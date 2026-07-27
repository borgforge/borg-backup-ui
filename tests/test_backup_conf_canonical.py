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

from config_api import canonical_backup_conf_plan, get_setup_status, read_raw_conf, read_setup_wizard_state, update_setup_wizard_state, write_conf  # noqa: E402
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


def test_fresh_install_template_requires_explicit_data_dir(tmp_path: Path) -> None:
    schema_file = ROOT / "runtime" / "config" / "backup.conf.example"
    raw = schema_file.read_text(encoding="utf-8")
    expanded = load_config(schema_file)

    assert 'GLOBAL_DATA_DIR=""' in raw
    assert "/mnt/user/borg-backup-ui" in raw
    assert expanded["GLOBAL_DATA_DIR"] == ""
    assert expanded["GLOBAL_LOG_DIR"] == ""
    assert expanded["STATUS_DIR"] == ""
    assert expanded["RESTORE_TEST_STATUS_DIR"] == ""

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "backup.conf").write_text(raw, encoding="utf-8")
    config = {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "BACKUP_CONF_SCHEMA_FILE": str(schema_file),
    }

    setup = get_setup_status(config)

    assert setup["global_data_dir_set"] is False
    assert setup["ready"] is False
    assert setup["validation"]["errors"][0]["message_code"] == "config_data_dir_missing"
    assert setup["setup"]["required"] is True
    assert setup["setup"]["missing_optional"] == ["storage", "repository", "job"]
    assert setup["setup"]["show_optional_wizard"] is False


def test_setup_status_tracks_optional_first_run_milestones_and_dismissal(tmp_path: Path) -> None:
    config = _config(tmp_path)
    data_dir = tmp_path / "runtime-data"

    write_conf(config, {"GLOBAL_DATA_DIR": str(data_dir)})
    setup = get_setup_status(config)

    assert setup["global_data_dir_set"] is True
    assert setup["ready"] is True
    assert setup["setup"]["required"] is False
    assert setup["setup"]["optional_incomplete"] is True
    assert setup["setup"]["missing_optional"] == ["storage", "repository", "job"]
    assert setup["setup"]["show_optional_wizard"] is True

    state = update_setup_wizard_state(config, "dismiss_optional")
    assert state["optional_dismissed_at"]
    assert read_setup_wizard_state(config)["optional_dismissed_at"] == state["optional_dismissed_at"]

    setup_after_dismiss = get_setup_status(config)
    assert setup_after_dismiss["setup"]["optional_dismissed"] is True
    assert setup_after_dismiss["setup"]["show_optional_wizard"] is False
