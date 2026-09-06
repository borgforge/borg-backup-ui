"""Cron quoting, invalid input and failure handling at the UUID boundary (#474)."""
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
from test_canonical_job_wizard import setup, create
from job_model import JobValidationError
import schedule_api


def test_invalid_and_unknown_ids_never_invoke_crontab(setup, monkeypatch):
    calls = []
    monkeypatch.setattr(schedule_api.subprocess, 'run', lambda *args, **kwargs: calls.append(args))
    for value in ["appdata_local'; touch injected; '", 'photos_local', str(uuid4()), '../metadata']:
        with pytest.raises(JobValidationError):
            schedule_api.save_schedule(setup[0], value, '0 2 * * *', True)
    assert calls == []


def test_apply_writes_quoted_uuid_payload_and_preserves_unmanaged_cron(setup, monkeypatch):
    result, _ = create(setup)
    written = {}
    def fake_run(cmd, **kwargs):
        if cmd == ['crontab', '-l']:
            return subprocess.CompletedProcess(cmd, 0, '0 1 * * * /synthetic/other\n', '')
        assert cmd == ['crontab', '-']
        written['input'] = kwargs['input']
        return subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(schedule_api.subprocess, 'run', fake_run)
    schedule_api.save_schedule(setup[0], result['job_id'], '0 2 * * *', True)
    text = written['input']
    assert '/bin/sh -c' in text and '--data-binary' in text
    assert 'job_id' in text and 'job_key' not in text and result['job_id'] in text
    assert '0 1 * * * /synthetic/other' in text
    assert f'token_file={setup[3]}/config/.api-token' in text


def test_restore_service_does_not_require_a_job(setup, monkeypatch):
    lines = []
    monkeypatch.setattr(schedule_api, '_update_crontab', lambda value: lines.extend(value) or {})
    schedule_api.save_schedule(setup[0], 'restore_test', '0 3 * * *', True)
    assert '/api/restore-tests/run' in lines[0] and '{"scheduled":true}' in lines[0]


@pytest.mark.parametrize('text', ['# --- BORG-BACKUP-UI BEGIN ---\n',
                                '# --- BORG-BACKUP-UI END ---\n# --- BORG-BACKUP-UI BEGIN ---\n',
                                '# --- BORG-BACKUP-UI BEGIN ---\n# --- BORG-BACKUP-UI BEGIN ---\n# --- BORG-BACKUP-UI END ---'])
def test_malformed_markers_never_install_crontab(monkeypatch, text):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert cmd == ['crontab', '-l']
        return subprocess.CompletedProcess(cmd, 0, text, '')
    monkeypatch.setattr(schedule_api.subprocess, 'run', fake_run)
    with pytest.raises(RuntimeError, match='markers'):
        schedule_api._update_crontab([])
    assert calls == [['crontab', '-l']]


@pytest.mark.parametrize('cron', ['0 2 * * *\n', '0 2 * * *;command', '0 2 * *', '0 2\x00 * * *'])
def test_invalid_cron_never_installs_or_writes(setup, monkeypatch, cron):
    result, _ = create(setup)
    monkeypatch.setattr(schedule_api, '_update_crontab', lambda _: pytest.fail('must not install'))
    with pytest.raises(ValueError):
        schedule_api.save_schedule(setup[0], result['job_id'], cron, True)
    assert not (setup[3] / 'config/schedules.json').exists()


def test_crontab_install_and_rollback_failure_are_explicit(setup, monkeypatch):
    result, _ = create(setup)
    def fake_run(cmd, **kwargs):
        if cmd == ['crontab', '-l']:
            return subprocess.CompletedProcess(cmd, 0, '', '')
        return subprocess.CompletedProcess(cmd, 1, '', 'permission denied')
    monkeypatch.setattr(schedule_api.subprocess, 'run', fake_run)
    with pytest.raises(JobValidationError, match='recovery is required'):
        schedule_api.save_schedule(setup[0], result['job_id'], '0 2 * * *', True)
    assert not (setup[3] / 'config/schedules.json').exists()


def test_crontab_read_failure_never_installs(setup, monkeypatch):
    result, _ = create(setup)
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 2, '', 'unavailable')
    monkeypatch.setattr(schedule_api.subprocess, 'run', fake_run)
    schedule_api.write_schedules(setup[0], {result['job_id']: {'cron': '0 2 * * *', 'enabled': True}})
    with pytest.raises(RuntimeError, match='Could not read crontab'):
        schedule_api.apply_all_schedules(setup[0])
    assert calls == [['crontab', '-l']]


def test_scripts_root_token_path_and_cron_percent_escaping(tmp_path):
    lines = schedule_api.schedule_lines({'BACKUP_SCRIPTS_DIR': str(tmp_path / "space % quoted'" / 'scripts')},
                                      {'restore_test': {'cron': '0 2 * * *', 'enabled': True}}, {})
    assert '\\%' in lines[0] and '/scripts/config/' not in lines[0]
