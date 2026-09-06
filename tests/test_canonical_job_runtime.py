"""#475: immutable runtime ownership through edits, cancellation and reconnects."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
sys.path.insert(0, str(ROOT / 'runtime'))
sys.path.insert(0, str(ROOT / 'runtime/lib'))
from test_canonical_job_wizard import setup, create, edit
from inventory_store import atomic_write_json
from job_control import JobControl, read_control_state, request_cancel
from job_runs import create_run_context, read_run_context, descriptors, find_run_status, maintenance_context_unchanged
from jobs_api import JobManager, durable_running_states
from wizard_runner import _load_env_from_job, ResourceLockSet, _build_resources
from lib.backup_job import BackupJobConfig
from lib.status import BackupStatus, StatusStore


@pytest.fixture(autouse=True)
def confined(tmp_path, monkeypatch):
    monkeypatch.setenv('BORG_UI_CONTROL_ROOT', str(tmp_path / 'run'))
    monkeypatch.setattr('activity_log_capture.CAPTURE_ROOT', tmp_path / 'captures')
    monkeypatch.setattr('config_api.read_expanded_conf', lambda cfg: {
        'GLOBAL_LOG_DIR': str(tmp_path / 'logs'), 'STATUS_DIR': str(tmp_path / 'status'),
        'GLOBAL_BORG_CACHE_BASE': str(tmp_path / 'cache'),
        'LOCK_FILE_DIR': str(tmp_path / 'locks'), 'ABORT_ON_PARITY_CHECK': 'false',
        'NOTIFY_UNRAID_EVENTS': 'none', 'NOTIFY_EMAIL_EVENTS': 'none',
        'NOTIFY_APPRISE_EVENTS': 'none',
    })
    monkeypatch.setattr(JobManager, '_instance', JobManager())


def context(setup, monkeypatch, **changes):
    result, _ = create(setup, **changes)
    config = setup[0]
    config['STATUS_DIR'] = str(setup[3] / 'status')
    snapshot = create_run_context(config, result['job_id'])
    monkeypatch.setenv('BORG_UI_RUN_ID', snapshot['run_id'])
    return config, snapshot


def test_snapshot_freezes_all_operational_settings_and_exact_prefix(setup, monkeypatch):
    config, snapshot = context(setup, monkeypatch, archive_prefix='config', keep_daily='0', keep_weekly='1')
    job_id = snapshot['job_id']
    before = (Path(os.environ['BORG_UI_CONTROL_ROOT']) / snapshot['run_id'] / 'context.json').read_bytes()
    edit(setup, job_id, job_name='pfsense', archive_prefix='pfsense', repository_key='repo_b', keep_daily='31')
    env, meta = _load_env_from_job(job_id, setup[2], setup[3])
    assert env['BORG_REPO'] == snapshot['repository_snapshot']
    assert env['ARCHIVE_PREFIX'] == 'config'
    assert env['JOB_NAME'] == 'Synthetic job'
    assert env['BORG_KEEP_DAILY'] == '0' and env['BORG_KEEP_WEEKLY'] == '1'
    assert json.loads(env['BACKUP_PATHS_JSON']) == setup[1]['source_paths']
    assert env['JOB_ID'] == job_id and env['RUN_ID'] == snapshot['run_id']
    assert 'BACKUP_TYPE' not in env and not {'backup_type','job_key','location'}.intersection(meta)
    assert read_run_context(job_id, snapshot['run_id'])['context']['job']['name'] == 'Synthetic job'
    assert not maintenance_context_unchanged(config, snapshot)
    assert before == (Path(os.environ['BORG_UI_CONTROL_ROOT']) / snapshot['run_id'] / 'context.json').read_bytes()
    assert str(Path(env['BORG_CACHE_DIR']).name) == job_id
    assert _build_resources(env, meta)[0] == 'job:' + job_id


def test_explicit_cache_reference_survives_edits_and_duplicate_gets_new_cache(setup, monkeypatch):
    result, meta = create(setup)
    cache = setup[3] / 'cache/local_config'
    cache.mkdir(parents=True)
    (cache / 'files').write_bytes(b'existing chunk metadata')
    meta['cache_reference'] = {'repository_key':'repo_a', 'directory': str(cache), 'check_flag_file': str(cache / '.last_check_config')}
    atomic_write_json(Path(result['metadata_path']), meta)
    edit(setup, result['job_id'], job_name='pfsense', archive_prefix='pfsense')
    snapshot = create_run_context(setup[0], result['job_id'])
    monkeypatch.setenv('BORG_UI_RUN_ID', snapshot['run_id'])
    env, _ = _load_env_from_job(result['job_id'], setup[2], setup[3])
    assert env['BORG_CACHE_DIR'] == str(cache)
    assert env['BORG_CHECK_FLAG_FILE'].endswith('.last_check_config')
    assert (cache / 'files').read_bytes() == b'existing chunk metadata'
    edit(setup, result['job_id'], repository_key='repo_b')
    moved = create_run_context(setup[0], result['job_id'])
    monkeypatch.setenv('BORG_UI_RUN_ID', moved['run_id'])
    moved_env, _ = _load_env_from_job(result['job_id'], setup[2], setup[3])
    assert moved_env['BORG_CACHE_DIR'] == str(cache)
    assert moved_env['BORG_CHECK_FLAG_FILE'] != env['BORG_CHECK_FLAG_FILE']
    from job_model import apply_wizard_changes
    duplicate = apply_wizard_changes({'archive_prefix': 'duplicate'}, existing=meta, job_id=str(uuid4()), now='now', duplicate=True)
    assert 'cache_reference' not in duplicate


@pytest.mark.parametrize('wrong', ['config_local', '../job', '', '11111111-1111-1111-8111-111111111111'])
def test_run_context_rejects_mutable_and_invalid_identity(setup, monkeypatch, wrong):
    _, snapshot = context(setup, monkeypatch)
    with pytest.raises(ValueError):
        read_run_context(wrong, snapshot['run_id'])
    with pytest.raises(ValueError):
        read_run_context(snapshot['job_id'], wrong)


def test_run_context_cannot_be_rebound_or_overwritten(setup, monkeypatch):
    _, snapshot = context(setup, monkeypatch)
    with pytest.raises(ValueError):
        read_run_context(str(uuid4()), snapshot['run_id'])
    path = Path(os.environ['BORG_UI_CONTROL_ROOT']) / snapshot['run_id'] / 'context.json'
    assert path.stat().st_mode & 0o777 == 0o600
    snapshot['job_name_snapshot'] = 'changed'
    atomic_write_json(path, snapshot)
    with pytest.raises(ValueError):
        read_run_context(snapshot['job_id'], snapshot['run_id'])


def test_cancellation_is_bound_to_full_job_and_run_ids(setup, monkeypatch):
    _, snapshot = context(setup, monkeypatch)
    control = JobControl(snapshot['job_id'], snapshot['run_id'], snapshot=descriptors(snapshot))
    control.update_phase('borg_create', cancel_allowed=True)
    edit(setup, snapshot['job_id'], job_name='renamed', archive_prefix='renamed')
    state = request_cancel(snapshot['job_id'], snapshot['run_id'])
    assert state['job_name_snapshot'] == 'Synthetic job'
    assert control.is_cancel_requested()
    with pytest.raises(ValueError):
        request_cancel(str(uuid4()), snapshot['run_id'])
    with pytest.raises(FileNotFoundError):
        request_cancel(snapshot['job_id'], str(uuid4()))
    control.update_phase('recovering_docker', cancel_allowed=False)
    with pytest.raises(RuntimeError):
        request_cancel(snapshot['job_id'], snapshot['run_id'])
    control.update_phase('completed', cancel_allowed=False, finished=True, exit_code=0)
    with pytest.raises(FileNotFoundError):
        request_cancel(snapshot['job_id'], snapshot['run_id'])


def test_parallel_start_is_atomic_and_cannot_override_run_identity(setup, monkeypatch):
    _, snapshot = context(setup, monkeypatch)
    manager = JobManager.get()
    class Process:
        stdout = io.StringIO('done\n')
        def wait(self): return 0
    calls = []
    def launch(*args, **kwargs):
        calls.append(kwargs['env'])
        time.sleep(.02)
        return Process()
    monkeypatch.setattr('jobs_api.subprocess.Popen', launch)
    monkeypatch.setattr(manager, '_reader', lambda *args: None)
    def start(_):
        return manager.start(snapshot['job_id'], ['synthetic'], setup[3], {'BORG_UI_RUN_ID': str(uuid4()), 'BORG_UI_JOB_ID': str(uuid4())}, run_context=snapshot)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(start, range(8)))
    assert sum(ok for ok, _ in results) == 1 and len(calls) == 1
    assert calls[0]['BORG_UI_RUN_ID'] == snapshot['run_id']
    assert calls[0]['BORG_UI_JOB_ID'] == snapshot['job_id']
    state = manager.get_state(snapshot['job_id'])
    assert state['job_name_snapshot'] == 'Synthetic job'
    assert 'job_key' not in state


def test_status_is_attributed_by_payload_after_rename_and_legacy_remains_unassigned(setup, monkeypatch):
    config, snapshot = context(setup, monkeypatch)
    env, _ = _load_env_from_job(snapshot['job_id'], setup[2], setup[3])
    cfg = BackupJobConfig.from_config(env)
    status = BackupStatus(**cfg.identity_snapshot(), exit_code=0, status='success', timestamp='2026-09-06 02:00:00', log_file=env['LOG_FILE'])
    path = status.save(Path(config['STATUS_DIR']))
    assert snapshot['run_id'] in path.name and 'Synthetic-job' in path.name
    edit(setup, snapshot['job_id'], job_name='Renamed', archive_prefix='Renamed', repository_key='repo_b')
    renamed = path.with_name('a-completely-unrelated-name.status')
    path.rename(renamed)
    loaded = BackupStatus.from_file(renamed)
    assert loaded.key == snapshot['job_id'] and loaded.job_name_snapshot == 'Synthetic job'
    assert loaded.run_id == snapshot['run_id']
    assert find_run_status(config, snapshot['job_id'], snapshot['run_id'])['exit_code'] == 0
    legacy = renamed.with_name('2020-01-01_01-00-00_config_local.status')
    legacy.write_text(json.dumps({'backup_type':'config','location':'local','timestamp':'2020-01-01'}))
    old = legacy.read_bytes()
    rows = StatusStore(legacy.parent).load()
    assert len(rows) == 2 and len(StatusStore(legacy.parent).get_latest_per_key(rows)) == 1
    assert next(r for r in rows if r.source_path == legacy).run_id == ''
    assert legacy.read_bytes() == old
    data = json.loads(renamed.read_text())
    assert not {'backup_type','location','job_key'}.intersection(data)


def test_resource_lock_reconnect_and_exact_release_owner(setup, monkeypatch):
    config, snapshot = context(setup, monkeypatch)
    locks = ResourceLockSet(setup[3] / 'locks', snapshot['job_id'], run_id=snapshot['run_id'], snapshot=descriptors(snapshot), heartbeat_seconds=3600, log_file=snapshot['log_file'])
    try:
        assert locks.acquire(['repo:' + snapshot['repository_snapshot']])[0]
        edit(setup, snapshot['job_id'], job_name='changed', archive_prefix='changed')
        state = durable_running_states(config)[snapshot['job_id']]
        assert state['job_name_snapshot'] == 'Synthetic job' and state['run_id'] == snapshot['run_id']
        other = ResourceLockSet(setup[3] / 'locks', str(uuid4()), run_id=str(uuid4()))
        assert not other.acquire(['repo:' + snapshot['repository_snapshot']])[0]
        path = locks._owned[0]
        data = json.loads(path.read_text())
        data['run_id'] = str(uuid4())
        path.write_text(json.dumps(data))
        locks.release()
        assert path.exists()
    finally:
        locks.release()


def test_recovery_and_notification_use_run_snapshots(setup, monkeypatch):
    _, snapshot = context(setup, monkeypatch)
    from lib.runtime_recovery import record_runtime_stopped, pending_runtime_recovery_entries, mark_runtime_restarted
    from lib.notification_events import NotificationEvent, _queue_item_from_event, reminder_key
    fields = {key: value for key, value in descriptors(snapshot).items() if key not in {'started_at','log_file','file_activity'}}
    recovery_path = setup[3] / 'config/runtime-recovery.json'
    entry_id = record_runtime_stopped(recovery_path, kind='docker', targets=[{'id':'container-fixed-id','name':'db'}], snapshot=fields, log_file=snapshot['log_file'])
    edit(setup, snapshot['job_id'], job_name='changed', archive_prefix='changed')
    entry = pending_runtime_recovery_entries(recovery_path)[0]
    assert entry['job_id'] == snapshot['job_id'] and entry['job_name_snapshot'] == 'Synthetic job'
    assert entry['targets'] == [{'id':'container-fixed-id','name':'db'}]
    event = NotificationEvent(event_type='backup_warning',title='Synthetic', message='Test only', **fields)
    row = _queue_item_from_event({'id':'synthetic','name':'synthetic'}, event)
    assert row['run_id'] == snapshot['run_id'] and row['job_id'] == snapshot['job_id']
    assert 'job_key' not in row
    assert reminder_key('backup_overdue', snapshot['job_id'], '2026-09-06') == 'backup_overdue:' + snapshot['job_id'] + ':2026-09-06'
    mark_runtime_restarted(recovery_path, entry_id)
    assert pending_runtime_recovery_entries(recovery_path) == []


@pytest.mark.parametrize('activity', [False, True])
def test_real_runner_creates_exact_archive_and_retains_run_status(setup, monkeypatch, activity):
    import subprocess
    from migration_gate_support import ready_gate
    config, snapshot = context(setup, monkeypatch, file_activity=activity)
    root = setup[3]
    ready_gate(config, monkeypatch, root / "writer-gate")
    (root / 'source/file.txt').write_text('synthetic backup source')
    bin_dir = root / 'bin'; bin_dir.mkdir()
    (bin_dir / 'borg').symlink_to(ROOT / 'runtime/bin/borg/borg-linux-glibc231-x86_64-1.4.5')
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
    for key in ('BORG_CACHE_DIR','BORG_SECURITY_DIR','BORG_KEYS_DIR'):
        monkeypatch.setenv(key, str(root / key.lower()))
    monkeypatch.delenv('BORG_PASSCOMMAND', raising=False)
    monkeypatch.setenv('BORG_UI_DATA_ROOT', str(root))
    monkeypatch.setenv('UNRAID_DASHBOARD_WIDGET_FILE', str(root / 'widget.json'))
    repo = Path(snapshot['repository_snapshot']); repo.parent.mkdir(parents=True)
    # Repository-local durable I/O can exceed 30 seconds on slow development
    # filesystems even before plugin execution starts (#476).
    result = subprocess.run(['borg','init','--encryption=none',str(repo)],capture_output=True,text=True,timeout=120)
    assert result.returncode == 0, result.stderr
    manager = JobManager.get()
    ok, error = manager.start(snapshot['job_id'], [sys.executable,str(ROOT / 'api/wizard_runner.py')], root,
        {'BORG_UI_BORG_SCRIPTS_DIR':str(setup[2])}, run_context=snapshot)
    assert ok, error
    state = manager._states[snapshot['job_id']]
    deadline = time.monotonic() + 180
    while not state.finished and time.monotonic() < deadline:
        time.sleep(.02)
    if not state.finished:
        state.proc.terminate()
        state.proc.wait(timeout=5)
        pytest.fail('Synthetic backup did not complete')
    output = state.log_file.read_text() if activity else '\n'.join(state.lines)
    assert state.exit_code == 0, output
    rows = StatusStore(root / 'status').load()
    assert len(rows) == 1
    status = rows[0]
    assert status.job_id == snapshot['job_id'] and status.run_id == snapshot['run_id']
    assert status.archive_name.startswith('Exact.Prefix_1-') and '-backup-' not in status.archive_name
    assert status.repository_snapshot == str(repo) and status.repository_key_snapshot == 'repo_a'
    assert status.file_activity is activity and status.files_count == 1
    assert Path(status.log_file).is_file()
    assert not durable_running_states(config)
    # Completion remains readable after the WebUI loses all in-memory state.
    manager._states.clear()
    recovered = find_run_status(config, snapshot['job_id'], snapshot['run_id'])
    assert recovered['log_file'] == status.log_file and recovered['exit_code'] == 0
    if not activity:
        from check_api import CheckManager
        metadata_file = root / 'config/jobs' / (snapshot['job_id'] + '.json')
        metadata = json.loads(metadata_file.read_text())
        metadata['enabled'] = False
        atomic_write_json(metadata_file, metadata)
        repository = json.loads((root / 'config/repositories.json').read_text())['repositories'][0]
        command = CheckManager()._repository_command(config, repository, str(repo), 'prune', 'quick', job_id=snapshot['job_id'])
        manual = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert manual.returncode == 0, manual.stderr
    if activity:
        from activity_log import get_activity_window
        result = get_activity_window(config, {'job_id':[snapshot['job_id']], 'run_id':[snapshot['run_id']]})
        assert not result['running'] and result['exit_code'] == 0


def test_two_starters_cannot_steal_a_recovered_stale_resource_lock(setup, monkeypatch):
    _, snapshot = context(setup, monkeypatch)
    first = ResourceLockSet(setup[3] / 'locks', snapshot['job_id'],run_id=snapshot['run_id'],heartbeat_seconds=3600)
    second = ResourceLockSet(setup[3] / 'locks',str(uuid4()),run_id=str(uuid4()),heartbeat_seconds=3600)
    first.lock_dir.mkdir()
    path = first._lock_path('repo:synthetic')
    path.write_text('{corrupt stale record')
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda lock: lock.acquire(['repo:synthetic']), [first, second]))
        assert sum(ok for ok, _ in results) == 1
        winner = first if results[0][0] else second
        assert json.loads(path.read_text())['run_id'] == winner.run_id
        assert first._lock_path('repo:/a/b') != first._lock_path('repo:/a_b')
    finally:
        first.release(); second.release()


def test_migration_verifier_accepts_new_run_context_and_keeps_its_bytes(setup, monkeypatch):
    config, snapshot = context(setup, monkeypatch)
    from migrations.immutable_job_id_v1 import build_plan
    path = Path(os.environ['BORG_UI_CONTROL_ROOT']) / snapshot['run_id'] / 'context.json'
    before = path.read_bytes()
    config['PLUGIN_DIR'] = str(setup[3] / 'plugin')
    plan = build_plan(config, control_root=path.parent.parent)
    assert plan['classification'] != 'blocked', plan.get('reasons')
    assert path.read_bytes() == before


def test_cancel_api_uses_active_ownership_without_waiting_for_configuration(setup, monkeypatch):
    from borg_backup_ui import BackupUIHandler
    _, snapshot = context(setup, monkeypatch)
    handler = object.__new__(BackupUIHandler)
    handler.config = setup[0]
    handler._read_json_body = lambda: {'job_id': snapshot['job_id'], 'run_id': snapshot['run_id']}
    handler._get_current_session_meta = lambda: {}
    monkeypatch.setattr('job_actions.resolve_request_job_id', lambda *a,**kw: pytest.fail('Cancellation must not acquire the configuration lock'))
    calls=[]
    monkeypatch.setattr('jobs_api.cancel_job', lambda cfg,job_id,run_id,**kw: calls.append((job_id,run_id)) or {'phase':'borg_prune'})
    assert handler._post_cancel_job()['cancel_requested']
    assert calls == [(snapshot['job_id'],snapshot['run_id'])]


@pytest.mark.parametrize('name', ['job', 'a' * 400, 'Änderung / 测试 \" name'])
def test_readable_artifact_names_are_bounded_and_consistent(name):
    from job_runs import log_filename
    from lib.run_identity import filename_stem
    from runtime_fixture_support import JOB_ID, RUN_ID
    filename = log_filename(JOB_ID, RUN_ID, name)
    assert filename == 'Borg-Backup_' + filename_stem(JOB_ID, RUN_ID, name) + '.log'
    assert len(filename.encode()) < 160 and RUN_ID in filename
    assert '/' not in filename and '\"' not in filename


def test_legacy_run_id_is_preserved_without_inventing_a_new_one(tmp_path):
    from runtime_fixture_support import JOB_ID
    path = tmp_path / 'legacy.status'
    payload = {'job_id':JOB_ID,'run_id':'20260716T120000Z-abcdef12','backup_type':'old','location':'local'}
    path.write_text(json.dumps(payload))
    status = BackupStatus.from_file(path)
    assert status.run_id == payload['run_id'] and status.job_id == JOB_ID
    assert json.loads(path.read_text()) == payload


def test_reminders_ignore_mutable_descriptors_and_unassigned_history():
    from notification_reminder_api import _latest_backup_status_by_key
    job_id = str(uuid4())
    assigned = {'job_id': job_id, 'timestamp': '2026-09-01 12:00:00'}
    unassigned = {'job_id': job_id, 'identity_state': 'unassigned', 'timestamp': '2026-09-06 12:00:00'}
    legacy = {'key': job_id, 'backup_type': 'config', 'location': 'local',
              'timestamp': '2026-09-06 13:00:00'}
    assert _latest_backup_status_by_key([assigned, unassigned, legacy]) == {job_id: assigned}
