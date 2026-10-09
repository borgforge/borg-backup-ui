"""Hook inventory, real Bash execution and complete runner lifecycle (#550)."""
from pathlib import Path
from types import SimpleNamespace
import json
import base64
import logging
import os
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / 'api', ROOT / 'runtime'):
    sys.path.insert(0, str(folder)) if str(folder) not in sys.path else None

import job_scripts
import wizard_runner
from borg_backup_ui import BackupUIHandler
from lib.backup_job import BackupJob
from lib.borg_runner import BorgRunner
from lib.status import BackupStatus
from job_fixtures import job_id
from test_runtime_before_maintenance import run_backup


def script(content='exit 0', **overrides):
    """Return an execution definition with a bounded timeout."""
    return {'id': 'script-' + 'a' * 32, 'name': 'Test', 'description': '',
            'content': content, 'timeout_seconds': 2, **overrides}


def test_inventory_syntax_validation_never_executes_and_does_not_leak_source(tmp_path):
    cfg = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    marker = tmp_path / 'executed'
    valid = script(f'touch "{marker}"\nexit 0')
    valid.pop('id')
    saved = job_scripts.save_script(cfg, valid)['script']
    assert not marker.exists()
    assert job_scripts.store_path(cfg).stat().st_mode & 0o777 == 0o600
    original = job_scripts.store_path(cfg).read_bytes()
    with pytest.raises(ValueError, match=r'Bash syntax error at line \d+') as exc:
        job_scripts.save_script(cfg, {**saved, 'content': 'if true\n password=do-not-expose\nfi'})
    assert 'do-not-expose' not in str(exc.value)
    assert job_scripts.store_path(cfg).read_bytes() == original
    with pytest.raises(ValueError, match='no longer exists'):
        job_scripts.save_script(cfg, {**saved, 'id': 'script-' + 'f' * 32})


def test_central_edits_apply_next_run_but_not_current_snapshot(tmp_path):
    cfg = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    payload = script(); payload.pop('id')
    row = job_scripts.save_script(cfg, payload)['script']
    hooks = {'pre': row['id'], 'post': row['id'], 'post_when': 'always'}
    _, current = job_scripts.snapshot_hooks(cfg, hooks)
    job_scripts.save_script(cfg, {**row, 'content': 'exit 42'})
    _, following = job_scripts.snapshot_hooks(cfg, hooks)
    assert current['pre']['content'] == current['post']['content'] == 'exit 0'
    assert following['pre']['content'] == following['post']['content'] == 'exit 42'
    jobs = tmp_path / 'config/jobs'; jobs.mkdir()
    (jobs / 'job.json').write_text(json.dumps({'hooks': hooks}))
    with pytest.raises(ValueError, match='assigned'):
        job_scripts.delete_script(cfg, row['id'])
    (jobs / 'job.json').write_text(json.dumps({'hooks': {}}))
    job_scripts.delete_script(cfg, row['id'])
    with pytest.raises(ValueError, match='no longer exists'):
        job_scripts.snapshot_hooks(cfg, hooks)


def test_script_usage_includes_both_phases_disabled_jobs_and_live_edits(tmp_path):
    cfg = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    payload = script(); payload.pop('id')
    used = job_scripts.save_script(cfg, payload)['script']
    unused = job_scripts.save_script(cfg, {**payload, 'name': 'Unused'})['script']
    before = job_scripts.store_path(cfg).read_bytes()
    jobs = tmp_path / 'config/jobs'; jobs.mkdir()
    first = {'job_id': 'first', 'name': 'Appdata', 'location': 'local', 'enabled': False,
             'hooks': {'pre': used['id'], 'post': used['id'], 'post_when': 'always'}}
    (jobs / 'first.json').write_text(json.dumps(first))
    (jobs / 'second.json').write_text(json.dumps({'name': 'Flash', 'hooks': {'post': used['id']}}))
    rows = job_scripts.list_scripts_with_assignments(cfg)['scripts']
    assert rows[0]['assignments'] == [
        {'job_id': 'first', 'name': 'Appdata', 'location': 'local', 'enabled': False, 'phase': 'pre', 'post_when': None},
        {'job_id': 'first', 'name': 'Appdata', 'location': 'local', 'enabled': False, 'phase': 'post', 'post_when': 'always'},
        {'job_id': 'second', 'name': 'Flash', 'location': '', 'enabled': True, 'phase': 'post', 'post_when': 'success'},
    ]
    assert rows[1]['id'] == unused['id'] and rows[1]['assignments'] == []
    assert job_scripts.store_path(cfg).read_bytes() == before
    first.update(name='Renamed', hooks={})
    (jobs / 'first.json').write_text(json.dumps(first))
    assert len(job_scripts.list_scripts_with_assignments(cfg)['scripts'][0]['assignments']) == 1
    with pytest.raises(ValueError, match='assigned'):
        job_scripts.delete_script(cfg, used['id'])


def test_script_usage_does_not_claim_unused_when_job_metadata_is_unreadable(tmp_path):
    cfg = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    jobs = tmp_path / 'config/jobs'; jobs.mkdir(parents=True)
    (jobs / 'broken.json').write_text('{')
    with pytest.raises(json.JSONDecodeError):
        job_scripts.list_scripts_with_assignments(cfg)


def test_bash_highlighting_preserves_source_and_escapes_markup():
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for Bash highlighting tests')
    subprocess.run([node, 'tests/bash_highlighting.cjs'], cwd=ROOT, check=True)


@pytest.mark.parametrize('phase,code', [('pre', 0), ('pre', 41), ('post', 0), ('post', 42)])
def test_real_bash_outcomes_and_masked_output(phase, code, caplog):
    caplog.set_level(logging.INFO)
    outcome = job_scripts.run_hook(script(f'echo marker; echo password=hidden >&2; exit {code}'), phase, 'job')
    assert outcome['exit_code'] == code
    assert outcome['status'] == ('success' if code == 0 else 'failed')
    assert 'marker' in caplog.text and 'hidden' not in caplog.text
    assert f'PHASE: {phase.upper()} SCRIPT' in caplog.text
    assert caplog.text.count('━' * 80) == 3
    assert caplog.text.index('Script: Test') < caplog.text.index('marker') < caplog.text.index('script finished:')


@pytest.mark.parametrize('cancel', [False, True])
def test_timeout_and_cancellation_kill_process_group(tmp_path, cancel):
    marker = tmp_path / 'child-survived'
    content = f'(sleep 1.5; touch "{marker}") &\nwait'
    began = time.monotonic()
    outcome = job_scripts.run_hook(script(content, timeout_seconds=1), 'pre', 'job',
                                   cancelled=(lambda: time.monotonic() - began > .15) if cancel else None)
    assert outcome['status'] == ('cancelled' if cancel else 'timeout')
    assert outcome['exit_code'] == (130 if cancel else 124)
    time.sleep(1.6)
    assert not marker.exists()


def test_script_environment_excludes_borg_credentials_and_shell_startup(monkeypatch, tmp_path, caplog):
    marker = tmp_path / 'bash-env'
    rc = tmp_path / 'rc'; rc.write_text(f'touch "{marker}"')
    monkeypatch.setenv('BASH_ENV', str(rc))
    monkeypatch.setenv('BORG_PASSPHRASE', 'never-print-this')
    caplog.set_level(logging.INFO)
    outcome = job_scripts.run_hook(script('env'), 'post', 'job', result='failed')
    assert outcome['exit_code'] == 0 and not marker.exists()
    assert 'never-print-this' not in caplog.text
    assert 'BBUI_JOB_RESULT=failed' in caplog.text


def configure_hooks(monkeypatch, state, *, pre=0, post=0, mode='success'):
    """Insert deterministic hooks into the real runner and record ordering."""
    monkeypatch.setattr(job_scripts, 'snapshot_hooks', lambda *_: (
        {'post_when': mode}, {'pre': script(), 'post': script()}))
    def run(definition, phase, *_args, **_kwargs):
        state.actions.append(phase)
        code = pre if phase == 'pre' else post
        return {'name': 'Test', 'script_id': definition['id'], 'status': 'success' if code == 0 else 'failed', 'exit_code': code}
    monkeypatch.setattr(job_scripts, 'run_hook', run)
    def mount(*_):
        state.actions.append('mount')
        return SimpleNamespace(cleanup=lambda: state.actions.append('unmount'))
    monkeypatch.setattr(wizard_runner, '_ensure_smb_mount', mount)
    monkeypatch.setattr(BackupJob, '_get_repository_size', lambda _: state.actions.append('repo_info') or 100)


def test_hooks_enclose_all_operations_and_final_result(run_backup, monkeypatch):
    state = run_backup
    configure_hooks(monkeypatch, state)
    assert state.run() == 0
    assert state.actions == ['pre', 'mount', 'stop_docker', 'stop_vms', 'create',
        'start_docker', 'start_vms', 'prune', 'compact', 'check', 'repo_info', 'unmount', 'post', 'finish', 'release']
    assert next(details for phase, details in state.phases if phase == 'post_script')['cancel_allowed'] is False


@pytest.mark.parametrize('mode,expected', [('success', ['pre', 'finish', 'release']), ('always', ['pre', 'post', 'finish', 'release'])])
def test_pre_failure_prevents_mount_and_backup(run_backup, monkeypatch, mode, expected):
    state = run_backup
    configure_hooks(monkeypatch, state, pre=41, mode=mode)
    assert state.run() == 2
    assert state.actions == expected
    assert state.result == (2, 'PRE_SCRIPT_FAILED')


def test_post_failure_changes_exit_and_preserves_created_archive(run_backup, monkeypatch):
    state = run_backup
    configure_hooks(monkeypatch, state, post=42)
    state.config.log_file.write_text('Archive name: retained-archive\n')
    captured = {}
    def finish(job):
        captured.update(exit=job.exit_code, backup_exit=job.backup_exit_code, stats=job._borg_stats, hooks=job.hook_results)
    monkeypatch.setattr(BackupJob, '_do_finish', finish)
    assert state.run() == 2
    assert captured['exit'] == 2 and captured['backup_exit'] == 0
    assert captured['stats'].archive_name == 'retained-archive'
    assert captured['hooks']['post']['exit_code'] == 42
    assert state.phases[-1][0] == 'failed'


@pytest.mark.parametrize('cancel_at', ['stop_docker', 'create', 'check'])
def test_post_always_runs_after_cancel_recovery(run_backup, monkeypatch, cancel_at):
    state = run_backup; state.cancel_at = cancel_at
    configure_hooks(monkeypatch, state, mode='always')
    assert state.run() == 130
    assert state.actions.index('start_docker') < state.actions.index('unmount') < state.actions.index('post') < state.actions.index('finish')


def test_post_runs_after_exception_and_cannot_mask_failed_backup(run_backup, monkeypatch):
    state = run_backup; state.create_error = True
    configure_hooks(monkeypatch, state, mode='always')
    with pytest.raises(RuntimeError, match='create process failed'):
        state.run()
    assert state.result[0] == 2
    assert state.actions[-4:] == ['unmount', 'post', 'finish', 'release']


def test_maintenance_exception_after_successful_create_is_failure(run_backup, monkeypatch):
    state = run_backup
    configure_hooks(monkeypatch, state, mode='always')
    def fail(*_args, **_kwargs):
        raise RuntimeError('maintenance failed')
    monkeypatch.setattr(BorgRunner, 'maintenance', fail)
    with pytest.raises(RuntimeError, match='maintenance failed'):
        state.run()
    assert state.result[0] == 2
    assert 'post' in state.actions


def test_skip_waits_for_post_before_persisting(run_backup, monkeypatch):
    state = run_backup
    configure_hooks(monkeypatch, state, mode='always')
    def skip(job):
        job._skip_reason = 'USB is not mounted: test'
        job._persist_skip_status_once()
        assert not job._skip_status_written
        raise SystemExit(0)
    monkeypatch.setattr(BackupJob, 'check_prerequisites', skip)
    monkeypatch.setattr(BackupJob, '_save_skip_status', lambda job: state.actions.append('save_skip'))
    monkeypatch.setattr(BackupJob, '_send_notification_event', lambda *_args: None)
    assert state.run() == 0
    assert state.actions.index('post') < state.actions.index('save_skip')
    assert state.phases[-1][0] == 'skipped'


def test_status_roundtrip_retains_hook_outcomes(tmp_path):
    status = BackupStatus(job_id=job_id('hooks'), status='error', backup_exit_code=0,
                          hook_results={'post': {'exit_code': 42, 'status': 'failed'}})
    path = status.save(tmp_path)
    loaded = BackupStatus.from_file(path)
    assert loaded.backup_exit_code == 0 and loaded.hook_results == status.hook_results


@pytest.mark.parametrize('method', ['GET', 'POST', 'DELETE'])
@pytest.mark.parametrize('path', ['/api/settings/scripts', '/api/settings/scripts/import', '/api/settings/scripts/export'])
def test_scripts_require_admin(method, path):
    handler = BackupUIHandler.__new__(BackupUIHandler)
    assert handler._required_role_for_request(path, method) == 'admin'


def test_http_script_routes_validate_before_save(tmp_path, monkeypatch):
    """Exercise the real HTTP dispatch and error contract with an admin fixture."""
    from http.server import ThreadingHTTPServer
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    import threading
    import borg_backup_ui
    monkeypatch.setattr(borg_backup_ui, '_log', lambda *_: None)
    class Handler(BackupUIHandler):
        config = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
        def _authorize_api_request(self, *_):
            return True
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    url = f'http://127.0.0.1:{server.server_port}/api/settings/scripts'
    def request(method, body=None, suffix=''):
        payload = json.dumps(body).encode() if body is not None else None
        try:
            response = urlopen(Request(url + suffix, data=payload, method=method,
                                       headers={'Content-Type': 'application/json'}), timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), response.headers
    try:
        payload = script(); payload.pop('id')
        status, row, _ = request('POST', payload)
        assert status == 200
        status, data, headers = request('GET')
        assert status == 200 and len(data['scripts']) == 1
        assert data['scripts'][0]['assignments'] == []
        assert headers['Cache-Control'] == 'no-store'
        original = job_scripts.store_path(Handler.config).read_bytes()
        status, exported, headers = request('POST', payload, '/export')
        assert status == 200 and headers['Cache-Control'] == 'no-store'
        status, imported, headers = request('POST', {'filename': exported['filename'],
            'content_base64': base64.b64encode(exported['content'].encode()).decode()}, '/import')
        assert status == 200 and headers['Cache-Control'] == 'no-store'
        assert 'id' not in imported['script']
        assert job_scripts.store_path(Handler.config).read_bytes() == original
        status, error, _ = request('POST', {'filename': 'python.sh',
            'content_base64': base64.b64encode(b'#!/usr/bin/python3\nprint(1)').decode()}, '/import')
        assert status == 400 and error['code'] == 'job_script_import_bash'
        status, error, _ = request('POST', {**row['script'], 'content': 'if true\nsecret=never-expose\nfi'})
        assert status == 400 and error['code'] == 'job_script_syntax'
        assert error['message_params']['line'] == '3'
        assert 'never-expose' not in json.dumps(error)
        assert request('GET')[1]['scripts'][0]['content'] == 'exit 0'
        assert request('DELETE', suffix='?id=' + row['script']['id'])[0] == 200
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)


@pytest.mark.parametrize('phase', ['pre', 'post'])
def test_example_scripts(phase):
    """Verify user-delivered examples exercise syntax and runtime failures separately."""
    root = ROOT / 'docs/examples/job-hooks'
    for name, expected in [('success', 0), ('failure', 41 if phase == 'pre' else 42)]:
        definition = job_scripts.validate_script(script((root / f'{phase}-{name}.sh').read_text()))
        outcome = job_scripts.run_hook({**definition, 'id': 'example'}, phase, 'job')
        assert outcome['exit_code'] == expected
    with pytest.raises(job_scripts.ScriptValidationError, match='line 7'):
        job_scripts.validate_script(script((root / f'{phase}-syntax-error.sh').read_text()))


@pytest.mark.parametrize('mode,post_runs', [('success', False), ('always', True)])
def test_post_policy_after_backup_failure(run_backup, monkeypatch, mode, post_runs):
    state = run_backup; state.create_exit = 2
    configure_hooks(monkeypatch, state, mode=mode)
    assert state.run() == 2
    assert ('post' in state.actions) is post_runs
    assert 'start_docker' in state.actions and 'start_vms' in state.actions


def test_post_failure_after_cancel_is_reported_as_failure(run_backup, monkeypatch):
    state = run_backup; state.cancel_at = 'create'
    configure_hooks(monkeypatch, state, mode='always', post=42)
    assert state.run() == 2
    assert state.result == (2, 'POST_SCRIPT_FAILED')


def test_recovery_failure_still_runs_post_always(run_backup, monkeypatch):
    state = run_backup; state.fail_restart = 'docker'
    configure_hooks(monkeypatch, state, mode='always')
    with pytest.raises(RuntimeError):
        state.run()
    assert 'post' in state.actions and state.result[0] == 2


def test_resource_conflict_does_not_run_hooks(run_backup, monkeypatch):
    state = run_backup
    configure_hooks(monkeypatch, state, mode='always')
    monkeypatch.setattr(wizard_runner, 'ResourceLockSet', lambda **_: SimpleNamespace(acquire=lambda _: (False, 'resource locked')))
    monkeypatch.setattr(BackupJob, 'record_prestart_skip', lambda *_: None)
    assert state.run() == 2
    assert not state.actions


def test_no_hook_phase_separators_without_hooks(run_backup, caplog):
    caplog.set_level(logging.INFO)
    assert run_backup.run() == 0
    assert 'PHASE: PRE SCRIPT' not in caplog.text and 'PHASE: POST SCRIPT' not in caplog.text


def test_script_launch_failure_is_a_failed_hook(monkeypatch):
    def fail(*_, **__):
        raise OSError('not started')
    monkeypatch.setattr(job_scripts.subprocess, 'Popen', fail)
    assert job_scripts.run_hook(script(), 'pre', 'job')['status'] == 'launch_failed'


def test_wizard_persists_references_and_rejects_missing_script(tmp_path):
    from repositories_api import write_repository_store
    from storage_objects_api import write_storage_store
    from wizard_api import save_job, generate_flow_preview
    cfg = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    write_storage_store(cfg, {'storages': [{'storage_key': 'storage_local', 'display_name': 'Local',
        'storage_type': 'local', 'location': 'local', 'identity': 'local:/mnt/backup', 'base_path': '/mnt/backup'}]})
    write_repository_store(cfg, {'repositories': [{'repository_key': 'repo_local', 'display_name': 'Local',
        'storage_key': 'storage_local', 'relative_path': 'repo', 'encryption': 'none'}]})
    payload = script(); payload.pop('id')
    saved = job_scripts.save_script(cfg, payload)['script']
    params = {'job_name': 'Hook test', 'archive_prefix': 'hook-test', 'location': 'local',
        'repository_key': 'repo_local', 'source_paths': ['/boot'],
        'hooks': {'pre': saved['id'], 'post': saved['id'], 'post_when': 'always'}}
    result = save_job(params, tmp_path / 'scripts', tmp_path, cfg)
    metadata = json.loads(Path(result['metadata_path']).read_text())
    assert metadata['hooks'] == params['hooks']
    assert 'content' not in json.dumps(metadata)
    steps = [row['code'] for row in generate_flow_preview(params, cfg)['step_codes']]
    assert steps.index('preScript') < steps.index('prechecks') < steps.index('borgCreate')
    assert steps.index('repositoryStats') < steps.index('postScriptAlways') < steps.index('statusNotification')
    with pytest.raises(job_scripts.ScriptValidationError, match='assigned'):
        job_scripts.delete_script(cfg, saved['id'])
    params['hooks']['pre'] = 'script-' + 'f' * 32
    with pytest.raises(job_scripts.ScriptValidationError, match='no longer exists'):
        save_job({**params, 'archive_prefix': 'another-job'}, tmp_path / 'scripts', tmp_path, cfg)


def test_log_output_is_bounded(caplog):
    caplog.set_level(logging.INFO)
    result = job_scripts.run_hook(script("printf '%070000d' 0"), 'pre', 'job')
    assert result['exit_code'] == 0
    assert 'Output truncated at 64 KiB' in caplog.text
    assert len(caplog.text) < 70000


@pytest.mark.parametrize('header', ['#!/bin/bash', '#!/usr/bin/bash', '#!/usr/bin/env bash'])
def test_import_bash_creates_only_a_validated_draft(tmp_path, header):
    marker = tmp_path / 'must-not-run'
    raw = ('\ufeff' + header + '\r\n' + f'touch "{marker}"\r\n# Grüße\r\n').encode()
    result = job_scripts.import_script({'filename': 'Test.sh', 'content_base64': base64.b64encode(raw).decode(),
                                       'id': 'ignored', 'hooks': {'pre': 'ignored'}})['script']
    assert result['name'] == 'Test' and result['timeout_seconds'] == 300
    assert result['content'].startswith(header + '\n') and '\r' not in result['content']
    assert set(result) == {'name', 'description', 'timeout_seconds', 'content'}
    assert not marker.exists() and not (tmp_path / 'config').exists()


@pytest.mark.parametrize('filename,raw,code', [
    ('test.py', b'#!/bin/bash\nexit 0', 'import_file'),
    ('../test.sh', b'#!/bin/bash\nexit 0', 'import_file'),
    ('test.sh', b'#!/usr/bin/python3\nprint("hi")', 'import_bash'),
    ('test.sh', b'#!/bin/sh\nexit 0', 'import_bash'),
    ('test.sh', b'exit 0', 'import_bash'),
    ('test.sh', b'#!/bin/bash -e\nexit 0', 'import_bash'),
    ('test.sh', b'#!/bin/bash\n\x00binary', 'import_text'),
    ('test.sh', b'#!/bin/bash\n\xff', 'import_text'),
    ('test.sh', b'', 'import_size'),
    ('test.sh', b'#' * 65537, 'import_size'),
    ('test.sh', b'#!/bin/bash\nif true\nsecret=do-not-expose\nfi', 'syntax'),
])
def test_import_rejects_non_bash_binary_oversized_and_invalid_scripts(filename, raw, code):
    with pytest.raises(job_scripts.ScriptValidationError) as exc:
        job_scripts.import_script({'filename': filename, 'content_base64': base64.b64encode(raw).decode()})
    assert exc.value.api_code == 'job_script_' + code
    assert 'do-not-expose' not in str(exc.value)


@pytest.mark.parametrize('encoded', ['%%%bad%%%', 'ümlaut', 'AAAA=bad'])
def test_import_rejects_invalid_transport(encoded):
    with pytest.raises(job_scripts.ScriptValidationError):
        job_scripts.import_script({'filename': 'test.sh', 'content_base64': encoded})


@pytest.mark.parametrize('content', ['exit 0\n', '#!/usr/bin/env bash\necho "Grüße"\n', '#!/bin/sh\nexit 0\n'])
def test_export_import_round_trip_preserves_body_and_never_executes(tmp_path, content):
    marker = tmp_path / 'not-executed'
    content += f'touch "{marker}"\n'
    output = job_scripts.export_script(script(content, name='../../Test / 名'))
    assert output['filename'] == 'Test.sh'
    assert output['content'].endswith(content)
    restored = job_scripts.import_script({'filename': output['filename'],
        'content_base64': base64.b64encode(output['content'].encode()).decode()})['script']
    assert restored['content'] == output['content']
    assert not marker.exists()


def test_import_export_size_boundary_counts_utf8_bytes():
    content = '#!/bin/bash\n#' + 'a' * (65536 - len('#!/bin/bash\n#'))
    payload = {'filename': 'limit.sh', 'content_base64': base64.b64encode(content.encode()).decode()}
    assert job_scripts.import_script(payload)['script']['content'] == content
    assert job_scripts.export_script(script(content))['content'] == content
    payload['content_base64'] = base64.b64encode((content[:-1] + 'ü').encode()).decode()
    with pytest.raises(job_scripts.ScriptValidationError) as exc:
        job_scripts.import_script(payload)
    assert exc.value.api_code == 'job_script_import_size'
    with pytest.raises(job_scripts.ScriptValidationError):
        job_scripts.export_script(script('#' * 65536))
