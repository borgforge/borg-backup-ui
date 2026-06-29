from pathlib import Path
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
