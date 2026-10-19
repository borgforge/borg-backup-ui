"""VM preparation, opt-in force-off and partial recovery regressions (#541)."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / 'api', ROOT / 'runtime'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from job_fixtures import job_id
from lib import vm_manager, runtime_recovery
from lib.backup_job import BackupJob, BackupJobConfig
from test_runtime_before_maintenance import run_backup  # noqa: F401
import jobs_api
import wizard_api
import wizard_runner

RealVmManager = vm_manager.VmManager


@pytest.fixture
def hypervisor(monkeypatch):
    """A fake libvirt with real manager logic and controlled delayed shutdowns."""
    class Hypervisor:
        active = None
        calls = None
        shutdown_error = ''
        force_fails = False
        restart_fails = False
        query_fails = False
        paused = False
        fail_query_after_shutdown = False
        late_after = None
        elapsed = 0
        before_command = None

        def run(self, cmd, **kwargs):
            self.calls.append(cmd)
            action = cmd[1]
            if self.before_command:
                self.before_command(action)
            rc, out, err = 0, '', ''
            if action == 'list':
                if self.query_fails:
                    rc, err = 1, 'password=do-not-log connection failed'
                else:
                    visible = self.active - {'B'} if self.paused and '--state-running' in cmd else self.active
                    out = '\n'.join(sorted(visible))
            elif action == 'shutdown':
                if self.fail_query_after_shutdown:
                    self.query_fails = True
                if cmd[2] == 'A':
                    self.active.discard('A')
                elif self.shutdown_error == 'timeout':
                    raise subprocess.TimeoutExpired(cmd, 30)
                elif self.shutdown_error == 'os':
                    raise OSError('password=do-not-log')
                elif self.shutdown_error == 'exit':
                    rc, err = 1, 'password=do-not-log command rejected\nextra line'
            elif action == 'destroy':
                if self.force_fails:
                    rc, err = 1, 'force failed'
                else:
                    self.active.discard(cmd[2])
            elif action == 'start':
                if self.restart_fails:
                    rc, err = 1, 'start failed'
                else:
                    self.active.add(cmd[2])
            return subprocess.CompletedProcess(cmd, rc, out, err)

        def sleep(self, seconds):
            self.elapsed += seconds
            if self.late_after is not None and self.elapsed >= self.late_after:
                self.active.discard('B')
                self.late_after = None

    hyper = Hypervisor()
    hyper.active, hyper.calls = {'A', 'B', 'unrelated'}, []
    monkeypatch.setattr(vm_manager, 'virsh_available', lambda: True)
    monkeypatch.setattr(vm_manager.subprocess, 'run', hyper.run)
    monkeypatch.setattr(vm_manager.time, 'sleep', hyper.sleep)
    monkeypatch.setattr(vm_manager.time, 'monotonic', lambda: hyper.elapsed)
    return hyper


def make_job(tmp_path, *, force=False):
    cfg = BackupJobConfig(
        job_id=job_id('vm-shutdown-safety'), job_name='VM test', backup_type='vms', backup_location='local',
        lock_file=tmp_path / 'job.lock', log_dir=tmp_path, log_file=tmp_path / 'job.log',
        backup_paths=[tmp_path], borg_cache_dir=tmp_path / 'cache',
        date_tag='2026-10-19', status_dir=tmp_path / 'status',
        runtime_recovery_file=tmp_path / 'recovery.json',
    )
    return BackupJob(cfg, vm_manager=RealVmManager(vm_manager.VmConfig(
        warning_minutes=0, shutdown_timeout=10, startup_wait=0, force_stop=force,
    )))


@pytest.mark.parametrize('selected', [None, ['A', 'B', 'already-off']])
def test_partial_shutdown_is_recorded_before_commands_and_recovers_stopped_vm(tmp_path, hypervisor, selected):
    hypervisor.active.discard('unrelated')
    job = make_job(tmp_path)

    def persisted(action):
        if action == 'shutdown':
            rows = runtime_recovery.pending_runtime_recovery_entries(job.config.runtime_recovery_file)
            assert len(rows) == 1
            assert {target['name'] for target in rows[0]['targets']} == {'A', 'B'}
            assert rows[0]['shutdown_requested_at']
    hypervisor.before_command = persisted
    with pytest.raises(vm_manager.VmShutdownError, match='shutdown_timeout') as error:
        job.shutdown_vms(selected)
    assert error.value.vms == ['B']
    assert error.value.timeout == 10
    with pytest.raises(RuntimeError, match='Runtime recovery failed'):
        job.recover_runtime()
    assert ['virsh', 'start', 'A'] in hypervisor.calls
    assert ['virsh', 'start', 'already-off'] not in hypervisor.calls
    assert not any(call[1] == 'destroy' for call in hypervisor.calls)
    summary = runtime_recovery.summarize_runtime_recovery(job.config.runtime_recovery_file)
    assert summary['attention_count'] == 1
    assert 'B' in summary['entries'][0]['message']


@pytest.mark.parametrize('selected', [None, ['A', 'B', 'already-off']])
def test_explicit_force_permission_only_stops_initial_targets_after_timeout(tmp_path, hypervisor, selected):
    if selected is None:
        hypervisor.active.discard('unrelated')
    job = make_job(tmp_path, force=True)
    force_times = []
    hypervisor.before_command = lambda action: force_times.append(hypervisor.elapsed) if action == 'destroy' else None
    job.shutdown_vms(selected)
    assert force_times == [10]
    assert job._vm_shutdown_result.forced_vms == ['B']
    assert ['virsh', 'destroy', 'A'] not in hypervisor.calls
    job.recover_runtime()
    assert {'A', 'B'} <= hypervisor.active
    assert ['virsh', 'start', 'already-off'] not in hypervisor.calls
    assert ['virsh', 'destroy', 'unrelated'] not in hypervisor.calls
    assert not runtime_recovery.pending_runtime_recovery_entries(job.config.runtime_recovery_file)


def test_successful_graceful_shutdown_never_forces_and_recovers(tmp_path, hypervisor):
    job = make_job(tmp_path, force=True)
    job.shutdown_vms(['A', 'already-off'])
    job.recover_runtime()
    assert 'A' in hypervisor.active
    assert not any(call[1] == 'destroy' for call in hypervisor.calls)
    assert not runtime_recovery.pending_runtime_recovery_entries(job.config.runtime_recovery_file)


@pytest.mark.parametrize('failure,expected', [('exit', 'command rejected'), ('timeout', 'command timed out'), ('os', 'command could not run')])
def test_shutdown_command_failures_have_safe_diagnostics(tmp_path, hypervisor, caplog, failure, expected):
    hypervisor.shutdown_error = failure
    job = make_job(tmp_path)
    with pytest.raises(vm_manager.VmShutdownError, match=expected) as error:
        job.shutdown_vms(['B'])
    assert 'do-not-log' not in str(error.value) + caplog.text
    assert error.value.failure_code == 'vm_shutdown_failed'
    assert not any(call[1] == 'destroy' for call in hypervisor.calls)


@pytest.mark.parametrize('force', [False, True])
def test_unknown_state_never_means_stopped(tmp_path, hypervisor, force):
    job = make_job(tmp_path, force=force)
    hypervisor.query_fails = True
    with pytest.raises(vm_manager.VmShutdownError, match='state_query_failed'):
        job.shutdown_vms(['A', 'B'])
    assert all(call[1] == 'list' for call in hypervisor.calls)
    assert not job.config.runtime_recovery_file.exists()


def test_state_query_failure_after_requests_keeps_recovery_and_does_not_force(tmp_path, hypervisor):
    job = make_job(tmp_path, force=True)
    hypervisor.fail_query_after_shutdown = True
    with pytest.raises(vm_manager.VmShutdownError, match='state_query_failed'):
        job.shutdown_vms(['A', 'B'])
    with pytest.raises(RuntimeError, match='Runtime recovery failed'):
        job.recover_runtime()
    assert runtime_recovery.summarize_runtime_recovery(job.config.runtime_recovery_file)['attention_count'] == 1
    assert not any(call[1] == 'destroy' for call in hypervisor.calls)


def test_failed_force_off_does_not_allow_backup(tmp_path, hypervisor):
    job = make_job(tmp_path, force=True)
    hypervisor.force_fails = True
    with pytest.raises(vm_manager.VmShutdownError, match='force_stop_failed'):
        job.shutdown_vms(['A', 'B'])
    assert job._vm_shutdown_result.pending_vms == ['B']


def test_late_shutdown_during_recovery_is_restarted(tmp_path, hypervisor):
    job = make_job(tmp_path)
    hypervisor.late_after = 15
    with pytest.raises(vm_manager.VmShutdownError):
        job.shutdown_vms(['A', 'B'])
    job.recover_runtime()
    assert {'A', 'B'} <= hypervisor.active
    assert ['virsh', 'start', 'A'] in hypervisor.calls
    assert ['virsh', 'start', 'B'] in hypervisor.calls
    assert not runtime_recovery.pending_runtime_recovery_entries(job.config.runtime_recovery_file)


def test_recovery_write_failure_prevents_shutdown(tmp_path, hypervisor, monkeypatch):
    job = make_job(tmp_path)
    def fail(*args, **kwargs):
        raise OSError('read-only storage')
    monkeypatch.setattr(runtime_recovery, 'record_runtime_stopped', fail)
    with pytest.raises(vm_manager.VmShutdownError, match='recovery_record_failed'):
        job.shutdown_vms(['A'])
    assert all(call[1] == 'list' for call in hypervisor.calls)
    assert job._vm_shutdown_result is None


@pytest.mark.parametrize('restart_fails', [False, True])
def test_history_notification_and_log_preserve_preparation_failure(tmp_path, hypervisor, monkeypatch, caplog, restart_fails):
    import lifecycle_log
    job = make_job(tmp_path)
    hypervisor.restart_fails = restart_fails
    notifications = []
    monkeypatch.setattr(job, '_send_notification_event', lambda *args: notifications.append(args))
    monkeypatch.setattr(job, '_refresh_unraid_dashboard_widget_cache', lambda *args: None)
    monkeypatch.setattr(lifecycle_log, 'emit_lifecycle', lambda *args, **kwargs: None)
    with caplog.at_level('INFO'), pytest.raises(vm_manager.VmShutdownError):
        with job:
            job.shutdown_vms(['A', 'B'])
    status = json.loads(next(job.config.status_dir.glob('*.status')).read_text())
    assert status['failure_code'] == 'vm_shutdown_failed'
    assert 'shutdown_timeout' in status['error_message']
    assert 'Runtime recovery failed' in status['error_message']
    assert 'Borg backup failed' not in caplog.text
    assert 'exception: 1' not in caplog.text
    assert any('shutdown_timeout' in str(notification) for notification in notifications)
    assert not job.config.lock_file.exists()


@pytest.mark.parametrize('raw,allowed', [(None, False), (False, False), ('true', False), ('false', False), (1, False), (True, True)])
def test_force_permission_requires_explicit_boolean_across_api_and_runner(raw, allowed):
    params = {'vm_control': {'mode': 'selected', 'selected': ['A'], 'force_stop': raw}}
    assert wizard_api._runtime_control_from_params(params, 'vm')['force_stop'] is allowed
    assert wizard_api._runtime_control_from_meta(params, 'vm')['force_stop'] is allowed
    assert jobs_api._runtime_control_from_meta(params, 'vm')['force_stop'] is allowed
    assert wizard_runner._runtime_control(params, 'vm')['force_stop'] is allowed


@pytest.mark.parametrize('force', [False, True])
def test_real_runner_starts_borg_only_after_confirmed_shutdown(run_backup, hypervisor, monkeypatch, force):
    state = run_backup
    state.docker_mode = 'none'
    hypervisor.active.discard('unrelated')
    monkeypatch.setattr(vm_manager, 'VmManager', RealVmManager)
    monkeypatch.setattr(vm_manager.VmConfig, 'from_config', classmethod(lambda cls, env: cls(warning_minutes=0, shutdown_timeout=10, startup_wait=0)))
    original = wizard_runner._runtime_control
    def control(meta, kind):
        value = original(meta, kind)
        if kind == 'vm':
            value['force_stop'] = force
        return value
    monkeypatch.setattr(wizard_runner, '_runtime_control', control)
    assert state.run() == (0 if force else 2)
    assert ('create' in state.actions) is force
    assert state.result == ((0, '') if force else (2, 'vm_shutdown_failed'))


@pytest.mark.parametrize('force', [False, True])
def test_paused_guests_are_not_silently_stopped_and_restarted_running(tmp_path, hypervisor, force):
    hypervisor.paused = True
    job = make_job(tmp_path, force=force)
    with pytest.raises(vm_manager.VmShutdownError, match='guest_not_running'):
        job.shutdown_vms(['A', 'B'])
    assert all(call[1] == 'list' for call in hypervisor.calls)


def test_late_shutdown_at_timeout_needs_no_force(tmp_path, hypervisor):
    job = make_job(tmp_path, force=True)
    hypervisor.late_after = 10
    job.shutdown_vms(['A', 'B'])
    assert not any(call[1] == 'destroy' for call in hypervisor.calls)
    job.recover_runtime()
    assert {'A', 'B'} <= hypervisor.active


def test_previously_off_guest_started_during_preparation_aborts_without_force(tmp_path, hypervisor):
    job = make_job(tmp_path, force=True)
    def concurrent_start(action):
        if action == 'shutdown':
            hypervisor.active.add('already-off')
    hypervisor.before_command = concurrent_start
    with pytest.raises(vm_manager.VmShutdownError, match='guest_became_active'):
        job.shutdown_vms(['A', 'already-off'])
    job.recover_runtime()
    assert ['virsh', 'destroy', 'already-off'] not in hypervisor.calls
    assert ['virsh', 'start', 'already-off'] not in hypervisor.calls


def test_secondary_completion_failures_keep_original_vm_cause(tmp_path):
    job = make_job(tmp_path)
    job._failure_code = 'vm_shutdown_failed'
    job._final_msg = 'Backup not started: B shutdown timeout.'
    job.set_result(2, final_msg='Network share cleanup failed.')
    job.record_hook_result('post', {'status': 'failed', 'exit_code': 1})
    job.record_hook_result('post', {'status': 'cancelled', 'exit_code': 130})
    job.set_result(0)
    assert job._failure_code == 'vm_shutdown_failed'
    assert job.exit_code == 2
    assert 'B shutdown timeout' in job._final_msg
    assert 'Network share cleanup failed' in job._final_msg
    assert 'Post script failed' in job._final_msg
    assert job._cancelled is False
