from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from migrations import smb_protocol_auto_v1  # noqa: E402
from storage_objects_api import read_storage_store, write_storage_store  # noqa: E402


def test_smb_protocol_migration_changes_old_default_once_and_creates_backup(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [
        {
            "storage_key": "storage_smb_old",
            "display_name": "NAS",
            "storage_type": "smb",
            "location": "smb",
            "identity": "smb-profile:nas",
            "profile_key": "nas",
            "base_path": "/mnt/remotes/nas",
            "mount_path": "/mnt/remotes/nas",
            "server": "nas.example.test",
            "share": "backup",
            "username": "backup",
            "password_file": "/secret.cred",
            "vers": "3.0",
        },
        {
            "storage_key": "storage_smb_explicit",
            "display_name": "Legacy NAS",
            "storage_type": "smb",
            "location": "smb",
            "identity": "smb-profile:legacy",
            "profile_key": "legacy",
            "base_path": "/mnt/remotes/legacy",
            "mount_path": "/mnt/remotes/legacy",
            "server": "legacy.example.test",
            "share": "backup",
            "username": "backup",
            "password_file": "/legacy.cred",
            "vers": "2.1",
        },
    ]})

    assert smb_protocol_auto_v1.detect(config)["storage_keys"] == ["storage_smb_old"]
    result = smb_protocol_auto_v1.apply(config)

    assert result["status"] == "applied"
    rows = {row["storage_key"]: row for row in read_storage_store(config)["storages"]}
    assert rows["storage_smb_old"]["vers"] == "auto"
    assert rows["storage_smb_explicit"]["vers"] == "2.1"
    backup_dir = Path(result["details"]["backup_directory"])
    assert (backup_dir / "storages.json").is_file()
    assert smb_protocol_auto_v1.detect(config)["required"] is False


def test_smb_protocol_migration_is_not_required_for_new_auto_profiles(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_smb_auto",
        "display_name": "NAS",
        "storage_type": "smb",
        "location": "smb",
        "identity": "smb-profile:nas",
        "profile_key": "nas",
        "base_path": "/mnt/remotes/nas",
        "mount_path": "/mnt/remotes/nas",
        "server": "nas.example.test",
        "share": "backup",
        "username": "backup",
        "password_file": "/secret.cred",
        "vers": "auto",
    }]})

    assert smb_protocol_auto_v1.detect(config)["required"] is False
