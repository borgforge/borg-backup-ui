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

from lib.apprise_adapter import AppriseAdapterError, send_notification
from lib.notifications import MailConfig, NtfyConfig, notify, send_mail, send_ntfy

logger = logging.getLogger(__name__)

DEFAULT_EMAIL_EVENTS = {"backup_failed"}
DEFAULT_UNRAID_EVENTS = {"backup_success", "backup_warning", "backup_failed", "backup_skipped"}
DEFAULT_REMINDER_INTERVAL_HOURS = 24
DEFAULT_REMINDER_STATE_RETENTION_DAYS = 90
MAX_EMAIL_LOG_CHARS = 40_000

EVENT_ALIASES = {
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


@dataclass
class AppriseEventResult:
    delivered: bool = False
    delivered_profiles: list[str] = field(default_factory=list)


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
    results = {"unraid": False, "email": False, "ntfy": False, "apprise": False}
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

    apprise_result = _send_event_apprise(config, event)
    results["apprise"] = apprise_result.delivered

    if ntfy_config is not None:
        logger.info(
            "Notification event processed (event=%s source=%s unraid=%s email=%s native_ntfy=%s apprise=%s apprise_profiles=%s)",
            event_type,
            event.source or "-",
            results["unraid"],
            results["email"],
            results["ntfy"],
            results["apprise"],
            _log_list(apprise_result.delivered_profiles),
        )
    else:
        logger.info(
            "Notification event processed (event=%s source=%s unraid=%s email=%s apprise=%s apprise_profiles=%s)",
            event_type,
            event.source or "-",
            results["unraid"],
            results["email"],
            results["apprise"],
            _log_list(apprise_result.delivered_profiles),
        )
    return results


def _send_event_mail(config: MailConfig, event: NotificationEvent) -> bool:
    if event.log_file:
        return send_mail(config, event.title, _event_mail_with_log(event))
    return send_mail(config, event.title, event.message)


def _event_mail_with_log(event: NotificationEvent) -> str:
    parts = [event.message.rstrip()]
    parts.extend([
        "",
        "Log file:",
        str(event.log_file),
        "",
        "Log output:",
        _read_log_excerpt(Path(event.log_file)),
    ])
    return "\n".join(parts).rstrip() + "\n"


def _read_log_excerpt(log_file: Path) -> str:
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Log file is not readable: {exc}"

    if len(text) <= MAX_EMAIL_LOG_CHARS:
        return text.rstrip() or "(log file is empty)"

    return (
        f"(log output truncated to the last {MAX_EMAIL_LOG_CHARS} characters)\n"
        f"{text[-MAX_EMAIL_LOG_CHARS:].rstrip()}"
    )


def _send_event_ntfy(config: NtfyConfig, event: NotificationEvent) -> bool:
    allowed = set(config.events or set())
    aliases = EVENT_ALIASES.get(event.event_type, {event.event_type})
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


def _send_event_apprise(config: dict, event: NotificationEvent) -> AppriseEventResult:
    result = AppriseEventResult()
    for profile in apprise_event_profiles(config, event.event_type):
        profile_id = str(profile.get("id") or "").strip()
        url = _read_apprise_secret(config, profile_id)
        if not url:
            logger.info("Apprise event skipped because profile URL is missing: profile=%s", profile_id)
            continue
        delivered = _notify_apprise_profile(config, profile, url, event)
        result.delivered = result.delivered or delivered
        if delivered:
            result.delivered_profiles.append(_apprise_profile_log_name(profile))
    return result


def _apprise_profile_log_name(profile: dict[str, Any]) -> str:
    profile_id = str(profile.get("id") or "").strip()
    name = str(profile.get("name") or "").strip()
    if name and profile_id and name != profile_id:
        return f"{name} ({profile_id})"
    return name or profile_id or "-"


def _log_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def apprise_event_profiles(config: dict, event_type: str) -> list[dict[str, Any]]:
    """Return enabled Apprise profiles ready to receive the given event."""
    event = str(event_type or "").strip()
    if not event:
        return []
    aliases = EVENT_ALIASES.get(event, {event})
    profiles = []
    for row in _read_apprise_profiles(config):
        if not isinstance(row, dict):
            continue
        profile_id = str(row.get("id") or "").strip()
        if not profile_id or not bool(row.get("enabled", True)):
            continue
        selected = _profile_event_set(row.get("selected_events"))
        if selected and not (selected & aliases):
            continue
        if not _apprise_secret_path(config, profile_id).is_file():
            continue
        profiles.append(row)
    return profiles


def _profile_event_set(value: Any) -> set[str]:
    if isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw = value
    else:
        raw = []
    return {str(item or "").strip() for item in raw if str(item or "").strip()}


def _notify_apprise_profile(config: dict, profile: dict[str, Any], url: str, event: NotificationEvent) -> bool:
    profile_id = str(profile.get("id") or "").strip()
    name = str(profile.get("name") or profile_id or "Borg Backup UI").strip()
    timeout_seconds = _apprise_timeout(profile.get("timeout_seconds"))
    retry_policy = profile.get("retry_policy") if isinstance(profile.get("retry_policy"), dict) else {}
    attempts = _apprise_attempts(retry_policy.get("attempts") if isinstance(retry_policy, dict) else None)
    backoff = _apprise_backoff(retry_policy.get("backoff_seconds") if isinstance(retry_policy, dict) else None)

    for attempt in range(1, attempts + 1):
        try:
            result = send_notification(
                url,
                title=_apprise_title(name, event.title),
                body=event.message,
                timeout_seconds=timeout_seconds,
            )
        except AppriseAdapterError as exc:
            logger.warning(
                "Apprise notification failed to load runtime (profile=%s event=%s): %s",
                profile_id,
                event.event_type,
                _safe_error(exc),
            )
            return False
        except Exception as exc:  # noqa: BLE001 - channel delivery is best-effort
            logger.warning(
                "Apprise notification failed (profile=%s event=%s): %s",
                profile_id,
                event.event_type,
                _safe_error(exc),
            )
            result = None

        if result is not None and result.ok:
            return True

        message = _safe_error(getattr(result, "message", "") if result is not None else "")
        logger.warning(
            "Apprise notification was not delivered (profile=%s event=%s attempt=%s/%s timeout=%ss): %s",
            profile_id,
            event.event_type,
            attempt,
            attempts,
            timeout_seconds,
            message,
        )
        if attempt < attempts and backoff > 0:
            time.sleep(backoff)
    return False


def _apprise_title(profile_name: str, title: str) -> str:
    return _ntfy_title(NtfyConfig(name=profile_name), title)


def _apprise_timeout(value: Any) -> int:
    try:
        return max(1, min(300, int(str(value or "15").strip())))
    except (TypeError, ValueError):
        return 15


def _apprise_attempts(value: Any) -> int:
    try:
        return max(1, min(5, int(str(value or "1").strip())))
    except (TypeError, ValueError):
        return 1


def _apprise_backoff(value: Any) -> int:
    try:
        return max(0, min(3600, int(str(value or "0").strip())))
    except (TypeError, ValueError):
        return 0


def _apprise_profile_store_path(config: dict) -> Path:
    root = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    return root / "config" / "apprise-profiles.json"


def _apprise_secret_path(config: dict, profile_id: str) -> Path:
    root = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    return root / "secrets" / f".apprise-profile-{profile_id}.url"


def _read_apprise_profiles(config: dict) -> list[dict[str, Any]]:
    path = _apprise_profile_store_path(config)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Apprise profiles are not readable: %s", _safe_error(exc))
        return []
    rows = payload.get("profiles") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _read_apprise_secret(config: dict, profile_id: str) -> str:
    if not profile_id:
        return ""
    path = _apprise_secret_path(config, profile_id)
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        logger.warning("Apprise profile secret is not readable: %s", path.name)
        logger.debug("Apprise secret read error: %s", _safe_error(exc))
    return ""


def _safe_error(value: BaseException | str) -> str:
    text = str(value or "").strip()
    return text[:500] if text else "unknown error"


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


def cleanup_reminder_state(
    config: dict,
    *,
    retention_days: int = DEFAULT_REMINDER_STATE_RETENTION_DAYS,
    now: float | None = None,
) -> dict[str, int]:
    """Remove stale or invalid reminder state entries.

    The reminder state is a rate-limit cache, not an audit log. Keeping old
    entries forever makes the file grow without adding user value.
    """
    state = read_notification_state(config)
    sent = state.get("last_sent") if isinstance(state.get("last_sent"), dict) else {}
    current_ts = float(now if now is not None else time.time())
    try:
        retention_seconds = max(1, int(retention_days)) * 86400
    except (TypeError, ValueError):
        retention_seconds = DEFAULT_REMINDER_STATE_RETENTION_DAYS * 86400

    removed_legacy = 0
    removed_expired = 0
    removed_invalid = 0
    for key, value in list(sent.items()):
        text_key = str(key)
        if text_key.startswith("restore_test_overdue:") and text_key.endswith(":never"):
            sent.pop(key, None)
            removed_legacy += 1
            continue
        try:
            sent_ts = float(value)
        except (TypeError, ValueError):
            sent.pop(key, None)
            removed_invalid += 1
            continue
        if current_ts - sent_ts > retention_seconds:
            sent.pop(key, None)
            removed_expired += 1

    removed = removed_legacy + removed_expired + removed_invalid
    if removed:
        state["last_sent"] = sent
        write_notification_state(config, state)
    return {
        "removed": removed,
        "removed_legacy": removed_legacy,
        "removed_expired": removed_expired,
        "removed_invalid": removed_invalid,
    }
