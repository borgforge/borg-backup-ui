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
    assert 'data-i18n="auth.passwordConfirm"' in html
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


def test_is_api_authorized_accepts_header_token_when_ui_session_not_required():
    h = _make_handler()
    h.headers = {"X-API-Token": "tok-1"}
    h._ui_auth_enabled = lambda: False
    h._is_ui_session_valid = lambda: False
    h._get_api_token = lambda: "tok-1"
    assert h._is_api_authorized() is True


def test_is_api_authorized_rejects_cookie_token_without_valid_ui_session():
    h = _make_handler()
    h.headers = {"Cookie": "bbui_api_token=tok-1; bbui_session=sid-1"}
    h._ui_auth_enabled = lambda: True
    h._is_ui_session_valid = lambda: False
    h._get_api_token = lambda: "tok-1"
    assert h._is_api_authorized() is False


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
