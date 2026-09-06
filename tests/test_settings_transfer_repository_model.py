"""Explicit source/target identity, complete dependencies and rollback (#478)."""
from copy import deepcopy
import base64
import hashlib
from pathlib import Path
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from inventory_store import atomic_write_json
from job_store import read_jobs, read_json
from job_model import new_job_defaults
from job_transfer import apply_import, reference_map, validate_bundle
from settings_transfer_api import export_jobs_bundle, import_jobs_bundle, preview_jobs_bundle


def installation(root, *, jobs=1):
    config = {"BACKUP_SCRIPTS_DIR": str(root), "STATUS_DIR": str(root / "status"), "RESTORE_TEST_STATUS_DIR": str(root / "restore-status")}
    rows = []
    for number in range(jobs):
        row = {**new_job_defaults(), "job_id": str(uuid4()), "name": "Same friendly name", "repository_key": "repo",
               "source_paths": [str(root / "source")], "archive_prefixes": ["prefix" + str(number)]}
        atomic_write_json(root / "config/jobs" / (row["job_id"] + ".json"), row)
        rows.append(row)
    ids = [row["job_id"] for row in rows]
    atomic_write_json(root / "config/repositories.json", {"schema_version": 1, "repositories": [
        {"repository_key": "repo", "storage_key": "local", "relative_path": "repo", "encryption": "none",
         "job_ids": ids, "source_job_ids": ids}]})
    atomic_write_json(root / "config/storages.json", {"schema_version": 1, "storages": [
        {"storage_key": "local", "storage_type": "local", "location": "local", "base_path": "/mnt/synthetic-repository-target"}]})
    atomic_write_json(root / "config/schedules.json", {job_id: {"enabled": True, "cron": "0 4 * * *"} for job_id in ids})
    return config, rows


@pytest.fixture(autouse=True)
def cron(monkeypatch):
    monkeypatch.setattr("schedule_api._update_crontab", lambda lines: None)


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file() and p.name != '.inventory.lock'}


def test_export_filters_every_dependency_and_preview_has_no_implicit_target(tmp_path):
    config, jobs = installation(tmp_path / 'source', jobs=2)
    bundle = export_jobs_bundle(config, [jobs[0]['job_id']])['bundle']
    assert bundle['format'] == 'bbui-job-bundle-v3'
    assert bundle['repositories'][0]['job_ids'] == [jobs[0]['job_id']]
    assert list(bundle['schedules']) == [jobs[0]['job_id']]
    assert bundle['references'] == reference_map(bundle)
    preview = preview_jobs_bundle(config, bundle)
    assert preview['jobs'][0]['job_id'] == jobs[0]['job_id']
    assert preview['jobs'][0]['suggested_mode'] == 'new'
    assert 'target_job_id' not in preview['jobs'][0]
    assert len(preview['current_jobs']) == 2


def test_new_import_allocates_and_remaps_all_included_references(tmp_path):
    config, jobs = installation(tmp_path / 'source')
    bundle = export_jobs_bundle(config)['bundle']
    target = {'BACKUP_SCRIPTS_DIR': str(tmp_path / 'target')}
    result = import_jobs_bundle(target, bundle, dry_run=False)
    old = jobs[0]['job_id']; new = result['id_map'][old]
    assert new != old
    assert list(read_jobs(tmp_path / 'target/config/jobs')) == [new]
    assert list(read_json(tmp_path / 'target/config/schedules.json')) == [new]
    assert read_json(tmp_path / 'target/config/repositories.json')['repositories'][0]['job_ids'] == [new]


def test_same_id_does_not_implicitly_merge_and_explicit_merge_keeps_target(tmp_path):
    config, jobs = installation(tmp_path / 'source')
    bundle = export_jobs_bundle(config)['bundle']; old = jobs[0]['job_id']
    with pytest.raises(ValueError, match='overlap'):
        import_jobs_bundle(config, bundle, dry_run=False)
    with pytest.raises(ValueError, match='UUIDv4'):
        import_jobs_bundle(config, bundle, mode='merge', dry_run=False)
    result = import_jobs_bundle(config, bundle, mode='merge', target_jobs={old: old}, dry_run=False)
    assert result['id_map'] == {old: old}
    copied = import_jobs_bundle(config, bundle, archive_prefixes={old: 'independent'}, dry_run=False)
    assert copied['id_map'][old] != old


def test_explicit_merge_into_different_id_retains_target_aliases_and_history(tmp_path):
    config, source = installation(tmp_path / 'source')
    target, rows = installation(tmp_path / 'target')
    sid, tid = source[0]['job_id'], rows[0]['job_id']
    rows[0]['legacy_job_keys'] = ['retained_alias']
    rows[0]['archive_prefixes'] = ['previous']
    atomic_write_json(tmp_path / 'target/config/jobs' / (tid + '.json'), rows[0])
    result = import_jobs_bundle(target, export_jobs_bundle(config)['bundle'], mode='merge', target_jobs={sid: tid}, dry_run=False)
    assert result['id_map'] == {sid: tid}
    job = read_jobs(tmp_path / 'target/config/jobs')[tid]
    assert job['legacy_job_keys'] == ['retained_alias']
    assert job['archive_prefixes'] == ['prefix0', 'previous']


@pytest.mark.parametrize('damage', ['references', 'schedule', 'repository', 'duplicate', 'unknown_dependency'])
def test_invalid_or_partial_bundle_rejected_before_writes(tmp_path, damage):
    source, jobs = installation(tmp_path / 'source')
    bundle = export_jobs_bundle(source)['bundle']
    if damage == 'references': bundle['references']['jobs'] = {}
    if damage == 'schedule': bundle['schedules'][str(uuid4())] = {'cron':'0 4 * * *', 'enabled': True}
    if damage == 'repository': bundle['repositories'] = []
    if damage == 'duplicate': bundle['jobs'].append(deepcopy(jobs[0]))
    if damage == 'unknown_dependency': bundle['dependent_records'] = {'pending': 'unhandled'}
    target, _ = installation(tmp_path / 'target', jobs=0)
    before = snapshot(tmp_path / 'target')
    with pytest.raises(ValueError): import_jobs_bundle(target, bundle, dry_run=False)
    assert snapshot(tmp_path / 'target') == before


def test_empty_selection_does_not_import_all(tmp_path):
    source, _ = installation(tmp_path / 'source')
    target, _ = installation(tmp_path / 'target', jobs=0)
    before = snapshot(tmp_path / 'target')
    result = import_jobs_bundle(target, export_jobs_bundle(source)['bundle'], selected_jobs=[], dry_run=False)
    assert result['imported_count'] == 0
    assert snapshot(tmp_path / 'target') == before


def test_secret_validation_and_io_failure_roll_back_the_entire_plan(tmp_path, monkeypatch):
    source, jobs = installation(tmp_path / 'source'); sid = jobs[0]['job_id']
    target, _ = installation(tmp_path / 'target', jobs=0)
    bundle = export_jobs_bundle(source)['bundle']
    before = snapshot(tmp_path / 'target')
    secrets = {'passphrase_files': {'repo': {'content_b64': 'invalid', 'sha256': 'bad'}}}
    with pytest.raises(ValueError, match='Protected file'):
        apply_import(target, bundle, dry_run=False, secret_payload=secrets)
    assert snapshot(tmp_path / 'target') == before
    secret = b'synthetic passphrase\n'
    secrets['passphrase_files']['repo'] = {'content_b64': base64.b64encode(secret).decode(), 'sha256': hashlib.sha256(secret).hexdigest(), 'path': str(tmp_path/'untrusted-target')}
    import job_store
    write = job_store.atomic_write_json
    def fail_once(path, payload):
        if Path(path).name == 'schedules.json': raise OSError('injected write failure')
        write(path, payload)
    monkeypatch.setattr(job_store, 'atomic_write_json', fail_once)
    with pytest.raises(OSError): apply_import(target, bundle, dry_run=False, secret_payload=secrets)
    assert snapshot(tmp_path / 'target') == before
    assert not (tmp_path / 'untrusted-target').exists()


def test_cron_failure_restores_inventory_and_old_schedule(tmp_path, monkeypatch):
    config, rows = installation(tmp_path / 'source'); sid = rows[0]['job_id']
    bundle = export_jobs_bundle(config)['bundle']; bundle['jobs'][0]['name'] = 'Changed'
    before = snapshot(tmp_path / 'source'); calls = []
    def cron(lines):
        calls.append(lines)
        if len(calls) == 1: raise OSError('cron unavailable')
    monkeypatch.setattr('schedule_api._update_crontab', cron)
    with pytest.raises(OSError): import_jobs_bundle(config, bundle, mode='merge', target_jobs={sid: sid}, dry_run=False)
    assert snapshot(tmp_path / 'source') == before
    assert len(calls) == 2


def test_authenticated_job_import_restores_secrets_to_owned_paths_only(tmp_path):
    from settings_transfer_api import export_jobs_bundle_encrypted, import_jobs_bundle_encrypted
    source, jobs = installation(tmp_path / 'source')
    secret = tmp_path / 'source/secrets/.borg-passphrase-repo'
    secret.parent.mkdir(); secret.write_bytes(b'protected synthetic value')
    path = tmp_path / 'source/config/repositories.json'; store = read_json(path)
    store['repositories'][0]['passphrase_ref'] = str(secret)
    atomic_write_json(path, store)
    payload = export_jobs_bundle_encrypted(source, 'synthetic-password')
    target, _ = installation(tmp_path / 'target', jobs=0)
    empty = import_jobs_bundle_encrypted(target, 'synthetic-password', payload['payload_b64'], selected_jobs=[], dry_run=False)
    assert empty['restored_passphrases'] == 0
    assert not (tmp_path / 'target/secrets').exists()
    result = import_jobs_bundle_encrypted(target, 'synthetic-password', payload['payload_b64'], dry_run=False)
    restored = tmp_path / 'target/secrets/.borg-passphrase-repo'
    assert restored.read_bytes() == secret.read_bytes()
    assert restored.stat().st_mode & 0o777 == 0o600
    assert result['id_map'][jobs[0]['job_id']] != jobs[0]['job_id']


def test_legacy_v2_preview_conversion_keeps_one_source_map_and_new_destination_id(tmp_path):
    source, _ = installation(tmp_path / 'source', jobs=0)
    bundle = {'format': 'bbui-job-bundle-v2', 'jobs': [{
        'schema_version': 3, 'job_key': 'config_local', 'backup_type': 'config', 'location': 'local',
        'name': 'Old export', 'repository_key': 'repo', 'source_paths': ['/mnt/user/config'],
        'features': {'docker': True, 'vm': False}}],
        'repositories': [{'repository_key':'repo','storage_key':'local','relative_path':'repo','encryption':'none',
                          'used_by':['config_local'], 'source_job_keys':['config_local']}],
        'storages': read_json(tmp_path / 'source/config/storages.json')['storages'],
        'schedules': {'config_local': {'cron':'0 4 * * *','enabled':True}, 'restore_test': {'cron':'0 1 * * *','enabled':True}},
        'settings_payload': {'usb_profiles': [{'key':'unrelated'}]}}
    preview = preview_jobs_bundle(source, bundle)
    sid = preview['jobs'][0]['job_id']
    assert preview['legacy_conversion'] is True
    assert preview['legacy_source_ids'] == {'config_local': sid}
    result = import_jobs_bundle(source, bundle, dry_run=False, selected_jobs=[sid], legacy_source_ids=preview['legacy_source_ids'])
    new = result['id_map'][sid]
    assert new != sid
    job = read_jobs(tmp_path / 'source/config/jobs')[new]
    assert job['archive_prefixes'] == ['config-backup']
    assert job['docker_control']['mode'] == 'all'
    assert not {'job_key','backup_type','location','cache_reference'} & job.keys()
    assert list(read_json(tmp_path / 'source/config/schedules.json')) == [new]


def test_legacy_secure_bundle_selection_is_not_merged_by_old_key(tmp_path):
    from settings_transfer_api import _encrypt_authenticated_export, preview_jobs_bundle_encrypted, import_jobs_bundle_encrypted
    import json
    config, _ = installation(tmp_path / 'target', jobs=0)
    plain = {'format':'bbui-job-bundle-v2', 'jobs':[{'schema_version':3,'job_key':'old_local','backup_type':'old','location':'local',
             'name':'Legacy','repository_key':'repo','source_paths':['/mnt/user/old']}],
             'repositories':[{'repository_key':'repo','storage_key':'local','relative_path':'repo','encryption':'none'}],
             'storages':read_json(tmp_path/'target/config/storages.json')['storages'], 'schedules':{}}
    payload = {'format':'bbui-job-bundle-secure-v2','bundle':plain,'passphrase_files':{},'key_files':{}}
    encoded = base64.b64encode(_encrypt_authenticated_export(json.dumps(payload).encode(),'test-password')).decode()
    preview = preview_jobs_bundle_encrypted(config,'test-password',encoded)
    source_id = preview['jobs'][0]['job_id']
    result = import_jobs_bundle_encrypted(config,'test-password',encoded,selected_jobs=[source_id],
        legacy_source_ids=preview['legacy_source_ids'],dry_run=False)
    assert result['id_map'][source_id] != source_id
