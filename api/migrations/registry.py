"""Central startup migration registry and runner."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import (
    canonical_data_model_v1,
    job_source_paths_v1,
    notification_events_v1,
    restore_history_v1,
    smb_protocol_auto_v1,
)
from .audit import append_event, config_dir as audit_config_dir, read_state

try:
    from ..security_utils import mask_secrets
except ImportError:  # Runtime/tests may import migrations directly from API_ROOT.
    from security_utils import mask_secrets

MIGRATIONS = [
    restore_history_v1,
    notification_events_v1,
    canonical_data_model_v1,
    job_source_paths_v1,
    smb_protocol_auto_v1,
]

FINAL_STATES = {"applied", "not_required", "not_applicable", "skipped"}


def _config_dir(config: dict):
    return audit_config_dir(config)


def read_central_migration_state(config: dict) -> dict[str, Any]:
    return read_state(config)


def _migration_entry(state: dict[str, Any], migration_id: str) -> dict[str, Any]:
    migrations = state.get("migrations") if isinstance(state.get("migrations"), dict) else {}
    entry = migrations.get(migration_id) if isinstance(migrations.get(migration_id), dict) else {}
    return entry


def _is_central_registry_result(entry: dict[str, Any]) -> bool:
    details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
    return str(details.get("runner") or "").strip() == "central_migration_registry"


def _normalize_status(result: dict[str, Any]) -> str:
    status = str(result.get("status") or result.get("previous_state") or "not_required").strip()
    if status == "skipped" and str(result.get("previous_state") or "").strip():
        return str(result.get("previous_state")).strip()
    return status or "not_required"


def _result_details(result: dict[str, Any]) -> dict[str, Any]:
    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    return {
        **details,
        "migration_id": str(result.get("migration_id") or details.get("migration_id") or ""),
        "introduced_in": str(result.get("introduced_in") or details.get("introduced_in") or ""),
        "runner": str(result.get("runner") or details.get("runner") or "central_migration_registry"),
    }


def _reason_for(results: dict[str, Any], applied: list[str], failed: list[str]) -> tuple[str, str]:
    if failed:
        return "error", "Startup migrations completed with errors"
    if not applied:
        return "no_changes", "No startup migrations required changes"
    return "startup_migrations_applied", "Startup migrations applied"


def _result_is_effective(result: dict[str, Any]) -> bool:
    status = str(result.get("status") or "").strip()
    if status == "failed":
        return True
    if status != "applied":
        return False
    details = _result_details(result)
    if details.get("updated_keys"):
        return True
    if int(details.get("imported") or 0) > 0:
        return True
    if details.get("removed_obsolete_tracking_files"):
        return True
    return True


def _write_state_and_log(config: dict, summary: dict[str, Any]) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    previous = read_central_migration_state(config)
    previous_migrations = previous.get("migrations") if isinstance(previous.get("migrations"), dict) else {}
    results = summary.get("results") if isinstance(summary.get("results"), dict) else {}
    applied = [str(item) for item in (summary.get("applied") if isinstance(summary.get("applied"), list) else [])]
    failed = [str(item) for item in (summary.get("failed") if isinstance(summary.get("failed"), list) else [])]
    reason_code, reason_text = _reason_for(results, applied, failed)
    messages = [str(item) for item in (summary.get("messages") if isinstance(summary.get("messages"), list) else [])]

    migrations = dict(previous_migrations)
    effective = bool(failed)
    for migration_id, result in results.items():
        if not isinstance(result, dict):
            continue
        migration_id_text = str(migration_id)
        status = _normalize_status(result)
        details = _result_details(result)
        previous_entry = previous_migrations.get(migration_id_text) if isinstance(previous_migrations.get(migration_id_text), dict) else {}
        if status in {"not_required", "skipped"} and str(previous_entry.get("state") or "").strip() in FINAL_STATES:
            migrations[migration_id_text] = previous_entry
        else:
            migrations[migration_id_text] = {
                "state": status,
                "checked_at": ts,
                "source": "startup_registry",
                "details": details,
            }
        effective = effective or _result_is_effective(result)

    last_run = {
        "timestamp": ts,
        "success": not failed,
        "message": "; ".join(messages) or "Startup migrations checked",
        "reason_code": reason_code,
        "reason_text": reason_text,
        "details": {"startup_migrations": summary},
    }
    if not effective and isinstance(previous.get("last_run"), dict):
        last_run = previous["last_run"]

    payload: dict[str, Any] = {
        "schema_version": 2,
        "last_run": last_run,
        "migrations": migrations,
    }

    state_file = _config_dir(config) / "migration-state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    from inventory_store import atomic_write_json
    atomic_write_json(state_file, payload)

    if effective:
        entry = {
            "event": "startup_migration",
            **last_run,
            "migrations": migrations,
        }
        try:
            append_event(config, entry)
        except (OSError, TypeError, ValueError):
            pass


def run_startup_migrations(config: dict) -> dict[str, Any]:
    state = read_central_migration_state(config)
    results: dict[str, Any] = {}
    applied = []
    skipped = []
    failed = []
    messages = []

    for migration in MIGRATIONS:
        migration_id = str(migration.MIGRATION_ID)
        previous = _migration_entry(state, migration_id)
        previous_state = str(previous.get("state") or "").strip()
        if previous_state in FINAL_STATES and _is_central_registry_result(previous):
            skipped.append(migration_id)
            results[migration_id] = {
                "migration_id": migration_id,
                "introduced_in": str(migration.INTRODUCED_IN),
                "runner": "central_migration_registry",
                "status": "skipped",
                "previous_state": previous_state,
                "details": previous.get("details", {}),
            }
            messages.append(f"{migration_id}=skipped(previous={previous_state})")
            continue

        try:
            detected = migration.detect(config)
        except Exception as exc:
            result = {
                "migration_id": migration_id,
                "introduced_in": str(migration.INTRODUCED_IN),
                "runner": "central_migration_registry",
                "status": "failed",
                "details": {
                    "error_type": type(exc).__name__,
                    "error": mask_secrets(str(exc))[:500],
                    "failed_phase": "detect",
                },
            }
            results[migration_id] = result
            failed.append(migration_id)
            messages.append(f"{migration_id}=failed")
            continue
        if not bool(detected.get("required")):
            skipped.append(migration_id)
            results[migration_id] = {
                "migration_id": migration_id,
                "introduced_in": str(migration.INTRODUCED_IN),
                "runner": "central_migration_registry",
                "status": "not_required",
                "details": detected,
            }
            messages.append(f"{migration_id}=not_required")
            continue

        try:
            result = migration.apply(config)
        except Exception as exc:
            result = {
                "migration_id": migration_id,
                "introduced_in": str(migration.INTRODUCED_IN),
                "runner": "central_migration_registry",
                "status": "failed",
                "details": {
                    "error_type": type(exc).__name__,
                    "error": mask_secrets(str(exc))[:500],
                    "failed_phase": "apply",
                },
            }
        results[migration_id] = result
        status = str(result.get("status") or "")
        if status == "failed":
            failed.append(migration_id)
        elif status == "applied":
            applied.append(migration_id)
        else:
            skipped.append(migration_id)
        messages.append(f"{migration_id}={status}")

    summary = {
        "status": "failed" if failed else "ok",
        "applied": applied,
        "skipped": skipped,
        "failed": failed,
        "messages": messages,
        "results": results,
    }
    _write_state_and_log(config, summary)
    return summary
