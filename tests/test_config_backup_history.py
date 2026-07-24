import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from config_api import backup_conf_snapshot, list_conf_backups  # noqa: E402


def _config(tmp_path: Path) -> dict:
    return {"BACKUP_SCRIPTS_DIR": str(tmp_path)}


def test_config_backup_history_uses_snapshot_creation_time_not_source_mtime(tmp_path: Path):
    config = _config(tmp_path)
    conf_dir = tmp_path / "config"
    conf_dir.mkdir(parents=True)
    conf = conf_dir / "backup.conf"
    conf.write_text('GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n', encoding="utf-8")
    old_source_mtime = 1_700_000_000
    os.utime(conf, (old_source_mtime, old_source_mtime))

    backup = backup_conf_snapshot(config, reason="Manual change")
    assert backup is not None

    item = list_conf_backups(config)["backups"][0]

    assert item["name"] == backup.name
    assert item["reason"] == "Manual change"
    assert item["created_ts"] > old_source_mtime
    assert item["mtime"] > old_source_mtime
    assert item["created_at"]


def test_config_backup_history_falls_back_to_timestamp_in_backup_name(tmp_path: Path):
    config = _config(tmp_path)
    backup_dir = tmp_path / "config" / "backups"
    backup_dir.mkdir(parents=True)
    backup = backup_dir / "backup.conf.20260724-110501.bak"
    backup.write_text('GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n', encoding="utf-8")
    old_file_mtime = 1_700_000_000
    os.utime(backup, (old_file_mtime, old_file_mtime))

    item = list_conf_backups(config)["backups"][0]

    assert item["name"] == backup.name
    assert item["created_at"] == "2026-07-24T11:05:01"
    assert item["created_ts"] != old_file_mtime
