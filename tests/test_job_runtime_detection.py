import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import jobs_api  # noqa: E402
from jobs_api import durable_running_states, is_resource_active, stream_job_output  # noqa: E402
from wizard_runner import ResourceLockSet  # noqa: E402


def test_active_resource_lock_restores_running_job_and_log(tmp_path: Path):
    log_file = tmp_path / "logs" / "Borg-Backup_appdata_usb--2026.log"
    log_file.parent.mkdir()
    log_file.write_text("backup running\n", encoding="utf-8")
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    (lock_dir / "repo.lock.json").write_text(json.dumps({
        "resource": "repo:/mnt/disks/usb/appdata",
        "job_key": "appdata_usb",
        "pid": os.getpid(),
        "started_at": "2026-07-10T09:00:00+00:00",
        "updated_at": "2026-07-10T09:01:00+00:00",
        "log_file": str(log_file),
    }), encoding="utf-8")
    config = {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "BORG_RESOURCE_LOCK_DIR": str(lock_dir),
    }

    state = durable_running_states(config)["appdata_usb"]

    assert state["running"] is True
    assert state["source"] == "resource_lock"
    assert state["log_file"] == str(log_file)
    assert state["log_available"] is True
    assert is_resource_active(config, "repo:/mnt/disks/usb/appdata") is True


def test_dead_resource_lock_is_not_reported_as_running(tmp_path: Path):
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    (lock_dir / "repo.lock.json").write_text(json.dumps({
        "resource": "repo:/mnt/backup/appdata",
        "job_key": "appdata_local",
        "pid": 99999999,
        "started_at": "2026-07-10T09:00:00+00:00",
    }), encoding="utf-8")
    config = {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "BORG_RESOURCE_LOCK_DIR": str(lock_dir),
    }

    assert durable_running_states(config) == {}
    assert is_resource_active(config, "repo:/mnt/backup/appdata") is False


def test_job_discovery_cache_reuses_metadata_and_detects_atomic_update(tmp_path: Path, monkeypatch):
    jobs_dir = tmp_path / "config" / "jobs"
    jobs_dir.mkdir(parents=True)
    metadata = jobs_dir / "flash_local.json"
    payload = {
        "job_key": "flash_local",
        "name": "Flash",
        "backup_type": "flash",
        "location": "local",
    }
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    jobs_api.invalidate_job_discovery_cache()
    original = jobs_api._discover_jobs_uncached
    calls = []

    def counted(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(jobs_api, "_discover_jobs_uncached", counted)
    clock = iter((0.0, 0.0, jobs_api._JOB_DISCOVERY_CACHE_TTL_SECONDS + 1.0))
    monkeypatch.setattr(jobs_api.time, "monotonic", lambda: next(clock))

    assert jobs_api.discover_jobs(tmp_path)[0].name == "Flash"
    assert jobs_api.discover_jobs(tmp_path)[0].name == "Flash"
    assert calls == [True]

    payload["name"] = "Updated Flash"
    replacement = jobs_dir / ".flash_local.json.new"
    replacement.write_text(json.dumps(payload), encoding="utf-8")
    replacement.replace(metadata)

    assert jobs_api.discover_jobs(tmp_path)[0].name == "Updated Flash"
    assert calls == [True, True]


def test_runner_resource_lock_records_live_log_path(tmp_path: Path):
    log_file = tmp_path / "backup.log"
    lock_set = ResourceLockSet(
        tmp_path / "locks",
        "appdata_usb",
        heartbeat_seconds=3600,
        log_file=str(log_file),
    )

    ok, reason = lock_set.acquire(["repo:/mnt/disks/usb/appdata"])

    assert ok is True
    assert reason == ""
    payload = json.loads(lock_set._owned[0].read_text(encoding="utf-8"))
    assert payload["log_file"] == str(log_file)
    lock_set.release()


def test_recovered_job_stream_follows_persistent_log(tmp_path: Path, monkeypatch):
    log_file = tmp_path / "backup.log"
    log_file.write_text("line one\nline two\n", encoding="utf-8")
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    lock_file = lock_dir / "repo.lock.json"
    lock_file.write_text(json.dumps({
        "resource": "repo:/mnt/backup/recovered",
        "job_key": "recovered_usb",
        "pid": os.getpid(),
        "started_at": "2026-07-10T09:00:00+00:00",
        "log_file": str(log_file),
    }), encoding="utf-8")
    config = {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "BORG_RESOURCE_LOCK_DIR": str(lock_dir),
    }
    monkeypatch.setattr(jobs_api.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(jobs_api, "_latest_job_exit_code", lambda *_args: 0)

    stream = stream_job_output(config, "recovered_usb")
    assert next(stream) == ": heartbeat\n\n"
    assert next(stream) == "data: line one\n\n"
    assert next(stream) == "data: line two\n\n"
    lock_file.unlink()
    assert next(stream) == "event: done\ndata: 0\n\n"
