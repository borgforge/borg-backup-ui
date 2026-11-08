from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from wizard_runner import ResourceLockSet, _build_resources  # noqa: E402


def test_resource_lock_blocks_same_resource_until_released(tmp_path: Path):
    first = ResourceLockSet(tmp_path, "appdata_local", heartbeat_seconds=3600)
    second = ResourceLockSet(tmp_path, "photos_local", heartbeat_seconds=3600)

    ok, reason = first.acquire(["repo:/mnt/user/backups/repo1"])
    assert ok is True
    assert reason == ""

    ok, reason = second.acquire(["repo:/mnt/user/backups/repo1"])
    assert ok is False
    assert "resource locked by appdata_local" in reason

    first.release()

    ok, reason = second.acquire(["repo:/mnt/user/backups/repo1"])
    assert ok is True
    assert reason == ""
    second.release()


def test_resource_lock_recovers_corrupt_stale_lock_file(tmp_path: Path):
    lock_set = ResourceLockSet(tmp_path, "appdata_local", grace_seconds=0, heartbeat_seconds=3600)
    lock_path = lock_set._lock_path("repo:/mnt/user/backups/repo1")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("{not-json", encoding="utf-8")

    ok, reason = lock_set.acquire(["repo:/mnt/user/backups/repo1"])

    assert ok is True
    assert reason == ""
    assert "appdata_local" in lock_path.read_text(encoding="utf-8")
    lock_set.release()


def test_docker_control_resource_is_based_on_runtime_control_not_only_features():
    resources = _build_resources(
        {"BORG_REPO": "/mnt/backup/testdaten"},
        {"docker_control": {"mode": "all"}, "features": {"docker": False}},
    )

    assert "repo:/mnt/backup/testdaten" in resources
    assert "docker-control" in resources


def test_activity_updates_preserve_live_locks_and_survive_heartbeat(tmp_path, monkeypatch):
    """Queue metadata is observable without changing ownership or lock exclusion."""
    import json
    import pytest
    import jobs_api
    from job_fixtures import job_id

    job_key = job_id("queued-test")
    locks = ResourceLockSet(tmp_path, job_key, operation="restore_test", heartbeat_seconds=3600)
    locks.set_activity_state("running")
    assert locks.acquire(["repo:/one", "smb-mount:one"])[0]
    config = {"BORG_RESOURCE_LOCK_DIR": str(tmp_path)}
    try:
        before = [json.loads(path.read_text()) for path in locks._owned]
        assert {row["activity_state"] for row in jobs_api.active_resource_locks(config)} == {"running"}
        for state in ("waiting", "running"):
            locks.set_activity_state(state)
            with locks._metadata_lock:
                locks._refresh_owned_metadata()
            rows = jobs_api.active_resource_locks(config)
            assert len(rows) == 2
            assert {row["activity_state"] for row in rows} == {state}
            for path, original in zip(locks._owned, before):
                updated = json.loads(path.read_text())
                assert all(updated[key] == original[key] for key in ("pid", "resource", "started_at", "job_key"))
            contender = ResourceLockSet(tmp_path, "other")
            assert not contender.acquire(["repo:/one"])[0]
        with pytest.raises(ValueError):
            locks.set_activity_state("invalid")
        # Display metadata failures must not abort a workload or release its locks.
        original_write = Path.write_text
        def fail_metadata(path, *args, **kwargs):
            if ".heartbeat-" in path.name:
                raise OSError("read-only")
            return original_write(path, *args, **kwargs)
        monkeypatch.setattr(Path, "write_text", fail_metadata)
        locks.set_activity_state("waiting")
        assert len(jobs_api.active_resource_locks(config)) == 2
    finally:
        locks.release()
    assert jobs_api.active_resource_locks(config) == []
