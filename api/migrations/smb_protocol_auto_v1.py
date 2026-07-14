"""Migration: replace the former implicit SMB 3.0 default with auto negotiation."""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from storage_objects_api import read_storage_store, storages_file, write_storage_store

from .audit import append_event, config_dir, write_pending_state


MIGRATION_ID = "smb_protocol_auto_v1"
INTRODUCED_IN = "2026.07.14.0000"


def _candidates(config: dict) -> list[str]:
    rows = read_storage_store(config).get("storages", [])
    return [
        str(row.get("storage_key") or "")
        for row in rows
        if str(row.get("location") or row.get("storage_type") or "").strip().lower() == "smb"
        and str(row.get("vers") or "").strip() == "3.0"
    ]


def detect(config: dict) -> dict[str, Any]:
    candidates = _candidates(config)
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(candidates),
        "candidate_count": len(candidates),
        "storage_keys": candidates,
        "reason": "Former implicit SMB 3.0 defaults require automatic SMB 2/3 negotiation" if candidates else "SMB protocol settings are current",
    }


def apply(config: dict) -> dict[str, Any]:
    candidates = set(_candidates(config))
    if not candidates:
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "not_required",
            "details": {"updated_storages": [], "affected_files": []},
        }

    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    source = storages_file(config)
    backup_dir = config_dir(config) / "migration-backups" / f"{MIGRATION_ID}-{run_id}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup_file = backup_dir / source.name
    if source.is_file():
        shutil.copy2(source, backup_file)
        backup_file.chmod(0o600)

    write_pending_state(
        config,
        migration_id=MIGRATION_ID,
        introduced_in=INTRODUCED_IN,
        run_id=run_id,
        source_classification="implicit_smb_3_0_default",
    )
    append_event(config, {
        "event": "migration_started",
        "migration_id": MIGRATION_ID,
        "run_id": run_id,
        "affected_files": [str(source)],
        "backup_directory": str(backup_dir),
        "storage_keys": sorted(candidates),
    })

    try:
        store = read_storage_store(config)
        updated: list[str] = []
        for row in store.get("storages", []):
            key = str(row.get("storage_key") or "")
            if key in candidates and str(row.get("vers") or "").strip() == "3.0":
                row["vers"] = "auto"
                updated.append(key)
        write_storage_store(config, store)
    except Exception as exc:
        if backup_file.is_file():
            shutil.copy2(backup_file, source)
        append_event(config, {
            "event": "migration_failed",
            "migration_id": MIGRATION_ID,
            "run_id": run_id,
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
            "rollback_status": "restored" if backup_file.is_file() else "not_available",
        })
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "failed",
            "details": {
                "error": str(exc)[:1000],
                "rollback_status": "restored" if backup_file.is_file() else "not_available",
                "affected_files": [str(source)],
            },
        }

    append_event(config, {
        "event": "migration_applied",
        "migration_id": MIGRATION_ID,
        "run_id": run_id,
        "updated_storages": sorted(updated),
        "affected_files": [str(source)],
        "backup_directory": str(backup_dir),
    })
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied",
        "details": {
            "run_id": run_id,
            "updated_storages": sorted(updated),
            "affected_files": [str(source)],
            "backup_directory": str(backup_dir),
            "actions": ["Changed the former implicit SMB 3.0 default to automatic SMB 2/3 negotiation"],
        },
    }
