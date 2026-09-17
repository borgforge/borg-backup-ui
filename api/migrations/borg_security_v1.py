"""Adopt Borg's volatile repository security records without replacing state."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from borg_environment import borg_security_dir, ensure_borg_security_dir, legacy_security_dir
from inventory_store import atomic_write_bytes, atomic_write_json, inventory_lock
from security_utils import mask_secrets

from .audit import append_event, config_dir, now, write_pending_state

MIGRATION_ID = "borg_security_v1"
INTRODUCED_IN = "2026.09.17.1618"


def _journal(config):
    return config_dir(config) / "borg-security-migration.json"


def _read_plan(config):
    path = _journal(config)
    if not path.exists():
        return None
    plan = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or plan.get("status") not in {"pending", "applied"}:
        raise ValueError("Invalid Borg security migration journal")
    return plan


def detect(config):
    plan = _read_plan(config)
    return {"required": plan is None or plan["status"] != "applied"}


def _records(directory: Path) -> dict[str, bytes]:
    if directory.is_symlink():
        raise ValueError(f"Symbolic link in Borg security state: {directory}")
    try:
        entries = sorted(directory.iterdir())
    except FileNotFoundError:
        return {}
    records = {}
    for repo in entries:
        if repo.is_symlink() or not repo.is_dir() or not re.fullmatch(r"[a-fA-F0-9]{64}", repo.name):
            raise ValueError(f"Unrecognized Borg security repository entry: {repo}")
        for path in sorted(repo.iterdir()):
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Non-regular Borg security record: {path}")
            records[f"{repo.name}/{path.name}"] = path.read_bytes()
    return records


def _digest(content):
    return hashlib.sha256(content).hexdigest()


def _preconditions(config):
    from jobs_api import active_resource_locks, durable_running_states

    if active_resource_locks(config) or durable_running_states(config):
        raise RuntimeError("Borg security migration requires backup and restore workers to finish; restart the plugin afterwards")
    return ensure_borg_security_dir(config)


def _plan(config, target):
    source = legacy_security_dir()
    if not source.is_absolute():
        raise ValueError("Legacy Borg security storage requires an absolute path")
    old = _records(source)
    existing = _records(target)
    # Validate the entire import before any live record is written. Different
    # timestamps/nonces are not resolved by mtime or blind overwrite.
    for relative, content in old.items():
        if relative in existing and existing[relative] != content:
            raise ValueError(f"Conflicting Borg security record; both copies preserved: {target / relative}")
    run_id = str(uuid4())
    stamp = now().replace("-", "").replace(":", "")
    backup = config_dir(config) / "migration-backups" / f"{MIGRATION_ID}-{stamp}-{run_id.replace('-', '')}"
    backup.mkdir(parents=True, mode=0o700)
    for category, records in (("source", old), ("destination", existing)):
        for relative, content in records.items():
            parent = (backup / category / relative).parent
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_write_bytes(backup / category / relative, content)
    plan = {
        "migration_id": MIGRATION_ID, "status": "pending", "timestamp": now(), "run_id": run_id,
        "source": str(source), "target": str(target), "backup_directory": str(backup),
        "source_missing": not source.exists(),
        "records": {relative: _digest(content) for relative, content in old.items()},
    }
    atomic_write_json(backup / "manifest.json", plan)
    atomic_write_json(_journal(config), plan)
    return plan


def _apply_records(plan):
    source, target = Path(plan["source"]), Path(plan["target"])
    records = plan["records"]
    # If a reboot removed the volatile source during an interrupted migration,
    # the durable snapshot is sufficient to resume. A changed source is not.
    if source != target and source.exists():
        if {name: _digest(value) for name, value in _records(source).items()} != records:
            raise ValueError("Borg security source changed during migration; copies preserved")
    existing = _records(target)
    pending = []
    for relative, digest in records.items():
        content = (Path(plan["backup_directory"]) / "source" / relative).read_bytes()
        if _digest(content) != digest:
            raise ValueError("Borg security migration snapshot verification failed")
        if relative in existing:
            if _digest(existing[relative]) != digest:
                raise ValueError(f"Conflicting Borg security record; both copies preserved: {target / relative}")
        else:
            pending.append((target / relative, content))
    for path, content in pending:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write_bytes(path, content)
    for relative, digest in records.items():
        if _digest((target / relative).read_bytes()) != digest:
            raise ValueError("Borg security destination verification failed")


def apply(config):
    with inventory_lock(config_dir(config)):
        plan = _read_plan(config)
        if plan and plan["status"] == "applied":
            return {"status": "not_required"}
        try:
            target = _preconditions(config)
            plan = plan or _plan(config, target)
            if Path(plan["target"]) != borg_security_dir(config):
                raise ValueError("Borg security destination changed during migration")
            write_pending_state(config, migration_id=MIGRATION_ID, introduced_in=INTRODUCED_IN,
                                run_id=plan["run_id"], source_classification="borg_security")
            append_event(config, {"event": "migration_started", **plan})
            print(f"[{now()}] Migration {MIGRATION_ID}: adopting {len(plan['records'])} security records into {target}", flush=True)
            _apply_records(plan)
            plan.update(status="applied", applied_at=now())
            atomic_write_json(Path(plan["backup_directory"]) / "manifest.json", plan)
            atomic_write_json(_journal(config), plan)
        except Exception as exc:
            append_event(config, {"event": "migration_failed", "migration_id": MIGRATION_ID,
                                  "error_type": type(exc).__name__, "error": mask_secrets(str(exc))})
            raise
        details = {
            "source": plan["source"], "target": plan["target"], "source_missing": plan["source_missing"],
            "affected_files": [str(target / name) for name in plan["records"]],
            "backup_directory": plan["backup_directory"], "imported": len(plan["records"]),
            "actions": ["Saved source and existing destination records in a snapshot",
                        "Copied missing security records without replacing existing files",
                        "Kept the legacy source unchanged"],
        }
        append_event(config, {"event": "migration_applied", "migration_id": MIGRATION_ID, **details})
        print(f"[{now()}] Migration {MIGRATION_ID}: applied; persistent Borg security storage is {target}", flush=True)
        return {"status": "applied", "details": details}
