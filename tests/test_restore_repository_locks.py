from pathlib import Path
import io
import json
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import restore_api  # noqa: E402
from restore_identity_support import JOB_ID, OTHER_ID, RUN_ID, info
from wizard_runner import ResourceLockSet  # noqa: E402


class _NoopGuard:
    def cleanup(self) -> None:
        pass


def _config(tmp_path: Path) -> dict:
    return {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "BORG_RESOURCE_LOCK_DIR": str(tmp_path / "locks"),
    }


def _repo_info(repo: str = "/repo") -> dict:
    return info(repo)


def _patch_restore_basics(monkeypatch, tmp_path: Path, repo: str = "/repo") -> Path:
    target = tmp_path / "restore-target"
    target.mkdir()
    monkeypatch.setattr(restore_api, "_get_job_repo_info", lambda _config, _job_key: _repo_info(repo))
    monkeypatch.setattr(restore_api, "_repository_borg_env", lambda _config, _info: {})
    monkeypatch.setattr(restore_api, "_validate_target_dir", lambda _target_dir, _config: target)
    monkeypatch.setattr(
        restore_api,
        "_precheck_metadata",
        lambda _repo, _archive, _source_path, _env: {
            "ok": True,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "basename": "foo",
            "source_clean": "foo",
            "source_type": "-",
        },
    )
    return target


def test_restore_browse_blocks_when_repository_resource_is_locked(tmp_path: Path, monkeypatch):
    cfg = _config(tmp_path)
    lock = ResourceLockSet(tmp_path / "locks", JOB_ID, run_id=RUN_ID, snapshot={"job_name_snapshot": "Photos"}, heartbeat_seconds=3600)
    assert lock.acquire(["repo:/repo"])[0] is True

    monkeypatch.setattr(restore_api, "_get_job_repo_info", lambda _config, _job_key: _repo_info())
    monkeypatch.setattr("smb_mount.ensure_smb_mount_for_context", lambda _info: _NoopGuard())

    try:
        with pytest.raises(restore_api.RestoreRepositoryBusy, match="Photos"):
            restore_api.list_archives(cfg, OTHER_ID)
    finally:
        lock.release()


def test_restore_extract_holds_repository_resource_lock(tmp_path: Path, monkeypatch):
    cfg = _config(tmp_path)
    target = _patch_restore_basics(monkeypatch, tmp_path)
    monkeypatch.setattr("smb_mount.ensure_smb_mount_for_context", lambda _info: _NoopGuard())

    class FakePopen:
        def __init__(self, _cmd, stdout=None, stderr=None, text=False, env=None, cwd=None, bufsize=0):
            locks = list((tmp_path / "locks").glob("*.lock.json"))
            assert len(locks) == 1
            payload = json.loads(locks[0].read_text(encoding="utf-8"))
            assert payload["run_id"] == RUN_ID
            assert payload["operation"] == "restore"
            self.stdout = io.StringIO("foo\n")
            self.returncode = 0
            Path(cwd, "foo").write_text("restored", encoding="utf-8")

        def wait(self):
            return self.returncode

    monkeypatch.setattr(restore_api.subprocess, "Popen", FakePopen)

    result = restore_api.start_restore(
        cfg,
        JOB_ID,
        "archive-1",
        "foo",
        str(target),
        "overwrite",
        restore_id=RUN_ID,
    )

    assert result["started"] is True
    assert list((tmp_path / "locks").glob("*.lock.json")) == []


def test_restore_extract_blocks_when_repository_resource_is_locked(tmp_path: Path, monkeypatch):
    cfg = _config(tmp_path)
    target = _patch_restore_basics(monkeypatch, tmp_path)
    monkeypatch.setattr("smb_mount.ensure_smb_mount_for_context", lambda _info: _NoopGuard())
    lock = ResourceLockSet(tmp_path / "locks", OTHER_ID, run_id=RUN_ID, snapshot={"job_name_snapshot": "Photos"}, heartbeat_seconds=3600)
    assert lock.acquire(["repo:/repo"])[0] is True

    try:
        with pytest.raises(restore_api.RestoreRepositoryBusy, match="Photos"):
            restore_api.start_restore(
                cfg,
                JOB_ID,
                "archive-1",
                "foo",
                str(target),
                "overwrite",
            )
    finally:
        lock.release()
