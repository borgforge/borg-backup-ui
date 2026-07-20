"""Migration: normalize backup.conf to the version-owned canonical schema."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from config_api import canonical_backup_conf_plan
from inventory_store import atomic_write_bytes, inventory_lock
from security_utils import mask_secrets

from .audit import append_event, config_dir, write_pending_state


MIGRATION_ID = "canonical_backup_conf_v1"
INTRODUCED_IN = "2026.07.19.0000"


def _conf_file(config: dict):
    return config_dir(config) / "backup.conf"


def _legacy_schema_file(config: dict):
    return config_dir(config) / "backup.conf.example"


def detect(config: dict) -> dict[str, Any]:
    plan = canonical_backup_conf_plan(config)
    legacy_schema = _legacy_schema_file(config)
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(plan["changed"] or legacy_schema.is_file()),
        "missing_keys": list(plan["missing_keys"]),
        "unknown_keys": list(plan["unknown_keys"]),
        "reason": (
            "backup.conf or its legacy persistent schema copy needs canonicalization"
            if plan["changed"] or legacy_schema.is_file()
            else "backup.conf already matches the version-owned canonical schema"
        ),
        "legacy_schema_copy": str(legacy_schema) if legacy_schema.is_file() else "",
    }


def apply(config: dict) -> dict[str, Any]:
    source = _conf_file(config)
    legacy_schema = _legacy_schema_file(config)
    source.parent.mkdir(parents=True, exist_ok=True)

    # Keep detection, snapshot, rewrite, verification and rollback in one
    # inventory transaction so the snapshot always matches the migrated input.
    with inventory_lock(source.parent):
        current_content = source.read_text(encoding="utf-8") if source.is_file() else ""
        plan = canonical_backup_conf_plan(config, source_content=current_content)
        legacy_schema_existed = legacy_schema.is_file()
        if not plan["changed"] and not legacy_schema_existed:
            return {
                "migration_id": MIGRATION_ID,
                "introduced_in": INTRODUCED_IN,
                "runner": "central_migration_registry",
                "status": "not_required",
                "details": {"affected_files": [str(source)]},
            }

        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        backup_dir = config_dir(config) / "migration-backups" / f"{MIGRATION_ID}-{run_id}"
        backup_dir.mkdir(parents=True, exist_ok=False)
        backup_file = backup_dir / source.name
        legacy_schema_backup = backup_dir / "legacy-backup.conf.example"
        source_existed = source.is_file()
        if source_existed:
            atomic_write_bytes(backup_file, current_content.encode("utf-8"))
        if legacy_schema_existed:
            atomic_write_bytes(legacy_schema_backup, legacy_schema.read_bytes())

        affected_files = [str(source)]
        if legacy_schema_existed:
            affected_files.append(str(legacy_schema))

        manifest = {
            "schema_version": 1,
            "migration_id": MIGRATION_ID,
            "run_id": run_id,
            "source_file": str(source),
            "source_existed": source_existed,
            "legacy_schema_file": str(legacy_schema),
            "legacy_schema_existed": legacy_schema_existed,
            "missing_keys": list(plan["missing_keys"]),
            "removed_keys": list(plan["unknown_keys"]),
        }
        atomic_write_bytes(
            backup_dir / "manifest.json",
            (json.dumps(manifest, ensure_ascii=True, indent=2) + "\n").encode("utf-8"),
        )
        write_pending_state(
            config,
            migration_id=MIGRATION_ID,
            introduced_in=INTRODUCED_IN,
            run_id=run_id,
            source_classification="existing_backup_conf" if source_existed else "missing_backup_conf",
        )
        append_event(config, {
            "event": "migration_started",
            "migration_id": MIGRATION_ID,
            "run_id": run_id,
            "affected_files": affected_files,
            "backup_directory": str(backup_dir),
            "missing_keys": list(plan["missing_keys"]),
            "removed_keys": list(plan["unknown_keys"]),
        })

        try:
            if plan["changed"]:
                atomic_write_bytes(source, plan["content"].encode("utf-8"))
            if legacy_schema_existed:
                legacy_schema.unlink()
            verification = canonical_backup_conf_plan(config)
            if verification["changed"]:
                raise RuntimeError("Canonical backup.conf verification failed after write")
            if legacy_schema.exists():
                raise RuntimeError("Legacy persistent backup.conf schema still exists")
        except Exception as exc:
            if source_existed and backup_file.is_file():
                atomic_write_bytes(source, backup_file.read_bytes())
                rollback_status = "restored"
            elif not source_existed:
                source.unlink(missing_ok=True)
                rollback_status = "removed_created_file"
            else:
                rollback_status = "not_available"
            if legacy_schema_existed and legacy_schema_backup.is_file():
                atomic_write_bytes(legacy_schema, legacy_schema_backup.read_bytes())
            safe_error = mask_secrets(str(exc))[:1000]
            append_event(config, {
                "event": "migration_failed",
                "migration_id": MIGRATION_ID,
                "run_id": run_id,
                "error_type": type(exc).__name__,
                "error": safe_error,
                "rollback_status": rollback_status,
            })
            return {
                "migration_id": MIGRATION_ID,
                "introduced_in": INTRODUCED_IN,
                "runner": "central_migration_registry",
                "status": "failed",
                "details": {
                    "error_type": type(exc).__name__,
                    "error": safe_error,
                    "failed_phase": "apply",
                    "rollback_status": rollback_status,
                    "affected_files": affected_files,
                },
            }

        append_event(config, {
            "event": "migration_applied",
            "migration_id": MIGRATION_ID,
            "run_id": run_id,
            "affected_files": affected_files,
            "backup_directory": str(backup_dir),
            "added_keys": list(plan["missing_keys"]),
            "removed_keys": list(plan["unknown_keys"]),
        })
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "applied",
            "details": {
                "run_id": run_id,
                "added_keys": list(plan["missing_keys"]),
                "removed_keys": list(plan["unknown_keys"]),
                "affected_files": affected_files,
                "backup_directory": str(backup_dir),
                "legacy_schema_removed": legacy_schema_existed,
                "actions": [
                    "Rebuilt backup.conf from the version-owned canonical schema",
                    *(["Removed the obsolete persistent backup.conf.example copy"] if legacy_schema_existed else []),
                ],
            },
        }
