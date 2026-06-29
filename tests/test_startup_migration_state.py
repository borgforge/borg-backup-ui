from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from borg_backup_ui import _write_migration_state
from config_api import derive_data_dirs, migrate_storage_paths_from_global_data_dir


def test_write_migration_state_v2_skips_no_changes_log(tmp_path: Path):
    scripts = tmp_path / "scripts"
    config_dir = scripts / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "backup.conf").write_text('GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n', encoding="utf-8")
    (config_dir / "backup.conf.example").write_text('GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n', encoding="utf-8")
    cfg = {"BACKUP_SCRIPTS_DIR": str(scripts)}

    _write_migration_state(
        cfg,
        True,
        "jobs_layout=ok; storage_paths=ok(changed=False,moved=0,move_errors=0,settings_changed=False,forced_conf_write=False)",
        reason_code="no_changes",
        reason_text="Keine Änderungen nötig",
        details={
            "jobs_layout": {"status": "ok"},
            "storage_paths": {
                "status": "ok",
                "changed": False,
                "moved": 0,
                "move_errors": 0,
                "settings_changed": False,
                "forced_conf_write": False,
            },
        },
    )

    state = json.loads((config_dir / "migration-state.json").read_text(encoding="utf-8"))
    assert state["schema_version"] == 2
    assert state["last_run"]["reason_code"] == "no_changes"
    assert state["migrations"]["storage_paths_v1"]["state"] == "baseline_detected"
    assert state["migrations"]["restore_history_v1"]["state"] == "not_applicable"
    assert state["checks"]["jobs_layout"]["state"] == "ok"
    assert state["config"]["backup_conf_schema"]["state"] == "ok"
    assert state["config"]["backup_conf_schema"]["missing_count"] == 0
    assert state["config"]["backup_conf_schema"]["deprecated_active_count"] == 0
    assert not (config_dir / "migrations.log.jsonl").exists()


def test_write_migration_state_records_restore_history_import(tmp_path: Path):
    scripts = tmp_path / "scripts"
    config_dir = scripts / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "backup.conf").write_text('GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n', encoding="utf-8")
    cfg = {"BACKUP_SCRIPTS_DIR": str(scripts)}

    _write_migration_state(
        cfg,
        True,
        "restore_history=applied(imported=3,active_kept=0,errors=0)",
        reason_code="restore_history_migrated",
        reason_text="Restore-History aus restore-runs.json migriert",
        details={
            "jobs_layout": {"status": "ok"},
            "storage_paths": {"status": "ok", "changed": False, "moved": 0, "move_errors": 0},
            "restore_history": {
                "status": "applied",
                "imported": 3,
                "active_kept": 0,
                "errors": 0,
            },
        },
    )

    state = json.loads((config_dir / "migration-state.json").read_text(encoding="utf-8"))
    log_lines = (config_dir / "migrations.log.jsonl").read_text(encoding="utf-8").splitlines()

    assert state["last_run"]["reason_code"] == "restore_history_migrated"
    assert state["migrations"]["restore_history_v1"]["state"] == "applied"
    assert state["migrations"]["restore_history_v1"]["details"]["imported"] == 3
    assert len(log_lines) == 1


def test_storage_path_migration_does_not_write_legacy_marker_when_unchanged(tmp_path: Path):
    scripts = tmp_path / "scripts"
    config_dir = scripts / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir(parents=True)
    dirs = derive_data_dirs(str(data_dir))
    (config_dir / "backup.conf").write_text(
        "\n".join([
            f'GLOBAL_DATA_DIR="{data_dir}"',
            f'GLOBAL_LOG_DIR="{dirs["logs"]}"',
            f'STATUS_DIR="{dirs["status"]}"',
            f'RESTORE_TEST_STATUS_DIR="{dirs["restore_status"]}"',
            f'GLOBAL_BORG_CACHE_BASE="{dirs["cache"]}"',
            "",
        ]),
        encoding="utf-8",
    )
    cfg = {"BACKUP_SCRIPTS_DIR": str(scripts)}

    result = migrate_storage_paths_from_global_data_dir(cfg)

    text = (config_dir / "backup.conf").read_text(encoding="utf-8")
    assert result["changed"] is False
    assert "MIGRATION_STORAGE_PATHS_VERSION" not in text
    assert not (config_dir / "backups").exists()
