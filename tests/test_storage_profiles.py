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
from repositories_api import write_repository_store
from storage_objects_api import write_storage_store


def _write_storagebox_reference(data_root: Path) -> dict:
    config = {"BACKUP_SCRIPTS_DIR": str(data_root)}
    meta_dir = data_root / "config" / "jobs"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "job1.json").write_text(
        '{"schema_version":2,"job_key":"job1","name":"Job 1",'
        '"location":"storagebox","repository_key":"repo_job1"}\n',
        encoding="utf-8",
    )
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_remote_a",
        "display_name": "Storagebox",
        "storage_type": "ssh",
        "location": "storagebox",
        "identity": "storagebox-profile:storage-1",
        "profile_key": "storage-1",
        "base_path": "./backup",
        "host": "u123.your-storagebox.de",
        "port": "23",
        "user": "u123",
        "endpoint": "u123.your-storagebox.de:23",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_job1",
        "display_name": "Job 1",
        "storage_key": "storage_remote_a",
        "relative_path": "borg-backup-job1",
        "path_raw": "ssh://u123@u123.your-storagebox.de:23/./backup/borg-backup-job1",
        "encryption": "none",
    }]})
    return config


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


def test_resolve_storage_profile_returns_requested_canonical_profile(tmp_path: Path):
    from storage_objects_api import replace_profile_storages

    profiles = [
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
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts")}
    replace_profile_storages(config, "storagebox", profiles)
    row = resolve_storage_profile(config, "storage-b")

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

    data_root = tmp_path / "data"
    cfg = _write_storagebox_reference(data_root)

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


def test_settings_save_blocks_new_incomplete_storage_profile(tmp_path: Path, monkeypatch):
    import borg_backup_ui
    import config_api

    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts")}

    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {"GLOBAL_DATA_DIR": "/mnt/user/backups"})
    monkeypatch.setattr(config_api, "write_conf", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(borg_backup_ui, "_apply_runtime_dirs_from_conf", lambda _cfg: None)

    handler = borg_backup_ui.BackupUIHandler.__new__(borg_backup_ui.BackupUIHandler)
    handler.config = cfg
    handler._read_json_body = lambda: {
        "updates": {},
        "profile_updates": {"storagebox": [{
            "key": "storage-1",
            "name": "Neues SSH Profil",
            "host": "",
            "port": "23",
            "user": "u123",
            "base_path": "/./backup",
            "target_type": "storagebox",
        }]},
    }

    with pytest.raises(ValueError, match="Storage profile 'storage-1' is incomplete"):
        handler._put_settings()
