from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUNTIME_ROOT = ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from runtime.lib.backup_job import BackupJob, BackupJobConfig


def _cfg(lock_file: Path) -> BackupJobConfig:
    return BackupJobConfig(
        job_name="test-job",
        backup_type="flash",
        backup_location="local",
        lock_file=lock_file,
        log_dir=lock_file.parent,
        log_file=lock_file.parent / "test.log",
        backup_paths=[],
        borg_cache_dir=lock_file.parent / "cache",
        date_tag="2026-05-30",
    )


def test_create_lock_writes_pid_and_remove_lock_cleans_file(tmp_path: Path):
    lock_file = tmp_path / "job.lock"
    job = BackupJob(_cfg(lock_file))
    job._create_lock()
    try:
        assert lock_file.exists()
        assert lock_file.read_text(encoding="utf-8").strip().isdigit()
    finally:
        job._remove_lock()
    assert not lock_file.exists()


def test_create_lock_blocks_parallel_job_with_system_exit(tmp_path: Path):
    lock_file = tmp_path / "job.lock"
    job1 = BackupJob(_cfg(lock_file))
    job2 = BackupJob(_cfg(lock_file))

    job1._create_lock()
    try:
        with pytest.raises(SystemExit) as exc:
            job2._create_lock()
        assert exc.value.code == 1
    finally:
        job1._remove_lock()

