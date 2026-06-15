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
            "job_key": "job1",
            "name": "Job 1",
            "location": "smb",
            "smb_profile_key": "nas-a",
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

    monkeypatch.setattr(jobs_api, "resolve_scripts_dir", lambda _cfg: scripts_dir)
    monkeypatch.setattr(jobs_api, "resolve_data_root", lambda _cfg: data_root)
    monkeypatch.setattr(jobs_api, "get_jobs_meta_dirs", lambda _scripts, _data: [meta_dir])
    monkeypatch.setattr(config_api, "get_conf_file", lambda _cfg: scripts_dir / "config" / "backup.conf")
    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {
        "SMB_PROFILES_JSON": json.dumps(profiles),
        "GLOBAL_DATA_DIR": str(data_root),
    })

    with pytest.raises(ValueError, match="SMB-Profil kann nicht gelöscht werden"):
        validate_smb_profile_usage_before_save({"BACKUP_SCRIPTS_DIR": str(scripts_dir)}, [])
