"""Regressions for repository actions on temporarily mounted SMB storage (#726)."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import repositories_api as repositories
import smb_profiles_api
from storage_objects_api import write_storage_store


@pytest.fixture
def smb_target(tmp_path, monkeypatch):
    """Model separate local/NAS contents without mounting or using a real NAS."""
    local = tmp_path / 'mountpoint'
    hidden = tmp_path / 'underlying-local'
    remote = tmp_path / 'nas'
    local.mkdir()
    remote.mkdir()
    # This is the misplaced local repository from the forum report. Never modify it.
    misplaced = local / 'Backup_ISO'
    misplaced.mkdir()
    (misplaced / 'config').write_text('[repository]\nid = aabbccdd\n')
    (misplaced / 'data').mkdir()
    config = {'BACKUP_SCRIPTS_DIR': str(tmp_path / 'app')}
    storage = {
        'storage_key': 'smb-test', 'display_name': 'NAS', 'storage_type': 'smb',
        'location': 'smb', 'identity': 'smb-profile:nas', 'profile_key': 'nas',
        'base_path': str(local), 'mount_path': str(local),
        'server': 'nas.example.test', 'share': 'Backup', 'username': 'backup',
        'mount_on_startup': False, 'keep_mounted': False,
    }
    write_storage_store(config, {'storages': [storage]})
    state = SimpleNamespace(config=config, storage=storage, local=local, remote=remote,
                            mounted=False, events=[], mount_failure=False,
                            borg_failure=False, cleanup_failure=False)

    def mount(_config, key, action):
        assert key == 'nas'
        state.events.append(action)
        if action == 'mount':
            if state.mount_failure:
                return {'ok': False, 'message': 'SMB mount failed'}
            if state.mounted:
                return {'ok': True, 'message_code': 'smb_already_mounted'}
            local.rename(hidden)
            local.symlink_to(remote, target_is_directory=True)
            state.mounted = True
            return {'ok': True, 'message_code': 'smb_mount_success'}
        assert action == 'unmount' and state.mounted
        if state.cleanup_failure:
            return {'ok': False}
        local.unlink()
        hidden.rename(local)
        state.mounted = False
        return {'ok': True}

    def borg(cmd, **kwargs):
        assert state.mounted, 'Borg must never access the underlying local directory'
        target = Path(cmd[-1])
        assert target.parent.resolve() == remote
        state.events.append(cmd[1])
        if state.borg_failure:
            return subprocess.CompletedProcess(cmd, 2, '', 'Simulated Borg failure')
        if cmd[1] == 'init':
            target.mkdir()
            (target / 'config').write_text('[repository]\nid = 11223344\n')
            (target / 'data').mkdir()
            return subprocess.CompletedProcess(cmd, 0, '', '')
        assert cmd[1] == 'info' and (target / 'config').is_file()
        return subprocess.CompletedProcess(cmd, 0, json.dumps({
            'repository': {'id': '11223344'}, 'encryption': {'mode': 'repokey-blake2'},
        }), '')

    monkeypatch.setattr(smb_profiles_api, 'run_smb_profile_action', mount)
    monkeypatch.setattr(repositories.subprocess, 'run', borg)
    state.mount = mount
    state.payload = {
        'action': 'create', 'storage_key': 'smb-test', 'repository_name': 'Backup_ISO',
        'relative_path': 'Backup_ISO', 'encryption': 'repokey-blake2',
        'passphrase': 'test-only-passphrase',
    }
    yield state
    if state.mounted:
        state.cleanup_failure = False
        mount(config, 'nas', 'unmount')


def test_validation_inspects_nas_not_misplaced_local_repository(smb_target):
    s = smb_target
    assert repositories.validate_repository_target(s.config, s.payload)['state'] == 'absent'
    assert s.events == ['mount', 'unmount']
    assert (s.local / 'Backup_ISO/config').read_text().endswith('aabbccdd\n')
    assert not (s.remote / 'Backup_ISO').exists()
    assert not (Path(s.config['BACKUP_SCRIPTS_DIR']) / 'secrets').exists()


@pytest.mark.parametrize('entry', ['repository_api', 'shared_http_endpoint'])
def test_create_after_temporary_validation_mount_keeps_nas_through_info(smb_target, entry):
    s = smb_target
    # Both initial setup and Settings open the shared repository manager/API.
    repositories.validate_repository_target(s.config, s.payload)
    s.events.clear()
    if entry == 'shared_http_endpoint':
        from borg_backup_ui import BackupUIHandler
        handler = BackupUIHandler.__new__(BackupUIHandler)
        handler.config = s.config
        handler._read_json_body = lambda: s.payload
        result = handler._post_repository()
    else:
        result = repositories.create_or_import_repository(s.config, s.payload)
    assert result['ok']
    assert result['repository']['borg_repository_id'] == '11223344'
    assert s.events[-4:] == ['mount', 'init', 'info', 'unmount']
    assert (s.remote / 'Backup_ISO/config').read_text().endswith('11223344\n')
    assert (s.local / 'Backup_ISO/config').read_text().endswith('aabbccdd\n')
    assert not s.mounted


@pytest.mark.parametrize('already_mounted,keep_mounted', [(True, False), (False, True)])
def test_creation_preserves_existing_mount_or_keep_mounted(smb_target, already_mounted, keep_mounted):
    s = smb_target
    s.storage['keep_mounted'] = keep_mounted
    write_storage_store(s.config, {'storages': [s.storage]})
    if already_mounted:
        s.mount(s.config, 'nas', 'mount')
    s.events.clear()
    assert repositories.create_or_import_repository(s.config, s.payload)['ok']
    assert s.mounted
    assert s.events == ['mount', 'init', 'info']


@pytest.mark.parametrize('operation', ['validate', 'create', 'import'])
def test_mount_failure_aborts_before_borg_secrets_or_inventory(smb_target, operation):
    s = smb_target
    s.mount_failure = True
    if operation == 'import':
        s.payload['action'] = 'import'
    function = (repositories.validate_repository_target if operation == 'validate'
                else repositories.create_or_import_repository)
    with pytest.raises(ValueError, match='SMB mount failed'):
        function(s.config, s.payload)
    assert s.events == ['mount']
    assert not (Path(s.config['BACKUP_SCRIPTS_DIR']) / 'secrets').exists()
    assert not repositories.read_repository_store(s.config)['repositories']
    assert (s.local / 'Backup_ISO/config').read_text().endswith('aabbccdd\n')
    assert not list(s.remote.iterdir())


def test_import_reads_nas_repository_before_releasing_mount(smb_target):
    s = smb_target
    target = s.remote / 'Backup_ISO'
    target.mkdir()
    (target / 'config').write_text('[repository]\nid = 11223344\n')
    s.payload['action'] = 'import'
    result = repositories.create_or_import_repository(s.config, s.payload)
    assert result['repository']['borg_repository_id'] == '11223344'
    assert s.events == ['mount', 'info', 'unmount']
    assert not s.mounted


@pytest.mark.parametrize('operation', ['create', 'import'])
def test_borg_failure_releases_owned_mount_and_restores_secret(smb_target, operation):
    s = smb_target
    s.payload['action'] = operation
    s.borg_failure = True
    with pytest.raises((ValueError, RuntimeError), match='Simulated Borg failure'):
        repositories.create_or_import_repository(s.config, s.payload)
    assert not s.mounted
    assert s.events[0] == 'mount' and s.events[-1] == 'unmount'
    assert not repositories.read_repository_store(s.config)['repositories']
    assert not list((Path(s.config['BACKUP_SCRIPTS_DIR']) / 'secrets').glob('.borg-passphrase-*'))


def test_existing_remote_repository_rejected_without_writes(smb_target):
    s = smb_target
    target = s.remote / 'Backup_ISO'
    target.mkdir()
    (target / 'config').write_text('[repository]\nid = 11223344\n')
    with pytest.raises(repositories.RepositoryTargetConflict) as error:
        repositories.create_or_import_repository(s.config, s.payload)
    assert error.value.code == 'repository_target_borg_exists'
    assert s.events == ['mount', 'unmount']
    assert not (Path(s.config['BACKUP_SCRIPTS_DIR']) / 'secrets').exists()
    assert (target / 'config').read_text().endswith('11223344\n')


def test_failed_unmount_is_reported(smb_target):
    s = smb_target
    s.cleanup_failure = True
    with pytest.raises(RuntimeError, match='cleanup failed'):
        repositories.validate_repository_target(s.config, s.payload)
    assert s.events == ['mount', 'unmount']
