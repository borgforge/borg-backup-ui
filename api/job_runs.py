"""Immutable, private start-time context for a backup run (#475).

The HTTP boundary creates this once. The runner never re-resolves an editable
job to obtain its sources, target, retention or runtime-control settings.
Only ``descriptors`` may be exposed in status/log responses.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from job_model import JobValidationError, validate_job, validate_job_id


def validate_run_id(value):
    try:
        return validate_job_id(value)
    except ValueError as exc:
        raise JobValidationError("invalid_run_id", "A canonical UUIDv4 run_id is required") from exc


def control_root():
    return Path(os.environ.get("BORG_UI_CONTROL_ROOT") or "/run/borg-backup-ui/jobs")


def log_filename(job_id, run_id, name):
    validate_job_id(job_id)
    validate_run_id(run_id)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name)).strip(".-_")[:48] or "job"
    return f"Borg-Backup_{slug}_{job_id[:8]}--{run_id}.log"


def descriptors(context):
    return {key: deepcopy(context[key]) for key in (
        "job_id", "run_id", "job_name_snapshot", "archive_prefix_snapshot",
        "archive_prefixes_snapshot", "repository_key_snapshot",
        "repository_snapshot", "location_snapshot", "started_at", "log_file", "file_activity",
    )}


def create_run_context(config, job_id, *, require_enabled=True):
    from config_api import read_expanded_conf
    from inventory_store import inventory_lock
    from job_actions import prepare_job_action
    from repository_context import jobs_dir, resolve_job_repository_context
    with inventory_lock(jobs_dir(config).parent):
        context = prepare_job_action(config, job_id, require_enabled=require_enabled)
        # Validate the credential reference before creating a run or subprocess.
        context = resolve_job_repository_context(config, job_id, job=context["job"])
        settings = read_expanded_conf(config)
        run_id = str(uuid4())
        payload = {
            "schema_version": 1, "job_id": job_id, "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "job_name_snapshot": context["name"],
            "archive_prefix_snapshot": context["archive_prefix"],
            "archive_prefixes_snapshot": context["archive_prefixes"],
            "repository_key_snapshot": context["repository_key"],
            "repository_snapshot": context["repository_path"],
            "location_snapshot": context["location"],
            "context": context, "settings": settings,
            "log_file": str(Path(settings.get("GLOBAL_LOG_DIR") or "/mnt/user/Logs") / log_filename(job_id, run_id, context["name"])),
            "file_activity": bool(context["job"].get("file_activity")),
        }
        validate_run_context(payload, job_id, run_id)
        directory = control_root() / run_id
        directory.mkdir(parents=True, mode=0o700)  # UUID collision never overwrites.
        path = directory / "context.json"
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        return deepcopy(payload)


def read_run_context(job_id, run_id):
    from job_store import read_json
    validate_job_id(job_id)
    validate_run_id(run_id)
    payload = read_json(control_root() / run_id / "context.json")
    return validate_run_context(payload, job_id, run_id)


def validate_run_context(payload, job_id, run_id):
    """Pure validation, also used by the migration's owned-record verifier."""
    validate_job_id(job_id)
    validate_run_id(run_id)
    if not isinstance(payload, dict):
        raise FileNotFoundError("Run context is not available")
    context = payload.get("context", {})
    if not isinstance(context, dict):
        raise ValueError("Run repository context is missing")
    if payload.get("schema_version") != 1 or payload.get("job_id") != job_id or payload.get("run_id") != run_id:
        raise JobValidationError("conflicting_run_identity", "Run context does not match the requested identity")
    job = context.get("job")
    validate_job(job)
    expected = {
        "job_id": job["job_id"], "job_name_snapshot": job["name"],
        "archive_prefix_snapshot": job["archive_prefixes"][0],
        "archive_prefixes_snapshot": job["archive_prefixes"],
        "repository_key_snapshot": job["repository_key"],
        "repository_snapshot": context.get("repository_path"),
        "location_snapshot": context.get("location"),
        "file_activity": bool(job.get("file_activity")),
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise JobValidationError("conflicting_run_identity", "Run snapshot descriptors are inconsistent")
    if not isinstance(payload.get("settings"), dict):
        raise ValueError("Run settings are missing")
    if type(payload.get("file_activity")) is not bool:
        raise ValueError("Run file-activity setting is invalid")
    path = payload.get("log_file")
    if (not isinstance(path, str) or not Path(path).is_absolute()
            or Path(path).name != log_filename(job_id, run_id, job["name"])):
        raise ValueError("Run log reference is invalid")
    return payload


def maintenance_context_unchanged(config, snapshot):
    """Do not prune an old target after it may have acquired another owner."""
    from job_actions import prepare_job_action
    try:
        current = prepare_job_action(config, snapshot["job_id"])
    except (ValueError, OSError):
        return False
    return (current["repository_key"] == snapshot["repository_key_snapshot"]
            and current["repository_path"] == snapshot["repository_snapshot"]
            and set(snapshot["archive_prefixes_snapshot"]).issubset(current["archive_prefixes"]))


def find_run_status(config, job_id, run_id=""):
    """Locate a finished run by payload identity, without filename inference."""
    validate_job_id(job_id)
    if run_id:
        validate_run_id(run_id)
    from wizard_runner import _ensure_runtime_import_paths
    _ensure_runtime_import_paths(Path(config["BACKUP_SCRIPTS_DIR"]))
    from lib.status import StatusStore
    directory = Path(config.get("STATUS_DIR") or "/mnt/user/backup-status")
    rows = [row for row in StatusStore(directory).load()
            if row.job_id == job_id and row.identity_state != "unassigned"
            and (not run_id or row.run_id == run_id)]
    if not rows:
        return {}
    status = max(rows, key=lambda row: (row.timestamp, row.run_id))
    return {"job_id": status.job_id, "run_id": status.run_id,
            "job_name_snapshot": status.job_name_snapshot,
            "running": False, "exit_code": status.exit_code,
            "phase": "skipped" if status.status == "skipped" else ("completed" if status.exit_code < 2 else status.status),
            "file_activity": status.file_activity, "log_file": status.log_file}
