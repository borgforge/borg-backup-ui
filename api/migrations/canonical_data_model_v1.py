"""Baseline migration from legacy or partial installs to the canonical model."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inventory_store import atomic_write_bytes, inventory_lock
from repository_context import LEGACY_JOB_REPOSITORY_FIELDS, resolve_job_repository_context
from repositories_api import read_repository_store, repositories_file
from storage_objects_api import _safe_local_storage_path, read_storage_store, storages_file

from . import (
    canonical_storage_profiles_v1,
    repository_contract_cleanup_v1,
    repository_objects_v1,
    repository_objects_v2,
    repository_objects_v3,
    repository_objects_v4,
    repository_runtime_v1,
    storage_objects_v1,
    storage_objects_v2,
)
from .audit import append_event, config_dir, now, read_state, write_pending_state


MIGRATION_ID = "canonical_data_model_v1"
INTRODUCED_IN = "2026.07.11.1700"
SUPERSEDED_MIGRATIONS = [
    "repository_objects_v1",
    "repository_objects_v2",
    "repository_objects_v3",
    "repository_objects_v4",
    "storage_objects_v1",
    "storage_objects_v2",
    "repository_runtime_v1",
    "borg_keyfiles_v1",
    "canonical_storage_profiles_v1",
    "repository_contract_cleanup_v1",
]
PHASES = [
    repository_objects_v1,
    repository_objects_v2,
    repository_objects_v3,
    repository_objects_v4,
    storage_objects_v1,
    storage_objects_v2,
    repository_runtime_v1,
    canonical_storage_profiles_v1,
    repository_contract_cleanup_v1,
]


def _settings_file(config: dict) -> Path:
    return config_dir(config) / "settings.json"


def _jobs_dir(config: dict) -> Path:
    return config_dir(config) / "jobs"


def _conf_file(config: dict) -> Path:
    return config_dir(config) / "backup.conf"


def _job_files(config: dict) -> list[Path]:
    directory = _jobs_dir(config)
    return sorted(path for path in directory.glob("*.json") if path.is_file()) if directory.is_dir() else []


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root is not an object: {path.name}")
    return payload


def _source_classification(config: dict) -> str:
    state = read_state(config)
    migrations = state.get("migrations") if isinstance(state.get("migrations"), dict) else {}
    partial = any(str((migrations.get(key) or {}).get("state") or "") in {"applied", "pending", "failed"} for key in SUPERSEDED_MIGRATIONS)
    has_canonical = repositories_file(config).is_file() or storages_file(config).is_file()
    has_legacy = _settings_file(config).is_file() or any(
        any(field in _read_json(path) for field in LEGACY_JOB_REPOSITORY_FIELDS)
        for path in _job_files(config)
    )
    if partial:
        return "partial_test_install"
    if has_legacy:
        return "stable_legacy_install"
    if has_canonical:
        return "already_canonical"
    return "fresh_install"


def _phase_required(config: dict) -> tuple[list[str], list[dict[str, str]]]:
    required: list[str] = []
    errors: list[dict[str, str]] = []
    for phase in PHASES:
        try:
            detected = phase.detect(config)
        except Exception as exc:
            required.append(str(phase.MIGRATION_ID))
            errors.append({
                "phase": str(phase.MIGRATION_ID),
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            })
            continue
        if bool(detected.get("required")):
            required.append(str(phase.MIGRATION_ID))
    return required, errors


def _has_legacy_job_contract(config: dict) -> bool:
    return any(
        any(field in _read_json(path) for field in LEGACY_JOB_REPOSITORY_FIELDS)
        for path in _job_files(config)
    )


def _should_run_phase(config: dict, phase: Any) -> bool:
    required = bool(phase.detect(config).get("required"))
    # The first phase also repairs incomplete repository objects produced by an
    # interrupted earlier test build. Its own legacy detector only looked for
    # missing links, not missing passphrase or display metadata.
    if phase is repository_objects_v1 and _has_legacy_job_contract(config):
        return True
    return required


def detect(config: dict) -> dict[str, Any]:
    settings_exists = _settings_file(config).is_file()
    phases, detection_errors = _phase_required(config)
    try:
        source = _source_classification(config)
    except Exception as exc:
        source = "invalid_source"
        detection_errors.append({
            "phase": "source_classification",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        })
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(settings_exists or phases or detection_errors),
        "source_classification": source,
        "required_phases": phases,
        "detection_errors": detection_errors,
        "settings_file_present": settings_exists,
        "superseded_migrations": SUPERSEDED_MIGRATIONS,
    }


def _backup_targets(config: dict) -> list[Path]:
    targets = [
        _settings_file(config),
        storages_file(config),
        repositories_file(config),
        _conf_file(config),
        _jobs_dir(config),
        config_dir(config).parent / "borg-keys",
    ]
    return [path for path in targets if path.exists()]


def _create_backup(config: dict, run_id: str) -> tuple[Path, dict[str, str]]:
    backup_dir = config_dir(config) / "migration-backups" / f"{MIGRATION_ID}-{run_id}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, str] = {}
    root = config_dir(config).parent
    for source in _backup_targets(config):
        try:
            relative = source.relative_to(root)
        except ValueError:
            relative = Path(source.name)
        target = backup_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        manifest[str(source)] = str(target)
    atomic_write_bytes(
        backup_dir / "manifest.json",
        (json.dumps({"run_id": run_id, "files": manifest}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return backup_dir, manifest


def _restore_backup(config: dict, manifest: dict[str, str], existed_before: set[str]) -> list[str]:
    managed = {
        str(_settings_file(config)),
        str(storages_file(config)),
        str(repositories_file(config)),
        str(_conf_file(config)),
        str(_jobs_dir(config)),
        str(config_dir(config).parent / "borg-keys"),
    }
    restored: list[str] = []
    for raw in managed:
        target = Path(raw)
        if raw not in existed_before and target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
    for raw_source, raw_backup in manifest.items():
        source, backup = Path(raw_source), Path(raw_backup)
        if source.exists():
            shutil.rmtree(source) if source.is_dir() else source.unlink()
        source.parent.mkdir(parents=True, exist_ok=True)
        if backup.is_dir():
            shutil.copytree(backup, source)
        else:
            shutil.copy2(backup, source)
        restored.append(str(source))
    return restored


def _validate(config: dict) -> dict[str, Any]:
    if _settings_file(config).exists():
        raise ValueError("Legacy settings.json still exists")
    storages = read_storage_store(config).get("storages", [])
    repositories = read_repository_store(config).get("repositories", [])
    storage_keys = {str(row.get("storage_key") or "") for row in storages}
    repository_keys = {str(row.get("repository_key") or "") for row in repositories}
    if "" in storage_keys or len(storage_keys) != len(storages):
        raise ValueError("Storage IDs are missing or duplicated")
    for storage in storages:
        storage_key = str(storage.get("storage_key") or "")
        storage_type = str(storage.get("storage_type") or "").strip().lower()
        if storage_type not in {"local", "usb", "smb"}:
            continue
        path = str(storage.get("mount_path") or storage.get("base_path") or "")
        _safe_local_storage_path(path, field=f"Storage '{storage_key}' path")
    if "" in repository_keys or len(repository_keys) != len(repositories):
        raise ValueError("Repository IDs are missing or duplicated")
    for repository in repositories:
        key = str(repository.get("repository_key") or "")
        if str(repository.get("storage_key") or "") not in storage_keys:
            raise ValueError(f"Repository '{key}' references an unknown storage")
        if not str(repository.get("encryption") or "").strip():
            raise ValueError(f"Repository '{key}' has no encryption metadata")
        if repository_contract_cleanup_v1.LEGACY_FIELDS.intersection(repository):
            raise ValueError(f"Repository '{key}' still contains legacy fields")
    jobs = []
    for path in _job_files(config):
        job = _read_json(path)
        key = str(job.get("job_key") or path.stem)
        if int(job.get("schema_version") or 0) < 2:
            raise ValueError(f"Job '{key}' does not use schema version 2")
        if any(field in job for field in LEGACY_JOB_REPOSITORY_FIELDS):
            raise ValueError(f"Job '{key}' still contains legacy repository fields")
        if str(job.get("repository_key") or "") not in repository_keys:
            raise ValueError(f"Job '{key}' references an unknown repository")
        resolve_job_repository_context(config, key, job=job)
        jobs.append(key)
    return {
        "storage_count": len(storages),
        "repository_count": len(repositories),
        "job_count": len(jobs),
        "validated_jobs": sorted(jobs),
    }


def _object_snapshot(config: dict) -> dict[str, dict[str, str]]:
    storages = read_storage_store(config).get("storages", []) if storages_file(config).is_file() else []
    repositories = read_repository_store(config).get("repositories", []) if repositories_file(config).is_file() else []
    jobs: dict[str, str] = {}
    for path in _job_files(config):
        try:
            payload = _read_json(path)
            key = str(payload.get("job_key") or path.stem)
            jobs[key] = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        except Exception:
            jobs[path.stem] = "<unreadable>"
    return {
        "storage_ids": {
            str(row.get("storage_key")): json.dumps(row, sort_keys=True, ensure_ascii=False)
            for row in storages if str(row.get("storage_key") or "")
        },
        "repository_ids": {
            str(row.get("repository_key")): json.dumps(row, sort_keys=True, ensure_ascii=False)
            for row in repositories if str(row.get("repository_key") or "")
        },
        "job_ids": jobs,
    }


def _object_changes(before: dict[str, dict[str, str]], after: dict[str, dict[str, str]]) -> dict[str, dict[str, list[str]]]:
    changes: dict[str, dict[str, list[str]]] = {}
    for key in ("storage_ids", "repository_ids", "job_ids"):
        old_rows, new_rows = before.get(key, {}), after.get(key, {})
        old, new = set(old_rows), set(new_rows)
        changes[key] = {
            "created": sorted(new - old),
            "preserved": sorted(new & old),
            "updated": sorted(item for item in new & old if old_rows[item] != new_rows[item]),
            "removed": sorted(old - new),
        }
    return changes


def apply(config: dict) -> dict[str, Any]:
    detected = detect(config)
    if not detected["required"]:
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "not_applicable",
            "details": detected,
        }
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    source = str(detected["source_classification"])
    write_pending_state(
        config,
        migration_id=MIGRATION_ID,
        introduced_in=INTRODUCED_IN,
        run_id=run_id,
        source_classification=source,
    )
    append_event(config, {
        "event": "migration_started",
        "migration_id": MIGRATION_ID,
        "run_id": run_id,
        "started_at": now(),
        "source_classification": source,
        "required_phases": detected["required_phases"],
    })
    existed_before = {str(path) for path in _backup_targets(config)}
    before_ids = _object_snapshot(config)
    backup_dir: Path | None = None
    manifest: dict[str, str] = {}
    phase_results: list[dict[str, Any]] = []
    current_phase = "backup"
    try:
        backup_dir, manifest = _create_backup(config, run_id)
        append_event(config, {
            "event": "migration_backup_created",
            "migration_id": MIGRATION_ID,
            "run_id": run_id,
            "backup_directory": str(backup_dir),
            "affected_files": sorted(manifest),
        })
        with inventory_lock(config_dir(config)):
            phase_config = {**config, "_CANONICAL_BASELINE_BACKUP_DIR": str(backup_dir)}
            for phase in PHASES:
                phase_id = str(phase.MIGRATION_ID)
                current_phase = phase_id
                required = _should_run_phase(config, phase)
                if not required:
                    phase_results.append({"phase": phase_id, "status": "not_required"})
                    continue
                append_event(config, {
                    "event": "migration_phase_started",
                    "migration_id": MIGRATION_ID,
                    "run_id": run_id,
                    "phase": phase_id,
                })
                result = phase.apply(phase_config)
                status = str(result.get("status") or "failed")
                if status == "failed":
                    error = str((result.get("details") or {}).get("error") or "Migration phase failed")
                    raise RuntimeError(f"{phase_id}: {error}")
                phase_results.append({"phase": phase_id, "status": status})
                append_event(config, {
                    "event": "migration_phase_completed",
                    "migration_id": MIGRATION_ID,
                    "run_id": run_id,
                    "phase": phase_id,
                    "status": status,
                })
            _settings_file(config).unlink(missing_ok=True)
            current_phase = "validation"
            validation = _validate(config)
            after_ids = _object_snapshot(config)
    except Exception as exc:
        restored: list[str] = []
        rollback_status = "failed"
        try:
            restored = _restore_backup(config, manifest, existed_before) if manifest else []
            rollback_status = "completed"
        except Exception as rollback_exc:
            append_event(config, {
                "event": "migration_rollback_failed",
                "migration_id": MIGRATION_ID,
                "run_id": run_id,
                "error_type": type(rollback_exc).__name__,
                "error": str(rollback_exc)[:500],
            })
        append_event(config, {
            "event": "migration_failed",
            "migration_id": MIGRATION_ID,
            "run_id": run_id,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "rollback_status": rollback_status,
            "restored_files": restored,
        })
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "failed",
            "details": {
                "run_id": run_id,
                "source_classification": source,
                "failed_phase": current_phase,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
                "rollback_status": rollback_status,
                "backup_directory": str(backup_dir or ""),
            },
        }
    append_event(config, {
        "event": "migration_completed",
        "migration_id": MIGRATION_ID,
        "run_id": run_id,
        "finished_at": now(),
        "status": "applied",
        "source_classification": source,
        "backup_directory": str(backup_dir or ""),
        "phase_results": phase_results,
        "validation": validation,
        "object_changes": _object_changes(before_ids, after_ids),
    })
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied",
        "details": {
            "run_id": run_id,
            "source_classification": source,
            "backup_directory": str(backup_dir or ""),
            "phase_results": phase_results,
            "validation": validation,
            "object_changes": _object_changes(before_ids, after_ids),
            "affected_files": sorted(manifest),
            "removed_files": [str(_settings_file(config))],
            "superseded_migrations": SUPERSEDED_MIGRATIONS,
        },
    }
