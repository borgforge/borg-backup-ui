from pathlib import Path
from datetime import datetime
import importlib.util
import json
import logging
import os
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "api"))

from lib.notification_events import (  # noqa: E402
    NotificationEvent,
    cleanup_reminder_state,
    mark_reminder_sent,
    read_notification_state,
    reminder_allowed,
    send_event,
)
from lib.backup_job import BackupJob, BackupJobConfig  # noqa: E402
from lib.notifications import MailConfig, NtfyConfig  # noqa: E402
import notification_reminder_api  # noqa: E402


def _backup_job_config(tmp_path: Path) -> BackupJobConfig:
    return BackupJobConfig(
        job_name="Flash",
        backup_type="flash",
        backup_location="local",
        lock_file=tmp_path / "job.lock",
        log_dir=tmp_path,
        log_file=tmp_path / "backup.log",
        backup_paths=[],
        borg_cache_dir=tmp_path / "cache",
        date_tag="2026-07-04",
    )


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

    assert result == {"unraid": True, "email": False, "ntfy": True, "apprise": False}
    assert [c[0] for c in calls] == ["unraid", "ntfy"]


def test_send_event_routes_to_enabled_apprise_profiles(monkeypatch, tmp_path):
    calls = []
    store = tmp_path / "config" / "apprise-profiles.json"
    secret = tmp_path / "secrets" / ".apprise-profile-alerts-main.url"
    store.parent.mkdir(parents=True)
    secret.parent.mkdir(parents=True)
    store.write_text(json.dumps({
        "schema_version": 1,
        "profiles": [{
            "id": "alerts-main",
            "name": "Critical Alerts",
            "enabled": True,
            "provider": "ntfy",
            "selected_events": ["backup_success"],
            "timeout_seconds": 15,
            "retry_policy": {"attempts": 1, "backoff_seconds": 0},
            "priority": "default",
            "default": True,
            "url_set": True,
        }],
    }), encoding="utf-8")
    secret.write_text("json://token@example.test\n", encoding="utf-8")

    def fake_send(url, *, title, body, **kwargs):
        calls.append({"url": url, "title": title, "body": body, "kwargs": kwargs})
        return SimpleNamespace(ok=True, message="sent")

    monkeypatch.setattr("lib.notification_events.send_notification", fake_send)

    result = send_event(
        {
            "BACKUP_SCRIPTS_DIR": str(tmp_path),
            "NOTIFY_UNRAID_EVENTS": "none",
            "NOTIFY_EMAIL_EVENTS": "",
        },
        NotificationEvent(
            event_type="backup_success",
            title="Borg Backup UI: Backup OK",
            message="done",
            job_name="Job",
        ),
    )

    assert result["apprise"] is True
    assert calls == [{
        "url": "json://token@example.test",
        "title": "Critical Alerts - Backup OK",
        "body": "done",
        "kwargs": {"timeout_seconds": 15},
    }]


def test_send_event_logs_delivered_apprise_profiles(monkeypatch, tmp_path, caplog):
    store = tmp_path / "config" / "apprise-profiles.json"
    secrets = tmp_path / "secrets"
    store.parent.mkdir(parents=True)
    secrets.mkdir(parents=True)
    store.write_text(json.dumps({
        "schema_version": 1,
        "profiles": [
            {
                "id": "alerts-main",
                "name": "Critical Alerts",
                "enabled": True,
                "provider": "ntfy",
                "selected_events": ["backup_success"],
                "timeout_seconds": 15,
                "retry_policy": {"attempts": 1, "backoff_seconds": 0},
                "url_set": True,
            },
            {
                "id": "rocketchat",
                "name": "Rocket.Chat",
                "enabled": True,
                "provider": "rocket",
                "selected_events": ["backup_success"],
                "timeout_seconds": 15,
                "retry_policy": {"attempts": 1, "backoff_seconds": 0},
                "url_set": True,
            },
        ],
    }), encoding="utf-8")
    (secrets / ".apprise-profile-alerts-main.url").write_text("json://one@example.test\n", encoding="utf-8")
    (secrets / ".apprise-profile-rocketchat.url").write_text("json://two@example.test\n", encoding="utf-8")

    monkeypatch.setattr(
        "lib.notification_events.send_notification",
        lambda *args, **kwargs: SimpleNamespace(ok=True, message="sent"),
    )

    with caplog.at_level(logging.INFO, logger="lib.notification_events"):
        result = send_event(
            {
                "BACKUP_SCRIPTS_DIR": str(tmp_path),
                "NOTIFY_UNRAID_EVENTS": "",
                "NOTIFY_EMAIL_EVENTS": "",
            },
            NotificationEvent(
                event_type="backup_success",
                title="Borg Backup UI: Backup OK",
                message="done",
                job_name="Job",
            ),
        )

    assert result["apprise"] is True
    assert "apprise_profiles=[\"Critical Alerts (alerts-main)\", \"Rocket.Chat (rocketchat)\"]" in caplog.text
    assert " ntfy=False" not in caplog.text
    assert "native_ntfy=" not in caplog.text


def test_send_event_skips_apprise_profiles_without_matching_event(monkeypatch, tmp_path):
    store = tmp_path / "config" / "apprise-profiles.json"
    secret = tmp_path / "secrets" / ".apprise-profile-alerts-main.url"
    store.parent.mkdir(parents=True)
    secret.parent.mkdir(parents=True)
    store.write_text(json.dumps({
        "schema_version": 1,
        "profiles": [{
            "id": "alerts-main",
            "name": "Critical Alerts",
            "enabled": True,
            "provider": "ntfy",
            "selected_events": ["backup_failed"],
            "timeout_seconds": 15,
            "retry_policy": {"attempts": 1, "backoff_seconds": 0},
            "priority": "default",
            "default": True,
            "url_set": True,
        }],
    }), encoding="utf-8")
    secret.write_text("json://token@example.test\n", encoding="utf-8")

    monkeypatch.setattr(
        "lib.notification_events.send_notification",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Apprise must not be called")),
    )

    result = send_event(
        {
            "BACKUP_SCRIPTS_DIR": str(tmp_path),
            "NOTIFY_UNRAID_EVENTS": "none",
            "NOTIFY_EMAIL_EVENTS": "",
        },
        NotificationEvent(
            event_type="backup_success",
            title="Borg Backup UI: Backup OK",
            message="done",
            job_name="Job",
        ),
    )

    assert result["apprise"] is False


def test_send_event_routes_restore_test_success_to_email_when_selected(monkeypatch):
    calls = []
    monkeypatch.setattr("lib.notification_events.send_mail", lambda config, subject, body: calls.append((subject, body)) or True)

    result = send_event(
        {
            "NOTIFY_UNRAID_EVENTS": "",
            "NOTIFY_EMAIL_EVENTS": "restore_test_success",
        },
        NotificationEvent(
            event_type="restore_test_success",
            title="Borg Backup UI: Restore test Successful",
            message="Restore test completed successfully.",
            job_name="Borg Backup UI (flash_local)",
        ),
        mail_config=MailConfig(recipient="admin@example.test"),
    )

    assert result["email"] is True
    assert calls == [("Borg Backup UI: Restore test Successful", "Restore test completed successfully.")]


def test_backup_failed_email_uses_event_message_and_appends_log(monkeypatch, tmp_path):
    calls = []
    log_file = tmp_path / "backup.log"
    log_file.write_text("line one\nline two\n", encoding="utf-8")
    monkeypatch.setattr("lib.notification_events.send_mail", lambda config, subject, body: calls.append((subject, body)) or True)

    result = send_event(
        {
            "NOTIFY_UNRAID_EVENTS": "",
            "NOTIFY_EMAIL_EVENTS": "backup_failed",
        },
        NotificationEvent(
            event_type="backup_failed",
            title="Borg Backup UI: Backup failed",
            message="Job: Appdata\nResult: Error\nAction: Review the backup log.",
            job_name="Borg Backup UI (appdata_local)",
            log_file=str(log_file),
            backup_type="appdata",
            date_tag="2026-07-04",
            exit_code=2,
        ),
        mail_config=MailConfig(recipient="admin@example.test"),
    )

    assert result["email"] is True
    assert calls[0][0] == "Borg Backup UI: Backup failed"
    assert "Job: Appdata" in calls[0][1]
    assert "Log file:" in calls[0][1]
    assert str(log_file) in calls[0][1]
    assert "line one\nline two" in calls[0][1]
    assert "Borg Backup Summary" not in calls[0][0]


def test_backup_success_email_appends_log_when_available(monkeypatch, tmp_path):
    calls = []
    log_file = tmp_path / "backup.log"
    log_file.write_text("backup started\nbackup completed\n", encoding="utf-8")
    monkeypatch.setattr("lib.notification_events.send_mail", lambda config, subject, body: calls.append((subject, body)) or True)

    result = send_event(
        {
            "NOTIFY_UNRAID_EVENTS": "",
            "NOTIFY_EMAIL_EVENTS": "backup_success",
        },
        NotificationEvent(
            event_type="backup_success",
            title="Borg Backup UI: Backup successful",
            message=(
                "Job: Flash\n"
                "Result: Successful\n"
                "Duration: 3 sec\n"
                "Finished: 2026-07-04 14:22\n"
                "Target: Local / borg-backup-flash\n"
                "Archive: flash-backup-2026-07-04_14-22-37"
            ),
            job_name="Borg Backup UI (flash_local)",
            log_file=str(log_file),
        ),
        mail_config=MailConfig(recipient="admin@example.test"),
    )

    assert result["email"] is True
    assert calls[0][0] == "Borg Backup UI: Backup successful"
    assert "Job: Flash" in calls[0][1]
    assert "Archive: flash-backup-2026-07-04_14-22-37" in calls[0][1]
    assert "Log file:" in calls[0][1]
    assert str(log_file) in calls[0][1]
    assert "backup started\nbackup completed" in calls[0][1]


def test_backup_job_uses_loaded_notification_config_for_email_events(monkeypatch, tmp_path):
    captured = {}

    def fake_send_event(config, event, *, mail_config=None, ntfy_config=None):
        captured["config"] = dict(config)
        captured["event_type"] = event.event_type
        captured["mail_recipient"] = mail_config.recipient if mail_config else ""
        return {"unraid": False, "email": True, "ntfy": False}

    monkeypatch.setattr("lib.notification_events.send_event", fake_send_event)
    job = BackupJob(
        _backup_job_config(tmp_path),
        mail_config=MailConfig(recipient="admin@example.test"),
        notification_config={
            "NOTIFY_EMAIL_EVENTS": "backup_success,restore_test_success",
            "NOTIFY_UNRAID_EVENTS": "",
        },
    )

    job._send_notification_event(
        "backup_success",
        "Borg Backup UI: Backup successful",
        "Backup completed successfully.",
        "info",
        12,
        0,
    )

    assert captured["event_type"] == "backup_success"
    assert captured["config"]["NOTIFY_EMAIL_EVENTS"] == "backup_success,restore_test_success"
    assert captured["mail_recipient"] == "admin@example.test"


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


def test_cleanup_reminder_state_removes_legacy_and_expired_entries(tmp_path):
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    state_path = tmp_path / "config" / "notification-state.json"
    state_path.parent.mkdir(parents=True)
    now = 2_000_000
    state_path.write_text(json.dumps({
        "schema_version": 1,
        "last_sent": {
            "restore_test_overdue:flash_local:never": now,
            "backup_overdue:old_job:2026-01-01 09:00:00": now - 91 * 86400,
            "backup_overdue:bad_job:2026-01-02 09:00:00": "not-a-number",
            "backup_overdue:fresh_job:2026-07-01 09:00:00": now - 3600,
        },
    }), encoding="utf-8")

    result = cleanup_reminder_state(cfg, retention_days=90, now=now)

    state = read_notification_state(cfg)
    assert result == {
        "removed": 3,
        "removed_legacy": 1,
        "removed_expired": 1,
        "removed_invalid": 1,
    }
    assert list(state["last_sent"].keys()) == ["backup_overdue:fresh_job:2026-07-01 09:00:00"]


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


def test_backup_overdue_uses_type_location_status_when_key_is_missing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("lib.notification_events.notify", lambda **kwargs: calls.append(kwargs["subject"]) or True)
    monkeypatch.setattr(notification_reminder_api, "datetime", _WednesdayLate)
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {"appdata_usb": {"enabled": True, "cron": "0 10 * * *"}})
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, opts: [{"key": "appdata_usb", "display_name": "Appdata", "enabled": True, "repo_path": "/repo"}])
    monkeypatch.setattr("status_api.get_status_data", lambda cfg: {"backups": [{
        "backup_type": "appdata",
        "location": "usb",
        "timestamp": "2026-07-01 10:04:45",
        "status": "success",
    }]})

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


def test_backup_overdue_clears_stale_sent_key_when_status_satisfies_expected_run(monkeypatch, tmp_path):
    key = "backup_overdue:appdata_local:2026-07-01 09:00:00"
    mark_reminder_sent({"BACKUP_SCRIPTS_DIR": str(tmp_path)}, key, now=datetime(2026, 7, 1, 23, 34, 52).timestamp())
    monkeypatch.setattr("lib.notification_events.notify", lambda **kwargs: True)
    monkeypatch.setattr(notification_reminder_api, "datetime", _WednesdayLate)
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {"appdata_local": {"enabled": True, "cron": "0 9 * * *"}})
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, opts: [{"key": "appdata_local", "display_name": "Appdata", "enabled": True, "repo_path": "/repo"}])
    monkeypatch.setattr("status_api.get_status_data", lambda cfg: {"backups": [{
        "key": "appdata_local",
        "timestamp": "2026-07-01 09:05:17",
        "status": "success",
    }]})

    result = notification_reminder_api.run_due_notification_reminders({
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "backup_overdue",
        "NOTIFY_EMAIL_EVENTS": "",
        "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": "6",
        "NTFY_ENABLED": "false",
    })

    state = read_notification_state({"BACKUP_SCRIPTS_DIR": str(tmp_path)})
    assert result["checked"] == 1
    assert result["sent"] == 0
    assert key not in state["last_sent"]


def test_backup_overdue_sender_matches_diagnostics_and_sends_only_ready_jobs(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("lib.notification_events.notify", lambda **kwargs: calls.append(kwargs["job_name"]) or True)
    monkeypatch.setattr(notification_reminder_api, "datetime", _ThursdayLateNight)
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {
        "appdata_usb": {"enabled": True, "cron": "0 10 * * *"},
        "sonstiges_usb": {"enabled": True, "cron": "0 15 * * *"},
    })
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, opts: [
        {"key": "appdata_usb", "display_name": "Appdata - USB", "enabled": True, "repo_path": "/repo/appdata"},
        {"key": "sonstiges_usb", "display_name": "Sonstiges - USB", "enabled": True, "repo_path": "/repo/sonstiges"},
    ])
    monkeypatch.setattr("status_api.get_status_data", lambda cfg: {"backups": [
        {"backup_type": "appdata", "location": "usb", "timestamp": "2026-07-02 12:10:27", "status": "success"},
        {"backup_type": "sonstiges", "location": "usb", "timestamp": "2026-07-01 15:00:01", "status": "success"},
    ]})
    stale_appdata = "backup_overdue:appdata_usb:2026-07-02 10:00:00"
    mark_reminder_sent({"BACKUP_SCRIPTS_DIR": str(tmp_path)}, stale_appdata, now=datetime(2026, 7, 2, 8, 0, 0).timestamp())

    result = notification_reminder_api.run_due_notification_reminders({
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "backup_overdue",
        "NOTIFY_EMAIL_EVENTS": "",
        "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": "6",
        "NTFY_ENABLED": "false",
    })

    state = read_notification_state({"BACKUP_SCRIPTS_DIR": str(tmp_path)})
    assert result["checked"] == 2
    assert result["sent"] == 1
    assert calls == ["Borg Backup (Sonstiges - USB)"]
    assert stale_appdata not in state["last_sent"]
    assert "backup_overdue:sonstiges_usb:2026-07-02 15:00:00" in state["last_sent"]


def test_notification_reminder_diagnostics_reports_backup_overdue_window(monkeypatch, tmp_path):
    monkeypatch.setattr(notification_reminder_api, "datetime", _ThursdayMorning)
    old_key = "backup_overdue:appdata_usb:2026-07-02 10:00:00"
    mark_reminder_sent({"BACKUP_SCRIPTS_DIR": str(tmp_path)}, old_key, now=datetime(2026, 7, 2, 8, 0, 0).timestamp())
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {"appdata_usb": {"enabled": True, "cron": "0 10 * * *"}})
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, opts: [{"key": "appdata_usb", "display_name": "Appdata", "enabled": True, "repo_path": "/repo"}])
    monkeypatch.setattr("status_api.get_status_data", lambda cfg: {"backups": [{
        "backup_type": "appdata",
        "location": "usb",
        "timestamp": "2026-07-02 10:04:45",
        "status": "success",
    }]})
    monkeypatch.setattr("restore_tests_api.list_restore_test_plan", lambda cfg: {"jobs": []})

    result = notification_reminder_api.get_notification_reminder_diagnostics({
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "backup_overdue",
        "NOTIFY_EMAIL_EVENTS": "",
        "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": "6",
        "NTFY_ENABLED": "false",
    })

    assert result["enabled"] is True
    assert result["backup_overdue"]["channels"] == ["unraid"]
    item = result["backup_overdue"]["items"][0]
    assert item["job_key"] == "appdata_usb"
    assert item["expected_run"] == "2026-07-03T10:00:00"
    assert item["next_scheduled_run"] == "2026-07-03T10:00:00"
    assert item["overdue_after"] == "2026-07-03T16:00:00"
    assert item["latest_status_at"] == "2026-07-02T10:04:45"
    assert item["state"] == "current"
    assert item["sent"] is False
    assert old_key in read_notification_state({"BACKUP_SCRIPTS_DIR": str(tmp_path)})["last_sent"]


def test_notification_reminder_diagnostics_reports_apprise_channel(monkeypatch, tmp_path):
    store = tmp_path / "config" / "apprise-profiles.json"
    secret = tmp_path / "secrets" / ".apprise-profile-reminders.url"
    store.parent.mkdir(parents=True)
    secret.parent.mkdir(parents=True)
    store.write_text(json.dumps({
        "schema_version": 1,
        "profiles": [{
            "id": "reminders",
            "name": "Reminder Alerts",
            "enabled": True,
            "provider": "ntfy",
            "selected_events": ["backup_overdue"],
            "timeout_seconds": 15,
            "retry_policy": {"attempts": 1, "backoff_seconds": 0},
            "priority": "default",
            "default": True,
            "url_set": True,
        }],
    }), encoding="utf-8")
    secret.write_text("json://token@example.test\n", encoding="utf-8")
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {})
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, opts: [])
    monkeypatch.setattr("status_api.get_status_data", lambda cfg: {"backups": []})
    monkeypatch.setattr("restore_tests_api.list_restore_test_plan", lambda cfg: {"jobs": []})

    result = notification_reminder_api.get_notification_reminder_diagnostics({
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "none",
        "NOTIFY_EMAIL_EVENTS": "",
        "NTFY_ENABLED": "false",
    })

    assert result["enabled"] is True
    assert result["backup_overdue"]["channels"] == ["apprise"]
    assert result["restore_test_overdue"]["channels"] == []


def test_notification_reminder_diagnostics_distinguishes_missed_and_next_backup_run(monkeypatch, tmp_path):
    monkeypatch.setattr(notification_reminder_api, "datetime", _MondayMorning)
    missed_key = "backup_overdue:photos_usb:2026-07-05 14:00:00"
    mark_reminder_sent({"BACKUP_SCRIPTS_DIR": str(tmp_path)}, missed_key, now=datetime(2026, 7, 5, 21, 25, 51).timestamp())
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {"photos_usb": {"enabled": True, "cron": "0 14 * * 0"}})
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, opts: [{"key": "photos_usb", "display_name": "Photos - USB", "enabled": True, "repo_path": "/repo"}])
    monkeypatch.setattr("status_api.get_status_data", lambda cfg: {"backups": [{
        "backup_type": "photos",
        "location": "usb",
        "timestamp": "2026-07-01 07:58:54",
        "status": "success",
    }]})
    monkeypatch.setattr("restore_tests_api.list_restore_test_plan", lambda cfg: {"jobs": []})

    result = notification_reminder_api.get_notification_reminder_diagnostics({
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "backup_overdue",
        "NOTIFY_EMAIL_EVENTS": "",
        "NOTIFY_REMINDER_INTERVAL_HOURS": "24",
        "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": "6",
        "NTFY_ENABLED": "false",
    })

    item = result["backup_overdue"]["items"][0]
    assert item["job_key"] == "photos_usb"
    assert item["expected_run"] == "2026-07-05T14:00:00"
    assert item["next_scheduled_run"] == "2026-07-12T14:00:00"
    assert item["overdue_after"] == "2026-07-05T20:00:00"
    assert item["latest_status_at"] == "2026-07-01T07:58:54"
    assert item["state"] == "overdue_waiting"
    assert item["sent"] is True
    assert item["next_allowed_at"] == "2026-07-06T21:25:51"


def test_notification_reminder_diagnostics_reports_sent_restore_wait(monkeypatch, tmp_path):
    monkeypatch.setattr(notification_reminder_api, "datetime", _WednesdayLate)
    key = "restore_test_overdue:flash_local:2026-07-01T09:00:00"
    mark_reminder_sent({"BACKUP_SCRIPTS_DIR": str(tmp_path)}, key, now=datetime(2026, 7, 1, 20, 0, 0).timestamp())
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {})
    monkeypatch.setattr("restore_tests_api.list_restore_test_plan", lambda cfg: {"jobs": [{
        "job_key": "flash_local",
        "display_name": "Flash - Lokal",
        "enabled": True,
        "location": "local",
        "policy": {"mode": "scheduled", "level": 2, "interval_days": 30},
        "next_due_at": "2026-07-01T09:00:00",
        "last_test_date": "2026-06-01 09:00:00",
        "is_overdue": True,
    }]})

    result = notification_reminder_api.get_notification_reminder_diagnostics({
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "restore_test_overdue",
        "NOTIFY_EMAIL_EVENTS": "",
        "NOTIFY_REMINDER_INTERVAL_HOURS": "24",
        "NTFY_ENABLED": "false",
    })

    item = result["restore_test_overdue"]["items"][0]
    assert item["job_key"] == "flash_local"
    assert item["state"] == "overdue_waiting"
    assert item["sent"] is True
    assert item["next_allowed_at"]


def test_restore_overdue_reminder_skips_rows_without_due_marker(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("lib.notification_events.notify", lambda **kwargs: calls.append(kwargs["subject"]) or True)
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {})
    monkeypatch.setattr("restore_tests_api.list_restore_test_plan", lambda cfg: {"jobs": [{
        "job_key": "flash_local",
        "display_name": "Flash - Lokal",
        "enabled": True,
        "location": "local",
        "policy": {"mode": "scheduled", "level": 2, "interval_days": 30},
        "next_due_at": "",
        "last_test_date": "",
        "is_overdue": True,
    }]})

    result = notification_reminder_api.run_due_notification_reminders({
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "restore_test_overdue",
        "NOTIFY_EMAIL_EVENTS": "",
        "NTFY_ENABLED": "false",
    })

    state = read_notification_state({"BACKUP_SCRIPTS_DIR": str(tmp_path)})
    assert result["sent"] == 0
    assert result["rows"][0]["reason"] == "missing_due_marker"
    assert calls == []
    assert not any(key.endswith(":never") for key in state["last_sent"])


def test_backup_overdue_expected_run_supports_simple_crons():
    now = datetime(2026, 7, 1, 12, 0, 0)
    assert notification_reminder_api._latest_expected_run("0 9 * * 1-5", now) == datetime(2026, 7, 1, 9, 0, 0)
    assert notification_reminder_api._latest_expected_run("0 9 * * 1,3,5", now) == datetime(2026, 7, 1, 9, 0, 0)
    assert notification_reminder_api._latest_expected_run("0 9 * * 1", now) == datetime(2026, 6, 29, 9, 0, 0)
    assert notification_reminder_api._latest_expected_run("0 9 1 * *", now) == datetime(2026, 7, 1, 9, 0, 0)
    assert notification_reminder_api._latest_expected_run("0 9 * * */2", now) is None
    assert notification_reminder_api._next_expected_run("0 9 * * 1-5", now) == datetime(2026, 7, 2, 9, 0, 0)
    assert notification_reminder_api._next_expected_run("0 9 * * 1,3,5", now) == datetime(2026, 7, 3, 9, 0, 0)
    assert notification_reminder_api._next_expected_run("0 9 * * 1", now) == datetime(2026, 7, 6, 9, 0, 0)
    assert notification_reminder_api._next_expected_run("0 9 1 * *", now) == datetime(2026, 8, 1, 9, 0, 0)
    assert notification_reminder_api._next_expected_run("0 9 * * */2", now) is None


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 29, 12, 0, 0)


class _WednesdayNoon(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 1, 12, 0, 0)


class _WednesdayLate(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 1, 23, 34, 54)


class _ThursdayMorning(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 2, 11, 34, 54)


class _ThursdayLateNight(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 2, 23, 47, 49)


class _FridayLateNight(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 3, 23, 1, 25)


class _MondayMorning(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 6, 9, 5, 0)


def test_backup_overdue_sender_does_not_send_when_diagnostics_are_current_after_success(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("lib.notification_events.notify", lambda **kwargs: calls.append(kwargs["job_name"]) or True)
    monkeypatch.setattr(notification_reminder_api, "datetime", _FridayLateNight)
    schedules = {
        "appdata_local": {"enabled": True, "cron": "0 9 * * 1-5"},
        "flash_local": {"enabled": True, "cron": "0 9 * * 1-5"},
        "appdata_usb": {"enabled": True, "cron": "0 10 * * 1-5"},
        "flash_usb": {"enabled": True, "cron": "0 10 * * 1-5"},
        "sonstiges_usb": {"enabled": True, "cron": "0 15 * * 1-5"},
    }
    jobs = [
        {"key": "appdata_local", "display_name": "Appdata - Lokal", "enabled": True, "repo_path": "/repo/appdata-local"},
        {"key": "flash_local", "display_name": "Flash - Lokal", "enabled": True, "repo_path": "/repo/flash-local"},
        {"key": "appdata_usb", "display_name": "Appdata - USB", "enabled": True, "repo_path": "/repo/appdata-usb"},
        {"key": "flash_usb", "display_name": "Flash - USB", "enabled": True, "repo_path": "/repo/flash-usb"},
        {"key": "sonstiges_usb", "display_name": "Sonstiges - USB", "enabled": True, "repo_path": "/repo/sonstiges-usb"},
    ]
    backups = [
        {"key": "appdata_local", "backup_type": "appdata", "location": "local", "timestamp": "2026-07-03 09:06:20", "status": "success"},
        {"key": "flash_local", "backup_type": "flash", "location": "local", "timestamp": "2026-07-03 13:10:15", "status": "success"},
        {"key": "appdata_usb", "backup_type": "appdata", "location": "usb", "timestamp": "2026-07-03 10:07:51", "status": "success"},
        {"key": "flash_usb", "backup_type": "flash", "location": "usb", "timestamp": "2026-07-03 10:00:12", "status": "success"},
        {"key": "sonstiges_usb", "backup_type": "sonstiges", "location": "usb", "timestamp": "2026-07-03 15:03:32", "status": "success"},
    ]
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: schedules)
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, opts: jobs)
    monkeypatch.setattr("status_api.get_status_data", lambda cfg: {"backups": backups})
    monkeypatch.setattr("restore_tests_api.list_restore_test_plan", lambda cfg: {"jobs": []})
    cfg = {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "backup_overdue",
        "NOTIFY_EMAIL_EVENTS": "",
        "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": "6",
        "NTFY_ENABLED": "false",
    }
    for key in (
        "backup_overdue:appdata_local:2026-07-03 09:00:00",
        "backup_overdue:flash_local:2026-07-03 09:00:00",
        "backup_overdue:appdata_usb:2026-07-03 10:00:00",
        "backup_overdue:flash_usb:2026-07-03 10:00:00",
        "backup_overdue:sonstiges_usb:2026-07-03 15:00:00",
    ):
        mark_reminder_sent({"BACKUP_SCRIPTS_DIR": str(tmp_path)}, key, now=datetime(2026, 7, 3, 23, 0, 0).timestamp())

    diagnostics = notification_reminder_api.get_notification_reminder_diagnostics(cfg)
    result = notification_reminder_api.run_due_notification_reminders(cfg)
    state = read_notification_state({"BACKUP_SCRIPTS_DIR": str(tmp_path)})

    assert {item["job_key"]: item["state"] for item in diagnostics["backup_overdue"]["items"]} == {
        "appdata_local": "current",
        "appdata_usb": "current",
        "flash_local": "current",
        "flash_usb": "current",
        "sonstiges_usb": "current",
    }
    assert result["sent"] == 0
    assert calls == []
    assert state["last_sent"] == {}


def test_backup_overdue_sender_skips_when_latest_status_is_missing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("lib.notification_events.notify", lambda **kwargs: calls.append(kwargs["job_name"]) or True)
    monkeypatch.setattr(notification_reminder_api, "datetime", _FridayLateNight)
    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {"appdata_local": {"enabled": True, "cron": "0 9 * * 1-5"}})
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, opts: [{"key": "appdata_local", "display_name": "Appdata - Lokal", "enabled": True, "repo_path": "/repo"}])
    monkeypatch.setattr("status_api.get_status_data", lambda cfg: {"backups": []})
    monkeypatch.setattr("restore_tests_api.list_restore_test_plan", lambda cfg: {"jobs": []})

    result = notification_reminder_api.run_due_notification_reminders({
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "backup_overdue",
        "NOTIFY_EMAIL_EVENTS": "",
        "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": "6",
        "NTFY_ENABLED": "false",
    })
    diagnostics = notification_reminder_api.get_notification_reminder_diagnostics({
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "NOTIFY_UNRAID_EVENTS": "backup_overdue",
        "NOTIFY_EMAIL_EVENTS": "",
        "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": "6",
        "NTFY_ENABLED": "false",
    })

    assert result["checked"] == 1
    assert result["sent"] == 0
    assert result["rows"][0]["reason"] == "missing_status"
    assert calls == []
    assert diagnostics["backup_overdue"]["items"][0]["state"] == "missing_status"


def test_restore_runner_uses_restore_status_dir_and_test_date(tmp_path):
    script_path = ROOT / "runtime" / "scripts" / "borg_restore_test.py"
    spec = importlib.util.spec_from_file_location("borg_restore_test_for_test", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    status_dir = tmp_path / "backup-status"
    restore_status = tmp_path / "restore-status"
    restore_status.mkdir(parents=True)
    test_file = restore_status / "flash_local.test"
    test_file.write_text(json.dumps({
        "test_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "test_result": "success",
    }), encoding="utf-8")
    old = datetime(2020, 1, 1).timestamp()
    os.utime(test_file, (old, old))

    args = type("Args", (), {"level": 2, "force": False, "scheduled": True})()
    tester = module.RestoreTest({
        "STATUS_DIR": str(status_dir),
        "GLOBAL_LOG_DIR": str(tmp_path / "logs"),
        "RESTORE_TEST_INTERVAL_DAYS": "30",
    }, args)
    try:
        assert tester.status_dir == restore_status
        assert tester._should_test("flash_local") is False
    finally:
        tester.close()
