"""Scheduled notification reminder checks."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def get_notification_reminder_diagnostics(config: dict) -> dict[str, Any]:
    """Return read-only reminder diagnostics for system health."""
    from config_api import read_expanded_conf
    from jobs_api import list_jobs
    from restore_tests_api import list_restore_test_plan
    from schedule_api import get_schedules
    from status_api import get_status_data
    from lib.notification_events import (
        DEFAULT_EMAIL_EVENTS,
        DEFAULT_UNRAID_EVENTS,
        event_set,
        read_notification_state,
        reminder_interval_hours,
        reminder_key,
    )
    from lib.notifications import MailConfig, NtfyConfig

    effective = {**read_expanded_conf(config), **config}
    interval_hours = reminder_interval_hours(effective)
    backup_tolerance_hours = _backup_overdue_tolerance_hours(effective)
    state = read_notification_state(effective)
    sent = state.get("last_sent") if isinstance(state.get("last_sent"), dict) else {}

    def _active_channels(event_type: str) -> list[str]:
        channels: list[str] = []
        if event_type in event_set(effective, "NOTIFY_UNRAID_EVENTS", DEFAULT_UNRAID_EVENTS):
            channels.append("unraid")
        mail_cfg = MailConfig.from_config(effective)
        if mail_cfg.recipient and event_type in event_set(effective, "NOTIFY_EMAIL_EVENTS", DEFAULT_EMAIL_EVENTS):
            channels.append("email")
        ntfy_cfg = NtfyConfig.from_config(effective)
        if ntfy_cfg.enabled and ntfy_cfg.server_url and ntfy_cfg.topic and event_type in set(ntfy_cfg.events or set()):
            channels.append("ntfy")
        return channels

    now = datetime.now()
    backup_channels = _active_channels("backup_overdue")
    restore_channels = _active_channels("restore_test_overdue")
    result: dict[str, Any] = {
        "enabled": bool(backup_channels or restore_channels),
        "generated_at": now.isoformat(timespec="seconds"),
        "settings": {
            "reminder_interval_hours": interval_hours,
            "backup_overdue_tolerance_hours": backup_tolerance_hours,
        },
        "backup_overdue": {
            "enabled": bool(backup_channels),
            "channels": backup_channels,
            "items": [],
        },
        "restore_test_overdue": {
            "enabled": bool(restore_channels),
            "channels": restore_channels,
            "items": [],
        },
    }

    if backup_channels:
        schedules = get_schedules(effective)
        jobs = {
            str(job.get("key") or "").strip(): job
            for job in list_jobs(effective, {})
            if isinstance(job, dict) and str(job.get("key") or "").strip()
        }
        status = get_status_data(effective)
        latest = _latest_backup_status_by_key(status.get("backups") or [])
        result["backup_overdue"]["items"] = _backup_overdue_diagnostics(
            effective,
            schedules,
            jobs,
            latest,
            sent,
            now,
            interval_hours,
            backup_tolerance_hours,
        )

    if restore_channels:
        plan = list_restore_test_plan(effective)
        result["restore_test_overdue"]["items"] = _restore_test_overdue_diagnostics(
            plan,
            sent,
            now,
            interval_hours,
        )

    return result


def run_due_notification_reminders(config: dict) -> dict[str, Any]:
    """Send configured overdue reminders without starting backup or restore jobs."""
    from config_api import read_expanded_conf
    from restore_tests_api import list_restore_test_plan
    from lib.notifications import MailConfig, NtfyConfig, build_restore_test_ntfy_message
    from lib.notification_events import (
        NotificationEvent,
        cleanup_reminder_state,
        mark_reminder_sent,
        reminder_allowed,
        reminder_key,
        send_event,
    )

    effective = {**read_expanded_conf(config), **config}
    cleanup_result = cleanup_reminder_state(effective)
    mail_config = MailConfig.from_config(effective)
    ntfy_config = NtfyConfig.from_config(effective)
    plan = list_restore_test_plan(effective)

    checked = 0
    sent = 0
    skipped = 0
    rows = []

    backup_result = _send_backup_overdue_reminders(effective, mail_config, ntfy_config)
    checked += int(backup_result.get("checked") or 0)
    sent += int(backup_result.get("sent") or 0)
    skipped += int(backup_result.get("skipped") or 0)
    rows.extend(backup_result.get("rows") or [])

    for row in plan.get("jobs") or []:
        if not isinstance(row, dict):
            continue
        policy = row.get("policy") if isinstance(row.get("policy"), dict) else {}
        if str(policy.get("mode") or "").strip().lower() != "scheduled":
            continue
        if row.get("enabled") is False:
            continue
        if not bool(row.get("is_overdue", False)):
            continue

        checked += 1
        job_key = str(row.get("job_key") or "").strip()
        if not job_key:
            continue
        due_marker = str(row.get("next_due_at") or "").strip()
        if not due_marker:
            skipped += 1
            rows.append({"job_key": job_key, "sent": False, "reason": "missing_due_marker"})
            continue
        key = reminder_key("restore_test_overdue", job_key, due_marker)
        if not reminder_allowed(effective, key):
            skipped += 1
            rows.append({"job_key": job_key, "sent": False, "reason": "interval_not_elapsed"})
            continue

        display_name = str(row.get("display_name") or job_key)
        message = build_restore_test_ntfy_message(
            job_name=display_name,
            status="Overdue",
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            repository=str(row.get("location") or ""),
            level=int(policy.get("level") or 0),
            error_message="Scheduled restore verification is overdue.",
        )
        event = NotificationEvent(
            event_type="restore_test_overdue",
            title="Borg Backup UI: Restore test overdue",
            message=message,
            severity="warning",
            job_name=f"Borg Backup UI ({display_name})",
            job_key=job_key,
            status="overdue",
            source="scheduled_reminder",
            extra={"due_marker": due_marker},
        )
        results = send_event(effective, event, mail_config=mail_config, ntfy_config=ntfy_config)
        if any(results.values()):
            mark_reminder_sent(effective, key)
            sent += 1
            rows.append({"job_key": job_key, "sent": True, "channels": results})
        else:
            skipped += 1
            rows.append({"job_key": job_key, "sent": False, "reason": "no_channel_sent", "channels": results})

    return {
        "checked": checked,
        "sent": sent,
        "skipped": skipped,
        "rows": rows,
        "cleanup": cleanup_result,
    }


def _send_backup_overdue_reminders(effective: dict, mail_config, ntfy_config) -> dict[str, Any]:
    from jobs_api import list_jobs
    from schedule_api import get_schedules
    from status_api import get_status_data
    from lib.notifications import build_backup_ntfy_message
    from lib.notification_events import (
        NotificationEvent,
        clear_reminder_prefix,
        mark_reminder_sent,
        reminder_allowed,
        reminder_key,
        send_event,
    )

    schedules = get_schedules(effective)
    if not isinstance(schedules, dict) or not schedules:
        return {"checked": 0, "sent": 0, "skipped": 0, "rows": []}

    jobs = {
        str(job.get("key") or "").strip(): job
        for job in list_jobs(effective, {})
        if isinstance(job, dict) and str(job.get("key") or "").strip()
    }
    status = get_status_data(effective)
    latest = _latest_backup_status_by_key(status.get("backups") or [])

    checked = 0
    sent = 0
    skipped = 0
    rows = []
    now = datetime.now()
    for job_key, sched in schedules.items():
        if job_key == "restore_test" or not isinstance(sched, dict) or not bool(sched.get("enabled", True)):
            continue
        job = jobs.get(str(job_key))
        if not job or job.get("enabled") is False:
            continue
        cron = str(sched.get("cron") or "").strip()
        expected_run = _latest_expected_run(cron, now)
        if expected_run is None:
            skipped += 1
            rows.append({"job_key": job_key, "event": "backup_overdue", "sent": False, "reason": "unsupported_cron"})
            continue

        checked += 1
        last = latest.get(str(job_key))
        last_ts = _parse_status_time(str((last or {}).get("timestamp") or ""))
        tolerance = timedelta(hours=_backup_overdue_tolerance_hours(effective))
        due_marker = expected_run.strftime("%Y-%m-%d %H:%M:%S")
        key = reminder_key("backup_overdue", str(job_key), due_marker)
        if last_ts is not None and last_ts >= expected_run:
            clear_reminder_prefix(effective, key)
            continue
        overdue = now > expected_run + tolerance and (last_ts is None or last_ts < expected_run)
        if not overdue:
            continue

        if not reminder_allowed(effective, key):
            skipped += 1
            rows.append({"job_key": job_key, "event": "backup_overdue", "sent": False, "reason": "interval_not_elapsed"})
            continue

        display_name = str(job.get("display_name") or job.get("name") or job_key)
        message = build_backup_ntfy_message(
            job_name=display_name,
            status="Overdue",
            timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
            duration_seconds=0,
            repository=str(job.get("repo_path") or ""),
            error_message=f"Scheduled backup missed the expected run at {due_marker}.",
        )
        event = NotificationEvent(
            event_type="backup_overdue",
            title="Borg Backup UI: Backup overdue",
            message=message,
            severity="warning",
            job_name=f"Borg Backup ({display_name})",
            job_key=str(job_key),
            status="overdue",
            repository=str(job.get("repo_path") or ""),
            source="scheduled_reminder",
            extra={"cron": cron, "expected_run": due_marker, "last_timestamp": str((last or {}).get("timestamp") or "")},
        )
        results = send_event(effective, event, mail_config=mail_config, ntfy_config=ntfy_config)
        if any(results.values()):
            mark_reminder_sent(effective, key)
            sent += 1
            rows.append({"job_key": job_key, "event": "backup_overdue", "sent": True, "channels": results})
        else:
            skipped += 1
            rows.append({"job_key": job_key, "event": "backup_overdue", "sent": False, "reason": "no_channel_sent", "channels": results})

    return {"checked": checked, "sent": sent, "skipped": skipped, "rows": rows}


def _backup_overdue_diagnostics(
    effective: dict,
    schedules: dict,
    jobs: dict,
    latest: dict,
    sent: dict,
    now: datetime,
    interval_hours: int,
    backup_tolerance_hours: int,
) -> list[dict[str, Any]]:
    from lib.notification_events import reminder_key

    if not isinstance(schedules, dict):
        return []
    items: list[dict[str, Any]] = []
    tolerance = timedelta(hours=backup_tolerance_hours)
    for job_key, sched in sorted(schedules.items()):
        if job_key == "restore_test" or not isinstance(sched, dict) or not bool(sched.get("enabled", True)):
            continue
        job = jobs.get(str(job_key))
        if not job or job.get("enabled") is False:
            continue
        cron = str(sched.get("cron") or "").strip()
        latest_expected_run = _latest_expected_run(cron, now)
        if latest_expected_run is None:
            items.append({
                "type": "backup_overdue",
                "job_key": str(job_key),
                "display_name": str(job.get("display_name") or job.get("name") or job_key),
                "cron": cron,
                "state": "unsupported",
                "reason": "unsupported_cron",
            })
            continue
        last = latest.get(str(job_key)) or {}
        last_ts = _parse_status_time(str(last.get("timestamp") or ""))
        expected_run = latest_expected_run
        if last_ts is not None and last_ts >= latest_expected_run:
            expected_run = _next_expected_run(cron, now) or latest_expected_run
        overdue_after = expected_run + tolerance
        overdue = now > overdue_after and (last_ts is None or last_ts < expected_run)
        key = reminder_key("backup_overdue", str(job_key), expected_run.strftime("%Y-%m-%d %H:%M:%S"))
        reminder = (
            {"sent": False, "sent_at": "", "next_allowed_at": "", "allowed": True}
            if last_ts is not None and last_ts >= expected_run
            else _reminder_state_for_key(sent, key, now, interval_hours)
        )
        state = "overdue_ready" if overdue and reminder["allowed"] else ("overdue_waiting" if overdue else "current")
        reason = "ready_to_send" if state == "overdue_ready" else ("interval_not_elapsed" if state == "overdue_waiting" else "not_overdue")
        items.append({
            "type": "backup_overdue",
            "job_key": str(job_key),
            "display_name": str(job.get("display_name") or job.get("name") or job_key),
            "cron": cron,
            "state": state,
            "reason": reason,
            "expected_run": expected_run.isoformat(timespec="seconds"),
            "overdue_after": overdue_after.isoformat(timespec="seconds"),
            "latest_status_at": last_ts.isoformat(timespec="seconds") if last_ts else "",
            "latest_status": str(last.get("status") or ""),
            "reminder_key": key,
            **reminder,
        })
    return items


def _restore_test_overdue_diagnostics(plan: dict, sent: dict, now: datetime, interval_hours: int) -> list[dict[str, Any]]:
    from lib.notification_events import reminder_key

    items: list[dict[str, Any]] = []
    for row in plan.get("jobs") or []:
        if not isinstance(row, dict):
            continue
        policy = row.get("policy") if isinstance(row.get("policy"), dict) else {}
        if str(policy.get("mode") or "").strip().lower() != "scheduled":
            continue
        if row.get("enabled") is False:
            continue
        job_key = str(row.get("job_key") or "").strip()
        if not job_key:
            continue
        due_marker = str(row.get("next_due_at") or "").strip()
        key = reminder_key("restore_test_overdue", job_key, due_marker) if due_marker else ""
        reminder = _reminder_state_for_key(sent, key, now, interval_hours) if key else {
            "sent": False,
            "sent_at": "",
            "next_allowed_at": "",
            "allowed": False,
        }
        overdue = bool(row.get("is_overdue", False))
        state = "missing_due" if not due_marker else ("overdue_ready" if overdue and reminder["allowed"] else ("overdue_waiting" if overdue else "current"))
        reason = {
            "missing_due": "missing_due_marker",
            "overdue_ready": "ready_to_send",
            "overdue_waiting": "interval_not_elapsed",
            "current": "not_overdue",
        }.get(state, "unknown")
        items.append({
            "type": "restore_test_overdue",
            "job_key": job_key,
            "display_name": str(row.get("display_name") or job_key),
            "state": state,
            "reason": reason,
            "next_due_at": due_marker,
            "last_test_date": str(row.get("last_test_date") or ""),
            "level": int(policy.get("level") or 0),
            "interval_days": int(policy.get("interval_days") or 0),
            "reminder_key": key,
            **reminder,
        })
    return items


def _reminder_state_for_key(sent: dict, key: str, now: datetime, interval_hours: int) -> dict[str, Any]:
    previous = sent.get(key)
    if previous is None:
        return {"sent": False, "sent_at": "", "next_allowed_at": "", "allowed": True}
    try:
        previous_ts = float(previous)
    except (TypeError, ValueError):
        return {"sent": False, "sent_at": "", "next_allowed_at": "", "allowed": True}
    sent_at = datetime.fromtimestamp(previous_ts)
    next_allowed = sent_at + timedelta(hours=interval_hours)
    return {
        "sent": True,
        "sent_at": sent_at.isoformat(timespec="seconds"),
        "next_allowed_at": next_allowed.isoformat(timespec="seconds"),
        "allowed": now >= next_allowed,
    }


def _backup_overdue_tolerance_hours(config: dict) -> int:
    raw = str(config.get("NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS", "6") or "6")
    try:
        return max(1, int(raw.strip()))
    except ValueError:
        return 6


def _latest_backup_status_by_key(rows: list) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        keys = []
        explicit_key = str(row.get("key") or "").strip()
        if explicit_key:
            keys.append(explicit_key)
        backup_type = str(row.get("backup_type") or row.get("type") or "").strip().lower()
        location = str(row.get("location") or "").strip().lower()
        if backup_type and location:
            keys.append(f"{backup_type}_{location}")
        for key in keys:
            current = latest.get(key)
            if current is None or _status_is_newer(row, current):
                latest[key] = row
    return latest


def _status_is_newer(candidate: dict, current: dict) -> bool:
    cand_ts = _parse_status_time(str(candidate.get("timestamp") or ""))
    cur_ts = _parse_status_time(str(current.get("timestamp") or ""))
    if cand_ts is None:
        return False
    if cur_ts is None:
        return True
    return cand_ts > cur_ts


def _latest_expected_run(cron: str, now: datetime) -> datetime | None:
    parts = cron.split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if month != "*":
        return None
    try:
        minute_value = int(minute)
        hour_value = int(hour)
    except ValueError:
        return None
    if minute_value < 0 or minute_value > 59 or hour_value < 0 or hour_value > 23:
        return None
    if dom != "*" and dow != "*":
        return None

    dow_values = _parse_cron_dow_values(dow) if dow != "*" else set(range(7))
    if not dow_values:
        return None
    dom_value: int | None = None
    if dom != "*":
        try:
            dom_value = int(dom)
        except ValueError:
            return None
        if dom_value < 1 or dom_value > 31:
            return None

    base = now.replace(second=0, microsecond=0)
    for offset in range(0, 370):
        day = base.date() - timedelta(days=offset)
        if dom_value is not None and day.day != dom_value:
            continue
        if dom_value is None and _cron_dow_for_datetime(datetime(day.year, day.month, day.day)) not in dow_values:
            continue
        candidate = datetime(day.year, day.month, day.day, hour_value, minute_value)
        if candidate <= now:
            return candidate
    return None


def _next_expected_run(cron: str, now: datetime) -> datetime | None:
    parts = cron.split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if month != "*":
        return None
    try:
        minute_value = int(minute)
        hour_value = int(hour)
    except ValueError:
        return None
    if minute_value < 0 or minute_value > 59 or hour_value < 0 or hour_value > 23:
        return None
    if dom != "*" and dow != "*":
        return None

    dow_values = _parse_cron_dow_values(dow) if dow != "*" else set(range(7))
    if not dow_values:
        return None
    dom_value: int | None = None
    if dom != "*":
        try:
            dom_value = int(dom)
        except ValueError:
            return None
        if dom_value < 1 or dom_value > 31:
            return None

    base = now.replace(second=0, microsecond=0)
    for offset in range(0, 370):
        day = base.date() + timedelta(days=offset)
        if dom_value is not None and day.day != dom_value:
            continue
        if dom_value is None and _cron_dow_for_datetime(datetime(day.year, day.month, day.day)) not in dow_values:
            continue
        candidate = datetime(day.year, day.month, day.day, hour_value, minute_value)
        if candidate > now:
            return candidate
    return None


def _cron_dow_for_datetime(value: datetime) -> int:
    # Python: Monday=0..Sunday=6. Cron: Sunday=0/7, Monday=1..Saturday=6.
    return (value.weekday() + 1) % 7


def _parse_cron_dow_values(raw: str) -> set[int]:
    values: set[int] = set()
    text = str(raw or "").strip()
    if not text or text == "*":
        return set(range(7))
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        if "/" in item:
            return set()
        if "-" in item:
            start_raw, end_raw = item.split("-", 1)
            try:
                start = int(start_raw)
                end = int(end_raw)
            except ValueError:
                return set()
            if start > end:
                return set()
            for value in range(start, end + 1):
                normalized = 0 if value == 7 else value
                if normalized < 0 or normalized > 6:
                    return set()
                values.add(normalized)
            continue
        try:
            value = int(item)
        except ValueError:
            return set()
        normalized = 0 if value == 7 else value
        if normalized < 0 or normalized > 6:
            return set()
        values.add(normalized)
    return values


def _parse_status_time(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None
