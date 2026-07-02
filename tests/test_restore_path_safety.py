from pathlib import Path
import io
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import restore_api  # noqa: E402


def _allow_root(monkeypatch, allowed: Path) -> dict:
    import config_api

    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {"RESTORE_ALLOWED_ROOTS": str(allowed)})
    monkeypatch.setattr(restore_api, "_is_safe_restore_root_text", lambda _raw: True)
    return {"BACKUP_SCRIPTS_DIR": str(allowed.parent)}


def test_validate_target_dir_returns_resolved_allowed_path(tmp_path: Path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "restore"
    target.mkdir()
    link = allowed / "restore-link"
    link.symlink_to(target)
    cfg = _allow_root(monkeypatch, allowed)

    assert restore_api._validate_target_dir(str(link), cfg) == target.resolve()


def test_restore_stage_dir_is_exclusive_and_inside_target(tmp_path: Path):
    target = tmp_path / "restore"
    target.mkdir()

    first = restore_api._make_restore_stage_dir(target)
    second = restore_api._make_restore_stage_dir(target)

    assert first.parent == target
    assert second.parent == target
    assert first != second
    assert first.is_dir()
    assert second.is_dir()


def test_restore_overwrite_blocks_symlink_destination_outside_target(tmp_path: Path, monkeypatch):
    allowed = tmp_path / "allowed"
    target = allowed / "restore"
    outside = tmp_path / "outside"
    target.mkdir(parents=True)
    outside.mkdir()
    outside_file = outside / "foo"
    outside_file.write_text("outside", encoding="utf-8")
    (target / "foo").symlink_to(outside_file)
    cfg = _allow_root(monkeypatch, allowed)

    monkeypatch.setattr(restore_api, "_get_job_repo_info", lambda _config, _job_key: {"repo": "/repo", "passphrase_file": None})
    monkeypatch.setattr(restore_api, "_borg_env", lambda _passphrase_file: {})
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

    class FakePopen:
        def __init__(self, _cmd, stdout=None, stderr=None, text=False, env=None, cwd=None, bufsize=0):
            self.stdout = io.StringIO("foo\n")
            self.returncode = 0
            Path(cwd, "foo").write_text("restored", encoding="utf-8")

        def wait(self):
            return self.returncode

    monkeypatch.setattr(restore_api.subprocess, "Popen", FakePopen)

    with pytest.raises(ValueError, match="outside"):
        restore_api.start_restore(
            cfg,
            "appdata_local",
            "archive-1",
            "foo",
            str(target),
            "overwrite",
        )

    assert outside_file.read_text(encoding="utf-8") == "outside"
    assert (target / "foo").is_symlink()
