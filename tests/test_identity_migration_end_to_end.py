"""A migrated local installation performs actual Borg backup and restore (#479)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from test_identity_migration_assistant import installation, prepare, binding
from identity_contract_support import ROOT


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
