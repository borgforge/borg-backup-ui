"""Complete bounded mobile logs: no missing UTF-8, no arbitrary source reads (#746)."""
from datetime import datetime
import pytest
from test_mobile_auth import config  # noqa: F401
from test_mobile_details import log_handler
import mobile_api as api
import mobile_auth as auth
import mobile_logs
import mobile_log_window as windows
import jobs_api
import config_api


def retained(config, tmp_path, monkeypatch, text):
    """Create one authorized synthetic retained event and its confined file."""
    h, session = log_handler(config)
    auth.log_permission(config, 'viewer', session['id'], True)
    path = tmp_path / 'logs' / 'run.log'
    path.parent.mkdir()
    path.write_bytes(text.encode())
    monkeypatch.setattr(config_api, 'read_expanded_conf', lambda _: {'GLOBAL_LOG_DIR': str(path.parent)})
    row = {'job_key': 'photos', 'timestamp': '2026-11-17T10:00:00Z', 'run_id': 'run-12345', 'log_file': str(path)}
    h._get_history = lambda _: {'entries': [row]}
    event = api._id('photos' + api._stamp(row['timestamp']) + 'run-12345')
    return h, session, path, {'event_id': event}


def pin(row):
    """Build client source/truncation guards from the preceding response."""
    return {'file_id': row['file_id'], 'known_size': row['size']}


def test_complete_utf8_forward_and_backward(config, tmp_path, monkeypatch):
    text = 'Beginning\r\n' + 'ä😀 long line without newline ' * 10000 + '\nFinal\n'
    h, _, path, body = retained(config, tmp_path, monkeypatch, text)
    row = mobile_logs.read_log(h, {**body, 'start': 0})
    forward = row['text']
    while row['end'] < row['size']:
        next_row = mobile_logs.read_log(h, {**body, **pin(row), 'start': row['end']})
        assert next_row['start'] == row['end'] and next_row['end'] > next_row['start']
        assert len(next_row['text'].encode()) <= windows.FILE_WINDOW
        forward += next_row['text']
        row = next_row
    assert forward == text and row['size'] == path.stat().st_size
    row = mobile_logs.read_log(h, body)
    backward = row['text']
    while row['start']:
        previous = mobile_logs.read_log(h, {**body, **pin(row), 'before': row['start']})
        assert previous['end'] == row['start']
        backward = previous['text'] + backward
        row = previous
    assert backward == text


def test_source_replacement_truncation_and_revocation(config, tmp_path, monkeypatch):
    h, session, path, body = retained(config, tmp_path, monkeypatch, 'original\n' * 10000)
    row = mobile_logs.read_log(h, body)
    replacement = path.with_suffix('.txt'); replacement.write_text('replacement\n' * 10000)
    replacement.replace(path)
    with pytest.raises(auth.MobileError) as exc:
        mobile_logs.read_log(h, {**body, **pin(row), 'start': 0})
    assert exc.value.api_status == 409
    row = mobile_logs.read_log(h, body)
    path.write_text('short\n')
    with pytest.raises(auth.MobileError) as exc:
        mobile_logs.read_log(h, {**body, **pin(row), 'start': 0})
    assert exc.value.api_status == 409
    row = mobile_logs.read_log(h, body)
    auth.log_permission(config, 'viewer', session['id'], False)
    with pytest.raises(auth.MobileError) as exc:
        mobile_logs.read_log(h, {**body, **pin(row), 'start': 0})
    assert exc.value.api_status == 403


def test_memory_complete_and_growth_without_full_snapshot():
    manager = jobs_api.JobManager()
    state = jobs_api._JobState(None, datetime.now(), 'exact-run')
    state.lines = ['start', 'x😀' * 50000, 'last']
    manager._states['photos'] = state
    row = manager.output_window('photos', 'exact-run', {'start': 0})
    text = row['text']
    while row['end'] < row['size']:
        row = manager.output_window('photos', 'exact-run', {**pin(row), 'start': row['end']})
        assert len(row['text']) <= windows.TEXT_WINDOW
        text += row['text']
    assert text == '\n'.join(state.lines) + '\n'
    state.lines.append('new')
    next_row = manager.output_window('photos', 'exact-run', {**pin(row), 'start': row['end']})
    assert next_row['text'] == 'new\n' and next_row['running']
    assert manager.output_window('photos', 'other-run', {}) is None


@pytest.mark.parametrize('query', [{'start': True}, {'before': -1}, {'start': 2**53},
                                  {'start': 0, 'before': 1}, {'file_id': '../path', 'known_size': 1},
                                  {'known_size': 0}])
def test_invalid_navigation(query):
    with pytest.raises(auth.MobileError) as exc:
        windows.options(query)
    assert exc.value.api_status == 400


def test_growing_partial_unicode_is_not_lost(tmp_path):
    path = tmp_path / 'utf8.log'; path.write_bytes(b'A\xf0\x9f')
    with path.open('rb') as handle:
        row = windows.file_window(handle, {'start': 0}, running=True)
    assert row['text'] == 'A' and row['end'] == 1
    with path.open('ab') as handle: handle.write(b'\x98\x80\n')
    with path.open('rb') as handle:
        next_row = windows.file_window(handle, {**pin(row), 'start': row['end']}, running=False)
    assert next_row['text'] == '😀\n'


def test_resources_do_not_read_restore_or_group_services(config, monkeypatch):
    import mobile_monitoring as monitoring
    h, _ = log_handler(config)
    monkeypatch.setattr(monitoring, 'resources', lambda _: {'cpu_percent': 12})
    def unexpected(_): raise AssertionError('Composite monitoring must not run')
    monkeypatch.setattr(monitoring, 'restore_tests', unexpected)
    monkeypatch.setattr(monitoring, 'groups', unexpected)
    assert monitoring.handle(h, 'resources', {}) == {'cpu_percent': 12}
    assert '/api/mobile/v1/resources' in api.ROUTES['GET']
    def revoked(_):
        auth.revoke(config, 'viewer', h._mobile_session['id'])
        return {'cpu_percent': 12}
    monkeypatch.setattr(monitoring, 'resources', revoked)
    with pytest.raises(auth.MobileError) as exc: monitoring.handle(h, 'resources', {})
    assert exc.value.api_status == 401


def test_active_capture_keeps_identity_after_retained_copy(config, tmp_path, monkeypatch):
    from contextlib import contextmanager
    import activity_log
    import shutil
    h, session = log_handler(config)
    auth.log_permission(config, 'viewer', session['id'], True)
    monkeypatch.setattr(jobs_api.JobManager, 'output_window', lambda *_: None)
    monkeypatch.setattr(jobs_api, 'get_job_runtime_state', lambda *_: {'run_id': 'run-12345', 'file_activity': True})
    active = tmp_path / 'active.log'; active.write_text('first\n' * 20000)
    saved = tmp_path / 'saved.log'
    identity = lambda p: f'{p.stat().st_dev}:{p.stat().st_ino}'
    capture = {'active_file': str(active), 'active_file_id': identity(active)}
    current = [active, True]
    @contextmanager
    def opened(*_):
        with current[0].open('rb') as handle:
            yield current[0], {'running': current[1], 'capture': capture}, handle
    monkeypatch.setattr(activity_log, 'open_activity_run', opened)
    body = {'job_id': api._id('photos'), 'run_id': 'run-12345', 'start': 0}
    row = mobile_logs.read_log(h, body)
    shutil.copyfile(active, saved)
    capture['retained_file_id'] = identity(saved)
    current[:] = [saved, False]
    next_row = mobile_logs.read_log(h, {**body, **pin(row), 'start': row['end']})
    assert next_row['file_id'] == row['file_id'] and not next_row['running']
    capture['retained_file_id'] = 'wrong'
    with pytest.raises(auth.MobileError) as exc: mobile_logs.read_log(h, body)
    assert exc.value.api_status == 409
