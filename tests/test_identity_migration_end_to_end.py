"""A migrated local installation performs actual Borg backup and restore (#479)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

from test_identity_migration_assistant import installation, prepare, binding
from identity_contract_support import ROOT


def test_restore_proof_migrates_and_native_report_remains_valid_on_restart(installation, monkeypatch):
    root, config, assistant, _, _ = installation
    from job_store import read_json, read_jobs
    from test_restore_test_runner_profiles import _load_restore_runner

    proof_dir = Path(config['RESTORE_TEST_STATUS_DIR'])
    proof_dir.mkdir()
    legacy_path = proof_dir / 'config_local.test'
    legacy = {'report_schema_version': 1, 'type': 'config', 'location': 'local',
              'repository': str(root / 'repositories/repo_docs'),
              'test_date': '2026-08-31 08:10:00', 'test_result': 'success',
              'tested_archive': 'config-backup-2026-08-31_08-00-00', 'tested_entries': ['original.txt']}
    legacy_path.write_text(json.dumps(legacy))
    original_bytes = legacy_path.read_bytes()
    detected = assistant.startup_detection()
    assert detected['classification'] == 'applicable', detected
    status = prepare(installation)
    assert status['stage'] == 'backup_ready', status
    assert legacy_path.read_bytes() == original_bytes
    assistant.acknowledge({**binding(status), 'independent_backup_ack': True})
    migrated = assistant.apply(binding(status), background=False)
    assert migrated['status'] == 'applied', migrated
    job_id = next(iter(read_jobs(root / 'data/config/jobs')))
    proof_path = proof_dir / f'{job_id}.test'
    assert read_json(proof_path) == {**legacy, 'schema_version': 1, 'job_id': job_id}
    assert not legacy_path.exists()
    assert assistant.startup_detection()['required'] is False

    # Exercise the actual current result writer: its type contains an archive
    # prefix, not the backup_type that identified pre-migration jobs.
    runner = _load_restore_runner()
    monkeypatch.setenv('BORG_UI_DATA_ROOT', str(root / 'data'))
    monkeypatch.setattr(runner, '_refresh_unraid_dashboard_widget_cache', lambda *args: None)
    tester = object.__new__(runner.RestoreTest)
    tester.conf = config
    tester.status_dir = proof_dir
    tester.test_level = 1
    tester.sample_size = 1
    tester.log = lambda *args: None
    tester.args = SimpleNamespace(scheduled=False)
    repo = runner.discover_repos(config)[0]
    repo['run_id'] = '33333333-3333-4333-8333-333333333333'
    archive = repo['type'] + '-2026-09-06_10-00-00'
    tester._write(job_id, repo, 'success', 1, 1, 0, 1, '1/1', archive, {'files_count': 1}, ['new.txt'])
    native = read_json(proof_path)
    assert native['type'] == 'config-backup'
    assert native['job_id'] == job_id
    assert native['tested_entries'] == ['new.txt']
    from identity_migration_api import IdentityMigrationAssistant
    restarted = IdentityMigrationAssistant(config)
    assert restarted.startup_detection()['required'] is False
    assert read_json(proof_path) == native


def test_migrated_job_runs_borg_and_restores_original_bytes(installation, monkeypatch):
    root, config, assistant, _, _ = installation
    sys.path[:0] = [str(ROOT / 'runtime'), str(ROOT / 'runtime/lib')]
    source = root / 'sources/config/qualification.txt'
    source.write_bytes(b'Independent immutable identity migration qualification.\n')
    runtime = ROOT / 'runtime/scripts'
    config['BORG_SCRIPTS_DIR'] = str(runtime)
    config['UNRAID_DASHBOARD_WIDGET_FILE'] = str(root / 'plugin/widget-status.json')
    conf = root / 'data/config/backup.conf'
    conf.write_text('\n'.join([
        'GLOBAL_DATA_DIR=' + str(root / 'data'), 'GLOBAL_LOG_DIR=' + str(root / 'logs'),
        'STATUS_DIR=' + str(root / 'status'), 'GLOBAL_BORG_CACHE_BASE=' + str(root / 'cache'),
        'LOCK_FILE_DIR=' + str(root / 'locks'), 'ABORT_ON_PARITY_CHECK=false',
        'NOTIFY_UNRAID_EVENTS=none', 'NOTIFY_EMAIL_EVENTS=none', 'NOTIFY_APPRISE_EVENTS=none',
    ]) + '\n')
    (root / 'schema.example').write_bytes(conf.read_bytes())
    bin_dir = root / 'bin'; bin_dir.mkdir()
    (bin_dir / 'borg').symlink_to(ROOT / 'runtime/bin/borg/borg-linux-glibc231-x86_64-1.4.5')
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('BORG_UI_CONTROL_ROOT', str(root / 'run'))
    monkeypatch.setattr('activity_log_capture.CAPTURE_ROOT', root / 'captures')
    monkeypatch.setenv('BORG_UI_DATA_ROOT', str(root / 'data'))
    monkeypatch.setenv('UNRAID_DASHBOARD_WIDGET_FILE', str(root / 'plugin/widget-status.json'))
    for key in ('BORG_CACHE_DIR', 'BORG_SECURITY_DIR', 'BORG_KEYS_DIR'):
        monkeypatch.setenv(key, str(root / key.lower()))
    monkeypatch.delenv('BORG_PASSCOMMAND', raising=False)
    repo = root / 'repositories/repo_docs'
    initialized = subprocess.run(['borg', 'init', '--encryption=none', str(repo)], capture_output=True, text=True, timeout=120)
    assert initialized.returncode == 0, initialized.stderr
    status = prepare(installation)
    assert status['stage'] == 'backup_ready', status
    assistant.acknowledge({**binding(status), 'independent_backup_ack':True})
    migrated = assistant.apply(binding(status), background=False)
    assert migrated['status'] == 'applied', migrated
    from job_store import read_jobs
    from job_runs import create_run_context, find_run_status
    from jobs_api import JobManager
    from lib.status import StatusStore
    from migration_barrier import writer_lease
    jobs = read_jobs(root / 'data/config/jobs')
    assert len(jobs) == 1
    job_id = next(iter(jobs))
    with writer_lease(config):
        context = create_run_context(config, job_id)
        manager = JobManager()
        ok, error = manager.start(job_id, [sys.executable, str(ROOT / 'api/wizard_runner.py')], root / 'data',
            {'BORG_UI_BORG_SCRIPTS_DIR':str(runtime)}, run_context=context)
    assert ok, error
    state = manager._states[job_id]
    deadline = time.monotonic() + 180
    while not state.finished and time.monotonic() < deadline:
        time.sleep(.05)
    assert state.finished, 'Synthetic backup failed to finish within qualification deadline'
    assert state.exit_code == 0, state.log_file.read_text() if state.log_file else state.lines
    statuses = StatusStore(root / 'status').load()
    current = next(row for row in statuses if row.run_id == context['run_id'])
    assert current.job_id == job_id and current.archive_name.startswith('config-backup-')
    assert current.files_count == 1
    assert find_run_status(config, job_id, context['run_id'])['exit_code'] == 0
    assert len(statuses) == 2  # Historical pre-migration evidence remains attributed.
    import restore_api as restore
    restore._RESTORE_RUNS.clear(); restore._RESTORE_RUNS_LOADED = False
    target = root / 'restored'; target.mkdir()
    # Only Unraid's /mnt target allowlist is replaced for this repo-local harness.
    # Borg execution, repository locks, archive checks and history writes stay real.
    monkeypatch.setattr(restore, '_get_restore_allowed_roots', lambda cfg: [target])
    archives = restore.list_archives(config, job_id)
    assert any(row['name'] == current.archive_name for row in archives)
    result = restore.start_restore_async(config, job_id, current.archive_name, str(source).lstrip('/'), str(target), 'skip')
    restore_id = result['restore_id']
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        restored = restore.get_restore_state(config, restore_id)
        if restored['state'] in {'done', 'error'}:
            break
        time.sleep(.05)
    assert restored['state'] == 'done', restored
    assert (target / source.name).read_bytes() == source.read_bytes()
    history = restore.list_restore_history(config)['runs']
    assert any(row['job_id'] == job_id and row['restore_id'] == restore_id for row in history)
    assert assistant.startup_detection()['required'] is False
