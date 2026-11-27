"""Persistent device grants retain revocation and short access expiry (#742)."""
import json
import pytest
from test_mobile_auth import config, handler  # noqa: F401
import mobile_auth as auth
import mobile_api as api


def paired(config):
    pair = auth.begin(config, 'Synthetic phone', 'ip', True)
    auth.approve(config, 'viewer', pair['user_code'])
    return auth.exchange(config, pair['device_code'])


def test_refresh_after_long_absence_keeps_identity_and_hashed_secrets(config, monkeypatch):
    session = paired(config)
    original = auth.authenticate(config, session['access_token'])
    monkeypatch.setattr(auth.time, 'time', lambda: session['expires_at'] + 365 * 86400)
    with pytest.raises(auth.MobileError):
        auth.authenticate(config, session['access_token'])
    metadata = auth.sessions(config, 'viewer')['sessions'][0]
    assert metadata['persistent'] is True
    assert 'refresh_hash' not in metadata
    renewed = auth.refresh(config, session['refresh_token'])
    assert renewed['session_id'] == original['id']
    assert renewed['expires_at'] == auth.time.time() + auth.SESSION_TTL
    assert auth.authenticate(config, renewed['access_token'])['username'] == 'viewer'
    raw = auth._path(config).read_text()
    assert session['refresh_token'] not in raw and renewed['access_token'] not in raw
    assert auth._path(config).stat().st_mode & 0o777 == 0o600
    with pytest.raises(auth.MobileError):
        auth.authenticate(config, session['refresh_token'])
    # A lost renewal response can be recovered with the device credential.
    again = auth.refresh(config, session['refresh_token'])
    with pytest.raises(auth.MobileError):
        auth.authenticate(config, renewed['access_token'])
    auth.authenticate(config, again['access_token'])
    auth.revoke(config, 'viewer', original['id'])
    with pytest.raises(auth.MobileError):
        auth.refresh(config, session['refresh_token'])
    with pytest.raises(auth.MobileError):
        auth.authenticate(config, again['access_token'])


@pytest.mark.parametrize('change', [{'enabled': False}, {'role': 'operator'}, {'password_hash': 'changed'}])
def test_refresh_rechecks_account_security(config, change):
    session = paired(config)
    users = auth.read_users_store(config)
    users['users'][0].update(change)
    from auth_store import write_users_store
    write_users_store(config, users)
    with pytest.raises(auth.MobileError):
        auth.refresh(config, session['refresh_token'])


def test_logout_all_revokes_refresh_and_pending_grants(config):
    session = paired(config)
    auth.revoke_users(config)
    with pytest.raises(auth.MobileError):
        auth.refresh(config, session['refresh_token'])


def test_refresh_route_origin_contract_and_legacy(config):
    legacy = auth.begin(config, 'Legacy', 'legacy')
    auth.approve(config, 'viewer', legacy['user_code'])
    assert 'refresh_token' not in auth.exchange(config, legacy['device_code'])
    session = paired(config)
    h = handler(config, 'POST', '/api/mobile/v1/refresh', {'Content-Type': 'application/json'})
    payload = {'refresh_token': session['refresh_token']}
    h.headers['Content-Length'] = str(len(json.dumps(payload)))
    h._read_json_body = lambda: payload
    assert api.authorize(h, h.path, 'test')
    assert api.handle(h)['session_id'] == session['session_id']
    h.headers['Origin'] = 'https://example.test'
    assert not api.authorize(h, h.path, 'test')
    assert h.error_status == 403
    for value in [True, 'invalid', session['access_token']]:
        with pytest.raises(auth.MobileError):
            auth.refresh(config, value)
    with pytest.raises(auth.MobileError):
        auth.begin(config, 'Phone', 'ip', 'true')


def test_renewal_rejects_already_authorized_old_command_epoch(config):
    users = auth.read_users_store(config)
    users['users'][0]['role'] = 'operator'
    from auth_store import write_users_store
    write_users_store(config, users)
    pair = auth.begin(config, 'Phone', 'ip', True)
    auth.approve(config, 'viewer', pair['user_code'], True)
    session = auth.exchange(config, pair['device_code'])
    old = auth.authenticate(config, session['access_token'])
    auth.refresh(config, session['refresh_token'])
    with pytest.raises(auth.MobileError) as error:
        auth.command(config, old, 'a' * 32, {}, lambda: pytest.fail('Old epoch executed'))
    assert error.value.api_status == 401
