"""Restore-test cancellation identities, cleanup and retained evidence (#605)."""
import fcntl
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from borg_backup_ui import BackupUIHandler, ApiConflictError
import job_control
import jobs_api
import restore_tests_api
from restore_test_io import run_borg
import restore_test_resources as resources
from test_restore_test_memory import borg_env, guard_fakes
from test_restore_test_scheduling import _tester


@pytest.fixture
def controlled_runtime(tmp_path, monkeypatch):
    root = tmp_path / 'control'
    read = job_control.read_control_state
    cancel = job_control.request_cancel
    monkeypatch.setattr(job_control, 'read_control_state', lambda run_id, *_: read(run_id, root))
    monkeypatch.setattr(job_control, 'request_cancel', lambda key, run_id, **kwargs: cancel(key, run_id, root=root, **kwargs))
    states, locks = {}, []
    monkeypatch.setattr(jobs_api.JobManager, 'get', lambda: SimpleNamespace(get_all_states=lambda: states))
    monkeypatch.setattr(jobs_api, 'active_resource_locks', lambda _config: locks)
    return root, states, locks


def test_cancel_is_idempotent_and_rejects_stale_or_other_job_runs(controlled_runtime):
    root, states, _ = controlled_runtime
    control = job_control.JobControl('restore_test_alpha', 'run-alpha', root)
    control.update_phase('restore_test', cancel_allowed=True)
    states['restore_test_alpha'] = {'running': True, 'run_id': 'run-alpha'}
    runtime = restore_tests_api.restore_test_runtime({})
    assert runtime['active_jobs'][0]['cancel_allowed']
    for key, run_id in [('alpha', 'old-run-id'), ('beta', 'run-alpha')]:
        with pytest.raises(FileNotFoundError):
            restore_tests_api.cancel_restore_test({}, key, run_id)
    assert not control.is_cancel_requested()
    restore_tests_api.cancel_restore_test({}, 'alpha', 'run-alpha', 'operator')
    first = control.cancel_file.read_bytes()
    restore_tests_api.cancel_restore_test({}, 'alpha', 'run-alpha', 'other')
    assert control.cancel_file.read_bytes() == first
    assert json.loads(first)['requested_by'] == 'operator'
    assert restore_tests_api.restore_test_runtime({})['active_jobs'][0]['cancel_requested']
    states['restore_test_alpha'] = {'running': True, 'run_id': 'run-new-id'}
    with pytest.raises(FileNotFoundError):
        restore_tests_api.cancel_restore_test({}, 'alpha', 'run-alpha')


def test_batch_control_survives_ui_restart_and_does_not_cancel_independent_test(controlled_runtime):
    root, states, locks = controlled_runtime
    batch = job_control.JobControl('restore_test', 'batch-run-id', root)
    batch.update_phase('restore_test', cancel_allowed=True)
    independent = job_control.JobControl('restore_test_beta', 'beta-run-id', root)
    independent.update_phase('restore_test', cancel_allowed=True)
    locks.extend([{'operation':'restore_test','job_key':'alpha','run_id':'batch-run-id'},
                  {'operation':'restore_test','job_key':'alpha','run_id':'batch-run-id'},
                  {'operation':'backup','job_key':'backup','run_id':'backup-run-id'}])
    states['restore_test_beta'] = {'running':True,'run_id':'beta-run-id'}
    restore_tests_api.cancel_restore_test({}, 'alpha', 'batch-run-id')
    assert batch.is_cancel_requested()
    assert not independent.is_cancel_requested()
    batch.update_phase('finished', cancel_allowed=False, finished=True)
    with pytest.raises(FileNotFoundError):
        restore_tests_api.cancel_restore_test({}, 'alpha', 'batch-run-id')


def test_cancel_route_requires_operator_and_returns_conflict_for_finished_run(controlled_runtime):
    handler = object.__new__(BackupUIHandler)
    handler.config = {}
    handler._get_current_session_meta = lambda: {'username':'operator'}
    handler._read_json_body = lambda: {'job_key':'alpha','run_id':'old-run-id'}
    assert handler._required_role_for_request('/api/restore-tests/cancel', 'POST') == 'operator'
    with pytest.raises(ApiConflictError):
        handler._post_cancel_restore_test()


def test_cancellation_kills_real_borg_descendants_without_waiting_for_timeout(tmp_path, borg_env):
    child_file = tmp_path / 'child'
    start = time.monotonic()
    with pytest.raises(resources.ResourceGuardError) as error:
        run_borg(['hang', str(child_file)], borg_env, 60, cancel_requested=child_file.exists)
    assert error.value.cancelled and error.value.code == 'RT_CANCELLED'
    assert time.monotonic() - start < 5
    pid = int(child_file.read_text())
    for _ in range(50):
        try:
            if 'State:\tZ' in Path(f'/proc/{pid}/status').read_text():
                break
        except (FileNotFoundError, ProcessLookupError):
            break
        time.sleep(.02)
    else:
        pytest.fail('Cancelled Borg descendant survived')


def test_cancel_while_queued_does_not_launch_worker_or_release_other_lock(tmp_path, guard_fakes):
    states = []
    started = time.monotonic()
    with (tmp_path / 'restore-test-memory.lock').open('a') as occupied:
        fcntl.flock(occupied, fcntl.LOCK_EX)
        with pytest.raises(resources.ResourceGuardError) as error:
            resources.run_guarded(['worker'], {}, tmp_path, 2048, 1024, lambda _: None,
                                  cancel_requested=lambda: time.monotonic() - started > .15, on_state=states.append)
        assert error.value.cancelled
        assert states == ['waiting']
        assert not guard_fakes['started']
        with (tmp_path / 'restore-test-memory.lock').open('a') as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_cancel_protected_worker_closes_group_and_reaps_launcher(tmp_path, guard_fakes, monkeypatch):
    state = guard_fakes
    class Worker:
        returncode = None
        def __init__(self, *args, **kwargs): state['started'] = True
        def poll(self): return self.returncode
        def kill(self): self.returncode = -9; state['killed'] = True
        def wait(self): state['waited'] = True; return self.returncode
    monkeypatch.setattr(resources.subprocess, 'Popen', Worker)
    with pytest.raises(resources.ResourceGuardError):
        resources.run_guarded(['worker'], {}, tmp_path, 2048, 1024, lambda _: None,
                              cancel_requested=lambda: state['started'])
    assert state['closed'] and state['killed'] and state['waited']


@pytest.mark.parametrize('protected', [False, True])
def test_cancel_records_interruption_after_cleanup_and_releases_locks(tmp_path, monkeypatch, protected):
    tester, repo = _tester(tmp_path, monkeypatch)
    tester.conf['RESTORE_TEST_MEMORY_LIMIT_MIB'] = '2048' if protected else '0'
    cleaned, notified = [], []
    monkeypatch.setattr(tester, '_cleanup_smb_mount', lambda *_: cleaned.append(True))
    monkeypatch.setattr(tester, '_notify_event', lambda *args: notified.append(args))
    def interrupt(*args, **kwargs):
        raise resources.ResourceGuardError('RT_CANCELLED','Cancelled',cancelled=True)
    if protected:
        monkeypatch.setattr(resources, 'run_guarded', interrupt)
    else:
        repo.update(encryption='none', passphrase_file='', path=str(tmp_path))
        monkeypatch.setattr(tester, '_env', lambda *args, **kwargs: {})
        monkeypatch.setattr(tester, '_borg', interrupt)
    try:
        assert tester.test_repo(repo) == 130
        assert tester._cancelled and cleaned
        report = json.loads((tester.status_dir / f"{repo['job_key']}.test").read_text())
        assert report['failure_code'] == 'RT_CANCELLED'
        assert report['test_exit_code'] == 130
        assert report['test_result'] != 'success'
        assert not notified
        assert not list((tmp_path / 'locks').glob('*.lock.json'))
        assert list((tester.status_dir / 'runs' / repo['job_key']).glob('*.test'))
    finally:
        tester.close()


def test_managed_runner_registers_control_and_marks_it_finished(tmp_path, monkeypatch):
    from test_restore_test_runner_profiles import _load_restore_runner
    runner = _load_restore_runner()
    monkeypatch.setenv('BORG_UI_RUN_ID', 'managed-run-id')
    monkeypatch.setattr(job_control, 'CONTROL_ROOT', tmp_path / 'controls')
    monkeypatch.setattr(runner.RestoreTest, '_load_notification_config', lambda _: None)
    tester = runner.RestoreTest({'GLOBAL_LOG_DIR':str(tmp_path / 'logs'), 'RESTORE_TEST_STATUS_DIR':str(tmp_path / 'reports')},
                               SimpleNamespace(level=2, job_keys=['alpha'], resource_worker=False))
    state = json.loads(tester.control.state_file.read_text())
    assert state['job_key'] == 'restore_test_alpha' and state['cancel_allowed']
    job_control.request_cancel('restore_test_alpha','managed-run-id',root=tmp_path / 'controls')
    assert tester.cancel_requested()
    tester.close()
    assert json.loads(tester.control.state_file.read_text())['finished']
    tester.close()


def test_batch_main_stops_after_cancelled_job_and_reports_exit_130(monkeypatch):
    from test_restore_test_runner_profiles import _load_restore_runner
    runner = _load_restore_runner()
    visited, events, closed = [], [], []
    class Tester:
        log_path = 'test.log'
        _cancelled = False
        def __init__(self, *_): pass
        def log(self, *_): pass
        def close(self): closed.append(True)
        def test_repo(self, repo):
            visited.append(repo['job_key'])
            self._cancelled = True
            return 130
    monkeypatch.setattr(runner, 'RestoreTest', Tester)
    monkeypatch.setattr(runner, 'load_conf', lambda: {})
    monkeypatch.setattr(runner, 'discover_repos', lambda _: [{'job_key':key,'location':'local'} for key in ['alpha','beta']])
    monkeypatch.setattr(runner, 'emit_lifecycle', lambda *args, **kwargs: events.append((args, kwargs)))
    monkeypatch.setattr(runner.sys, 'argv', ['borg_restore_test.py', '--force'])
    with pytest.raises(SystemExit) as exit:
        runner.main()
    assert exit.value.code == 130 and visited == ['alpha'] and closed
    finished = [data for args, data in events if args[1] == 'finished'][0]
    assert finished['status'] == 'cancelled' and finished['exit_code'] == 130
