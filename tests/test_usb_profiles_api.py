from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import usb_profiles_api


def test_usb_profile_normalization_derives_unique_keys():
    rows = usb_profiles_api.normalize_usb_profile_rows([
        {"name": "USB Backup", "mount_path": "/mnt/disks/backup"},
        {"name": "USB Backup", "mount_path": "/mnt/disks/backup2"},
        {"name": "", "mount_path": "/mnt/disks/incomplete"},
    ])

    assert rows == [
        {"key": "usb-backup", "name": "USB Backup", "mount_path": "/mnt/disks/backup"},
        {"key": "usb-backup-2", "name": "USB Backup", "mount_path": "/mnt/disks/backup2"},
    ]


def test_usb_profile_status_reports_missing_path():
    result = usb_profiles_api.test_usb_profiles_status([
        {"key": "usb-a", "name": "USB A", "mount_path": "/path/that/does/not/exist"},
    ])

    assert result["results"][0]["ok"] is False
    assert result["results"][0]["exists"] is False
    assert result["results"][0]["message"] == "Path not found"


def test_usb_profile_status_reports_directory_state(tmp_path: Path):
    result = usb_profiles_api.test_usb_profiles_status([
        {"key": "usb-a", "name": "USB A", "mount_path": str(tmp_path)},
    ])

    assert result["results"][0]["exists"] is True
    assert result["results"][0]["is_dir"] is True
    assert result["results"][0]["message"] in {"OK", "Pfad ist nicht gemountet"}
