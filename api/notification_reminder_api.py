"""Scheduled notification reminder checks."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def run_due_notification_reminders(config: dict) -> dict[str, Any]:
    """Send configured overdue reminders without starting backup or restore jobs."""
    from config_api import read_expanded_conf
    from restore_tests_api import list_restore_test_plan
    from lib.notifications import MailConfig, NtfyConfig, build_restore_test_ntfy_message
    from lib.notification_events import (
        NotificationEvent,
        mark_reminder_sent,
        reminder_allowed,
        reminder_key,
        send_event,
    )

    effective = {**read_expanded_conf(config), **config}
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
        due_marker = str(row.get("next_due_at") or row.get("last_test_date") or "never")
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
    }


def _send_backup_overdue_reminders(effective: dict, mail_config, ntfy_config) -> dict[str, Any]:
    from jobs_api import list_jobs
    from schedule_api import get_schedules
    from status_api import get_status_data
    from lib.notifications import build_backup_ntfy_message
    from lib.notification_events import (
        NotificationEvent,
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
    latest = {
        str(row.get("key") or "").strip(): row
        for row in status.get("backups") or []
        if isinstance(row, dict) and str(row.get("key") or "").strip()
    }

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
        overdue = now > expected_run + tolerance and (last_ts is None or last_ts < expected_run)
        if not overdue:
            continue

        due_marker = expected_run.strftime("%Y-%m-%d %H:%M:%S")
        key = reminder_key("backup_overdue", str(job_key), due_marker)
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


def _backup_overdue_tolerance_hours(config: dict) -> int:
    raw = str(config.get("NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS", "6") or "6")
    try:
        return max(1, int(raw.strip()))
    except ValueError:
        return 6


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
