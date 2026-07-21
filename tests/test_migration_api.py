from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from migration_api import analyze_backup_conf_state, get_migration_registry_status


def _write_conf_tree(root: Path, backup_conf: str, example: str) -> dict:
    scripts = root / "scripts"
    config_dir = scripts / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "backup.conf").write_text(backup_conf, encoding="utf-8")
    schema_file = root / "plugin-backup.conf.example"
    schema_file.write_text(example, encoding="utf-8")
    return {"BACKUP_SCRIPTS_DIR": str(scripts), "BACKUP_CONF_SCHEMA_FILE": str(schema_file)}


def _items_by_id(registry: dict) -> dict:
    return {item["id"]: item for item in registry["items"]}


def test_analyze_backup_conf_state_reports_canonical_differences(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/custom"',
            'REPO_FLASH_LOCAL="/mnt/backup/borg-backup-flash"',
            "",
        ]),
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            'BORG_MAX_RUNTIME_HOURS="0"',
            "",
        ]),
    )

    state = analyze_backup_conf_state(cfg)

    assert state["state"] == "pending"
    assert state["missing_keys"] == ["BORG_MAX_RUNTIME_HOURS"]
    assert state["unknown_keys"] == ["REPO_FLASH_LOCAL"]
    assert state["canonical_content_changed"] is True


def test_analyze_backup_conf_state_accepts_exact_canonical_file(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        'GLOBAL_DATA_DIR="/mnt/user/custom"\nUI_SESSION_TIMEOUT_MINUTES="30"\n',
        'GLOBAL_DATA_DIR="/mnt/user/custom"\nUI_SESSION_TIMEOUT_MINUTES="30"\n',
    )

    state = analyze_backup_conf_state(cfg)

    assert state["state"] == "ok"
    assert state["missing_keys"] == []
    assert state["unknown_keys"] == []
    assert state["canonical_content_changed"] is False


def test_registry_reports_schema_missing_without_legacy_storage_marker_status(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            'MIGRATION_STORAGE_PATHS_VERSION="0"',
            "",
        ]),
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            'MIGRATION_STORAGE_PATHS_VERSION="0"',
            'BORG_MAX_RUNTIME_HOURS="0"',
            "",
        ]),
    )
    registry = get_migration_registry_status(cfg)
    items = _items_by_id(registry)

    assert "setup_runtime_paths" not in items
    assert items["config_backup_conf_schema"]["title"] == "Canonical backup.conf configuration"
    assert items["config_backup_conf_schema"]["category"] == "config"
    assert "1 missing schema key(s): BORG_MAX_RUNTIME_HOURS" in items["config_backup_conf_schema"]["reason"]
    assert "file content differs" in items["config_backup_conf_schema"]["reason"]
    assert items["config_backup_conf_schema"]["status"] == "pending"
    assert items["config_backup_conf_schema"]["details"]["missing_keys"] == ["BORG_MAX_RUNTIME_HOURS"]
    assert registry["summary"]["failed"] == 0
    assert registry["summary"]["pending"] >= 1


def test_registry_hides_obsolete_restore_history_migration_state(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            "",
        ]),
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            "",
        ]),
    )
    state_file = Path(cfg["BACKUP_SCRIPTS_DIR"]) / "config" / "migration-state.json"
    state_file.write_text(
        """{
  "schema_version": 2,
  "migrations": {
    "restore_history_v1": {
      "state": "applied",
      "checked_at": "2026-06-29T15:54:20",
      "source": "startup_registry",
      "details": {
        "migration_id": "restore_history_v1",
        "introduced_in": "2026.06.29.1544",
        "runner": "central_migration_registry",
        "imported": 5
      }
    }
  }
}
""",
        encoding="utf-8",
    )

    registry = get_migration_registry_status(cfg)
    items = _items_by_id(registry)

    assert "restore_history_v1" not in items


def test_registry_hides_obsolete_storage_paths_migration_state(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n',
        'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n',
    )
    state_file = Path(cfg["BACKUP_SCRIPTS_DIR"]) / "config" / "migration-state.json"
    state_file.write_text(
        """{
  "schema_version": 2,
  "migrations": {
    "storage_paths_v1": {
      "state": "applied",
      "checked_at": "2026-06-29T15:54:20",
      "details": {
        "runner": "legacy_startup_state"
      }
    },
    "notification_events_v1": {
      "state": "applied",
      "checked_at": "2026-06-29T22:55:18",
      "details": {
        "runner": "central_migration_registry",
        "updated_keys": ["NTFY_EVENTS"]
      }
    }
  }
}
""",
        encoding="utf-8",
    )

    registry = get_migration_registry_status(cfg)
    items = _items_by_id(registry)

    assert "storage_paths_v1" not in items
    assert "notification_events_v1" in items


def test_registry_exposes_failed_canonical_migration_with_details(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n',
        'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n',
    )
    state_file = Path(cfg["BACKUP_SCRIPTS_DIR"]) / "config" / "migration-state.json"
    state_file.write_text(
        json.dumps({
            "schema_version": 2,
            "migrations": {
                "canonical_data_model_v1": {
                    "state": "failed",
                    "checked_at": "2026-07-12T09:00:00",
                    "details": {
                        "runner": "central_migration_registry",
                        "introduced_in": "2026.07.11.1700",
                        "failed_phase": "validation",
                        "error": "Storage path contains empty path segments",
                        "rollback_status": "completed",
                    },
                },
            },
        }, indent=2) + "\n",
        encoding="utf-8",
    )

    registry = get_migration_registry_status(cfg)
    item = _items_by_id(registry)["canonical_data_model_v1"]

    assert item["status"] == "failed"
    assert item["details"]["failed_phase"] == "validation"
    assert item["details"]["rollback_status"] == "completed"
    assert registry["summary"]["failed"] == 1


def test_registry_exposes_migration_blocked_by_previous_failure(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n',
        'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n',
    )
    state_file = Path(cfg["BACKUP_SCRIPTS_DIR"]) / "config" / "migration-state.json"
    state_file.write_text(
        json.dumps({
            "schema_version": 2,
            "migrations": {
                "later_v1": {
                    "state": "blocked",
                    "checked_at": "2026-07-17T12:00:00",
                    "details": {
                        "runner": "central_migration_registry",
                        "introduced_in": "2026.07.17.0001",
                        "blocked_by": "first_v1",
                    },
                },
            },
        }, indent=2) + "\n",
        encoding="utf-8",
    )

    registry = get_migration_registry_status(cfg)
    item = _items_by_id(registry)["later_v1"]

    assert item["status"] == "blocked"
    assert "first_v1 failed" in item["reason"]
    assert item["details"]["blocked_by"] == "first_v1"


def test_registry_reports_recorded_notification_events_migration(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            'NOTIFY_EMAIL_EVENTS="backup_failed"',
            'NOTIFY_UNRAID_EVENTS="backup_success,backup_warning,backup_failed,backup_skipped"',
            'NOTIFY_REMINDER_INTERVAL_HOURS="24"',
            "",
        ]),
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            'NOTIFY_EMAIL_EVENTS="backup_failed"',
            'NOTIFY_UNRAID_EVENTS="backup_success,backup_warning,backup_failed,backup_skipped"',
            'NOTIFY_REMINDER_INTERVAL_HOURS="24"',
            "",
        ]),
    )
    state_file = Path(cfg["BACKUP_SCRIPTS_DIR"]) / "config" / "migration-state.json"
    state_file.write_text(
        """{
  "schema_version": 2,
  "migrations": {
    "notification_events_v1": {
      "state": "applied",
      "checked_at": "2026-06-29T22:23:59",
      "source": "startup_check",
      "details": {
        "migration_id": "notification_events_v1",
        "introduced_in": "2026.06.29.2000",
        "runner": "central_migration_registry",
        "updated_keys": ["NTFY_EVENTS"]
      }
    }
  }
}
""",
        encoding="utf-8",
    )

    registry = get_migration_registry_status(cfg)
    item = _items_by_id(registry)["notification_events_v1"]

    assert item["category"] == "migration"
    assert item["status"] == "applied"
    assert item["details"]["updated_keys"] == ["NTFY_EVENTS"]
    assert item["details"]["checked_at"] == "2026-06-29T22:23:59"
    assert item["details"]["applied_at"] == ""
    assert item["details"]["last_checked_at"] == ""
    assert item["details"]["introduced_in"] == "2026.06.29.2000"


def test_registry_exposes_separate_application_and_check_times(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n',
        'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"\n',
    )
    state_file = Path(cfg["BACKUP_SCRIPTS_DIR"]) / "config" / "migration-state.json"
    state_file.write_text(
        json.dumps({
            "schema_version": 3,
            "migrations": {
                "notification_events_v1": {
                    "state": "applied",
                    "checked_at": "2026-06-29T22:23:59Z",
                    "applied_at": "2026-06-29T22:23:59Z",
                    "last_checked_at": "2026-07-20T07:23:14Z",
                    "source": "startup_registry",
                    "details": {
                        "migration_id": "notification_events_v1",
                        "introduced_in": "2026.06.29.2000",
                        "runner": "central_migration_registry",
                        "updated_keys": ["NTFY_EVENTS"],
                    },
                },
            },
        }) + "\n",
        encoding="utf-8",
    )

    item = _items_by_id(get_migration_registry_status(cfg))["notification_events_v1"]

    assert item["details"]["applied_at"] == "2026-06-29T22:23:59Z"
    assert item["details"]["last_checked_at"] == "2026-07-20T07:23:14Z"
