"""
Central notification events for Borg Backup UI.

Transport functions live in lib.notifications. This module owns the decision
which event goes to which configured channel.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import fcntl
import subprocess
import sys

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
    mode: str = "sync"


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

    if _apprise_async_enabled(config):
        apprise_result = enqueue_event_apprise(config, event)
    else:
        apprise_result = _send_event_apprise(config, event)
    results["apprise"] = apprise_result.delivered

    if ntfy_config is not None:
        logger.info(
            "Notification event processed (event=%s source=%s unraid=%s email=%s native_ntfy=%s apprise=%s apprise_mode=%s apprise_profiles=%s)",
            event_type,
            event.source or "-",
            results["unraid"],
            results["email"],
            results["ntfy"],
            results["apprise"],
            apprise_result.mode,
            _log_list(apprise_result.delivered_profiles),
        )
    else:
        logger.info(
            "Notification event processed (event=%s source=%s unraid=%s email=%s apprise=%s apprise_mode=%s apprise_profiles=%s)",
            event_type,
            event.source or "-",
            results["unraid"],
            results["email"],
            results["apprise"],
            apprise_result.mode,
            _log_list(apprise_result.delivered_profiles),
        )
    _emit_lifecycle_notification(event, results, apprise_result)
    return results


def _emit_lifecycle_notification(event: NotificationEvent, results: dict[str, bool], apprise_result: AppriseEventResult) -> None:
    event_type = str(event.event_type or "").strip()
    source = str(event.source or "").strip()
    if source == "backup_job" or event_type.startswith("backup_"):
        component = "JOB"
    elif source == "restore_test" or event_type.startswith("restore_test_"):
        component = "RESTORE_TEST"
    else:
        return
    try:
        from lifecycle_log import emit_lifecycle

        emit_lifecycle(
            component,
            "notification",
            job_key=event.job_key,
            event=event_type,
            source=source,
            status=event.status,
            duration_seconds=event.duration_seconds,
            exit_code=event.exit_code,
            unraid=bool(results.get("unraid")),
            email=bool(results.get("email")),
            native_ntfy=bool(results.get("ntfy")),
            apprise=bool(results.get("apprise")),
            apprise_mode=apprise_result.mode,
            apprise_profiles=apprise_result.delivered_profiles,
        )
    except Exception:
        return


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
    result = AppriseEventResult(mode="sync")
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


def enqueue_event_apprise(config: dict, event: NotificationEvent) -> AppriseEventResult:
    """Queue Apprise delivery durably so provider I/O does not block the source operation."""
    result = AppriseEventResult(mode="queued")
    for profile in apprise_event_profiles(config, event.event_type):
        profile_id = str(profile.get("id") or "").strip()
        item = _queue_item_from_event(profile, event)
        try:
            _append_queue_item(config, item)
            _record_delivery_status(config, item, status="queued", message="Queued for background delivery.")
        except Exception as exc:  # noqa: BLE001 - notifications are best-effort
            logger.warning(
                "Apprise notification could not be queued (profile=%s event=%s): %s",
                profile_id,
                event.event_type,
                _safe_error(exc),
            )
            continue
        result.delivered = True
        result.delivered_profiles.append(_apprise_profile_log_name(profile))
    if result.delivered:
        _kick_notification_delivery(config)
    return result


def drain_notification_queue(config: dict, *, max_items: int = 20) -> dict[str, Any]:
    """Deliver due queued Apprise notifications.

    Returns a compact status dictionary for background worker logs and tests.
    """
    now_ts = time.time()
    due: list[dict[str, Any]] = []
    with _notification_lock(config):
        store = _read_queue_store_unlocked(config)
        rows = store.get("queue") if isinstance(store.get("queue"), list) else []
        pending: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            next_attempt = _float(row.get("next_attempt_at"), default=0.0)
            if next_attempt <= now_ts and len(due) < max_items:
                due.append(row)
            else:
                pending.append(row)
        store["queue"] = pending
        _write_json(_queue_path(config), store)

    delivered = 0
    failed = 0
    retried = 0
    for item in due:
        status = _deliver_queue_item(config, item)
        if status == "delivered":
            delivered += 1
        elif status == "retrying":
            retried += 1
        else:
            failed += 1

    remaining = len(_read_queue_store(config).get("queue") or [])
    return {
        "checked": len(due),
        "delivered": delivered,
        "failed": failed,
        "retrying": retried,
        "remaining": remaining,
    }


def read_notification_delivery_status(config: dict) -> dict[str, Any]:
    with _notification_lock(config):
        return _read_status_store_unlocked(config)


def _deliver_queue_item(config: dict, item: dict[str, Any]) -> str:
    profile_id = str(item.get("profile_id") or "").strip()
    event_type = str(item.get("event_type") or "").strip()
    attempts_made = _int(item.get("attempts_made"), default=0) + 1
    max_attempts = max(1, _int(item.get("max_attempts"), default=1))
    timeout_seconds = _apprise_timeout(item.get("timeout_seconds"))
    url = _read_apprise_secret(config, profile_id)
    if not url:
        item["attempts_made"] = attempts_made
        _record_delivery_status(config, item, status="failed", message="Apprise profile URL is missing.")
        logger.warning("Queued Apprise notification failed (profile=%s event=%s): profile URL is missing", profile_id, event_type)
        return "failed"

    try:
        delivery = send_notification(
            url,
            title=str(item.get("title") or "Borg Backup UI"),
            body=str(item.get("body") or ""),
            timeout_seconds=timeout_seconds,
        )
    except AppriseAdapterError as exc:
        delivery = None
        message = f"Apprise runtime unavailable: {_safe_error(exc)}"
    except Exception as exc:  # noqa: BLE001 - background delivery is best-effort
        delivery = None
        message = f"Apprise notification failed: {_safe_error(exc)}"
    else:
        message = _safe_error(getattr(delivery, "message", ""))

    item["attempts_made"] = attempts_made
    if delivery is not None and delivery.ok:
        _record_delivery_status(config, item, status="delivered", message=message or "Delivered.")
        logger.info(
            "Queued Apprise notification delivered (profile=%s event=%s id=%s attempt=%s/%s)",
            profile_id,
            event_type,
            str(item.get("id") or ""),
            attempts_made,
            max_attempts,
        )
        return "delivered"

    if attempts_made < max_attempts:
        backoff = _apprise_backoff(item.get("backoff_seconds"))
        item["next_attempt_at"] = time.time() + backoff
        _requeue_item(config, item)
        _record_delivery_status(config, item, status="retrying", message=message)
        logger.warning(
            "Queued Apprise notification will retry (profile=%s event=%s id=%s attempt=%s/%s): %s",
            profile_id,
            event_type,
            str(item.get("id") or ""),
            attempts_made,
            max_attempts,
            message,
        )
        return "retrying"

    _record_delivery_status(config, item, status="failed", message=message)
    logger.warning(
        "Queued Apprise notification failed permanently (profile=%s event=%s id=%s attempts=%s): %s",
        profile_id,
        event_type,
        str(item.get("id") or ""),
        attempts_made,
        message,
    )
    return "failed"


def _queue_item_from_event(profile: dict[str, Any], event: NotificationEvent) -> dict[str, Any]:
    profile_id = str(profile.get("id") or "").strip()
    name = str(profile.get("name") or profile_id or "Borg Backup UI").strip()
    retry_policy = profile.get("retry_policy") if isinstance(profile.get("retry_policy"), dict) else {}
    created = _utc_now()
    return {
        "id": uuid.uuid4().hex,
        "created_at": created,
        "updated_at": created,
        "next_attempt_at": time.time(),
        "attempts_made": 0,
        "max_attempts": _apprise_attempts(retry_policy.get("attempts") if isinstance(retry_policy, dict) else None),
        "backoff_seconds": _apprise_backoff(retry_policy.get("backoff_seconds") if isinstance(retry_policy, dict) else None),
        "timeout_seconds": _apprise_timeout(profile.get("timeout_seconds")),
        "profile_id": profile_id,
        "profile_name": name,
        "provider": str(profile.get("provider") or "").strip(),
        "event_type": str(event.event_type or "").strip(),
        "source": str(event.source or "").strip(),
        "job_key": str(event.job_key or "").strip(),
        "severity": str(event.severity or "").strip(),
        "title": _apprise_title(name, event.title),
        "body": str(event.message or ""),
    }


def _append_queue_item(config: dict, item: dict[str, Any]) -> None:
    with _notification_lock(config):
        store = _read_queue_store_unlocked(config)
        rows = store.get("queue") if isinstance(store.get("queue"), list) else []
        rows.append(item)
        max_entries = _queue_max_entries(config)
        dropped = rows[:-max_entries] if len(rows) > max_entries else []
        rows = rows[-max_entries:]
        store["queue"] = rows
        store["updated_at"] = _utc_now()
        _write_json(_queue_path(config), store)
        for old in dropped:
            if isinstance(old, dict):
                _record_delivery_status_unlocked(config, old, status="dropped", message="Notification queue was full.")


def _requeue_item(config: dict, item: dict[str, Any]) -> None:
    item["updated_at"] = _utc_now()
    with _notification_lock(config):
        store = _read_queue_store_unlocked(config)
        rows = store.get("queue") if isinstance(store.get("queue"), list) else []
        rows.append(item)
        store["queue"] = rows[-_queue_max_entries(config):]
        store["updated_at"] = _utc_now()
        _write_json(_queue_path(config), store)


def _record_delivery_status(config: dict, item: dict[str, Any], *, status: str, message: str) -> None:
    with _notification_lock(config):
        _record_delivery_status_unlocked(config, item, status=status, message=message)


def _record_delivery_status_unlocked(config: dict, item: dict[str, Any], *, status: str, message: str) -> None:
    store = _read_status_store_unlocked(config)
    rows = store.get("deliveries") if isinstance(store.get("deliveries"), list) else []
    item_id = str(item.get("id") or "").strip()
    rows = [row for row in rows if not (isinstance(row, dict) and str(row.get("id") or "") == item_id)]
    rows.append({
        "id": item_id,
        "status": str(status or "unknown"),
        "message": _safe_error(message),
        "profile_id": str(item.get("profile_id") or ""),
        "profile_name": str(item.get("profile_name") or ""),
        "provider": str(item.get("provider") or ""),
        "event_type": str(item.get("event_type") or ""),
        "source": str(item.get("source") or ""),
        "job_key": str(item.get("job_key") or ""),
        "attempts_made": _int(item.get("attempts_made"), default=0),
        "max_attempts": _int(item.get("max_attempts"), default=1),
        "created_at": str(item.get("created_at") or ""),
        "updated_at": _utc_now(),
    })
    store["deliveries"] = rows[-_status_history_limit(config):]
    store["updated_at"] = _utc_now()
    _write_json(_delivery_status_path(config), store)


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _data_root(config: dict) -> Path:
    root = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    return root.parent if root.name == "scripts" else root


def _queue_path(config: dict) -> Path:
    return _data_root(config) / "config" / "notification-queue.json"


def _delivery_status_path(config: dict) -> Path:
    return _data_root(config) / "config" / "notification-deliveries.json"


def _notification_lock_path(config: dict) -> Path:
    return _data_root(config) / "locks" / "notification-delivery.lock"


@contextmanager
def _notification_lock(config: dict):
    path = _notification_lock_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _read_json_file(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(fallback)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return dict(fallback)
    return payload if isinstance(payload, dict) else dict(fallback)


def _read_queue_store(config: dict) -> dict[str, Any]:
    with _notification_lock(config):
        return _read_queue_store_unlocked(config)


def _read_queue_store_unlocked(config: dict) -> dict[str, Any]:
    store = _read_json_file(_queue_path(config), {"schema_version": 1, "queue": []})
    if not isinstance(store.get("queue"), list):
        store["queue"] = []
    store.setdefault("schema_version", 1)
    return store


def _read_status_store_unlocked(config: dict) -> dict[str, Any]:
    store = _read_json_file(_delivery_status_path(config), {"schema_version": 1, "deliveries": []})
    if not isinstance(store.get("deliveries"), list):
        store["deliveries"] = []
    store.setdefault("schema_version", 1)
    return store


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)


def _apprise_async_enabled(config: dict) -> bool:
    raw = str(config.get("NOTIFY_APPRISE_ASYNC", "true") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _apprise_immediate_kick_enabled(config: dict) -> bool:
    raw = str(config.get("NOTIFY_APPRISE_IMMEDIATE_KICK", "true") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _kick_notification_delivery(config: dict) -> None:
    if not _apprise_immediate_kick_enabled(config):
        return
    data_root = str(config.get("BACKUP_SCRIPTS_DIR", "") or _data_root(config))
    runtime_dir = Path(__file__).resolve().parents[1]
    runtime_lib = runtime_dir / "lib"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", os.environ.get("LANG", "C.UTF-8")),
    }
    env["BBUI_BACKUP_SCRIPTS_DIR"] = data_root
    for key in ("NOTIFY_APPRISE_STATUS_HISTORY",):
        if key in config:
            env[f"BBUI_{key}"] = str(config.get(key) or "")
    code = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(runtime_lib)!r})\n"
        f"sys.path.insert(0, {str(runtime_dir)!r})\n"
        "from lib.notification_events import drain_notification_queue\n"
        "cfg = {'BACKUP_SCRIPTS_DIR': os.environ.get('BBUI_BACKUP_SCRIPTS_DIR', '')}\n"
        "if os.environ.get('BBUI_NOTIFY_APPRISE_STATUS_HISTORY'):\n"
        "    cfg['NOTIFY_APPRISE_STATUS_HISTORY'] = os.environ['BBUI_NOTIFY_APPRISE_STATUS_HISTORY']\n"
        "drain_notification_queue(cfg, max_items=20)\n"
    )
    try:
        subprocess.Popen(  # noqa: S603 - fixed interpreter and inline code without secrets.
            [sys.executable or "python3", "-c", code],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            close_fds=True,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001 - queued notification still remains for the periodic worker
        logger.warning("Apprise notification immediate delivery kick failed: %s", _safe_error(exc))


def _queue_max_entries(config: dict) -> int:
    return max(1, min(5000, _int(config.get("NOTIFY_APPRISE_QUEUE_MAX_ENTRIES"), default=500)))


def _status_history_limit(config: dict) -> int:
    return max(1, min(5000, _int(config.get("NOTIFY_APPRISE_STATUS_HISTORY"), default=200)))


def _int(value: Any, *, default: int) -> int:
    try:
        return int(str(value if value is not None else default).strip())
    except (TypeError, ValueError):
        return default


def _float(value: Any, *, default: float) -> float:
    try:
        return float(str(value if value is not None else default).strip())
    except (TypeError, ValueError):
        return default


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
