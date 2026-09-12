"""Materialize effective settings before removing type dependencies (#495)."""

import copy
import hashlib
from pathlib import Path

from config_api import read_expanded_conf
from inventory_store import atomic_write_bytes, atomic_write_json, inventory_lock
from job_identity import metadata_job_id, new_job_id
from job_settings import DEFAULT_RETENTION, JOB_SETTINGS_SCHEMA, explicit_job_settings
from security_utils import mask_secrets

from .audit import append_event, config_dir, now, write_pending_state
from .job_ids_v1 import _apply_operation, _digest, _jobs, _paths, _preconditions, _read

MIGRATION_ID = "job_settings_v1"
INTRODUCED_IN = "2026.09.07.2355"
RECHECK_AFTER_FINAL = True

_ICONS = set("flash appdata photos vms sonstiges docker folder cloud archive database server home music video documents code camera usb shield".split())
_COLORS = set("blue indigo purple pink green lime violet amber orange red rose teal cyan gray".split())
_TYPE_COLORS = {"flash": "theme-blue", "appdata": "theme-orange", "photos": "theme-purple", "vms": "theme-green"}


def _journal(config):
    return config_dir(config) / "job-settings-migration.json"


def _needs_migration(meta):
    return int(meta.get("schema_version") or 0) < JOB_SETTINGS_SCHEMA


def detect(config):
    journal = _journal(config)
    pending = journal.is_file() and _read(journal).get("status") != "applied"
    return {"required": pending or any(_needs_migration(meta) for _, meta in _jobs(config))}


def materialize(meta, conf):
    result = copy.deepcopy(meta)
    metadata_job_id(result)
    backup_type = str(result.get("backup_type") or "").strip().lower()
    type_suffix = "".join(c if c.isalnum() else "_" for c in backup_type.upper())
    result["compression"] = str(result.get("compression") or "").strip() or conf.get(f"COMPRESSION_{type_suffix}", "lz4")
    retention = result.get("retention") if isinstance(result.get("retention"), dict) else {}
    result["retention"] = {
        **retention,
        **{period: str(retention.get(period) if retention.get(period) is not None else "").strip() or str(conf.get(f"RETENTION_{type_suffix}_{period.upper()}", default))
           for period, default in DEFAULT_RETENTION.items()},
    }
    if str(result.get("icon") or "").lower() not in _ICONS:
        result["icon"] = backup_type if backup_type in _ICONS else "sonstiges"
    if str(result.get("icon_color") or "").lower() not in _COLORS:
        result["icon_color"] = _TYPE_COLORS.get(backup_type, "")
    result.pop("backup_type", None)
    result.pop("type_id", None)
    result["schema_version"] = JOB_SETTINGS_SCHEMA
    explicit_job_settings(result)
    return result


def _plan(config):
    conf = read_expanded_conf(config)
    proposed = [(path, materialize(meta, conf)) for path, meta in _jobs(config) if _needs_migration(meta)]
    run_id = new_job_id()
    backup = config_dir(config) / "migration-backups" / f"{MIGRATION_ID}-{run_id}"
    backup.mkdir(parents=True, mode=0o700)
    operations = []
    import json
    for index, (path, meta) in enumerate(proposed):
        before, after = path.read_bytes(), (json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode()
        before_file, after_file = backup / f"{index}.before", backup / f"{index}.after"
        stat = path.stat()
        atomic_write_bytes(before_file, before)
        atomic_write_bytes(after_file, after)
        operations.append({
            "source": str(path), "target": str(path), "before": str(before_file), "after": str(after_file),
            "before_sha256": hashlib.sha256(before).hexdigest(), "after_sha256": hashlib.sha256(after).hexdigest(),
            "atime_ns": stat.st_atime_ns, "mtime_ns": stat.st_mtime_ns,
        })
    return {"migration_id": MIGRATION_ID, "status": "pending", "run_id": run_id,
            "timestamp": now(), "backup_directory": str(backup), "operations": operations}


def apply(config):
    with inventory_lock(config_dir(config)):
        _preconditions(config, _paths(config))
        journal = _journal(config)
        plan = _read(journal) if journal.is_file() else None
        if plan and plan.get("status") == "applied":
            if any(_needs_migration(meta) for _, meta in _jobs(config)):
                raise ValueError("Unsupported old job added after migration; create a new configuration export after upgrading the source installation")
            return {"status": "not_required"}
        if plan is None:
            if not detect(config)["required"]:
                return {"status": "not_required"}
            plan = _plan(config)
            atomic_write_json(journal, plan)
        write_pending_state(config, migration_id=MIGRATION_ID, introduced_in=INTRODUCED_IN,
                            run_id=plan["run_id"], source_classification="job_metadata")
        append_event(config, {"event": "migration_started", "migration_id": MIGRATION_ID,
                              "run_id": plan["run_id"], "backup_directory": plan["backup_directory"]})
        try:
            total = len(plan["operations"])
            for index, op in enumerate(plan["operations"], 1):
                print(f"[{now()}] Migration {MIGRATION_ID}: saving explicit job settings {index}/{total}", flush=True)
                _apply_operation(op)
                append_event(config, {"event": "migration_file_applied", "migration_id": MIGRATION_ID,
                                      "source": op["source"], "target": op["target"],
                                      "action": "materialize_settings_and_appearance"})
            for op in plan["operations"]:
                if _digest(Path(op["target"])) != op["after_sha256"]:
                    raise ValueError("Job settings migration verification failed")
                explicit_job_settings(_read(Path(op["target"])))
            plan.update(status="applied", applied_at=now())
            atomic_write_json(journal, plan)
        except Exception as exc:
            append_event(config, {"event": "migration_failed", "migration_id": MIGRATION_ID,
                                  "error_type": type(exc).__name__, "error": mask_secrets(str(exc))})
            raise
        details = {"affected_files": [op["target"] for op in plan["operations"]],
                   "backup_directory": plan["backup_directory"],
                   "actions": ["Preserved original job metadata", "Saved effective settings, icons and colors", "Removed obsolete job type fields"]}
        append_event(config, {"event": "migration_applied", "migration_id": MIGRATION_ID, **details})
        return {"status": "applied", "details": details}
