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
from job_model import new_job_defaults
from repositories_api import write_repository_store
from storage_objects_api import write_storage_store

JOB_ID = "11111111-1111-4111-8111-111111111111"


def _write_usb_reference(tmp_path: Path) -> dict:
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    jobs_dir = tmp_path / "config" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / (JOB_ID + ".json")).write_text(json.dumps({
        **new_job_defaults(),
        "job_id": JOB_ID,
        "name": "Photos USB",
        "repository_key": "repo_photos_usb",
        "source_paths": [str(tmp_path)],
        "archive_prefixes": ["photos"],
        "legacy_job_keys": ["photos-usb"],
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
        "job_ids": [JOB_ID],
        "source_job_ids": [JOB_ID],
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
        "usb-a": [f"Photos USB ({JOB_ID})"]
    }


def test_validate_usb_profile_usage_blocks_removal(tmp_path: Path):
    config = _write_usb_reference(tmp_path)
    before = {path: path.read_bytes() for path in (tmp_path / "config").rglob("*.json")}

    try:
        usb_profiles_api.validate_usb_profile_usage_before_save(config, [])
    except ValueError as exc:
        assert "usb-a" in str(exc)
        assert "still used" in str(exc)
    else:
        raise AssertionError("Expected in-use USB profile removal to be blocked")
    assert {path: path.read_bytes() for path in (tmp_path / "config").rglob("*.json")} == before
