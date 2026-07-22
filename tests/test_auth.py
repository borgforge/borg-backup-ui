from io import BytesIO
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from api.auth_store import (
    UsersStoreError,
    hash_password,
    parse_cookie_header,
    read_sessions_store,
    read_users_store,
    verify_password_hash,
    write_sessions_store,
    write_users_store,
)
from borg_backup_ui import BackupUIHandler
from api.restore_api import _validate_target_dir


def _make_handler() -> BackupUIHandler:
    h = BackupUIHandler.__new__(BackupUIHandler)
    h.headers = {}
    h.config = {}
    return h


def _render_auth_page(method_name: str) -> str:
    handler = _make_handler()
    handler.wfile = BytesIO()
    handler._bootstrap_required = lambda: method_name == "_serve_setup_admin_page"
    handler._ui_auth_enabled = lambda: True
    handler.send_response = lambda _status: None
    handler.send_header = lambda _name, _value: None
    handler.end_headers = lambda: None

    getattr(handler, method_name)()
    return handler.wfile.getvalue().decode("utf-8")


def test_verify_password_hash_accepts_valid_password():
    encoded = hash_password("secret-123")
    assert verify_password_hash("secret-123", encoded) is True


def test_verify_password_hash_rejects_invalid_password():
    encoded = hash_password("secret-123")
    assert verify_password_hash("wrong-password", encoded) is False


def test_parse_cookie_header_ignores_invalid_parts():
    assert parse_cookie_header("bbui_session=sid-1; invalid; theme=dark") == {
        "bbui_session": "sid-1",
        "theme": "dark",
    }


def test_login_page_uses_shared_language_preference_and_localized_error_codes():
    html = _render_auth_page("_serve_login_page")

    assert '/ui/js/components/i18n.js' in html
    assert 'data-i18n="auth.loginTitle"' in html
    assert 'data-i18n="auth.username"' in html
    assert "api.errors.${code}" in html
    assert "d.message" not in html
    assert "Login fehlgeschlagen" not in html


def test_setup_page_uses_shared_language_preference_and_localized_error_codes():
    html = _render_auth_page("_serve_setup_admin_page")

    assert '/ui/js/components/i18n.js' in html
    assert 'data-i18n="auth.setupTitle"' in html
    assert 'data-i18n="auth.passwordHint"' in html
    assert 'data-i18n="auth.passwordConfirm"' in html
    assert "auth.errors.passwordTooShort" in html
    assert "auth.errors.passwordMismatch" in html
    assert "api.errors.${code}" in html
    assert "d.message" not in html
    assert "Setup fehlgeschlagen" not in html


def test_auth_store_writes_users_and_sessions_atomically(tmp_path: Path):
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_users_store(cfg, {"schema_version": 1, "users": [{"username": "admin"}]})
    write_sessions_store(cfg, {"schema_version": 1, "sessions": [{"sid": "s1"}]})

    assert read_users_store(cfg)["users"][0]["username"] == "admin"
    assert read_sessions_store(cfg)["sessions"][0]["sid"] == "s1"
    assert (tmp_path / "config" / "users.json").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "config" / "sessions.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "payload",
    [
        "{invalid-json",
        "[]",
        "{}",
        '{"users": {"admin": true}}',
        '{"users": [], "security": []}',
    ],
)
def test_existing_invalid_users_store_fails_closed(tmp_path: Path, payload: str):
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    users_path = tmp_path / "config" / "users.json"
    users_path.parent.mkdir(parents=True)
    users_path.write_text(payload, encoding="utf-8")

    with pytest.raises(UsersStoreError, match="Authentication user store"):
        read_users_store(cfg)


def test_missing_users_store_still_requires_initial_admin_setup(tmp_path: Path):
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    h = _make_handler()
    h.config = cfg

    assert read_users_store(cfg)["users"] == []
    assert h._bootstrap_required() is True
    assert h._ui_auth_enabled() is False


def test_existing_empty_users_store_does_not_reopen_bootstrap(tmp_path: Path):
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    users_path = tmp_path / "config" / "users.json"
    users_path.parent.mkdir(parents=True)
    users_path.write_text('{"schema_version": 1, "users": [], "security": {}}', encoding="utf-8")
    h = _make_handler()
    h.config = cfg

    assert h._bootstrap_required() is False
    assert h._ui_auth_enabled() is True


def test_corrupt_users_store_blocks_bootstrap_sessions_and_api(tmp_path: Path):
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    users_path = tmp_path / "config" / "users.json"
    users_path.parent.mkdir(parents=True)
    users_path.write_text("{broken", encoding="utf-8")
    h = _make_handler()
    h.config = cfg
    h.command = "GET"
    errors = []
    h._send_api_error = lambda status, code, message, *, request_id: errors.append(
        (status, code, message, request_id)
    )

    assert h._bootstrap_required() is False
    assert h._ui_auth_enabled() is True
    assert h._is_ui_session_valid() is False
    assert h._authorize_api_request("/api/status", "req-corrupt") is False
    assert errors[0][0:2] == (503, "auth_store_unavailable")


def test_static_file_serving_rejects_paths_outside_ui_root(tmp_path: Path):
    ui_root = tmp_path / "ui"
    ui_root.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    h = _make_handler()
    h.wfile = BytesIO()
    errors = []
    h.send_error = lambda status, message: errors.append((status, message))

    h._serve_file(outside, allowed_root=ui_root)

    assert errors == [(404, "Not found")]
    assert h.wfile.getvalue() == b""


def test_static_file_serving_rejects_symlink_escape(tmp_path: Path):
    ui_root = tmp_path / "ui"
    ui_root.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    linked_asset = ui_root / "linked.txt"
    linked_asset.symlink_to(outside)
    h = _make_handler()
    h.wfile = BytesIO()
    errors = []
    h.send_error = lambda status, message: errors.append((status, message))

    h._serve_file(linked_asset, allowed_root=ui_root)

    assert errors == [(404, "Not found")]
    assert h.wfile.getvalue() == b""


def test_static_file_serving_allows_regular_ui_asset(tmp_path: Path):
    ui_root = tmp_path / "ui"
    ui_root.mkdir()
    asset = ui_root / "app.js"
    asset.write_text("console.log('ok');", encoding="utf-8")
    h = _make_handler()
    h.wfile = BytesIO()
    status = []
    headers = []
    h.send_response = lambda value: status.append(value)
    h.send_header = lambda name, value: headers.append((name, value))
    h.end_headers = lambda: None
    h.send_error = lambda _status, _message: pytest.fail("valid UI asset was rejected")

    h._serve_file(asset, allowed_root=ui_root)

    assert status == [200]
    assert ("Content-Type", "application/javascript") in headers
    assert h.wfile.getvalue() == b"console.log('ok');"


def test_api_success_logging_suppresses_routine_fast_gets():
    h = _make_handler()
    h.config = {}

    assert h._should_log_api_success("GET", "/api/status", 20, 100) is False
    assert h._should_log_api_success("GET", "/api/system-health", 120, 94735) is False
    assert h._should_log_api_success("GET", "/api/jobs?x=1", 120, 18000) is False


def test_api_success_logging_keeps_write_slow_large_and_nonroutine_gets():
    h = _make_handler()
    h.config = {}

    assert h._should_log_api_success("POST", "/api/jobs/run", 20, 100) is True
    assert h._should_log_api_success("GET", "/api/status", 500, 100) is True
    assert h._should_log_api_success("GET", "/api/status", 20, 262144) is True
    assert h._should_log_api_success("GET", "/api/custom", 20, 100) is True


def test_raw_http_access_logging_is_suppressed_except_errors(monkeypatch):
    calls = []
    monkeypatch.setattr("borg_backup_ui._log", calls.append)
    h = _make_handler()
    h.config = {}

    h.log_message('"GET /api/status HTTP/1.1" 200 -')
    assert calls == []

    h.log_message('"GET /missing HTTP/1.1" 404 -')
    assert calls == ['"GET /missing HTTP/1.1" 404 -']


def test_verbose_access_log_keeps_raw_http_and_api_success(monkeypatch):
    calls = []
    monkeypatch.setattr("borg_backup_ui._log", calls.append)
    h = _make_handler()
    h.config = {"LOG_VERBOSE_ACCESS": "true"}

    assert h._should_log_api_success("GET", "/api/status", 1, 10) is True
    h.log_message('"GET /api/status HTTP/1.1" 200 -')

    assert calls == ['"GET /api/status HTTP/1.1" 200 -']


def test_security_audit_can_log_fresh_login_actor_without_existing_session(monkeypatch):
    calls = []
    monkeypatch.setattr("borg_backup_ui._log", calls.append)
    h = _make_handler()
    h.headers = {}
    h.client_address = ("192.0.2.10", 12345)
    h.path = "/api/auth/login"
    h._current_request_id = "req-login"
    h._get_current_session_meta = lambda: None

    h._security_audit("auth_login", "ok", actor_user="admin", actor_role="admin")

    assert len(calls) == 1
    assert "SECURITY event=auth_login result=ok" in calls[0]
    assert "user=admin" in calls[0]
    assert "role=admin" in calls[0]
    assert "endpoint=/api/auth/login" in calls[0]
    assert "target= " in calls[0]


@pytest.mark.parametrize(
    ("path", "handler_name"),
    [
        ("/api/jobs/log/stream?job=flash_local", "_handle_sse"),
        ("/api/restore-tests/log/stream", "_handle_sse"),
        ("/api/restore/download?job=x&archive=y&path=z", "_handle_restore_download"),
        ("/api/storage/check/stream", "_handle_check_sse"),
    ],
)
def test_direct_stream_and_download_routes_use_api_authorization(path: str, handler_name: str):
    h = _make_handler()
    h.path = path
    h.command = "GET"
    calls = []
    h._handle_direct_api = lambda _fn: calls.append("authorized-wrapper")
    setattr(h, handler_name, lambda *_args: pytest.fail("route bypassed authorization wrapper"))

    h.do_GET()

    assert calls == ["authorized-wrapper"]


def test_direct_api_authorization_rejects_missing_credentials():
    h = _make_handler()
    h.command = "GET"
    h._auth_store_failure = lambda: ""
    h._is_api_authorized = lambda: False
    errors = []
    h._send_api_error = lambda status, code, message, *, request_id: errors.append(
        (status, code, message, request_id)
    )

    assert h._authorize_api_request("/api/jobs/log/stream", "req-stream") is False
    assert errors[0][0:2] == (401, "unauthorized")


def test_direct_api_authorization_accepts_viewer_session():
    h = _make_handler()
    h.command = "GET"
    h._auth_store_failure = lambda: ""
    h._is_api_authorized = lambda: True
    h._get_current_role = lambda: "viewer"

    assert h._authorize_api_request("/api/restore/download", "req-download") is True


def test_is_api_authorized_accepts_header_token_when_ui_session_not_required():
    h = _make_handler()
    h.headers = {"X-API-Token": "tok-1"}
    h._ui_auth_enabled = lambda: False
    h._is_ui_session_valid = lambda: False
    h._get_api_token = lambda: "tok-1"
    assert h._is_api_authorized() is True


def test_is_api_authorized_rejects_api_token_cookie_without_valid_ui_session():
    h = _make_handler()
    h.headers = {"Cookie": "bbui_api_token=tok-1; bbui_session=sid-1"}
    h._ui_auth_enabled = lambda: True
    h._is_ui_session_valid = lambda: False
    h._get_api_token = lambda: "tok-1"
    assert h._is_api_authorized() is False


def test_is_api_authorized_ignores_api_token_cookie_for_automation_auth():
    h = _make_handler()
    h.headers = {"Cookie": "bbui_api_token=tok-1"}
    h._ui_auth_enabled = lambda: False
    h._is_ui_session_valid = lambda: False
    h._get_api_token = lambda: "tok-1"
    assert h._is_api_authorized() is False


def test_repository_request_context_contains_safe_lifecycle_fields():
    h = _make_handler()
    h.path = "/api/repositories"
    h._last_json_body = {
        "repository_key": "repo_photos_local_12345678",
        "mode": "delete",
        "confirmation_phrase": "DELETE",
    }

    context = h._extract_request_context()
    context = h._augment_context_from_response(
        h.path,
        {
            "repository_key": "repo_photos_local_12345678",
            "mode": "delete",
            "repository_deleted": True,
            "secret_deleted": True,
        },
        context,
    )

    assert context["repository_key"] == "repo_photos_local_12345678"
    assert context["repository_mode"] == "delete"
    assert context["repository_deleted"] is True
    assert context["secret_deleted"] is True
    assert "confirmation_phrase" not in context


def test_repository_delete_passes_authenticated_actor_to_audit(monkeypatch):
    import repositories_api

    captured = {}

    def fake_apply(_config, payload, *, audit_context=None):
        captured["payload"] = payload
        captured["audit_context"] = audit_context
        return {"ok": True}

    monkeypatch.setattr(repositories_api, "apply_repository_lifecycle", fake_apply)
    h = _make_handler()
    h._current_request_id = "request-456"
    h._read_json_body = lambda: {"repository_key": "repo_photos", "mode": "delete"}
    h._get_current_session_meta = lambda: {"username": "Admin.User", "role": "admin"}
    h._has_valid_api_token_header = lambda: False

    assert h._delete_repository() == {"ok": True}
    assert captured["audit_context"] == {
        "actor": "admin.user",
        "actor_role": "admin",
        "auth_method": "session",
        "request_id": "request-456",
    }


def test_ui_session_expired_is_invalid_and_removed():
    h = _make_handler()
    h.headers = {"Cookie": "bbui_session=sid-expired"}
    h._ui_auth_enabled = lambda: True
    h._persist_sessions = lambda: None
    h._session_idle_timeout_seconds = lambda: 1800
    h._session_absolute_timeout_seconds = lambda: 43200
    BackupUIHandler._UI_SESSIONS = {
        "sid-expired": {
            "created_at": time.time() - 7200,
            "expires_at": time.time() - 5,
            "last_seen_at": time.time() - 60,
        }
    }
    assert h._is_ui_session_valid() is False
    assert "sid-expired" not in BackupUIHandler._UI_SESSIONS


def test_valid_ui_session_refreshes_browser_cookie():
    h = _make_handler()
    h.headers = {"Cookie": "bbui_session=sid-active"}
    h._ui_auth_enabled = lambda: True
    h._persist_sessions = lambda: None
    h._session_idle_timeout_seconds = lambda: 900
    h._session_absolute_timeout_seconds = lambda: 43200
    now = time.time()
    BackupUIHandler._UI_SESSIONS = {
        "sid-active": {
            "created_at": now - 60,
            "expires_at": now + 60,
            "last_seen_at": now - 30,
        }
    }

    assert h._is_ui_session_valid() is True
    assert "bbui_session=sid-active" in h._refreshed_session_cookie
    assert "Max-Age=900" in h._refreshed_session_cookie
    assert BackupUIHandler._UI_SESSIONS["sid-active"]["expires_at"] > now + 800


def test_validate_target_dir_rejects_path_outside_allowed_roots(tmp_path: Path, monkeypatch):
    import config_api
    import api.restore_api as restore_api

    allowed = tmp_path / "allowed"
    other = tmp_path / "other"
    allowed.mkdir()
    other.mkdir()
    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {"RESTORE_ALLOWED_ROOTS": str(allowed)})
    monkeypatch.setattr(restore_api, "_is_safe_restore_root_text", lambda _raw: True)
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    with pytest.raises(ValueError, match="outside"):
        _validate_target_dir(str(other), cfg)


def test_validate_target_dir_rejects_nonexistent_directory(tmp_path: Path, monkeypatch):
    import config_api
    import api.restore_api as restore_api

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    missing = allowed / "missing-dir"
    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {"RESTORE_ALLOWED_ROOTS": str(allowed)})
    monkeypatch.setattr(restore_api, "_is_safe_restore_root_text", lambda _raw: True)
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    with pytest.raises(ValueError, match="does not exist"):
        _validate_target_dir(str(missing), cfg)


def test_restore_allowed_roots_filter_broad_mount_collections(monkeypatch):
    import config_api
    from api.restore_api import list_allowed_target_roots

    monkeypatch.setattr(
        config_api,
        "read_expanded_conf",
        lambda _cfg: {
            "RESTORE_ALLOWED_ROOTS": "/mnt/user,/mnt/data,/mnt,/mnt/disks,/mnt/disks/USB1,/mnt/remotes,/mnt/remotes/storagebox1,/boot"
        },
    )

    assert list_allowed_target_roots({}) == [
        "/mnt/user",
        "/mnt/data",
        "/mnt/disks/USB1",
        "/mnt/remotes/storagebox1",
    ]
