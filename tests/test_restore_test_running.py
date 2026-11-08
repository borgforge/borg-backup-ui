"""Running restore-test job identities and plan state transitions (#605)."""
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from borg_backup_ui import BackupUIHandler
import jobs_api


def test_running_job_ids_combine_managed_runs_and_current_batch_locks(monkeypatch):
    states = {
        'restore_test_first': {'running': True, 'start_time': '2026-10-26T10:00'},
        'restore_test_second': {'running': True, 'start_time': '2026-10-26T11:00'},
        'restore_test_finished': {'running': False, 'start_time': '2026-10-26T12:00'},
        'restore_test': {'running': True, 'start_time': '2026-10-26T09:00'},
        'backup': {'running': True},
    }
    locks = [
        {'operation': 'restore_test', 'job_key': 'first', 'activity_state': 'waiting'},
        {'operation': 'restore_test', 'job_key': 'batch-current'},
        {'operation': 'restore_test', 'job_key': 'batch-current'},
        {'operation': 'backup', 'job_key': 'backup'},
    ]
    monkeypatch.setattr(jobs_api.JobManager, 'get', lambda: SimpleNamespace(get_all_states=lambda: states))
    monkeypatch.setattr(jobs_api, 'active_resource_locks', lambda config: locks)
    handler = object.__new__(BackupUIHandler)
    handler.config = {}
    snapshot = handler._get_rt_running()
    assert snapshot['active_job_keys'] == ['batch-current', 'first', 'second']
    assert next(run for run in snapshot['active_jobs'] if run['job_key'] == 'first')['activity_state'] == 'waiting'
    assert next(run for run in snapshot['active_jobs'] if run['job_key'] == 'second')['activity_state'] == 'unknown'
    assert snapshot['running'] is True
    assert snapshot['run_key'] == 'restore_test_second'
    assert len(snapshot['runs']) == 4

    # A UI restart loses managed runs but live runner locks still identify rows.
    states.clear()
    assert handler._get_rt_running()['active_job_keys'] == ['batch-current', 'first']
    locks.clear()
    assert handler._get_rt_running() == {'running': False, 'runs': [], 'active_job_keys': [], 'active_jobs': []}


def test_restore_test_plan_running_transitions():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for the restore-test plan regression checks')
    subprocess.run([node, '--test', 'tests/restore_test_running.cjs'],
                   cwd=Path(__file__).resolve().parents[1], check=True)
