"""Support ZIP database snapshot contract and credential boundary (#703)."""
import base64
import json
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
import support_database_inventory as inventory
from support_bundle_api import create_support_bundle


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'config' / 'database-profiles.json'
    path.parent.mkdir()
    return path, {'BACKUP_SCRIPTS_DIR': str(tmp_path / 'scripts')}


def profile(**overrides):
    """Provide valid persisted configuration including sensitive non-export fields."""
    return {
        'id': 'db-0123456789ab', 'name': 'App database', 'engine': 'postgresql',
        'enabled': True, 'container': 'postgres', 'auth_mode': 'managed',
        'credential_id': 'database-private-reference-v001',
        'database_user': 'private_db_user', 'execution_user': 'private_exec_user',
        'staging_mount': '/mnt/cache', 'staging_dir': '/mnt/cache/db-dumps',
        'databases': ['app'], 'include_globals': True, 'retention': 'after_archive',
        'port': 5432, 'timeout_seconds': 600, 'min_free_mib': 2048,
        **overrides,
    }


def write_inventory(path, rows):
    path.write_text(json.dumps({'schema_version': 1, 'profiles': rows}))


@pytest.mark.parametrize('engine', ['postgresql', 'mysql', 'mariadb'])
def test_available_allowlisted_snapshot_keeps_disabled_profiles(source, engine):
    path, config = source
    row = profile(engine=engine, enabled=False, include_globals=False,
                  password='must-not-export', extension={'hidden': 'must-not-export'})
    write_inventory(path, [row])
    before = path.read_bytes()
    result = inventory.support_database_inventory(config)
    assert result['status'] == 'available'
    assert result['schema_version'] == 1
    assert result['scope'] == 'current_configuration_at_export'
    assert datetime.fromisoformat(result['captured_at']).utcoffset().total_seconds() == 0
    expected = {key: row[key] for key in inventory.PROFILE_FIELDS}
    assert result['profiles'] == [{**expected, 'engine_status': 'supported'}]
    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == ['database-profiles.json']


def test_retired_profiles_are_identifiable_not_executable(source):
    path, config = source
    write_inventory(path, [profile(engine='sqlite', include_globals=False)])
    result = inventory.support_database_inventory(config)
    assert result['status'] == 'available'
    assert result['profiles'][0]['engine_status'] == 'retired'
    assert result['profiles'][0]['engine'] == 'sqlite'


def test_empty_and_missing_have_distinct_meanings(source):
    path, config = source
    assert inventory.support_database_inventory(config)['status'] == 'missing'
    assert not path.exists()
    write_inventory(path, [])
    result = inventory.support_database_inventory(config)
    assert result['status'] == 'available' and result['profiles'] == []


@pytest.mark.parametrize('payload,status', [
    ('not JSON: private-value', 'invalid'),
    ('[]', 'invalid'),
    ('{"profiles": []}', 'invalid'),
    ('{"schema_version": true, "profiles": []}', 'invalid'),
    ('{"schema_version": 2, "profiles": []}', 'unsupported_schema'),
    ('{"schema_version": 1, "profiles": {}}', 'invalid'),
    (json.dumps({'schema_version': 1, 'profiles': [profile(), profile()]}), 'invalid'),
    (json.dumps({'schema_version': 1, 'profiles': [profile(), {'id': 'broken'}]}), 'invalid'),
    (json.dumps({'schema_version': 1, 'profiles': [profile(name={'password': 'private-value'})]}), 'invalid'),
    (json.dumps({'schema_version': 1, 'profiles': [profile(engine='unknown')]}), 'invalid'),
])
def test_invalid_inventory_has_fixed_status_without_partial_rows_or_values(source, payload, status):
    path, config = source
    path.write_text(payload)
    result = inventory.support_database_inventory(config)
    assert result['status'] == status
    assert result['profiles'] == []
    assert 'private-value' not in json.dumps(result)
    assert path.read_text() == payload


def test_invalid_encoding_and_size_limit(source, monkeypatch):
    path, config = source
    path.write_bytes(b'\xff')
    assert inventory.support_database_inventory(config)['status'] == 'invalid'
    monkeypatch.setattr(inventory, 'MAX_INVENTORY_BYTES', 64)
    path.write_bytes(b' ' * 65)
    assert inventory.support_database_inventory(config)['status'] == 'too_large'


def test_unreadable_inventory_does_not_expose_exception(source, monkeypatch):
    _, config = source

    def denied(*args, **kwargs):
        raise PermissionError('private-value')

    monkeypatch.setattr(inventory.os, 'open', denied)
    result = inventory.support_database_inventory(config)
    assert result['status'] == 'unreadable'
    assert 'private-value' not in json.dumps(result)


def test_symlink_and_fifo_are_rejected_without_reading(source):
    path, config = source
    secret = path.parent / 'secret.json'
    secret.write_text('PRIVATE-CREDENTIAL-CONTENT')
    path.symlink_to(secret)
    assert inventory.support_database_inventory(config)['status'] == 'unreadable'
    path.unlink()
    os.mkfifo(path)
    assert inventory.support_database_inventory(config)['status'] == 'unreadable'


@pytest.fixture
def zip_environment(source, monkeypatch):
    import config_api
    import system_health_api
    path, config = source
    monkeypatch.setattr(config_api, 'read_expanded_conf', lambda _: {})
    monkeypatch.setattr(config_api, 'get_conf_file', lambda _: path.parent / 'absent.conf')
    monkeypatch.setattr(system_health_api, 'get_system_health_data', lambda _: {})
    monkeypatch.setattr('support_bundle_api._plugin_log_candidates', lambda _: [])
    return path, config


def test_zip_resolves_job_ids_sanitizes_strings_and_never_reads_credentials(zip_environment, monkeypatch):
    path, config = zip_environment
    rows = [profile(id='db-ffffffffffff', name='Contact admin@example.test password=hidden-value'),
            profile(auth_mode='container', credential_file='/private/credential-file')]
    write_inventory(path, rows)
    jobs = path.parent / 'jobs'
    jobs.mkdir()
    (jobs / 'job.json').write_text(json.dumps({'database_profile_ids': [r['id'] for r in rows]}))
    real_open = inventory.os.open
    opened = []

    def checked_open(target, flags, *args, **kwargs):
        opened.append(Path(target))
        assert Path(target) == path
        return real_open(target, flags, *args, **kwargs)

    monkeypatch.setattr(inventory.os, 'open', checked_open)
    bundle = create_support_bundle(config, app_version='test')
    with zipfile.ZipFile(BytesIO(base64.b64decode(bundle['payload_b64']))) as archive:
        data = json.loads(archive.read('config/database-profiles.sanitized.json'))
        job = json.loads(archive.read('jobs/job.json'))
        report = json.loads(archive.read('support/sanitizing-report.json'))
        assert data['status'] == 'available'
        assert [p['id'] for p in data['profiles']] == sorted(job['database_profile_ids'])
        assert 'config/database-profiles.sanitized.json' in report['included_files']
        text = '\n'.join(archive.read(name).decode() for name in archive.namelist())
    for forbidden in ('private-reference', 'private_db_user', 'private_exec_user',
                      '/private/credential-file', 'credential_id', 'credential_file',
                      'auth_mode', 'admin@example.test', 'hidden-value'):
        assert forbidden not in text
    assert '[MASKED_EMAIL]' in text
    assert opened == [path]


@pytest.mark.parametrize('invalid', [False, True])
def test_zip_remains_available_and_reports_missing_or_invalid_inventory(zip_environment, invalid):
    path, config = zip_environment
    if invalid:
        path.write_text('{broken')
    bundle = create_support_bundle(config)
    with zipfile.ZipFile(BytesIO(base64.b64decode(bundle['payload_b64']))) as archive:
        data = json.loads(archive.read('config/database-profiles.sanitized.json'))
        report = json.loads(archive.read('support/sanitizing-report.json'))
        expected = 'invalid' if invalid else 'missing'
        assert data['status'] == expected
        assert data['profiles'] == []
        assert {'path': 'config/database-profiles.json', 'reason': expected} in report['skipped']


def test_corrupt_database_inventory_does_not_abort_job_health_or_support_export(zip_environment, monkeypatch):
    import system_health_api
    path, config = zip_environment
    path.write_text('{broken')
    jobs = path.parent / 'jobs'
    jobs.mkdir()
    (jobs / 'job.json').write_text(json.dumps({
        'job_key': 'job', 'database_profile_ids': ['db-0123456789ab'], 'source_paths': [],
    }))
    monkeypatch.setattr(system_health_api, 'get_system_health_data',
                        lambda cfg: {'jobs': system_health_api._collect_job_health(cfg, jobs)})
    bundle = create_support_bundle(config)
    with zipfile.ZipFile(BytesIO(base64.b64decode(bundle['payload_b64']))) as archive:
        assert json.loads(archive.read('config/database-profiles.sanitized.json'))['status'] == 'invalid'
        assert b'Database profile inventory is unavailable or corrupt' in archive.read('system/health.json')


def test_disabled_profile_health_error_does_not_abort_export(zip_environment, monkeypatch):
    import system_health_api
    path, config = zip_environment
    write_inventory(path, [profile(enabled=False)])
    jobs = path.parent / 'jobs'
    jobs.mkdir()
    (jobs / 'job.json').write_text(json.dumps({
        'job_key': 'job', 'database_profile_ids': ['db-0123456789ab'], 'source_paths': [],
    }))
    monkeypatch.setattr(system_health_api, 'get_system_health_data',
                        lambda cfg: {'jobs': system_health_api._collect_job_health(cfg, jobs)})
    bundle = create_support_bundle(config)
    with zipfile.ZipFile(BytesIO(base64.b64decode(bundle['payload_b64']))) as archive:
        data = json.loads(archive.read('config/database-profiles.sanitized.json'))
        assert data['status'] == 'available' and data['profiles'][0]['enabled'] is False
        assert b'profile_unavailable' in archive.read('system/health.json')
