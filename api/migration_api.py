"""Migration status, diagnostics and explicit configuration cleanup actions."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


DEPRECATED_CONF_KEYS: Dict[str, str] = {
    "BORG_PASSPHRASE_FILE_LOCAL": "Passphrase reference is now stored by the repository object",
    "BORG_PASSPHRASE_FILE_STORAGEBOX": "Passphrase reference is now stored by the repository object",
    "GLOBAL_DOCKER_STOP_TIMEOUT": "replaced by DOCKER_STOP_TIMEOUT",
    "GLOBAL_DOCKER_STOP_WAIT": "replaced by DOCKER_STOP_WAIT",
    "GLOBAL_DOCKER_START_WAIT": "replaced by DOCKER_START_WAIT",
    "STORAGEBOX_BASE": "alias replaced by STORAGEBOX_BASE_PATH",
}
PROTECTED_CONF_KEYS = {
    "MIGRATION_STORAGE_PATHS_VERSION",
}


def _config_dir(ui_config: dict) -> Path:
    return Path(str(ui_config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup/scripts"))) / "config"


def _iter_conf_assignment_keys(lines: List[str]) -> List[str]:
    keys: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        clean = stripped.removeprefix("readonly ")
        if "=" not in clean or clean.startswith("("):
            continue
        key = clean.split("=", 1)[0].strip()
        if key and re.fullmatch(r"[A-Z0-9_]+", key):
            keys.append(key)
    return keys


def _assignment_key(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    clean = stripped.removeprefix("readonly ")
    if "=" not in clean or clean.startswith("("):
        return ""
    key = clean.split("=", 1)[0].strip()
    return key if key and re.fullmatch(r"[A-Z0-9_]+", key) else ""


def _disabled_assignment_keys(lines: List[str]) -> List[str]:
    prefix = "# LEGACY_CLEANUP_DISABLED "
    keys: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        key = _assignment_key(stripped[len(prefix):])
        if key:
            keys.append(key)
    return keys


def _read_example_keys(config_dir: Path) -> List[str]:
    example_file = config_dir / "backup.conf.example"
    if not example_file.exists():
        return []
    try:
        return _iter_conf_assignment_keys(example_file.read_text(encoding="utf-8").splitlines())
    except OSError:
        return []


def _read_migration_state(config_dir: Path) -> Dict[str, Any]:
    state_file = config_dir / "migration-state.json"
    if not state_file.exists():
        return {}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _deprecated_reason(key: str) -> str:
    if key.startswith("BORG_PASSPHRASE_FILE_"):
        return "Passphrase reference is now stored by the repository object"
    return DEPRECATED_CONF_KEYS.get(key, "")


def _cleanup_candidates(raw_conf: Dict[str, str], example_keys: List[str]) -> List[Dict[str, Any]]:
    example_set = set(example_keys)
    legacy_keys = sorted(
        key for key in raw_conf.keys()
        if example_set and key not in example_set and key not in PROTECTED_CONF_KEYS
    )
    return [
        {
            "key": key,
            "reason": _deprecated_reason(key) or "no longer present in the current backup.conf.example",
            "known": bool(_deprecated_reason(key)),
        }
        for key in legacy_keys
    ]


def analyze_backup_conf_state(ui_config: dict) -> Dict[str, Any]:
    from config_api import read_raw_conf

    config_dir = _config_dir(ui_config)
    conf_file = config_dir / "backup.conf"
    example_keys = _read_example_keys(config_dir)
    raw_conf = read_raw_conf(ui_config)
    schema_missing = [key for key in example_keys if key not in raw_conf]
    cleanup_candidates = _cleanup_candidates(raw_conf, example_keys)
    try:
        conf_lines = (conf_file.read_text(encoding="utf-8", errors="replace").splitlines() if conf_file.exists() else [])
    except OSError:
        conf_lines = []
    disabled_keys = sorted(set(_disabled_assignment_keys(conf_lines)))
    protected_active = sorted(key for key in PROTECTED_CONF_KEYS if key in raw_conf)
    protected_disabled = sorted(key for key in PROTECTED_CONF_KEYS if key in disabled_keys)
    return {
        "state": "pending" if schema_missing or cleanup_candidates else "ok",
        "checked": True,
        "conf_file": str(conf_file),
        "schema_key_count": len(example_keys),
        "missing_keys": schema_missing,
        "missing_count": len(schema_missing),
        "deprecated_active_keys": cleanup_candidates,
        "deprecated_active_count": len(cleanup_candidates),
        "deprecated_disabled_keys": [key for key in disabled_keys if key not in PROTECTED_CONF_KEYS],
        "deprecated_disabled_count": len([key for key in disabled_keys if key not in PROTECTED_CONF_KEYS]),
        "protected_internal_keys": {
            "active": protected_active,
            "disabled": protected_disabled,
        },
    }


def build_legacy_cleanup_plan(ui_config: dict, *, mode: str = "comment_out") -> Dict[str, Any]:
    """
    Dry-run plan for a later backup.conf cleanup migration.

    mode:
      - comment_out: keep lines as comments for first rollout
      - remove: remove lines completely after validation

    This function never writes files.
    """
    from config_api import read_raw_conf

    config_dir = _config_dir(ui_config)
    conf_file = config_dir / "backup.conf"
    raw_conf = read_raw_conf(ui_config)
    example_keys = _read_example_keys(config_dir)
    candidates = _cleanup_candidates(raw_conf, example_keys)
    mode_norm = str(mode or "comment_out").strip().lower()
    if mode_norm not in {"comment_out", "remove"}:
        mode_norm = "comment_out"
    action = "comment out" if mode_norm == "comment_out" else "remove"

    planned = []
    for row in candidates:
        planned.append({
            "key": row["key"],
            "action": action,
            "mode": mode_norm,
            "reason": row["reason"],
            "known": bool(row.get("known")),
        })

    return {
        "dry_run": True,
        "migration_id": "legacy_deprecated_keys_cleanup_v1",
        "mode": mode_norm,
        "conf_file": str(conf_file),
        "backup_required": True,
        "rollback": {
            "available": True,
            "method": "backup_conf_snapshot before apply; restore through config backups and rollback",
        },
        "candidate_count": len(planned),
        "known_deprecated_count": sum(1 for row in planned if row.get("known")),
        "unknown_legacy_count": sum(1 for row in planned if not row.get("known")),
        "planned_actions": planned,
    }


def apply_legacy_cleanup(ui_config: dict, *, mode: str = "comment_out", confirm: str = "") -> Dict[str, Any]:
    """
    Applies the legacy backup.conf cleanup migration.

    First rollout only supports comment_out. A config backup snapshot is created
    before writing. Existing comments are left untouched.
    """
    if str(confirm or "").strip() != "AUSKOMMENTIEREN":
        raise ValueError("Confirmation is missing")

    mode_norm = str(mode or "comment_out").strip().lower()
    if mode_norm != "comment_out":
        raise ValueError("Only comment_out mode is currently allowed")

    from config_api import backup_conf_snapshot

    plan = build_legacy_cleanup_plan(ui_config, mode=mode_norm)
    candidate_keys = {str(row.get("key") or "").strip() for row in plan.get("planned_actions", [])}
    candidate_keys.discard("")
    if not candidate_keys:
        return {
            "applied": False,
            "changed": False,
            "mode": mode_norm,
            "candidate_count": 0,
            "commented_count": 0,
            "backup": None,
            "message": "No cleanup candidates are available.",
            "message_code": "cleanup_no_candidates",
        }

    config_dir = _config_dir(ui_config)
    conf_file = config_dir / "backup.conf"
    if not conf_file.exists() or not conf_file.is_file():
        raise FileNotFoundError("backup.conf not found")

    old_lines = conf_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    out: List[str] = []
    commented: List[str] = []
    for line in old_lines:
        key = _assignment_key(line)
        if key in candidate_keys:
            newline = "\n" if line.endswith("\n") else ""
            body = line[:-1] if newline else line
            out.append(f"# LEGACY_CLEANUP_DISABLED {body}{newline}")
            commented.append(key)
        else:
            out.append(line)

    new_text = "".join(out)
    old_text = "".join(old_lines)
    if new_text == old_text:
        return {
            "applied": False,
            "changed": False,
            "mode": mode_norm,
            "candidate_count": len(candidate_keys),
            "commented_count": 0,
            "commented_keys": [],
            "backup": None,
            "message": "No active legacy lines were found.",
            "message_code": "cleanup_no_active_lines",
        }

    snapshot = backup_conf_snapshot(ui_config, keep=10, reason="Legacy cleanup migration")
    conf_file.write_text(new_text, encoding="utf-8")
    return {
        "applied": True,
        "changed": True,
        "mode": mode_norm,
        "candidate_count": len(candidate_keys),
        "commented_count": len(commented),
        "commented_keys": commented,
        "backup": snapshot.name if snapshot else None,
        "message": f"Commented out {len(commented)} legacy/deprecated key(s).",
        "message_code": "cleanup_commented",
        "message_params": {"count": len(commented)},
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
    example_keys = _read_example_keys(config_dir)
    config_state = analyze_backup_conf_state(ui_config)
    schema_missing = list(config_state.get("missing_keys") or [])
    cleanup_candidates = list(config_state.get("deprecated_active_keys") or [])
    cleanup_plan = build_legacy_cleanup_plan(ui_config, mode="comment_out")

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
            "backup.conf schema from backup.conf.example",
            "applied" if conf_file.exists() and not schema_missing else "pending",
            "backup.conf contains all current schema keys." if conf_file.exists() and not schema_missing else "backup.conf is missing schema keys.",
            category="config",
            details={
                "conf_file": config_state.get("conf_file") or str(conf_file),
                "schema_key_count": int(config_state.get("schema_key_count") or len(example_keys)),
                "missing_keys": schema_missing,
                "missing_count": len(schema_missing),
            },
        ),
        _status_item(
            "legacy_deprecated_keys_cleanup_v1",
            "Deprecated backup.conf cleanup candidates",
            "pending" if cleanup_candidates else "not_needed",
            "Legacy/deprecated keys are present and can be cleaned up." if cleanup_candidates else "No legacy/deprecated keys found.",
            category="planned_migration",
            stage="planned",
            destructive=True,
            auto_apply=False,
            details={
                "candidate_keys": cleanup_candidates,
                "candidate_count": len(cleanup_candidates),
                "known_deprecated_count": sum(1 for row in cleanup_candidates if row.get("known")),
                "unknown_legacy_count": sum(1 for row in cleanup_candidates if not row.get("known")),
                "disabled_key_count": int(config_state.get("deprecated_disabled_count") or 0),
                "disabled_keys": config_state.get("deprecated_disabled_keys") or [],
                "protected_internal_keys": config_state.get("protected_internal_keys") or {},
                "dry_run_plan": cleanup_plan,
            },
        ),
    ]
    items.extend(_recorded_startup_migration_items(migrations))

    return {
        "schema_version": 1,
        "items": items,
        "summary": {
            "total": len(items),
            "pending": sum(
                1 for item in items
                if item.get("status") == "pending" and item.get("category") != "planned_migration"
            ),
            "failed": sum(1 for item in items if item.get("status") == "failed"),
            "planned": sum(1 for item in items if item.get("stage") == "planned" and item.get("status") != "not_needed"),
            "cleanup_key_candidates": len(cleanup_candidates),
            "deprecated_key_candidates": len(cleanup_candidates),
            "known_deprecated_keys": sum(1 for row in cleanup_candidates if row.get("known")),
            "unknown_legacy_keys": sum(1 for row in cleanup_candidates if not row.get("known")),
        },
    }
