"""Central startup migration registry and runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import restore_history_v1

MIGRATIONS = [
    restore_history_v1,
]

FINAL_STATES = {"applied", "not_required", "skipped"}


def _config_dir(config: dict) -> Path:
    return Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup") / "config"


def read_central_migration_state(config: dict) -> dict[str, Any]:
    fp = _config_dir(config) / "migration-state.json"
    if not fp.exists():
        return {}
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _migration_entry(state: dict[str, Any], migration_id: str) -> dict[str, Any]:
    migrations = state.get("migrations") if isinstance(state.get("migrations"), dict) else {}
    entry = migrations.get(migration_id) if isinstance(migrations.get(migration_id), dict) else {}
    return entry


def _is_central_registry_result(entry: dict[str, Any]) -> bool:
    details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
    return str(details.get("runner") or "").strip() == "central_migration_registry"


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

        detected = migration.detect(config)
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
                "status": "failed",
                "details": {"error": str(exc)},
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

    return {
        "status": "failed" if failed else "ok",
        "applied": applied,
        "skipped": skipped,
        "failed": failed,
        "messages": messages,
        "results": results,
    }
