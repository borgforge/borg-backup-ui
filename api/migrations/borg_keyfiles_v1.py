"""Migration: move known Borg keyfiles into persistent plugin storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from borg_key_store import (
    borg_keys_dir,
    find_key_file,
    import_default_key_if_present,
    is_keyfile_encryption,
)
from repositories_api import read_repository_store, write_repository_store


MIGRATION_ID = "borg_keyfiles_v1"
INTRODUCED_IN = "2026.07.10.0006"


def _candidates(config: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for repository in read_repository_store(config).get("repositories", []):
        if not isinstance(repository, dict) or not is_keyfile_encryption(repository.get("encryption")):
            continue
        repository_id = str(repository.get("borg_repository_id") or "").strip().lower()
        repository_key = str(repository.get("repository_key") or "").strip()
        if not repository_id or not repository_key:
            continue
        current = find_key_file(borg_keys_dir(config), repository_id)
        source = current or find_key_file(Path.home() / ".config" / "borg" / "keys", repository_id)
        if source is not None and str(repository.get("keyfile_ref") or "") != str(current or source):
            rows.append({
                "repository_key": repository_key,
                "repository_id": repository_id,
                "keyfile_ref": str(current or source),
            })
    return rows


def detect(config: dict) -> dict[str, Any]:
    candidates = _candidates(config)
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(candidates),
        "repositories": [row["repository_key"] for row in candidates],
        "target_directory": str(borg_keys_dir(config)),
    }


def apply(config: dict) -> dict[str, Any]:
    candidates = {row["repository_key"]: row for row in _candidates(config)}
    updated: list[str] = []
    repositories = []
    for repository in read_repository_store(config).get("repositories", []):
        key = str(repository.get("repository_key") or "") if isinstance(repository, dict) else ""
        candidate = candidates.get(key)
        if candidate and isinstance(repository, dict):
            imported = import_default_key_if_present(config, candidate["repository_id"])
            if imported is not None:
                repository = {**repository, "keyfile_ref": str(imported)}
                updated.append(key)
        repositories.append(repository)
    if updated:
        write_repository_store(config, {"repositories": repositories})
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied" if updated else "not_required",
        "details": {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "updated_repositories": updated,
            "updated_repository_count": len(updated),
            "target_directory": str(borg_keys_dir(config)),
        },
    }
