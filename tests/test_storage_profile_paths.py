from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from storage_objects_api import (  # noqa: E402
    _safe_local_storage_path,
    read_storage_store,
    replace_profile_storages,
    settings_profiles_from_storages,
)


def _config(tmp_path: Path) -> dict:
    return {"BACKUP_SCRIPTS_DIR": str(tmp_path)}


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
