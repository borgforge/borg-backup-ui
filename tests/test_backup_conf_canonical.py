from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
RUNTIME_LIB = ROOT / "runtime" / "lib"
for candidate in (ROOT, API_ROOT, RUNTIME_LIB):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from config_api import canonical_backup_conf_plan, read_raw_conf, write_conf  # noqa: E402
from status import load_config  # noqa: E402


def _config(root: Path) -> dict:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    schema_file = root / "plugin-backup.conf.example"
    schema_file.write_text(
        'GLOBAL_DATA_DIR="/mnt/user/borg_backup_ui"\n'
        'GLOBAL_LOG_DIR="${GLOBAL_DATA_DIR}/logs"\n'
        'GLOBAL_MAIL_SENDER=""\n',
        encoding="utf-8",
    )
    return {"BACKUP_SCRIPTS_DIR": str(root), "BACKUP_CONF_SCHEMA_FILE": str(schema_file)}


def test_canonical_backup_conf_round_trips_special_characters(tmp_path: Path) -> None:
    config = _config(tmp_path)
    special = 'Name #1: "quoted" \\ $value'

    changed = write_conf(config, {"GLOBAL_MAIL_SENDER": special})
    plan = canonical_backup_conf_plan(config)

    assert changed is True
    assert plan["changed"] is False
    assert read_raw_conf(config)["GLOBAL_MAIL_SENDER"] == special
    expanded = load_config(tmp_path / "config" / "backup.conf")
    assert expanded["GLOBAL_MAIL_SENDER"] == special
    assert expanded["GLOBAL_LOG_DIR"] == "/mnt/user/borg_backup_ui/logs"


def test_write_conf_rejects_unknown_keys_and_line_breaks(tmp_path: Path) -> None:
    config = _config(tmp_path)

    with pytest.raises(ValueError, match="Unsupported backup.conf keys"):
        write_conf(config, {"REPO_FLASH_LOCAL": "/mnt/backup/repo"})
    with pytest.raises(ValueError, match="must not contain line breaks"):
        write_conf(config, {"GLOBAL_MAIL_SENDER": "first\nsecond"})
