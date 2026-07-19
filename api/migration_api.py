"""Migration status and diagnostics for the canonical startup registry."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def _config_dir(ui_config: dict) -> Path:
    return Path(str(ui_config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup/scripts"))) / "config"


def _read_migration_state(config_dir: Path) -> Dict[str, Any]:
    state_file = config_dir / "migration-state.json"
    if not state_file.exists():
        return {}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def analyze_backup_conf_state(ui_config: dict) -> Dict[str, Any]:
    from config_api import canonical_backup_conf_plan

    config_dir = _config_dir(ui_config)
    conf_file = config_dir / "backup.conf"
    plan = canonical_backup_conf_plan(ui_config)
    missing_keys = list(plan.get("missing_keys") or [])
    unknown_keys = list(plan.get("unknown_keys") or [])
    changed = bool(plan.get("changed"))
    return {
        "state": "pending" if missing_keys or unknown_keys or changed else "ok",
        "checked": True,
        "conf_file": str(conf_file),
        "schema_key_count": len(plan.get("schema_keys") or []),
        "missing_keys": missing_keys,
        "missing_count": len(missing_keys),
        "unknown_keys": unknown_keys,
        "unknown_count": len(unknown_keys),
        "canonical_content_changed": changed,
    }


def _status_item(
    item_id: str,
    title: str,
    status: str,
    reason: str,
    *,
    category: str = "setup",
    version: int = 1,
    stage: str = "current",
    destructive: bool = False,
    auto_apply: bool = True,
    details: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "id": item_id,
        "title": title,
        "category": category,
        "version": version,
        "stage": stage,
        "status": status,
        "reason": reason,
        "destructive": destructive,
        "auto_apply": auto_apply,
        "details": details or {},
    }


def _migration_status_from_state(state: str) -> str:
    state_norm = str(state or "").strip()
    if state_norm == "failed":
        return "failed"
    if state_norm == "blocked":
        return "blocked"
    if state_norm in {"applied", "baseline_detected", "imported_from_legacy_marker"}:
        return "applied"
    if state_norm in {"not_required", "not_applicable", "skipped"}:
        return "not_needed"
    return "pending"


def _migration_reason_from_state(migration_id: str, state: str, details: Dict[str, Any]) -> str:
    state_norm = str(state or "").strip()
    if state_norm == "applied":
        updated = details.get("updated_keys") if isinstance(details.get("updated_keys"), list) else []
        if updated:
            return f"Migration applied; updated keys: {', '.join(str(item) for item in updated)}."
        return "Migration applied."
    if state_norm in {"not_required", "not_applicable"}:
        return "Migration checked; no changes were required."
    if state_norm == "skipped":
        return "Migration skipped because a final state was already recorded."
    if state_norm == "failed":
        return "Migration failed."
    if state_norm == "blocked":
        blocked_by = str(details.get("blocked_by") or "a previous migration")
        return f"Migration was not executed because {blocked_by} failed."
    return f"Migration state for {migration_id} has not reached a final state."


def _recorded_startup_migration_items(migrations: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    hidden_legacy_ids = {
        "storage_paths_v1",
        "restore_history_v1",
        "repository_objects_v1",
        "repository_objects_v2",
        "repository_objects_v3",
        "repository_objects_v4",
        "storage_objects_v1",
        "storage_objects_v2",
        "repository_runtime_v1",
        "borg_keyfiles_v1",
        "canonical_storage_profiles_v1",
        "repository_contract_cleanup_v1",
    }
    for migration_id in sorted(str(key) for key in migrations.keys()):
        if migration_id in hidden_legacy_ids:
            continue
        row = migrations.get(migration_id)
        if not isinstance(row, dict):
            continue
        state = str(row.get("state") or "").strip()
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        checked_at = str(row.get("checked_at") or "").strip()
        items.append(_status_item(
            migration_id,
            migration_id,
            _migration_status_from_state(state),
            _migration_reason_from_state(migration_id, state, details),
            category="migration",
            details={
                **details,
                "state": state,
                "checked_at": checked_at,
                "updated_keys": details.get("updated_keys") if isinstance(details.get("updated_keys"), list) else [],
                "runner": str(details.get("runner") or ""),
                "introduced_in": str(details.get("introduced_in") or ""),
            },
        ))
    return items


def get_migration_registry_status(ui_config: dict) -> Dict[str, Any]:
    from storage_objects_api import read_storage_store

    config_dir = _config_dir(ui_config)
    conf_file = config_dir / "backup.conf"
    storage_file = config_dir / "storages.json"
    jobs_dir = config_dir / "jobs"
    migration_state = _read_migration_state(config_dir)
    config_state = analyze_backup_conf_state(ui_config)
    schema_missing = list(config_state.get("missing_keys") or [])
    unknown_keys = list(config_state.get("unknown_keys") or [])
    schema_changed = bool(config_state.get("canonical_content_changed"))
    schema_ok = conf_file.exists() and not schema_missing and not unknown_keys and not schema_changed

    try:
        profile_count = len(read_storage_store(ui_config).get("storages", []))
    except Exception:
        profile_count = 0

    migrations = migration_state.get("migrations") if isinstance(migration_state.get("migrations"), dict) else {}

    items = [
        _status_item(
            "setup_jobs_dir",
            "Job metadata directory",
            "applied" if jobs_dir.is_dir() else "pending",
            "Job metadata directory exists." if jobs_dir.is_dir() else "Job metadata directory is missing.",
            category="setup",
            details={"jobs_dir": str(jobs_dir)},
        ),
        _status_item(
            "setup_storage_inventory",
            "Canonical storage inventory",
            "applied" if storage_file.exists() else "pending",
            "storages.json exists." if storage_file.exists() else "storages.json is missing.",
            category="setup",
            details={"storage_file": str(storage_file), "profile_count": profile_count},
        ),
        _status_item(
            "config_backup_conf_schema",
            "Canonical backup.conf configuration",
            "applied" if schema_ok else "pending",
            "backup.conf matches the current canonical schema."
            if schema_ok
            else "backup.conf does not match the current canonical schema.",
            category="config",
            details={
                "conf_file": config_state.get("conf_file") or str(conf_file),
                "schema_key_count": int(config_state.get("schema_key_count") or 0),
                "missing_keys": schema_missing,
                "missing_count": len(schema_missing),
                "unknown_keys": unknown_keys,
                "unknown_count": len(unknown_keys),
                "canonical_content_changed": schema_changed,
            },
        ),
    ]
    items.extend(_recorded_startup_migration_items(migrations))

    return {
        "schema_version": 1,
        "items": items,
        "summary": {
            "total": len(items),
            "pending": sum(1 for item in items if item.get("status") == "pending"),
            "failed": sum(1 for item in items if item.get("status") == "failed"),
            "blocked": sum(1 for item in items if item.get("status") == "blocked"),
        },
    }
