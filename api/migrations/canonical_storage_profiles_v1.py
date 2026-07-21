"""Migration: make storages.json the only storage profile source."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inventory_store import atomic_write_bytes
from storage_objects_api import _safe_local_storage_path, replace_profile_storages, storages_file


MIGRATION_ID = "canonical_storage_profiles_v1"
INTRODUCED_IN = "2026.07.11.0100"


def _config_dir(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    root = base.parent if base.name == "scripts" else base
    return root / "config"


def _settings_file(config: dict) -> Path:
    return _config_dir(config) / "settings.json"


def _read_settings(config: dict) -> dict[str, Any]:
    path = _settings_file(config)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Legacy settings profile source is not readable: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Legacy settings profile source is invalid: {path}")
    return payload


def _profile_counts(settings: dict[str, Any]) -> dict[str, int]:
    return {
        key: len(settings.get(key)) if isinstance(settings.get(key), list) else 0
        for key in ("usb_profiles", "smb_profiles", "storage_profiles")
    }


def _managed_smb_mount_path(profile: dict[str, Any]) -> str:
    key = str(profile.get("key") or profile.get("profile_key") or "").strip().lower()
    if not key:
        raise ValueError("SMB profile key is required")
    return f"/mnt/borg-backup-ui/smb/{key}"


def _normalize_legacy_smb_profiles(profiles: Any) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    normalized: list[dict[str, Any]] = []
    rewrites: list[dict[str, str]] = []
    for raw in profiles if isinstance(profiles, list) else []:
        if not isinstance(raw, dict):
            continue
        profile = dict(raw)
        original = str(profile.get("mount_path") or "").strip()
        try:
            _safe_local_storage_path(original, field="SMB mount path")
        except ValueError as exc:
            managed = _managed_smb_mount_path(profile)
            profile["mount_path"] = managed
            rewrites.append({
                "profile_key": str(profile.get("key") or profile.get("profile_key") or "").strip(),
                "old_mount_path": original,
                "new_mount_path": managed,
                "reason": str(exc),
            })
        normalized.append(profile)
    return normalized, rewrites


def detect(config: dict) -> dict[str, Any]:
    settings = _read_settings(config)
    counts = _profile_counts(settings)
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": any(counts.values()),
        "settings_file": str(_settings_file(config)),
        "storage_file": str(storages_file(config)),
        "profile_counts": counts,
    }


def apply(config: dict) -> dict[str, Any]:
    settings_path = _settings_file(config)
    storage_path = storages_file(config)
    settings = _read_settings(config)
    counts = _profile_counts(settings)
    if not any(counts.values()):
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "not_required",
            "details": {"profile_counts": counts},
        }
    baseline_backup = str(config.get("_CANONICAL_BASELINE_BACKUP_DIR") or "").strip()
    owns_backup = not baseline_backup
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = (
        Path(baseline_backup)
        if baseline_backup
        else _config_dir(config) / "migration-backups" / f"{MIGRATION_ID}-{timestamp}-{uuid.uuid4().hex[:8]}"
    )
    if owns_backup:
        backup_dir.mkdir(parents=True, exist_ok=False)
    old_settings = settings_path.read_bytes() if settings_path.exists() else None
    old_storages = storage_path.read_bytes() if storage_path.exists() else None
    if owns_backup and old_settings is not None:
        atomic_write_bytes(backup_dir / "settings.json", old_settings)
    if owns_backup and old_storages is not None:
        atomic_write_bytes(backup_dir / "storages.json", old_storages)
    updated: dict[str, list[str]] = {}
    normalized_mount_paths: list[dict[str, str]] = []
    try:
        mapping = {
            "usb": settings.get("usb_profiles", []),
            "smb": settings.get("smb_profiles", []),
            "storagebox": settings.get("storage_profiles", []),
        }
        for location, profiles in mapping.items():
            if isinstance(profiles, list) and profiles:
                if location == "smb":
                    profiles, rewrites = _normalize_legacy_smb_profiles(profiles)
                    normalized_mount_paths.extend(rewrites)
                updated[location] = replace_profile_storages(config, location, profiles)
        cleaned = {"schema_version": int(settings.get("schema_version") or 1)}
        atomic_write_bytes(settings_path, (json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except Exception:
        if owns_backup:
            if old_settings is None:
                settings_path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(settings_path, old_settings)
            if old_storages is None:
                storage_path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(storage_path, old_storages)
        raise
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied",
        "details": {
            "profile_counts": counts,
            "updated_storage_keys": updated,
            "normalized_mount_paths": normalized_mount_paths,
            "backup_directory": str(backup_dir),
            "settings_file": str(settings_path),
            "storage_file": str(storage_path),
            "actions": ["migrated profiles to storages.json", "removed profile arrays from settings.json"],
        },
    }
