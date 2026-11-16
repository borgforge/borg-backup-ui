"""Security and projection contract regression tests for issue #738."""
import json
from types import SimpleNamespace

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import mobile_auth as auth
from api.auth_store import write_users_store
import mobile_api
from borg_backup_ui import BackupUIHandler


@pytest.fixture
def config(tmp_path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_users_store(config, {"users": [{"username": "viewer", "password_hash": "synthetic-hash",
                                        "role": "viewer", "enabled": True}]})
    return config


def paired(config):
    pairing = auth.begin(config, "Test Android", "test-client")
    assert auth.exchange(config, pairing["device_code"]) == {"status": "pending"}
    auth.approve(config, "viewer", pairing["user_code"])
    return pairing, auth.exchange(config, pairing["device_code"])


def test_pairing_consumed_hashed_private_and_revocable(config):
    pairing, session = paired(config)
    assert session["scope"] == "monitor:read"
    assert auth.authenticate(config, session["access_token"])["username"] == "viewer"
    raw = auth._path(config).read_text()
    assert session["access_token"] not in raw
    assert pairing["device_code"] not in raw
    assert pairing["user_code"] not in raw
    assert auth._path(config).stat().st_mode & 0o777 == 0o600
    with pytest.raises(auth.MobileError):
        auth.exchange(config, pairing["device_code"])
    own = auth.sessions(config, "viewer")["sessions"]
    assert set(own[0]) == {"id", "label", "created_at", "expires_at"}
    auth.revoke(config, "another", session["session_id"])
    auth.authenticate(config, session["access_token"])
    auth.revoke(config, "viewer", session["session_id"])
    with pytest.raises(auth.MobileError):
        auth.authenticate(config, session["access_token"])


@pytest.mark.parametrize('change', [{"enabled": False}, {"password_hash": "changed"}, {"role": "admin"}])
def test_user_changes_invalidate_device(config, change):
    _, session = paired(config)
    store = auth.read_users_store(config)
    store["users"][0].update(change)
    write_users_store(config, store)
    with pytest.raises(auth.MobileError):
        auth.authenticate(config, session["access_token"])


def test_expiry_rate_limit_and_corruption(config, monkeypatch):
    start = auth.time.time()
    pairing, session = paired(config)
    for _ in range(9):
        auth.begin(config, "Device", "test-client")
    with pytest.raises(auth.MobileError) as exc:
        auth.begin(config, "Device", "test-client")
    assert exc.value.api_status == 429
    monkeypatch.setattr(auth.time, 'time', lambda: start + auth.SESSION_TTL + 10)
    with pytest.raises(auth.MobileError):
        auth.authenticate(config, session["access_token"])
    auth._path(config).write_text('{broken')
    with pytest.raises(auth.MobileError) as exc:
        auth.begin(config, "Device", "other-client")
    assert exc.value.api_status == 503
    assert auth._path(config).read_text() == '{broken'


def handler(config, method, path, headers=None):
    h = BackupUIHandler.__new__(BackupUIHandler)
    h.config, h.command, h.path, h.headers = config, method, path, headers or {}
    h._ui_auth_enabled = lambda: True
    h._is_ui_session_valid = lambda: False
    h._authorize_maintenance_request = lambda *_: True
    h._send_api_error = lambda status, *args, **kwargs: setattr(h, 'error_status', status)
    return h


def test_authorization_boundaries(config):
    _, session = paired(config)
    bearer = {"Authorization": "Bearer " + session["access_token"]}
    h = handler(config, 'GET', '/api/mobile/v1/snapshot', bearer)
    assert h._authorize_api_request(h.path, 'test')
    h.path = '/api/jobs'
    h._get_api_token = lambda: 'synthetic-internal-token'
    assert not h._authorize_api_request(h.path, 'test')
    assert h.error_status == 401
    for credential in ({"Cookie": "bbui_session=anything"}, {"Authorization": "Bearer synthetic-internal-token"}):
        h = handler(config, 'GET', '/api/mobile/v1/snapshot', credential)
        assert not h._authorize_api_request(h.path, 'test')
        assert h.error_status == 401
    h = handler(config, 'POST', '/api/auth/mobile/approve', {**bearer, 'Content-Type': 'application/json'})
    assert not h._authorize_api_request(h.path, 'test')
    h._is_ui_session_valid = lambda: True
    h._get_current_session_meta = lambda: {'username': 'viewer'}
    assert not h._authorize_api_request(h.path, 'test')
    h.headers.update(Origin='https://example.test', Host='example.test')
    assert h._authorize_api_request(h.path, 'test')
    h.headers['Origin'] = 'http://example.test'
    assert not h._authorize_api_request(h.path, 'test')


def test_snapshot_allowlist_and_unknown_measurements():
    secret = '/private/secret-path'
    h = SimpleNamespace(
        _get_jobs=lambda: {'jobs': [{'key': secret, 'display_name': 'Photos', 'repository_key': secret,
                                    'repository_name': 'Repository', 'repo_path': secret, 'last_status': 'success'}]},
        _get_history=lambda _: {'entries': [{'job_key': secret, 'job_name': 'Photos', 'timestamp': '2026-01-02 12:00:00', 'log_file': secret}]},
        _get_report_overview=lambda _: {'daily': [{'date': '2026-01-02', 'repository_bytes': None}]})
    result = mobile_api.snapshot(h)
    assert secret not in json.dumps(result)
    assert result['history'][0]['bytes'] is None
    assert result['repositories'][0]['bytes'] is None
    assert result['jobs'][0]['next_run'] is None
    assert result['jobs'][0]['status'] == 'success'
    assert result['history'][0]['timestamp'].endswith('+00:00')


def test_disable_then_reenable_does_not_restore_device(config):
    _, session = paired(config)
    store = auth.read_users_store(config)
    store['users'][0]['enabled'] = False
    write_users_store(config, store)
    store['users'][0]['enabled'] = True
    write_users_store(config, store)
    with pytest.raises(auth.MobileError):
        auth.authenticate(config, session['access_token'])


def test_pending_expiry_approval_replay_and_unknown_methods(config, monkeypatch):
    pair = auth.begin(config, 'Phone', 'ip')
    auth.approve(config, 'viewer', pair['user_code'])
    with pytest.raises(auth.MobileError):
        auth.approve(config, 'viewer', pair['user_code'])
    now = auth.time.time()
    monkeypatch.setattr(auth.time, 'time', lambda: now + 601)
    with pytest.raises(auth.MobileError):
        auth.exchange(config, pair['device_code'])
    for method, path in [('POST', '/api/mobile/v1/snapshot'), ('GET', '/api/mobile/v1/pair'), ('GET', '/api/mobile/v1/snapshot?token=synthetic')]:
        h = handler(config, method, path, {'Content-Type': 'application/json'})
        assert not h._authorize_api_request(path.split('?')[0], 'test')
        assert h.error_status == 404


def test_http_pairing_snapshot_and_logout(config):
    """Exercise real HTTP parsing, browser cookies/Origin, headers and projection."""
    from http.server import ThreadingHTTPServer
    from http.client import HTTPConnection
    import threading
    from io import BytesIO

    class TestHandler(BackupUIHandler):
        _UI_SESSIONS = {}
        def log_message(self, *_args):
            pass
        def _get_jobs(self):
            return {'jobs': []}
        def _get_history(self, _query):
            return {'entries': []}
        def _get_report_overview(self, _query):
            return {'daily': []}

    TestHandler.config = config
    TestHandler._UI_SESSIONS['synthetic-browser-session'] = {
        'username': 'viewer', 'role': 'viewer', 'mode': 'users',
        'created_at': auth.time.time(), 'expires_at': auth.time.time() + 300}
    server = ThreadingHTTPServer(('127.0.0.1', 0), TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = HTTPConnection(*server.server_address, timeout=5)
    def request(method, path, body=None, headers=None):
        payload = None if body is None else json.dumps(body)
        conn.request(method, path, payload, {'Content-Type': 'application/json', **(headers or {})})
        response = conn.getresponse()
        data = json.loads(response.read())
        return response.status, dict(response.getheaders()), data
    try:
        status, headers, pair = request('POST', '/api/mobile/v1/pair', {'device_name': 'Test Android'})
        assert status == 200
        assert headers['Cache-Control'] == 'no-store'
        assert 'Set-Cookie' not in headers
        status, _, _ = request('POST', '/api/auth/mobile/approve', {'user_code': pair['user_code']},
                               {'Cookie': 'bbui_session=synthetic-browser-session', 'Origin': 'https://example.test', 'Host': 'example.test'})
        assert status == 200
        status, _, session = request('POST', '/api/mobile/v1/exchange', {'device_code': pair['device_code']})
        assert status == 200
        bearer = {'Authorization': 'Bearer ' + session['access_token']}
        status, headers, data = request('GET', '/api/mobile/v1/snapshot', headers=bearer)
        assert status == 200 and data['api_version'] == 1
        assert headers['Cache-Control'] == 'no-store'
        assert 'Set-Cookie' not in headers
        assert request('POST', '/api/jobs/run', {'job_key': 'never-run'}, bearer)[0] in (401, 403)
        assert request('POST', '/api/mobile/v1/logout', {}, bearer)[0] == 200
        assert request('GET', '/api/mobile/v1/snapshot', headers=bearer)[0] == 401
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
