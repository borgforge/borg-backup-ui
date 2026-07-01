"""
Central notification events for Borg Backup UI.

Transport functions live in lib.notifications. This module owns the decision
which event goes to which configured channel.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from lib.notifications import MailConfig, NtfyConfig, notify, send_backup_log_mail, send_mail, send_ntfy

logger = logging.getLogger(__name__)

DEFAULT_EMAIL_EVENTS = {"backup_failed"}
DEFAULT_UNRAID_EVENTS = {"backup_success", "backup_warning", "backup_failed", "backup_skipped"}
DEFAULT_REMINDER_INTERVAL_HOURS = 24

NTFY_EVENT_ALIASES = {
    # Existing ntfy installs used backup_failed for Borg warnings.
    "backup_warning": {"backup_warning", "backup_failed"},
}


@dataclass
class NotificationEvent:
    event_type: str
    title: str
    message: str
    severity: str = "info"
    job_name: str = "Borg Backup UI"
    job_key: str = ""
    status: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    duration_seconds: int = 0
    repository: str = ""
    log_file: str = ""
    backup_type: str = ""
    date_tag: str = ""
    exit_code: int = 0
    source: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def event_set(config: dict, key: str, default: set[str]) -> set[str]:
    raw = str(config.get(key, "") or "").strip()
    if not raw:
        return set(default)
    return {item.strip() for item in raw.split(",") if item.strip()}


def reminder_interval_hours(config: dict) -> int:
    raw = str(config.get("NOTIFY_REMINDER_INTERVAL_HOURS", str(DEFAULT_REMINDER_INTERVAL_HOURS)) or "")
    try:
        return max(1, int(raw.strip()))
    except ValueError:
        return DEFAULT_REMINDER_INTERVAL_HOURS


def send_event(
    config: dict,
    event: NotificationEvent,
    *,
    mail_config: Optional[MailConfig] = None,
    ntfy_config: Optional[NtfyConfig] = None,
) -> dict[str, bool]:
    """Send one logical event to all configured channels, best-effort."""
    results = {"unraid": False, "email": False, "ntfy": False}
    event_type = str(event.event_type or "").strip()
    if not event_type:
        return results

    if event_type in event_set(config, "NOTIFY_UNRAID_EVENTS", DEFAULT_UNRAID_EVENTS):
        results["unraid"] = notify(
            level=event.severity,
            subject=event.title,
            description=event.message,
            job_name=event.job_name or "Borg Backup UI",
        )

    if mail_config is not None and event_type in event_set(config, "NOTIFY_EMAIL_EVENTS", DEFAULT_EMAIL_EVENTS):
        results["email"] = _send_event_mail(mail_config, event)

    if ntfy_config is not None:
        results["ntfy"] = _send_event_ntfy(ntfy_config, event)

    logger.info(
        "Notification event processed (event=%s source=%s unraid=%s email=%s ntfy=%s)",
        event_type,
        event.source or "-",
        results["unraid"],
        results["email"],
        results["ntfy"],
    )
    return results


def _send_event_mail(config: MailConfig, event: NotificationEvent) -> bool:
    if event.event_type == "backup_failed" and event.log_file:
        return send_backup_log_mail(
            config=config,
            backup_type=event.backup_type or event.job_key or "backup",
            date_tag=event.date_tag or datetime.now().strftime("%Y-%m-%d"),
            exit_code=int(event.exit_code or 2),
            duration_seconds=max(0, int(event.duration_seconds or 0)),
            log_file=Path(event.log_file),
        )
    return send_mail(config, event.title, event.message)


def _send_event_ntfy(config: NtfyConfig, event: NotificationEvent) -> bool:
    allowed = set(config.events or set())
    aliases = NTFY_EVENT_ALIASES.get(event.event_type, {event.event_type})
    if allowed and not (allowed & aliases):
        logger.info("ntfy event skipped by configuration: %s", event.event_type)
        return False
    return send_ntfy(config, event.event_type, _ntfy_title(config, event.title), event.message)


def _ntfy_title(config: NtfyConfig, title: str) -> str:
    prefix = str(config.name or "Borg Backup UI").strip() or "Borg Backup UI"
    text = str(title or "").strip()
    for marker in ("Borg Backup UI:", "Borg Backup UI -"):
        if text.startswith(marker):
            text = text[len(marker):].strip()
            break
    if not text:
        text = "Notification"
    if text.lower().startswith(prefix.lower()):
        return text
    return f"{prefix} - {text}"


def notification_state_path(config: dict) -> Path:
    root = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    return root / "config" / "notification-state.json"


def read_notification_state(config: dict) -> dict[str, Any]:
    path = notification_state_path(config)
    if not path.exists():
        return {"schema_version": 1, "last_sent": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw.setdefault("schema_version", 1)
            if not isinstance(raw.get("last_sent"), dict):
                raw["last_sent"] = {}
            return raw
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {"schema_version": 1, "last_sent": {}}


def write_notification_state(config: dict, state: dict[str, Any]) -> None:
    path = notification_state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "last_sent": state.get("last_sent") if isinstance(state.get("last_sent"), dict) else {},
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def reminder_key(event_type: str, job_key: str, due_marker: str = "") -> str:
    marker = str(due_marker or "").strip() or "current"
    return f"{event_type}:{job_key}:{marker}"


def reminder_allowed(config: dict, key: str, *, now: float | None = None) -> bool:
    state = read_notification_state(config)
    sent = state.get("last_sent") if isinstance(state.get("last_sent"), dict) else {}
    previous = sent.get(key)
    if previous is None:
        return True
    try:
        previous_ts = float(previous)
    except (TypeError, ValueError):
        return True
    interval_seconds = reminder_interval_hours(config) * 3600
    return (now if now is not None else time.time()) - previous_ts >= interval_seconds


def mark_reminder_sent(config: dict, key: str, *, now: float | None = None) -> None:
    state = read_notification_state(config)
    sent = state.get("last_sent") if isinstance(state.get("last_sent"), dict) else {}
    sent[key] = int(now if now is not None else time.time())
    state["last_sent"] = sent
    write_notification_state(config, state)


def clear_reminder_prefix(config: dict, prefix: str) -> None:
    state = read_notification_state(config)
    sent = state.get("last_sent") if isinstance(state.get("last_sent"), dict) else {}
    changed = False
    for key in list(sent.keys()):
        if str(key).startswith(prefix):
            sent.pop(key, None)
            changed = True
    if changed:
        state["last_sent"] = sent
        write_notification_state(config, state)
