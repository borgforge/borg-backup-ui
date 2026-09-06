from runtime_fixture_support import job_config_identity
import os
from pathlib import Path
import sys
from types import SimpleNamespace


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
        **job_config_identity("flash"),
        backup_location="local",
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
        job_id="11111111-1111-4111-8111-111111111111",
        status="failed",
        password="secret-value",
        apprise_profiles=["Critical Alerts (alerts-main)"],
    )

    line = log_file.read_text(encoding="utf-8")
    assert "JOB finished" in line
    assert "job_id=11111111-1111-4111-8111-111111111111" in line
    assert "status=failed" in line
    assert "password=***" in line
    assert "secret-value" not in line
    assert 'apprise_profiles=["Critical Alerts (alerts-main)"]' in line


def test_backup_finish_emits_lifecycle_summary(tmp_path: Path, monkeypatch):
    log_file = tmp_path / "borg_backup_ui.log"
    monkeypatch.setenv("BORG_UI_MAIN_LOG", str(log_file))
    monkeypatch.setenv("BORG_UI_JOB_KEY", "old_mutable_key")
    monkeypatch.setenv("BORG_UI_JOB_ID", "environment-must-not-rebind-the-run")
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
    assert "job_id=11111111-1111-4111-8111-111111111111" in text
    assert "run_id=" + job.config.run_id in text
    assert "status=success" in text
    assert "exit_code=0" in text
    assert "duration_seconds=45" in text
    assert "status_file=" in text


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
            job_id="11111111-1111-4111-8111-111111111111",
            status="success",
            duration_seconds=45,
            exit_code=0,
            source="backup_job",
        ),
    )

    assert result["unraid"] is True
    text = log_file.read_text(encoding="utf-8")
    assert "JOB notification" in text
    assert "job_id=11111111-1111-4111-8111-111111111111" in text
    assert "event=backup_success" in text
    assert "apprise_mode=queued" in text or "apprise_mode=sync" in text


def test_scheduled_backup_run_sets_lifecycle_source_env(tmp_path: Path, monkeypatch):
    from test_canonical_job_wizard import setup as setup_fixture, create
    from job_runs import read_run_context
    import jobs_api
    fixture = setup_fixture.__wrapped__(tmp_path)
    result, _ = create(fixture)
    monkeypatch.setenv('BORG_UI_CONTROL_ROOT', str(tmp_path / 'run'))
    captured = {}
    class Jobs:
        def start(self, job_id, command, cwd, extra_env=None, *, run_context=None):
            captured.update(job_id=job_id, command=command, extra_env=extra_env, context=run_context)
            return True, None
    handler = BackupUIHandler.__new__(BackupUIHandler)
    handler.config = fixture[0]
    handler._current_request_id = 'req-scheduled'
    handler._read_json_body = lambda: {'job_id':result['job_id'],'scheduled':True}
    handler._require_data_dir_ready = lambda: None
    handler._get_current_session_meta = lambda: {}
    handler._has_valid_api_token_header = lambda: True
    monkeypatch.setattr(jobs_api.JobManager,'get',classmethod(lambda cls:Jobs()))
    monkeypatch.setattr(jobs_api,'get_job_runtime_state',lambda *_:{'running':False})
    response = handler._post_run_job()
    assert response['started'] and response['job_id'] == result['job_id']
    assert read_run_context(response['job_id'],response['run_id'])['job_id'] == result['job_id']
    assert captured['extra_env']['BORG_UI_REQUEST_ID'] == 'req-scheduled'
    assert captured['extra_env']['BORG_UI_REQUEST_SOURCE'] == 'schedule'
    assert captured['extra_env']['BORG_UI_REQUEST_ACTOR'] == 'scheduler'


def test_restore_test_script_contains_lifecycle_summary_hooks():
    source = (ROOT / "runtime" / "scripts" / "borg_restore_test.py").read_text(encoding="utf-8")

    assert source.count('"RESTORE_TEST"') >= 3
    assert '"requested"' in source
    assert '"process_started"' in source
    assert '"finished"' in source
