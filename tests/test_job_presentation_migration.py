"""Automatic icons survive conversion and only untouched jobs are repaired."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))

import job_presentation
from migration_barrier import block_writers, exclusive_migration, writer_lease
from migrations import identity_storage as storage, immutable_job_id_v1 as identity, registry
from migrations import job_presentation_v1 as repair
from test_identity_migration_assistant import installation, prepare, binding
from identity_contract_support import tree_bytes


def photos(installation, appearance=None):
    root, _, _, _, _ = installation
    appearance = dict(appearance or {})
    backup_type = appearance.pop('backup_type', 'photos')
    for path in list(root.rglob('*')):
        if path.is_file():
            data = path.read_bytes().replace(b'config_local', (backup_type + '_local').encode()).replace(b'config-backup', (backup_type + '-backup').encode())
            data = data.replace(b'"backup_type": "config"', ('"backup_type": "' + backup_type + '"').encode())
            path.write_bytes(data)
    path = root / 'data/config/jobs/config_local.json'
    path.rename(path.with_name(backup_type + '_local.json'))
    if appearance:
        path = path.with_name(backup_type + '_local.json')
        value = json.loads(path.read_text())
        value.update(appearance)
        path.write_text(json.dumps(value))


@pytest.fixture
def migrated(installation, monkeypatch, request):
    photos(installation, getattr(request, 'param', None))
    root, config, assistant, _, _ = installation
    # Produce authentic old-plan/snapshot bytes with the previously shipped
    # omission, then run its normal explicitly approved conversion.
    with monkeypatch.context() as old:
        old.setattr(job_presentation, 'legacy_presentation_defaults', lambda _: {})
        old.setattr(registry, 'MIGRATIONS', [registry.immutable_job_id_activation, registry.canonical_backup_conf_v1])
        status = prepare(installation)
        assert status['stage'] == 'backup_ready', status
        assistant.acknowledge({**binding(status), 'independent_backup_ack': True})
        assert assistant.apply(binding(status), background=False)['status'] == 'applied'
    path = next((root / 'data/config/jobs').glob('*.json'))
    return root, config, path


def run(config):
    block_writers(config)
    with exclusive_migration(config):
        return registry.run_startup_migrations(config)


@pytest.mark.parametrize('appearance', [{}, {'icon': '', 'icon_color': ''}, {'icon': 'server', 'icon_color': 'blue'}])
def test_new_conversion_materializes_only_automatic_icon(installation, appearance):
    photos(installation, appearance)
    root, _, _, _, _ = installation
    before = tree_bytes(root)
    result = identity.build_plan(installation[1], control_root=root / 'run')
    job = next(iter(result['jobs'].values()))
    assert job['icon'] == (appearance.get('icon') or 'photos')
    assert job.get('icon_color') == appearance.get('icon_color')
    assert tree_bytes(root) == before


@pytest.mark.parametrize(('backup_type', 'icon', 'color', 'expected'), [
    ('vms', 'server', '', {'icon_color': 'green'}),
    ('photos', 'database', '', {'icon_color': 'violet'}),
    ('appdata', 'documents', '', {'icon_color': 'orange'}),
    ('flash', 'server', '', {'icon_color': 'blue'}),
    ('custom_type', 'flash', '', {'icon_color': 'gray'}),
    ('custom_type', 'server', '', {}),
    ('photos', 'photos', '', {}),
    ('vms', 'server', 'pink', {}),
    ('photos', 'database', 'unrecognized-explicit-value', {}),
])
def test_legacy_color_materialization_uses_only_recorded_type_and_existing_palette(backup_type, icon, color, expected):
    source = {'backup_type': backup_type, 'icon': icon, 'icon_color': color, 'name': 'Unrelated Photos display name'}
    assert job_presentation.legacy_presentation_defaults(source) == expected
    assert source['icon'] == icon and source['icon_color'] == color


@pytest.mark.parametrize(('backup_type', 'icon', 'expected'), [
    ('vms', 'server', 'green'), ('photos', 'database', 'violet'), ('custom_type', 'flash', 'gray'),
])
def test_new_conversion_preserves_list_color_for_explicit_icon(installation, backup_type, icon, expected):
    photos(installation, {'backup_type': backup_type, 'icon': icon, 'icon_color': ''})
    root, config, _, _, _ = installation
    before = tree_bytes(root)
    result = identity.build_plan(config, control_root=root / 'run')
    job = next(iter(result['jobs'].values()))
    assert job['icon'] == icon and job['icon_color'] == expected
    assert 'backup_type' not in job
    assert tree_bytes(root) == before


def test_fresh_installation_never_creates_recovery(installation):
    root, config, _, _, _ = installation
    before = tree_bytes(root)
    assert repair.detect(config) == {'required': False, 'reason': 'no_identity_migration'}
    assert tree_bytes(root) == before
    assert registry.MIGRATIONS.index(repair) == registry.MIGRATIONS.index(registry.immutable_job_id_activation) + 1


@pytest.mark.parametrize('migrated', [{}, {'icon': '', 'icon_color': 'pink'}], indirect=True)
def test_untouched_job_repair_private_backup_audit_and_idempotency(migrated):
    root, config, path = migrated
    before = path.read_bytes()
    original_recovery = tree_bytes(root / 'migration')
    first = run(config)
    result = first['results'][repair.MIGRATION_ID]
    assert result['status'] == 'applied', result
    assert json.loads(path.read_text()) == {**json.loads(before), 'icon': 'photos'}
    backup = Path(result['details']['actions'][0]['backup'])
    assert backup.read_bytes() == before
    assert backup.parent.parent == root and backup.parent != root / 'migration'
    assert backup.stat().st_mode & 0o777 == 0o600
    assert backup.parent.stat().st_mode & 0o777 == 0o700
    assert tree_bytes(root / 'migration') == original_recovery
    again = run(config)
    assert again['results'][repair.MIGRATION_ID]['status'] == 'skipped'
    events = [json.loads(row) for row in (root / 'data/config/migrations.log.jsonl').read_text().splitlines()]
    pending = next(row for row in events if row.get('event') == 'migration_job_pending')
    assert pending['timestamp'] and pending['status'] == 'pending'
    assert pending['details']['job_id'] == path.stem
    assert any(row.get('event') == 'migration_applied' and row.get('migration_id') == repair.MIGRATION_ID for row in events)
    assert backup.read_bytes() == before


@pytest.mark.parametrize('change', ['name', 'icon', 'format'])
def test_later_user_edits_are_preserved_and_audited(migrated, change):
    root, config, path = migrated
    data = json.loads(path.read_text())
    if change != 'format':
        data[change] = 'My edit' if change == 'name' else 'server'
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    result = run(config)['results'][repair.MIGRATION_ID]
    assert result['status'] == 'skipped'
    assert result['details']['skipped'] == [{'job_id': path.stem, 'reason': 'changed_since_identity_migration'}]
    assert path.read_bytes() == before
    assert not list(root.glob('.job-presentation-v1-*'))


@pytest.mark.parametrize('migrated', [{'icon': 'server', 'icon_color': 'blue'}], indirect=True)
def test_explicit_original_presentation_is_not_changed(migrated):
    root, config, path = migrated
    before = path.read_bytes()
    result = run(config)['results'][repair.MIGRATION_ID]
    assert result['status'] == 'skipped'
    assert result['details']['skipped'][0]['reason'] == 'explicit_or_unchanged_presentation'
    assert path.read_bytes() == before
    assert not list(root.glob('.job-presentation-v1-*'))


@pytest.mark.parametrize(('migrated', 'expected'), [
    ({'backup_type': 'vms', 'icon': 'server', 'icon_color': ''}, 'green'),
    ({'backup_type': 'photos', 'icon': 'database', 'icon_color': ''}, 'violet'),
    ({'backup_type': 'custom_type', 'icon': 'flash', 'icon_color': ''}, 'gray'),
], indirect=['migrated'])
def test_verified_repair_preserves_original_list_color_without_changing_icon(migrated, expected):
    root, config, path = migrated
    before = path.read_bytes()
    original_recovery = tree_bytes(root / 'migration')
    result = run(config)['results'][repair.MIGRATION_ID]
    assert result['status'] == 'applied'
    assert json.loads(path.read_text()) == {**json.loads(before), 'icon_color': expected}
    assert result['details']['actions'][0]['appearance'] == {'icon_color': expected}
    assert Path(result['details']['actions'][0]['backup']).read_bytes() == before
    assert tree_bytes(root / 'migration') == original_recovery


@pytest.mark.parametrize('missing', ['manifest', 'blob'])
def test_missing_original_recovery_skips_cosmetic_repair(migrated, missing):
    root, config, path = migrated
    target = root / 'migration/snapshot/manifest.json' if missing == 'manifest' else next((root / 'migration/snapshot/files').iterdir())
    target.rename(target.with_name(target.name + '.removed-for-test'))
    before = path.read_bytes()
    result = run(config)
    assert result['status'] == 'ok'
    assert result['results'][repair.MIGRATION_ID]['details']['reason'] == 'original_recovery_unavailable'
    assert path.read_bytes() == before


def test_repair_requires_held_writer_exclusion(migrated):
    _, config, path = migrated
    before = path.read_bytes()
    with writer_lease(config):
        result = repair.apply(config)
        assert result['status'] == 'failed'
        assert result['details']['error'] == 'exclusive_migration_required'
    assert path.read_bytes() == before


def test_unavailable_private_backup_skips_without_mutating_job(migrated, monkeypatch):
    root, config, path = migrated
    before = path.read_bytes()
    original_recovery = tree_bytes(root / 'migration')

    def unavailable(*args, **kwargs):
        raise OSError('synthetic passphrase=DO-NOT-EXPOSE')

    monkeypatch.setattr(storage, '_publish_once', unavailable)
    result = run(config)
    assert result['status'] == 'ok'
    assert result['results'][repair.MIGRATION_ID]['details']['skipped'][0]['reason'] == 'private_recovery_unavailable'
    assert path.read_bytes() == before
    assert tree_bytes(root / 'migration') == original_recovery
    assert 'DO-NOT-EXPOSE' not in json.dumps(result)


def test_write_failure_restores_exact_before_bytes_and_blocks_later_migrations(migrated, monkeypatch):
    root, config, path = migrated
    before = path.read_bytes()
    original_recovery = tree_bytes(root / 'migration')
    write = repair.atomic_write_bytes
    failed = False

    def fail_after_write(destination, raw, **kwargs):
        nonlocal failed
        write(destination, raw, **kwargs)
        if not failed:
            failed = True
            raise OSError('synthetic passphrase=DO-NOT-EXPOSE')

    monkeypatch.setattr(repair, 'atomic_write_bytes', fail_after_write)
    result = run(config)
    assert result['status'] == 'failed'
    assert result['results'][repair.MIGRATION_ID]['details']['rollback'] == [{'job_id': path.stem, 'status': 'restored'}]
    assert result['results']['canonical_backup_conf_v1']['status'] == 'blocked'
    assert 'DO-NOT-EXPOSE' not in json.dumps(result)
    assert path.read_bytes() == before
    assert tree_bytes(root / 'migration') == original_recovery
    monkeypatch.setattr(repair, 'atomic_write_bytes', write)
    assert run(config)['results'][repair.MIGRATION_ID]['status'] == 'applied'


@pytest.mark.parametrize('migrated', [{}, {'backup_type': 'vms', 'icon': 'server', 'icon_color': ''}], indirect=True)
def test_interruption_after_job_publication_resumes_from_private_before_copy(migrated, monkeypatch):
    root, config, path = migrated
    before = path.read_bytes()
    original_recovery = tree_bytes(root / 'migration')
    write = repair.atomic_write_bytes

    def interrupted(destination, raw, **kwargs):
        write(destination, raw, **kwargs)
        raise SystemExit('synthetic interruption')

    monkeypatch.setattr(repair, 'atomic_write_bytes', interrupted)
    with pytest.raises(SystemExit):
        run(config)
    corrected = path.read_bytes()
    original = json.loads(before)
    expected = {'icon_color': 'green'} if original.get('icon') == 'server' else {'icon': 'photos'}
    assert json.loads(corrected) == {**original, **expected}
    monkeypatch.setattr(repair, 'atomic_write_bytes', lambda *args, **kwargs: pytest.fail('repeated job write'))
    result = run(config)['results'][repair.MIGRATION_ID]
    assert result['status'] == 'applied'
    assert result['details']['actions'] == [{'job_id': path.stem, 'action': 'already_applied'}]
    assert path.read_bytes() == corrected
    assert tree_bytes(root / 'migration') == original_recovery
    assert next(root.glob('.job-presentation-v1-*/*.json')).read_bytes() == before
