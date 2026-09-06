"""Owned store integrity, typed reference maps and precise history deletion (#478)."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
from test_settings_transfer_repository_model import installation, snapshot
from inventory_store import atomic_write_json
from job_store import read_jobs, read_json
from identity_lifecycle import record_digest, read_owned, record_references, remap_records, validate_records, identity_health, deletion_plan
from job_actions import delete_job_configuration


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('BORG_UI_CONTROL_ROOT', str(tmp_path / 'controls'))
    monkeypatch.setattr('jobs_api.get_job_runtime_state', lambda *args: {'running': False})
    monkeypatch.setattr('schedule_api._update_crontab', lambda lines: None)


def full(root, jobs=1):
    config, rows = installation(root, jobs=jobs)
    config['BACKUP_CONF_SCHEMA_FILE'] = str(Path(__file__).resolve().parents[1] / 'runtime/config/backup.conf.example')
    (root / 'config/backup.conf').write_text('GLOBAL_DATA_DIR="' + str(root / 'data') + '"\n')
    return config, rows


def test_all_typed_reference_shapes_remap_without_touching_descriptors(tmp_path):
    config, jobs = full(tmp_path); old = jobs[0]['job_id']; new = str(uuid4())
    records = read_owned(config)
    records['status/run.status'] = {'kind': 'status', 'data': {'schema_version': 1, 'job_id': old, 'job_name_snapshot': old}}
    records['config/notification-state.json'] = {'kind': 'notification_state', 'data': {'schema_version': 1, 'last_sent': {'reminder:' + old + ':2026': 42}}}
    records['config/notification-deliveries.json'] = {'kind': 'notification_deliveries', 'data': {'schema_version': 1, 'deliveries': [{'schema_version': 1, 'job_id': old, 'source': 'backup_job'}]}}
    records['proof/' + old + '.test'] = {'kind': 'restore_test', 'data': {'schema_version': 1, 'job_id': old}}
    mapped = remap_records(records, {old: new})
    validate_records(mapped)
    assert {ref['job_id'] for ref in record_references(mapped)} == {new}
    assert mapped['status/run.status']['data']['job_name_snapshot'] == old
    assert 'proof/' + new + '.test' in mapped
    assert 'reminder:' + new + ':2026' in mapped['config/notification-state.json']['data']['last_sent']


def test_exact_history_confirmation_does_not_use_filename_prefix(tmp_path):
    config, jobs = full(tmp_path, jobs=2); first, other = [job['job_id'] for job in jobs]
    atomic_write_json(tmp_path / 'status/unrelated-name.status', {'schema_version': 1, 'job_id': first, 'job_name_snapshot': 'old display'})
    atomic_write_json(tmp_path / 'status' / (first + '-looks-owned.status'), {'schema_version': 1, 'job_id': other})
    preview = delete_job_configuration(config, first, preview=True)
    assert [row['file'] for row in preview['artifacts']] == ['status/unrelated-name.status']
    delete_job_configuration(config, first)
    assert (tmp_path / 'status/unrelated-name.status').exists()
    assert (tmp_path / 'status' / (first + '-looks-owned.status')).exists()
    health = identity_health(config)
    assert any(row['code'] == 'deleted_job_history_preserved' for row in health['findings'])


def test_deletion_requires_exact_unchanged_artifacts(tmp_path):
    config, jobs = full(tmp_path); job_id = jobs[0]['job_id']
    path = tmp_path / 'status/owned.status'
    atomic_write_json(path, {'schema_version': 1, 'job_id': job_id})
    preview = delete_job_configuration(config, job_id, preview=True)
    token = preview['artifacts'][0]['id']
    atomic_write_json(path, {'schema_version': 1, 'job_id': job_id, 'changed': True})
    with pytest.raises(ValueError, match='preview changed'):
        delete_job_configuration(config, job_id, confirmed_artifacts=[token])
    token = delete_job_configuration(config, job_id, preview=True)['artifacts'][0]['id']
    delete_job_configuration(config, job_id, confirmed_artifacts=[token])
    assert not path.exists()


def test_health_reports_duplicate_missing_dangling_and_history_without_contents(tmp_path):
    config, jobs = full(tmp_path); job_id = jobs[0]['job_id']
    duplicate = deepcopy(jobs[0]); duplicate['exclude_paths'] = ['private-rule-body']
    atomic_write_json(tmp_path / 'config/jobs/wrong.json', duplicate)
    atomic_write_json(tmp_path / 'config/jobs/missing.json', {'schema_version': 4, 'name': 'Missing ID'})
    atomic_write_json(tmp_path / 'config/schedules.json', {str(uuid4()): {'enabled': False, 'cron': ''}})
    result = identity_health(config)
    codes = {row['code'] for row in result['findings']}
    assert {'duplicate_job_id', 'missing_job_id', 'orphan_active_schedule'} <= codes
    assert 'private-rule-body' not in str(result)
    assert result['ok'] is False


def test_pending_job_deletion_is_blocked_and_history_pair_requires_both_records(tmp_path):
    config, jobs = full(tmp_path); job_id = jobs[0]['job_id']
    queue = tmp_path / 'config/notification-queue.json'
    atomic_write_json(queue, {'schema_version': 1, 'queue': [{'schema_version': 1, 'job_id': job_id, 'source': 'backup_job'}]})
    with pytest.raises(ValueError, match='pending notifications'):
        delete_job_configuration(config, job_id)
    atomic_write_json(queue, {'schema_version': 1, 'queue': []})
    rid = str(uuid4())
    row = {'schema_version': 1, 'job_id': job_id, 'restore_id': rid, 'state': 'done'}
    atomic_write_json(tmp_path / 'config/restore-history/index.json', {'schema_version': 1, 'runs': [row]})
    atomic_write_json(tmp_path / 'config/restore-history/runs' / (rid + '.json'), row)
    artifacts = delete_job_configuration(config, job_id, preview=True)['artifacts']
    assert len(artifacts) == 2
    with pytest.raises(ValueError, match='missing_restore_'):
        delete_job_configuration(config, job_id, confirmed_artifacts=[artifacts[0]['id']])
    delete_job_configuration(config, job_id, confirmed_artifacts=[row['id'] for row in artifacts])
    assert not (tmp_path / 'config/restore-history/runs' / (rid + '.json')).exists()




def test_existing_backup_conf_recovery_leaves_id_stores_and_history_unchanged(tmp_path):
    from config_api import backup_conf_snapshot, restore_conf_backup
    config, jobs = full(tmp_path)
    job_id = jobs[0]['job_id']
    atomic_write_json(tmp_path / 'status/history.status', {'schema_version':1,'job_id':job_id})
    before = {name: record_digest(record) for name, record in read_owned(config).items()}
    backup = backup_conf_snapshot(config)
    (tmp_path / 'config/backup.conf').write_text('GLOBAL_DATA_DIR="/mnt/user/changed"\n')
    restore_conf_backup(config, backup.name)
    assert {name: record_digest(record) for name, record in read_owned(config).items()} == before
    assert read_jobs(tmp_path / 'config/jobs')[job_id] == jobs[0]
