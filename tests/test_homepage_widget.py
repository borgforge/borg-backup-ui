from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys


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


def test_settings_javascript_contains_homepage_custom_api_configuration():
    source = (ROOT / "ui" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")

    assert "type: customapi" in source
    assert "X-Borg-Widget-Token" in source
    assert "/api/widget/summary" in source
    assert "refreshInterval: 60000" in source
