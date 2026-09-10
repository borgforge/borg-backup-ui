"""Reject unavailable USB targets before runtime changes or Borg access (#502)."""

import errno
import json
import logging
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / 'api', ROOT / 'runtime', ROOT / 'runtime/lib'):
    sys.path.insert(0, str(folder))

from job_fixtures import job_id
from lib import backup_job
from lib.backup_job import BackupJob, BackupJobConfig, UsbMountAccessError, USB_MOUNT_ACCESS_FAILED


@pytest.fixture
def job(tmp_path, monkeypatch):
    cfg = BackupJobConfig(
        job_id=job_id('usb-preflight'), job_name='USB test', backup_type='', backup_location='usb',
        lock_file=tmp_path / 'job.lock', log_dir=tmp_path, log_file=tmp_path / 'backup.log',
        backup_paths=[tmp_path / 'source'], borg_cache_dir=tmp_path / 'cache',
        borg_repo=str(tmp_path / 'drive/repository'), date_tag='2026-09-10_15-00-01',
        status_dir=tmp_path / 'status', borg_check_flag_file=tmp_path / 'old-check',
    )
    cfg.backup_paths[0].mkdir()
    cfg.borg_check_flag_file.touch()
    instance = BackupJob(cfg)
    instance.notifications = []
    instance.events = []
    monkeypatch.setattr(instance, '_send_notification_event', lambda *args: instance.notifications.append(args))
    import lifecycle_log
    monkeypatch.setattr(lifecycle_log, 'emit_lifecycle', lambda *_args, **kwargs: instance.events.append(kwargs))
    monkeypatch.setattr(instance, '_refresh_unraid_dashboard_widget_cache', lambda *_args: None)
    return instance


def _reject_borg(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('USB rejection must not execute any Borg command, including completion info')
    monkeypatch.setattr(backup_job.subprocess, 'run', forbidden)


def _status(job):
    return json.loads(next(job.config.status_dir.glob('*.status')).read_text())


@pytest.mark.parametrize('kind,reason', [
    ('missing', 'usb_not_mounted'), ('directory', 'usb_not_mounted'),
    ('file', 'usb_not_mounted'), ('readonly', 'usb_not_writable'),
])
def test_unmounted_or_readonly_usb_is_skipped_without_target_writes(job, tmp_path, monkeypatch, kind, reason):
    mount = tmp_path / 'drive'
    if kind in {'directory', 'readonly'}:
        mount.mkdir()
    elif kind == 'file':
        mount.write_text('not a mount')
    if kind == 'readonly':
        monkeypatch.setattr(Path, 'is_mount', lambda path: path == mount)
        access = backup_job.os.access
        monkeypatch.setattr(backup_job.os, 'access', lambda path, mode: False if path == mount else access(path, mode))
    _reject_borg(monkeypatch)
    with pytest.raises(SystemExit) as stopped:
        with job:
            job.check_usb_mount(mount)
            pytest.fail('Docker/VM stop and backup must not be reached')
    assert stopped.value.code == 0
    data = _status(job)
    assert (data['status'], data['exit_code'], data['skip_reason_code']) == ('skipped', 0, reason)
    assert not job.config.lock_file.exists()
    assert len(job.notifications) == 1 and job.notifications[0][0] == 'backup_skipped'
    assert not (mount / 'repository').exists()
    if kind in {'directory', 'readonly'}:
        assert list(mount.iterdir()) == []


@pytest.mark.parametrize('stage', ['stat', 'mount', 'access'])
@pytest.mark.parametrize('error_number', [errno.EIO, errno.ENODEV])
def test_mount_access_errors_have_specific_failure_and_never_query_borg(
    job, tmp_path, monkeypatch, caplog, stage, error_number,
):
    mount = tmp_path / 'drive'
    mount.mkdir()
    original_stat = Path.stat
    def failing_stat(path, *args, **kwargs):
        if path == mount and stage == 'stat':
            raise OSError(error_number, 'simulated USB access failure', str(mount))
        return original_stat(path, *args, **kwargs)
    def mounted(path):
        if path == mount and stage == 'mount':
            raise OSError(error_number, 'simulated USB access failure', str(mount))
        return path == mount
    original_access = backup_job.os.access
    def access(path, mode):
        if path == mount and stage == 'access':
            raise OSError(error_number, 'simulated USB access failure', str(mount))
        return original_access(path, mode)
    monkeypatch.setattr(Path, 'stat', failing_stat)
    monkeypatch.setattr(Path, 'is_mount', mounted)
    monkeypatch.setattr(backup_job.os, 'access', access)
    _reject_borg(monkeypatch)
    with caplog.at_level(logging.INFO), pytest.raises(UsbMountAccessError):
        with job:
            job.check_usb_mount(mount)
            pytest.fail('Docker/VM stop and backup must not be reached')
    data = _status(job)
    assert (data['status'], data['exit_code']) == ('error', 2)
    assert data['failure_code'] == USB_MOUNT_ACCESS_FAILED
    assert 'USB drive is not accessible' in data['error_message']
    assert 'Backup was not started' in data['error_message']
    assert str(mount) in data['error_message'] and f'[Errno {error_number}]' in data['error_message']
    assert data['repository_check_status'] == 'unknown' and data['repository_size'] == 0
    assert not job.config.lock_file.exists()
    assert len(job.notifications) == 1 and job.notifications[0][0] == 'backup_failed'
    assert 'USB drive is not accessible' in job.notifications[0][2]
    assert job.events[0]['failure_code'] == USB_MOUNT_ACCESS_FAILED
    assert 'USB preflight' in caplog.text
    assert 'Borg backup failed' not in caplog.text
    assert list(mount.iterdir()) == []


def test_mounted_accessible_usb_passes_without_creating_probe_files(job, tmp_path, monkeypatch):
    mount = tmp_path / 'drive'
    mount.mkdir()
    monkeypatch.setattr(Path, 'is_mount', lambda path: path == mount)
    _reject_borg(monkeypatch)
    assert job.check_usb_mount(mount) is None
    assert not job.config.status_dir.exists()
    assert list(mount.iterdir()) == []
    assert job.notifications == []


def test_real_runner_returns_usb_failure_and_releases_resources(job, tmp_path, monkeypatch):
    import job_control
    import lifecycle_log
    import wizard_runner
    from lib.borg_runner import BorgRunner

    mount = tmp_path / 'drive'
    mount.mkdir()
    phases, resources, actions = [], [], []
    control = SimpleNamespace(update_phase=lambda phase, **kwargs: phases.append((phase, kwargs)),
                              is_cancel_requested=lambda: False)
    monkeypatch.setattr(job_control, 'JobControl', lambda *_args: control)
    monkeypatch.setattr(wizard_runner, 'ResourceLockSet', lambda **_kwargs: SimpleNamespace(
        acquire=lambda _: (True, ''), release=lambda: resources.append('released')))
    monkeypatch.setattr(wizard_runner, '_ensure_borg_available', lambda: 'borg')
    monkeypatch.setattr(wizard_runner, '_setup_stdout_logging', lambda: None)
    monkeypatch.setattr(wizard_runner, '_setup_full_logging', lambda _: None)
    monkeypatch.setattr(wizard_runner, '_ensure_runtime_import_paths', lambda _: None)
    monkeypatch.setattr(wizard_runner, '_load_env_from_job', lambda *_args: (
        {'BACKUP_SCRIPTS_DIR': str(tmp_path), 'ABORT_ON_PARITY_CHECK': 'false'},
        {'job_id': job.config.job_id, 'location': 'usb', 'archive_prefix': 'test-backup',
         '_resolved_storage': {'mount_path': str(mount)},
         'docker_control': {'mode': 'all'}, 'vm_control': {'mode': 'all'}}))
    monkeypatch.setattr(BackupJobConfig, 'from_config', lambda _: job.config)
    monkeypatch.setattr(BackupJob, '_send_notification_event', lambda *_args: None)
    monkeypatch.setattr(BackupJob, '_refresh_unraid_dashboard_widget_cache', lambda *_args: None)
    monkeypatch.setattr(BackupJob, 'stop_docker', lambda *_args, **_kwargs: actions.append('stop Docker'))
    monkeypatch.setattr(BackupJob, 'shutdown_vms', lambda *_args, **_kwargs: actions.append('stop VMs'))
    monkeypatch.setattr(BorgRunner, 'create', lambda *_args, **_kwargs: actions.append('create') or 0)
    monkeypatch.setattr(BorgRunner, 'maintenance', lambda *_args, **_kwargs: actions.append('maintenance') or 0)
    monkeypatch.setattr(lifecycle_log, 'emit_lifecycle', lambda *_args, **_kwargs: None)
    for name, value in {'BORG_UI_JOB_KEY': job.config.job_id, 'BORG_UI_BORG_SCRIPTS_DIR': str(ROOT / 'runtime/scripts'),
                        'BORG_SCRIPT_DIR': str(tmp_path), 'BORG_UI_RUN_ID': '20260910T150001Z-usbtest'}.items():
        monkeypatch.setenv(name, value)
    original_stat = Path.stat
    def failed(path, *args, **kwargs):
        if path == mount: raise OSError(errno.EIO, 'Input/output error', str(mount))
        return original_stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', failed)
    _reject_borg(monkeypatch)
    assert wizard_runner.main() == 2
    assert actions == [] and resources == ['released']
    assert not job.config.lock_file.exists()
    assert phases[-1][0] == 'failed' and phases[-1][1]['exit_code'] == 2
    assert _status(job)['failure_code'] == USB_MOUNT_ACCESS_FAILED
