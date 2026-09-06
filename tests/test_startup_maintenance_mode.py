from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
for import_root in (ROOT, API_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import borg_backup_ui  # noqa: E402
from startup_state import get_startup_state, normal_startup_state  # noqa: E402


def _summary(*, status="ok", failed=None, results=None):
    return {
        "status": status,
        "applied": [],
        "skipped": [],
        "failed": list(failed or []),
        "messages": [],
        "results": dict(results or {}),
    }


def _handler(config: dict, method: str = "GET"):
    handler = borg_backup_ui.BackupUIHandler.__new__(borg_backup_ui.BackupUIHandler)
    handler.config = config
    handler.command = method
    handler.headers = {}
    handler._auth_store_failure = lambda: ""
    handler._has_valid_api_token_header = lambda: True
    handler._is_same_origin_request = lambda: True
    handler._is_api_authorized = lambda: True
    handler._get_current_role = lambda: "admin"
    errors = []
    handler._send_api_error = lambda status, code, message, *, request_id: errors.append(
        (status, code, message, request_id)
    )
    return handler, errors


def test_failed_required_migration_selects_maintenance_and_skips_runtime_services():
    config = {}
    failed_summary = _summary(
        status="failed",
        failed=["required_v1"],
        results={
            "required_v1": {
                "status": "failed",
                "details": {
                    "failed_phase": "apply",
                    "error_type": "RuntimeError",
                    "error": "migration failed",
                },
            }
        },
    )

    ready, returned = borg_backup_ui._evaluate_startup_migrations(
        config, migration_runner=lambda _config: failed_summary
    )
    started = []

    assert ready is False
    assert returned["failed"] == ["required_v1"]
    state = get_startup_state(config)
    assert state["mode"] == "maintenance"
    assert state["severity"] == "critical"
    assert state["blocking"] is True
    assert state["failures"] == [
        {
            "migration_id": "required_v1",
            "phase": "apply",
            "error_type": "RuntimeError",
            "error": "migration failed",
        }
    ]
    assert state["recommendation_codes"] == [
        "create_support_bundle",
        "review_migration_log",
        "correct_failure",
        "restart_plugin",
        "preserve_migration_state",
    ]
    assert borg_backup_ui._activate_runtime_services(
        config, ready, starter=lambda _config: started.append(True)
    ) is False
    assert started == []


def test_failed_result_cannot_hide_behind_incorrect_summary_status():
    config = {}
    inconsistent = _summary(
        status="ok",
        results={"hidden_failure_v1": {"status": "failed", "details": {"error": "failed"}}},
    )

    ready, returned = borg_backup_ui._evaluate_startup_migrations(
        config, migration_runner=lambda _config: inconsistent
    )

    assert ready is False
    assert returned["status"] == "failed"
    assert returned["failed"] == ["hidden_failure_v1"]
    assert get_startup_state(config)["mode"] == "maintenance"


def test_runner_exception_and_invalid_result_fail_closed():
    for runner in (
        lambda _config: (_ for _ in ()).throw(RuntimeError("registry crashed")),
        lambda _config: None,
    ):
        config = {}
        ready, _result = borg_backup_ui._evaluate_startup_migrations(config, migration_runner=runner)

        assert ready is False
        state = get_startup_state(config)
        assert state["mode"] == "maintenance"
        assert state["reason_code"] == "startup_migration_runner_failed"


def test_runner_exception_exposes_safe_diagnostic_without_secret():
    config = {}

    ready, _result = borg_backup_ui._evaluate_startup_migrations(
        config,
        migration_runner=lambda _config: (_ for _ in ()).throw(
            RuntimeError("manual failure password=very-secret")
        ),
    )

    assert ready is False
    public = borg_backup_ui._public_startup_state(config)
    assert public["severity"] == "critical"
    assert public["blocking"] is True
    assert public["failed_migrations"] == ["startup_migration_registry"]
    assert public["failures"][0]["phase"] == "runner"
    assert "manual failure" in public["failures"][0]["error"]
    assert "very-secret" not in public["failures"][0]["error"]


def test_later_successful_restart_returns_to_normal_operation():
    config = {}
    borg_backup_ui._evaluate_startup_migrations(
        config,
        migration_runner=lambda _config: _summary(status="failed", failed=["required_v1"]),
    )

    ready, _result = borg_backup_ui._evaluate_startup_migrations(
        config, migration_runner=lambda _config: _summary()
    )

    assert ready is True
    state = get_startup_state(config)
    assert state["mode"] == "normal"
    assert state["severity"] == "ok"
    assert state["blocking"] is False
    assert state["failures"] == []


def test_successful_start_removes_installer_created_schema_copy(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    schema = tmp_path / "runtime-backup.conf.example"
    schema.write_text('GLOBAL_DATA_DIR="/mnt/user/borg_backup_ui"\n', encoding="utf-8")
    (config_dir / "backup.conf").write_text(
        'GLOBAL_DATA_DIR="/mnt/user/borg_backup_ui"\n', encoding="utf-8"
    )
    legacy = config_dir / "backup.conf.example"
    legacy.write_text('STALE_KEY="stale"\n', encoding="utf-8")
    config = {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "BACKUP_CONF_SCHEMA_FILE": str(schema),
    }

    assert borg_backup_ui._remove_obsolete_persistent_backup_conf_schema(config) is True
    assert not legacy.exists()


def test_noncanonical_backup_conf_retains_installer_schema_copy(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    schema = tmp_path / "runtime-backup.conf.example"
    schema.write_text('GLOBAL_DATA_DIR="/mnt/user/borg_backup_ui"\n', encoding="utf-8")
    (config_dir / "backup.conf").write_text('STALE_KEY="stale"\n', encoding="utf-8")
    legacy = config_dir / "backup.conf.example"
    legacy.write_text('STALE_KEY="stale"\n', encoding="utf-8")
    config = {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "BACKUP_CONF_SCHEMA_FILE": str(schema),
    }

    assert borg_backup_ui._remove_obsolete_persistent_backup_conf_schema(config) is False
    assert legacy.is_file()


def test_default_normal_state_is_non_blocking():
    state = normal_startup_state()

    assert state["mode"] == "normal"
    assert state["severity"] == "ok"
    assert state["blocking"] is False
    assert state["recommendation_codes"] == []


def test_maintenance_blocks_operational_api_after_normal_authorization():
    config = {}
    borg_backup_ui._evaluate_startup_migrations(
        config,
        migration_runner=lambda _config: _summary(status="failed", failed=["required_v1"]),
    )

    for method, path in (
        ("POST", "/api/jobs/run"),
        ("POST", "/api/restore/start"),
        ("POST", "/api/restore-tests/run"),
        ("POST", "/api/storage/check/run"),
        ("POST", "/api/settings"),
        ("GET", "/api/jobs/log/stream"),
    ):
        handler, errors = _handler(config, method)
        assert handler._authorize_api_request(path, "req-blocked") is False
        assert errors[-1][0:2] == (503, "maintenance_mode")
        assert "required_v1" in errors[-1][2]


def test_maintenance_keeps_diagnostics_and_support_bundle_available():
    config = {}
    borg_backup_ui._evaluate_startup_migrations(
        config,
        migration_runner=lambda _config: _summary(status="failed", failed=["required_v1"]),
    )

    for method, path in (
        ("GET", "/api/version"),
        ("GET", "/api/system-health"),
        ("GET", "/api/setup-status"),
        ("GET", "/api/migration/identity/status"),
        ("POST", "/api/settings/support-bundle"),
    ):
        handler, errors = _handler(config, method)
        assert handler._authorize_api_request(path, "req-allowed") is True
        assert errors == []


def test_ui_contains_global_localized_maintenance_notice():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "ui" / "style.css").read_text(encoding="utf-8")
    js = (ROOT / "ui" / "js" / "core" / "app-core.js").read_text(encoding="utf-8")
    bindings = (ROOT / "ui" / "js" / "components" / "app-bindings.js").read_text(
        encoding="utf-8"
    )
    settings = (ROOT / "ui" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")
    de = (ROOT / "ui" / "i18n" / "de.json").read_text(encoding="utf-8")
    en = (ROOT / "ui" / "i18n" / "en.json").read_text(encoding="utf-8")

    assert 'id="startup-maintenance-banner"' in html
    assert '<div class="startup-maintenance-icon" aria-hidden="true">!' not in html
    assert '<circle cx="12" cy="12" r="8.5"></circle>' in html
    assert '<path d="m9 9 6 6"></path>' in html
    assert ".startup-maintenance-icon svg" in css
    assert "background: var(--danger, #dc3545);" not in css
    assert "renderStartupMaintenanceBanner" in js
    assert "maintenance-disabled" in js
    assert "applyStartupMaintenanceNavigation" in js
    assert "isStartupMaintenanceMode" in bindings
    assert "startup-migration-critical" in settings
    assert "maintenanceUnavailable" in settings
    assert '"maintenanceMode"' in de
    assert '"maintenanceMode"' in en
