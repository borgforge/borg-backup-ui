"""Migration: enrich storage objects with configured profile details."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repositories_api import read_repository_store, write_repository_store
from storage_objects_api import read_storage_store, storage_key_for, storages_file, upsert_storages_from_settings


MIGRATION_ID = "storage_objects_v2"
INTRODUCED_IN = "2026.07.09.0004"


def _data_root(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    return base.parent if base.name == "scripts" else base


def _settings_file(config: dict) -> Path:
    return _data_root(config) / "config" / "settings.json"


def _read_settings(config: dict) -> dict[str, Any]:
    path = _settings_file(config)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _expected_profile_storages(settings: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for profile in settings.get("usb_profiles") if isinstance(settings.get("usb_profiles"), list) else []:
        if not isinstance(profile, dict):
            continue
        key = str(profile.get("key") or "").strip().lower()
        mount_path = str(profile.get("mount_path") or "").strip()
        if key and mount_path:
            rows.append({
                "storage_key": storage_key_for("usb", f"usb-profile:{key}"),
                "display_name": str(profile.get("name") or key).strip(),
                "profile_key": key,
                "base_path": mount_path,
                "mount_path": mount_path,
                "source": "usb_profile",
            })
    for profile in settings.get("smb_profiles") if isinstance(settings.get("smb_profiles"), list) else []:
        if not isinstance(profile, dict):
            continue
        key = str(profile.get("key") or "").strip().lower()
        mount_path = str(profile.get("mount_path") or "").strip()
        if key and mount_path:
            rows.append({
                "storage_key": storage_key_for("smb", f"smb-profile:{key}"),
                "display_name": str(profile.get("name") or key).strip(),
                "profile_key": key,
                "base_path": mount_path,
                "mount_path": mount_path,
                "server": str(profile.get("server") or "").strip(),
                "share": str(profile.get("share") or "").strip(),
                "source": "smb_profile",
            })
    for profile in settings.get("storage_profiles") if isinstance(settings.get("storage_profiles"), list) else []:
        if not isinstance(profile, dict):
            continue
        key = str(profile.get("key") or "").strip().lower()
        host = str(profile.get("host") or "").strip()
        base_path = str(profile.get("base_path") or "").strip()
        if key and host and base_path:
            rows.append({
                "storage_key": storage_key_for("storagebox", f"storagebox-profile:{key}"),
                "display_name": str(profile.get("name") or key).strip(),
                "profile_key": key,
                "base_path": base_path,
                "host": host,
                "port": str(profile.get("port") or "").strip(),
                "user": str(profile.get("user") or "").strip(),
                "target_type": str(profile.get("target_type") or "storagebox").strip(),
                "ssh_key_path": str(profile.get("ssh_key_path") or "").strip(),
                "source": "storage_profile",
            })
    return rows


def detect(config: dict) -> dict[str, Any]:
    settings = _read_settings(config)
    expected = _expected_profile_storages(settings)
    current = {
        str(row.get("storage_key") or ""): row
        for row in read_storage_store(config).get("storages", [])
        if str(row.get("storage_key") or "").strip()
    }
    missing_or_stale = []
    for item in expected:
        existing = current.get(str(item.get("storage_key") or ""))
        if not existing:
            missing_or_stale.append(str(item.get("storage_key") or ""))
            continue
        for field, value in item.items():
            if field == "storage_key":
                continue
            if str(existing.get(field) or "").strip() != str(value or "").strip():
                missing_or_stale.append(str(item.get("storage_key") or ""))
                break
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(missing_or_stale),
        "storage_file": str(storages_file(config)),
        "settings_file": str(_settings_file(config)),
        "profile_storage_count": len(expected),
        "missing_or_stale_storage_keys": sorted(set(missing_or_stale)),
    }


def apply(config: dict) -> dict[str, Any]:
    settings = _read_settings(config)
    changed = upsert_storages_from_settings(config, settings)
    storage_by_key = {
        str(row.get("storage_key") or ""): row
        for row in read_storage_store(config).get("storages", [])
        if str(row.get("storage_key") or "").strip()
    }
    repo_store = read_repository_store(config, preserve_legacy=True)
    updated_repos = []
    updated_repo_keys = []
    for repo in repo_store.get("repositories", []):
        if not isinstance(repo, dict):
            continue
        storage = storage_by_key.get(str(repo.get("storage_key") or ""))
        if storage:
            storage_name = str(storage.get("display_name") or "").strip()
            if storage_name and str(repo.get("storage_name") or "").strip() != storage_name:
                repo = {**repo, "storage_name": storage_name}
                updated_repo_keys.append(str(repo.get("repository_key") or ""))
        updated_repos.append(repo)
    if updated_repo_keys:
        write_repository_store(config, {"repositories": updated_repos})
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied" if changed or updated_repo_keys else "not_required",
        "details": {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "storage_file": str(storages_file(config)),
            "settings_file": str(_settings_file(config)),
            "updated_storage_keys": changed,
            "updated_repository_keys": sorted(set(updated_repo_keys)),
        },
    }
