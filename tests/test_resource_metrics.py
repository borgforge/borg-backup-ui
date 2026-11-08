"""Read-only resource telemetry: accounting, ownership, limits and HTTP access."""
import http.client
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import threading

import pytest
import resource_metrics as metrics


def test_host_cpu_deltas_exclude_guest_double_counting_and_iowait(tmp_path):
    (tmp_path / 'stat').write_text('cpu 100 10 20 300 50 5 5 10 90 5\ncpu0 0\n')
    (tmp_path / 'meminfo').write_text('MemTotal: 32768 kB\nMemAvailable: 8192 kB\nMemFree: 1024 kB\n')
    first = metrics.host_counters(tmp_path)
    assert first['ticks'] == 500
    assert first['memory_available_bytes'] == 8192 * 1024
    assert metrics.cpu_percent(None, first) is None
    assert metrics.cpu_percent(first, first) is None
    assert metrics.cpu_percent(first, dict(first, ticks=600, idle=400)) == 50
    assert metrics.cpu_percent(first, dict(first, ticks=1)) is None
    (tmp_path / 'meminfo').write_text('MemTotal: 32768 kB\n')
    with pytest.raises(KeyError):
        metrics.host_counters(tmp_path)


def make_group(root, proc, suffix, parent=42):
    group = root / ('borg-backup-ui-restore-' + suffix)
    group.mkdir()
    for name, value in {'cgroup.procs': '100\n101\n', 'cpu.stat': 'usage_usec 1000000\n',
                        'memory.current': '1073741824', 'memory.max': '2147483648'}.items():
        (group / name).write_text(value)
    (proc / '100').mkdir(exist_ok=True)
    (proc / '100' / 'status').write_text(f'Name: keeper\nPPid:\t{parent}\n')
    return group


def test_group_matches_owning_supervisor_not_waiting_test(tmp_path):
    root = tmp_path / 'groups'; root.mkdir()
    proc = tmp_path / 'proc'; proc.mkdir()
    group = make_group(root, proc, 'one')
    runs = [{'pid': 42, 'operation': 'restore_test', 'job_key': 'appdata', 'run_id': 'run-1'},
            {'pid': 43, 'operation': 'restore_test', 'job_key': 'waiting', 'run_id': 'run-2'}]
    result = metrics.protected_groups(root, proc, runs)
    assert len(result) == 1
    assert result[0]['job_key'] == 'appdata'
    assert result[0]['memory_limit_bytes'] == 2 * 1024**3
    assert metrics.protected_groups(root, proc, runs[1:]) == []
    assert metrics.protected_groups(root, proc, [dict(runs[0], operation='backup')]) == []
    (group / 'memory.current').unlink()
    assert metrics.protected_groups(root, proc, runs) == []


@pytest.fixture
def sampler(monkeypatch, tmp_path):
    import jobs_api, config_api, restore_test_resources
    clock = [1000.0]
    monkeypatch.setattr(metrics.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(metrics.time, 'time', lambda: clock[0] + 10000)
    monkeypatch.setattr(metrics.os, 'cpu_count', lambda: 4)
    runs = [{'pid': 42, 'operation': 'restore_test', 'job_key': 'appdata', 'run_id': 'one'}]
    monkeypatch.setattr(jobs_api, 'active_resource_locks', lambda _: runs + runs)
    monkeypatch.setattr(config_api, 'read_expanded_conf', lambda _: {'RESTORE_TEST_HOST_RESERVE_MIB': '1024'})
    monkeypatch.setattr(restore_test_resources, 'cgroup_root', lambda: tmp_path)
    host = {'ticks': 100, 'idle': 50, 'memory_total_bytes': 32 * 1024**3, 'memory_available_bytes': 5 * 1024**3}
    monkeypatch.setattr(metrics, 'host_counters', lambda _: host.copy())
    group = {'id': 'owned', 'job_key': 'appdata', 'run_id': 'one', 'usage_usec': 1000000,
             'memory_bytes': 1024**3, 'memory_limit_bytes': 2 * 1024**3}
    monkeypatch.setattr(metrics, 'protected_groups', lambda *_: [group.copy()])
    return metrics.ResourceSampler({}), clock, host, group, runs


def test_sample_normalizes_cpu_and_deduplicates_locks(sampler):
    service, clock, host, group, runs = sampler
    initial = service.sample()
    assert initial['host']['cpu_percent'] is None
    assert initial['protected_tests'][0]['cpu_percent'] is None
    assert len(initial['runs']) == 1
    assert 'pid' not in initial['runs'][0]
    clock[0] += 2
    host.update(ticks=300, idle=150)
    group['usage_usec'] += 4000000  # Two cores for two seconds, four host cores.
    current = service.sample()
    assert current['host']['cpu_percent'] == 50
    assert current['protected_tests'][0]['cpu_percent'] == 50
    assert current['configured_reserve_bytes'] == 1024**3
    assert current['interval_seconds'] == 1
    group['id'] = 'new-run'
    clock[0] += 1
    assert service.sample()['protected_tests'][0]['cpu_percent'] is None
    runs.clear()
    current = service.sample()
    assert current['protected_tests'] == []
    assert current['interval_seconds'] == 10


def test_missing_measurements_stale_data_and_history_bound(sampler, monkeypatch):
    service, clock, _, _, _ = sampler
    for _ in range(1000):
        service.sample()
        clock[0] += 1
    snapshot = service.snapshot()
    assert len(service.history) <= 600
    assert len(snapshot['history']) <= 121
    assert snapshot['history'][0]['timestamp'] >= snapshot['timestamp'] - 600
    snapshot['host']['cpu_percent'] = 999
    assert service.snapshot()['host']['cpu_percent'] != 999
    clock[0] += 6
    assert service.snapshot()['stale'] is True
    def missing(_): raise FileNotFoundError()
    monkeypatch.setattr(metrics, 'host_counters', missing)
    current = service.sample()
    assert current['host']['memory_available_bytes'] is None
    assert current['host']['cpu_percent'] is None
    assert len(current['protected_tests']) == 1
    assert service.snapshot()['stale'] is False


def test_shared_sampler_starts_once_for_concurrent_clients(monkeypatch):
    starts = []
    monkeypatch.setattr(metrics, '_sampler', None)
    monkeypatch.setattr(metrics.ResourceSampler, 'start', lambda self: starts.append(1))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: metrics.get_resource_metrics({}), range(16)))
    assert len(starts) == 1
    assert all(result['available'] is False for result in results)


def test_authenticated_endpoint_and_shipped_dashboard(monkeypatch, tmp_path):
    from borg_backup_ui import BackupUIHandler, ThreadedHTTPServer
    import borg_backup_ui
    monkeypatch.setattr(borg_backup_ui, '_log', lambda *_: None)
    monkeypatch.setattr(metrics, 'get_resource_metrics', lambda _: {'available': True, 'host': {'cpu_percent': 12.5}})
    class Handler(BackupUIHandler):
        def _auth_store_failure(self): return ''
        def _ui_auth_enabled(self): return False
        def _get_api_token(self): return 'resource-test-token'
        def _get_current_role(self): return 'viewer'
        def _security_audit(self, *_args, **_kwargs): pass
    Handler.config = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    handler = Handler.__new__(Handler)
    assert handler._required_role_for_request('/api/system-resources', 'GET') == 'viewer'
    server = ThreadedHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        for token, expected in [('', 401), ('resource-test-token', 200)]:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
            conn.request('GET', '/api/system-resources', headers={'Authorization': 'Bearer ' + token} if token else {})
            response = conn.getresponse(); body = response.read()
            assert response.status == expected
            if token: assert json.loads(body)['host']['cpu_percent'] == 12.5
            conn.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_resource_monitor_browser_behaviour():
    subprocess.run(['node', '--test', 'tests/resource_monitor.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)


def test_queue_states_do_not_depend_on_cgroup_measurements(sampler, monkeypatch):
    service, _, _, _, runs = sampler
    runs[0]["activity_state"] = "running"
    for index in range(3):
        runs.append({"pid": 50 + index, "operation": "restore_test", "job_key": f"waiting-{index}",
                     "run_id": str(index), "activity_state": "waiting"})
    snapshot = service.sample()
    assert [run["activity_state"] for run in snapshot["runs"]] == ["running", "waiting", "waiting", "waiting"]
    assert len(snapshot["protected_tests"]) == 1
    monkeypatch.setattr(metrics, "protected_groups", lambda *_: [])
    runs[1]["activity_state"] = "running"
    del runs[2]["activity_state"]
    snapshot = service.sample()
    assert [run["activity_state"] for run in snapshot["runs"]] == ["running", "running", "unknown", "waiting"]
    assert not snapshot["protected_tests"]
