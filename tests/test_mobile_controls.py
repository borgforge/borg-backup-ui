"""Mobile monitoring and opt-in commands use real authorization, mocked runners."""
from types import SimpleNamespace
import json
import pytest
from test_mobile_auth import config  # noqa: F401
import mobile_auth as auth
import mobile_api as api
import jobs_api
import job_launch
import schedule_api


def operator(config, consent=True):
    users = auth.read_users_store(config)
    users['users'][0]['role'] = 'operator'
    from auth_store import write_users_store
    write_users_store(config, users)
    pair = auth.begin(config, 'Synthetic phone', 'ip')
    auth.approve(config, 'viewer', pair['user_code'], consent)
    token = auth.exchange(config, pair['device_code'])['access_token']
    return auth.authenticate(config, token)


def make_handler(config, session):
    job = {'key': 'photos', 'display_name': 'Photos', 'enabled': True,
           'standard': 'wizard', 'is_utility': False, 'last_status': 'failed',
           'repository_key': 'repo', 'repository_name': 'Local',
           'restore_verification_status': 'never'}
    return SimpleNamespace(config=config, _mobile_session=session,
        _get_jobs=lambda: {'jobs': [job]}, _get_running=lambda: {},
        _get_status=lambda: {'backups': [{'key': 'photos', 'status': 'failed',
            'original_size': 100, 'repository_size': 500, 'exit_code': 2,
            'failure_code': 'required_source_paths_missing', 'timestamp': '2026-11-15T10:00:00Z',
            'error_message': '/private/secret', 'repository_check_date': '2026-11-14T10:00:00Z'}]},
        _get_history=lambda _: {'entries': []}, _get_report_overview=lambda _: {'daily': []})


def test_status_schedule_metrics_and_allowlist(config, monkeypatch):
    h = make_handler(config, operator(config))
    monkeypatch.setattr(schedule_api, 'get_schedules', lambda _: {'photos': {'enabled': True, 'cron': '0 22 * * *'}})
    data = api.snapshot(h)
    job = data['jobs'][0]
    assert job['status'] == 'error' and job['bytes'] == 100
    assert job['exit_code'] == 2 and job['reason_code'] == 'required_source_paths_missing'
    assert job['schedule_state'] == 'active' and job['next_run']
    assert job['can_start'] and not job['can_cancel']
    assert data['repositories'][0]['bytes'] == 500
    assert data['repositories'][0]['checked_at']
    assert data['restore_tests'][0]['verification'] == 'never'
    assert data['restore_tests'][0]['checked_at'] is None
    assert '/private' not in json.dumps(data)
    for value in ('cancelled', 'skipped', 'unavailable'):
        assert api._status(value) == value
    assert api._status('failed') == 'error'
    assert api._code('/private/error') is None
    assert api._schedule({'key':'x'}, {})['schedule_state'] == 'none'
    assert api._schedule({'key':'x'}, {'x':{'cron':'*/5 * * * *'}})['schedule_state'] == 'unsupported'


def test_readonly_and_viewer_cannot_gain_control(config):
    pair = auth.begin(config, 'Synthetic', 'ip')
    with pytest.raises(auth.MobileError) as exc:
        auth.approve(config, 'viewer', pair['user_code'], True)
    assert exc.value.api_status == 403
    for consent in ('true', 1):
        with pytest.raises(auth.MobileError):
            auth.approve(config, 'viewer', pair['user_code'], consent)
    h = make_handler(config, operator(config, False))
    with pytest.raises(auth.MobileError) as exc:
        api.control(h, 'start', {'job_id':api._id('photos'), 'request_id':'a'*32})
    assert exc.value.api_status == 403


def test_start_duplicate_guard_persists_and_rechecks_revocation(config, monkeypatch):
    h = make_handler(config, operator(config))
    calls = []
    monkeypatch.setattr(jobs_api, 'get_job_runtime_state', lambda *_: {})
    monkeypatch.setattr(job_launch, 'start_backup', lambda *a, **kw: calls.append(kw) or {'run_id':'run-1'})
    body = {'job_id':api._id('photos'), 'request_id':'a'*32}
    assert api.control(h, 'start', body) == {'accepted':True, 'run_id':'run-1'}
    assert api.control(h, 'start', body)['accepted']
    assert len(calls) == 1
    assert calls[0]['source'] == 'mobile'
    with pytest.raises(auth.MobileError):
        api.control(h, 'start', {**body, 'job_id':api._id('another')})
    auth.revoke(config, 'viewer', h._mobile_session['id'])
    with pytest.raises(auth.MobileError) as exc:
        api.control(h, 'start', body)
    assert exc.value.api_status == 401
    assert len(calls) == 1


def test_uncertain_launch_never_retried(config, monkeypatch):
    h = make_handler(config, operator(config))
    calls = []
    monkeypatch.setattr(jobs_api, 'get_job_runtime_state', lambda *_: {})
    def fail(*args, **kwargs):
        calls.append(True)
        raise RuntimeError('/private/launch-detail')
    monkeypatch.setattr(job_launch, 'start_backup', fail)
    body = {'job_id':api._id('photos'), 'request_id':'a'*32}
    for _ in range(2):
        with pytest.raises(auth.MobileError) as exc:
            api.control(h, 'start', body)
        assert exc.value.api_status == 409
        assert 'private' not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.parametrize('runtime', [
    {}, {'running':True,'run_id':'new','cancel_allowed':True},
    {'running':True,'run_id':'old','cancel_allowed':False},
    {'running':True,'run_id':'old','cancel_allowed':True,'cancel_requested':True},
])
def test_cancel_rejects_stale_or_protected_run(config, monkeypatch, runtime):
    h = make_handler(config, operator(config))
    monkeypatch.setattr(jobs_api, 'get_job_runtime_state', lambda *_: runtime)
    monkeypatch.setattr(jobs_api, 'cancel_job', lambda *_a, **_k: pytest.fail('must not cancel'))
    with pytest.raises(auth.MobileError) as exc:
        api.control(h, 'cancel', {'job_id':api._id('photos'), 'run_id':'old','request_id':'b'*32})
    assert exc.value.api_status == 409


def test_cancel_current_run_and_runtime_projection(config, monkeypatch):
    h = make_handler(config, operator(config))
    live = {'running':True,'run_id':'current','cancel_allowed':True, 'phase':'borg_create',
            'borg_progress':{'original_size':123, 'percent':None, 'path':'/private'}}
    h._get_running = lambda: {'photos':live}
    monkeypatch.setattr(jobs_api, 'get_job_runtime_state', lambda *_: live)
    calls = []
    monkeypatch.setattr(jobs_api, 'cancel_job', lambda *a, **kw: calls.append((a,kw)) or {'cancellation_deferred':True})
    data = api.snapshot(h)['jobs'][0]
    assert data['can_cancel'] and not data['can_start']
    assert data['percent'] is None and data['processed_bytes'] == 123
    body = {'job_id':api._id('photos'), 'run_id':'current','request_id':'b'*32}
    assert api.control(h, 'cancel', body)['cancellation_deferred']
    assert api.control(h, 'cancel', body)['accepted']
    assert len(calls) == 1 and calls[0][0][2] == 'current'


def test_commands_keep_route_and_maintenance_guard(config):
    from test_mobile_auth import handler
    h = handler(config, 'POST', '/api/mobile/v1/jobs/start', {'Content-Type':'application/json'})
    assert not api.authorize(h, h.path, 'request')
    pair = auth.begin(config, 'Phone', 'ip')
    auth.approve(config, 'viewer', pair['user_code'])
    token = auth.exchange(config, pair['device_code'])['access_token']
    h.headers['Authorization'] = 'Bearer ' + token
    h._authorize_maintenance_request = lambda *_: False
    assert not api.authorize(h, h.path, 'request')
    h._authorize_maintenance_request = lambda *_: True
    assert api.authorize(h, h.path, 'request')
    h.command = 'GET'
    assert not api.authorize(h, h.path, 'request')


def test_utility_jobs_never_launch(config, monkeypatch):
    h = make_handler(config, operator(config))
    row = h._get_jobs()['jobs'][0]
    row['is_utility'] = True
    h._get_jobs = lambda: {'jobs':[row]}
    monkeypatch.setattr(job_launch, 'start_backup', lambda *_a, **_k: pytest.fail('must not launch'))
    with pytest.raises(auth.MobileError) as exc:
        api.control(h, 'start', {'job_id':api._id('photos'), 'request_id':'c'*32})
    assert exc.value.api_status == 403
