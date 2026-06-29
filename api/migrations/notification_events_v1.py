"""Migration: add central notification event configuration."""

from __future__ import annotations

from typing import Any

MIGRATION_ID = "notification_events_v1"
INTRODUCED_IN = "2026.06.29.2000"
DESCRIPTION = "Add central notification event configuration and reminder interval."

DEFAULT_EMAIL_EVENTS = "backup_failed"
DEFAULT_UNRAID_EVENTS = "backup_success,backup_warning,backup_failed,backup_skipped"
DEFAULT_REMINDER_INTERVAL_HOURS = "24"
DEFAULT_BACKUP_OVERDUE_TOLERANCE_HOURS = "6"


def _events(raw: str) -> list[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _join_events(items: list[str]) -> str:
    seen = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return ",".join(seen)


def detect(config: dict) -> dict[str, Any]:
    from config_api import read_raw_conf

    conf = read_raw_conf(config)
    missing = [
        key for key in (
            "NOTIFY_EMAIL_EVENTS",
            "NOTIFY_UNRAID_EVENTS",
            "NOTIFY_REMINDER_INTERVAL_HOURS",
            "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS",
        )
        if key not in conf
    ]
    ntfy_events = _events(str(conf.get("NTFY_EVENTS", "")))
    needs_warning_alias = "backup_failed" in ntfy_events and "backup_warning" not in ntfy_events
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(missing or needs_warning_alias),
        "missing_keys": missing,
        "ntfy_warning_alias_required": needs_warning_alias,
        "reason": "Central notification keys are missing" if missing else (
            "ntfy backup warning alias is missing" if needs_warning_alias else "Notification configuration is current"
        ),
    }


def apply(config: dict) -> dict[str, Any]:
    from config_api import read_raw_conf, write_conf

    conf = read_raw_conf(config)
    updates: dict[str, str] = {}
    if "NOTIFY_EMAIL_EVENTS" not in conf:
        updates["NOTIFY_EMAIL_EVENTS"] = DEFAULT_EMAIL_EVENTS
    if "NOTIFY_UNRAID_EVENTS" not in conf:
        updates["NOTIFY_UNRAID_EVENTS"] = DEFAULT_UNRAID_EVENTS
    if "NOTIFY_REMINDER_INTERVAL_HOURS" not in conf:
        updates["NOTIFY_REMINDER_INTERVAL_HOURS"] = DEFAULT_REMINDER_INTERVAL_HOURS
    if "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS" not in conf:
        updates["NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS"] = DEFAULT_BACKUP_OVERDUE_TOLERANCE_HOURS

    ntfy_events = _events(str(conf.get("NTFY_EVENTS", "")))
    if "backup_failed" in ntfy_events and "backup_warning" not in ntfy_events:
        updates["NTFY_EVENTS"] = _join_events(ntfy_events + ["backup_warning"])

    changed = write_conf(config, updates, snapshot_reason="Notification events migration") if updates else False
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied" if changed else "not_required",
        "details": {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "updated_keys": sorted(updates.keys()),
        },
    }
