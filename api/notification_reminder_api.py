"""Scheduled notification reminder checks."""

from __future__ import annotations

from datetime import datetime
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
        period = _schedule_period_seconds(cron)
        if period <= 0:
            skipped += 1
            rows.append({"job_key": job_key, "event": "backup_overdue", "sent": False, "reason": "unsupported_cron"})
            continue

        checked += 1
        last = latest.get(str(job_key))
        last_ts = _parse_status_time(str((last or {}).get("timestamp") or ""))
        overdue = last_ts is None or (now - last_ts).total_seconds() > period
        if not overdue:
            continue

        due_marker = str((last or {}).get("timestamp") or "never")
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
            error_message="Scheduled backup has not reported a recent run.",
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
            extra={"cron": cron, "last_timestamp": due_marker},
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


def _schedule_period_seconds(cron: str) -> int:
    parts = cron.split()
    if len(parts) != 5:
        return 0
    minute, hour, dom, month, dow = parts
    if month != "*":
        return 0
    if minute == "*" or hour == "*":
        return 0
    if dom == "*" and dow == "*":
        return int(36 * 3600)
    if dom == "*" and dow != "*":
        return int(8 * 86400)
    if dom != "*" and dow == "*":
        return int(32 * 86400)
    return 0


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
