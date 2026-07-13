from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from migrations import canonical_storage_profiles_v1  # noqa: E402
from storage_objects_api import (  # noqa: E402
    _safe_local_storage_path,
    read_storage_store,
    replace_profile_storages,
    settings_profiles_from_storages,
    write_storage_store,
)


def _config(tmp_path: Path) -> dict:
    return {"BACKUP_SCRIPTS_DIR": str(tmp_path)}


def _legacy_settings(tmp_path: Path) -> Path:
    path = tmp_path / "config" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 1,
        "usb_profiles": [{"key": "usb-a", "name": "USB A", "mount_path": "/mnt/disks/USB-A"}],
        "smb_profiles": [{
            "key": "smb-a", "name": "NAS A", "server": "nas.local", "share": "backup",
            "mount_path": "/mnt/borg-backup-ui/smb/smb-a", "username": "backup",
            "password_file": "/boot/config/borg-backup/secrets/.smb-smb-a.cred", "vers": "3.0",
        }],
        "storage_profiles": [{
            "key": "storage-a", "name": "Offsite", "host": "backup.example", "port": "23",
            "user": "u1", "base_path": "./backup", "target_type": "storagebox",
            "ssh_key_path": "/root/.ssh/id_ed25519",
        }],
    }, indent=2) + "\n", encoding="utf-8")
    return path


def test_local_profile_path_validation_supports_arbitrary_unraid_pools() -> None:
    for path in ("/mnt/user", "/mnt/cache/apps", "/mnt/disk12/backup", "/mnt/backup/repos", "/mnt/disks/USB-A", "/mnt/remotes/NAS"):
        assert _safe_local_storage_path(path, field="path") == path
    assert _safe_local_storage_path(" /mnt/backup/ ", field="path") == "/mnt/backup"
    for path in (
        "",
        "/",
        "/mnt",
        "/mnt/disks",
        "/mnt/remotes",
        "/etc",
        "/mnt//backup",
        "/mnt/backup//",
        "/mnt/./backup",
        "/mnt/../etc",
    ):
        with pytest.raises(ValueError):
            _safe_local_storage_path(path, field="path")


def test_local_profile_save_reports_empty_path_segments(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="contains empty path segments"):
        replace_profile_storages(_config(tmp_path), "local", [
            {"name": "Broken Pool", "base_path": "/mnt//backup"},
        ])
    assert read_storage_store(_config(tmp_path))["storages"] == []


def test_local_profiles_are_written_to_canonical_inventory(tmp_path: Path) -> None:
    config = _config(tmp_path)
    keys = replace_profile_storages(config, "local", [
        {"name": "Backup Pool", "base_path": "/mnt/backup"},
        {"name": "Cache Pool", "base_path": "/mnt/cache/repositories"},
    ])
    assert len(keys) == 2
    profiles = settings_profiles_from_storages(config)["local_profiles"]
    assert {row["base_path"] for row in profiles} == {"/mnt/backup", "/mnt/cache/repositories"}


def test_canonical_profile_migration_is_auditable_and_idempotent(tmp_path: Path) -> None:
    config = _config(tmp_path)
    settings_path = _legacy_settings(tmp_path)
    write_storage_store(config, {"storages": []})
    assert canonical_storage_profiles_v1.detect(config)["required"] is True

    result = canonical_storage_profiles_v1.apply(config)

    assert result["status"] == "applied"
    assert Path(result["details"]["backup_directory"]).is_dir()
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {"schema_version": 1}
    profiles = settings_profiles_from_storages(config)
    assert len(profiles["usb_profiles"]) == 1
    assert len(profiles["smb_profiles"]) == 1
    assert len(profiles["storage_profiles"]) == 1
    assert canonical_storage_profiles_v1.detect(config)["required"] is False


def test_canonical_profile_migration_rejects_malformed_settings(tmp_path: Path) -> None:
    config = _config(tmp_path)
    path = tmp_path / "config" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not readable"):
        canonical_storage_profiles_v1.detect(config)


def test_canonical_profile_migration_rolls_back_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    settings_path = _legacy_settings(tmp_path)
    write_storage_store(config, {"storages": []})
    storage_path = tmp_path / "config" / "storages.json"
    old_settings = settings_path.read_bytes()
    old_storages = storage_path.read_bytes()
    original = canonical_storage_profiles_v1.replace_profile_storages
    calls = {"count": 0}

    def fail_second(cfg, location, profiles):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("injected migration failure")
        return original(cfg, location, profiles)

    monkeypatch.setattr(canonical_storage_profiles_v1, "replace_profile_storages", fail_second)
    with pytest.raises(OSError, match="injected"):
        canonical_storage_profiles_v1.apply(config)
    assert settings_path.read_bytes() == old_settings
    assert storage_path.read_bytes() == old_storages
