"""Migration: remove transitional repository path and profile fields."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repositories_api import read_repository_store, repositories_file, write_repository_store


MIGRATION_ID = "repository_contract_cleanup_v1"
INTRODUCED_IN = "2026.07.11.1400"
LEGACY_FIELDS = {
    "repo_path",
    "repo_uri",
    "path_raw",
    "path_display",
    "storage_profile_key",
    "usb_profile_key",
    "smb_profile_key",
    "repo_conf_key",
    "conf_key",
}


def _raw_rows(config: dict) -> list[dict[str, Any]]:
    path = repositories_file(config)
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("repositories"), list):
        raise ValueError("Repository inventory is invalid")
    return [row for row in payload["repositories"] if isinstance(row, dict)]


def detect(config: dict) -> dict[str, Any]:
    rows = _raw_rows(config)
    affected = {
        str(row.get("repository_key") or ""): sorted(LEGACY_FIELDS.intersection(row))
        for row in rows
        if LEGACY_FIELDS.intersection(row)
    }
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(affected),
        "repository_file": str(repositories_file(config)),
        "affected_repositories": affected,
    }


def apply(config: dict) -> dict[str, Any]:
    detected = detect(config)
    if not detected["required"]:
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "not_required",
            "details": detected,
        }
    store = read_repository_store(config, preserve_legacy=True)
    write_repository_store(config, store)
    remaining = detect(config)
    if remaining["required"]:
        raise RuntimeError("Repository compatibility fields could not be removed")
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied",
        "details": {
            **detected,
            "removed_fields": sum(len(fields) for fields in detected["affected_repositories"].values()),
        },
    }
