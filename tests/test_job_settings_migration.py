"""Type-free jobs preserve effective settings and reject old exports (#495)."""

import base64
import json
from pathlib import Path

import pytest

from test_job_id_migration import main_fixture, write
from migrations import job_ids_v1, job_settings_v1
from job_identity import new_job_id
from job_settings import explicit_job_settings
from settings_transfer_api import (
    ConfigurationExportError, _encrypt_authenticated_export,
    import_jobs_bundle, preview_jobs_bundle, import_jobs_bundle_encrypted,
    preview_jobs_bundle_encrypted, import_profile_secrets_backup, preview_profile_secrets_backup,
)


def _identified(config):
    job_ids_v1.apply(config)
    return sorted((Path(config['BACKUP_SCRIPTS_DIR']) / 'config/jobs').glob('*.json'))


def test_settings_migration_preserves_values_and_repeats_without_changes(tmp_path):
    config, _ = main_fixture(tmp_path)
    paths = _identified(config)
    original = json.loads(paths[0].read_text())
    original.update(backup_type='flash', compression='', icon='', icon_color='')
    original['retention'].pop('daily')
    original['retention']['yearly'] = 0
    write(paths[0], original)
    conf = Path(config['BACKUP_SCRIPTS_DIR']) / 'config/backup.conf'
    with conf.open('a') as out:
        out.write('COMPRESSION_FLASH="zstd,7"\nRETENTION_FLASH_DAILY="12"\nRETENTION_FLASH_WEEKLY="99"\n')
    result = job_settings_v1.apply(config)
    assert result['status'] == 'applied'
    saved = json.loads(paths[0].read_text())
    assert saved['compression'] == 'zstd,7'
    assert saved['retention'] == {**original['retention'], 'daily': '12', 'yearly': '0'}
    assert saved['icon'] == 'flash'
    assert saved['icon_color'] == 'theme-blue'
    assert 'backup_type' not in saved and 'type_id' not in saved
    for key in ('job_id', 'job_key', 'name', 'archive_prefixes', 'cache_subdir', 'check_flag_name', 'extension', 'created_at', 'updated_at'):
        assert saved[key] == original[key]
    backups = [json.loads(path.read_text()) for path in Path(result['details']['backup_directory']).glob('*.before')]
    assert original in backups
    before = {p: p.read_bytes() for p in paths}
    assert job_settings_v1.detect(config)['required'] is False
    assert job_settings_v1.apply(config)['status'] == 'not_required'
    assert before == {p: p.read_bytes() for p in paths}


def test_settings_migration_resumes_after_interrupted_write(tmp_path, monkeypatch):
    config, _ = main_fixture(tmp_path)
    paths = _identified(config)
    real_apply = job_settings_v1._apply_operation
    count = 0
    def fail_second(op):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError('simulated write interruption')
        real_apply(op)
    monkeypatch.setattr(job_settings_v1, '_apply_operation', fail_second)
    with pytest.raises(OSError, match='interruption'):
        job_settings_v1.apply(config)
    pending = json.loads(job_settings_v1._journal(config).read_text())
    assert pending['status'] == 'pending'
    assert job_settings_v1.detect(config)['required'] is True
    monkeypatch.setattr(job_settings_v1, '_apply_operation', real_apply)
    assert job_settings_v1.apply(config)['status'] == 'applied'
    applied = json.loads(job_settings_v1._journal(config).read_text())
    assert applied['backup_directory'] == pending['backup_directory']
    for path in paths:
        saved = json.loads(path.read_text())
        assert saved['schema_version'] == 5
        explicit_job_settings(saved)


def test_invalid_old_settings_do_not_partially_migrate_jobs(tmp_path):
    config, _ = main_fixture(tmp_path)
    paths = _identified(config)
    invalid = json.loads(paths[-1].read_text())
    invalid['retention']['daily'] = 'invalid'
    write(paths[-1], invalid)
    before = {path: path.read_bytes() for path in paths}
    with pytest.raises(ValueError, match='retention'):
        job_settings_v1.apply(config)
    assert {path: path.read_bytes() for path in paths} == before


def _encrypted(payload):
    return base64.b64encode(_encrypt_authenticated_export(json.dumps(payload).encode(), 'synthetic-test-password')).decode()


@pytest.mark.parametrize('kind', ['jobs', 'profiles'])
@pytest.mark.parametrize('preview', [False, True])
def test_old_encrypted_packages_are_rejected_without_writing(tmp_path, kind, preview):
    target = tmp_path / 'not-created'
    config = {'BACKUP_SCRIPTS_DIR': str(target)}
    payload = {'format': 'bbui-job-bundle-secure-v2', 'bundle': {'format': 'bbui-job-bundle-v2', 'jobs': []}} if kind == 'jobs' else {'format': 'bbui-profile-secrets-v1', 'manifest': [], 'files': []}
    function = (preview_jobs_bundle_encrypted if preview else import_jobs_bundle_encrypted) if kind == 'jobs' else (preview_profile_secrets_backup if preview else import_profile_secrets_backup)
    with pytest.raises(ConfigurationExportError):
        function(config, 'synthetic-test-password', _encrypted(payload))
    assert not target.exists()


@pytest.mark.parametrize('preview', [False, True])
def test_new_format_marker_does_not_make_old_job_metadata_supported(tmp_path, preview):
    target = tmp_path / 'not-created'
    bundle = {'format': 'bbui-job-bundle-v3', 'jobs': [{'schema_version': 3, 'job_key': 'flash_local', 'backup_type': 'flash'}]}
    with pytest.raises(ConfigurationExportError):
        (preview_jobs_bundle if preview else import_jobs_bundle)({'BACKUP_SCRIPTS_DIR': str(target)}, bundle)
    assert not target.exists()


def test_orphan_status_and_restore_files_remain_without_becoming_jobs(tmp_path):
    from test_job_identity_integration import migrated
    from status_api import get_status_data
    from reports_api import get_report_jobs
    from history_api import get_history_data
    from restore_tests_api import list_restore_tests
    config, _, ids, _ = migrated(tmp_path)
    status = Path(config['STATUS_DIR'])
    orphan = status / '2026-09-07_13-00-00_deleted_local.status'
    write(orphan, {'backup_type': 'deleted', 'location': 'local', 'status': 'success', 'timestamp': '2026-09-07 13:00:00'})
    removed = status / '2026-09-07_14-00-00_deleted_uuid.status'
    write(removed, {'job_id': new_job_id(), 'status': 'success', 'timestamp': '2026-09-07 14:00:00'})
    restore = Path(config['RESTORE_TEST_STATUS_DIR']) / 'deleted_local.test'
    write(restore, {'test_result': 'success', 'type': 'deleted', 'location': 'local'})
    before = {path: path.read_bytes() for path in (orphan, removed, restore)}
    assert {row['key'] for row in get_status_data(config)['backups']} == set(ids.values())
    assert {row['key'] for row in get_report_jobs(config)} == set(ids.values())
    assert {row['job_id'] for row in get_history_data(config)['entries']} == set(ids.values())
    assert {row['job_key'] for row in list_restore_tests(config)} == set(ids.values())
    assert {path: path.read_bytes() for path in before} == before
