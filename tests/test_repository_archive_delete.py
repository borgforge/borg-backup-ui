"""Admin-only deletion of a single archive (#507)."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / 'api'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import archive_browser
import repositories_api as repos
from borg_backup_ui import BackupUIHandler
from check_api import CheckManager
from jobs_api import JobManager, is_resource_active
from test_repository_archive_browser import _repository_config
from wizard_runner import ResourceLockSet

ARCHIVE_ID = 'a' * 64
REPO_ID = 'b' * 64
ACTOR = {'actor': 'admin-user', 'actor_role': 'admin', 'auth_method': 'session'}


def _payload(name='backup-one'):
    return {'repository_key': 'repo_test', 'archive': name, 'expected_archive_id': ARCHIVE_ID,
            'expected_repository_id': REPO_ID, 'confirmed': True}


@pytest.fixture
def context(tmp_path, monkeypatch):
    config, repo = _repository_config(tmp_path)
    config['BORG_RESOURCE_LOCK_DIR'] = str(tmp_path / 'locks')
    monkeypatch.setattr(CheckManager, 'get', lambda: SimpleNamespace(get_state=lambda: {}))
    monkeypatch.setattr(JobManager, 'get', lambda: SimpleNamespace(get_state=lambda *_: {}))
    monkeypatch.setattr(repos, '_borg_list', lambda *_: {
        'repository': {'id': REPO_ID}, 'archives': [{'name': 'backup-one', 'id': ARCHIVE_ID}]})
    monkeypatch.setattr(repos, 'refresh_repository_info', lambda *_: {})
    archive_browser._CACHE.clear()
    yield config, repo
    archive_browser._CACHE.clear()


def test_exact_archive_deleted_under_resource_lock_and_audited(context, tmp_path, monkeypatch):
    config, repo = context
    history = tmp_path / 'old-run.status'
    history.write_text('historical backup result')
    before = repos.repositories_file(config).read_bytes()
    archive_browser._CACHE[(str(repo), 'backup-one')] = {'index': {}}
    calls = []

    def run(command, **kwargs):
        assert is_resource_active(config, f'repo:{repo}')
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(repos.subprocess, 'run', run)
    result = repos.delete_repository_archive(config, _payload(), audit_context=ACTOR)
    assert result['ok'] is True
    assert calls == [['borg', 'delete', '--lock-wait', '1', '--', f'{repo}::backup-one']]
    assert not is_resource_active(config, f'repo:{repo}')
    assert (str(repo), 'backup-one') not in archive_browser._CACHE
    assert repos.repositories_file(config).read_bytes() == before
    assert history.read_text() == 'historical backup result'
    audit = [json.loads(line) for line in repos._repository_lifecycle_audit_file(config).read_text().splitlines()]
    assert [row['status'] for row in audit] == ['started', 'success']
    assert all(row['actor'] == 'admin-user' and row['details']['archive_id'] == ARCHIVE_ID for row in audit)


@pytest.mark.parametrize('change', [
    {'archive': ''}, {'archive': 'bad::name'}, {'archive': 'bad\nname'},
    {'expected_archive_id': ''}, {'expected_repository_id': ''}, {'confirmed': False}, {'confirmed': 'true'},
])
def test_incomplete_confirmation_never_runs_borg(context, monkeypatch, change):
    config, _ = context
    monkeypatch.setattr(repos.subprocess, 'run', lambda *_a, **_k: pytest.fail('Borg must not run'))
    with pytest.raises(ValueError):
        repos.delete_repository_archive(config, {**_payload(), **change})


@pytest.mark.parametrize('change', [
    {'archive': 'missing'}, {'expected_archive_id': 'c' * 64}, {'expected_repository_id': 'c' * 64},
])
def test_changed_archive_or_repository_cannot_be_deleted(context, monkeypatch, change):
    config, repo = context
    monkeypatch.setattr(repos.subprocess, 'run', lambda *_a, **_k: pytest.fail('Delete must not run'))
    with pytest.raises(repos.RepositoryLifecycleConflict) as error:
        repos.delete_repository_archive(config, {**_payload(), **change})
    assert error.value.code == 'repository_archive_changed'
    assert not is_resource_active(config, f'repo:{repo}')


@pytest.mark.parametrize('operation', ['backup', 'restore', 'delete_archive'])
def test_busy_repository_cannot_be_deleted(context, operation):
    config, repo = context
    lock = ResourceLockSet(Path(config['BORG_RESOURCE_LOCK_DIR']), 'existing', operation=operation)
    assert lock.acquire([f'repo:{repo}'])[0]
    try:
        with pytest.raises(repos.RepositoryBusyError):
            repos.delete_repository_archive(config, _payload())
        assert is_resource_active(config, f'repo:{repo}')
    finally:
        lock.release()


@pytest.mark.parametrize('kind', ['maintenance', 'restore-test'])
def test_active_maintenance_and_restore_test_block_delete(context, monkeypatch, kind):
    config, _ = context
    if kind == 'maintenance':
        monkeypatch.setattr(CheckManager, 'get', lambda: SimpleNamespace(get_state=lambda: {'running': True, 'target_key': 'repo_test'}))
    else:
        monkeypatch.setattr(JobManager, 'get', lambda: SimpleNamespace(get_state=lambda *_: {'running': True}))
    with pytest.raises(repos.RepositoryBusyError):
        repos.delete_repository_archive(config, _payload())


@pytest.mark.parametrize('failure', ['error', 'timeout', 'locked'])
def test_borg_failure_releases_lock_invalidates_cache_and_is_audited(context, monkeypatch, failure):
    config, repo = context
    archive_browser._CACHE[(str(repo), 'backup-one')] = {'index': {}}
    def run(*args, **kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(args[0], 3600)
        return SimpleNamespace(returncode=2, stdout='', stderr='Failed to create/acquire the lock' if failure == 'locked' else 'I/O failure')
    monkeypatch.setattr(repos.subprocess, 'run', run)
    with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
        repos.delete_repository_archive(config, _payload(), audit_context=ACTOR)
    assert not is_resource_active(config, f'repo:{repo}')
    assert (str(repo), 'backup-one') not in archive_browser._CACHE
    audit = [json.loads(line) for line in repos._repository_lifecycle_audit_file(config).read_text().splitlines()]
    assert audit[-1]['status'] == 'failed'
    assert not any(row['status'] == 'success' for row in audit)


def test_statistics_failure_does_not_report_successful_delete_as_failed(context, monkeypatch):
    config, _ = context
    monkeypatch.setattr(repos.subprocess, 'run', lambda *_a, **_k: SimpleNamespace(returncode=0, stdout='', stderr=''))
    def refresh(*_):
        raise RuntimeError('Repository offline')
    monkeypatch.setattr(repos, 'refresh_repository_info', refresh)
    result = repos.delete_repository_archive(config, _payload())
    assert result['ok'] and result['refresh_warning'] == 'Repository offline'


@pytest.mark.parametrize('session', [None, {}, {'username': 'reader', 'role': 'viewer'},
                                     {'username': 'operator', 'role': 'operator'}, {'role': 'admin'}])
def test_direct_delete_requires_admin_user_session_even_with_api_token(monkeypatch, session):
    handler = BackupUIHandler.__new__(BackupUIHandler)
    handler._get_current_session_meta = lambda: session
    handler._get_current_role = lambda: 'admin'
    handler._has_valid_api_token_header = lambda: True
    handler._read_json_body = lambda: pytest.fail('Must reject before reading the body')
    with pytest.raises(PermissionError):
        handler._delete_repository_archive()


def test_admin_handler_dispatch_and_capability(context, monkeypatch):
    config, _ = context
    handler = BackupUIHandler.__new__(BackupUIHandler)
    handler.config = config
    handler._get_current_session_meta = lambda: {'username': 'admin-user', 'role': 'admin'}
    handler._read_json_body = _payload
    handler._repository_audit_context = lambda *_: ACTOR
    monkeypatch.setattr(repos, 'delete_repository_archive', lambda c, p, **kw: {'ok': c == config and p == _payload() and kw['audit_context'] == ACTOR})
    assert handler._delete_repository_archive() == {'ok': True}
    assert handler._required_role_for_request('/api/repositories/archive', 'DELETE') == 'admin'
    assert handler._get_repository_archives('repository_key=repo_test')['can_delete'] is True
    handler._get_current_session_meta = lambda: None
    assert handler._get_repository_archives('repository_key=repo_test')['can_delete'] is False


def test_cache_invalidation_during_load_does_not_restore_deleted_index(monkeypatch):
    def run(*_a, **_k):
        archive_browser.invalidate_archive_index('/repo', 'old')
        return SimpleNamespace(returncode=0, stdout='{"path":"file.txt"}', stderr='')
    monkeypatch.setattr(archive_browser.subprocess, 'run', run)
    archive_browser.build_archive_index('/repo', 'old', {})
    assert ('/repo', 'old') not in archive_browser._CACHE


def test_real_borg_deletes_only_selected_archive_and_preserves_restore(tmp_path, monkeypatch):
    borg = shutil.which('borg')
    if not borg:
        pytest.skip('Borg binary is required for the archive deletion integration test')
    config, repo = _repository_config(tmp_path)
    config.update(BORG_RESOURCE_LOCK_DIR=str(tmp_path / 'locks'), GLOBAL_DATA_DIR=str(tmp_path / 'data'))
    monkeypatch.setenv('BORG_BASE_DIR', str(tmp_path / 'borg-home'))
    monkeypatch.setenv('BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK', 'yes')
    monkeypatch.setattr(CheckManager, 'get', lambda: SimpleNamespace(get_state=lambda: {}))
    monkeypatch.setattr(JobManager, 'get', lambda: SimpleNamespace(get_state=lambda *_: {}))
    source = tmp_path / 'hello.txt'
    source.write_text('unchanged content shared by both archives')
    def borg_run(*args):
        return subprocess.run([borg, *args], cwd=tmp_path, check=True, capture_output=True, text=True)
    borg_run('init', '--encryption=none', str(repo))
    for name in ['backup-{literal}', 'backup-keep']:
        target = f'{repo}::{name}'.replace('{', '{{').replace('}', '}}')
        borg_run('create', target, 'hello.txt')
    listed = repos.get_repository_archives(config, 'repo_test')
    archive = next(row for row in listed['archives'] if row['name'] == 'backup-{literal}')
    archive_browser._CACHE[(str(repo), archive['name'])] = {'index': {}}
    result = repos.delete_repository_archive(config, {
        **_payload(archive['name']), 'expected_archive_id': archive['id'], 'expected_repository_id': listed['repository_id'],
    }, audit_context=ACTOR)
    assert result['ok'] and 'refresh_warning' not in result
    assert (str(repo), archive['name']) not in archive_browser._CACHE
    assert [row['name'] for row in repos.get_repository_archives(config, 'repo_test')['archives']] == ['backup-keep']
    assert borg_run('extract', '--stdout', f'{repo}::backup-keep', 'hello.txt').stdout == source.read_text()
    assert repos.read_repository_store(config)['repositories'][0]['repository_stats']['archives_count'] == 1


@pytest.mark.parametrize('role,session,expected_status', [
    ('admin', {'username': 'admin-user', 'role': 'admin'}, 200),
    ('operator', {'username': 'operator-user', 'role': 'operator'}, 403),
    ('viewer', {'username': 'viewer-user', 'role': 'viewer'}, 403),
    ('admin', None, 403),  # Token-only automation is not an admin user.
])
def test_delete_http_route_enforces_role_and_session(context, monkeypatch, role, session, expected_status):
    from io import BytesIO
    config, _ = context
    handler = BackupUIHandler.__new__(BackupUIHandler)
    handler.config = config
    handler.path = '/api/repositories/archive'
    handler.command = 'DELETE'
    handler.client_address = ('127.0.0.1', 10000)
    handler.headers = {'Host': 'localhost', 'Origin': 'http://localhost'}
    handler.wfile = BytesIO()
    handler._auth_store_failure = lambda: None
    handler._is_api_authorized = lambda: True
    handler._has_valid_api_token_header = lambda: session is None
    handler._get_current_role = lambda: role
    handler._get_current_session_meta = lambda: session
    handler._read_json_body = _payload
    handler._repository_audit_context = lambda *_: ACTOR
    handler._should_log_api_success = lambda *_: False
    handler._extract_request_context = lambda: {}
    status = []
    handler.send_response = status.append
    handler.send_header = lambda *_: None
    handler.end_headers = lambda: None
    handler._send_api_error = lambda code, *_a, **_k: status.append(code)
    calls = []
    monkeypatch.setattr(repos, 'delete_repository_archive', lambda *_a, **_k: calls.append('delete') or {'ok': True})
    handler.do_DELETE()
    assert status == [expected_status]
    assert calls == (['delete'] if expected_status == 200 else [])
