from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from wizard_runner import ResourceLockSet  # noqa: E402


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
