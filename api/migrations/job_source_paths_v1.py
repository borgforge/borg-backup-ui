"""Migration: replace ambiguous job path strings with canonical JSON arrays."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inventory_store import atomic_write_bytes, inventory_lock
from job_source_paths import (
    JOB_SCHEMA_VERSION,
    SourcePathValidationError,
    normalize_source_paths,
    upgrade_job_source_paths,
)

from .audit import append_event, config_dir, write_pending_state


MIGRATION_ID = "job_source_paths_v1"
INTRODUCED_IN = "2026.07.13.2200"


class SourcePathMigrationError(ValueError):
    """Legacy source paths cannot be converted without guessing."""


def _jobs_dir(config: dict) -> Path:
    return config_dir(config) / "jobs"


def _job_files(config: dict) -> list[Path]:
    directory = _jobs_dir(config)
    return sorted(path for path in directory.glob("*.json") if path.is_file()) if directory.is_dir() else []


def _read_job(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourcePathMigrationError(f"Job file is not readable JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise SourcePathMigrationError(f"Job file root is not an object: {path.name}")
    return payload


def _needs_migration(job: dict[str, Any]) -> bool:
    try:
        schema_version = int(job.get("schema_version") or 0)
    except (TypeError, ValueError):
        schema_version = 0
    return (
        schema_version < JOB_SCHEMA_VERSION
        or "paths" in job
        or not isinstance(job.get("source_paths"), list)
    )


def detect(config: dict) -> dict[str, Any]:
    # Source paths are the final job-schema step. Never create a mixed model
    # when the canonical repository/storage migration is still incomplete.
    from . import canonical_data_model_v1

    canonical = canonical_data_model_v1.detect(config)
    if bool(canonical.get("required")):
        raise SourcePathMigrationError(
            "The canonical data-model migration must complete successfully before job source paths can be migrated"
        )

    candidates: list[str] = []
    for path in _job_files(config):
        job = _read_job(path)
        if _needs_migration(job):
            candidates.append(str(job.get("job_key") or path.stem))
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(candidates),
        "candidate_count": len(candidates),
        "candidate_jobs": candidates,
    }


def apply(config: dict) -> dict[str, Any]:
    paths = _job_files(config)
    planned: list[tuple[Path, dict[str, Any], bytes]] = []
    failures: list[dict[str, str]] = []

    for path in paths:
        try:
            job = _read_job(path)
            if not _needs_migration(job):
                normalize_source_paths(job.get("source_paths"), field=f"Job '{path.stem}' source_paths")
                continue
            job_key = str(job.get("job_key") or path.stem)
            migrated = upgrade_job_source_paths(job, job_key=job_key)
            normalize_source_paths(migrated.get("source_paths"), field=f"Job '{job_key}' source_paths")
            planned.append((path, migrated, path.read_bytes()))
        except (OSError, SourcePathMigrationError, SourcePathValidationError, ValueError) as exc:
            failures.append({"job_file": path.name, "error": str(exc)[:1000]})

    if failures:
        error = failures[0]["error"]
        append_event(config, {
            "event": "migration_failed",
            "migration_id": MIGRATION_ID,
            "failed_phase": "source_path_conversion",
            "error": error,
            "failed_jobs": failures,
            "rollback_status": "not_required",
        })
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "failed",
            "details": {
                "failed_phase": "source_path_conversion",
                "error": error,
                "errors": [row["error"] for row in failures],
                "failed_jobs": failures,
                "rollback_status": "not_required",
                "actions": ["No job files were changed"],
            },
        }

    if not planned:
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "not_required",
            "details": {"migrated_jobs": [], "affected_files": []},
        }

    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    backup_dir = config_dir(config) / "migration-backups" / f"{MIGRATION_ID}-{run_id}"
    originals = {str(path): content for path, _job, content in planned}
    migrated_jobs = [str(job.get("job_key") or path.stem) for path, job, _content in planned]
    write_pending_state(
        config,
        migration_id=MIGRATION_ID,
        introduced_in=INTRODUCED_IN,
        run_id=run_id,
        source_classification="legacy_job_source_paths",
    )
    append_event(config, {
        "event": "migration_started",
        "migration_id": MIGRATION_ID,
        "run_id": run_id,
        "candidate_jobs": migrated_jobs,
    })

    try:
        with inventory_lock(config_dir(config)):
            backup_dir.mkdir(parents=True, exist_ok=False)
            for path, _job, original in planned:
                atomic_write_bytes(backup_dir / path.name, original)
            manifest = {
                "migration_id": MIGRATION_ID,
                "run_id": run_id,
                "affected_files": [str(path) for path, _job, _content in planned],
            }
            atomic_write_bytes(
                backup_dir / "manifest.json",
                (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            )
            for path, job, _original in planned:
                atomic_write_bytes(
                    path,
                    (json.dumps(job, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                )
            for path, _job, _original in planned:
                validated = _read_job(path)
                if _needs_migration(validated):
                    raise SourcePathMigrationError(f"Job '{path.stem}' still uses the legacy source-path model")
                normalize_source_paths(validated.get("source_paths"), field=f"Job '{path.stem}' source_paths")
    except Exception as exc:
        rollback_errors: list[str] = []
        with inventory_lock(config_dir(config)):
            for raw_path, content in originals.items():
                try:
                    atomic_write_bytes(Path(raw_path), content)
                except Exception as rollback_exc:
                    rollback_errors.append(f"{Path(raw_path).name}: {rollback_exc}")
        rollback_status = "completed" if not rollback_errors else "failed"
        append_event(config, {
            "event": "migration_failed",
            "migration_id": MIGRATION_ID,
            "run_id": run_id,
            "failed_phase": "write_or_validation",
            "error": str(exc)[:1000],
            "rollback_status": rollback_status,
            "rollback_errors": rollback_errors,
        })
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "failed",
            "details": {
                "run_id": run_id,
                "failed_phase": "write_or_validation",
                "error": str(exc)[:1000],
                "rollback_status": rollback_status,
                "rollback_errors": rollback_errors,
                "backup_directory": str(backup_dir),
            },
        }

    append_event(config, {
        "event": "migration_completed",
        "migration_id": MIGRATION_ID,
        "run_id": run_id,
        "migrated_jobs": migrated_jobs,
        "affected_files": [str(path) for path, _job, _content in planned],
        "backup_directory": str(backup_dir),
    })
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied",
        "details": {
            "run_id": run_id,
            "migrated_jobs": migrated_jobs,
            "migrated_count": len(migrated_jobs),
            "affected_files": [str(path) for path, _job, _content in planned],
            "backup_directory": str(backup_dir),
            "actions": [f"Migrated {len(migrated_jobs)} job source-path definition(s) to JSON arrays"],
        },
    }
