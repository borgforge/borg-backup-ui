"""Read-only collection, evidence semantics and access boundaries for #534."""
from __future__ import annotations

import http.client
import json
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for root in (ROOT, ROOT / 'api', ROOT / 'runtime', ROOT / 'runtime' / 'lib'):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from api import prometheus_api as metrics
from borg_backup_ui import BackupUIHandler, ThreadedHTTPServer
from job_fixtures import write_job


def samples(text, name, **labels):
    rows = []
    for line in text.splitlines():
        if not line.startswith(name + '{') and not line.startswith(name + ' '):
            continue
        if all(f'{key}={json.dumps(str(value), ensure_ascii=False)}' in line for key, value in labels.items()):
            rows.append(float(line.rsplit(' ', 1)[1]))
    return rows


@pytest.fixture
def installation(tmp_path):
    config = {'BACKUP_SCRIPTS_DIR': str(tmp_path), 'STATUS_DIR': str(tmp_path / 'status'),
              'RESTORE_TEST_STATUS_DIR': str(tmp_path / 'restore-status')}
    job = write_job(tmp_path, 'appdata_usb', name='Appdata "USB"\\disk\nLabel', repository_key='usb-repo',
                    restore_test_policy={'mode': 'scheduled', 'cron': '0 20 * * 0', 'validity_days': 30, 'level': 3})
    write_job(tmp_path, 'appdata_local', name='Never run', repository_key='local-repo')
    (tmp_path / 'status').mkdir()
    (tmp_path / 'restore-status').mkdir()
    (tmp_path / 'config' / 'backup.conf').write_text(
        f'STATUS_DIR={tmp_path}/status\nRESTORE_TEST_STATUS_DIR={tmp_path}/restore-status\n')
    now = datetime.now().replace(microsecond=0)
    success_at = now - timedelta(hours=1)
    for filename, state, stamp in [('success', 'success', success_at), ('failed', 'error', now)]:
        (tmp_path / 'status' / f'{filename}.status').write_text(json.dumps({
            'job_id': job['job_id'], 'status': state, 'timestamp': stamp.isoformat(),
            'duration_seconds': 123 if state == 'success' else 2,
            'archive_name': 'secret-archive-name' if state == 'success' else '',
            'original_size': 4096 if state == 'success' else 0,
            'compressed_size': 2048, 'deduplicated_size': 1024, 'files_count': 12,
            'error_message': 'password=must-not-export', 'log_file': '/private/path/secret.log',
        }))
    (tmp_path / 'config' / 'repositories.json').write_text(json.dumps({'repositories': [{
        'repository_key': 'usb-repo', 'display_name': 'USB repository', 'location': 'usb',
        'repository_stats': {'archives_count': 3, 'total_size': 8192, 'total_csize': 4096, 'unique_csize': 2048},
        'last_info_refresh_at': now.isoformat(), 'last_info_refresh_status': 'success',
        'passphrase_ref': '/private/passphrase', 'repo_uri': 'ssh://private-host/repo'
    }]}))
    (tmp_path / 'restore-status' / (job['job_id'] + '.test')).write_text(json.dumps({
        'job_id': job['job_id'], 'test_date': success_at.strftime('%Y-%m-%d %H:%M:%S'),
        'test_result': 'success', 'test_level': 3, 'test_duration_seconds': 44,
    }))
    (tmp_path / 'config' / 'schedules.json').write_text(json.dumps({job['job_id']: {'enabled': True, 'cron': '0 12 * * *'}}))
    metrics._cache.clear()
    return config, job, success_at


def test_settings_default_off_persistent_token_and_revocation(tmp_path):
    config = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    assert metrics.settings_status(config) == {'enabled': False, 'configured': False, 'cache_seconds': 60}
    assert not list(tmp_path.iterdir())
    first = metrics.update_settings(config, {'enabled': True})
    token = first['token']
    assert len(token) == 64
    assert metrics.settings_file(config).stat().st_mode & 0o777 == 0o600
    assert 'token' not in metrics.settings_status(config)
    metrics.update_settings(config, {'enabled': False})
    assert metrics.read_settings(config)['token'] == token
    assert 'token' not in metrics.update_settings(config, {'enabled': True})
    assert metrics.update_settings(config, {'rotate': True})['token'] != token
    assert metrics.update_settings(config, {'revoke': True})['configured'] is False
    assert metrics.settings_status(config)['enabled'] is False
    for body in ({'enabled': 'true'}, {'token': 'user-supplied'}, {'revoke': True, 'enabled': True}, {}):
        with pytest.raises(ValueError):
            metrics.update_settings(config, body)


def test_corrupt_settings_fail_closed(tmp_path):
    config = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    path = metrics.settings_file(config)
    path.parent.mkdir()
    for invalid in ('not json', '[]', 'null'):
        path.write_text(invalid)
        assert metrics.settings_status(config)['enabled'] is False


def test_collection_read_only_and_evidence_not_replaced_by_failure(installation, monkeypatch):
    config, job, success_at = installation
    root = Path(config['BACKUP_SCRIPTS_DIR'])
    before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    def forbidden(*_args, **_kwargs):
        pytest.fail('Metric collection attempted to start a process')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    text = metrics.collect_metrics(config, 'test-version')
    assert samples(text, 'bbui_collector_success') == [1, 1, 1, 1, 1]
    assert samples(text, 'bbui_backup_last_result', job_id=job['job_id'], result='error') == [1]
    assert samples(text, 'bbui_backup_last_success_timestamp_seconds', job_id=job['job_id']) == [success_at.timestamp()]
    assert samples(text, 'bbui_backup_last_duration_seconds', job_id=job['job_id']) == [2]
    assert samples(text, 'bbui_backup_archive_original_bytes', job_id=job['job_id']) == [4096]
    assert samples(text, 'bbui_backup_last_result', job_name='Never run', result='unknown') == [1]
    assert not samples(text, 'bbui_backup_last_success_timestamp_seconds', job_name='Never run')
    assert not samples(text, 'bbui_backup_archive_files', job_name='Never run')
    assert samples(text, 'bbui_repository_archives') == [3]
    assert samples(text, 'bbui_restore_verification_state', job_id=job['job_id'], state='verified') == [1]
    assert samples(text, 'bbui_restore_test_last_level', job_id=job['job_id']) == [3]
    assert samples(text, 'bbui_restore_test_next_run_timestamp_seconds', job_id=job['job_id'])[0] > datetime.now().timestamp()
    for secret in ('private-host', '/private/', 'must-not-export', 'secret-archive-name'):
        assert secret not in text
    assert 'job_name="Appdata \\"USB\\"\\\\disk\\nLabel"' in text
    after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    assert after == before


def test_failed_collector_omits_partial_data(installation):
    config, _, _ = installation
    path = Path(config['BACKUP_SCRIPTS_DIR']) / 'config' / 'repositories.json'
    path.write_text('{"repositories": [{"repository_key":"one"}, null]}')
    text = metrics.collect_metrics(config, 'test')
    assert samples(text, 'bbui_collector_success', collector='repositories') == [0]
    assert 'bbui_repository_info' not in text
    assert samples(text, 'bbui_collector_success', collector='backups') == [1]
    assert 'Traceback' not in text


def test_cache_ttl_serializes_concurrent_collection(installation, monkeypatch):
    config, _, _ = installation
    clock = [100.0]
    calls = []
    monkeypatch.setattr(metrics.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(metrics, 'collect_metrics', lambda *_: calls.append(1) or 'snapshot')
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(lambda _: metrics.cached_metrics(config, 'test'), range(16))) == ['snapshot'] * 16
    assert len(calls) == 1
    clock[0] += 59
    assert metrics.cached_metrics(config, 'test') == 'snapshot'
    assert len(calls) == 1
    clock[0] += 1
    metrics.cached_metrics(config, 'test')
    assert len(calls) == 2


@pytest.fixture
def http_server(installation, monkeypatch):
    import borg_backup_ui
    config, _, _ = installation
    monkeypatch.setattr(borg_backup_ui, '_log', lambda *_: None)
    class Handler(BackupUIHandler):
        def _auth_store_failure(self): return ''
        def _ui_auth_enabled(self): return False
        def _get_api_token(self): return 'admin-test-token'
        def _get_current_role(self): return 'admin'
        def _security_audit(self, *_args, **_kwargs): pass
    Handler.config = config
    server = ThreadedHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, token='', method='GET', body=None):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        headers = {'Origin': f'http://127.0.0.1:{server.server_port}'}
        if token: headers['Authorization'] = 'Bearer ' + token
        if body is not None: headers['Content-Type'] = 'application/json'
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read().decode()
        conn.close()
        return result
    yield config, request
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_http_auth_lifecycle_and_scope(http_server):
    config, request = http_server
    assert request('/metrics')[0] == 404
    assert request('/api/settings/prometheus', method='POST', body={'enabled': True})[0] == 401
    code, headers, body = request('/api/settings/prometheus', 'admin-test-token', 'POST', {'enabled': True})
    assert code == 200
    assert headers['Cache-Control'] == 'no-store'
    token = json.loads(body)['token']
    for invalid in ('', 'bad', 'admin-test-token', 'invalid-é'):
        assert request('/metrics', invalid)[0] == 401
    for path in ('/api/status', '/api/widget/summary'):
        assert request(path, token)[0] == 401
    assert request('/api/settings/prometheus', token, 'POST', {'enabled': False})[0] == 401
    code, headers, text = request('/metrics', token)
    assert code == 200
    assert headers['Content-Type'].startswith('text/plain; version=0.0.4')
    assert text.endswith('\n')
    assert samples(text, 'bbui_collector_success') == [1, 1, 1, 1, 1]
    assert token not in text
    replacement = json.loads(request('/api/settings/prometheus', 'admin-test-token', 'POST', {'rotate': True})[2])['token']
    assert request('/metrics', token)[0] == 401
    assert request('/metrics', replacement)[0] == 200
    request('/api/settings/prometheus', 'admin-test-token', 'POST', {'enabled': False})
    assert request('/metrics', replacement)[0] == 404
    request('/api/settings/prometheus', 'admin-test-token', 'POST', {'enabled': True})
    assert request('/metrics', replacement)[0] == 200
    request('/api/settings/prometheus', 'admin-test-token', 'POST', {'revoke': True})
    assert request('/metrics', replacement)[0] == 404
    assert metrics.read_settings(config)['token'] == ''


def test_disabled_endpoint_does_not_collect(http_server, monkeypatch):
    _, request = http_server
    monkeypatch.setattr(metrics, 'cached_metrics', lambda *_: pytest.fail('Disabled exporter collected data'))
    assert request('/metrics')[0] == 404


def test_maintenance_mode_blocks_metrics(http_server):
    from api.startup_state import set_startup_state
    config, request = http_server
    token = metrics.update_settings(config, {'enabled': True})['token']
    set_startup_state(config, {'mode': 'maintenance', 'blocking': True})
    assert request('/metrics', token)[0] == 503
    assert request('/api/settings/prometheus', 'admin-test-token', 'POST', {'enabled': False})[0] == 503


def test_non_admin_session_cannot_change_integration(installation):
    handler = BackupUIHandler.__new__(BackupUIHandler)
    handler.config = installation[0]
    handler.command = 'POST'
    handler._auth_store_failure = lambda: ''
    handler._has_valid_api_token_header = lambda: False
    handler._is_same_origin_request = lambda: True
    handler._is_api_authorized = lambda: True
    handler._get_current_role = lambda: 'viewer'
    failures = []
    handler._send_api_error = lambda *args, **kwargs: failures.append(args)
    assert handler._authorize_api_request('/api/settings/prometheus', 'test') is False
    assert failures[-1][:2] == (403, 'forbidden')


def test_skipped_run_preserves_success_and_expired_restore_is_visible(installation):
    config, job, success_at = installation
    root = Path(config['BACKUP_SCRIPTS_DIR'])
    failed = root / 'status/failed.status'
    row = json.loads(failed.read_text())
    row['status'] = 'skipped'
    failed.write_text(json.dumps(row))
    report = root / 'restore-status' / (job['job_id'] + '.test')
    row = json.loads(report.read_text())
    row['test_date'] = (datetime.now() - timedelta(days=40)).strftime('%Y-%m-%d %H:%M:%S')
    report.write_text(json.dumps(row))
    text = metrics.collect_metrics(config, 'test')
    assert samples(text, 'bbui_backup_last_result', job_id=job['job_id'], result='skipped') == [1]
    assert samples(text, 'bbui_backup_last_success_timestamp_seconds', job_id=job['job_id']) == [success_at.timestamp()]
    assert samples(text, 'bbui_restore_verification_state', job_id=job['job_id'], state='stale') == [1]
    assert samples(text, 'bbui_restore_test_overdue', job_id=job['job_id']) == [1]
    expiry = samples(text, 'bbui_restore_test_valid_until_timestamp_seconds', job_id=job['job_id'])[0]
    next_run = samples(text, 'bbui_restore_test_next_run_timestamp_seconds', job_id=job['job_id'])[0]
    assert expiry < datetime.now().timestamp() < next_run


def test_dashboard_queries_reference_exported_families(installation):
    config, _, _ = installation
    dashboard = json.loads((ROOT / 'ui/integrations/borg-backup-ui-grafana.json').read_text())
    families = set(re.findall(r'^# TYPE (\w+)', metrics.collect_metrics(config, 'test'), re.M))
    def panel_queries(panels):
        for panel in panels:
            yield from (target['expr'] for target in panel.get('targets', []))
            yield from panel_queries(panel.get('panels', []))
    variables = dashboard['templating']['list']
    queries = list(panel_queries(dashboard['panels']))
    for variable in variables:
        query = variable.get('query', '')
        queries.append(query['query'] if isinstance(query, dict) else query)
    for query in queries:
        assert set(re.findall(r'\bbbui_\w+', query)) <= families
    assert {v['name'] for v in variables if not v.get('hide')} == {'instance', 'location', 'repository', 'backup_job'}


def test_dashboard_download_serves_importable_template(http_server):
    _, request = http_server
    code, headers, body = request('/ui/integrations/borg-backup-ui-grafana.json', 'admin-test-token')
    assert code == 200
    assert 'application/json' in headers['Content-Type']
    dashboard = json.loads(body)
    assert dashboard == json.loads((ROOT / 'ui/integrations/borg-backup-ui-grafana.json').read_text())
    assert dashboard['uid'] == 'borg-backup-ui'
    assert dashboard['id'] is None
    assert dashboard['__inputs'][0]['name'] == 'DS_PROMETHEUS'


def test_ui_translations_complete():
    de = json.loads((ROOT / 'ui/i18n/de.json').read_text())['settings']['prometheus']
    en = json.loads((ROOT / 'ui/i18n/en.json').read_text())['settings']['prometheus']
    assert set(de) == set(en)
    assert all(de.values()) and all(en.values())
