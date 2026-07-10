"""Migration: move known Borg keyfiles into persistent plugin storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from borg_key_store import (
    borg_keys_dir,
    find_key_file,
    import_default_key_if_present,
    is_keyfile_encryption,
    repository_id_from_key_file,
)
from repositories_api import (
    _borg_info_fields,
    _borg_info_with_default_keys,
    _storage_by_key,
    effective_repository_path,
    read_repository_store,
    write_repository_store,
)


MIGRATION_ID = "borg_keyfiles_v1"
INTRODUCED_IN = "2026.07.10.0006"


def _candidates(config: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    legacy_dir = Path.home() / ".config" / "borg" / "keys"
    try:
        legacy_has_keys = any(repository_id_from_key_file(path) for path in legacy_dir.iterdir())
    except OSError:
        legacy_has_keys = False
    for repository in read_repository_store(config).get("repositories", []):
        if not isinstance(repository, dict) or not is_keyfile_encryption(repository.get("encryption")):
            continue
        repository_id = str(repository.get("borg_repository_id") or "").strip().lower()
        repository_key = str(repository.get("repository_key") or "").strip()
        if not repository_key:
            continue
        if not repository_id:
            if legacy_has_keys:
                rows.append({"repository_key": repository_key, "repository_id": "", "keyfile_ref": ""})
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
    failed: list[dict[str, str]] = []
    repositories = []
    storages = _storage_by_key(config)
    for repository in read_repository_store(config).get("repositories", []):
        key = str(repository.get("repository_key") or "") if isinstance(repository, dict) else ""
        candidate = candidates.get(key)
        if candidate and isinstance(repository, dict):
            try:
                repository_id = candidate["repository_id"]
                if not repository_id:
                    storage = storages.get(str(repository.get("storage_key") or ""), {})
                    if not storage:
                        raise RuntimeError("Storage target is missing")
                    repo_path = effective_repository_path(storage, str(repository.get("relative_path") or ""))
                    passphrase_ref = str(repository.get("passphrase_ref") or "").strip()
                    passphrase_file = Path(passphrase_ref) if passphrase_ref else None
                    if passphrase_file is not None and not passphrase_file.is_file():
                        raise RuntimeError("Repository passphrase file is missing")
                    fields = _borg_info_fields(
                        _borg_info_with_default_keys(storage, repo_path, passphrase_file)
                    )
                    repository_id = str(fields.get("borg_repository_id") or "").strip().lower()
                    if not repository_id:
                        raise RuntimeError("Borg did not return a repository ID")
                imported = import_default_key_if_present(config, repository_id)
                if imported is None:
                    raise RuntimeError("No exact matching Borg keyfile was found")
                repository = {
                    **repository,
                    "borg_repository_id": repository_id,
                    "keyfile_ref": str(imported),
                }
                updated.append(key)
            except Exception as exc:
                failed.append({"repository_key": key, "error": str(exc)[:500]})
        repositories.append(repository)
    if updated:
        write_repository_store(config, {"repositories": repositories})
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "failed" if failed else ("applied" if updated else "not_required"),
        "details": {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "updated_repositories": updated,
            "updated_repository_count": len(updated),
            "failed_repositories": failed,
            "failed_repository_count": len(failed),
            "target_directory": str(borg_keys_dir(config)),
        },
    }
