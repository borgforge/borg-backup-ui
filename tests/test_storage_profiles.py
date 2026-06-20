from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from storage_profiles_api import (
    build_storage_repo_uri,
    normalize_storage_profile_rows,
    resolve_storage_profile,
    storage_repo_base_path_for_uri,
    validate_storage_profiles_complete_before_save,
    validate_storage_profile_usage_before_save,
)


def test_storage_profile_normalization_keeps_incomplete_profile_with_key():
    rows = normalize_storage_profile_rows([{
        "key": "storage-1",
        "name": "Storagebox",
        "host": "",
        "port": "23",
        "user": "u123",
        "base_path": "/./backup",
        "target_type": "storagebox",
    }])

    assert rows == [{
        "key": "storage-1",
        "name": "Storagebox",
        "host": "",
        "port": "23",
        "user": "u123",
        "base_path": "/./backup",
        "target_type": "storagebox",
        "ssh_key_path": "",
    }]


def test_storage_repo_uri_builder_normalizes_relative_base_path():
    profile = {
        "host": "u123.your-storagebox.de",
        "port": "23",
        "user": "u123",
        "base_path": "./backup",
    }

    assert storage_repo_base_path_for_uri("./backup") == "/./backup"
    assert build_storage_repo_uri(profile, "flash") == "ssh://u123@u123.your-storagebox.de:23/./backup/borg-backup-flash"


def test_resolve_storage_profile_returns_requested_profile(tmp_path: Path, monkeypatch):
    import config_api

    settings = {
        "storage_profiles": [
            {
                "key": "storage-a",
                "name": "Storage A",
                "host": "a.example.test",
                "port": "23",
                "user": "u1",
                "base_path": "/./backup-a",
            },
            {
                "key": "storage-b",
                "name": "Storage B",
                "host": "b.example.test",
                "port": "22",
                "user": "u2",
                "base_path": "volume1/backup-b",
            },
        ]
    }

    monkeypatch.setattr(config_api, "ensure_settings_migrated", lambda _cfg: settings)

    row = resolve_storage_profile({"BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts")}, "storage-b")

    assert row["key"] == "storage-b"
    assert row["host"] == "b.example.test"
    assert row["base_path"] == "/volume1/backup-b"


def test_unreferenced_storage_profile_with_empty_host_is_blocked():
    next_rows = normalize_storage_profile_rows([{
        "key": "storage-1",
        "name": "Storagebox",
        "host": "",
        "port": "23",
        "user": "u123",
        "base_path": "/./backup",
    }])

    with pytest.raises(ValueError, match="Storage profile 'storage-1' is incomplete"):
        validate_storage_profiles_complete_before_save(next_rows)


def test_referenced_storage_profile_with_empty_host_is_blocked(tmp_path: Path, monkeypatch):
    import config_api
    import jobs_api

    data_root = tmp_path / "data"
    meta_dir = data_root / "config" / "jobs"
    meta_dir.mkdir(parents=True)
    (meta_dir / "job1.json").write_text(
        '{"job_key":"job1","name":"Job 1","location":"storagebox","storage_profile_key":"storage-1"}\n',
        encoding="utf-8",
    )
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts")}

    monkeypatch.setattr(jobs_api, "resolve_scripts_dir", lambda _cfg: tmp_path / "scripts")
    monkeypatch.setattr(jobs_api, "resolve_data_root", lambda _cfg: data_root)
    monkeypatch.setattr(jobs_api, "get_jobs_meta_dirs", lambda _scripts, _data: [meta_dir])

    next_rows = normalize_storage_profile_rows([{
        "key": "storage-1",
        "name": "Storagebox",
        "host": "",
        "port": "23",
        "user": "u123",
        "base_path": "/./backup",
    }])

    with pytest.raises(ValueError, match="cannot be saved incomplete"):
        config_api.validate_storage_profile_usage_before_save(cfg, next_rows)


def test_storagebox_legacy_update_blocks_incomplete_referenced_profile(tmp_path: Path, monkeypatch):
    import borg_backup_ui
    import config_api
    import jobs_api

    data_root = tmp_path / "data"
    meta_dir = data_root / "config" / "jobs"
    meta_dir.mkdir(parents=True)
    (meta_dir / "job1.json").write_text(
        '{"job_key":"job1","name":"Job 1","location":"storagebox","storage_profile_key":"storage-1"}\n',
        encoding="utf-8",
    )
    settings = {
        "storage_profiles": [{
            "key": "storage-1",
            "name": "Storagebox",
            "host": "u123.your-storagebox.de",
            "port": "23",
            "user": "u123",
            "base_path": "/./backup",
            "target_type": "storagebox",
            "ssh_key_path": "",
        }]
    }
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts")}

    monkeypatch.setattr(jobs_api, "resolve_scripts_dir", lambda _cfg: tmp_path / "scripts")
    monkeypatch.setattr(jobs_api, "resolve_data_root", lambda _cfg: data_root)
    monkeypatch.setattr(jobs_api, "get_jobs_meta_dirs", lambda _scripts, _data: [meta_dir])
    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {"GLOBAL_DATA_DIR": "/mnt/user/backups"})
    monkeypatch.setattr(config_api, "read_settings_payload", lambda _cfg: settings)
    monkeypatch.setattr(config_api, "write_settings_payload", lambda _cfg, payload: None)
    monkeypatch.setattr(config_api, "write_conf", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(borg_backup_ui, "_apply_runtime_dirs_from_conf", lambda _cfg: None)

    handler = borg_backup_ui.BackupUIHandler.__new__(borg_backup_ui.BackupUIHandler)
    handler.config = cfg
    handler._read_json_body = lambda: {"updates": {"STORAGEBOX_HOST": ""}}

    with pytest.raises(ValueError, match="Storage profile 'storage-1' is incomplete"):
        handler._put_settings()


def test_settings_save_blocks_new_incomplete_storage_profile(tmp_path: Path, monkeypatch):
    import borg_backup_ui
    import config_api
    import jobs_api

    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts")}

    monkeypatch.setattr(jobs_api, "resolve_scripts_dir", lambda _cfg: tmp_path / "scripts")
    monkeypatch.setattr(jobs_api, "resolve_data_root", lambda _cfg: tmp_path / "data")
    monkeypatch.setattr(jobs_api, "get_jobs_meta_dirs", lambda _scripts, _data: [])
    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {"GLOBAL_DATA_DIR": "/mnt/user/backups"})
    monkeypatch.setattr(config_api, "read_settings_payload", lambda _cfg: {"storage_profiles": []})
    monkeypatch.setattr(config_api, "write_settings_payload", lambda _cfg, payload: None)
    monkeypatch.setattr(config_api, "write_conf", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(borg_backup_ui, "_apply_runtime_dirs_from_conf", lambda _cfg: None)

    handler = borg_backup_ui.BackupUIHandler.__new__(borg_backup_ui.BackupUIHandler)
    handler.config = cfg
    handler._read_json_body = lambda: {
        "updates": {
            "STORAGE_PROFILES_JSON": (
                '[{"key":"storage-1","name":"Neues SSH Profil","host":"","port":"23",'
                '"user":"u123","base_path":"/./backup","target_type":"storagebox"}]'
            )
        }
    }

    with pytest.raises(ValueError, match="Storage profile 'storage-1' is incomplete"):
        handler._put_settings()
