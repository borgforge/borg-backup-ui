"""Unavailable repository reports for stale USB mounts and path errors (#612)."""
import errno
import json
import os
import subprocess
from pathlib import Path

import pytest

from test_restore_test_scheduling import _tester
from wizard_runner import ResourceLockSet


def fail_repository_stat(monkeypatch, path, error_number):
    """Inject a filesystem failure only for the repository, leaving reports writable."""
    original = Path.stat

    def stat(self, *args, **kwargs):
        if str(self) == path:
            raise OSError(error_number, "sensitive exception text must not be copied", path)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)


@pytest.mark.parametrize("error_number", [errno.EIO, errno.ESTALE, errno.ENODEV, errno.EACCES])
@pytest.mark.parametrize("guarded", [False, True])
def test_access_error_records_unavailable_and_releases_lock(tmp_path, monkeypatch, error_number, guarded):
    tester, repo = _tester(tmp_path, monkeypatch)
    repo.update(location="usb", passphrase_file="must-not-read", encryption="repokey")
    fail_repository_stat(monkeypatch, repo["path"], error_number)
    monkeypatch.setattr(tester, "_borg", lambda *_a, **_k: pytest.fail("Must not start Borg"))
    monkeypatch.setattr(tester, "_read_passphrase", lambda *_a: pytest.fail("Must not read secrets"))
    latest = tester.status_dir / f"{repo['job_key']}.test"
    if guarded:
        import restore_test_resources
        tester.conf["RESTORE_TEST_MEMORY_LIMIT_MIB"] = "2048"

        def worker(_command, env, *_args, **_kwargs):
            monkeypatch.setenv("BORG_UI_RESTORE_RESULT", env["BORG_UI_RESTORE_RESULT"])
            tester.args.resource_worker = True
            try:
                result = tester._test_repo_locked(repo)
            finally:
                tester.args.resource_worker = False
            assert not latest.exists(), "Supervisor must publish the pending result"
            return result

        monkeypatch.setattr(restore_test_resources, "run_guarded", worker)
    lock = ResourceLockSet(tmp_path / "locks", "backup-after-test")
    try:
        assert tester.test_repo(repo) == 3
        report = json.loads(latest.read_text())
        assert report["test_result"] == "unavailable"
        assert report["test_exit_code"] == 3
        assert report["failure_code"] == "RT_REPO_UNAVAILABLE"
        assert report["steps"][0]["step_id"] == "repo_reachable"
        assert report["steps"][0]["status"] == "failed"
        assert all(step["status"] == "not_tested" for step in report["steps"][1:])
        assert len(report["steps"]) == len(tester.STEP_IDS)
        assert report["tested_files"] == 0 and report["test_coverage"] == "unknown"
        assert f"errno {error_number}" in report["error_analysis"]["error_details"]
        assert os.strerror(error_number) in report["failure_hint"]
        assert "mount" in report["failure_hint"]
        assert "sensitive exception text" not in latest.read_text()
        assert "sensitive exception text" not in tester.log_path.read_text()
        assert "Traceback" not in tester.log_path.read_text()
        assert len(list((tester.status_dir / "runs" / repo["job_key"]).glob("*.test"))) == 1
        assert not list(tester.status_dir.glob(".pending-*.json"))
        assert lock.acquire([f"repo:{repo['path']}"])[0]
    finally:
        lock.release()
        tester.close()


@pytest.mark.parametrize("exists", [False, True])
def test_missing_path_or_regular_file_stays_unavailable(tmp_path, monkeypatch, exists):
    tester, repo = _tester(tmp_path, monkeypatch)
    repo.update(passphrase_file="", encryption="none", archive_prefix="flash-backup")
    if exists:
        Path(repo["path"]).write_text("not a directory")
    monkeypatch.setattr(tester, "_borg", lambda *_a, **_k: pytest.fail("Must not start Borg"))
    try:
        assert tester.test_repo(repo) == 3
        report = json.loads((tester.status_dir / f"{repo['job_key']}.test").read_text())
        assert report["failure_code"] == "RT_REPO_UNAVAILABLE"
    finally:
        tester.close()


@pytest.mark.parametrize("remote", [False, True])
def test_reachable_directory_and_ssh_proceed_to_borg(tmp_path, monkeypatch, remote):
    tester, repo = _tester(tmp_path, monkeypatch)
    repo.update(passphrase_file="", encryption="none", archive_prefix="flash-backup")
    if remote:
        repo["path"] = "ssh://backup@example.invalid/repository"
        fail_repository_stat(monkeypatch, str(Path(repo["path"])), errno.EIO)
    else:
        Path(repo["path"]).mkdir()
    calls = []
    monkeypatch.setattr(tester, "_env", lambda *_a, **_k: {})

    def borg(command, _env):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '{"archives": []}', "")

    monkeypatch.setattr(tester, "_borg", borg)
    try:
        assert tester.test_repo(repo) == 1  # Reachable but deliberately empty repository.
        assert calls == [["list", "--json", "--sort-by", "timestamp", "--last", "1",
                          "--glob-archives=flash-backup-*", repo["path"]]]
        report = json.loads((tester.status_dir / f"{repo['job_key']}.test").read_text())
        assert report["failure_code"] == "RT_ARCHIVE_MISSING"
    finally:
        tester.close()


def test_smb_cleanup_still_runs_after_path_error(tmp_path, monkeypatch):
    tester, repo = _tester(tmp_path, monkeypatch)
    repo.update(location="smb", passphrase_file="", encryption="none")
    fail_repository_stat(monkeypatch, repo["path"], errno.EIO)
    monkeypatch.setattr(tester, "_ensure_smb_mount", lambda _repo: (True, ""))
    cleaned = []
    monkeypatch.setattr(tester, "_cleanup_smb_mount", lambda _repo, mounted: cleaned.append(mounted))
    try:
        assert tester.test_repo(repo) == 3
        assert cleaned == [True]
    finally:
        tester.close()
