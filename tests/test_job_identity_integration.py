"""Identity survives the normal Main workflows without changing their results (#486)."""
import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT / 'api', ROOT / 'runtime', ROOT / 'runtime/lib'):
    sys.path.insert(0, str(folder))

from test_job_id_migration import main_fixture, write
from job_fixtures import job_id
from migrations import job_ids_v1 as migration
from archive_prefix import validate_prefix_ownership, validate_archive_prefix
from wizard_api import load_job_for_wizard, save_job
from jobs_api import discover_jobs, list_jobs
from repositories_api import write_repository_store, read_repository_store
from storage_objects_api import write_storage_store
from schedule_api import get_schedules
from status_api import get_status_data
from history_api import get_history_data
from reports_api import get_report_jobs, get_report_data
from restore_tests_api import list_restore_tests, list_restore_test_plan
from settings_transfer_api import export_jobs_bundle, import_jobs_bundle
import wizard_runner


def migrated(tmp_path):
    config, jobs = main_fixture(tmp_path)
    root = Path(config['BACKUP_SCRIPTS_DIR'])
    (tmp_path / 'source').mkdir()
    write_storage_store(config, {'storages': [{
        'storage_key': 'local-test', 'display_name': 'Local', 'storage_type': 'local',
        'location': 'local', 'identity': 'local:' + str(tmp_path / 'repos'),
        'base_path': str(tmp_path / 'repos'),
    }]})
    write_repository_store(config, {'repositories': [
        {'repository_key': key, 'display_name': key, 'storage_key': 'local-test',
         'relative_path': key, 'encryption': 'none',
         'used_by': [j['job_key'] for j in jobs] if key == 'shared' else []}
        for key in ('shared', 'separate')
    ]})
    assert migration.apply(config)['status'] == 'applied'
    plan = json.loads(migration._journal(config).read_text())
    return config, jobs, plan['assignment'], root


def test_name_and_full_prefix_edit_keeps_every_job_relationship(tmp_path, monkeypatch):
    config, jobs, ids, root = migrated(tmp_path)
    key = ids[jobs[0]['job_key']]
    meta_path = root / 'config/jobs' / (key + '.json')
    before = json.loads(meta_path.read_text())
    schedules = get_schedules(config)
    results = list_restore_tests(config)
    initial = {row['key']: row for row in get_status_data(config)['backups']}[key]
    monkeypatch.setattr(wizard_runner.os, 'environ', dict(wizard_runner.os.environ))
    env_before, _ = wizard_runner._load_env_from_job(key, root / 'scripts', root)
    params = load_job_for_wizard(key, root / 'scripts', config)
    params.update(existing_job_key=key, job_name='A renamed job', archive_prefix='flash-config')
    result = save_job(params, root / 'scripts', root, config)
    after = json.loads(meta_path.read_text())
    assert result['job_id'] == result['job_key'] == key
    for field in ('backup_type', 'icon', 'icon_color', 'cache_subdir', 'check_flag_name',
                  'source_paths', 'retention', 'restore_test_policy', 'extension', 'created_at'):
        assert after[field] == before[field]
    assert after['archive_prefixes'] == ['flash-config', *before['archive_prefixes']]
    assert get_schedules(config) == schedules
    assert list_restore_tests(config) == results
    env_after, _ = wizard_runner._load_env_from_job(key, root / 'scripts', root)
    for field in ('BORG_UI_JOB_KEY', 'BORG_CACHE_DIR', 'BORG_CHECK_FLAG_FILE', 'BORG_REPO'):
        assert env_after[field] == env_before[field]
    statuses = get_status_data(config)['backups']
    row = next(r for r in statuses if r['key'] == key)
    for field in ('repository_check_status', 'repository_check_date', 'status', 'archive_name',
                  'original_size', 'restore_verification_last_test_date', 'restore_verification_status'):
        assert row.get(field) == initial.get(field)
    assert row['name'] == 'A renamed job'
    assert [row['name'] for row in statuses] == ['A renamed job', 'Alpha']
    assert [job.name for job in discover_jobs(root / 'scripts', root)] == ['A renamed job', 'Alpha']
    history = get_history_data(config, {'job_key': key})
    assert len(history['entries']) == 1
    assert history['entries'][0]['job_id'] == key
    assert history['entries'][0]['job_name'] == 'A renamed job'
    assert get_report_data(config, key)['run_count'] == 1
    assert get_report_jobs(config)[0]['display_name'] == 'A renamed job'
    assert list_restore_test_plan(config)['jobs'][0]['job_key'] == key
    exported = export_jobs_bundle(config, [key])['bundle']
    assert exported['jobs'] == [after]
    assert exported['schedules'] == {key: schedules[key]}
    # Reusing a prefix owned by this same job is allowed.
    params['archive_prefix'] = before['archive_prefix']
    assert save_job(params, root / 'scripts', root, config)['job_id'] == key
    params['job_id'] = job_id('different')
    with pytest.raises(ValueError, match='cannot be changed'):
        save_job(params, root / 'scripts', root, config)


def test_two_jobs_can_share_a_prefix_only_in_different_repositories(tmp_path, monkeypatch):
    config, jobs, ids, root = migrated(tmp_path)
    key = ids[jobs[0]['job_key']]
    params = load_job_for_wizard(key, root / 'scripts', config)
    params.pop('job_id', None)
    params.update(job_name='New independent job', repository_key='separate')
    created = save_job(params, root / 'scripts', root, config)
    assert created['job_id'] not in ids.values()
    assert len(discover_jobs(root / 'scripts', root)) == 3
    monkeypatch.setattr(wizard_runner.os, 'environ', dict(wizard_runner.os.environ))
    original, _ = wizard_runner._load_env_from_job(key, root / 'scripts', root)
    independent, _ = wizard_runner._load_env_from_job(created['job_id'], root / 'scripts', root)
    assert independent['BORG_CACHE_DIR'] != original['BORG_CACHE_DIR']
    assert independent['BORG_CHECK_FLAG_FILE'] != original['BORG_CHECK_FLAG_FILE']
    assert independent['LOCK_FILE'] != original['LOCK_FILE']
    params['repository_key'] = 'shared'
    with pytest.raises(ValueError, match='overlaps'):
        save_job(params, root / 'scripts', root, config)
    assert len(discover_jobs(root / 'scripts', root)) == 3


@pytest.mark.parametrize('prefix', ['flash', 'flash-config', 'old-flash'])
def test_prefix_ownership_includes_overlap_and_previous_prefixes(prefix):
    owner = {'job_id': job_id('first'), 'name': 'First', 'repository_key': 'shared',
             'archive_prefix': 'flash', 'archive_prefixes': ['old-flash']}
    candidate = {**owner, 'job_id': job_id('second'), 'archive_prefix': prefix, 'archive_prefixes': []}
    with pytest.raises(ValueError, match='overlaps'):
        validate_prefix_ownership(candidate, [owner])
    validate_prefix_ownership({**candidate, 'repository_key': 'other'}, [owner])
    validate_prefix_ownership(owner, [owner])
    assert validate_archive_prefix('flash-config') == 'flash-config'


def test_old_and_new_imports_preserve_identity_and_do_not_duplicate_ownership(tmp_path):
    config, jobs, ids, root = migrated(tmp_path)
    key = ids[jobs[0]['job_key']]
    bundle = export_jobs_bundle(config, [key])['bundle']
    bundle['jobs'][0]['name'] = 'Updated from export'
    report = import_jobs_bundle(config, bundle, mode='overwrite', dry_run=False)
    assert report['report'][0]['new_job_key'] == key
    assert json.loads((root / 'config/jobs' / (key + '.json')).read_text())['extension'] == jobs[0]['extension']
    # The saved migration map makes an old export an update of the same job.
    legacy = copy.deepcopy(bundle)
    legacy['jobs'] = [copy.deepcopy(jobs[0])]
    legacy['jobs'][0]['backup_type'] = jobs[0]['backup_type'].upper()
    legacy['schedules'] = {jobs[0]['job_key']: {'cron': '5 9 * * *', 'enabled': True}}
    report = import_jobs_bundle(config, legacy, mode='overwrite', dry_run=False)
    assert report['report'][0]['new_job_key'] == key
    assert get_schedules(config)[key]['cron'] == '5 9 * * *'
    imported = json.loads((root / 'config/jobs' / (key + '.json')).read_text())
    assert imported['archive_prefix'] == jobs[0]['backup_type'].lower() + '-backup'
    assert import_jobs_bundle(config, bundle, mode='skip', dry_run=False)['imported_count'] == 0
    before = {p.name: p.read_bytes() for p in (root / 'config/jobs').glob('*.json')}
    with pytest.raises(ValueError, match='overlaps'):
        import_jobs_bundle(config, bundle, mode='rename', dry_run=False)
    assert {p.name: p.read_bytes() for p in (root / 'config/jobs').glob('*.json')} == before
    # Importing a copy into another repository allocates an independent ID.
    copied = copy.deepcopy(bundle)
    copied['jobs'][0]['repository_key'] = 'separate'
    report = import_jobs_bundle(config, copied, mode='rename', dry_run=False)
    copied_id = report['report'][0]['new_job_key']
    assert copied_id != key
    assert get_schedules(config)[copied_id] == bundle['schedules'][key]
    repositories = {r['repository_key']: r for r in read_repository_store(config)['repositories']}
    assert repositories['separate']['used_by'] == [copied_id]
    assert set(repositories['shared']['used_by']) == set(ids.values())


def test_migrated_jobs_remain_complete_in_support_bundle(tmp_path, monkeypatch):
    import base64
    import io
    import zipfile
    import support_bundle_api
    import system_health_api
    config, jobs, ids, root = migrated(tmp_path)
    monkeypatch.setattr(system_health_api, 'get_system_health_data', lambda _: {})
    payload = support_bundle_api.create_support_bundle(config, app_version='test-486')
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload['payload_b64']))) as bundle:
        for key in ids.values():
            expected = json.loads((root / 'config/jobs' / (key + '.json')).read_text())
            assert json.loads(bundle.read('jobs/' + key + '.json')) == expected


def test_delete_optional_artifacts_selects_only_the_requested_id(tmp_path, monkeypatch):
    from borg_backup_ui import BackupUIHandler
    import schedule_api
    config, jobs, ids, root = migrated(tmp_path)
    selected, retained = [ids[j['job_key']] for j in jobs]
    log_dir = tmp_path / 'logs'
    log_dir.mkdir()
    with (root / 'config/backup.conf').open('a') as handle:
        handle.write(f'GLOBAL_LOG_DIR="{log_dir}"\n')
    owned = log_dir / 'old-custom-type.log'
    other = log_dir / 'other.log'
    owned.write_text('selected')
    other.write_text('retained')
    for path in Path(config['STATUS_DIR']).glob('*.status'):
        payload = json.loads(path.read_text())
        payload['log_file'] = str(owned if payload['job_id'] == selected else other)
        write(path, payload)
    monkeypatch.setattr(schedule_api, 'delete_schedule', lambda *args: {})
    handler = BackupUIHandler.__new__(BackupUIHandler)
    handler.config = config
    handler._read_json_body = lambda: {'job_key': selected, 'delete_artifacts': True}
    assert handler._delete_job()['deleted'] is True
    assert [j.key for j in discover_jobs(root / 'scripts', root)] == [retained]
    assert len(list(Path(config['STATUS_DIR']).glob('*.status'))) == 1
    assert not owned.exists()
    assert other.read_text() == 'retained'
    assert [r['job_key'] for r in list_restore_tests(config)] == [retained]
