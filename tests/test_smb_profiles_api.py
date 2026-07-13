from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from smb_profiles_api import (
    normalize_smb_profile_rows,
    validate_smb_profile_usage_before_save,
)
from repositories_api import write_repository_store
from storage_objects_api import write_storage_store


def test_smb_profile_normalization_derives_key_from_secret_path(tmp_path: Path):
    cred = tmp_path / ".smb-nas-a.cred"
    cred.write_text("username=backup\npassword=secret\n", encoding="utf-8")

    rows = normalize_smb_profile_rows([{
        "name": "NAS A",
        "server": "192.0.2.10",
        "share": "/backup",
        "mount_path": "/mnt/user/borg-backup-ui/remotes/nas-a",
        "username": "backup",
        "password_file": str(cred),
    }])

    assert rows == [{
        "key": "nas-a",
        "name": "NAS A",
        "server": "192.0.2.10",
        "share": "backup",
        "mount_path": "/mnt/user/borg-backup-ui/remotes/nas-a",
        "username": "backup",
        "vers": "3.0",
        "sec": "",
        "password_file": str(cred),
        "smb_password": "",
        "password_set": "true",
    }]


def test_smb_profile_usage_blocks_delete_when_job_references_profile(tmp_path: Path, monkeypatch):
    import config_api
    import jobs_api

    scripts_dir = tmp_path / "scripts"
    data_root = tmp_path / "data"
    meta_dir = data_root / "config" / "jobs"
    meta_dir.mkdir(parents=True)
    (meta_dir / "job1.json").write_text(
        json.dumps({
            "schema_version": 2,
            "job_key": "job1",
            "name": "Job 1",
            "location": "smb",
            "repository_key": "repo_job1",
        }) + "\n",
        encoding="utf-8",
    )
    profiles = [{
        "key": "nas-a",
        "name": "NAS A",
        "server": "192.0.2.10",
        "share": "backup",
        "mount_path": "/mnt/user/borg-backup-ui/remotes/nas-a",
        "username": "backup",
        "password_file": "/boot/config/borg-backup/secrets/.smb-nas-a.cred",
    }]

    config = {"BACKUP_SCRIPTS_DIR": str(data_root)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_nas_a",
        "display_name": "NAS A",
        "storage_type": "smb",
        "location": "smb",
        "identity": "smb-profile:nas-a",
        "profile_key": "nas-a",
        "base_path": "/mnt/user/borg-backup-ui/remotes/nas-a",
        "mount_path": "/mnt/user/borg-backup-ui/remotes/nas-a",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_job1",
        "display_name": "Job 1",
        "storage_key": "storage_nas_a",
        "relative_path": "borg-backup-job1",
        "path_raw": "/mnt/user/borg-backup-ui/remotes/nas-a/borg-backup-job1",
        "encryption": "none",
    }]})
    monkeypatch.setattr(config_api, "get_conf_file", lambda _cfg: scripts_dir / "config" / "backup.conf")
    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {
        "SMB_PROFILES_JSON": json.dumps(profiles),
        "GLOBAL_DATA_DIR": str(data_root),
    })

    with pytest.raises(ValueError, match="SMB profile cannot be deleted"):
        validate_smb_profile_usage_before_save(config, [])
