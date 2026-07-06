"""Migration: move legacy completed restore runs into restore-history storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MIGRATION_ID = "restore_history_v1"
INTRODUCED_IN = "2026.06.29.1544"
DESCRIPTION = "Move completed restore runs from restore-runs.json into restore-history."


def _read_legacy_runs(config: dict) -> tuple[Path, dict[str, dict]]:
    from restore_api import _restore_runs_file

    fp = _restore_runs_file(config)
    if not fp.exists():
        return fp, {}
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fp, {}
    runs = raw.get("runs") if isinstance(raw, dict) else {}
    if not isinstance(runs, dict):
        return fp, {}
    return fp, {str(rid): run for rid, run in runs.items() if isinstance(run, dict)}


def _split_runs(config: dict) -> tuple[Path, dict[str, dict], dict[str, dict], set[str]]:
    from restore_api import _is_restore_terminal, _read_history_index

    fp, runs = _read_legacy_runs(config)
    terminal = {
        rid: run for rid, run in runs.items()
        if _is_restore_terminal(run.get("state"))
    }
    active = {
        rid: run for rid, run in runs.items()
        if not _is_restore_terminal(run.get("state"))
    }
    known_history_ids = {
        str(row.get("restore_id") or "").strip()
        for row in _read_history_index(config)
        if str(row.get("restore_id") or "").strip()
    }
    return fp, terminal, active, known_history_ids


def _obsolete_internal_tracking_files(config: dict) -> list[Path]:
    from restore_api import _restore_history_dir

    base = _restore_history_dir(config)
    return [
        path for path in [
            base / "migration-state.json",
            base / "migrations.log.jsonl",
        ]
        if path.exists()
    ]


def detect(config: dict) -> dict[str, Any]:
    fp, terminal, active, known_history_ids = _split_runs(config)
    pending = {
        rid: run for rid, run in terminal.items()
        if str(run.get("restore_id") or rid).strip() not in known_history_ids
    }
    already_imported = len(terminal) - len(pending)
    obsolete_files = _obsolete_internal_tracking_files(config)
    required = bool(pending or already_imported or obsolete_files)
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": required,
        "source_file": str(fp),
        "terminal_count": len(terminal),
        "pending_count": len(pending),
        "active_kept": len(active),
        "already_imported": already_imported,
        "obsolete_tracking_files": [str(path) for path in obsolete_files],
        "reason": (
            "restore-runs.json contains completed restore runs"
            if pending
            else (
                "restore-runs.json contains already imported completed restore runs"
                if already_imported else (
                    "Obsolete restore-history migration tracking files exist"
                    if obsolete_files else "No legacy restore runs found"
                )
            )
        ),
    }


def apply(config: dict) -> dict[str, Any]:
    from restore_api import _persist_restore_runs, _record_restore_history

    fp, terminal, active, known_history_ids = _split_runs(config)
    pending = {
        rid: run for rid, run in terminal.items()
        if str(run.get("restore_id") or rid).strip() not in known_history_ids
    }
    details: dict[str, Any] = {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "source_file": str(fp),
        "imported": 0,
        "active_kept": len(active),
        "already_imported": len(terminal) - len(pending),
        "removed_obsolete_tracking_files": [],
        "errors": [],
    }
    for rid, run in pending.items():
        try:
            _record_restore_history(config, run, "restore_history_v1")
            details["imported"] += 1
        except Exception as exc:
            details["errors"].append({"restore_id": rid, "error": str(exc)})

    for path in _obsolete_internal_tracking_files(config):
        try:
            path.unlink()
            details["removed_obsolete_tracking_files"].append(str(path))
        except OSError as exc:
            details["errors"].append({"path": str(path), "error": str(exc)})

    if terminal and not details["errors"]:
        # Keep only non-terminal runs in the runtime file after migration.
        from restore_api import _RESTORE_RUNS
        _RESTORE_RUNS.clear()
        _RESTORE_RUNS.update(active)
        _persist_restore_runs(config)

    status = "failed" if details["errors"] else (
        "applied" if details["imported"] or details["removed_obsolete_tracking_files"] else "not_required"
    )
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": status,
        "details": details,
    }
