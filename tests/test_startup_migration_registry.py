from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from migrations import registry  # noqa: E402


def _write_notification_config(config_dir: Path) -> Path:
    config_dir.mkdir(parents=True)
    (config_dir / "backup.conf").write_text(
        'NTFY_EVENTS="backup_success,backup_failed,backup_skipped"\n',
        encoding="utf-8",
    )
    schema_file = config_dir.parent / "plugin-backup.conf.example"
    schema_file.write_text(
        '\n'.join(
            (
                'NTFY_EVENTS="backup_success,backup_failed,backup_skipped"',
                'NOTIFY_EMAIL_EVENTS="backup_failed"',
                'NOTIFY_UNRAID_EVENTS="backup_success,backup_warning,backup_failed,backup_skipped"',
                'NOTIFY_REMINDER_INTERVAL_HOURS="24"',
                'NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS="6"',
                '',
            )
        ),
        encoding="utf-8",
    )
    return schema_file


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
    schema_file = _write_notification_config(config_dir)
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "BACKUP_CONF_SCHEMA_FILE": str(schema_file)}

    result = registry.run_startup_migrations(config)
    state = _state(config)
    logs = _log_lines(config)

    assert result["status"] == "ok"
    assert "notification_events_v1" in result["applied"]
    assert state["schema_version"] == 3
    assert state["last_run"]["reason_code"] == "startup_migrations_applied"
    assert state["migrations"]["notification_events_v1"]["state"] == "applied"
    assert state["migrations"]["notification_events_v1"]["applied_at"]
    assert state["migrations"]["notification_events_v1"]["last_checked_at"]
    assert state["migrations"]["notification_events_v1"]["details"]["runner"] == "central_migration_registry"
    assert "ntfy_apprise_cutover_v1" in result["applied"]
    assert state["migrations"]["notification_events_v1"]["details"]["updated_keys"] == ["NTFY_EVENTS"]
    assert len(logs) == 1
    assert logs[0]["event"] == "startup_migration"
    assert "notification_events_v1" in logs[0]["details"]["startup_migrations"]["applied"]


def test_registry_second_run_preserves_last_effective_migration(tmp_path: Path):
    config_dir = tmp_path / "config"
    schema_file = _write_notification_config(config_dir)
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "BACKUP_CONF_SCHEMA_FILE": str(schema_file)}

    first_result = registry.run_startup_migrations(config)
    first_state = _state(config)
    second_result = registry.run_startup_migrations(config)
    second_state = _state(config)
    logs = _log_lines(config)

    assert first_result["results"]["notification_events_v1"]["status"] == "applied"
    assert second_result["results"]["notification_events_v1"]["status"] in {"skipped", "not_required"}
    assert second_state["last_run"] == first_state["last_run"]
    assert second_state["migrations"]["notification_events_v1"]["state"] == "applied"
    assert (
        second_state["migrations"]["notification_events_v1"]["applied_at"]
        == first_state["migrations"]["notification_events_v1"]["applied_at"]
    )
    assert (
        second_state["migrations"]["notification_events_v1"]["checked_at"]
        == first_state["migrations"]["notification_events_v1"]["checked_at"]
    )
    assert second_state["migrations"]["notification_events_v1"]["last_checked_at"]
    assert len(logs) == 1


def test_registry_recovers_legacy_applied_at_from_success_audit(monkeypatch, tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    class ExistingMigration:
        MIGRATION_ID = "existing_v1"
        INTRODUCED_IN = "2026.07.01.0000"

        @staticmethod
        def detect(_config: dict) -> dict:
            return {"required": False}

        @staticmethod
        def apply(_config: dict) -> dict:
            raise AssertionError("apply must not run for a completed migration")

    monkeypatch.setattr(registry, "MIGRATIONS", [ExistingMigration])
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "migration-state.json").write_text(
        json.dumps({
            "schema_version": 2,
            "migrations": {
                "existing_v1": {
                    "state": "applied",
                    "checked_at": "2026-07-20T07:23:14",
                    "source": "startup_registry",
                    "details": {
                        "migration_id": "existing_v1",
                        "runner": "central_migration_registry",
                    },
                },
            },
        }) + "\n",
        encoding="utf-8",
    )
    (config_dir / "migrations.log.jsonl").write_text(
        json.dumps({
            "schema_version": 2,
            "timestamp": "2026-07-11T18:03:24Z",
            "event": "migration_completed",
            "migration_id": "existing_v1",
        }) + "\n",
        encoding="utf-8",
    )

    registry.run_startup_migrations(config)
    entry = _state(config)["migrations"]["existing_v1"]

    assert entry["state"] == "applied"
    assert entry["applied_at"] == "2026-07-11T18:03:24Z"
    assert entry["checked_at"] == "2026-07-20T07:23:14"
    assert entry["last_checked_at"]


def test_registry_does_not_invent_legacy_applied_at_without_audit(monkeypatch, tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    class ExistingMigration:
        MIGRATION_ID = "existing_v1"
        INTRODUCED_IN = "2026.07.01.0000"

        @staticmethod
        def detect(_config: dict) -> dict:
            return {"required": False}

        @staticmethod
        def apply(_config: dict) -> dict:
            raise AssertionError("apply must not run for a completed migration")

    monkeypatch.setattr(registry, "MIGRATIONS", [ExistingMigration])
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "migration-state.json").write_text(
        json.dumps({
            "schema_version": 2,
            "migrations": {
                "existing_v1": {
                    "state": "applied",
                    "checked_at": "2026-07-20T07:23:14",
                    "source": "startup_registry",
                    "details": {
                        "migration_id": "existing_v1",
                        "runner": "central_migration_registry",
                    },
                },
            },
        }) + "\n",
        encoding="utf-8",
    )

    registry.run_startup_migrations(config)
    entry = _state(config)["migrations"]["existing_v1"]

    assert entry["state"] == "applied"
    assert "applied_at" not in entry
    assert entry["last_checked_at"]


def test_registry_rechecks_completed_migration_when_declared(monkeypatch, tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    apply_calls = 0

    class RecheckMigration:
        MIGRATION_ID = "recheck_v1"
        INTRODUCED_IN = "2026.07.21.0000"
        RECHECK_AFTER_FINAL = True

        @staticmethod
        def detect(_config: dict) -> dict:
            return {"required": True, "missing_keys": ["NEW_KEY"]}

        @staticmethod
        def apply(_config: dict) -> dict:
            nonlocal apply_calls
            apply_calls += 1
            return {
                "migration_id": "recheck_v1",
                "introduced_in": "2026.07.21.0000",
                "status": "applied",
                "details": {"updated_keys": ["NEW_KEY"]},
            }

    monkeypatch.setattr(registry, "MIGRATIONS", [RecheckMigration])
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "migration-state.json").write_text(
        json.dumps({
            "schema_version": 3,
            "migrations": {
                "recheck_v1": {
                    "state": "applied",
                    "checked_at": "2026-07-20T07:23:14",
                    "applied_at": "2026-07-20T07:23:14",
                    "source": "startup_registry",
                    "details": {
                        "migration_id": "recheck_v1",
                        "runner": "central_migration_registry",
                    },
                },
            },
        }) + "\n",
        encoding="utf-8",
    )

    result = registry.run_startup_migrations(config)
    entry = _state(config)["migrations"]["recheck_v1"]

    assert apply_calls == 1
    assert result["applied"] == ["recheck_v1"]
    assert entry["state"] == "applied"
    assert entry["applied_at"] == "2026-07-20T07:23:14"
    assert entry["details"]["updated_keys"] == ["NEW_KEY"]


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
    assert state["migrations"]["broken_v1"]["details"]["failed_phase"] == "apply"
    assert len(logs) == 1
    assert logs[0]["success"] is False


def test_registry_records_detection_failure_without_running_apply(monkeypatch, tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    apply_called = False

    class BrokenDetection:
        MIGRATION_ID = "broken_detection_v1"
        INTRODUCED_IN = "2026.07.17.0000"

        @staticmethod
        def detect(_config: dict) -> dict:
            raise RuntimeError('token="private-value"')

        @staticmethod
        def apply(_config: dict) -> dict:
            nonlocal apply_called
            apply_called = True
            return {"status": "applied"}

    monkeypatch.setattr(registry, "MIGRATIONS", [BrokenDetection])

    result = registry.run_startup_migrations(config)
    state = _state(config)

    assert result["status"] == "failed"
    assert result["failed"] == ["broken_detection_v1"]
    assert apply_called is False
    details = state["migrations"]["broken_detection_v1"]["details"]
    assert details["failed_phase"] == "detect"
    assert details["error_type"] == "RuntimeError"
    assert "private-value" not in details["error"]


def test_registry_rejects_malformed_detection_result(monkeypatch, tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    apply_called = False

    class InvalidDetection:
        MIGRATION_ID = "invalid_detection_v1"
        INTRODUCED_IN = "2026.07.17.0000"

        @staticmethod
        def detect(_config: dict):
            return None

        @staticmethod
        def apply(_config: dict) -> dict:
            nonlocal apply_called
            apply_called = True
            return {"status": "applied"}

    monkeypatch.setattr(registry, "MIGRATIONS", [InvalidDetection])

    result = registry.run_startup_migrations(config)
    details = result["results"]["invalid_detection_v1"]["details"]

    assert result["failed"] == ["invalid_detection_v1"]
    assert apply_called is False
    assert details["failed_phase"] == "detect"
    assert details["error_type"] == "MigrationContractError"
    assert "detect() must return a mapping" in details["error"]


def test_registry_rejects_malformed_apply_result(monkeypatch, tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    class InvalidApply:
        MIGRATION_ID = "invalid_apply_v1"
        INTRODUCED_IN = "2026.07.17.0000"

        @staticmethod
        def detect(_config: dict) -> dict:
            return {"required": True}

        @staticmethod
        def apply(_config: dict):
            return None

    monkeypatch.setattr(registry, "MIGRATIONS", [InvalidApply])

    result = registry.run_startup_migrations(config)
    details = result["results"]["invalid_apply_v1"]["details"]

    assert result["failed"] == ["invalid_apply_v1"]
    assert details["failed_phase"] == "apply"
    assert details["error_type"] == "MigrationContractError"
    assert "apply() must return a mapping" in details["error"]


def test_registry_rejects_unsupported_apply_status(monkeypatch, tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    class InvalidStatus:
        MIGRATION_ID = "invalid_status_v1"
        INTRODUCED_IN = "2026.07.17.0000"

        @staticmethod
        def detect(_config: dict) -> dict:
            return {"required": True}

        @staticmethod
        def apply(_config: dict) -> dict:
            return {"status": "completed"}

    monkeypatch.setattr(registry, "MIGRATIONS", [InvalidStatus])

    result = registry.run_startup_migrations(config)
    details = result["results"]["invalid_status_v1"]["details"]

    assert result["failed"] == ["invalid_status_v1"]
    assert details["failed_phase"] == "apply"
    assert details["error_type"] == "MigrationContractError"
    assert "unsupported status completed" in details["error"]


def test_registry_rejects_mismatched_apply_migration_id(monkeypatch, tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    class MismatchedMigration:
        MIGRATION_ID = "expected_v1"
        INTRODUCED_IN = "2026.07.17.0000"

        @staticmethod
        def detect(_config: dict) -> dict:
            return {"required": True}

        @staticmethod
        def apply(_config: dict) -> dict:
            return {"migration_id": "different_v1", "status": "applied"}

    monkeypatch.setattr(registry, "MIGRATIONS", [MismatchedMigration])

    result = registry.run_startup_migrations(config)
    details = result["results"]["expected_v1"]["details"]

    assert result["failed"] == ["expected_v1"]
    assert details["failed_phase"] == "apply"
    assert details["error_type"] == "MigrationContractError"
    assert "mismatched migration_id different_v1" in details["error"]


def test_registry_blocks_later_migrations_after_first_failure(monkeypatch, tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    later_detect_called = False
    later_apply_called = False

    class FirstMigration:
        MIGRATION_ID = "first_v1"
        INTRODUCED_IN = "2026.07.17.0000"

        @staticmethod
        def detect(_config: dict) -> dict:
            return {"required": True}

        @staticmethod
        def apply(_config: dict) -> dict:
            return {
                "status": "failed",
                "details": {"error": "input is inconsistent", "failed_phase": "validate"},
            }

    class LaterMigration:
        MIGRATION_ID = "later_v1"
        INTRODUCED_IN = "2026.07.17.0001"

        @staticmethod
        def detect(_config: dict) -> dict:
            nonlocal later_detect_called
            later_detect_called = True
            return {"required": True}

        @staticmethod
        def apply(_config: dict) -> dict:
            nonlocal later_apply_called
            later_apply_called = True
            return {"status": "applied"}

    monkeypatch.setattr(registry, "MIGRATIONS", [FirstMigration, LaterMigration])

    result = registry.run_startup_migrations(config)
    state = _state(config)

    assert result["failed"] == ["first_v1"]
    assert result["blocked"] == ["later_v1"]
    assert result["results"]["later_v1"]["status"] == "blocked"
    assert result["results"]["later_v1"]["details"]["blocked_by"] == "first_v1"
    assert state["migrations"]["later_v1"]["state"] == "blocked"
    assert later_detect_called is False
    assert later_apply_called is False
