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
from storage_objects_api import read_storage_store, replace_profile_storages, write_storage_store


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
        "ssh_mode": "shell",
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


def test_storage_profile_normalization_preserves_borg_serve_mode():
    rows = normalize_storage_profile_rows([{
        "key": "borg",
        "name": "Borg Server",
        "host": "borg.example.test",
        "port": "2222",
        "user": "borg",
        "base_path": "/repositories",
        "target_type": "generic",
        "ssh_mode": "borg-serve",
    }])

    assert rows[0]["ssh_mode"] == "borg_serve"


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


def test_smb_profile_mount_policy_persists_to_storage_object(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts")}

    replace_profile_storages(config, "smb", [{
        "key": "smb-1",
        "name": "Borg VM",
        "server": "192.0.2.10",
        "share": "backup",
        "mount_path": "/mnt/borg-backup-ui/smb/Borg-VM-smb-123456",
        "username": "backup",
        "mount_at_start": True,
        "keep_mounted": True,
    }])

    row = read_storage_store(config)["storages"][0]
    assert row["mount_at_start"] is True
    assert row["keep_mounted"] is True


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


def test_storage_profile_delete_reports_repository_blocker(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "data")}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_smb_test",
        "display_name": "Borg-VM",
        "storage_type": "smb",
        "location": "smb",
        "identity": "smb-profile:smb-1",
        "profile_key": "smb-1",
        "base_path": "/mnt/borg-backup-ui/smb/Borg-VM-smb-123456",
        "mount_path": "/mnt/borg-backup-ui/smb/Borg-VM-smb-123456",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_borg_vm",
        "display_name": "Borg VM Repository",
        "storage_key": "storage_smb_test",
        "relative_path": "borg-backup",
        "encryption": "none",
        "used_by": [],
    }]})

    with pytest.raises(ValueError, match="Storage profiles are still used by repositories") as exc_info:
        replace_profile_storages(config, "smb", [])

    assert getattr(exc_info.value, "api_code") == "storage_profile_in_use"
    assert getattr(exc_info.value, "api_status") == 409
    assert getattr(exc_info.value, "api_message_params") == {
        "profiles": "Borg-VM",
        "repositories": "Borg VM Repository",
    }


def test_settings_smb_profile_delete_cleans_storage_secret_and_mountpoint(tmp_path: Path, monkeypatch):
    import borg_backup_ui
    import config_api

    data_root = tmp_path / "data"
    mount_path = tmp_path / "Borg-VM-smb-123456"
    mount_path.mkdir()
    secret = tmp_path / ".smb-smb-1.cred"
    secret.write_text("username=tsteinbe\npassword=secret\n", encoding="utf-8")
    config = {"BACKUP_SCRIPTS_DIR": str(data_root)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_smb_test",
        "display_name": "Borg-VM",
        "storage_type": "smb",
        "location": "smb",
        "identity": "smb-profile:smb-1",
        "profile_key": "smb-1",
        "base_path": str(mount_path),
        "mount_path": str(mount_path),
        "server": "192.0.2.10",
        "share": "borg",
        "username": "tsteinbe",
        "password_file": str(secret),
        "vers": "auto",
    }]})
    write_repository_store(config, {"repositories": []})

    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {"GLOBAL_DATA_DIR": "/mnt/user/backups"})
    monkeypatch.setattr(config_api, "write_conf", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(borg_backup_ui, "_apply_runtime_dirs_from_conf", lambda _cfg: None)

    handler = borg_backup_ui.BackupUIHandler.__new__(borg_backup_ui.BackupUIHandler)
    handler.config = config
    handler._read_json_body = lambda: {
        "updates": {},
        "profile_updates": {"smb": []},
        "smb_cleanup_keys": ["smb-1"],
        "smb_secret_cleanup_keys": ["smb-1"],
    }

    result = handler._put_settings()

    assert result["saved"] is True
    assert result["smb_cleanup"]["removed"] == [{"key": "smb-1", "path": str(mount_path)}]
    assert result["smb_secret_cleanup"]["removed"] == [{"key": "smb-1", "path": str(secret)}]
    assert read_storage_store(config)["storages"] == []
    assert not secret.exists()
    assert not mount_path.exists()
