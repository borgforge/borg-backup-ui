"""Job-scoped restore evidence for shared Borg repositories (#753)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from job_fixtures import job_id
from test_restore_test_scheduling import _tester


def _configure(tester, repo, monkeypatch):
    """Configure a manual L1 run without accessing real credentials."""
    tester.args.scheduled = False
    tester.args.force = True
    tester.test_level = 1
    repo.update(encryption="none", passphrase_file="", archive_prefix="fotos-backup",
                archive_prefixes=["oldfotos-backup"])
    Path(repo["path"]).mkdir()
    monkeypatch.setattr(tester, "_env", lambda *_a, **_k: {})


def _report(tester, repo):
    """Read the persisted per-job result of a completed test."""
    return json.loads((tester.status_dir / f"{repo['job_key']}.test").read_text())


@pytest.mark.parametrize("bad_history", [None, "old-prefix", {}, ["invalid*prefix"]])
def test_invalid_prefix_history_never_runs_borg(tmp_path, monkeypatch, bad_history):
    tester, repo = _tester(tmp_path, monkeypatch)
    _configure(tester, repo, monkeypatch)
    repo["archive_prefixes"] = bad_history
    monkeypatch.setattr(tester, "_borg", lambda *_a, **_k: pytest.fail("Invalid ownership must fail closed"))
    try:
        assert tester.test_repo(repo) == 1
        assert _report(tester, repo)["failure_code"] == "RT_ARCHIVE_SELECTION_FAILED"
    finally:
        tester.close()


@pytest.mark.parametrize("prefix", [None, "", "*"])
def test_missing_or_invalid_primary_prefix_never_falls_back(tmp_path, monkeypatch, prefix):
    tester, repo = _tester(tmp_path, monkeypatch)
    _configure(tester, repo, monkeypatch)
    repo["archive_prefix"] = prefix
    monkeypatch.setattr(tester, "_borg", lambda *_a, **_k: pytest.fail("Must not list repository without ownership"))
    try:
        assert tester.test_repo(repo) == 1
        assert _report(tester, repo)["failure_code"] == "RT_ARCHIVE_SELECTION_FAILED"
    finally:
        tester.close()


@pytest.mark.parametrize("output", ["", "null", "{}", '{"archives": {}}',
    '{"archives": [null]}', '{"archives": [{"name": "unraid_flash-backup-1", "start": "2026-11-01T00:00:00"}]}',
    '{"archives": [{"name": "fotos-backup-1", "start": "invalid"}]}',
    '{"archives": [{"name": "fotos-backup-1"}]}'])
def test_invalid_listing_cannot_produce_success(tmp_path, monkeypatch, output):
    tester, repo = _tester(tmp_path, monkeypatch)
    _configure(tester, repo, monkeypatch)
    calls = []
    def borg(command, env):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, output, "")
    monkeypatch.setattr(tester, "_borg", borg)
    try:
        assert tester.test_repo(repo) == 1
        report = _report(tester, repo)
        assert report["failure_code"] == "RT_ARCHIVE_SELECTION_FAILED"
        assert report["test_result"] == "failed"
        assert len(calls) == 1 and calls[0][:2] == ["list", "--json"]
        assert all(s["status"] == "not_tested" for s in report["steps"][1:])
    finally:
        tester.close()


def test_history_listing_failure_discards_partial_candidate(tmp_path, monkeypatch):
    tester, repo = _tester(tmp_path, monkeypatch)
    _configure(tester, repo, monkeypatch)
    calls = []
    def borg(command, env):
        calls.append(command)
        assert command[:2] == ["list", "--json"]
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 0, json.dumps({"archives": [
                {"name": "fotos-backup-1", "start": "2026-11-01T00:00:00"}]}), "")
        return subprocess.CompletedProcess(command, 2, "", "timeout")
    monkeypatch.setattr(tester, "_borg", borg)
    try:
        assert tester.test_repo(repo) == 1
        report = _report(tester, repo)
        assert report["test_result"] == "failed"
        assert report["failure_code"] == "RT_TIMEOUT"
        assert len(calls) == 2
    finally:
        tester.close()


@pytest.fixture(scope="module")
def shared_borg_repository(tmp_path_factory):
    """Create isolated real archives whose lexical and timestamp orders differ."""
    borg = shutil.which("borg")
    if not borg:
        pytest.skip("Borg binary unavailable")
    root = tmp_path_factory.mktemp("shared-restore-repository")
    env = {key: value for key, value in os.environ.items() if not key.startswith("BORG_")}
    env.update(BORG_BASE_DIR=str(root / "borg-home"), BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK="yes")
    repo = root / "repository"
    source = root / "source"
    source.mkdir()
    (source / "content.txt").write_text("restore evidence for issue 753\n")
    def run(*args):
        result = subprocess.run([borg, *args], cwd=root, env=env, text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr
    run("init", "--encryption=none", str(repo))
    for day, name in enumerate(["fotos-backup-z", "fotos-backup-a", "oldfotos-backup-history",
                                 "fotos-backup2-foreign", "unraid_flash-backup-latest"], 1):
        run("create", "--timestamp", f"2026-11-{day:02d}T00:00:00", f"{repo}::{name}", "source")
    return str(repo), env


@pytest.mark.parametrize("scheduled", [False, True])
@pytest.mark.parametrize("level", [1, 2, 3])
@pytest.mark.parametrize("prefix,history,expected", [
    ("fotos-backup", [], "fotos-backup-a"),
    ("fotos-backup", ["oldfotos-backup", "fotos-backup"], "oldfotos-backup-history"),
    ("renamed-backup", ["oldfotos-backup"], "oldfotos-backup-history"),
    ("unraid_flash-backup", [], "unraid_flash-backup-latest"),
    ("missing-backup", [], ""),
])
def test_real_shared_repository_selects_only_job_archives(
        tmp_path, monkeypatch, shared_borg_repository, scheduled, level, prefix, history, expected):
    tester, repo = _tester(tmp_path, monkeypatch)
    repository, env = shared_borg_repository
    tester.args.scheduled = scheduled
    tester.args.force = True
    tester.test_level = level
    repo.update(job_key=job_id(prefix + "_local"), path=repository, encryption="none", passphrase_file="",
                archive_prefix=prefix, archive_prefixes=history)
    repo["restore_test_policy"]["level"] = level
    monkeypatch.setattr(tester, "_env", lambda *_a, **_k: env)
    calls = []
    original = tester._borg
    def borg(command, env, **kwargs):
        calls.append(command)
        return original(command, env, **kwargs)
    monkeypatch.setattr(tester, "_borg", borg)
    try:
        assert tester.test_repo(repo) == (0 if expected else 1)
        report = _report(tester, repo)
        assert report["test_result"] == ("success" if expected else "failed")
        if expected:
            assert report["tested_archive"] == expected
            targets = [arg for cmd in calls for arg in cmd if arg.startswith(repository + "::")]
            assert targets and set(targets) == {f"{repository}::{expected}"}
            assert report["test_level"] == level
        else:
            assert report["failure_code"] == "RT_ARCHIVE_MISSING"
            assert "this job" in report["failure_hint"]
            assert all(cmd[:2] == ["list", "--json"] for cmd in calls)
        assert all("--glob-archives=" in " ".join(cmd) for cmd in calls if cmd[:2] == ["list", "--json"])
    finally:
        tester.close()
