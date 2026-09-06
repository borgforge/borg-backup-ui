"""Settings profile usage follows canonical IDs and current names (#479)."""
import pytest

from test_canonical_job_wizard import setup, create, edit
from config_api import get_settings_data
from inventory_store import atomic_write_json
from storage_objects_api import write_storage_store


@pytest.mark.parametrize('location,collection', [
    ('local', 'local_profiles'), ('usb', 'usb_profiles'),
    ('smb', 'smb_profiles'), ('storagebox', 'storage_profiles'),
])
def test_settings_usage_preserves_distinct_ids_and_tracks_rename(setup, monkeypatch, location, collection):
    config, _, _, root = setup
    monkeypatch.setattr('config_api._scan_per_repo_passphrases', lambda: [])
    monkeypatch.setattr('schedule_api._update_crontab', lambda rows: {})
    write_storage_store(config, {'storages': [{
        'storage_key': 'target', 'profile_key': 'target', 'display_name': 'Target',
        'storage_type': 'ssh' if location == 'storagebox' else location,
        'location': location, 'base_path': str(root / 'repositories'),
        'mount_path': str(root / 'repositories'), 'server': 'example.invalid',
        'share': 'backup', 'host': 'example.invalid', 'user': 'synthetic', 'port': '23',
        'username': 'synthetic', 'password_file': str(root / 'synthetic.cred'),
    }]})
    atomic_write_json(root / 'config' / 'repositories.json', {
        'schema_version': 1, 'repositories': [{
            'repository_key': 'repo_a', 'storage_key': 'target',
            'display_name': 'Repository', 'relative_path': 'repo_a',
            'encryption': 'none', 'job_ids': [], 'source_job_ids': [],
        }],
    })
    first, _ = create(setup, job_name='Same name', archive_prefix='first')
    second, _ = create(setup, job_name='Same name', archive_prefix='second')
    paths = list((root / 'config').rglob('*.json'))
    before = {path: path.read_bytes() for path in paths}

    profile = get_settings_data(config, include_storagebox_setup=False)[collection][0]
    assert profile['jobs_count'] == 2
    assert set(profile['job_refs']) == {
        f"Same name ({first['job_id']})", f"Same name ({second['job_id']})",
    }
    assert profile['repositories_count'] == 1
    assert profile['repository_refs'] == ['Repository']
    assert all(path.read_bytes() == raw for path, raw in before.items())

    edit(setup, first['job_id'], job_name='Renamed')
    profile = get_settings_data(config, include_storagebox_setup=False)[collection][0]
    assert profile['jobs_count'] == 2
    assert set(profile['job_refs']) == {
        f"Renamed ({first['job_id']})", f"Same name ({second['job_id']})",
    }
