"""USB roots/subdirectories and profile/backup agreement (#516)."""

import errno
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT / 'api', ROOT / 'runtime'):
    sys.path.insert(0, str(folder))

from lib import usb_storage
from lib.backup_job import BackupJob, UsbMountAccessError
import usb_profiles_api


@pytest.fixture
def drive(tmp_path, monkeypatch):
    drive = tmp_path / 'USB HDD'
    (drive / 'borg-backup' / 'repository').mkdir(parents=True)
    monkeypatch.setattr(usb_storage, '_read_mounts', lambda: [
        usb_storage.Mount(Path('/'), 'rootfs', False),
        usb_storage.Mount(drive, 'xfs', False),
    ])
    return drive


def _profile(path):
    return usb_profiles_api.test_usb_profiles_status([
        {'key': 'usb', 'name': 'USB HDD', 'mount_path': str(path)}
    ])['results'][0]


def _backup(path):
    # Exercise the real preflight without creating logs/status files or running Borg.
    job = BackupJob.__new__(BackupJob)
    job.config = SimpleNamespace(job_name='USB test')
    job._write_mini_log = lambda *_args: None
    job._persist_skip_status_once = lambda: None
    job.check_usb_mount(path)


@pytest.mark.parametrize('subpath', ['', 'borg-backup', 'borg-backup/repository'])
def test_root_and_nested_directories_work_in_both_callers(drive, subpath, caplog):
    path = drive / subpath
    before = sorted(drive.rglob('*'))
    with caplog.at_level('INFO'):
        _backup(path)
    result = _profile(path)
    assert result['ok'] and result['is_mounted'] and result['writable']
    assert result['mount_path'] == str(path)  # Keep the configured base, never rewrite it.
    assert result['detected_mount'] == str(drive)
    assert f'mount={drive}; result=ok' in caplog.text
    assert sorted(drive.rglob('*')) == before


@pytest.mark.parametrize('fs', ['rootfs', 'tmpfs', 'ramfs', 'overlay', 'ext4'])
def test_leftover_directory_is_not_a_drive(drive, monkeypatch, fs):
    monkeypatch.setattr(usb_storage, '_read_mounts', lambda: [usb_storage.Mount(Path('/'), fs, False)])
    path = drive / 'borg-backup'
    assert _profile(path)['code'] == 'not_mounted'
    with pytest.raises(SystemExit):
        _backup(path)


@pytest.mark.parametrize('fs', ['tmpfs', 'ramfs', 'overlay'])
def test_ram_or_system_filesystem_at_drive_path_is_rejected(drive, monkeypatch, fs):
    monkeypatch.setattr(usb_storage, '_read_mounts', lambda: [usb_storage.Mount(drive, fs, False)])
    assert not _profile(drive)['ok']
    with pytest.raises(SystemExit):
        _backup(drive)


def test_mount_prefix_must_end_at_directory_boundary(drive):
    neighbor = drive.with_name(drive.name + '-offline')
    neighbor.mkdir()
    assert _profile(neighbor)['code'] == 'not_mounted'
    with pytest.raises(SystemExit):
        _backup(neighbor)


def test_internal_symlink_allowed_but_escape_to_other_mount_rejected(drive, monkeypatch):
    (drive / 'inside').symlink_to(drive / 'borg-backup', target_is_directory=True)
    assert _profile(drive / 'inside')['ok']
    _backup(drive / 'inside')
    other = drive.parent / 'other-drive'
    other.mkdir()
    (drive / 'outside').symlink_to(other, target_is_directory=True)
    monkeypatch.setattr(usb_storage, '_read_mounts', lambda: [
        usb_storage.Mount(drive, 'xfs', False), usb_storage.Mount(other, 'xfs', False),
    ])
    assert _profile(drive / 'outside')['code'] == 'outside_mount'
    with pytest.raises(SystemExit):
        _backup(drive / 'outside')


@pytest.mark.parametrize('kind,code', [('missing', 'not_found'), ('file', 'not_directory')])
def test_missing_or_non_directory_target(drive, kind, code):
    path = drive / kind
    if kind == 'file':
        path.touch()
    assert _profile(path)['code'] == code
    with pytest.raises(SystemExit):
        _backup(path)


@pytest.mark.parametrize('mode', ['mount_readonly', 'no_write', 'no_read_search'])
def test_permissions_checked_by_both_callers(drive, monkeypatch, mode):
    if mode == 'mount_readonly':
        monkeypatch.setattr(usb_storage, '_read_mounts', lambda: [usb_storage.Mount(drive, 'xfs', True)])
    else:
        access = os.access
        denied = os.W_OK if mode == 'no_write' else os.R_OK | os.X_OK
        monkeypatch.setattr(usb_storage.os, 'access', lambda p, flags: False if flags == denied else access(p, flags))
    result = _profile(drive / 'borg-backup')
    assert not result['ok']
    assert result['code'] == ('access_error' if mode == 'no_read_search' else 'not_writable')
    with pytest.raises(UsbMountAccessError if mode == 'no_read_search' else SystemExit):
        _backup(drive / 'borg-backup')


@pytest.mark.parametrize('error_number', [errno.EIO, errno.ENODEV, errno.EACCES])
@pytest.mark.parametrize('stage', ['directory', 'mount', 'mount_table'])
def test_access_errors_survive_in_both_callers(drive, monkeypatch, error_number, stage):
    path = drive / 'borg-backup'
    original_stat = Path.stat
    def failing_stat(p, *args, **kwargs):
        if p == (drive if stage == 'mount' else path):
            raise OSError(error_number, 'simulated access failure', str(p))
        return original_stat(p, *args, **kwargs)
    if stage == 'mount_table':
        def failing_mounts():
            raise OSError(error_number, 'simulated mount table failure')
        monkeypatch.setattr(usb_storage, '_read_mounts', failing_mounts)
    else:
        monkeypatch.setattr(Path, 'stat', failing_stat)
    result = _profile(path)
    assert result['code'] == 'access_error' and not result['ok']
    assert f'Errno {error_number}' in result['message']
    with pytest.raises(UsbMountAccessError, match=f'Errno {error_number}'):
        _backup(path)


@pytest.mark.parametrize('filesystem', ['xfs', 'btrfs', 'zfs', 'ntfs3', 'fuseblk', 'exfat'])
@pytest.mark.parametrize('mount_opts,super_opts,readonly', [('rw', 'rw', False), ('ro', 'rw', True), ('rw', 'ro', True)])
def test_mountinfo_filesystems_escaping_and_readonly(monkeypatch, filesystem, mount_opts, super_opts, readonly):
    line = f'42 1 8:1 / /mnt/disks/USB\\040HDD\\134name {mount_opts} shared:7 - {filesystem} /dev/sda1 {super_opts}\n'
    monkeypatch.setattr(Path, 'read_text', lambda *args, **kwargs: line)
    assert usb_storage._read_mounts() == [usb_storage.Mount(Path('/mnt/disks/USB HDD\\name'), filesystem, readonly)]


@pytest.mark.parametrize('text', ['', 'invalid mount table', '42 1 8:1 / /mnt/drive rw - xfs'])
def test_unknown_mount_state_fails_closed(monkeypatch, text):
    monkeypatch.setattr(Path, 'read_text', lambda *args, **kwargs: text)
    with pytest.raises(OSError, match='kernel mount table'):
        usb_storage._read_mounts()


def test_deepest_mount_controls_readonly_state(drive, monkeypatch):
    path = drive / 'borg-backup'
    monkeypatch.setattr(usb_storage, '_read_mounts', lambda: [
        usb_storage.Mount(drive, 'xfs', False), usb_storage.Mount(path, 'btrfs', True),
    ])
    result = _profile(path / 'repository')
    assert result['code'] == 'not_writable' and result['detected_mount'] == str(path)
    with pytest.raises(SystemExit):
        _backup(path / 'repository')


def test_profile_access_failure_does_not_abort_other_results(drive, monkeypatch):
    original_stat = Path.stat
    def stat(p, *args, **kwargs):
        if p == drive / 'broken':
            raise OSError(errno.EIO, 'simulated USB failure')
        return original_stat(p, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', stat)
    results = usb_profiles_api.test_usb_profiles_status([
        {'mount_path': str(drive / 'broken')}, {'mount_path': str(drive)},
    ])['results']
    assert results[0]['code'] == 'access_error'
    assert results[1]['ok']


def test_ambiguous_mount_state_is_an_explicit_error(drive, monkeypatch):
    monkeypatch.setattr(usb_storage, '_read_mounts', lambda: [
        usb_storage.Mount(drive, 'xfs', False), usb_storage.Mount(drive, 'tmpfs', False),
    ])
    assert _profile(drive)['code'] == 'access_error'
    with pytest.raises(UsbMountAccessError, match='Ambiguous'):
        _backup(drive)
