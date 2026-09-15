"""Exercise selection layout and actual Borg extraction, including literal names."""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import restore_api
from restore_selection import normalize_paths


@pytest.fixture
def archive(tmp_path, monkeypatch):
    if not shutil.which("borg"):
        pytest.skip("Borg binary required for extraction integration tests")
    env = {**os.environ, "BORG_CACHE_DIR": str(tmp_path / "cache"),
           "BORG_SECURITY_DIR": str(tmp_path / "security"), "BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK": "yes"}
    repo = tmp_path / "repo"
    source = tmp_path / "source"
    target = tmp_path / "target"
    target.mkdir()
    for path, data in {
        "Backup/Test1/file.txt": "one", "Backup/Test2/file.txt": "two",
        "Backup/Test3/file.txt": "three", "Backup/Test4/file.txt": "leave out",
        "Other/Test1/file.txt": "different parent", "Backup/[literal]*.txt": "literal",
        "Backup/pf:literal.txt": "prefix", "Backup/space name.txt": "space",
    }.items():
        p = source / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data)
    def borg(*args):
        return subprocess.run(["borg", *args], cwd=source, env=env, check=True, capture_output=True, text=True)
    borg("init", "--encryption=none", str(repo))
    borg("create", str(repo) + "::test", "Backup", "Other")
    monkeypatch.setattr(restore_api, "_get_job_repo_info", lambda *a: {"repo": str(repo)})
    monkeypatch.setattr(restore_api, "_repository_borg_env", lambda *a: env)
    monkeypatch.setattr(restore_api, "_validate_target_dir", lambda *a: target)
    monkeypatch.setattr(restore_api, "ensure_restore_repository_available", lambda *a: None)
    monkeypatch.setattr(restore_api, "acquire_restore_repository_lock", lambda *a: SimpleNamespace(release=lambda: None))
    import smb_mount
    monkeypatch.setattr(smb_mount, "ensure_smb_mount_for_job", lambda *a: SimpleNamespace(cleanup=lambda: None))
    def run(paths, mode="skip"):
        return restore_api.start_restore({}, "test-job", "test", paths[0], str(target), mode,
                                         source_paths=paths)
    return target, run


def test_multiple_folders_preserve_common_parent_and_skip_unselected(archive):
    target, run = archive
    result = run(["Backup/Test1", "Backup/Test2", "Backup/Test3"])
    assert [i["restored"] for i in result["items"]] == [True, True, True]
    assert (target / "Test1/file.txt").read_text() == "one"
    assert (target / "Test2/file.txt").read_text() == "two"
    assert not (target / "Test4").exists()
    assert not list(target.glob(".bbui-restore-stage-*"))


def test_different_parents_keep_identically_named_folders_separate(archive):
    target, run = archive
    run(["Backup/Test1", "Other/Test1"])
    assert (target / "Backup/Test1/file.txt").read_text() == "one"
    assert (target / "Other/Test1/file.txt").read_text() == "different parent"


def test_literal_patterns_spaces_and_overlap_are_not_reinterpreted(archive):
    target, run = archive
    result = run(["Backup/Test1/file.txt", "Backup/Test1", "Backup/[literal]*.txt", "Backup/pf:literal.txt", "Backup/space name.txt"])
    assert len(result["items"]) == 4
    assert (target / "[literal]*.txt").read_text() == "literal"
    assert (target / "pf:literal.txt").read_text() == "prefix"
    assert (target / "space name.txt").read_text() == "space"
    assert not (target / "Test2").exists()


@pytest.mark.parametrize("mode", ["skip", "overwrite", "rename"])
def test_conflicts_per_selected_folder(archive, mode):
    target, run = archive
    (target / "Test1").mkdir()
    (target / "Test1/file.txt").write_text("existing")
    (target / "Test1/unrelated").write_text("keep")
    result = run(["Backup/Test1", "Backup/Test2"], mode)
    if mode == "skip":
        assert result["items"][0]["skipped"]
        assert (target / "Test1/file.txt").read_text() == "existing"
        assert (target / "Test2/file.txt").read_text() == "two"
    elif mode == "overwrite":
        assert (target / "Test1/file.txt").read_text() == "one"
        assert (target / "Test1/unrelated").read_text() == "keep"
    else:
        assert (target / "Test1/file.txt").read_text() == "existing"
        assert (Path(result["items"][0]["destination_path"]) / "file.txt").read_text() == "one"


def test_missing_path_fails_before_any_extraction(archive):
    target, run = archive
    with pytest.raises(ValueError, match="missing"):
        run(["Backup/Test1", "Backup/missing"])
    assert not list(target.iterdir())


def test_precheck_reports_each_destination_without_writing(archive):
    target, _ = archive
    (target / "Test1").mkdir()
    data = restore_api.restore_precheck({}, "test-job", "test", "", str(target), "skip",
                                       source_paths=["Backup/Test1", "Backup/Test2"])
    assert data["ok"]
    assert data["common_parent"] == "Backup"
    assert data["source_paths"] == ["Backup/Test1", "Backup/Test2"]
    assert [i["destination_path"] for i in data["items"]] == [str(target / "Test1"), str(target / "Test2")]
    assert data["items"][0]["skipped"] and not data["items"][1]["skipped"]
    assert list(target.iterdir()) == [target / "Test1"]


def test_precheck_rejects_missing_second_selection(archive):
    target, _ = archive
    with pytest.raises(ValueError, match="missing"):
        restore_api.restore_precheck({}, "test-job", "test", "Backup/Test1", str(target), "skip",
                                     source_paths=["Backup/Test1", "Backup/missing"])
    assert not list(target.iterdir())


def test_precheck_detects_containing_mount_including_spaces(monkeypatch):
    def findmnt(command, **kwargs):
        assert command == ["findmnt", "--json", "--target", "/mnt/restore pool/output", "--output", "TARGET"]
        assert kwargs["timeout"] == 5
        return SimpleNamespace(returncode=0, stdout='{"filesystems":[{"target":"/mnt/restore pool"}]}')
    monkeypatch.setattr(restore_api.subprocess, "run", findmnt)
    assert restore_api._restore_target_mountpoint(Path("/mnt/restore pool/output")) == "/mnt/restore pool"


@pytest.mark.parametrize("output", ['{}', '[]', '{"filesystems":[]}', 'not json',
                                    '{"filesystems":[{"target":"relative"}]}'])
def test_precheck_does_not_invent_mountpoint_for_unknown_result(monkeypatch, output):
    monkeypatch.setattr(restore_api.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=output))
    assert restore_api._restore_target_mountpoint(Path("/mnt/user/restore")) == ""


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("findmnt", 5)])
def test_precheck_mount_lookup_failure_does_not_block_restore(monkeypatch, error):
    def failed(*args, **kwargs):
        raise error
    monkeypatch.setattr(restore_api.subprocess, "run", failed)
    assert restore_api._restore_target_mountpoint(Path("/mnt/user/restore")) == ""


def test_symlink_parent_is_rejected_before_writes(archive, tmp_path):
    target, run = archive
    outside = tmp_path / "outside"
    outside.mkdir()
    (target / "Backup").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        run(["Backup/Test1", "Other/Test1"], "overwrite")
    assert not list(outside.iterdir())


@pytest.mark.parametrize("paths", [[], [".."], ["Backup/../foo"], ["/"], ["a\x00b"], [None], "Backup", ["a"] * 257])
def test_invalid_selections_are_rejected(paths):
    with pytest.raises(ValueError):
        normalize_paths("", paths)


def test_simulation_never_restores_or_overwrites_files(archive):
    target, _ = archive
    (target / 'Test1').mkdir()
    existing = target / 'Test1/file.txt'
    existing.write_text('existing')
    result = restore_api.start_restore({}, 'test-job', 'test', '', str(target), 'overwrite',
                                      source_paths=['Backup/Test1', 'Backup/Test2'], dry_run=True)
    assert result['dry_run'] is True
    assert existing.read_text() == 'existing'
    assert not (target / 'Test2').exists()
    assert not list(target.glob('.bbui-restore-stage-*'))


@pytest.mark.parametrize('mode', ['skip', 'overwrite', 'rename'])
def test_single_matching_directory_restores_contents_without_double_nesting(archive, monkeypatch, mode):
    target, _ = archive
    match = target / 'Test1'
    match.mkdir()
    monkeypatch.setattr(restore_api, '_validate_target_dir', lambda *a: match)
    result = restore_api.start_restore({}, 'test-job', 'test', '', str(match), mode,
                                      source_paths=['Backup/Test1'])
    dest = Path(result['destination_path'])
    assert (dest / 'file.txt').read_text() == 'one'
    assert not (dest / 'Test1').exists()


def test_extraction_error_leaves_destination_untouched_and_cleans_stage(archive, monkeypatch):
    target, run = archive
    import io
    class FailedExtract:
        stdout = io.StringIO('simulated extract error\n')
        def __init__(self, *args, **kwargs):
            (Path(kwargs['cwd']) / 'partial').write_text('partial')
        def wait(self): return 2
    monkeypatch.setattr(restore_api.subprocess, 'Popen', FailedExtract)
    # Supply selection metadata so the subprocess mock only intercepts extract.
    monkeypatch.setattr(restore_api, 'selected_entries', lambda *a: [{'path': 'Backup/Test1', 'type': 'd'}])
    with pytest.raises(RuntimeError, match='simulated extract error'):
        run(['Backup/Test1'])
    assert not list(target.iterdir())
