"""Explicit schema-v4 job transfer plans and atomic application (#447, #478).

Source IDs select bundle objects; only an explicit target selects a live job.
Historical records belong to full configuration recovery, never a new job copy.
"""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from inventory_store import inventory_lock
from job_model import JobValidationError, validate_job, validate_job_inventory, validate_job_id
from job_store import read_jobs, read_json, read_repositories, validate_assignments, write_transaction
from repository_context import jobs_dir, resolve_job_repository_context
from schedule_api import validate_schedules, schedule_lines

FORMAT = "bbui-job-bundle-v3"


def fail(code, message):
    raise JobValidationError(code, message)


def decode_json(text):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                fail("invalid_transfer_bundle", "Duplicate JSON members are not supported")
            out[key] = value
        return out
    try:
        if len(text) > 64 * 1024 * 1024:
            raise ValueError()
        return json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda _: fail("invalid_transfer_bundle", "Invalid JSON constant"))
    except (ValueError, UnicodeError, RecursionError):
        fail("invalid_transfer_bundle", "The transfer file is invalid or too large")


def indexed(rows, key):
    if not isinstance(rows, list):
        fail("invalid_transfer_bundle", "An inventory list is missing")
    result = {}
    for row in rows:
        value = row.get(key) if isinstance(row, dict) else None
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in {".", ".."} or value in result:
            fail("invalid_transfer_bundle", "Invalid or duplicate inventory identifier")
        result[value] = deepcopy(row)
    return result


def reference_map(bundle):
    return {"schema_version": 1, "jobs": {
        job["job_id"]: {"repository_key": job["repository_key"],
                       "scheduled": job["job_id"] in bundle["schedules"]}
        for job in bundle["jobs"]
    }, "repositories": {row["repository_key"]: {"storage_key": row["storage_key"],
                           "job_ids": sorted(row["job_ids"])} for row in bundle["repositories"]}}


def validate_bundle(bundle):
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT:
        fail("job_transfer_upgrade_required", "This operation requires a v3 job export from a migrated installation. Keep older backups for explicit configuration migration.")
    allowed = {"format", "exported_at", "jobs", "repositories", "storages", "schedules", "references", "passphrase_meta", "keyfile_meta"}
    if set(bundle) - allowed:
        fail("unsupported_transfer_dependency", "The bundle includes unsupported dependent objects; nothing was written")
    jobs = indexed(bundle.get("jobs"), "job_id")
    validate_job_inventory(jobs)
    repositories = indexed(bundle.get("repositories"), "repository_key")
    storages = indexed(bundle.get("storages"), "storage_key")
    validate_assignments(jobs, {"repositories": list(repositories.values())})
    validate_schedules(bundle.get("schedules"), jobs)
    if "restore_test" in bundle["schedules"]:
        fail("unsupported_transfer_dependency", "Service schedules require full configuration recovery")
    required_repos = {row["repository_key"] for row in jobs.values()}
    if set(repositories) != required_repos or {row.get("storage_key") for row in repositories.values()} != set(storages):
        fail("invalid_transfer_references", "Bundle dependencies are missing or outside the selected jobs")
    if any(row.get("schema_version", 1) != 1 for row in [*repositories.values(), *storages.values()]):
        fail("invalid_transfer_bundle", "Unsupported inventory schema")
    if bundle.get("references") != reference_map(bundle):
        fail("invalid_transfer_references", "The job reference map is incomplete or inconsistent")
    return jobs, repositories, storages


def export_bundle(config, selected_ids=None):
    root = jobs_dir(config).parent
    with inventory_lock(root):
        jobs = read_jobs(root / "jobs")
        repos = read_repositories(root / "repositories.json")
        validate_assignments(jobs, repos)
        schedules = validate_schedules(read_json(root / "schedules.json", missing={}), jobs)
        selected = set(jobs if selected_ids is None else selected_ids)
        if selected - jobs.keys():
            fail("unknown_job_id", "The selection includes an unknown job_id")
        repositories = [deepcopy(row) for row in repos["repositories"] if any(jobs[j]["repository_key"] == row["repository_key"] for j in selected)]
        for row in repositories:
            for field in ("job_ids", "source_job_ids"):
                row[field] = [job_id for job_id in row[field] if job_id in selected]
        storage_keys = {row["storage_key"] for row in repositories}
        storages = read_json(root / "storages.json", missing={"schema_version": 1, "storages": []})
        bundle = {"format": FORMAT, "jobs": [jobs[j] for j in sorted(selected)], "repositories": repositories,
                  "storages": [row for row in storages["storages"] if row["storage_key"] in storage_keys],
                  "schedules": {j: row for j, row in schedules.items() if j in selected}}
        bundle["references"] = reference_map(bundle)
        validate_bundle(bundle)
        return bundle


def preview_bundle(config, bundle):
    jobs, repos, storages = validate_bundle(bundle)
    current = read_jobs(jobs_dir(config))
    rows = []
    for job_id, job in jobs.items():
        repo = repos[job["repository_key"]]
        rows.append({"job_id": job_id, "name": job["name"][:200], "archive_prefix": job["archive_prefixes"][0],
                     "repository_key": job["repository_key"], "features": job.get("features", {}),
                     "schedule": bundle["schedules"].get(job_id, {}), "conflict": "exists" if job_id in current else "new",
                     "suggested_mode": "new", "repository": {"display_name": repo.get("display_name", repo["repository_key"]),
                     "repository_key": repo["repository_key"], "path": repo.get("relative_path", "")},
                     "passphrase": {"status": "present" if bundle.get("passphrase_meta", {}).get(repo["repository_key"], {}).get("exists") else "missing"}})
    return {"format": FORMAT, "job_count": len(rows), "jobs": rows,
            "current_jobs": [{"job_id": j, "name": job["name"][:200], "repository_key": job["repository_key"]} for j, job in current.items()]}


def _compatible(current, incoming, fields):
    def value(row, key):
        item = row.get(key)
        return '' if item is None else item
    return all(value(current, key) == value(incoming, key) for key in fields)


def plan_import(config, bundle, *, mode="new", selected_jobs=None, per_job_mode=None,
                target_jobs=None, archive_prefixes=None, import_jobs=True, secret_payload=None):
    source, source_repos, source_storages = validate_bundle(bundle)
    root = jobs_dir(config).parent
    jobs = read_jobs(root / "jobs")
    repos_store = read_repositories(root / "repositories.json")
    validate_assignments(jobs, repos_store)
    storage_store = read_json(root / "storages.json", missing={"schema_version": 1, "storages": []})
    repos = indexed(repos_store["repositories"], "repository_key")
    storages = indexed(storage_store["storages"], "storage_key")
    schedules = validate_schedules(read_json(root / "schedules.json", missing={}), jobs)
    old_lines = schedule_lines(config, schedules, jobs)
    selected = set(source if selected_jobs is None else selected_jobs)
    if selected - source.keys():
        fail("unknown_job_id", "Selection refers to jobs outside the bundle")
    modes, targets, prefixes = per_job_mode or {}, target_jobs or {}, archive_prefixes or {}
    for mapping in (modes, targets, prefixes):
        if not isinstance(mapping, dict) or set(mapping) - selected:
            fail("invalid_transfer_selection", "Import choices must reference selected source IDs")
    if mode not in {"new", "merge", "skip"}:
        fail("invalid_transfer_mode", "Choose new, merge with an explicit target, or skip")
    result_jobs, changes, remap, report, selected_repos = deepcopy(jobs), {}, {}, [], set()
    for source_id, raw in source.items():
        action = modes.get(source_id, mode)
        if source_id not in selected or action == "skip":
            report.append({"job_id": source_id, "status": "skipped_unselected" if source_id not in selected else "skipped"})
            continue
        if action not in {"new", "merge"}:
            fail("invalid_transfer_mode", "Choose new or an explicitly selected merge target")
        if action == "new":
            if source_id in targets or not import_jobs:
                fail("explicit_import_target_required", "Secret-only imports require an explicitly selected existing target job")
            target_id = str(uuid4())
            if target_id in jobs:
                fail("duplicate_job_id", "Allocated job_id already exists")
            patched = deepcopy(raw)
            patched["legacy_job_keys"] = []
            patched.pop("cache_reference", None)
        else:
            target_id = validate_job_id(targets.get(source_id))
            if target_id not in jobs:
                fail("unknown_job_id", "The selected merge target no longer exists")
            patched = {**deepcopy(jobs[target_id]), **deepcopy(raw)}
            patched["legacy_job_keys"] = deepcopy(jobs[target_id]["legacy_job_keys"])
            patched.pop("cache_reference", None)
            if "cache_reference" in jobs[target_id]:
                patched["cache_reference"] = deepcopy(jobs[target_id]["cache_reference"])
            if not import_jobs and raw["repository_key"] != jobs[target_id]["repository_key"]:
                fail("invalid_transfer_target", "Secret-only import must target a job using the same repository")
        if target_id in remap.values():
            fail("duplicate_transfer_target", "Each source job needs a distinct target")
        remap[source_id] = target_id
        patched["job_id"] = target_id
        if source_id in prefixes:
            patched["archive_prefixes"] = [prefixes[source_id]]
        if action == "merge":
            patched["archive_prefixes"] = list(dict.fromkeys([*patched["archive_prefixes"], *jobs[target_id]["archive_prefixes"]]))
        validate_job(patched)
        if import_jobs:
            result_jobs[target_id] = patched
            changes[root / "jobs" / (target_id + ".json")] = patched
            if source_id in bundle["schedules"]:
                schedules[target_id] = deepcopy(bundle["schedules"][source_id])
        selected_repos.add(raw["repository_key"])
        report.append({"job_id": source_id, "target_job_id": target_id, "status": action if import_jobs else "secrets", "name": patched["name"]})
    for key in selected_repos:
        incoming = source_repos[key]
        storage_key = incoming["storage_key"]
        storage = source_storages[storage_key]
        if storage_key in storages and not _compatible(storages[storage_key], storage, (
                "storage_type", "location", "identity", "base_path", "mount_path", "host", "user", "port", "server", "share")):
            fail("transfer_storage_collision", "A storage identifier refers to a different target")
        storages.setdefault(storage_key, deepcopy(storage))
        if key in repos:
            if not _compatible(repos[key], incoming, ("storage_key", "relative_path", "encryption", "borg_repository_id")):
                fail("transfer_repository_collision", "A repository identifier refers to a different repository")
        else:
            repo = deepcopy(incoming)
            repo.pop("keyfile_ref", None)
            # Imported host paths never select write destinations.
            if repo.get("passphrase_ref"):
                repo["passphrase_ref"] = str(root.parent / "secrets" / (".borg-passphrase-" + key))
            repos[key] = repo
    validate_job_inventory(result_jobs)
    for repo in repos.values():
        expected = [j for j, raw in result_jobs.items() if raw["repository_key"] == repo["repository_key"]]
        repo["job_ids"] = expected
        repo["source_job_ids"] = expected[:]
    next_repos = {**repos_store, "repositories": list(repos.values())}
    validate_assignments(result_jobs, next_repos)
    inventory = {"repositories": repos, "storages": storages}
    for target_id in remap.values():
        resolve_job_repository_context(config, target_id, job=result_jobs[target_id], inventory=inventory, require_passphrase_file=False)
    secret_counts = plan_secrets(config, secret_payload, selected_repos, repos, changes) if secret_payload is not None else {}
    if remap:
        changes[root / "repositories.json"] = next_repos
        changes[root / "storages.json"] = {**storage_store, "storages": list(storages.values())}
        changes[root / "schedules.json"] = schedules
    return {"changes": changes, "old_lines": old_lines, "new_lines": schedule_lines(config, schedules, result_jobs),
            "result": {"report": report, "id_map": remap, "imported_count": len(remap) if import_jobs else 0,
                       "scheduled_count": sum(j in bundle["schedules"] for j in remap) if import_jobs else 0,
                       "repository_inventory": {"repositories": len(selected_repos), "storages": len({repos[r]['storage_key'] for r in selected_repos})},
                       **secret_counts}}


def secret_bytes(row):
    if not isinstance(row, dict):
        fail("invalid_transfer_secret", "Malformed protected file")
    try:
        content = base64.b64decode(row["content_b64"], validate=True)
        if not content or len(content) > 1024 * 1024 or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError()
        return content
    except (ValueError, KeyError, TypeError):
        fail("invalid_transfer_secret", "Protected file content or digest is invalid")


def plan_secrets(config, payload, selected_repos, repositories, changes):
    from borg_key_store import borg_keys_dir, find_key_file
    from migrations.identity_storage import read_fingerprinted_file
    counts = {"restored_passphrases": 0, "restored_keyfiles": 0}
    for collection, count in (("passphrase_files", "restored_passphrases"), ("key_files", "restored_keyfiles")):
        files = payload.get(collection, {})
        if not isinstance(files, dict):
            fail("invalid_transfer_secret", "Invalid protected file collection")
        for key, row in files.items():
            if collection == "key_files" and isinstance(row, dict) and row.get("exists") is False:
                continue
            content = secret_bytes(row)  # Validate the complete included payload before any writes.
            if key not in selected_repos:
                continue
            repo = repositories[key]
            if collection == "passphrase_files":
                target = Path(repo.get("passphrase_ref") or jobs_dir(config).parent.parent / "secrets" / (".borg-passphrase-" + key))
                repo["passphrase_ref"] = str(target)
            else:
                repository_id = repo.get("borg_repository_id", "")
                if not re.fullmatch(r"[0-9a-f]{64}", repository_id) or row.get("repository_id") != repository_id or content.splitlines()[0] != ("BORG_KEY " + repository_id).encode():
                    fail("invalid_transfer_secret", "Borg key repository identity does not match")
                target = find_key_file(borg_keys_dir(config), repository_id) or borg_keys_dir(config) / ("bbui-" + repository_id)
                repo["keyfile_ref"] = str(target)
            old = read_fingerprinted_file(target)[1]
            if old is not None and old != content:
                fail("transfer_secret_collision", "A protected file differs from the existing file; restore it through the explicit secrets workflow")
            if target in changes and changes[target] != content:
                fail("transfer_secret_collision", "Two repositories refer to conflicting protected files")
            changes[target] = content
            counts[count] += 1
    return counts


def apply_import(config, bundle, *, dry_run=True, **choices):
    from schedule_api import _update_crontab
    with inventory_lock(jobs_dir(config).parent):
        plan = plan_import(config, bundle, **choices)
        if not dry_run and plan["changes"]:
            write_transaction(plan["changes"], after_write=lambda: _update_crontab(plan["new_lines"]),
                              rollback_after=lambda: _update_crontab(plan["old_lines"]))
        return {**plan["result"], "dry_run": bool(dry_run)}
