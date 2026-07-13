"""Durable audit helpers shared by startup migrations and the registry."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inventory_store import atomic_write_json, inventory_lock


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def config_dir(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    root = base.parent if base.name == "scripts" else base
    return root / "config"


def state_file(config: dict) -> Path:
    return config_dir(config) / "migration-state.json"


def log_file(config: dict) -> Path:
    return config_dir(config) / "migrations.log.jsonl"


def read_state(config: dict) -> dict[str, Any]:
    path = state_file(config)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_pending_state(
    config: dict,
    *,
    migration_id: str,
    introduced_in: str,
    run_id: str,
    source_classification: str,
) -> None:
    directory = config_dir(config)
    with inventory_lock(directory):
        previous = read_state(config)
        migrations = previous.get("migrations") if isinstance(previous.get("migrations"), dict) else {}
        payload = {
            "schema_version": 2,
            "last_run": {
                "timestamp": now(),
                "success": False,
                "message": f"{migration_id} is running",
                "reason_code": "migration_pending",
                "reason_text": "Startup migration is running",
                "details": {"migration_id": migration_id, "run_id": run_id},
            },
            "migrations": {
                **migrations,
                migration_id: {
                    "state": "pending",
                    "checked_at": now(),
                    "source": "startup_registry",
                    "details": {
                        "migration_id": migration_id,
                        "introduced_in": introduced_in,
                        "runner": "central_migration_registry",
                        "run_id": run_id,
                        "source_classification": source_classification,
                    },
                },
            },
        }
        atomic_write_json(state_file(config), payload)


def append_event(config: dict, event: dict[str, Any]) -> None:
    """Append one sanitized migration event and fsync it before returning."""
    directory = config_dir(config)
    payload = {"schema_version": 2, "timestamp": now(), **event}
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    with inventory_lock(directory):
        path = log_file(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)

