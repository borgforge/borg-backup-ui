from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
for import_root in (ROOT, API_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import borg_backup_ui  # noqa: E402
from startup_state import get_startup_state  # noqa: E402


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
    assert get_startup_state(config)["mode"] == "maintenance"
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
    assert get_startup_state(config)["mode"] == "normal"


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
        ("GET", "/api/settings"),
        ("POST", "/api/settings/support-bundle"),
    ):
        handler, errors = _handler(config, method)
        assert handler._authorize_api_request(path, "req-allowed") is True
        assert errors == []


def test_ui_contains_global_localized_maintenance_notice():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "ui" / "js" / "core" / "app-core.js").read_text(encoding="utf-8")
    de = (ROOT / "ui" / "i18n" / "de.json").read_text(encoding="utf-8")
    en = (ROOT / "ui" / "i18n" / "en.json").read_text(encoding="utf-8")

    assert 'id="startup-maintenance-banner"' in html
    assert "renderStartupMaintenanceBanner" in js
    assert '"maintenanceMode"' in de
    assert '"maintenanceMode"' in en
