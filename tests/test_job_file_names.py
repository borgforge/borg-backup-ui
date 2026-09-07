"""Readable run files retain permanent ownership and safe filename sizes (#486)."""

import json
import logging
import os
import sys
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / "api", ROOT / "runtime", ROOT / "runtime/lib"):
    sys.path.insert(0, str(folder))

from job_fixtures import job_id
from job_identity import job_file_component, job_log_filename, job_log_paths, job_run_date_tag
from lib.backup_job import BackupJob, BackupJobConfig
from lib.status import BackupStatus
from jobs_api import _fallback_runtime_log


def make_config(tmp_path, key, name="TestJobNeuerName"):
    return BackupJobConfig(
        job_id=key, job_name=name, backup_type="old_type", backup_location="storagebox",
        lock_file=tmp_path / "job.lock", log_dir=tmp_path, log_file=tmp_path / "run.log",
        backup_paths=[], borg_cache_dir=tmp_path / "cache", date_tag="2026-09-07_15-00-01",
        status_dir=tmp_path / "status",
    )


@pytest.mark.parametrize("name", ["TestJobNeuerName", "ä" * 100, "資料" * 50,
                                    "../My Job/USB:*?\\\nName", "🌍" * 100])
def test_run_files_fit_utf8_filename_limit_and_preserve_full_identity(tmp_path, name):
    key = job_id("readable")
    labels = ["2026-09-07_15-00-01", "2026-09-07_15-00-01_USB_NOT_MOUNTED",
              "activity-" + "a" * 96]
    for label in labels:
        filename = job_log_filename(name, "storagebox", key, label)
        assert filename.startswith("BBUI-")
        assert filename.endswith(f"_storagebox_{key}--{label}.log")
        assert len(filename.encode("utf-8")) <= 255
        assert Path(filename).name == filename
        assert not any(char in filename for char in '\\/:*?\n')
        (tmp_path / filename).write_text("complete log")
    status = BackupStatus(job_id=key, job_name=name, backup_type="old_type", location="storagebox")
    path = status.save(tmp_path)
    assert len(path.name.encode("utf-8")) <= 255
    assert path.name.endswith(f"_{job_file_component(name, 'storagebox', key)}.status")
    payload = json.loads(path.read_text())
    assert payload["job_name"] == name
    assert payload["job_id"] == key
    assert BackupStatus.from_file(path).key == key


def test_readable_names_and_log_header_match_the_job_at_run_time(tmp_path, caplog, monkeypatch):
    key = job_id("readable")
    cfg = make_config(tmp_path, key)
    assert job_log_filename(cfg.job_name, cfg.backup_location, key, cfg.date_tag) == (
        f"BBUI-TestJobNeuerName_storagebox_{key}--2026-09-07_15-00-01.log"
    )
    job = BackupJob(cfg)
    with caplog.at_level(logging.INFO):
        job._log_startup_banner()
    assert "TestJobNeuerName" in caplog.text and key in caplog.text
    job._write_mini_log("USB_NOT_MOUNTED", ["Skipped"])
    mini = next(tmp_path.glob("*_USB_NOT_MOUNTED.log"))
    assert f"TestJobNeuerName_storagebox_{key}--" in mini.name
    assert f"Job ID: {key}" in mini.read_text()
    monkeypatch.setattr(job, "_emit_lifecycle_finished", lambda **_: None)
    job._skip_reason = "USB is not mounted"
    job._save_skip_status()
    skipped = json.loads(next(cfg.status_dir.glob("*.status")).read_text())
    assert skipped["job_name"] == cfg.job_name and skipped["job_id"] == key


def test_log_lookup_and_retention_follow_id_across_renames_without_touching_other_jobs(tmp_path):
    selected, other = job_id("selected"), job_id("other")
    old = tmp_path / job_log_filename("Previous name", "local", selected, "2026-09-01_10-00-00")
    legacy = tmp_path / f"Borg-Backup_{selected}--2026-09-01_10-00-00.log"
    fresh = tmp_path / job_log_filename("Renamed", "usb", selected, "2026-09-07_10-00-00")
    foreign = tmp_path / job_log_filename("Previous name", "local", other, "2026-09-01_10-00-00")
    # A job name that contains another ID must not trick ownership matching.
    confusing = tmp_path / job_log_filename(f"Fake_local_{selected}--suffix", "local", other, "2026-09-01_10-00-00")
    for path in (old, legacy, fresh, foreign, confusing):
        path.write_text("preserve ownership")
        os.utime(path, (1, 1))
    os.utime(fresh, None)
    assert set(job_log_paths(tmp_path, selected)) == {old, legacy, fresh}
    assert _fallback_runtime_log({"GLOBAL_LOG_DIR": str(tmp_path)}, selected, "") == str(fresh)
    BackupJob(make_config(tmp_path, selected, "Another rename")).cleanup_old_logs()
    assert not old.exists() and not legacy.exists()
    assert fresh.exists() and foreign.exists() and confusing.exists()


@pytest.mark.parametrize("archived", [False, True])
def test_saved_activity_log_is_found_after_capture_state_and_job_name_change(tmp_path, monkeypatch, archived):
    import activity_log
    import activity_log_capture
    import jobs_api
    monkeypatch.setattr(activity_log_capture, "CAPTURE_ROOT", tmp_path / "ram")
    monkeypatch.setattr(jobs_api.JobManager, "get", classmethod(lambda cls: jobs_api.JobManager()))
    monkeypatch.setattr(jobs_api, "durable_running_states", lambda _: {})
    monkeypatch.setattr("job_control.read_control_state", lambda _: {})
    key, run = job_id("activity"), "20260907T130001Z-123456abcdef"
    logs = tmp_path / "logs"
    active, record_path = activity_log_capture.prepare_capture(
        key, run, logs, job_name="Name at start", location="usb",
    )
    active.write_text("A changed-Größe.stl\n")
    assert activity_log_capture.retain_capture(record_path, 0)
    record = activity_log_capture.read_record(record_path)
    retained = Path(record["retained_file"])
    assert retained.name == f"BBUI-Name_at_start_usb_{key}--{job_run_date_tag(run)}.log"
    cfg = make_config(tmp_path, key, "Name at start")
    cfg.retained_log_file = retained
    cfg.backup_location = "usb"
    monkeypatch.setenv("BORG_UI_RUN_ID", run)
    job = BackupJob(cfg)
    job.set_result(0)
    status_path = job._save_status(10)
    saved = BackupStatus.from_file(status_path)
    assert saved.run_id == run and saved.file_activity is True
    if archived:
        archive_dir = cfg.status_dir / "archive"
        archive_dir.mkdir()
        status_path.rename(archive_dir / status_path.name)
    record_path.unlink()  # Reboot loses the RAM capture record.
    config = {"GLOBAL_LOG_DIR": str(logs), "STATUS_DIR": str(cfg.status_dir)}
    resolved, _ = activity_log.resolve_activity_run(config, key, run)
    assert resolved == retained
    result = activity_log.get_activity_window(config, {"job": [key], "run": [run]})
    assert result["text"] == "A changed-Größe.stl\n"
    assert result["exit_code"] == 0
    # A different run of the same job must not read this run's file.
    with pytest.raises(FileNotFoundError):
        activity_log.get_activity_window(config, {"job": [key], "run": [run + "0"]})


def test_file_list_option_uses_the_same_retained_filename_as_normal_runner(tmp_path, monkeypatch):
    import activity_log_capture
    import wizard_runner
    from test_job_identity_integration import migrated

    config, jobs, ids, root = migrated(tmp_path)
    key = ids[jobs[0]["job_key"]]
    monkeypatch.setattr(activity_log_capture, "CAPTURE_ROOT", tmp_path / "ram")
    monkeypatch.setenv("BORG_UI_RUN_ID", "20260907T130001Z-123456abcdef")
    monkeypatch.setenv("BORG_UI_JOB_NAME", "Name at start")
    monkeypatch.setenv("BORG_UI_JOB_LOCATION", "local")
    monkeypatch.setenv("BORG_UI_FILE_ACTIVITY_RUN", "0")
    for name in ("LOG_FILE", "BORG_UI_CAPTURE_LOG", "BORG_UI_RETAINED_LOG"):
        monkeypatch.delenv(name, raising=False)
    normal, _ = wizard_runner._load_env_from_job(key, root / "scripts", root)
    expected = Path(normal["LOG_FILE"])
    active, record = activity_log_capture.prepare_capture(
        key, os.environ["BORG_UI_RUN_ID"], expected.parent,
        job_name="Name at start", location="local",
    )
    retained = activity_log_capture.read_record(record)["retained_file"]
    monkeypatch.setenv("BORG_UI_FILE_ACTIVITY_RUN", "1")
    monkeypatch.setenv("BORG_UI_CAPTURE_LOG", str(active))
    monkeypatch.setenv("BORG_UI_RETAINED_LOG", retained)
    enabled, _ = wizard_runner._load_env_from_job(key, root / "scripts", root)
    assert Path(enabled["BORG_UI_RETAINED_LOG"]) == expected
    assert enabled["DATE_TAG"] == normal["DATE_TAG"]
    assert enabled["LOG_FILE"] == str(active)
    assert "--activity-" not in expected.name


def test_failed_startup_log_reopens_without_status_or_ram_after_restart(tmp_path, monkeypatch):
    import activity_log
    import activity_log_capture
    import jobs_api

    key = job_id("startup-failure")
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(activity_log_capture, "CAPTURE_ROOT", tmp_path / "ram")
    manager = jobs_api.JobManager()
    monkeypatch.setattr(jobs_api.JobManager, "get", classmethod(lambda cls: manager))
    monkeypatch.setattr(jobs_api, "durable_running_states", lambda _: {})
    monkeypatch.setattr("job_control.read_control_state", lambda _: {})
    assert manager.start(key, [sys.executable, "-c", "print('ERROR simulated startup failure'); raise SystemExit(2)"], logs, {
        "BORG_UI_FILE_ACTIVITY_RUN": "1", "BORG_UI_ACTIVITY_LOG_DIR": str(logs),
        "BORG_UI_JOB_NAME": "Photos", "BORG_UI_JOB_LOCATION": "local",
    }) == (True, None)
    state = manager._states[key]
    assert state.proc.wait(timeout=10) == 2
    deadline = time.monotonic() + 5
    while not state.finished and time.monotonic() < deadline:
        time.sleep(0.01)
    assert state.finished
    retained = Path(activity_log_capture.read_record(state.capture_record_file)["retained_file"])
    assert retained.name == f"BBUI-Photos_local_{key}--{job_run_date_tag(state.run_id)}.log"
    assert f"job_id={key} run_id={state.run_id}" in retained.read_text().splitlines()[0]
    state.capture_record_file.unlink()
    manager._states.clear()
    config = {"GLOBAL_LOG_DIR": str(logs), "STATUS_DIR": str(tmp_path / "missing-status")}
    params = {"job": [key], "run": [state.run_id]}
    result = activity_log.get_activity_window(config, params)
    assert "ERROR simulated startup failure" in result["text"]
    assert result["running"] is False
    # Subsequent windows only open the requested log, not its identification
    # header or unrelated history again.
    opened = []
    original_open = activity_log.open_activity_file
    def track_open(path):
        opened.append(path)
        return original_open(path)
    monkeypatch.setattr(activity_log, "open_activity_file", track_open)
    activity_log.get_activity_window(config, params)
    assert opened == [retained]


@pytest.mark.parametrize("file_activity", [False, True])
@pytest.mark.parametrize("reason,suffix", [
    ("parity_active", "SKIPPED_PARITY"),
    ("usb_not_mounted", "USB_NOT_MOUNTED"),
    ("usb_not_writable", "USB_NOT_WRITABLE"),
])
def test_skipped_runs_keep_readable_log_names_and_status_links(tmp_path, monkeypatch, file_activity, reason, suffix):
    import activity_log_capture

    key, run = job_id("skip"), "20260907T130001Z-123456abcdef"
    monkeypatch.setenv("BORG_UI_RUN_ID", run)
    monkeypatch.setattr(activity_log_capture, "CAPTURE_ROOT", tmp_path / "ram")
    cfg = make_config(tmp_path, key, "Photos")
    cfg.backup_location = "usb"
    cfg.date_tag = job_run_date_tag(run)
    retained = cfg.log_dir / job_log_filename(cfg.job_name, cfg.backup_location, key, cfg.date_tag)
    record = None
    if file_activity:
        cfg.log_file, record = activity_log_capture.prepare_capture(
            key, run, cfg.log_dir, job_name=cfg.job_name, location=cfg.backup_location,
        )
        cfg.retained_log_file = retained
    else:
        cfg.log_file = retained
    cfg.log_file.write_text("Backup run started\n")
    job = BackupJob(cfg)
    monkeypatch.setattr(job, "_emit_lifecycle_finished", lambda **_: None)
    monkeypatch.setattr(job, "_send_notification_event", lambda *args, **kwargs: None)
    if reason == "parity_active":
        monkeypatch.setattr("lib.backup_job.shutil.which", lambda _: "/fake/mdcmd")
        monkeypatch.setattr("lib.backup_job.subprocess.run", lambda *args, **kwargs: SimpleNamespace(
            stdout="mdResyncAction=check\nmdResyncPos=50\nmdResyncSize=100\n",
        ))
        check = job.check_parity
    else:
        mount = tmp_path / "usb-mount"
        if reason == "usb_not_writable":
            mount.mkdir()
            monkeypatch.setattr("lib.backup_job.os.access", lambda *args: False)
        check = lambda: job.check_usb_mount(mount)
    with pytest.raises(SystemExit) as stopped:
        check()
    assert stopped.value.code == 0
    mini = cfg.log_dir / job_log_filename(cfg.job_name, cfg.backup_location, key, f"{cfg.date_tag}_{suffix}")
    assert mini.is_file() and key in mini.read_text()
    status_path = next(cfg.status_dir.glob("*.status"))
    data = json.loads(status_path.read_text())
    assert data["status"] == "skipped" and data["skip_reason_code"] == reason
    assert data["log_file"] == str(retained)
    assert data["run_id"] == run and data["file_activity"] is file_activity
    assert status_path.name.endswith(f"_Photos_usb_{key}.status")
    if record:
        assert activity_log_capture.retain_capture(record, 0)
    assert Path(data["log_file"]).is_file()
