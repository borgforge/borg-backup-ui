from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import usb_profiles_api
from repositories_api import write_repository_store
from storage_objects_api import write_storage_store


def _write_usb_reference(tmp_path: Path) -> dict:
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    jobs_dir = tmp_path / "config" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "photos-usb.json").write_text(json.dumps({
        "schema_version": 2,
        "job_key": "photos-usb",
        "name": "Photos USB",
        "location": "usb",
        "repository_key": "repo_photos_usb",
    }), encoding="utf-8")
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_usb_a",
        "display_name": "USB A",
        "storage_type": "usb",
        "location": "usb",
        "identity": "usb-profile:usb-a",
        "profile_key": "usb-a",
        "base_path": "/mnt/disks/a",
        "mount_path": "/mnt/disks/a",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_photos_usb",
        "display_name": "Photos",
        "storage_key": "storage_usb_a",
        "relative_path": "borg-backup-photos",
        "path_raw": "/mnt/disks/a/borg-backup-photos",
        "encryption": "none",
    }]})
    return config


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


def test_get_usb_profile_job_refs_uses_canonical_storage_reference(tmp_path: Path):
    config = _write_usb_reference(tmp_path)

    assert usb_profiles_api.get_usb_profile_job_refs(config) == {
        "usb-a": ["photos-usb (Photos USB)"]
    }


def test_validate_usb_profile_usage_blocks_removal(tmp_path: Path):
    config = _write_usb_reference(tmp_path)

    try:
        usb_profiles_api.validate_usb_profile_usage_before_save(config, [])
    except ValueError as exc:
        assert "usb-a" in str(exc)
        assert "still used" in str(exc)
    else:
        raise AssertionError("Expected in-use USB profile removal to be blocked")
