"""
api/migration_api.py - read-only migration registry for the legacy plugin.

The registry is intentionally conservative: it reports migration status and
cleanup candidates, but does not modify config files or move data.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


DEPRECATED_CONF_KEYS: Dict[str, str] = {
    "BORG_PASSPHRASE_FILE_LOCAL": "Passphrase path is now stored per job",
    "BORG_PASSPHRASE_FILE_STORAGEBOX": "Passphrase path is now stored per job",
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


def _disabled_assignment_value(lines: List[str], target_key: str) -> str:
    prefix = "# LEGACY_CLEANUP_DISABLED "
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        disabled_line = stripped[len(prefix):]
        if _assignment_key(disabled_line) != target_key:
            continue
        _, _, value = disabled_line.partition("=")
        return value.strip().strip('"').strip("'")
    return ""


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
        return "Passphrase path is now stored per job"
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


def get_migration_registry_status(ui_config: dict) -> Dict[str, Any]:
    from config_api import read_raw_conf, read_settings_payload

    config_dir = _config_dir(ui_config)
    conf_file = config_dir / "backup.conf"
    settings_file = config_dir / "settings.json"
    jobs_dir = config_dir / "jobs"
    raw_conf = read_raw_conf(ui_config)
    migration_state = _read_migration_state(config_dir)
    example_keys = _read_example_keys(config_dir)
    config_state = analyze_backup_conf_state(ui_config)
    schema_missing = list(config_state.get("missing_keys") or [])
    cleanup_candidates = list(config_state.get("deprecated_active_keys") or [])
    cleanup_plan = build_legacy_cleanup_plan(ui_config, mode="comment_out")

    try:
        settings_payload = read_settings_payload(ui_config)
    except Exception:
        settings_payload = {}
    profile_count = 0
    if isinstance(settings_payload, dict):
        for key in ("usb_profiles", "smb_profiles", "storage_profiles"):
            rows = settings_payload.get(key)
            if isinstance(rows, list):
                profile_count += len(rows)

    try:
        conf_lines = (conf_file.read_text(encoding="utf-8", errors="replace").splitlines() if conf_file.exists() else [])
    except OSError:
        conf_lines = []
    migrations = migration_state.get("migrations") if isinstance(migration_state.get("migrations"), dict) else {}
    storage_state = migrations.get("storage_paths_v1") if isinstance(migrations.get("storage_paths_v1"), dict) else {}
    storage_state_name = str(storage_state.get("state", "") or "").strip()
    storage_marker = str(raw_conf.get("MIGRATION_STORAGE_PATHS_VERSION", "")).strip()
    if not storage_marker:
        storage_marker = _disabled_assignment_value(conf_lines, "MIGRATION_STORAGE_PATHS_VERSION")
    if storage_state_name in {"applied", "baseline_detected", "imported_from_legacy_marker", "not_applicable"}:
        storage_status = "applied"
        storage_reason = "Storage path migration is complete in migration state."
    elif storage_state_name == "failed":
        storage_status = "failed"
        storage_reason = "Storage path migration is marked as failed in migration state."
    else:
        storage_status = "applied" if storage_marker == "1" else ("failed" if storage_marker == "0" else "pending")
        storage_reason = (
            "The legacy storage path migration marker is set."
            if storage_status == "applied"
            else ("The legacy storage path migration marker reports a failed or incomplete run." if storage_status == "failed" else "Storage path migration evidence is missing.")
        )

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
            "setup_settings_json",
            "Profile data in settings.json",
            "applied" if settings_file.exists() else "pending",
            "settings.json exists." if settings_file.exists() else "settings.json is missing.",
            category="setup",
            details={"settings_file": str(settings_file), "profile_count": profile_count},
        ),
        _status_item(
            "setup_runtime_paths",
            "Runtime paths from GLOBAL_DATA_DIR",
            storage_status,
            storage_reason,
            category="setup",
            destructive=True,
            details={
                "state": storage_state_name,
                "marker": storage_marker or "",
                "legacy_config_key": "MIGRATION_STORAGE_PATHS_VERSION",
            },
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
