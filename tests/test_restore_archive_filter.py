from job_fixtures import identified_job, job_id
from pathlib import Path
from types import SimpleNamespace
import json
import os
import shutil
import subprocess
import sys
import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import restore_api  # noqa: E402
import wizard_api  # noqa: E402
from archive_prefix import archive_prefix_from_job_key  # noqa: E402


class _NoopGuard:
    def cleanup(self) -> None:
        pass


def test_archive_prefix_from_job_key_preserves_multi_underscore_type_ids() -> None:
    assert archive_prefix_from_job_key("borg_backup_taeglich_local") == "borg_backup_taeglich-backup"
    assert archive_prefix_from_job_key("testdaten_local") == "testdaten-backup"
    assert archive_prefix_from_job_key("appdata_storagebox") == "appdata-backup"


def test_browse_restore_filters_archives_by_job_prefix_history(tmp_path: Path, monkeypatch) -> None:
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "BORG_RESOURCE_LOCK_DIR": str(tmp_path / "locks")}
    info = {
        "repo": "/repo",
        "passphrase_file": None,
        "repository_key": "repo-shared",
        "storage_key": "local",
        "storage": {},
        "job": {
            "job_key": job_id("testdaten_local"), "job_id": job_id("testdaten_local"), "archive_prefix": "testdaten-backup",
            "backup_type": "testdaten",
            "archive_prefixes": ["oldtestdaten-backup"],
        },
    }
    calls: list[list[str]] = []
    payloads = {
        "testdaten-backup-*": [
            {"name": "testdaten-backup-2026-08-29_22-00-00", "start": "2026-08-29T22:00:00"},
        ],
        "oldtestdaten-backup-*": [
            {"name": "oldtestdaten-backup-2026-08-28_22-00-00", "start": "2026-08-28T22:00:00"},
        ],
    }

    def fake_run(cmd, capture_output=False, text=False, env=None, timeout=None):
        calls.append(list(cmd))
        archive_filter = next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--glob-archives="))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"archives": payloads.get(archive_filter, [])}),
            stderr="",
        )

    monkeypatch.setattr("smb_mount.ensure_smb_mount_for_job", lambda _config, _job_key: _NoopGuard())
    monkeypatch.setattr(restore_api, "_get_job_repo_info", lambda _config, _job_key: info)
    monkeypatch.setattr(restore_api, "ensure_restore_repository_available", lambda _config, _info: None)
    monkeypatch.setattr(restore_api, "_repository_borg_env", lambda _config, _info: {})
    monkeypatch.setattr(restore_api.subprocess, "run", fake_run)

    result = restore_api.list_archives_with_context(cfg, "testdaten_local")

    assert [next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--glob-archives=")) for cmd in calls] == [
        "testdaten-backup-*",
        "oldtestdaten-backup-*",
    ]
    assert result["archive_filters"] == [
        {"prefix": "testdaten-backup", "filter": "testdaten-backup-*", "current": True},
        {"prefix": "oldtestdaten-backup", "filter": "oldtestdaten-backup-*", "current": False},
    ]
    assert [row["name"] for row in result["archives"]] == [
        "testdaten-backup-2026-08-29_22-00-00",
        "oldtestdaten-backup-2026-08-28_22-00-00",
    ]


def test_browse_restore_falls_back_to_unfiltered_archive_list_without_prefix(tmp_path: Path, monkeypatch) -> None:
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "BORG_RESOURCE_LOCK_DIR": str(tmp_path / "locks")}
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=False, text=False, env=None, timeout=None):
        calls.append(list(cmd))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"archives": [
                {"name": "archive-1", "start": "2026-08-29T20:00:00"},
            ]}),
            stderr="",
        )

    monkeypatch.setattr("smb_mount.ensure_smb_mount_for_job", lambda _config, _job_key: _NoopGuard())
    monkeypatch.setattr(restore_api, "_get_job_repo_info", lambda _config, _job_key: {
        "repo": "/repo",
        "passphrase_file": None,
        "repository_key": "repo-shared",
        "storage_key": "local",
        "storage": {},
        "job": {},
    })
    monkeypatch.setattr(restore_api, "ensure_restore_repository_available", lambda _config, _info: None)
    monkeypatch.setattr(restore_api, "_repository_borg_env", lambda _config, _info: {})
    monkeypatch.setattr(restore_api, "_archive_filter_rows_for_restore_job", lambda _job_key, _info: [])
    monkeypatch.setattr(restore_api.subprocess, "run", fake_run)

    assert restore_api.list_archives(cfg, "legacy_local")[0]["name"] == "archive-1"
    assert calls == [["borg", "list", "--json", "/repo"]]


def test_save_job_preserves_previous_archive_prefixes(tmp_path: Path, monkeypatch) -> None:
    scripts_dir = tmp_path / "scripts"
    jobs_dir = tmp_path / "config" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / (job_id("oldtype_local") + ".json")).write_text(json.dumps({
        "schema_version": 2,
        "job_key": job_id("oldtype_local"), "job_id": job_id("oldtype_local"), "archive_prefix": "oldtype-backup",
        "name": "Old type",
        "backup_type": "oldtype",
        "archive_prefixes": ["oldertype-backup"],
        "location": "local",
        "repository_key": "repo-shared",
    }), encoding="utf-8")
    captured: dict = {}

    def fake_transaction(config, metadata_path, metadata, repository_key, job_key, **kwargs):
        captured["metadata"] = metadata
        captured["metadata_path"] = metadata_path
        captured["repository_key"] = repository_key
        captured["job_key"] = job_key

    monkeypatch.setattr(wizard_api, "_repository_from_params", lambda _params, _config: {
        "repository_key": "repo-shared",
    })
    monkeypatch.setattr("repositories_api.save_job_repository_transaction", fake_transaction)

    wizard_api.save_job({
        "existing_job_key": job_id("oldtype_local"),
        "archive_prefix": "newtype-backup",
        "type_id": "newtype",
        "location": "local",
        "repository_key": "repo-shared",
        "source_paths": ["/mnt/user/appdata"],
    }, scripts_dir, tmp_path, {"BACKUP_SCRIPTS_DIR": str(tmp_path)})

    assert captured["job_key"] == job_id("oldtype_local")
    assert "backup_type" not in captured["metadata"]
    assert captured["metadata"]["archive_prefixes"] == [
        "newtype-backup",
        "oldtype-backup",
        "oldertype-backup",
    ]


@pytest.mark.parametrize("mode,pattern,expected", [
    ("all", "ignored-*", []),
    ("custom", "*-nextcloud-aio", ["--glob-archives=*-nextcloud-aio"]),
    ("custom", "202*", ["--glob-archives=202*"]),
    ("custom", "--unusual-*", ["--glob-archives=--unusual-*"]),
    ("custom", "name with spaces", ["--glob-archives=name with spaces"]),
])
def test_external_archive_filter_is_only_a_list_argument(monkeypatch, mode, pattern, expected):
    calls = []
    cleaned = []
    info = {"repo": "ssh://remote/repo", "job": {"archive_prefix": "job-backup"}}
    monkeypatch.setattr("smb_mount.ensure_smb_mount_for_job", lambda *_: SimpleNamespace(cleanup=lambda: cleaned.append(True)))
    monkeypatch.setattr(restore_api, "_get_job_repo_info", lambda *_: info)
    monkeypatch.setattr(restore_api, "ensure_restore_repository_available", lambda *_: None)
    monkeypatch.setattr(restore_api, "_repository_borg_env", lambda *_: {"SSH_CONTEXT": "preserved"})
    def run(cmd, **kwargs):
        calls.append(cmd)
        assert kwargs["env"] == {"SSH_CONTEXT": "preserved"}
        assert kwargs.get("shell", False) is False
        return SimpleNamespace(returncode=0, stdout='{"archives":[]}', stderr="")
    monkeypatch.setattr(restore_api.subprocess, "run", run)
    result = restore_api.list_archives_with_context({}, "test_local", filter_mode=mode, archive_filter=pattern)
    assert calls == [["borg", "list", "--json", *expected, "ssh://remote/repo"]]
    assert cleaned == [True]
    assert result["archive_filters"] == []
    assert result["filter_mode"] == mode
    assert info["job"] == {"archive_prefix": "job-backup"}


@pytest.mark.parametrize("mode,pattern", [
    ("invalid", "*"), ("custom", ""), ("custom", "   "), ("custom", "x" * 257),
    ("custom", "foo\nbar"), ("custom", "foo\x00bar"), ("custom", "foo\x7fbar"),
])
def test_bad_filter_is_rejected_before_mount_or_borg(monkeypatch, mode, pattern):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid archive filter reached storage")
    monkeypatch.setattr("smb_mount.ensure_smb_mount_for_job", forbidden)
    monkeypatch.setattr(restore_api.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="filter"):
        restore_api.list_archives_with_context({}, "test_local", filter_mode=mode, archive_filter=pattern)


def test_real_borg_external_archive_can_be_browsed_and_restored(tmp_path, monkeypatch):
    if not shutil.which("borg"):
        pytest.skip("Borg binary required for external archive integration")
    env = {**os.environ, "BORG_CACHE_DIR": str(tmp_path / "cache"),
           "BORG_SECURITY_DIR": str(tmp_path / "security"),
           "BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK": "yes"}
    repo, source, target = (tmp_path / name for name in ("repo", "source", "target"))
    source.mkdir(); target.mkdir()
    (source / "hello.txt").write_text("Restored from external archive")
    external = "20260922_160449-nextcloud-aio"
    def borg(*args):
        return subprocess.run(["borg", *args], cwd=source, env=env, check=True, capture_output=True, text=True)
    borg("init", "--encryption=none", str(repo))
    for name in ("job-backup-current", "old-backup-previous", external):
        borg("create", f"{repo}::{name}", "hello.txt")
    info = {"repo": str(repo), "job": {"archive_prefix": "job-backup", "archive_prefixes": ["old-backup"]}}
    monkeypatch.setattr("smb_mount.ensure_smb_mount_for_job", lambda *_: _NoopGuard())
    monkeypatch.setattr(restore_api, "_get_job_repo_info", lambda *_: info)
    monkeypatch.setattr(restore_api, "ensure_restore_repository_available", lambda *_: None)
    monkeypatch.setattr(restore_api, "_repository_borg_env", lambda *_: env)
    monkeypatch.setattr(restore_api, "_validate_target_dir", lambda *_: target)
    monkeypatch.setattr(restore_api, "acquire_restore_repository_lock", lambda *_: SimpleNamespace(release=lambda: None))
    def names(**kwargs):
        return {row["name"] for row in restore_api.list_archives_with_context({}, "test_local", **kwargs)["archives"]}
    assert names() == {"job-backup-current", "old-backup-previous"}
    assert names(filter_mode="all") == {"job-backup-current", "old-backup-previous", external}
    assert names(filter_mode="custom", archive_filter="*-nextcloud-aio") == {external}
    assert names(filter_mode="custom", archive_filter="202*") == {external}
    assert names(filter_mode="custom", archive_filter="202") == set()
    assert restore_api.list_files({}, "test_local", external, "")[0]["name"] == "hello.txt"
    result = restore_api.start_restore({}, "test_local", external, "hello.txt", str(target), "skip")
    assert result["items"][0]["restored"]
    assert (target / "hello.txt").read_text() == "Restored from external archive"
    assert names() == {"job-backup-current", "old-backup-previous"}
