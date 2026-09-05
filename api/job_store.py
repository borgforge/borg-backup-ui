"""Strict schema-v4 metadata persistence for the #447 cutover (#473).

No legacy discovery, conversion, reconciliation, or scheduler side effects.
Repository-wide readers/writers are converted in #474 before installation.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from inventory_store import atomic_write_bytes, atomic_write_json, inventory_lock
from job_model import JobValidationError, validate_job, validate_job_id, validate_job_inventory
from migrations.identity_storage import inventory_group, read_fingerprinted_file


def read_json(path, *, missing=None):
    """Read a regular file without following symlinks or accepting duplicate keys."""
    _, raw = read_fingerprinted_file(Path(path))
    if raw is None:
        return deepcopy(missing)

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate member")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("invalid constant")

    try:
        if len(raw) > 64 * 1024 * 1024:
            raise ValueError("too large")
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
        if not isinstance(value, dict):
            raise ValueError("not an object")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise JobValidationError("invalid_job_inventory", "An owned inventory file is malformed; no changes were made") from None


def job_revision(meta):
    return hashlib.sha256(json.dumps(meta, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def read_jobs(jobs_dir):
    result = {}
    for name in inventory_group(Path(jobs_dir), [".json"])["entries"]:
        meta = read_json(Path(jobs_dir) / name)
        validate_job(meta, filename=name)
        result[meta["job_id"]] = meta
    validate_job_inventory(result)
    return result


def read_job(jobs_dir, job_id):
    validate_job_id(job_id)
    # Validate the inventory as a whole: another ambiguous owner is not safe.
    jobs = read_jobs(jobs_dir)
    if job_id not in jobs:
        raise JobValidationError("unknown_job_id", "Unknown job_id; editing cannot create a job")
    return jobs[job_id]


def read_repositories(path):
    store = read_json(path, missing={"schema_version": 1, "repositories": []})
    if type(store.get("schema_version")) is not int or store["schema_version"] != 1 or not isinstance(store.get("repositories"), list):
        raise JobValidationError("invalid_job_repository", "Unsupported repository inventory")
    keys = set()
    for row in store["repositories"]:
        if not isinstance(row, dict) or not isinstance(row.get("repository_key"), str) or not row["repository_key"] or row["repository_key"] in keys:
            raise JobValidationError("invalid_job_repository", "Invalid or duplicate repository entry")
        keys.add(row["repository_key"])
    return store


def validate_assignments(jobs, store):
    keys = {row["repository_key"] for row in store["repositories"]}
    if any(job["repository_key"] not in keys for job in jobs.values()):
        raise JobValidationError("invalid_job_repository", "A job references a missing repository")
    for repo in store["repositories"]:
        if {"used_by", "source_job_keys"}.intersection(repo):
            raise JobValidationError("job_migration_required", "Repository assignments require the explicit identity migration")
        expected = {job_id for job_id, job in jobs.items() if job["repository_key"] == repo["repository_key"]}
        for field in ("job_ids", "source_job_ids"):
            values = repo.get(field)
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values) or set(values) != expected:
                raise JobValidationError("conflicting_job_assignments", "Repository assignments do not match job metadata")


def save_job_transaction(jobs_dir, repository_path, build, *, source_id=None, expected_revision=None, duplicate=False):
    """Serialize read/validate/patch/write; roll back ordinary I/O failures.

    Each replacement is durable, but the pair is not crash-atomic. A crash
    between replacements leaves inconsistent assignments which strict readers
    reject, never reconcile silently. The global cutover gate is owned by #479.
    """
    jobs_dir, repository_path = Path(jobs_dir), Path(repository_path)
    with inventory_lock(repository_path.parent):
        jobs = read_jobs(jobs_dir)
        store = read_repositories(repository_path)
        validate_assignments(jobs, store)
        existing = None
        if source_id is not None:
            validate_job_id(source_id)
            existing = jobs.get(source_id)
            if existing is None:
                raise JobValidationError("unknown_job_id", "Unknown job_id; editing cannot create a job")
            if expected_revision is not None and job_revision(existing) != expected_revision:
                raise JobValidationError("job_edit_conflict", "The job changed since it was opened; reload before saving")
        metadata = build(deepcopy(existing))
        validate_job(metadata)
        job_id = metadata["job_id"]
        fresh = source_id is None or duplicate
        if fresh and job_id in jobs:
            raise JobValidationError("duplicate_job_id", "Allocated job_id already exists")
        if not fresh and source_id != job_id:
            raise JobValidationError("immutable_job_id", "Editing cannot change job_id")
        if metadata["legacy_job_keys"] != ([] if fresh else existing["legacy_job_keys"]):
            raise JobValidationError("immutable_job_aliases", "Ordinary saves cannot add or change legacy aliases")
        jobs[job_id] = metadata
        validate_job_inventory(jobs)
        next_store = deepcopy(store)
        for repo in next_store["repositories"]:
            # Only update the affected ID; retain ordering and unknown fields.
            for field in ("job_ids", "source_job_ids"):
                values = repo[field]
                if repo["repository_key"] == metadata["repository_key"]:
                    if job_id not in values:
                        values.append(job_id)
                elif job_id in values:
                    values.remove(job_id)
        validate_assignments(jobs, next_store)
        target = jobs_dir / (job_id + ".json")
        _, before_job = read_fingerprinted_file(target)
        _, before_repos = read_fingerprinted_file(repository_path)
        try:
            atomic_write_json(target, metadata)
            if next_store != store:
                atomic_write_json(repository_path, next_store)
        except Exception:
            # Never turn a failed transaction into success. If rollback itself
            # fails, inconsistent inputs remain detectable by strict readers.
            if before_job is None:
                target.unlink(missing_ok=True)
            else:
                atomic_write_bytes(target, before_job)
            if before_repos is not None:
                atomic_write_bytes(repository_path, before_repos)
            raise
        return metadata, target
