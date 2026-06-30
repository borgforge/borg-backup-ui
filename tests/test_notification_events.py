from pathlib import Path
from datetime import datetime
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "api"))

from lib.notification_events import (  # noqa: E402
    NotificationEvent,
    mark_reminder_sent,
    read_notification_state,
    reminder_allowed,
    send_event,
)
from lib.notifications import MailConfig, NtfyConfig  # noqa: E402
import notification_reminder_api  # noqa: E402


def test_send_event_routes_to_configured_channels(monkeypatch):
    calls = []

    monkeypatch.setattr("lib.notification_events.notify", lambda **kwargs: calls.append(("unraid", kwargs)) or True)
    monkeypatch.setattr("lib.notification_events.send_mail", lambda config, subject, body: calls.append(("email", subject, body)) or True)
    monkeypatch.setattr("lib.notification_events.send_ntfy", lambda config, event_type, title, message: calls.append(("ntfy", event_type, title)) or True)

    result = send_event(
        {
            "NOTIFY_UNRAID_EVENTS": "backup_success",
            "NOTIFY_EMAIL_EVENTS": "backup_failed",
        },
        NotificationEvent(
            event_type="backup_success",
            title="Backup OK",
            message="done",
            job_name="Job",
        ),
        mail_config=MailConfig(recipient="admin@example.test"),
        ntfy_config=NtfyConfig(enabled=True, server_url="https://ntfy.example.test", topic="borg", events={"backup_success"}),
    )

    assert result == {"unraid": True, "email": False, "ntfy": True}
    assert [c[0] for c in calls] == ["unraid", "ntfy"]


def test_backup_warning_keeps_existing_ntfy_backup_failed_selection(monkeypatch):
    calls = []
    monkeypatch.setattr("lib.notification_events.send_ntfy", lambda config, event_type, title, message: calls.append(event_type) or True)

    result = send_event(
        {"NOTIFY_UNRAID_EVENTS": "", "NOTIFY_EMAIL_EVENTS": ""},
        NotificationEvent(event_type="backup_warning", title="Warning", message="warning"),
        ntfy_config=NtfyConfig(enabled=True, server_url="https://ntfy.example.test", topic="borg", events={"backup_failed"}),
    )

    assert result["ntfy"] is True
    assert calls == ["backup_warning"]


def test_reminder_state_rate_limits_by_interval(tmp_path):
    cfg = {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_REMINDER_INTERVAL_HOURS": "24",
    }
    key = "restore_test_overdue:appdata_local:never"

    assert reminder_allowed(cfg, key, now=1000) is True
    mark_reminder_sent(cfg, key, now=1000)
    assert reminder_allowed(cfg, key, now=1000 + 3600) is False
    assert reminder_allowed(cfg, key, now=1000 + 25 * 3600) is True

    state = read_notification_state(cfg)
    assert state["last_sent"][key] == 1000


def test_backup_overdue_reminder_uses_supported_schedules(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("lib.notification_events.notify", lambda **kwargs: calls.append(kwargs["subject"]) or True)
    monkeypatch.setattr(notification_reminder_api, "datetime", _FixedDateTime)
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {"appdata_local": {"enabled": True, "cron": "0 2 * * *"}})
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, opts: [{"key": "appdata_local", "display_name": "Appdata", "enabled": True, "repo_path": "/repo"}])
    monkeypatch.setattr("status_api.get_status_data", lambda cfg: {"backups": [{"key": "appdata_local", "timestamp": "2026-06-27 02:00:00"}]})

    result = notification_reminder_api.run_due_notification_reminders({
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "backup_overdue",
        "NOTIFY_EMAIL_EVENTS": "",
        "NTFY_ENABLED": "false",
    })

    assert result["checked"] == 1
    assert result["sent"] == 1
    assert calls == ["Borg Backup UI: Backup overdue"]


def test_backup_overdue_uses_expected_run_and_configured_tolerance(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("lib.notification_events.notify", lambda **kwargs: calls.append(kwargs["subject"]) or True)
    monkeypatch.setattr(notification_reminder_api, "datetime", _WednesdayNoon)
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {"photos_local": {"enabled": True, "cron": "0 9 * * 1-5"}})
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, opts: [{"key": "photos_local", "display_name": "Photos", "enabled": True, "repo_path": "/repo"}])
    monkeypatch.setattr("status_api.get_status_data", lambda cfg: {"backups": [{"key": "photos_local", "timestamp": "2026-06-29 09:00:00"}]})

    result = notification_reminder_api.run_due_notification_reminders({
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "backup_overdue",
        "NOTIFY_EMAIL_EVENTS": "",
        "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": "2",
        "NTFY_ENABLED": "false",
    })

    state = read_notification_state({"BACKUP_SCRIPTS_DIR": str(tmp_path)})
    assert result["checked"] == 1
    assert result["sent"] == 1
    assert calls == ["Borg Backup UI: Backup overdue"]
    assert "backup_overdue:photos_local:2026-07-01 09:00:00" in state["last_sent"]


def test_backup_overdue_waits_for_tolerance_window(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("lib.notification_events.notify", lambda **kwargs: calls.append(kwargs["subject"]) or True)
    monkeypatch.setattr(notification_reminder_api, "datetime", _WednesdayNoon)
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {"photos_local": {"enabled": True, "cron": "0 9 * * 1-5"}})
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, opts: [{"key": "photos_local", "display_name": "Photos", "enabled": True, "repo_path": "/repo"}])
    monkeypatch.setattr("status_api.get_status_data", lambda cfg: {"backups": [{"key": "photos_local", "timestamp": "2026-06-29 09:00:00"}]})

    result = notification_reminder_api.run_due_notification_reminders({
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "backup_overdue",
        "NOTIFY_EMAIL_EVENTS": "",
        "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": "6",
        "NTFY_ENABLED": "false",
    })

    assert result["checked"] == 1
    assert result["sent"] == 0
    assert calls == []


def test_backup_overdue_expected_run_supports_simple_crons():
    now = datetime(2026, 7, 1, 12, 0, 0)
    assert notification_reminder_api._latest_expected_run("0 9 * * 1-5", now) == datetime(2026, 7, 1, 9, 0, 0)
    assert notification_reminder_api._latest_expected_run("0 9 * * 1,3,5", now) == datetime(2026, 7, 1, 9, 0, 0)
    assert notification_reminder_api._latest_expected_run("0 9 * * 1", now) == datetime(2026, 6, 29, 9, 0, 0)
    assert notification_reminder_api._latest_expected_run("0 9 1 * *", now) == datetime(2026, 7, 1, 9, 0, 0)
    assert notification_reminder_api._latest_expected_run("0 9 * * */2", now) is None


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 29, 12, 0, 0)


class _WednesdayNoon(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 1, 12, 0, 0)
