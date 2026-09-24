"""Private regression coverage for GHSA-h4gr-4cm5-92gr.

Only synthetic logs and authentication stores below pytest's temporary root
are used. Requests exercise the real routing, session and role checks.
"""

from http.client import HTTPConnection
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "api", ROOT / "runtime" / "lib"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import history_api
from api.auth_store import hash_password, write_sessions_store, write_users_store
from borg_backup_ui import BackupUIHandler, ThreadedHTTPServer


@pytest.fixture
def logs(tmp_path, monkeypatch):
    """Isolate configured/legacy roots and seed real viewer/admin sessions."""
    current = tmp_path / "logs"
    legacy = tmp_path / "legacy-logs"
    outside = tmp_path / "logs-outside"
    for directory in (current, legacy, outside):
        directory.mkdir()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "app"), "STATUS_DIR": str(tmp_path / "status")}
    password = "local-history-test-password"
    write_users_store(config, {"users": [
        {"username": role, "role": role, "enabled": True,
         "password_hash": hash_password(password, iterations=10000)}
        for role in ("viewer", "admin")
    ]})
    conf = Path(config["BACKUP_SCRIPTS_DIR"]) / "config" / "backup.conf"
    conf.write_text(f'GLOBAL_LOG_DIR="{current}"\n', encoding="utf-8")
    now = time.time()
    write_sessions_store(config, {"sessions": [
        {"sid": f"test-{role}", "username": role, "role": role, "mode": "users",
         "created_at": now, "last_seen_at": now, "expires_at": now + 3600}
        for role in ("viewer", "admin")
    ]})
    monkeypatch.setattr(history_api, "LEGACY_LOG_DIR", legacy, raising=False)

    class Handler(BackupUIHandler):
        _UI_SESSIONS = {}
        _UI_SESSIONS_LOCK = threading.RLock()
        _LOGIN_FAILURES = {}

    Handler.config = config

    def request(path=None, *, query=None, role="viewer"):
        """Dispatch a GET with a real session, replacing only HTTP transport."""
        handler = Handler.__new__(Handler)
        handler.path = "/api/history/log?" + (query if query is not None else urlencode({"file": str(path)}))
        handler.command = "GET"
        handler.headers = {"Cookie": f"bbui_session=test-{role}"} if role else {}
        handler.client_address = ("127.0.0.1", 12345)
        handler.wfile = BytesIO()
        responses = []
        handler.send_response = responses.append
        handler.send_header = lambda *_args: None
        handler.end_headers = lambda: None
        handler.do_GET()
        assert len(responses) == 1
        return responses[0], json.loads(handler.wfile.getvalue())

    return current, legacy, outside, conf, Handler, request, password


@pytest.mark.parametrize("role", ["viewer", "admin"])
@pytest.mark.parametrize("kind", ["absolute", "relative-traversal", "absolute-traversal", "double-slash"])
def test_outside_log_files_are_denied(logs, kind, role):
    current, _legacy, outside, _conf, _handler, request, _password = logs
    secret = outside / "proof.txt"
    secret.write_text("OUTSIDE-LOG-PROOF", encoding="utf-8")
    paths = {
        "absolute": str(secret),
        "relative-traversal": "../logs-outside/proof.txt",
        "absolute-traversal": str(current / ".." / "logs-outside" / "proof.txt"),
        "double-slash": "/" + str(secret),
    }
    status, data = request(paths[kind], role=role)
    assert status == 403
    assert data["code"] == "forbidden"
    assert "OUTSIDE-LOG-PROOF" not in json.dumps(data)


@pytest.mark.parametrize("target_name", ["outside.txt", "outside.bin"])
def test_file_symlink_cannot_escape_log_roots(logs, target_name):
    current, _legacy, outside, _conf, _handler, request, _password = logs
    target = outside / target_name
    target.write_text("SYMLINK-OUTSIDE-PROOF", encoding="utf-8")
    link = current / "backup.log"
    link.symlink_to(target)
    status, data = request(link)
    assert status == 403
    assert "SYMLINK-OUTSIDE-PROOF" not in json.dumps(data)


def test_directory_symlink_cannot_escape_log_roots(logs):
    current, _legacy, outside, _conf, _handler, request, _password = logs
    (outside / "backup.log").write_text("DIRECTORY-OUTSIDE-PROOF", encoding="utf-8")
    (current / "nested").symlink_to(outside, target_is_directory=True)
    status, data = request(current / "nested" / "backup.log")
    assert status == 403
    assert "DIRECTORY-OUTSIDE-PROOF" not in json.dumps(data)


@pytest.mark.parametrize("name", ["backup.log", "backup.txt", "backup.LOG", "Größe + 100%.log", "literal%2fname.log"])
def test_viewer_can_read_configured_logs_with_one_url_decode(logs, name):
    current, _legacy, _outside, _conf, _handler, request, _password = logs
    path = current / name
    path.write_bytes(b"BACKUP-LOG\ninvalid-utf8:\xff\n")
    status, data = request(path)
    assert status == 200
    assert data == {"exists": True, "path": str(path), "content": "BACKUP-LOG\ninvalid-utf8:\ufffd\n"}


def test_unauthenticated_request_is_rejected(logs):
    current, _legacy, _outside, _conf, _handler, request, _password = logs
    path = current / "backup.log"
    path.write_text("PRIVATE-LOG", encoding="utf-8")
    status, data = request(path, role=None)
    assert status == 401
    assert "PRIVATE-LOG" not in json.dumps(data)


@pytest.mark.parametrize("relative", ["backup.log", "nested/backup.log"])
def test_relative_paths_use_configured_log_root_not_working_directory(logs, monkeypatch, relative):
    current, _legacy, outside, _conf, _handler, request, _password = logs
    allowed = current / relative
    disallowed = outside / relative
    allowed.parent.mkdir(exist_ok=True)
    disallowed.parent.mkdir(exist_ok=True)
    allowed.write_text("ALLOWED-LOG", encoding="utf-8")
    disallowed.write_text("WORKING-DIRECTORY-PROOF", encoding="utf-8")
    monkeypatch.chdir(outside)
    status, data = request(relative)
    assert status == 200
    assert data["content"] == "ALLOWED-LOG"
    assert data["path"] == str(allowed)


@pytest.mark.parametrize("destination", ["current", "legacy"])
def test_moved_log_basename_fallback_reads_only_allowed_copy(logs, destination):
    current, legacy, outside, _conf, _handler, request, _password = logs
    old = outside / "backup.log"
    old.write_text("OLD-OUTSIDE-PROOF", encoding="utf-8")
    allowed = (current if destination == "current" else legacy) / old.name
    allowed.write_text("RETAINED-LOG", encoding="utf-8")
    status, data = request(old)
    assert status == 200
    assert data == {"exists": True, "path": str(allowed), "content": "RETAINED-LOG"}


def test_exact_allowed_path_wins_over_basename_fallback(logs):
    current, legacy, _outside, _conf, _handler, request, _password = logs
    for directory in (current, legacy):
        (directory / "backup.log").write_text(directory.name, encoding="utf-8")
    status, data = request(legacy / "backup.log")
    assert status == 200
    assert data["content"] == legacy.name


def test_default_log_directory_still_works(logs):
    _current, legacy, _outside, conf, _handler, request, _password = logs
    conf.write_text('GLOBAL_LOG_DIR=""\n', encoding="utf-8")
    path = legacy / "backup.log"
    path.write_text("DEFAULT-LOG", encoding="utf-8")
    status, data = request(path.name)
    assert status == 200
    assert data["content"] == "DEFAULT-LOG"


@pytest.mark.parametrize("use_alias", [True, False])
def test_configured_root_symlink_and_its_canonical_path_are_supported(logs, use_alias):
    current, _legacy, outside, conf, _handler, request, _password = logs
    alias = outside / "configured-log-root"
    alias.symlink_to(current, target_is_directory=True)
    conf.write_text(f'GLOBAL_LOG_DIR="{alias}"\n', encoding="utf-8")
    (current / "backup.log").write_text("CONFIGURED-ROOT-LOG", encoding="utf-8")
    status, data = request((alias if use_alias else current) / "backup.log")
    assert status == 200
    assert data["content"] == "CONFIGURED-ROOT-LOG"


def test_symlink_staying_inside_log_storage_is_supported(logs):
    current, _legacy, _outside, _conf, _handler, request, _password = logs
    target = current / "backup.txt"
    target.write_text("INTERNAL-LINK-LOG", encoding="utf-8")
    link = current / "current.log"
    link.symlink_to(target)
    status, data = request(link)
    assert status == 200
    assert data["path"] == str(target)
    assert data["content"] == "INTERNAL-LINK-LOG"


def test_symlink_cannot_bypass_resolved_file_type(logs):
    current, _legacy, _outside, _conf, _handler, request, _password = logs
    target = current / "config.bin"
    target.write_text("NON-LOG-PROOF", encoding="utf-8")
    link = current / "backup.log"
    link.symlink_to(target)
    status, data = request(link)
    assert status == 403
    assert "NON-LOG-PROOF" not in json.dumps(data)


@pytest.mark.parametrize("destination", ["current", "legacy"])
def test_basename_fallback_cannot_follow_escaping_symlink(logs, destination):
    current, legacy, outside, _conf, _handler, request, _password = logs
    target = outside / "proof.txt"
    target.write_text("FALLBACK-OUTSIDE-PROOF", encoding="utf-8")
    ((current if destination == "current" else legacy) / "backup.log").symlink_to(target)
    status, data = request(outside / "old" / "backup.log")
    assert status == 403
    assert "FALLBACK-OUTSIDE-PROOF" not in json.dumps(data)


def test_symlink_loop_is_rejected(logs):
    current, _legacy, _outside, _conf, _handler, request, _password = logs
    path = current / "loop.log"
    path.symlink_to(path)
    status, _data = request(path)
    assert status == 403


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_non_regular_files_are_rejected_without_blocking(logs, kind):
    current, _legacy, _outside, _conf, _handler, request, _password = logs
    path = current / "special.log"
    if kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    status, data = request(path)
    assert status == 400
    assert data["code"] == "bad_request"


@pytest.mark.parametrize("query", ["", "file=", "file=backup.json", "file=bad%00.log"])
def test_invalid_requests_return_bad_request(logs, query):
    *_unused, request, _password = logs
    status, data = request(query=query)
    assert status == 400
    assert data["code"] == "bad_request"


def test_missing_allowed_file_preserves_response_contract(logs):
    current, _legacy, _outside, _conf, _handler, request, _password = logs
    path = current / "missing.log"
    status, data = request(path)
    assert status == 200
    assert data == {"exists": False, "content": "", "path": str(path)}


def test_double_encoded_traversal_is_not_decoded_again(logs):
    current, _legacy, outside, _conf, _handler, request, _password = logs
    target = outside / "proof.txt"
    target.write_text("DOUBLE-ENCODED-PROOF", encoding="utf-8")
    status, data = request(str(current) + "/%2e%2e%2flogs-outside%2fproof.txt")
    assert status == 200
    assert data["exists"] is False
    assert "DOUBLE-ENCODED-PROOF" not in json.dumps(data)


@pytest.mark.parametrize("component", ["file", "directory", "root"])
def test_symlink_swap_between_check_and_open_is_rejected(logs, monkeypatch, component):
    current, _legacy, outside, _conf, _handler, request, _password = logs
    nested = current / "nested"
    nested.mkdir()
    log = nested / "backup.log"
    log.write_text("ALLOWED-LOG", encoding="utf-8")
    (outside / "backup.log").write_text("RACE-OUTSIDE-PROOF", encoding="utf-8")
    victim = {"file": log, "directory": nested, "root": current}[component]
    destination = outside / "backup.log" if component == "file" else outside
    original_open = os.open
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and path == victim.name and kwargs.get("dir_fd") is not None:
            victim.rename(victim.with_name(victim.name + "-original"))
            victim.symlink_to(destination, target_is_directory=component != "file")
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(history_api.os, "open", swap_then_open)
    status, data = request(log)
    assert swapped
    assert status == 403
    assert "RACE-OUTSIDE-PROOF" not in json.dumps(data)


def test_real_http_viewer_login_log_access_and_ui_assets(logs):
    """Smoke-test the HTTP server with a real viewer login and local files."""
    current, _legacy, outside, _conf, handler, _request, password = logs
    (current / "backup.log").write_text("HTTP-ALLOWED-LOG", encoding="utf-8")
    (outside / "proof.txt").write_text("HTTP-OUTSIDE-PROOF", encoding="utf-8")
    server = ThreadedHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        client.request("POST", "/api/auth/login", json.dumps({"username": "viewer", "password": password}),
                       {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{server.server_port}"})
        response = client.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["role"] == "viewer"
        cookie = response.getheader("Set-Cookie").split(";", 1)[0]
        for path, expected_status, marker in [
            ("/api/history/log?" + urlencode({"file": str(current / "backup.log")}), 200, "HTTP-ALLOWED-LOG"),
            ("/api/history/log?" + urlencode({"file": str(outside / "proof.txt")}), 403, "forbidden"),
            ("/api/history", 200, '"entries"'),
            ("/", 200, "<html"),
            ("/ui/js/components/log-viewer.js", 200, "/api/history/log"),
        ]:
            client.request("GET", path, headers={"Cookie": cookie})
            response = client.getresponse()
            body = response.read().decode("utf-8")
            assert response.status == expected_status, body
            assert marker in body
            assert "HTTP-OUTSIDE-PROOF" not in body
        client.request("GET", "/api/history/log?file=backup.log")
        response = client.getresponse()
        assert response.status == 401
        response.read()
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
