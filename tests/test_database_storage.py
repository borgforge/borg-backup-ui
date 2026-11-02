"""Unraid writable-pool access and descriptor lifetime regressions (#591, #652)."""
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
import database_backup as backup
import database_api
from database_profiles import DatabaseError
from test_database_backups import config, profile, fake_export


@pytest.fixture
def pool(monkeypatch, profile):
    """Keep real directory/FD checks; substitute only mount/type detection."""
    mount = Path(profile['staging_mount'])
    mount.chmod(0o777)
    monkeypatch.setattr(backup.os.path, 'ismount', lambda p: p == mount)
    monkeypatch.setattr(backup, '_run', lambda *a, **kw: Mock(stdout='xfs'))
    return mount


def test_writable_pool_and_foreign_pool_owner_are_accepted(monkeypatch, profile, pool):
    original = backup.os.fstat
    def foreign_pool_owner(fd):
        info = original(fd)
        if info.st_ino == pool.stat().st_ino:
            values = list(info); values[4] = 65534; values[5] = 100
            return os.stat_result(values)
        return info
    monkeypatch.setattr(backup.os, 'fstat', foreign_pool_owner)
    with backup.open_staging(profile) as fd:
        assert backup._descriptor_path(fd).samefile(profile['staging_dir'])
    assert pool.stat().st_mode & 0o777 == 0o777
    with pytest.raises(OSError): os.fstat(fd)


@pytest.mark.parametrize('mode', [0o755, 0o770, 0o777])
def test_normal_dump_directory_modes_are_preserved(profile, pool, mode):
    Path(profile['staging_dir']).chmod(mode)
    assert backup.staging_root(profile) == Path(profile['staging_dir'])
    assert Path(profile['staging_dir']).stat().st_mode & 0o777 == mode


def test_foreign_dump_owner_is_accepted(monkeypatch, profile, pool):
    original = backup.os.fstat
    inode = Path(profile['staging_dir']).stat().st_ino
    def foreign_dump_owner(fd):
        info = original(fd)
        if info.st_ino == inode:
            values = list(info); values[4] = os.geteuid() + 1
            return os.stat_result(values)
        return info
    monkeypatch.setattr(backup.os, 'fstat', foreign_dump_owner)
    assert backup.staging_root(profile) == Path(profile['staging_dir'])


def test_only_export_creates_missing_direct_child(profile, pool):
    root = Path(profile['staging_dir']); root.rmdir()
    with pytest.raises(DatabaseError, match='storage_missing'):
        backup.staging_root(profile, require_space=False)
    assert not root.exists()
    backup.staging_root(profile)
    assert root.stat().st_mode & 0o777 == 0o755
    assert pool.stat().st_mode & 0o777 == 0o777


def test_missing_mount_and_unsupported_filesystem_do_not_create(monkeypatch, profile, pool):
    root = Path(profile['staging_dir']); root.rmdir()
    monkeypatch.setattr(backup.os.path, 'ismount', lambda p: False)
    with pytest.raises(DatabaseError, match='storage_mount'): backup.staging_root(profile)
    monkeypatch.setattr(backup.os.path, 'ismount', lambda p: True)
    monkeypatch.setattr(backup, '_run', lambda *a, **kw: Mock(stdout='tmpfs'))
    with pytest.raises(DatabaseError, match='storage_filesystem'): backup.staging_root(profile)
    assert not root.exists()


@pytest.mark.parametrize('component', ['mount', 'intermediate', 'dump'])
def test_symlink_components_are_rejected(profile, pool, component):
    root = Path(profile['staging_dir'])
    if component == 'mount':
        alias = pool / 'alias'; alias.symlink_to(pool, target_is_directory=True)
        profile.update(staging_mount=str(alias), staging_dir=str(alias / root.name))
    elif component == 'intermediate':
        alias = pool / 'alias'; alias.symlink_to(pool, target_is_directory=True)
        profile['staging_dir'] = str(alias / root.name)
    else:
        root.rmdir(); root.symlink_to(pool, target_is_directory=True)
    with pytest.raises(DatabaseError, match='storage_path'): backup.staging_root(profile)


def test_nested_dump_under_writable_parent(profile, pool):
    parent = pool / 'shared'; parent.mkdir(mode=0o777); parent.chmod(0o777)
    root = parent / 'private'; root.mkdir(mode=0o700)
    profile['staging_dir'] = str(root)
    assert backup.staging_root(profile) == root


def test_path_replacement_during_export_cannot_redirect_io(config, profile, pool, monkeypatch):
    fake_export(monkeypatch, profile)
    root = Path(profile['staging_dir']); original = root.with_name('original')
    def replace_during_probe(*args):
        root.rename(original)
        root.mkdir(mode=0o700)
        return {'server_version':'11.4.9', 'client_version':'11.4.9', 'extensions':[]}
    monkeypatch.setattr(backup, '_probe', replace_during_probe)
    results = backup.export_profiles(config, [profile], 'job', 'run')
    try:
        run = Path(results[0]['directory']).name
        import gzip
        assert gzip.decompress((original/run/'app.sql.gz').read_bytes()).startswith(b'CREATE TABLE')
        assert list(root.iterdir()) == []
        backup.write_manifest(results[0])
        assert copy.deepcopy(results) == json.loads(json.dumps(results))
        assert type(copy.deepcopy(results)[0]) is dict
        backup.cleanup_run(results[0], profile)
        assert list(original.iterdir()) == []
        assert list(root.iterdir()) == []
    finally:
        fd = results[0]._root_fd
        backup.close_results(results)
        backup.close_results(results)
        with pytest.raises(OSError): os.fstat(fd)


def test_retained_listing_reports_precise_storage_error(config, profile, pool, monkeypatch):
    monkeypatch.setattr(database_api, 'list_profiles', lambda config: {'profiles':[profile]})
    Path(profile['staging_dir']).rmdir()
    assert database_api.retained_runs(config) == {'runs':[], 'errors':[{'profile_id':profile['id'], 'profile_name':profile['name'], 'staging_dir':profile['staging_dir'], 'error_code':'database_storage_missing'}]}
    assert not Path(profile['staging_dir']).exists()


def test_retained_cleanup_on_writable_pool_and_no_fd_in_json(config, profile, pool, monkeypatch):
    fake_export(monkeypatch, profile)
    results = backup.export_profiles(config, [profile], 'job', 'run')
    backup.close_results(results)
    monkeypatch.setattr(database_api, 'list_profiles', lambda config: {'profiles':[profile]})
    listing = database_api.retained_runs(config)
    assert not listing['errors'] and listing['runs'][0]['directory'] == results[0]['directory']
    assert '/proc/' not in json.dumps(results)
    backup.cleanup_run(results[0]['directory'], profile)
    assert database_api.retained_runs(config)['runs'] == []


@pytest.mark.skipif(shutil.which('borg') is None, reason='Borg executable required')
@pytest.mark.parametrize('replaced', ['root', 'run'])
def test_real_borg_uses_held_directory_after_replacement(config, profile, pool, monkeypatch, tmp_path, replaced):
    fake_export(monkeypatch, profile)
    results = backup.export_profiles(config, [profile], 'job', 'run')
    try:
        root = Path(profile['staging_dir'])
        original = root if replaced == 'root' else Path(results[0]['directory'])
        original.rename(original.with_name('original'))
        original.mkdir(mode=0o777)
        for key in ('BORG_CACHE_DIR', 'BORG_SECURITY_DIR'):
            monkeypatch.setenv(key, str(tmp_path/key))
        monkeypatch.setenv('BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK', 'yes')
        repo = str(tmp_path/'repo')
        def borg(*args):
            return subprocess.check_output(['borg', *args], stderr=subprocess.PIPE, text=True, timeout=60)
        borg('init', '--encryption=none', repo)
        # The persistent configuration may be on FAT, which has no symlinks.
        symlink = backup.os.symlink
        def reject_persistent_alias(target, name, **kwargs):
            parent = Path(os.readlink(backup._descriptor_path(kwargs['dir_fd'])))
            if parent.is_relative_to(backup.data_root(config)):
                raise OSError('boot filesystem does not support symlinks')
            return symlink(target, name, **kwargs)
        monkeypatch.setattr(backup.os, 'symlink', reject_persistent_alias)
        archive = 'appdata-backup-2026-10-24_12-40-29'
        borg('create', repo+'::'+archive, *backup.borg_artifact_paths(results))
        before = borg('list', '--json', repo)
        with pytest.raises(subprocess.CalledProcessError):
            borg('create', repo+'::'+archive, *backup.borg_artifact_paths(results))
        assert borg('list', '--json', repo) == before
        paths = borg('list', '--short', repo+'::'+archive).splitlines()
        assert sorted(paths) == sorted(results[0]['archive_directory']+'/'+name for name in ['app.sql.gz','manifest.json'])
        backup.verify_archive(repo, archive, results)
        backup.write_manifest(results[0])
        alias = results[0]._alias_path
        assert alias.stat().st_mode & 0o777 == 0o700
        if replaced == 'root':
            backup.cleanup_run(results[0], profile, verified=True)
            assert not list(root.iterdir())
        else:
            with pytest.raises(DatabaseError, match='cleanup_blocked'):
                backup.cleanup_run(results[0], profile, verified=True)
            assert not list(original.iterdir())
        backup.close_results(results)
        assert not alias.exists()
    finally:
        backup.close_results(results)


def test_nested_unsupported_filesystem_is_rejected(monkeypatch, profile, pool):
    values = iter(['xfs', 'nfs'])
    monkeypatch.setattr(backup, '_run', lambda *a, **kw: Mock(stdout=next(values)))
    with pytest.raises(DatabaseError, match='storage_filesystem'): backup.staging_root(profile)


def test_export_failure_retains_manifest_and_releases_handle(config, profile, pool, monkeypatch):
    fake_export(monkeypatch, profile, 'export_failed')
    results = []
    try:
        with pytest.raises(DatabaseError, match='export_failed'):
            backup.export_profiles(config, [profile], 'job', 'run', results=results)
        assert results[0]['status'] == 'failed'
        fd = results[0]._root_fd
    finally:
        backup.close_results(results)
    with pytest.raises(OSError): os.fstat(fd)
    assert (Path(results[0]['directory'])/'app.sql.gz.partial').is_file()


def test_unraid_modes_and_ownership_allow_export_listing_and_cleanup(config, profile, pool, monkeypatch):
    fake_export(monkeypatch, profile)
    root = Path(profile['staging_dir'])
    root.chmod(0o777)
    results = backup.export_profiles(config, [profile], 'job', 'run')
    run = Path(results[0]['directory'])
    assert run.stat().st_mode & 0o777 == 0o755
    assert all(path.stat().st_mode & 0o777 == 0o644 for path in run.iterdir())
    backup.close_results(results)
    run.chmod(0o777)
    for path in run.iterdir():
        path.chmod(0o666)
    # Simulate Unraid's nobody:users ownership without requiring root in CI.
    original = backup.os.stat
    def foreign_owner(*args, **kwargs):
        info = original(*args, **kwargs)
        values = list(info); values[4] = 99; values[5] = 100
        return os.stat_result(values)
    monkeypatch.setattr(backup.os, 'stat', foreign_owner)
    monkeypatch.setattr(database_api, 'list_profiles', lambda _: {'profiles':[profile]})
    listing = database_api.retained_runs(config)
    assert len(listing['runs']) == 1 and not listing['errors']
    backup.cleanup_run(run, profile)
    assert list(root.iterdir()) == []
    assert root.stat().st_mode & 0o777 == 0o777


def test_run_replacement_cannot_redirect_export_or_manifest(config, profile, pool, monkeypatch, tmp_path):
    fake_export(monkeypatch, profile)
    root = Path(profile['staging_dir']); root.chmod(0o777)
    outside = tmp_path / 'outside'; outside.mkdir()
    sentinel = outside / 'manifest.json'; sentinel.write_text('keep')
    old = []
    def replace(*args):
        run = next(root.glob('bbui-*'))
        renamed = run.with_name('renamed-run')
        run.rename(renamed)
        run.symlink_to(outside, target_is_directory=True)
        old.append(renamed)
        return {'server_version':'11.4', 'client_version':'11.4', 'extensions':[]}
    monkeypatch.setattr(backup, '_probe', replace)
    results = backup.export_profiles(config, [profile], 'job', 'run')
    try:
        backup.write_manifest(results[0])
        assert (old[0] / 'app.sql.gz').is_file()
        assert sentinel.read_text() == 'keep'
        assert not (outside / 'app.sql.gz').exists()
        with pytest.raises(DatabaseError, match='cleanup_blocked'):
            backup.cleanup_run(results[0], profile)
    finally:
        backup.close_results(results)


def test_listing_permission_denied_and_missing_mount_are_distinct(config, profile, pool, monkeypatch):
    monkeypatch.setattr(database_api, 'list_profiles', lambda _: {'profiles':[profile]})
    monkeypatch.setattr(backup.os, 'access', lambda *a, **kw: False)
    assert database_api.retained_runs(config)['errors'][0]['error_code'] == 'database_storage_permissions'
    monkeypatch.setattr(backup.os.path, 'ismount', lambda _: False)
    assert database_api.retained_runs(config)['errors'][0]['error_code'] == 'database_storage_mount'


def test_listing_partial_results_preserves_available_profile(config, profile, pool, monkeypatch):
    fake_export(monkeypatch, profile)
    results = backup.export_profiles(config, [profile], 'job', 'run')
    backup.close_results(results)
    missing = dict(profile, id='db-bbbbbbbbbbbb', name='Missing database', staging_dir=str(pool/'absent'))
    monkeypatch.setattr(database_api, 'list_profiles', lambda _: {'profiles':[profile, missing]})
    response = database_api.retained_runs(config)
    assert len(response['runs']) == 1
    assert response['errors'][0]['profile_name'] == 'Missing database'
    assert response['errors'][0]['staging_dir'] == str(pool/'absent')
    assert not (pool/'absent').exists()


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo'])
def test_shared_manifest_links_and_special_files_are_rejected(config, profile, pool, monkeypatch, tmp_path, kind):
    fake_export(monkeypatch, profile)
    results = backup.export_profiles(config, [profile], 'job', 'run')
    run = Path(results[0]['directory'])
    backup.close_results(results)
    run.chmod(0o777)
    manifest = run / 'manifest.json'
    outside = tmp_path / 'outside.json'
    outside.write_bytes(manifest.read_bytes())
    original = outside.read_bytes()
    manifest.unlink()
    if kind == 'symlink':
        manifest.symlink_to(outside)
    elif kind == 'hardlink':
        os.link(outside, manifest)
    else:
        os.mkfifo(manifest)
    monkeypatch.setattr(database_api, 'list_profiles', lambda _: {'profiles':[profile]})
    listing = database_api.retained_runs(config)
    assert not listing['runs'] and listing['errors'][0]['error_code'] == 'database_storage_path'
    with pytest.raises(DatabaseError, match='cleanup_blocked'):
        backup.cleanup_run(run, profile)
    assert outside.read_bytes() == original
    assert (run / 'app.sql.gz').exists()


@pytest.mark.parametrize('suffix', ['new', 'new/deeper/TheTwist'])
def test_nested_directories_are_created_only_by_explicit_export(profile, pool, suffix):
    profile['staging_dir'] = str(pool / suffix)
    with pytest.raises(DatabaseError, match='storage_missing'):
        backup.staging_root(profile, require_space=False)
    assert not (pool / 'new').exists()
    backup.staging_root(profile)
    assert Path(profile['staging_dir']).is_dir()
    assert pool.stat().st_mode & 0o777 == 0o777


def test_nested_creation_rejects_symlink_and_foreign_filesystem(profile, pool, monkeypatch, tmp_path):
    outside = tmp_path / 'outside'; outside.mkdir()
    (pool / 'linked').symlink_to(outside)
    profile['staging_dir'] = str(pool / 'linked' / 'never-created')
    with pytest.raises(DatabaseError, match='storage_path'):
        backup.staging_root(profile)
    assert not (outside / 'never-created').exists()
    (pool / 'network').mkdir()
    profile['staging_dir'] = str(pool / 'network' / 'never-created')
    values = iter(['xfs','nfs'])
    monkeypatch.setattr(backup, '_run', lambda *a, **kw: Mock(stdout=next(values)))
    with pytest.raises(DatabaseError, match='storage_filesystem'):
        backup.staging_root(profile)
    assert not (pool / 'network' / 'never-created').exists()


def test_live_dump_progress_counts_streamed_bytes_and_finalization(config, profile, pool, monkeypatch):
    fake_export(monkeypatch, profile)
    messages = []
    def export(config, profile, cid, action, database, output, cancelled):
        for _ in range(4):
            output.write(b'CREATE TABLE example;\n' * 1000)
    monkeypatch.setattr(backup, '_operation', export)
    results = backup.export_profiles(config, [profile], 'job', 'run', live_progress=lambda value: messages.append(value.copy()))
    try:
        assert messages[0]['phase'] == 'checking'
        streamed = [m for m in messages if m['phase']=='exporting' and m['processed_bytes']]
        assert streamed and streamed[0]['processed_bytes'] < messages[-1]['processed_bytes']
        assert any(m['phase']=='finalizing' for m in messages)
        assert messages[-1]['processed_bytes'] == results[0]['files'][0]['uncompressed_bytes']
        assert messages[-1]['written_bytes'] == results[0]['files'][0]['bytes']
        assert all(m['database']=='app' and m['database_index']==1 for m in messages)
        assert 'CREATE TABLE' not in json.dumps(messages)
    finally:
        backup.close_results(results)


def test_live_operation_progress_is_in_memory_until_completion(config, profile, monkeypatch):
    import threading
    import time
    import database_profiles
    saved = database_profiles.save_profile(config, {k:v for k,v in profile.items() if k!='id'})['profile']
    entered, finish = threading.Event(), threading.Event()
    monkeypatch.setattr(database_api, 'reconcile_operations', lambda _:None)
    def export(*args, **kwargs):
        kwargs['live_progress']({'phase':'exporting','database':'digikam','processed_bytes':6*1024**3,'written_bytes':1024**3})
        entered.set()
        assert finish.wait(5)
    monkeypatch.setattr(database_api, 'export_profiles', export)
    state = database_api.start_operation(config, {'action':'dump','profile_id':saved['id']})
    try:
        assert entered.wait(3)
        live = database_api.operation_status(config, state['id'])
        assert live['status']=='running' and live['progress']['processed_bytes']==6*1024**3
        persisted = json.loads(database_api._state_path(config, state['id']).read_text())
        assert 'progress' not in persisted
    finally:
        finish.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        final = database_api.operation_status(config, state['id'])
        # The final file is published before the worker removes its live state.
        with database_api._guard:
            worker_finished = state['id'] not in database_api._active
        if final['status']!='running' and worker_finished: break
        time.sleep(.01)
    assert final['status']=='completed' and final['progress']['database']=='digikam'
    assert state['id'] not in database_api._live_progress


@pytest.mark.parametrize('identifier,origin', [
    ('test', 'manual'),
    ('11111111-1111-4111-8111-111111111111', 'job'),
    (None, 'unknown'), ('', 'unknown'), ('legacy-unknown', 'unknown'), ([], 'unknown'),
])
@pytest.mark.parametrize('archived', [False, True])
def test_retained_origin_uses_manifest_identity_without_rewriting(config, profile, monkeypatch, identifier, origin, archived):
    """Origins survive missing jobs and do not depend on export/archive success."""
    fake_export(monkeypatch, profile)
    results = backup.export_profiles(config, [profile], 'test', 'run')
    try:
        results[0].update(archived=archived, status='failed')
        if identifier is None:
            results[0].pop('job_id')
        else:
            results[0]['job_id'] = identifier
        backup.write_manifest(results[0])
        manifest = backup.result_directory(results[0]) / 'manifest.json'
        before = manifest.read_bytes()
        monkeypatch.setattr(database_api, 'list_profiles', lambda _: {'profiles':[profile]})
        response = database_api.retained_runs(config)
        assert not response['errors']
        row = response['runs'][0]
        assert row['origin'] == origin
        assert row['job_id'] == (identifier if origin == 'job' else '')
        assert row['archived'] is archived and row['status'] == 'failed'
        assert manifest.read_bytes() == before
    finally:
        backup.close_results(results)
