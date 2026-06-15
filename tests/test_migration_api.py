from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import pytest

from migration_api import analyze_backup_conf_state, apply_legacy_cleanup, build_legacy_cleanup_plan, get_migration_registry_status


def _write_conf_tree(root: Path, backup_conf: str, example: str) -> dict:
    scripts = root / "scripts"
    config_dir = scripts / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "backup.conf").write_text(backup_conf, encoding="utf-8")
    (config_dir / "backup.conf.example").write_text(example, encoding="utf-8")
    return {"BACKUP_SCRIPTS_DIR": str(scripts)}


def _items_by_id(registry: dict) -> dict:
    return {item["id"]: item for item in registry["items"]}


def test_registry_reports_deprecated_cleanup_candidates(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            'MIGRATION_STORAGE_PATHS_VERSION="1"',
            'BORG_PASSPHRASE_FILE_LOCAL="/boot/config/old"',
            'GLOBAL_DOCKER_STOP_WAIT="5"',
            'STORAGEBOX_BASE="/./backup"',
            'REPO_FLASH_LOCAL="/mnt/backup/borg-backup-flash"',
            "",
        ]),
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            'MIGRATION_STORAGE_PATHS_VERSION="0"',
            "",
        ]),
    )
    config_dir = Path(cfg["BACKUP_SCRIPTS_DIR"]) / "config"
    (config_dir / "jobs").mkdir()
    (config_dir / "settings.json").write_text("{}\n", encoding="utf-8")
    registry = get_migration_registry_status(cfg)
    cleanup = _items_by_id(registry)["legacy_deprecated_keys_cleanup_v1"]

    assert cleanup["title"] == "Deprecated backup.conf Cleanup-Kandidaten"
    assert "können bereinigt werden" in cleanup["reason"]
    assert cleanup["category"] == "planned_migration"
    assert cleanup["stage"] == "planned"
    assert cleanup["auto_apply"] is False
    assert cleanup["destructive"] is True
    assert cleanup["status"] == "pending"
    assert cleanup["details"]["candidate_count"] == 4
    assert {row["key"] for row in cleanup["details"]["candidate_keys"]} == {
        "BORG_PASSPHRASE_FILE_LOCAL",
        "GLOBAL_DOCKER_STOP_WAIT",
        "REPO_FLASH_LOCAL",
        "STORAGEBOX_BASE",
    }
    assert "MIGRATION_STORAGE_PATHS_VERSION" not in {row["key"] for row in cleanup["details"]["candidate_keys"]}
    assert cleanup["details"]["unknown_legacy_count"] == 1
    assert cleanup["details"]["dry_run_plan"]["dry_run"] is True
    assert cleanup["details"]["dry_run_plan"]["mode"] == "comment_out"
    assert cleanup["details"]["dry_run_plan"]["candidate_count"] == 4
    assert registry["summary"]["pending"] == 0
    assert registry["summary"]["deprecated_key_candidates"] == 4


def test_analyze_backup_conf_state_separates_active_and_disabled_legacy_keys(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            'REPO_FLASH_LOCAL="/mnt/backup/borg-backup-flash"',
            '# LEGACY_CLEANUP_DISABLED STORAGEBOX_BASE="/./backup"',
            '# LEGACY_CLEANUP_DISABLED MIGRATION_STORAGE_PATHS_VERSION=1',
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
    assert [row["key"] for row in state["deprecated_active_keys"]] == ["REPO_FLASH_LOCAL"]
    assert state["deprecated_disabled_keys"] == ["STORAGEBOX_BASE"]
    assert state["protected_internal_keys"]["disabled"] == ["MIGRATION_STORAGE_PATHS_VERSION"]


def test_registry_reports_schema_missing_and_storage_marker(tmp_path: Path):
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

    assert items["setup_runtime_paths"]["title"] == "Runtime-Pfade aus GLOBAL_DATA_DIR"
    assert items["setup_runtime_paths"]["category"] == "setup"
    assert "unvollstaendigen Lauf" in items["setup_runtime_paths"]["reason"]
    assert items["config_backup_conf_schema"]["title"] == "backup.conf-Schema aus backup.conf.example"
    assert items["config_backup_conf_schema"]["category"] == "config"
    assert "fehlen Schema-Keys" in items["config_backup_conf_schema"]["reason"]
    assert items["setup_runtime_paths"]["status"] == "failed"
    assert items["config_backup_conf_schema"]["status"] == "pending"
    assert items["config_backup_conf_schema"]["details"]["missing_keys"] == ["BORG_MAX_RUNTIME_HOURS"]
    assert registry["summary"]["failed"] == 1
    assert registry["summary"]["pending"] >= 1


def test_registry_prefers_migration_state_v2_over_legacy_marker(tmp_path: Path):
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
    "storage_paths_v1": {
      "state": "baseline_detected",
      "checked_at": "2026-06-07T09:30:00"
    }
  }
}
""",
        encoding="utf-8",
    )

    registry = get_migration_registry_status(cfg)
    item = _items_by_id(registry)["setup_runtime_paths"]

    assert item["status"] == "applied"
    assert item["details"]["state"] == "baseline_detected"
    assert "Migrationsstatus erledigt" in item["reason"]


def test_registry_does_not_count_not_needed_cleanup_as_planned(tmp_path: Path):
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

    registry = get_migration_registry_status(cfg)
    cleanup = _items_by_id(registry)["legacy_deprecated_keys_cleanup_v1"]

    assert cleanup["status"] == "not_needed"
    assert cleanup["details"]["dry_run_plan"]["candidate_count"] == 0
    assert registry["summary"]["planned"] == 0


def test_legacy_cleanup_plan_is_dry_run(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            'REPO_FLASH_LOCAL="/mnt/backup/borg-backup-flash"',
            "",
        ]),
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            "",
        ]),
    )

    plan = build_legacy_cleanup_plan(cfg)

    assert plan["dry_run"] is True
    assert plan["mode"] == "comment_out"
    assert plan["backup_required"] is True
    assert plan["rollback"]["available"] is True
    assert plan["candidate_count"] == 1
    assert plan["planned_actions"] == [{
        "key": "REPO_FLASH_LOCAL",
        "action": "auskommentieren",
        "mode": "comment_out",
        "reason": "nicht mehr im aktuellen backup.conf.example enthalten",
        "known": False,
    }]
    conf_file = Path(cfg["BACKUP_SCRIPTS_DIR"]) / "config" / "backup.conf"
    assert 'REPO_FLASH_LOCAL="/mnt/backup/borg-backup-flash"' in conf_file.read_text(encoding="utf-8")


def test_legacy_cleanup_apply_comments_lines_and_creates_snapshot(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            'MIGRATION_STORAGE_PATHS_VERSION="1"',
            'REPO_FLASH_LOCAL="/mnt/backup/borg-backup-flash"',
            'STORAGEBOX_BASE="/./backup"',
            "",
        ]),
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            "",
        ]),
    )

    result = apply_legacy_cleanup(cfg, confirm="AUSKOMMENTIEREN")

    assert result["applied"] is True
    assert result["changed"] is True
    assert result["commented_count"] == 2
    assert result["backup"]
    conf_file = Path(cfg["BACKUP_SCRIPTS_DIR"]) / "config" / "backup.conf"
    text = conf_file.read_text(encoding="utf-8")
    assert 'MIGRATION_STORAGE_PATHS_VERSION="1"' in text
    assert '# LEGACY_CLEANUP_DISABLED MIGRATION_STORAGE_PATHS_VERSION=' not in text
    assert '# LEGACY_CLEANUP_DISABLED REPO_FLASH_LOCAL="/mnt/backup/borg-backup-flash"' in text
    assert '# LEGACY_CLEANUP_DISABLED STORAGEBOX_BASE="/./backup"' in text
    backup_file = Path(cfg["BACKUP_SCRIPTS_DIR"]) / "config" / "backups" / result["backup"]
    assert backup_file.exists()
    assert 'REPO_FLASH_LOCAL="/mnt/backup/borg-backup-flash"' in backup_file.read_text(encoding="utf-8")

    second = apply_legacy_cleanup(cfg, confirm="AUSKOMMENTIEREN")
    assert second["applied"] is False
    assert second["changed"] is False
    assert second["commented_count"] == 0


def test_legacy_cleanup_apply_requires_confirmation(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        'REPO_FLASH_LOCAL="/mnt/backup/borg-backup-flash"\n',
        "",
    )

    with pytest.raises(ValueError):
        apply_legacy_cleanup(cfg, confirm="")


def test_registry_reads_storage_marker_after_previous_cleanup(tmp_path: Path):
    cfg = _write_conf_tree(
        tmp_path,
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            '# LEGACY_CLEANUP_DISABLED MIGRATION_STORAGE_PATHS_VERSION=1',
            "",
        ]),
        "\n".join([
            'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
            "",
        ]),
    )

    registry = get_migration_registry_status(cfg)
    item = _items_by_id(registry)["setup_runtime_paths"]

    assert item["status"] == "applied"
    assert item["details"]["marker"] == "1"
