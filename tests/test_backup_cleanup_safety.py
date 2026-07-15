from pathlib import Path
import logging
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "runtime"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from runtime.lib.backup_job import (  # noqa: E402
    BackupJob,
    BackupJobConfig,
    RUNTIME_RECOVERY_FAILED,
)


def _config(tmp_path: Path) -> BackupJobConfig:
    return BackupJobConfig(
        job_name="cleanup-test",
        backup_type="appdata",
        backup_location="local",
        lock_file=tmp_path / "backup.lock",
        log_dir=tmp_path,
        log_file=tmp_path / "backup.log",
        backup_paths=[tmp_path],
        borg_cache_dir=tmp_path / "cache",
        date_tag="2026-07-15",
    )


def _entered_job(tmp_path: Path) -> BackupJob:
    job = BackupJob(_config(tmp_path))
    job._create_lock()
    job.set_result(0, final_msg="Backup completed.")
    return job


def test_docker_recovery_failure_does_not_skip_vm_or_completion(
    monkeypatch,
    tmp_path: Path,
    caplog,
):
    job = _entered_job(tmp_path)
    job._docker_stop_result = object()
    job._vm_shutdown_result = object()
    calls = []

    def fail_docker():
        calls.append("docker")
        raise RuntimeError("password=must-not-be-logged")

    monkeypatch.setattr(job, "start_docker", fail_docker)
    monkeypatch.setattr(job, "start_vms", lambda: calls.append("vm"))
    monkeypatch.setattr(job, "_do_finish", lambda: calls.append("finish"))

    with caplog.at_level(logging.ERROR, logger="runtime.lib.backup_job"):
        with pytest.raises(RuntimeError, match="Backup cleanup failed"):
            job.__exit__(None, None, None)

    assert calls == ["docker", "vm", "finish"]
    assert job._borg_exit == 2
    assert job._failure_code == RUNTIME_RECOVERY_FAILED
    assert not job.config.lock_file.exists()
    assert "Docker recovery (RuntimeError)" in caplog.text
    assert "must-not-be-logged" not in caplog.text


def test_vm_recovery_failure_still_runs_completion(monkeypatch, tmp_path: Path):
    job = _entered_job(tmp_path)
    job._vm_shutdown_result = object()
    calls = []

    def fail_vm():
        calls.append("vm")
        raise RuntimeError("VM restart failed")

    monkeypatch.setattr(job, "start_vms", fail_vm)
    monkeypatch.setattr(job, "_do_finish", lambda: calls.append("finish"))

    with pytest.raises(RuntimeError, match="Backup cleanup failed"):
        job.__exit__(None, None, None)

    assert calls == ["vm", "finish"]
    assert job._borg_exit == 2
    assert job._failure_code == RUNTIME_RECOVERY_FAILED
    assert not job.config.lock_file.exists()


def test_completion_failure_still_releases_lock(monkeypatch, tmp_path: Path):
    job = _entered_job(tmp_path)

    def fail_completion():
        raise OSError("status write failed")

    monkeypatch.setattr(job, "_do_finish", fail_completion)

    with pytest.raises(RuntimeError, match="Backup cleanup failed"):
        job.__exit__(None, None, None)

    assert not job.config.lock_file.exists()


def test_skip_status_failure_does_not_exit_successfully(monkeypatch, tmp_path: Path):
    job = _entered_job(tmp_path)

    def fail_skip_status():
        raise OSError("skip status write failed")

    monkeypatch.setattr(job, "_persist_skip_status_once", fail_skip_status)

    with pytest.raises(RuntimeError, match="Backup cleanup failed"):
        job.__exit__(SystemExit, SystemExit(0), None)

    assert not job.config.lock_file.exists()


def test_original_exception_wins_over_lock_release_failure(
    monkeypatch,
    tmp_path: Path,
    caplog,
):
    job = BackupJob(_config(tmp_path))
    original_remove_lock = job._remove_lock

    def remove_then_fail():
        original_remove_lock()
        raise OSError("token=must-not-be-logged")

    monkeypatch.setattr(job, "_remove_lock", remove_then_fail)
    monkeypatch.setattr(job, "_do_finish", lambda: None)

    with caplog.at_level(logging.ERROR, logger="runtime.lib.backup_job"):
        with pytest.raises(ValueError, match="original backup failure"):
            with job:
                raise ValueError("original backup failure")

    assert not job.config.lock_file.exists()
    assert "lock release (OSError)" in caplog.text
    assert "must-not-be-logged" not in caplog.text
