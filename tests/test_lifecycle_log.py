from job_fixtures import identified_job, job_id
import json
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))
if str(ROOT / "runtime") not in sys.path:
    sys.path.insert(0, str(ROOT / "runtime"))

from lifecycle_log import emit_lifecycle  # noqa: E402
from lib.backup_job import BackupJob, BackupJobConfig  # noqa: E402
from lib.notification_events import NotificationEvent, send_event  # noqa: E402
from borg_backup_ui import BackupUIHandler  # noqa: E402


def _backup_job_config(tmp_path: Path) -> BackupJobConfig:
    return BackupJobConfig(
        job_name="Flash",
        backup_type="flash",
        backup_location="local",
        job_id=job_id("flash_local"),
        lock_file=tmp_path / "job.lock",
        log_dir=tmp_path / "logs",
        log_file=tmp_path / "logs" / "backup.log",
        backup_paths=[],
        borg_cache_dir=tmp_path / "cache",
        date_tag="2026-07-22",
        status_dir=tmp_path / "status",
    )


def test_emit_lifecycle_writes_masked_key_value_line(tmp_path: Path, monkeypatch):
    log_file = tmp_path / "borg_backup_ui.log"
    monkeypatch.setenv("BORG_UI_MAIN_LOG", str(log_file))

    emit_lifecycle(
        "JOB",
        "finished",
        job_key="flash_local",
        status="failed",
        password="secret-value",
        apprise_profiles=["Critical Alerts (alerts-main)"],
    )

    line = log_file.read_text(encoding="utf-8")
    assert "JOB finished" in line
    assert "job_key=flash_local" in line
    assert "status=failed" in line
    assert "password=***" in line
    assert "secret-value" not in line
    assert 'apprise_profiles=["Critical Alerts (alerts-main)"]' in line


def test_backup_finish_emits_lifecycle_summary(tmp_path: Path, monkeypatch):
    log_file = tmp_path / "borg_backup_ui.log"
    monkeypatch.setenv("BORG_UI_MAIN_LOG", str(log_file))
    monkeypatch.setenv("BORG_UI_JOB_KEY", "flash_local")
    monkeypatch.setenv("BORG_UI_RUN_ID", "run-123")
    monkeypatch.setenv("BORG_UI_REQUEST_ID", "req-123")
    monkeypatch.setenv("BORG_UI_REQUEST_SOURCE", "manual")
    monkeypatch.setenv("BORG_UI_REQUEST_ACTOR", "admin")

    job = BackupJob(_backup_job_config(tmp_path))
    job._start_time = 100.0
    monkeypatch.setattr("lib.backup_job.time.time", lambda: 145.0)
    monkeypatch.setattr(job, "_send_notification_event", lambda *args, **kwargs: None)

    job.set_result(0)
    job._do_finish()

    text = log_file.read_text(encoding="utf-8")
    assert "JOB finished" in text
    assert "request_id=req-123" in text
    assert f"job_key={job_id('flash_local')}" in text
    assert "run_id=run-123" in text
    assert "status=success" in text
    assert "exit_code=0" in text
    assert "duration_seconds=45" in text
    assert "status_file=" in text


@pytest.mark.parametrize('outcomes', [
    {'pre': ('failed', 41)},
    {'pre': ('timeout', 124)},
    {'pre': ('launch_failed', 2)},
    {'post': ('failed', 42)},
    {'pre': ('failed', 41), 'post': ('failed', 42)},
])
def test_script_failures_identify_causes_in_log_status_and_notification(
    tmp_path, monkeypatch, caplog, outcomes,
):
    job = BackupJob(_backup_job_config(tmp_path))
    job._completion_repo_info = (0, ('unknown', 'unknown', 'unknown'))
    notifications = []
    monkeypatch.setattr(job, '_send_notification_event', lambda *args: notifications.append(args))
    monkeypatch.setattr(job, '_emit_lifecycle_finished', lambda **kwargs: None)
    if 'pre' not in outcomes:
        job.set_result(0)
        job.backup_exit_code = 0
    for phase, (status, code) in outcomes.items():
        job.record_hook_result(phase, {'name': 'Test', 'status': status, 'exit_code': code})
    with caplog.at_level(logging.INFO):
        job._do_finish()
        job._do_finish()  # Finalization must not notify twice.
    saved = json.loads(job._last_status_file.read_text())
    assert saved['exit_code'] == 2 and saved['status'] == 'error'
    assert saved['backup_exit_code'] == (None if 'pre' in outcomes else 0)
    assert len(notifications) == 1 and notifications[0][0] == 'backup_failed'
    assert 'Backup job failed (job exit 2)' in caplog.text
    assert 'BACKUP FAILED' in caplog.text
    assert 'BACKUP COMPLETED' not in caplog.text
    assert 'Borg backup failed' not in caplog.text
    for phase, (status, code) in outcomes.items():
        message = f'{phase.title()} script {status} (exit {code})'
        assert message in caplog.text
        assert message in saved['error_message']
        assert message in notifications[0][2]
        assert saved['hook_results'][phase]['exit_code'] == code
    assert ('Backup was not started' in caplog.text) == ('pre' in outcomes)
    assert ('Backup was not started' in notifications[0][2]) == ('pre' in outcomes)


@pytest.mark.parametrize('code,cancelled,heading', [
    (0, False, 'BACKUP COMPLETED'),
    (1, False, 'BACKUP COMPLETED WITH WARNINGS'),
    (2, False, 'BACKUP FAILED'),
    (130, True, 'BACKUP CANCELLED'),
])
def test_backup_log_footer_matches_final_result(tmp_path, monkeypatch, caplog, code, cancelled, heading):
    job = BackupJob(_backup_job_config(tmp_path))
    job.set_result(code)
    if cancelled:
        job.set_cancelled()
    monkeypatch.setattr(job, '_send_notification_event', lambda *args: None)
    monkeypatch.setattr(job, '_save_status', lambda duration: None)
    monkeypatch.setattr(job, '_emit_lifecycle_finished', lambda **kwargs: None)
    with caplog.at_level(logging.INFO):
        job._do_finish()
    assert [record.message.strip() for record in caplog.records if record.message.strip().startswith('BACKUP ')] == [heading]


def test_backup_exit_refreshes_unraid_widget_cache_after_status_and_lock_release(tmp_path: Path, monkeypatch):
    calls: list[tuple[str, object]] = []

    def fake_widget_refresh(config, *, app_version=""):
        calls.append(("widget", {"config": dict(config), "app_version": app_version}))

    monkeypatch.setitem(
        sys.modules,
        "unraid_dashboard_widget",
        SimpleNamespace(write_unraid_dashboard_widget_status_file_cache=fake_widget_refresh),
    )
    monkeypatch.setenv("BACKUP_SCRIPTS_DIR", str(tmp_path))
    monkeypatch.setenv("BORG_UI_APP_VERSION", "2026.08.28.1913")

    job = BackupJob(_backup_job_config(tmp_path))
    job._start_time = 100.0
    monkeypatch.setattr("lib.backup_job.time.time", lambda: 145.0)
    monkeypatch.setattr(job, "_send_notification_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        job,
        "_save_status",
        lambda _duration: calls.append(("status", _duration)) or (tmp_path / "status" / "flash.status"),
    )
    monkeypatch.setattr(job, "_remove_lock", lambda: calls.append(("lock", None)))

    job.set_result(0)
    job.__exit__(None, None, None)

    assert [name for name, _payload in calls] == ["status", "lock", "widget"]
    widget_payload = calls[-1][1]
    assert widget_payload["config"]["STATUS_DIR"] == str(tmp_path / "status")
    assert widget_payload["config"]["BACKUP_SCRIPTS_DIR"] == str(tmp_path)
    assert widget_payload["app_version"] == "2026.08.28.1913"


def test_notification_event_emits_lifecycle_summary(tmp_path: Path, monkeypatch):
    log_file = tmp_path / "borg_backup_ui.log"
    monkeypatch.setenv("BORG_UI_MAIN_LOG", str(log_file))
    monkeypatch.setattr("lib.notification_events.notify", lambda **kwargs: True)

    result = send_event(
        {"NOTIFY_UNRAID_EVENTS": "backup_success"},
        NotificationEvent(
            event_type="backup_success",
            title="Backup OK",
            message="done",
            job_key=job_id("flash_local"),
            status="success",
            duration_seconds=45,
            exit_code=0,
            source="backup_job",
        ),
    )

    assert result["unraid"] is True
    text = log_file.read_text(encoding="utf-8")
    assert "JOB notification" in text
    assert f"job_key={job_id('flash_local')}" in text
    assert "event=backup_success" in text
    assert "apprise_mode=queued" in text or "apprise_mode=sync" in text


def test_scheduled_backup_run_sets_lifecycle_source_env(tmp_path: Path, monkeypatch):
    import jobs_api

    captured: dict[str, object] = {}

    class Jobs:
        def start(self, job_key, command, cwd, extra_env=None):
            captured["job_key"] = job_key
            captured["command"] = command
            captured["cwd"] = cwd
            captured["extra_env"] = dict(extra_env or {})
            return True, None

        def get_state(self, job_key):
            return {"running": True, "run_id": "run-scheduled"}

    handler = BackupUIHandler.__new__(BackupUIHandler)
    handler.config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    handler._current_request_id = "req-scheduled"
    handler._read_json_body = lambda: {"job_key": "flash_local", "scheduled": True}
    handler._require_data_dir_ready = lambda: None
    handler._get_current_session_meta = lambda: {}
    handler._has_valid_api_token_header = lambda: True

    monkeypatch.setattr(jobs_api.JobManager, "get", classmethod(lambda cls: Jobs()))
    monkeypatch.setattr(jobs_api, "resolve_scripts_dir", lambda _cfg: tmp_path / "scripts")
    monkeypatch.setattr(jobs_api, "resolve_data_root", lambda _cfg: tmp_path)
    monkeypatch.setattr(jobs_api, "get_job_runtime_state", lambda _cfg, _key: {"running": False})
    monkeypatch.setattr(jobs_api, "discover_jobs", lambda _scripts, _data: [
        SimpleNamespace(
            key="flash_local",
            name="Flash configuration",
            enabled=True,
            standard="wizard",
            backup_type="flash",
            location="local",
        )
    ])

    result = handler._post_run_job()

    assert result == {"started": True, "job_key": "flash_local", "run_id": "run-scheduled"}
    assert captured["job_key"] == "flash_local"
    assert captured["extra_env"]["BORG_UI_REQUEST_ID"] == "req-scheduled"
    assert captured["extra_env"]["BORG_UI_REQUEST_SOURCE"] == "schedule"
    assert captured["extra_env"]["BORG_UI_REQUEST_ACTOR"] == "scheduler"
    assert captured["extra_env"]["BORG_UI_JOB_NAME"] == "Flash configuration"
    assert captured["extra_env"]["BORG_UI_JOB_LOCATION"] == "local"


def test_restore_test_script_contains_lifecycle_summary_hooks():
    source = (ROOT / "runtime" / "scripts" / "borg_restore_test.py").read_text(encoding="utf-8")

    assert source.count('"RESTORE_TEST"') >= 3
    assert '"requested"' in source
    assert '"process_started"' in source
    assert '"finished"' in source
