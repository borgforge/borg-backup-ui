"""Central startup migration registry and runner."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from . import canonical_backup_conf_v1
from .audit import (
    append_event,
    config_dir as audit_config_dir,
    log_file as audit_log_file,
    read_state,
)

try:
    from ..security_utils import mask_secrets
except ImportError:  # Runtime/tests may import migrations directly from API_ROOT.
    from security_utils import mask_secrets

MIGRATIONS = [
    canonical_backup_conf_v1,
]

FINAL_STATES = {"applied", "not_required", "not_applicable", "skipped"}
APPLY_STATES = FINAL_STATES | {"failed"}
PROVEN_APPLIED_EVENTS = {"migration_applied", "migration_completed"}


class MigrationContractError(RuntimeError):
    """Raised when a migration does not honor the registry return contract."""


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


def _failure_result(migration: Any, phase: str, exc: Exception) -> dict[str, Any]:
    return {
        "migration_id": str(migration.MIGRATION_ID),
        "introduced_in": str(migration.INTRODUCED_IN),
        "runner": "central_migration_registry",
        "status": "failed",
        "details": {
            "error_type": type(exc).__name__,
            "error": mask_secrets(str(exc))[:500],
            "failed_phase": phase,
        },
    }


def _validate_detection(migration_id: str, detected: Any) -> dict[str, Any]:
    if not isinstance(detected, dict):
        raise MigrationContractError(
            f"Migration {migration_id} detect() must return a mapping."
        )
    if not isinstance(detected.get("required"), bool):
        raise MigrationContractError(
            f"Migration {migration_id} detect() must return a boolean required field."
        )
    return detected


def _validate_apply_result(migration: Any, result: Any) -> dict[str, Any]:
    migration_id = str(migration.MIGRATION_ID)
    if not isinstance(result, dict):
        raise MigrationContractError(
            f"Migration {migration_id} apply() must return a mapping."
        )
    status = str(result.get("status") or "").strip()
    if status not in APPLY_STATES:
        raise MigrationContractError(
            f"Migration {migration_id} apply() returned unsupported status {status or '<empty>'}."
        )
    reported_migration_id = str(result.get("migration_id") or migration_id).strip()
    if reported_migration_id != migration_id:
        raise MigrationContractError(
            f"Migration {migration_id} apply() reported mismatched migration_id "
            f"{reported_migration_id or '<empty>'}."
        )
    normalized = {
        **result,
        "migration_id": migration_id,
        "introduced_in": str(result.get("introduced_in") or migration.INTRODUCED_IN),
        "runner": "central_migration_registry",
        "status": status,
    }
    if status == "failed":
        details = result.get("details") if isinstance(result.get("details"), dict) else {}
        normalized["details"] = {
            **details,
            "error_type": str(details.get("error_type") or "MigrationReportedFailure"),
            "error": mask_secrets(
                str(details.get("error") or "Migration reported failure without error details.")
            )[:500],
            "failed_phase": str(details.get("failed_phase") or "apply"),
        }
    return normalized


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


def _remember_earliest_timestamp(
    applied_at: dict[str, str], migration_id: Any, timestamp: Any
) -> None:
    migration_id_text = str(migration_id or "").strip()
    timestamp_text = str(timestamp or "").strip()
    if not migration_id_text or not timestamp_text:
        return
    previous = applied_at.get(migration_id_text)
    if not previous or timestamp_text < previous:
        applied_at[migration_id_text] = timestamp_text


def _read_proven_applied_times(config: dict) -> dict[str, str]:
    """Read original application times only from explicit success audit events."""
    path = audit_log_file(config)
    if not path.is_file():
        return {}

    applied_at: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}

    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        event_name = str(event.get("event") or "").strip()
        timestamp = event.get("timestamp")
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        if event_name in PROVEN_APPLIED_EVENTS:
            _remember_earliest_timestamp(
                applied_at,
                event.get("migration_id") or details.get("migration_id"),
                timestamp,
            )
            continue

        if event_name != "startup_migration" or event.get("success") is not True:
            continue
        startup = details.get("startup_migrations")
        if not isinstance(startup, dict):
            continue
        applied = startup.get("applied") if isinstance(startup.get("applied"), list) else []
        for migration_id in applied:
            _remember_earliest_timestamp(applied_at, migration_id, timestamp)

    return applied_at


def _write_state_and_log(config: dict, summary: dict[str, Any]) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    previous = read_central_migration_state(config)
    previous_migrations = previous.get("migrations") if isinstance(previous.get("migrations"), dict) else {}
    results = summary.get("results") if isinstance(summary.get("results"), dict) else {}
    applied = [str(item) for item in (summary.get("applied") if isinstance(summary.get("applied"), list) else [])]
    failed = [str(item) for item in (summary.get("failed") if isinstance(summary.get("failed"), list) else [])]
    reason_code, reason_text = _reason_for(results, applied, failed)
    messages = [str(item) for item in (summary.get("messages") if isinstance(summary.get("messages"), list) else [])]
    proven_applied_times = _read_proven_applied_times(config)

    migrations = dict(previous_migrations)
    effective = bool(failed)
    for migration_id, result in results.items():
        if not isinstance(result, dict):
            continue
        migration_id_text = str(migration_id)
        result_status = str(result.get("status") or "").strip()
        status = _normalize_status(result)
        details = _result_details(result)
        previous_entry = previous_migrations.get(migration_id_text) if isinstance(previous_migrations.get(migration_id_text), dict) else {}
        previous_state = str(previous_entry.get("state") or "").strip()
        if result_status in {"not_required", "not_applicable", "skipped"} and previous_state in FINAL_STATES:
            preserved_entry = dict(previous_entry)
            if previous_state == "applied" and not str(preserved_entry.get("applied_at") or "").strip():
                recovered = proven_applied_times.get(migration_id_text)
                if recovered:
                    preserved_entry["applied_at"] = recovered
            preserved_entry["last_checked_at"] = ts
            migrations[migration_id_text] = preserved_entry
        else:
            entry = {
                "state": status,
                "checked_at": ts,
                "last_checked_at": ts,
                "source": "startup_registry",
                "details": details,
            }
            if status == "applied":
                entry["applied_at"] = str(previous_entry.get("applied_at") or ts)
            migrations[migration_id_text] = entry
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
        "schema_version": 3,
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
    blocked = []
    messages = []
    blocked_by = ""

    for migration in MIGRATIONS:
        migration_id = str(migration.MIGRATION_ID)
        if blocked_by:
            blocked.append(migration_id)
            results[migration_id] = {
                "migration_id": migration_id,
                "introduced_in": str(migration.INTRODUCED_IN),
                "runner": "central_migration_registry",
                "status": "blocked",
                "details": {
                    "blocked_by": blocked_by,
                    "reason": "A previous startup migration failed.",
                },
            }
            messages.append(f"{migration_id}=blocked(previous_failure={blocked_by})")
            continue

        previous = _migration_entry(state, migration_id)
        previous_state = str(previous.get("state") or "").strip()
        recheck_after_final = bool(getattr(migration, "RECHECK_AFTER_FINAL", False))
        if previous_state in FINAL_STATES and _is_central_registry_result(previous) and not recheck_after_final:
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
            detected = _validate_detection(migration_id, migration.detect(config))
        except Exception as exc:
            result = _failure_result(migration, "detect", exc)
            results[migration_id] = result
            failed.append(migration_id)
            blocked_by = migration_id
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
            result = _validate_apply_result(migration, migration.apply(config))
        except Exception as exc:
            result = _failure_result(migration, "apply", exc)
        results[migration_id] = result
        status = str(result.get("status") or "")
        if status == "failed":
            failed.append(migration_id)
            blocked_by = migration_id
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
        "blocked": blocked,
        "messages": messages,
        "results": results,
    }
    _write_state_and_log(config, summary)
    return summary
