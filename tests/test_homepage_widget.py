from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT, ROOT / "api", ROOT / "runtime" / "lib"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import jobs_api
from api.auth_store import (
    homepage_widget_token_status,
    read_homepage_widget_token,
    revoke_homepage_widget_token,
    rotate_homepage_widget_token,
)
import api.homepage_widget_api as homepage_widget_api
import api.unraid_dashboard_widget as unraid_dashboard_widget
from borg_backup_ui import BackupUIHandler


def _handler(config: dict, headers: dict | None = None) -> BackupUIHandler:
    handler = BackupUIHandler.__new__(BackupUIHandler)
    handler.config = config
    handler.headers = headers or {}
    handler.command = "GET"
    return handler


def test_homepage_widget_token_lifecycle_uses_restricted_permissions(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    assert homepage_widget_token_status(config) == {"configured": False}
    first = rotate_homepage_widget_token(config)
    token_file = tmp_path / "config" / ".homepage-widget-token"

    assert len(first) == 64
    assert read_homepage_widget_token(config) == first
    assert homepage_widget_token_status(config) == {"configured": True}
    assert os.stat(token_file).st_mode & 0o777 == 0o600

    second = rotate_homepage_widget_token(config)
    assert second != first
    assert read_homepage_widget_token(config) == second
    assert revoke_homepage_widget_token(config) is True
    assert revoke_homepage_widget_token(config) is False
    assert homepage_widget_token_status(config) == {"configured": False}


def test_homepage_widget_token_is_scoped_to_widget_endpoint(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    token = rotate_homepage_widget_token(config)
    handler = _handler(config, {"X-Borg-Widget-Token": token})
    handler._auth_store_failure = lambda: ""
    handler._ui_auth_enabled = lambda: False
    handler._is_ui_session_valid = lambda: False
    handler._get_api_token = lambda: "general-api-token"
    handler._get_current_role = lambda: "viewer"
    errors = []
    handler._send_api_error = lambda status, code, message, *, request_id: errors.append(
        (status, code, message, request_id)
    )

    assert handler._authorize_api_request("/api/widget/summary", "req-widget") is True
    assert handler._authorize_api_request("/api/status", "req-status") is False
    assert errors[-1][0:2] == (401, "unauthorized")


def test_general_api_token_cannot_replace_widget_token(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    rotate_homepage_widget_token(config)
    handler = _handler(config, {"X-API-Token": "general-api-token"})
    handler._auth_store_failure = lambda: ""
    handler._ui_auth_enabled = lambda: False
    handler._is_ui_session_valid = lambda: False
    errors = []
    handler._send_api_error = lambda status, code, message, *, request_id: errors.append(
        (status, code, message, request_id)
    )

    assert handler._authorize_api_request("/api/widget/summary", "req-widget") is False
    assert errors[-1][0:2] == (401, "widget_unauthorized")


def test_homepage_widget_summary_is_stable_and_redacted(monkeypatch):
    jobs = [
        {"key": "flash_local", "name": "Flash", "display_name": "Flash - Local", "enabled": True},
        {"key": "appdata_usb", "name": "Appdata", "display_name": "Appdata - USB", "enabled": True},
        {"key": "photos_local", "name": "Photos", "display_name": "Photos - Local", "enabled": False},
    ]
    latest = [
        {"key": "flash_local", "status": "success", "timestamp": "2026-07-14 09:00:00"},
        {"key": "appdata_usb", "status": "warning", "timestamp": "2026-07-14 10:00:00"},
    ]
    monkeypatch.setattr(homepage_widget_api, "_read_jobs", lambda _config: jobs)
    monkeypatch.setattr(homepage_widget_api, "_read_latest_backup_rows", lambda _config: latest)
    monkeypatch.setattr(homepage_widget_api, "_backup_overdue_count", lambda *_args: 1)
    monkeypatch.setattr(
        homepage_widget_api,
        "_restore_summary",
        lambda *_args: {"configured": 2, "verified": 1, "failed": 0, "overdue": 1, "never": 0},
    )
    monkeypatch.setattr(
        jobs_api,
        "get_all_runtime_states",
        lambda _config: {"flash_local": {"running": True, "log_file": "/secret/job.log"}},
    )

    result = homepage_widget_api.build_homepage_widget_summary(
        {}, now=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    )

    assert result == {
        "schema_version": 1,
        "generated_at": "2026-07-14T12:00:00Z",
        "status": {"state": "attention", "label": "Attention required", "severity": 2},
        "display": {
            "backups": "1/2 successful",
            "restore_tests": "1/2 verified",
            "attention": "3",
            "active": "Flash - Local",
        },
        "backups": {
            "total": 3,
            "enabled": 2,
            "disabled": 1,
            "successful": 1,
            "warning": 1,
            "failed": 0,
            "skipped": 0,
            "never": 0,
            "overdue": 1,
        },
        "restore_tests": {"configured": 2, "verified": 1, "failed": 0, "overdue": 1, "never": 0},
        "active": {"count": 1, "jobs": ["Flash - Local"]},
    }

    serialized = json.dumps(result).lower()
    for forbidden in (
        "/mnt/",
        "ssh://",
        "passphrase",
        "secret",
        "log_file",
        "error_message",
        "repository_path",
        "username",
    ):
        assert forbidden not in serialized


def test_homepage_widget_module_does_not_start_external_processes():
    source = (ROOT / "api" / "homepage_widget_api.py").read_text(encoding="utf-8")

    assert "subprocess" not in source
    assert "Popen" not in source
    assert "borg info" not in source.lower()


def test_unraid_dashboard_widget_cache_is_flash_safe_and_redacted(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    config = {"UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file)}
    status = {
        "summary": {"success": 1, "warning": 1, "skipped": 0, "error": 0},
        "backups": [
            {
                "key": "appdata_local",
                "backup_type": "appdata",
                "location": "local",
                "status": "success",
                "timestamp": "2026-08-08 09:00:00",
                "time_ago": "vor 2 Stunden",
                "duration_formatted": "3 Min.",
                "repo_path": "/mnt/user/private",
                "error_message": "secret details",
            }
        ],
    }
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_read_jobs",
        lambda _config, _backups: [
            {
                "key": "appdata_local",
                "display_name": "Appdata - Lokal",
                "enabled": True,
                "running": False,
                "restore_verification_status": "verified",
            }
        ],
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_repository_summary",
        lambda _config: {"online": 2, "total": 3},
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_next_backups",
        lambda *_args: [{"name": "Appdata - Lokal", "time": "Heute 09:00"}],
    )

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_cache(
        config,
        status,
        app_version="2026.08.09.1200",
        now=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert cache_file.exists()
    assert os.stat(cache_file).st_mode & 0o777 == 0o600
    assert result["schema_version"] == 1
    assert result["app_version"] == "2026.08.09.1200"
    assert result["jobs"]["successful"] == 1
    assert result["jobs"]["warnings"] == 1
    assert result["repositories"] == {"online": 2, "total": 3}
    assert result["latest_backup"]["name"] == "Appdata - Lokal"
    assert result["restore_proof"] == {
        "configured": 1,
        "verified": 1,
        "failed": 0,
        "overdue": 0,
        "open": 0,
    }

    serialized = cache_file.read_text(encoding="utf-8").lower()
    for forbidden in ("/mnt/", "secret", "repo_path", "error_message", "passphrase"):
        assert forbidden not in serialized


def test_unraid_dashboard_widget_startup_cache_is_written_without_backup_status(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    config = {"UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file), "BACKUP_SCRIPTS_DIR": str(tmp_path)}

    monkeypatch.setattr(jobs_api, "resolve_data_root", lambda _config: tmp_path)
    monkeypatch.setattr(jobs_api, "resolve_scripts_dir", lambda _config: scripts_dir)
    monkeypatch.setattr(
        jobs_api,
        "discover_jobs",
        lambda _scripts_dir, _data_root: [
            SimpleNamespace(
                key="flash_local",
                name="Flash",
                display_name="Flash - Lokal",
                enabled=True,
                is_utility=False,
            )
        ],
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_repository_summary",
        lambda _config, *, skip_if_array_root=False: {"online": 1, "total": 1},
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_next_backups",
        lambda *_args: [{"name": "Flash - Lokal", "time": "Heute 09:00"}],
    )

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_startup_cache(
        config,
        app_version="2026.08.09.1300",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
    )

    assert cache_file.exists()
    assert os.stat(cache_file).st_mode & 0o777 == 0o600
    assert result["cache_state"] == "initial"
    assert result["jobs"]["enabled"] == 1
    assert result["jobs"]["successful"] == 0
    assert result["latest_backup"]["status"] == "unknown"
    assert result["next_backups"] == [{"name": "Flash - Lokal", "time": "Heute 09:00"}]

    serialized = cache_file.read_text(encoding="utf-8").lower()
    for forbidden in ("/mnt/", "secret", "repo_path", "error_message", "passphrase"):
        assert forbidden not in serialized


def test_unraid_dashboard_widget_startup_cache_skips_array_backed_metadata(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    config = {"UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file), "BACKUP_SCRIPTS_DIR": "/mnt/user/borg-backup-ui"}

    monkeypatch.setattr(jobs_api, "resolve_data_root", lambda _config: Path("/mnt/user/borg-backup-ui"))
    monkeypatch.setattr(
        jobs_api,
        "discover_jobs",
        lambda *_args: (_ for _ in ()).throw(AssertionError("array metadata should not be read")),
    )

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_startup_cache(
        config,
        now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
    )

    assert result["cache_state"] == "initial"
    assert result["jobs"]["enabled"] == 0
    assert result["repositories"] == {"online": 0, "total": 0}


def test_unraid_dashboard_widget_page_and_assets_are_packaged():
    build = (ROOT / "plugin" / "build.sh").read_text(encoding="utf-8")
    page = (ROOT / "plugin" / "borg-backup-ui-dashboard.page").read_text(encoding="utf-8")

    assert 'Menu="Dashboard:0"' in page
    assert "$mytiles[$pluginname]['column1']" in page
    assert "/plugins/borg-backup-ui/app-icon.png" in page
    assert "{bbui_dash_h(" not in page
    assert "bbui-widget-strip" in page
    assert "font-size:20px" not in page
    assert '${SCRIPT_DIR}/${NAME}-dashboard.page' in build
    assert 'ui/assets/app-icon.png' in build
    assert '"${EMHTTP_DST}/app-icon.png"' in build


def test_settings_javascript_contains_homepage_custom_api_configuration():
    source = (ROOT / "ui" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")

    assert "type: customapi" in source
    assert "X-Borg-Widget-Token" in source
    assert "/api/widget/summary" in source
    assert "refreshInterval: 60000" in source


def test_settings_javascript_has_clipboard_fallback_for_plain_http():
    source = (ROOT / "ui" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")

    assert "window.isSecureContext" in source
    assert "copyHomepageWidgetFieldFallback" in source
    assert "document.execCommand('copy')" in source
