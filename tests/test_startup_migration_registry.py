from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from migrations import registry  # noqa: E402


def _state(config: dict) -> dict:
    state_file = Path(config["BACKUP_SCRIPTS_DIR"]) / "config" / "migration-state.json"
    return json.loads(state_file.read_text(encoding="utf-8"))


def _log_lines(config: dict) -> list[dict]:
    log_file = Path(config["BACKUP_SCRIPTS_DIR"]) / "config" / "migrations.log.jsonl"
    if not log_file.exists():
        return []
    return [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_registry_writes_central_state_and_log_for_applied_migration(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "backup.conf").write_text(
        'NTFY_EVENTS="backup_success,backup_failed,backup_skipped"\n',
        encoding="utf-8",
    )
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    result = registry.run_startup_migrations(config)
    state = _state(config)
    logs = _log_lines(config)

    assert result["status"] == "ok"
    assert "notification_events_v1" in result["applied"]
    assert state["schema_version"] == 2
    assert state["last_run"]["reason_code"] == "startup_migrations_applied"
    assert state["migrations"]["notification_events_v1"]["state"] == "applied"
    assert state["migrations"]["notification_events_v1"]["details"]["runner"] == "central_migration_registry"
    assert state["migrations"]["notification_events_v1"]["details"]["updated_keys"] == [
        "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS",
        "NOTIFY_EMAIL_EVENTS",
        "NOTIFY_REMINDER_INTERVAL_HOURS",
        "NOTIFY_UNRAID_EVENTS",
        "NTFY_EVENTS",
    ]
    assert len(logs) == 1
    assert logs[0]["event"] == "startup_migration"
    assert "notification_events_v1" in logs[0]["details"]["startup_migrations"]["applied"]


def test_registry_second_run_preserves_last_effective_migration(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "backup.conf").write_text(
        'NTFY_EVENTS="backup_success,backup_failed,backup_skipped"\n',
        encoding="utf-8",
    )
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    first_result = registry.run_startup_migrations(config)
    first_state = _state(config)
    second_result = registry.run_startup_migrations(config)
    second_state = _state(config)
    logs = _log_lines(config)

    assert first_result["results"]["notification_events_v1"]["status"] == "applied"
    assert second_result["results"]["notification_events_v1"]["status"] in {"skipped", "not_required"}
    assert second_state["last_run"] == first_state["last_run"]
    assert second_state["migrations"]["notification_events_v1"]["state"] == "applied"
    assert len(logs) == 1


def test_registry_records_failed_migration(monkeypatch, tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    class BrokenMigration:
        MIGRATION_ID = "broken_v1"
        INTRODUCED_IN = "2026.07.03.0000"

        @staticmethod
        def detect(_config: dict) -> dict:
            return {"required": True, "migration_id": "broken_v1"}

        @staticmethod
        def apply(_config: dict) -> dict:
            raise RuntimeError("boom")

    monkeypatch.setattr(registry, "MIGRATIONS", [BrokenMigration])

    result = registry.run_startup_migrations(config)
    state = _state(config)
    logs = _log_lines(config)

    assert result["status"] == "failed"
    assert result["failed"] == ["broken_v1"]
    assert state["last_run"]["success"] is False
    assert state["last_run"]["reason_code"] == "error"
    assert state["migrations"]["broken_v1"]["state"] == "failed"
    assert state["migrations"]["broken_v1"]["details"]["error"] == "boom"
    assert len(logs) == 1
    assert logs[0]["success"] is False
