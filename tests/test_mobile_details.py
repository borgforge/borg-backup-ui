"""Bounded private log consent, identity and repository projection (#743)."""
import json
import pytest
from test_mobile_auth import config, paired, handler  # noqa: F401
from test_mobile_controls import make_handler
import mobile_auth as auth
import mobile_api as api
import mobile_logs
import repositories_api
import config_api
import jobs_api


def log_handler(config):
    _, credentials = paired(config)
    session = auth.authenticate(config, credentials['access_token'])
    h = make_handler(config, session)
    return h, session


def test_consent_owned_rechecked_and_revocable(config, monkeypatch):
    h, session = log_handler(config)
    body = {'job_id': api._id('photos'), 'run_id': 'run-12345'}
    with pytest.raises(auth.MobileError) as exc:
        mobile_logs.read_log(h, body)
    assert exc.value.api_status == 403
    with pytest.raises(auth.MobileError):
        auth.log_permission(config, 'viewer', session['id'], 'true')
    assert auth.log_permission(config, 'viewer', session['id'], True) == {'logs': True}
    monkeypatch.setattr(jobs_api.JobManager, 'output_tail', lambda *_: {'text':'Backup complete\n', 'running':False})
    assert mobile_logs.read_log(h, body)['text'] == 'Backup complete\n'
    # Use the old in-flight session object: permission removal still takes effect.
    auth.log_permission(config, 'viewer', session['id'], False)
    with pytest.raises(auth.MobileError) as exc:
        mobile_logs.read_log(h, body)
    assert exc.value.api_status == 403
    auth.log_permission(config, 'viewer', session['id'], True)
    def revoke_during_read(*_):
        auth.revoke(config, 'viewer', session['id'])
        return {'text':'private', 'running':False}
    monkeypatch.setattr(jobs_api.JobManager, 'output_tail', revoke_during_read)
    with pytest.raises(auth.MobileError) as exc:
        mobile_logs.read_log(h, body)
    assert exc.value.api_status == 401


def test_history_exact_log_bounded_original_and_confined(config, tmp_path, monkeypatch):
    h, session = log_handler(config)
    auth.log_permission(config, 'viewer', session['id'], True)
    logs = tmp_path / 'logs'; logs.mkdir()
    log = logs / 'one.log'
    log.write_text('old\n'*10000 + 'password=synthetic-secret\nBORG_PASSPHRASE=hidden\n/private/file name.txt\nA private-name.txt\n' + 'bfm_'+'a'*43+'\nBackup complete\n')
    monkeypatch.setattr(config_api, 'read_expanded_conf', lambda _: {'GLOBAL_LOG_DIR':str(logs)})
    row = {'job_key':'photos', 'timestamp':'2026-11-16T10:00:00Z', 'run_id':'run-12345', 'log_file':str(log)}
    h._get_history = lambda _: {'entries':[row]}
    event = api._id('photos'+api._stamp(row['timestamp'])+'run-12345')
    body = {'event_id':event}
    result = mobile_logs.read_log(h, body)
    assert result['limited'] and result['redacted'] is False and not result['running']
    assert 'Backup complete' in result['text'] and len(result['text']) < 12001
    assert all(s in result['text'] for s in ('synthetic-secret','hidden','private-name','/private','bfm_'))
    for invalid in ({**body,'file':str(log)}, {'event_id':'../secret'}, {'event_id':'f'*32}):
        with pytest.raises(auth.MobileError): mobile_logs.read_log(h, invalid)
    outside = tmp_path / 'outside.log'; outside.write_text('must not read')
    log.unlink(); log.symlink_to(outside)
    with pytest.raises(auth.MobileError) as exc: mobile_logs.read_log(h, body)
    assert exc.value.api_status == 404


def test_run_replacement_and_permission_route_guards(config, monkeypatch):
    h, session = log_handler(config)
    auth.log_permission(config, 'viewer', session['id'], True)
    monkeypatch.setattr(jobs_api.JobManager, 'output_tail', lambda *_: None)
    monkeypatch.setattr(jobs_api, 'get_job_runtime_state', lambda *_: {'run_id':'new-run', 'running':True})
    with pytest.raises(auth.MobileError) as exc:
        mobile_logs.read_log(h, {'job_id':api._id('photos'), 'run_id':'old-run'})
    assert exc.value.api_status == 409
    for route in ('/api/mobile/v1/logs/read','/api/auth/mobile/log-permission'):
        request = handler(config, 'POST', route, {'Content-Type':'application/json'})
        assert not api.authorize(request, route, 'request')


def test_inventory_projection_never_exposes_secrets_or_executes_borg(config, monkeypatch):
    h, _ = log_handler(config)
    monkeypatch.setattr(repositories_api, 'read_repository_store', lambda _: {'repositories':[
        {'repository_key':'repo','display_name':'Local', 'encryption':'repokey',
         'repository_stats':{'archives_count':12,'total_size':1000,'total_csize':500,'unique_csize':300},
         'last_info_refresh_at':'2026-11-16T10:00:00Z', 'last_info_refresh_status':'success',
         'passphrase_ref':'secret', 'relative_path':'/private'},
        {'repository_key':'unused','display_name':'Empty','repository_stats':{}}]})
    data = api.snapshot(h)
    repo = data['repositories'][0]
    assert repo['archives_count'] == 12 and repo['deduplicated_bytes'] == 300
    assert repo['encryption'] == 'repokey' and repo['info_at']
    assert data['repositories'][1]['archives_count'] is None
    assert 'passphrase_ref' not in json.dumps(data) and '/private' not in json.dumps(data)


def test_memory_tail_pins_run_and_never_copies_full_log():
    from datetime import datetime
    manager = jobs_api.JobManager()
    state = jobs_api._JobState(None, datetime.now(), 'run-12345')
    state.lines = ['old'] * 1000 + ['x' * 9000, 'Backup complete']
    manager._states['photos'] = state
    assert manager.output_tail('photos', 'different-run') is None
    result = manager.output_tail('photos', 'run-12345')
    assert result['running'] and len(result['text']) <= 8192
    assert 'x' * 6000 in result['text']
    assert 'omitted' not in result['text']
    assert result['text'].endswith('Backup complete\n')


def test_permission_does_not_grant_foreign_devices(config):
    h, session = log_handler(config)
    from auth_store import write_users_store
    users = auth.read_users_store(config)
    users['users'].append({'username':'other','password_hash':'synthetic','role':'viewer','enabled':True})
    write_users_store(config, users)
    with pytest.raises(auth.MobileError) as exc:
        auth.log_permission(config, 'other', session['id'], True)
    assert exc.value.api_status == 404
    with pytest.raises(auth.MobileError):
        auth.require_logs(config, session)


def test_finished_live_run_uses_only_matching_history(config, tmp_path, monkeypatch):
    h, session = log_handler(config)
    auth.log_permission(config, 'viewer', session['id'], True)
    monkeypatch.setattr(jobs_api.JobManager, 'output_tail', lambda *_: None)
    monkeypatch.setattr(jobs_api, 'get_job_runtime_state', lambda *_: {'run_id':'new-run', 'running':True})
    log = tmp_path / 'logs' / 'run.log'; log.parent.mkdir(); log.write_text('Finished previous run\n')
    monkeypatch.setattr(config_api, 'read_expanded_conf', lambda _: {'GLOBAL_LOG_DIR':str(log.parent)})
    h._get_history = lambda _: {'entries':[{'job_key':'photos','run_id':'old-run','log_file':str(log)}]}
    result = mobile_logs.read_log(h, {'job_id':api._id('photos'), 'run_id':'old-run'})
    assert not result['running'] and result['text'] == 'Finished previous run\n'


def test_original_tail_preserves_text_and_never_exceeds_bound():
    text = "A /synthetic/file name.txt\r\npassword=synthetic-only\n  indented\ttext 😀\n"
    assert mobile_logs._tail(text) == text
    assert mobile_logs._tail("x" * 10000 + text) == ("x" * 10000 + text)[-6000:]
