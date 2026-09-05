from pathlib import Path
from types import SimpleNamespace
import json
import sys


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
            "job_key": "testdaten_local",
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
        archive_filter = cmd[cmd.index("--glob-archives") + 1]
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

    assert [cmd[cmd.index("--glob-archives") + 1] for cmd in calls] == [
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
    from canonical_wizard_support import canonical_fixture
    from repositories_api import write_repository_store
    from storage_objects_api import write_storage_store

    scripts_dir = tmp_path / "scripts"
    source = tmp_path / "source"
    source.mkdir()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "local", "storage_type": "local", "location": "local", "base_path": str(tmp_path / "repo-root"),
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_shared", "storage_key": "local", "relative_path": "repo", "encryption": "none",
    }]})
    canonical_fixture(config)
    original = wizard_api.save_job({
        "job_name": "Original", "archive_prefix": "oldertype-backup",
        "repository_key": "repo_shared", "source_paths": [str(source)],
    }, scripts_dir, tmp_path, config)
    for prefix in ["oldtype-backup", "newtype"]:
        result = wizard_api.save_job({
            "_wizard_mode": "edit", "job_id": original["job_id"], "archive_prefix": prefix,
        }, scripts_dir, tmp_path, config)
    assert result["job_id"] == original["job_id"]
    metadata = json.loads(Path(result["metadata_path"]).read_text())
    assert metadata["archive_prefixes"] == ["newtype", "oldtype-backup", "oldertype-backup"]
