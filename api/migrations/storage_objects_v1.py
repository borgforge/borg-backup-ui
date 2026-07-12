"""Migration: create storage target objects and link repositories to them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from storage_objects_api import (
    read_storage_store,
    repository_relative_path,
    storage_from_repository,
    storages_file,
    write_storage_store,
)
from repositories_api import read_repository_store, repositories_file, write_repository_store


MIGRATION_ID = "storage_objects_v1"
INTRODUCED_IN = "2026.07.09.0002"


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


def _legacy_storage_key(repo: dict[str, Any]) -> bool:
    value = str(repo.get("storage_key") or "").strip()
    return not value.startswith("storage_")


def detect(config: dict) -> dict[str, Any]:
    repo_store = read_repository_store(config, preserve_legacy=True)
    repositories = repo_store.get("repositories") if isinstance(repo_store.get("repositories"), list) else []
    storage_store = read_storage_store(config)
    storages = storage_store.get("storages") if isinstance(storage_store.get("storages"), list) else []
    needs_link = [
        str(repo.get("repository_key") or "")
        for repo in repositories
        if _legacy_storage_key(repo) or not str(repo.get("relative_path") or "").strip()
    ]
    required = bool(repositories and (not storages or needs_link))
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": required,
        "repository_file": str(repositories_file(config)),
        "storage_file": str(storages_file(config)),
        "repository_count": len(repositories),
        "storage_count": len(storages),
        "repositories_needing_storage_link": needs_link,
    }


def apply(config: dict) -> dict[str, Any]:
    settings = _read_settings(config)
    repo_store = read_repository_store(config, preserve_legacy=True)
    repositories = repo_store.get("repositories") if isinstance(repo_store.get("repositories"), list) else []
    storage_store = read_storage_store(config)
    by_key = {
        str(storage.get("storage_key") or ""): storage
        for storage in storage_store.get("storages", [])
        if str(storage.get("storage_key") or "").strip()
    }
    linked_repositories: list[str] = []

    updated_repos: list[dict[str, Any]] = []
    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        storage = storage_from_repository(repo, settings=settings)
        if storage:
            key = str(storage.get("storage_key") or "")
            previous = by_key.get(key, {})
            by_key[key] = {
                **previous,
                **storage,
                "storage_key": key,
                "created_at": str(previous.get("created_at") or storage.get("created_at") or ""),
                "created_by": str(previous.get("created_by") or storage.get("created_by") or "migration"),
            }
            before_key = str(repo.get("storage_key") or "")
            repo = {
                **repo,
                "storage_key": key,
                "storage_name": str(storage.get("display_name") or repo.get("storage_name") or ""),
                "relative_path": repository_relative_path(repo, storage),
            }
            if before_key != key:
                linked_repositories.append(str(repo.get("repository_key") or ""))
        updated_repos.append(repo)

    write_storage_store(config, {"storages": list(by_key.values())})
    write_repository_store(config, {"repositories": updated_repos})

    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied" if linked_repositories or by_key else "not_required",
        "details": {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "repository_file": str(repositories_file(config)),
            "storage_file": str(storages_file(config)),
            "storage_keys": sorted(by_key.keys()),
            "storage_count": len(by_key),
            "linked_repositories": linked_repositories,
            "linked_repository_count": len(linked_repositories),
        },
    }
