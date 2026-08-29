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

    result = restore_api.list_archives(cfg, "testdaten_local")

    assert [cmd[cmd.index("--glob-archives") + 1] for cmd in calls] == [
        "testdaten-backup-*",
        "oldtestdaten-backup-*",
    ]
    assert [row["name"] for row in result] == [
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
    monkeypatch.setattr(restore_api, "_archive_prefixes_for_restore_job", lambda _job_key, _info: [])
    monkeypatch.setattr(restore_api.subprocess, "run", fake_run)

    assert restore_api.list_archives(cfg, "legacy_local")[0]["name"] == "archive-1"
    assert calls == [["borg", "list", "--json", "/repo"]]


def test_save_job_preserves_previous_archive_prefixes(tmp_path: Path, monkeypatch) -> None:
    scripts_dir = tmp_path / "scripts"
    jobs_dir = tmp_path / "config" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "oldtype_local.json").write_text(json.dumps({
        "schema_version": 2,
        "job_key": "oldtype_local",
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
        "existing_job_key": "oldtype_local",
        "type_id": "newtype",
        "location": "local",
        "repository_key": "repo-shared",
        "source_paths": ["/mnt/user/appdata"],
    }, scripts_dir, tmp_path, {"BACKUP_SCRIPTS_DIR": str(tmp_path)})

    assert captured["job_key"] == "newtype_local"
    assert captured["metadata"]["archive_prefixes"] == [
        "newtype-backup",
        "oldtype-backup",
        "oldertype-backup",
    ]
