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

    effective = {**config, **read_expanded_conf(config)}
    mail_config = MailConfig.from_config(effective)
    ntfy_config = NtfyConfig.from_config(effective)
    plan = list_restore_test_plan(effective)

    checked = 0
    sent = 0
    skipped = 0
    rows = []
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
