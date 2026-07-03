"""Migration: import legacy script-only backup jobs into JSON metadata."""

from __future__ import annotations

from typing import Any

MIGRATION_ID = "legacy_script_jobs_v1"
INTRODUCED_IN = "2026.07.03.0000"
DESCRIPTION = "Import legacy borg_backup_*.py jobs into canonical job metadata."


def detect(config: dict) -> dict[str, Any]:
    from jobs_api import detect_legacy_script_jobs

    detected = detect_legacy_script_jobs(config)
    pending = list(detected.get("pending") or [])
    skipped = list(detected.get("skipped") or [])
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(pending),
        "pending_count": len(pending),
        "skipped_count": len(skipped),
        "pending_jobs": pending,
        "skipped_scripts": skipped,
        "reason": (
            "Legacy script-only jobs require metadata import"
            if pending else "No legacy script-only jobs found"
        ),
    }


def apply(config: dict) -> dict[str, Any]:
    from jobs_api import migrate_legacy_script_jobs

    details = migrate_legacy_script_jobs(config)
    errors = list(details.get("errors") or [])
    migrated = list(details.get("migrated") or [])
    status = "failed" if errors else ("applied" if migrated else "not_required")
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": status,
        "details": {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "migrated_count": len(migrated),
            "skipped_count": len(details.get("skipped") or []),
            "migrated_jobs": migrated,
            "skipped_scripts": details.get("skipped") or [],
            "errors": errors,
        },
    }
