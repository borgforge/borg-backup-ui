"""#474 control plane: real inventory transitions, HTTP boundaries and failure injection."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
sys.path.insert(0, str(ROOT))
from test_canonical_job_wizard import setup, create, edit
from inventory_store import atomic_write_json
from job_model import JobValidationError
from job_store import read_json, read_jobs
from job_actions import (resolve_request_job_id, resolve_request_schedule_id, prepare_job_action,
                         set_job_enabled, delete_job_configuration)
from jobs_api import discover_jobs, list_jobs
from repositories_api import (read_repository_store_for_api, repository_assignment_report,
                              reconcile_repository_usage, write_repository_store)
from schedule_api import get_schedules, save_schedule, delete_schedule, apply_all_schedules
from storage_objects_api import read_storage_store, write_storage_store
import schedule_api


@pytest.fixture
def cron(monkeypatch):
    calls = []
    def install(lines):
        calls.append(list(lines))
        return {'changed': True, 'line_count': len(lines)}
    monkeypatch.setattr(schedule_api, '_update_crontab', install)
    return calls


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in (root / 'config').rglob('*.json')}


def test_config_to_pfsense_preserves_one_job_schedule_and_alias(setup, cron):
    config, _, scripts, root = setup
    result, meta = create(setup, archive_prefix='config-backup', job_name='Config')
    job_id = result['job_id']
    meta['legacy_job_keys'] = ['config_local']
    atomic_write_json(Path(result['metadata_path']), meta)
    save_schedule(config, job_id, '17 3 * * 2', False)
    schedule_path = root / 'config/schedules.json'
    before = schedule_path.read_bytes()
    edit(setup, job_id, job_name='pfsense_local', archive_prefix='pfsense-backup', repository_key='repo_b')
    assert schedule_path.read_bytes() == before
    assert list(read_jobs(root / 'config/jobs')) == [job_id]
    context = prepare_job_action(config, job_id)
    assert context['job_id'] == job_id and context['name'] == 'pfsense_local'
    assert context['archive_prefixes'] == ['pfsense-backup', 'config-backup']
    assert context['location'] == 'storagebox'
    assert resolve_request_job_id(config, {'job_key': 'config_local'}, endpoint='jobs/run') == job_id
    assert resolve_request_job_id(config, {'job_id': job_id}, endpoint='jobs/run') == job_id
    with pytest.raises(JobValidationError):
        resolve_request_job_id(config, {'job_key': 'pfsense_local'}, endpoint='jobs/run')
    jobs = discover_jobs(scripts, root)
    assert len(jobs) == 1 and jobs[0].job_id == job_id and jobs[0].name == 'pfsense_local'
    rows = list_jobs(config, {})
    assert rows[0]['job_id'] == job_id and rows[0]['archive_prefix'] == 'pfsense-backup'
    assert not {'key', 'job_key', 'backup_type'}.intersection(rows[0])
    repositories = read_repository_store_for_api(config)['repositories']
    target = next(row for row in repositories if row['repository_key'] == 'repo_b')
    assert target['jobs'] == [{'job_id': job_id, 'name': 'pfsense_local', 'archive_prefix': 'pfsense-backup'}]


def test_storage_change_uses_current_descriptor_and_keeps_schedule_bytes(setup, cron):
    config, _, scripts, root = setup
    result, _ = create(setup)
    save_schedule(config, result['job_id'], '0 2 * * *', True)
    before = snapshot(root)
    store = read_storage_store(config)
    local = next(row for row in store['storages'] if row['storage_key'] == 'local')
    local['base_path'] = str(root / 'new-target')
    write_storage_store(config, store)
    job = discover_jobs(scripts, root)[0]
    assert job.job_id == result['job_id']
    assert prepare_job_action(config, job.job_id)['repository_path'] == str(root / 'new-target/repo_a')
    after = snapshot(root)
    for path in before:
        if path.name != 'storages.json':
            assert after[path] == before[path]


@pytest.mark.parametrize('operation', ['rename', 'enable', 'delete', 'save_schedule', 'apply'])
def test_dangling_disabled_schedule_blocks_every_write_without_cleanup(setup, cron, operation):
    config, _, _, root = setup
    result, _ = create(setup)
    atomic_write_json(root / 'config/schedules.json', {'config_local': {'cron': '0 2 * * *', 'enabled': False}})
    before = snapshot(root)
    calls = {
        'rename': lambda: edit(setup, result['job_id'], job_name='pfsense'),
        'enable': lambda: set_job_enabled(config, result['job_id'], False),
        'delete': lambda: delete_job_configuration(config, result['job_id']),
        'save_schedule': lambda: save_schedule(config, result['job_id'], '0 4 * * *', True),
        'apply': lambda: apply_all_schedules(config),
    }
    with pytest.raises(JobValidationError):
        calls[operation]()
    assert snapshot(root) == before and cron == []


@pytest.mark.parametrize('bad', ['{', '{"restore_test":{},"restore_test":{}}', '[]'])
def test_schedule_read_rejects_corruption_without_writes(setup, cron, bad):
    config, _, _, root = setup
    create(setup)
    path = root / 'config/schedules.json'
    path.write_text(bad)
    before = snapshot(root)
    with pytest.raises(JobValidationError):
        get_schedules(config)
    assert snapshot(root) == before and cron == []


def test_schedule_enable_disable_and_delete_preserve_service_and_extensions(setup, cron):
    config, _, _, root = setup
    result, _ = create(setup)
    job_id = result['job_id']
    service = {'cron': '0 1 * * *', 'enabled': True, 'extension': [True]}
    atomic_write_json(root / 'config/schedules.json', {'restore_test': service})
    save_schedule(config, job_id, '5 2 * * 3', True)
    assert any('job_id' in line and job_id in line and 'job_key' not in line for line in cron[-1])
    assert any('/api/restore-tests/run' in line for line in cron[-1])
    set_job_enabled(config, job_id, False)
    assert get_schedules(config)[job_id]['enabled'] is True
    assert all(job_id not in line for line in cron[-1])
    set_job_enabled(config, job_id, True)
    assert any(job_id in line for line in cron[-1])
    save_schedule(config, job_id, '5 2 * * 3', False)
    assert all(job_id not in line for line in cron[-1])
    delete_schedule(config, job_id)
    assert get_schedules(config) == {'restore_test': service}


@pytest.mark.parametrize('operation', ['schedule', 'enable', 'delete'])
def test_crontab_failure_rolls_back_all_bytes_and_old_cron(setup, cron, monkeypatch, operation):
    config, _, _, root = setup
    result, _ = create(setup)
    job_id = result['job_id']
    save_schedule(config, job_id, '0 2 * * *', True)
    original_lines = cron[-1]
    before = snapshot(root)
    attempts = []
    def fail_once(lines):
        attempts.append(list(lines))
        if len(attempts) == 1:
            raise OSError('synthetic crontab failure')
        return {}
    monkeypatch.setattr(schedule_api, '_update_crontab', fail_once)
    with pytest.raises(OSError):
        if operation == 'schedule':
            save_schedule(config, job_id, '0 5 * * *', True)
        elif operation == 'enable':
            set_job_enabled(config, job_id, False)
        else:
            delete_job_configuration(config, job_id)
    assert snapshot(root) == before and attempts[-1] == original_lines


def test_delete_is_one_configuration_transaction_and_retains_artifacts(setup, cron):
    config, _, _, root = setup
    result, _ = create(setup)
    save_schedule(config, result['job_id'], '0 2 * * *', True)
    artifact = root / 'historical.log'
    artifact.write_bytes(b'historical bytes')
    delete_job_configuration(config, result['job_id'])
    assert read_jobs(root / 'config/jobs') == {} and get_schedules(config) == {}
    assert all(row['job_ids'] == row['source_job_ids'] == [] for row in read_json(root / 'config/repositories.json')['repositories'])
    assert artifact.read_bytes() == b'historical bytes'
    assert cron[-1] == []


def test_repository_write_failure_rolls_back_job_and_leaves_schedule_unchanged(setup, cron, monkeypatch):
    import job_store
    config, _, _, root = setup
    result, _ = create(setup)
    save_schedule(config, result['job_id'], '0 2 * * *', False)
    before = snapshot(root)
    original = job_store.atomic_write_json
    def fail_repository(path, data):
        if Path(path).name == 'repositories.json':
            raise OSError('synthetic repository failure')
        original(path, data)
    monkeypatch.setattr(job_store, 'atomic_write_json', fail_repository)
    with pytest.raises(OSError):
        edit(setup, result['job_id'], job_name='new', repository_key='repo_b')
    assert snapshot(root) == before


@pytest.mark.parametrize('mutation', ['dangling', 'duplicate', 'legacy', 'missing_repo', 'wrong_repo'])
def test_repository_reconciliation_reports_and_never_repairs(setup, cron, mutation):
    config, _, _, root = setup
    result, _ = create(setup)
    path = root / 'config/repositories.json'
    store = read_json(path)
    repo = store['repositories'][0]
    if mutation == 'dangling':
        repo['job_ids'].append(str(uuid4()))
    elif mutation == 'duplicate':
        repo['job_ids'].append(result['job_id'])
    elif mutation == 'legacy':
        repo['used_by'] = ['config_local']
    elif mutation == 'missing_repo':
        store['repositories'].pop(0)
    else:
        repo['job_ids'] = repo['source_job_ids'] = []
    atomic_write_json(path, store)
    before = snapshot(root)
    report = reconcile_repository_usage(config)
    assert not report['ok'] and report['reconciled_repository_keys'] == []
    with pytest.raises(JobValidationError):
        read_repository_store_for_api(config)
    with pytest.raises(JobValidationError):
        edit(setup, result['job_id'], job_name='Changed')
    assert snapshot(root) == before and cron == []


def test_alias_resolution_is_exact_bounded_logged_and_conflicts_rejected(setup, caplog):
    config = setup[0]
    first, meta = create(setup)
    meta['legacy_job_keys'] = ['Config_local']
    atomic_write_json(Path(first['metadata_path']), meta)
    second, other = create(setup, archive_prefix='Second')
    for payload in [{'job_key': 'config_local'}, {'job_key': 'Config'},
                    {'job_id': second['job_id'], 'job_key': 'Config_local'}, {'job_id': '../Config'}]:
        with pytest.raises(JobValidationError):
            resolve_request_job_id(config, payload, endpoint='jobs/run')
    with pytest.raises(JobValidationError):
        resolve_request_job_id(config, {'job_key': 'Config_local'}, endpoint='wizard/save')
    assert resolve_request_job_id(config, {'job_id': first['job_id'], 'job_key': 'Config_local'}, endpoint='jobs/enabled') == first['job_id']
    assert 'Deprecated job_key request' in caplog.text
    other['legacy_job_keys'] = ['Config_local']
    atomic_write_json(Path(second['metadata_path']), other)
    with pytest.raises(JobValidationError, match='conflicting owners'):
        resolve_request_job_id(config, {'job_key': 'Config_local'}, endpoint='jobs/run')


def test_discovery_rejects_filename_mismatch_and_never_moves_legacy_files(setup):
    _, _, scripts, root = setup
    result, meta = create(setup)
    legacy = scripts / 'config/jobs'
    legacy.mkdir(parents=True)
    old = legacy / 'config_local.json'
    old.write_text('{"legacy":"must stay here"}')
    before = old.read_bytes()
    assert discover_jobs(scripts, root)[0].job_id == result['job_id']
    assert old.read_bytes() == before
    Path(result['metadata_path']).rename(root / 'config/jobs' / (str(uuid4()) + '.json'))
    with pytest.raises(JobValidationError, match='filename'):
        discover_jobs(scripts, root)


def test_http_control_boundaries_accept_uuid_and_keep_service_separate(setup, cron):
    from borg_backup_ui import BackupUIHandler
    config = setup[0]
    result, _ = create(setup)
    handler = object.__new__(BackupUIHandler)
    handler.config = config
    body = {'job_id': result['job_id'], 'cron': '0 2 * * *', 'enabled': True}
    handler._read_json_body = lambda: body
    assert handler._put_schedule()['saved']
    body['enabled'] = False
    assert handler._put_job_enabled()['job_id'] == result['job_id']
    assert handler._delete_schedule()['deleted']
    body.clear()
    body.update(service='restore_test', cron='0 4 * * *', enabled=True)
    assert handler._put_schedule()['saved']
    body['job_id'] = result['job_id']
    with pytest.raises(JobValidationError):
        handler._put_schedule()


def test_manual_prune_resolves_uuid_and_never_prunes_prefixes_separately(setup):
    from check_api import CheckManager
    result, _ = create(setup)
    repository = read_json(setup[3] / 'config/repositories.json')['repositories'][0]
    manager = CheckManager()
    cmd = manager._repository_command(setup[0], repository, '/synthetic/repo', 'prune', 'quick', job_id=result['job_id'])
    assert cmd.count('--glob-archives') == 1 and cmd[cmd.index('--glob-archives') + 1] == 'Exact.Prefix_1-*'
    edit(setup, result['job_id'], archive_prefix='Second')
    with pytest.raises(JobValidationError, match='Combined prefix retention'):
        manager._repository_command(setup[0], repository, '/synthetic/repo', 'prune', 'quick', job_id=result['job_id'])


def test_two_concurrent_schedule_saves_retain_both_jobs(setup, cron):
    import threading
    first, _ = create(setup)
    second, _ = create(setup, archive_prefix='Second')
    barrier, errors = threading.Barrier(2), []
    def save(job_id):
        try:
            barrier.wait(timeout=5)
            save_schedule(setup[0], job_id, '0 2 * * *', True)
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=save, args=(row['job_id'],)) for row in [first, second]]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert errors == []
    assert set(get_schedules(setup[0])) == {first['job_id'], second['job_id']}
    assert len(cron[-1]) == 2


def test_repository_deletion_stays_blocked_for_linked_uuid(setup, monkeypatch):
    from repositories_api import prepare_repository_lifecycle
    import jobs_api, restore_api
    from check_api import CheckManager
    result, _ = create(setup)
    monkeypatch.setattr(jobs_api, 'is_resource_active', lambda *_: False)
    monkeypatch.setattr(restore_api, 'list_restore_runs', lambda *_: {})
    monkeypatch.setattr(CheckManager, 'get_state', lambda _: {})
    preview = prepare_repository_lifecycle(setup[0], 'repo_a', 'delete')
    assert not preview['allowed'] and 'jobs_linked' in preview['blockers']
    assert preview['job_ids'] == [result['job_id']]
    assert 'job_keys' not in preview


def test_run_preparation_cannot_launch_the_legacy_runner(setup, monkeypatch):
    from borg_backup_ui import BackupUIHandler
    import jobs_api
    result, _ = create(setup)
    handler = object.__new__(BackupUIHandler)
    handler.config = setup[0]
    handler._require_data_dir_ready = lambda: None
    handler._read_json_body = lambda: {'job_id': result['job_id']}
    monkeypatch.setattr(jobs_api.JobManager, 'start', lambda *_args, **_kwargs: pytest.fail('legacy runner must not start'))
    with pytest.raises(JobValidationError) as exc:
        handler._post_run_job()
    assert exc.value.api_code == 'job_runtime_cutover_pending'


def test_prune_scope_is_validated_before_mounting_storage(setup, monkeypatch):
    from check_api import CheckManager
    from repositories_api import read_repository_store
    import smb_profiles_api, storage_objects_api
    result, _ = create(setup)
    edit(setup, result['job_id'], archive_prefix='Second')
    store = read_storage_store(setup[0])
    store['storages'][0].update(location='smb', storage_type='smb', profile_key='synthetic')
    monkeypatch.setattr(storage_objects_api, 'read_storage_store', lambda _: store)
    monkeypatch.setattr(smb_profiles_api, 'run_smb_profile_action', lambda *_: pytest.fail('invalid scope must not mount'))
    ok, message = CheckManager().start_repository(setup[0], 'repo_a', action='prune', job_id=result['job_id'])
    assert not ok and 'Combined prefix retention' in message
