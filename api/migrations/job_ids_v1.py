"""Enrich Main records with permanent job IDs, preserving their payloads (#486)."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path

from inventory_store import atomic_write_bytes, atomic_write_json, inventory_lock
from job_identity import metadata_job_id, new_job_id, validate_job_id
from security_utils import mask_secrets

from .audit import append_event, config_dir, now, write_pending_state

MIGRATION_ID = "job_ids_v1"
INTRODUCED_IN = "2026.09.07.1400"
RECHECK_AFTER_FINAL = True


def _read(path: Path):
    if path.is_symlink():
        raise ValueError(f"Migration input must not be a symlink: {path}")
    try:
        return json.loads(path.read_bytes())
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Invalid migration JSON: {path}") from exc


def _journal(config: dict) -> Path:
    return config_dir(config) / "job-id-migration.json"


def _jobs(config: dict) -> list[tuple[Path, dict]]:
    rows = []
    seen = set()
    for path in sorted((config_dir(config) / "jobs").glob("*.json")):
        data = _read(path)
        if not isinstance(data, dict):
            raise ValueError(f"Job metadata must be an object: {path}")
        key = str(data.get("job_key") or "")
        if not key or key != path.stem or key in seen:
            raise ValueError(f"Job filename/key conflict: {path}")
        if data.get("job_id"):
            metadata_job_id(data)
        elif (key != f"{data.get('backup_type', '')}_{data.get('location', '')}"
              or not re.fullmatch(r"[A-Za-z0-9_]+", str(data.get("backup_type") or ""))):
            raise ValueError(f"Ambiguous legacy job identity: {path}")
        seen.add(key)
        rows.append((path, data))
    return rows


def detect(config: dict) -> dict:
    journal = _journal(config)
    pending = journal.is_file() and _read(journal).get("status") != "applied"
    required = pending or any(not data.get("job_id") for _, data in _jobs(config))
    return {"required": required, "migration_id": MIGRATION_ID}


def _paths(config: dict) -> dict:
    # Read canonical runtime paths before normal startup applies them to the UI.
    from config_api import read_expanded_conf
    effective = dict(config)
    canonical = read_expanded_conf(config)
    for key in ("STATUS_DIR", "RESTORE_TEST_STATUS_DIR", "GLOBAL_BORG_CACHE_BASE"):
        if canonical.get(key):
            effective[key] = canonical[key]
    from restore_tests_api import resolve_restore_test_dir
    status = Path(effective.get("STATUS_DIR", "/mnt/user/backup-status"))
    return {
        "status": status,
        "archive": Path(effective.get("STATUS_ARCHIVE_DIR") or status / "archive"),
        "restore": resolve_restore_test_dir(effective),
        "weekly": Path(effective.get("SNAPSHOT_FILE") or status.parent / "weekly-snapshots.json"),
        "legacy_weekly": status / "weekly-snapshots.json",
        "cache": Path(effective.get("GLOBAL_BORG_CACHE_BASE") or "/mnt/cache/borg-cache"),
    }


def _preconditions(config: dict, paths: dict) -> None:
    from jobs_api import active_resource_locks, durable_running_states
    from status import status_storage_unavailable_reason
    if active_resource_locks(config) or durable_running_states(config):
        raise RuntimeError("Job ID migration requires backup and restore workers to finish; restart the plugin afterwards")
    for path in paths.values():
        reason = status_storage_unavailable_reason(path)
        if reason:
            raise RuntimeError(f"Job ID migration storage unavailable: {reason}")
        if not path.is_absolute():
            raise ValueError("Job ID migration requires absolute configured paths")


def _plan(config: dict, paths: dict) -> dict:
    rows = _jobs(config)
    assignment = {data["job_key"]: data.get("job_id") or new_job_id() for _, data in rows}
    if len(set(assignment.values())) != len(assignment):
        raise ValueError("Duplicate active job IDs")
    for job_id in assignment.values():
        validate_job_id(job_id)
    root = config_dir(config)
    run_id = new_job_id()
    snapshot = root / "migration-backups" / f"{MIGRATION_ID}-{run_id}"
    operations = []
    unresolved = []

    def resolve(key, path, *, strict=False):
        if key in assignment:
            return assignment[key]
        if key in assignment.values():
            return key
        if key:
            if strict:
                raise ValueError(f"Unresolved active job reference in {path}")
            unresolved.append({"file": str(path), "code": "unresolved_historical_job",
                               "reference": mask_secrets(str(key))})
        return key

    def add(path, data, target=None):
        before = path.read_bytes()
        after = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
        target = target or path
        if _read(path) == data and path == target:
            return
        if target != path and target.exists():
            raise ValueError(f"Migration target already exists: {target}")
        stat = path.stat()
        operations.append((path, target, before, after, stat.st_atime_ns, stat.st_mtime_ns))

    def refs(value, path):
        if isinstance(value, list):
            return [refs(item, path) for item in value]
        if not isinstance(value, dict):
            return value
        out = {key: refs(item, path) for key, item in value.items()}
        if out.get("job_key"):
            out["job_key"] = resolve(out["job_key"], path)
        return out

    # Preserve every job field. backup_type remains an operational/default value.
    migrated_jobs = []
    for path, data in rows:
        migrated = copy.deepcopy(data)
        job_id = assignment[data["job_key"]]
        migrated.update(job_id=job_id, job_key=job_id)
        migrated["schema_version"] = 4
        migrated.setdefault("cache_subdir", f"{data['location']}_{str(data['backup_type']).lower()}")
        migrated.setdefault("check_flag_name", f".last_check_{str(data['backup_type']).lower()}")
        migrated.setdefault("archive_prefix", f"{str(data['backup_type']).lower()}-backup")
        if not isinstance(migrated.get("archive_prefixes", []), list):
            raise ValueError(f"Invalid archive prefix list: {path}")
        migrated["archive_prefixes"] = list(dict.fromkeys([
            migrated["archive_prefix"], *migrated.get("archive_prefixes", []),
        ]))
        add(path, migrated, path.with_name(f"{job_id}.json"))
        migrated_jobs.append(migrated)
    from archive_prefix import validate_prefix_ownership
    for migrated in migrated_jobs:
        validate_prefix_ownership(migrated, migrated_jobs)

    path = root / "schedules.json"
    if path.is_file():
        data = _read(path)
        out = {}
        for key, value in data.items():
            new_key = key if key == "restore_test" else resolve(key, path, strict=True)
            if new_key in out:
                raise ValueError("Conflicting job schedules")
            out[new_key] = value
        add(path, out)

    path = root / "repositories.json"
    if rows and not path.is_file():
        raise ValueError("Active jobs require the canonical repository inventory")
    if path.is_file():
        data = _read(path)
        repositories = {repo["repository_key"]: repo for repo in data["repositories"]}
        job_repositories = {job["job_key"]: job.get("repository_key") for _, job in rows}
        if any(key not in repositories for key in job_repositories.values()):
            raise ValueError("Active job references an unknown repository")
        for repo in data["repositories"]:
            if any(key in job_repositories and job_repositories[key] != repo["repository_key"]
                   for key in repo.get("used_by", [])):
                raise ValueError("Conflicting active repository/job reference")
            for field in ("used_by", "source_job_keys"):
                if field in repo:
                    repo[field] = [resolve(key, path, strict=field == "used_by") for key in repo[field]]
        add(path, data)

    def historical_identity(data, path, primary):
        # Conflicting evidence must not attach old results to the wrong job.
        owner = assignment.get(primary, primary)
        hints = [data.get("job_key"), data.get("job_id")]
        conflict = any(assignment.get(hint, hint) != owner for hint in hints if hint)
        active = next((job for _, job in rows if assignment[job["job_key"]] == owner), None)
        if active:
            backup_type = data.get("backup_type") or data.get("type")
            conflict = conflict or bool(backup_type and backup_type != active.get("backup_type"))
            conflict = conflict or bool(data.get("location") and data["location"] != active.get("location"))
        if conflict:
            unresolved.append({"file": str(path), "code": "conflicting_historical_identity"})
            return ""
        return resolve(primary, path)

    for directory in set([paths["status"], paths["archive"]]):
        for path in sorted(directory.glob("*.status")):
            data = _read(path)
            old = str(data.get("job_key") or f"{data.get('backup_type', '')}_{data.get('location', '')}")
            job_id = historical_identity(data, path, old)
            if job_id in assignment.values():
                if data.get("job_id") and data["job_id"] != job_id:
                    raise ValueError(f"Conflicting status job ID: {path}")
                data["job_id"] = job_id
                if "job_key" in data:
                    data["job_key"] = job_id
                add(path, data)

    for path in sorted(paths["restore"].glob("*.test")):
        data = _read(path)
        job_id = historical_identity(data, path, path.stem)
        if job_id in assignment.values():
            if data.get("job_id") and data["job_id"] != job_id:
                raise ValueError(f"Conflicting restore-test job ID: {path}")
            data["job_id"] = job_id
            if "job_key" in data:
                data["job_key"] = job_id
            add(path, data, path.with_name(f"{job_id}.test"))

    for path in set([paths["weekly"], paths["legacy_weekly"]]):
        if path.is_file():
            data = _read(path)
            out = {}
            for key, value in data.items():
                new_key = resolve(key, path)
                if new_key in out:
                    raise ValueError(f"Conflicting weekly observations: {path}")
                out[new_key] = value
            add(path, out)

    for path in [root / name for name in (
        "restore-runs.json", "notification-queue.json", "notification-deliveries.json",
        "restore-history/index.json",
    )] + sorted((root / "restore-history/runs").glob("*.json")):
        if path.is_file():
            add(path, refs(_read(path), path))

    path = root / "runtime-recovery.json"
    if path.is_file():
        data = refs(_read(path), path)
        for entry in data.get("entries", []):
            old = str(entry.get("job_key") or f"{entry.get('backup_type', '')}_{entry.get('backup_location', '')}")
            job_id = resolve(old, path)
            if job_id in assignment.values():
                entry["job_id"] = job_id
        add(path, data)

    path = root / "notification-state.json"
    if path.is_file():
        data = _read(path)
        sent = {}
        for key, value in data.get("last_sent", {}).items():
            parts = key.split(":", 2)
            if len(parts) == 3:
                parts[1] = resolve(parts[1], path)
            new_key = ":".join(parts)
            if new_key in sent:
                raise ValueError("Conflicting reminder state")
            sent[new_key] = value
        data["last_sent"] = sent
        add(path, data)

    # Stage complete originals and proposed bytes before publishing the plan.
    # No affected input is changed until this durable plan owns the UUIDs.
    snapshot.mkdir(parents=True, mode=0o700)
    entries = []
    for index, (source, target, before, after, atime, mtime) in enumerate(operations):
        before_file = snapshot / f"{index}.before"
        after_file = snapshot / f"{index}.after"
        atomic_write_bytes(before_file, before)
        atomic_write_bytes(after_file, after)
        entries.append({
            "source": str(source), "target": str(target),
            "before": str(before_file), "after": str(after_file),
            "before_sha256": hashlib.sha256(before).hexdigest(),
            "after_sha256": hashlib.sha256(after).hexdigest(),
            "atime_ns": atime, "mtime_ns": mtime,
        })
    return {"migration_id": MIGRATION_ID, "status": "pending", "run_id": run_id,
            "timestamp": now(), "assignment": assignment, "operations": entries,
            "unresolved": unresolved, "backup_directory": str(snapshot)}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _apply_operation(op: dict) -> None:
    source, target = Path(op["source"]), Path(op["target"])
    before, after = op["before_sha256"], op["after_sha256"]
    staged = Path(op["after"])
    if _digest(staged) != after or _digest(Path(op["before"])) != before:
        raise ValueError("Migration snapshot checksum mismatch")
    source_hash, target_hash = _digest(source), _digest(target)
    if source == target:
        if source_hash not in (before, after):
            raise ValueError(f"Migration input changed since snapshot: {source}")
    elif source_hash not in ("", before) or target_hash not in ("", after) or not (source_hash or target_hash):
        raise ValueError(f"Migration rename conflicts with changed data: {source}")
    if target_hash != after:
        atomic_write_bytes(target, staged.read_bytes())
    os.utime(target, ns=(op["atime_ns"], op["mtime_ns"]))
    if source != target and source.exists():
        source.unlink()
        fd = os.open(source.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def apply(config: dict) -> dict:
    with inventory_lock(config_dir(config)):
        paths = _paths(config)
        _preconditions(config, paths)
        journal = _journal(config)
        plan = _read(journal) if journal.is_file() else None
        if plan and plan.get("status") == "applied":
            if any(not data.get("job_id") for _, data in _jobs(config)):
                raise ValueError("Unmigrated job added after migration; use the job import API")
            return {"status": "not_required"}
        if not plan:
            plan = _plan(config, paths)
            atomic_write_json(journal, plan)
        write_pending_state(config, migration_id=MIGRATION_ID, introduced_in=INTRODUCED_IN,
                            run_id=plan["run_id"], source_classification="main_job_metadata")
        append_event(config, {"event": "migration_started", "migration_id": MIGRATION_ID,
                              "run_id": plan["run_id"], "backup_directory": plan["backup_directory"]})
        try:
            for op in plan["operations"]:
                _apply_operation(op)
                append_event(config, {"event": "migration_file_applied", "migration_id": MIGRATION_ID,
                                      "source": op["source"], "target": op["target"],
                                      "action": "enrich_job_identity"})
            for op in plan["operations"]:
                if _digest(Path(op["target"])) != op["after_sha256"]:
                    raise ValueError("Job ID migration verification failed")
            _jobs(config)
            plan.update(status="applied", applied_at=now())
            atomic_write_json(journal, plan)
        except Exception as exc:
            append_event(config, {"event": "migration_failed", "migration_id": MIGRATION_ID,
                                  "error_type": type(exc).__name__, "error": mask_secrets(str(exc))})
            raise
        details = {"affected_files": [op["target"] for op in plan["operations"]],
                   "backup_directory": plan["backup_directory"], "job_count": len(plan["assignment"]),
                   "unresolved_history": plan["unresolved"],
                   "actions": ["Preserved originals", "Assigned permanent job IDs", "Updated job references"]}
        append_event(config, {"event": "migration_applied", "migration_id": MIGRATION_ID, **details})
        return {"status": "applied", "details": details}
