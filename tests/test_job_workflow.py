"""Configured job workflows, recovery outcomes and durable last success (#579)."""
import io
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime/lib"))

from test_runtime_before_maintenance import run_backup
from test_job_scripts import configure_hooks
import wizard_runner
import job_control
from lib.backup_job import BackupJob
from lib.borg_runner import BorgRunner
from lib import borg_runner
from lib.job_workflow import JobWorkflow
from lib.status import BackupStatus
from job_fixtures import job_id, write_job

# Retain real command boundaries before the lifecycle fixture substitutes commands.
REAL_COMMANDS = {name: getattr(BorgRunner, name) for name in ('create', 'prune', 'compact', 'check')}


def observe_run(state, monkeypatch, tmp_path, *, prune=True, hooks=False, pre=0, post=0, post_when='success'):
    """Exercise real workflow boundaries around simulated processes and services."""
    original_load = wizard_runner._load_env_from_job
    def load(*args):
        env, meta = original_load(*args)
        if hooks:
            meta['hooks'] = {'pre':'script-'+'a'*32, 'post':'script-'+'b'*32}
        return env, meta
    monkeypatch.setattr(wizard_runner, '_load_env_from_job', load)
    original_config = borg_runner.BorgConfig.from_config
    def config(env):
        cfg = original_config(env)
        cfg.check_flag_file = tmp_path / 'checked'
        cfg.repo = str(tmp_path / 'simulated-repository')
        if not prune:
            cfg.retention_policy = {'mode':'all'}
        return cfg
    monkeypatch.setattr(borg_runner.BorgConfig, 'from_config', config)
    for name, method in REAL_COMMANDS.items():
        monkeypatch.setattr(BorgRunner, name, method)
    def run(cmd, controller):
        state.actions.append(cmd[1])
        if cmd[1] == 'create':
            if state.create_error:
                raise RuntimeError('simulated process failure')
            if state.cancel_at == 'create':
                state.cancelled = True
            return state.create_exit
        return state.check_exit if cmd[1] == 'check' else 0
    monkeypatch.setattr(borg_runner, '_run_borg', run)
    controller = job_control.JobControl('unused', 'unused')  # Fixture-owned controller.
    controller.attach_process = lambda process: None
    controller.detach_process = lambda: None
    def popen(cmd, **kwargs):
        code = run(cmd, controller)
        return SimpleNamespace(stdout=io.StringIO(''), wait=lambda:code, returncode=code)
    monkeypatch.setattr(borg_runner.subprocess, 'Popen', popen)
    monkeypatch.setattr(borg_runner, '_start_process_watchdog', lambda *args, **kwargs:None)
    monkeypatch.setattr(BackupJob, '_get_repository_size', lambda _:0)
    monkeypatch.setattr(BackupJob, '_get_repo_check_info', lambda _:('unknown','unknown','unknown'))
    def finish(job):
        state.workflow = copy.deepcopy(job.workflow.steps)
        state.result = job.exit_code
    monkeypatch.setattr(BackupJob, '_do_finish', finish)
    if hooks:
        configure_hooks(monkeypatch, state, pre=pre, post=post, mode=post_when)
    return state


@pytest.mark.parametrize('prune,hooks', [(True,False),(False,False),(True,True)])
def test_actual_order_tracks_only_configured_actions(run_backup, monkeypatch, tmp_path, prune, hooks):
    state = observe_run(run_backup, monkeypatch, tmp_path, prune=prune, hooks=hooks)
    assert state.run() == 0
    names = (['pre_script'] if hooks else []) + ['stop_docker','stop_vms','create','start_docker','start_vms'] + (['prune'] if prune else []) + ['compact','check'] + (['post_script'] if hooks else [])
    assert [step['id'] for step in state.workflow] == names
    assert all(step['status'] == 'success' and step['duration_seconds'] >= 0 for step in state.workflow)
    assert next(step for step in state.workflow if step['id']=='start_docker')['details']['completed_count'] == 1
    assert next(step for step in state.workflow if step['id']=='stop_vms')['details']['completed_count'] == 1


@pytest.mark.parametrize('failure', ['error', 'cancel', 'restart', 'post', 'pre'])
def test_failures_never_mark_unexecuted_steps_successful(run_backup, monkeypatch, tmp_path, failure):
    state = observe_run(run_backup, monkeypatch, tmp_path, hooks=True,
                        pre=2 if failure=='pre' else 0, post=2 if failure=='post' else 0, post_when='always')
    if failure == 'error': state.create_exit = 2
    if failure == 'cancel': state.cancel_at = 'create'; state.create_exit = 130
    if failure == 'restart': state.fail_restart = 'docker'
    assert state.run() == (130 if failure=='cancel' else 1 if failure=='restart' else 2)
    steps = {step['id']:step for step in state.workflow}
    if failure in ('error','cancel','pre'):
        assert steps['compact']['status'] == 'skipped'
        assert 'duration_seconds' not in steps['compact']
    if failure == 'pre':
        assert steps['pre_script']['status'] == 'error'
        assert steps['create']['status'] == steps['start_docker']['status'] == 'skipped'
    else:
        assert steps['start_docker']['status'] == ('warning' if failure=='restart' else 'success')
    if failure == 'restart':
        assert all(steps[name]['status'] == 'success' for name in ('create', 'prune', 'compact', 'check'))
    assert steps['post_script']['status'] == ('error' if failure=='post' else 'success')


def test_post_condition_and_check_due_are_explicit(run_backup, monkeypatch, tmp_path):
    state = observe_run(run_backup, monkeypatch, tmp_path, hooks=True)
    state.create_exit = 2
    assert state.run() == 2
    assert next(step for step in state.workflow if step['id']=='post_script')['reason'] == 'post_condition'


@pytest.mark.parametrize('step', ['prune', 'compact', 'check', 'post'])
def test_restart_warning_cannot_hide_later_step_failures(run_backup, monkeypatch, tmp_path, step):
    state = observe_run(run_backup, monkeypatch, tmp_path, hooks=True,
                        post=42 if step == 'post' else 0)
    state.fail_restart = 'docker'
    if step != 'post':
        def fail_command(command, controller):
            return 2 if command[1] == step else 0
        monkeypatch.setattr(borg_runner, '_run_borg', fail_command)
    assert state.run() == 2
    steps = {item['id']: item for item in state.workflow}
    assert steps['create']['status'] == 'success'
    assert steps['start_docker']['status'] == 'warning'
    assert steps['post_script' if step == 'post' else step]['status'] == 'error'
    if step in ('prune', 'compact'):
        assert steps['check']['status'] == 'skipped'


def test_live_ledger_survives_phase_changes_and_write_failure(tmp_path, monkeypatch):
    control = job_control.JobControl('files_local','workflow-run-579',tmp_path/'control')
    control.update_phase('preparing',cancel_allowed=True)
    workflow = JobWorkflow.configured(hooks={'pre':'demo'},docker=True,prune=False,controller=control)
    with workflow.track('pre_script'):
        control.update_phase('pre_script',cancel_allowed=True)
        state = json.loads(control.state_file.read_text())
        assert state['job_steps'][0]['status'] == 'running'
        assert 'prune' not in [step['id'] for step in state['job_steps']]
    control.update_phase('mounting',cancel_allowed=True)
    assert json.loads(control.state_file.read_text())['job_steps'][0]['status']=='success'
    monkeypatch.setattr(control,'update_job_steps',lambda _: (_ for _ in ()).throw(OSError('read only')))
    with workflow.track('create'): pass
    assert workflow.get('create')['status']=='success'


@pytest.mark.parametrize('later_status,code', [('error',2),('warning',1),('cancelled',130),('skipped',0)])
def test_last_success_survives_failure_history_retention_and_api_reload(tmp_path, later_status, code):
    meta = write_job(tmp_path,'files_local')
    success = BackupStatus(job_id=meta['job_id'],job_name='files',status='success',exit_code=0,
                           timestamp='2026-10-21 10:00:00',duration_seconds=81,run_id='first')
    original = success.save(tmp_path)
    original.rename(tmp_path/'old.status')
    workflow=[{'id':'create','status':'error','duration_seconds':3}]
    failure=BackupStatus(job_id=meta['job_id'],job_name='files',status=later_status,exit_code=code,
                         timestamp='2026-10-22 10:00:00',job_steps=workflow)
    saved=failure.save(tmp_path)
    (tmp_path/'old.status').unlink()  # Simulate retention of this isolated fixture.
    loaded=BackupStatus.from_file(saved)
    assert loaded.last_successful_backup['timestamp']==success.timestamp
    assert loaded.last_successful_backup['duration_seconds']==81
    assert loaded.job_steps==workflow
    import status_api, jobs_api
    config={'STATUS_DIR':str(tmp_path),'BACKUP_SCRIPTS_DIR':str(tmp_path)}
    status=status_api.get_status_data(config)['backups'][0]
    jobs=jobs_api.list_jobs(config,{meta['job_id']:status})
    assert jobs[0]['last_job_steps']==workflow
    assert jobs[0]['last_successful_backup']==loaded.last_successful_backup
    other=BackupStatus(job_id=job_id('different'),status='error',exit_code=2,timestamp='2026-10-22 11:00:00')
    assert BackupStatus.from_file(other.save(tmp_path)).last_successful_backup=={}


def test_prune_plan_is_not_mistaken_for_completed_deletion(tmp_path):
    control=job_control.JobControl('files_local','workflow-prune-579',tmp_path/'control')
    control.update_phase('borg_prune',cancel_allowed=True)
    def emit(message):
        borg_runner._consume_borg_output(json.dumps({'type':'log_message','levelname':'INFO','message':message}),control,operation='prune')
    emit('Keeping 18 archives and 0 checkpoints, pruning 2 archives and 0 checkpoints.')
    assert control.get_borg_details()['prune_candidates']==2
    assert 'pruned_archives' not in control.get_borg_details()
    emit('Pruning archive (1/2): private-archive-name')
    assert control.get_borg_details()['pruned_archives']==1
    assert 'private' not in json.dumps(control.get_borg_details())
    control.update_phase('borg_compact',cancel_allowed=True)
    assert control.get_borg_details()=={}


def test_real_borg_workflow_keeps_measured_details(tmp_path, monkeypatch):
    import shutil
    import subprocess
    borg=shutil.which('borg')
    if not borg:
        pytest.skip('Bundled Borg executable required')
    for key in ('CACHE','SECURITY','KEYS'):
        monkeypatch.setenv(f'BORG_{key}_DIR',str(tmp_path/key.lower()))
    repo=tmp_path/'repo'; source=tmp_path/'source.txt'
    source.write_text('first version\n'*100)
    subprocess.run([borg,'init','--encryption=none',str(repo)],check=True,capture_output=True)
    subprocess.run([borg,'create',str(repo)+'::timeline-old',str(source)],check=True,capture_output=True)
    source.write_text('second version\n'*100)
    control=job_control.JobControl('files_local','real-workflow-579',tmp_path/'control')
    control.update_phase('preparing',cancel_allowed=True)
    workflow=JobWorkflow.configured(controller=control)
    runner=BorgRunner(borg_runner.BorgConfig(repo=str(repo),retention_policy={'mode':'last','last':1},check_flag_file=tmp_path/'checked'),
                      process_controller=control,workflow=workflow,
                      phase_callback=lambda phase:control.update_phase(phase,cancel_allowed=True))
    assert runner.create([source],'timeline')==0
    assert runner.maintenance('timeline')==0
    workflow.finalize()
    steps={step['id']:step for step in workflow.steps}
    assert all(step['status']=='success' for step in steps.values())
    assert steps['create']['details']['nfiles']==1
    assert steps['create']['details']['original_size']>0
    assert steps['prune']['details']['kept_archives']==1
    assert steps['prune']['details']['pruned_archives']==1
    assert steps['compact']['details']['freed_bytes']>0
    assert 'deduplicated_size' in steps['create']['details']
    assert 'source.txt' not in json.dumps(workflow.steps)
    control.update_phase('completed',cancel_allowed=False,finished=True)
    assert json.loads(control.state_file.read_text())['job_steps']==workflow.steps
    # Repeating unchanged contents still counts the files/original data, but
    # requires much less new deduplicated data than a full archive transfer.
    source.write_bytes(bytes(range(256)) * 4096)
    assert runner.create([source], 'data-first') == 0
    assert runner.create([source], 'data-unchanged') == 0
    details = control.get_borg_details()
    assert details['nfiles'] == 1
    assert details['original_size'] >= source.stat().st_size
    assert details['deduplicated_size'] < details['original_size'] / 10

@pytest.mark.parametrize('message,expected', [
    ('Repository compaction freed about 12.6 GB repository space.', 12_600_000_000),
    ('Remote: Repository compaction freed about 1.21 kB repository space.', 1210),
    ('compaction freed about 0 B repository space.', 0),
    ('compaction freed about 3.16 kB repository space.', 3160),
    ('Repository compaction freed about 1.5 MiB repository space.', 1572864),
    ('Repository compaction freed about -1 GB repository space.', None),
    ('Repository compaction freed about 1 XB repository space.', None),
    ('Repository compaction freed about 1.2.3 GB repository space.', None),
    ('Compacting segments 63%', None),
    ('compaction freed about ' + '9' * 400 + ' GB repository space.', None),
])
def test_compact_records_only_reported_reclaimed_space(tmp_path, message, expected):
    """Missing or malformed statistics stay unknown; an actual zero stays zero."""
    control = job_control.JobControl('files_local', 'compact-details', tmp_path / 'control')
    control.update_phase('borg_compact', cancel_allowed=True)
    event = {'type': 'log_message', 'name': 'borg.repository', 'levelname': 'INFO', 'message': message}
    borg_runner._consume_borg_output(json.dumps(event), control, operation='compact')
    assert control.get_borg_details() == ({} if expected is None else {'freed_bytes': expected})
    control.update_phase('borg_check', cancel_allowed=True)
    assert control.get_borg_details() == {}, 'Reclaimed space must not leak into a later step'
    borg_runner._consume_borg_output(json.dumps(event), control, operation='check')
    assert control.get_borg_details() == {}
