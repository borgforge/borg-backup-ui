"""#477: restore ownership, frozen execution and proof continuity."""
from copy import deepcopy
from migration_gate_support import ready_gate
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import UUID

import pytest
ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT/'api', ROOT/'runtime', ROOT/'runtime/lib'):
    sys.path.insert(0, str(folder))

from test_canonical_job_wizard import setup, create, edit
from test_restore_test_runner_profiles import _load_restore_runner
from restore_identity_support import JOB_ID, OTHER_ID, RUN_ID, info
import restore_api as restore
import restore_tests_api as tests_api
from restore_identity import capture_repository, historical_identity, snapshots
from job_store import read_json
from status_read_model import configured_jobs


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    restore._RESTORE_RUNS.clear()
    monkeypatch.setattr(restore, '_RESTORE_RUNS_LOADED', True)
    monkeypatch.setattr('config_api.read_expanded_conf', lambda cfg: {})
    monkeypatch.setattr('schedule_api._update_crontab', lambda rows: {})


def test_discovery_uses_current_repository_and_literal_ordered_prefixes(setup, monkeypatch):
    result, _ = create(setup, archive_prefix='old', job_name='Original')
    job_id = result['job_id']
    edit(setup, job_id, archive_prefix='new', repository_key='repo_b', job_name='Renamed')
    calls = []
    def borg(repo, env, pattern):
        calls.append((repo, pattern))
        return {'archives':[{'name':pattern[:-1]+'2026', 'start':'2026-01-01'}]}
    monkeypatch.setattr(restore, '_run_borg_archive_list', borg)
    monkeypatch.setattr(restore, 'ensure_restore_repository_available', lambda *a: None)
    monkeypatch.setattr(restore, '_repository_borg_env', lambda *a: {})
    data = restore.list_archives_with_context(setup[0], job_id)
    assert [p for _, p in calls] == ['new-*', 'old-*']
    assert all(repo.startswith('ssh://') for repo, _ in calls)
    assert [r['current'] for r in data['archive_filters']] == [True, False]
    assert job_id not in str(calls)
    with pytest.raises(ValueError): restore.list_files(setup[0], job_id, 'foreign-2026', '')
    with pytest.raises(ValueError): restore.list_archives(setup[0], 'Original_local')


def test_async_restore_keeps_original_context_through_edits_and_history(setup, monkeypatch):
    ready_gate(setup[0], monkeypatch, setup[3] / "writer-gate")
    result, _ = create(setup, archive_prefix='old', job_name='Original')
    job_id = result['job_id']; work = []
    monkeypatch.setattr(restore.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: work.append(kw['target'])))
    captured = []
    monkeypatch.setattr(restore, 'start_restore', lambda *a, **kw: captured.append(deepcopy(kw['_info'])) or {'destination_path':'/restored'})
    started = restore.start_restore_async(setup[0], job_id, 'old-2026', 'source', '/target', 'skip')
    run_id = started['restore_id']; assert UUID(run_id).version == 4
    edit(setup, job_id, job_name='Renamed', archive_prefix='new', repository_key='repo_b')
    work[0]()
    assert captured[0]['repo'].endswith('/repo_a') and captured[0]['job']['name'] == 'Original'
    detail = restore.get_restore_history_detail(setup[0], run_id)
    assert detail['run_id'] == run_id and detail['job_id'] == job_id
    assert detail['job_name_snapshot'] == 'Original' and detail['current_job_name'] == 'Renamed'
    assert detail['archive_prefix_snapshot'] == 'old' and detail['location_snapshot'] == 'local'
    assert restore.list_restore_history(setup[0])['runs'][0]['repository_snapshot'] == captured[0]['repo']


def test_restore_will_not_launch_without_persisted_ownership(monkeypatch, tmp_path):
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    ready_gate(cfg, monkeypatch, tmp_path / "writer-gate")
    monkeypatch.setattr(restore, '_get_job_repo_info', lambda *a: info())
    monkeypatch.setattr(restore, '_persist_restore_runs', lambda *a: (_ for _ in ()).throw(OSError('full')))
    monkeypatch.setattr(restore.threading, 'Thread', lambda **kw: pytest.fail('must not start'))
    with pytest.raises(OSError): restore.start_restore_async(cfg, JOB_ID, 'archive-1', 'file', '/target', 'skip')
    assert restore._RESTORE_RUNS == {}


def test_legacy_deleted_and_ambiguous_history_are_preserved(tmp_path):
    cfg = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    legacy = {'restore_id':'old-restore', 'job_key':'config_local', 'archive':'old-1', 'state':'done'}
    restore._record_restore_history(cfg, legacy, 'fixture')
    detail = restore.get_restore_history_detail(cfg, 'old-restore')
    assert detail['legacy_job_key'] == 'config_local' and detail['identity_scope'] == 'unassigned'
    assert detail['job_id'] == '' and 'job_name_snapshot' not in detail
    deleted = historical_identity({'job_id':JOB_ID, 'identity_state':'unassigned', 'identity_reason':'deleted_job'}, {})
    assert deleted['identity_scope'] == 'deleted' and deleted['job_id'] == JOB_ID


def test_corrupt_history_is_not_replaced_by_new_restore(tmp_path):
    cfg = {'BACKUP_SCRIPTS_DIR':str(tmp_path)}
    path = restore._restore_history_index_file(cfg); path.parent.mkdir(parents=True);path.write_text('{')
    with pytest.raises(ValueError): restore._record_restore_history(cfg, {'restore_id':RUN_ID}, 'fixture')
    assert path.read_text() == '{'
    assert not (restore._restore_history_runs_dir(cfg) / (RUN_ID+'.json')).exists()


def test_policy_plan_proof_and_runner_keep_id_across_prefix_edit(setup, monkeypatch):
    result, _ = create(setup, job_name='Original', archive_prefix='old')
    job_id = result['job_id']; cfg = setup[0]
    cfg.update(STATUS_DIR=str(setup[3]/'status'), RESTORE_TEST_STATUS_DIR=str(setup[3]/'tests'))
    directory = Path(cfg['RESTORE_TEST_STATUS_DIR']);directory.mkdir()
    frozen = capture_repository(cfg, job_id)
    proof = {**snapshots(frozen, 'old-2026', RUN_ID), 'tested_archive':'old-2026',
             'test_result':'success','test_date':datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'test_level':1}
    (directory/f'{job_id}.test').write_text(json.dumps(proof))
    tests_api.update_restore_test_policy(cfg, job_id, {'mode':'scheduled','level':1,'interval_days':30})
    edit(setup, job_id, job_name='Renamed', archive_prefix='new')
    row = tests_api.list_restore_test_plan(cfg)['jobs'][0]
    assert row['job_id'] == job_id and row['display_name'] == 'Renamed'
    assert row['verification_status'] == 'verified' and not row['is_overdue']
    report = tests_api.list_restore_tests(cfg)[0]
    assert report['job_name_snapshot'] == 'Original' and report['current_job_name'] == 'Renamed'
    runner = _load_restore_runner(); monkeypatch.setenv('BORG_UI_DATA_ROOT', str(setup[3]))
    repo = runner.discover_repos(cfg)[0]
    instance = object.__new__(runner.RestoreTest)
    instance.args=SimpleNamespace(force=False);instance.status_dir=directory;instance.test_interval=30;instance.log=lambda *a:None
    assert not instance._should_test(repo)
    edit(setup, job_id, repository_key='repo_b')
    assert tests_api.list_restore_test_plan(cfg)['jobs'][0]['is_overdue']
    assert instance._should_test(runner.discover_repos(cfg)[0])


def test_migrated_shipped_restore_evidence_remains_valid_after_rename(setup, monkeypatch):
    from migrations.identity_records import project_records, verify_records
    result, metadata = create(setup, job_name='Appdata', archive_prefix='appdata-backup')
    job_id = result['job_id']; cfg = setup[0]
    cfg.update(STATUS_DIR=str(setup[3]/'status'), RESTORE_TEST_STATUS_DIR=str(setup[3]/'tests'))
    directory = Path(cfg['RESTORE_TEST_STATUS_DIR']); directory.mkdir()
    tests_api.update_restore_test_policy(cfg, job_id, {'mode':'scheduled','level':1,'interval_days':30})
    target = capture_repository(cfg, job_id)['repo']
    legacy = {'report_schema_version':1, 'report_id':'RT-20260906-120000-appdata_local',
              'type':'appdata', 'location':'local', 'repository':target,
              'tested_archive':'appdata-backup-2026-09-06_12-00-00', 'test_result':'success',
              'test_level':1, 'test_date':datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    path = directory/f'{job_id}.test'
    projection = project_records({str(directory/'appdata_local.test'):{'kind':'restore_test',
        'data':legacy, 'legacy_key':'appdata_local', 'target_path':str(path)}},
        {job_id:metadata}, {'appdata_local':job_id})
    assert not projection['reasons']
    assert not verify_records(projection['records'], {job_id:metadata}, {'appdata_local':job_id})
    migrated = projection['records'][str(path)]['data']
    assert migrated == {**legacy, 'schema_version':1, 'job_id':job_id}
    path.write_text(json.dumps(migrated)); before = path.read_bytes()
    edit(setup, job_id, job_name='Renamed', archive_prefix='new-prefix')
    plan = tests_api.list_restore_test_plan(cfg)['jobs'][0]
    assert plan['verification_status'] == 'verified' and not plan['is_overdue']
    runner = _load_restore_runner(); monkeypatch.setenv('BORG_UI_DATA_ROOT', str(setup[3]))
    tester = object.__new__(runner.RestoreTest)
    tester.args=SimpleNamespace(force=False); tester.status_dir=directory; tester.test_interval=30; tester.log=lambda *a:None
    assert not tester._should_test(runner.discover_repos(cfg)[0])
    edit(setup, job_id, repository_key='repo_b')
    assert tests_api.list_restore_test_plan(cfg)['jobs'][0]['verification_reason'] == 'target_changed'
    assert tester._should_test(runner.discover_repos(cfg)[0])
    assert path.read_bytes() == before


@pytest.mark.parametrize(('evidence', 'status', 'reason'), [
    ({}, 'verified', 'within_validity'),
    ({'repository':'/different'}, 'stale', 'target_changed'),
    ({'tested_archive':'foreign-2026'}, 'stale', 'target_changed'),
    ({'tested_archive':'archive2-2026'}, 'stale', 'target_changed'),
    ({'tested_archive':''}, 'stale', 'target_unknown'),
    ({'repository':''}, 'stale', 'target_unknown'),
    ({'repository_snapshot':'/different', 'archive_prefix_snapshot':'archive'}, 'stale', 'target_changed'),
    ({'repository_snapshot':'/repo', 'archive_prefix_snapshot':'foreign'}, 'stale', 'target_changed'),
    ({'repository_snapshot':'', 'archive_prefix_snapshot':'archive'}, 'stale', 'target_unknown'),
    ({'run_id':RUN_ID}, 'stale', 'target_unknown'),
    ({'report_id':RUN_ID}, 'stale', 'target_unknown'),
    ({'archive_prefixes_snapshot':['archive']}, 'stale', 'target_unknown'),
    ({'policy_snapshot':{'mode':'scheduled'}}, 'stale', 'target_unknown'),
    ({'job_id':OTHER_ID}, 'never', 'no_test_report'),
    ({'identity_state':'unassigned'}, 'never', 'no_test_report'),
    ({'repository_snapshot':'/repo', 'archive_prefix_snapshot':'archive',
      'repository':'/different', 'tested_archive':'foreign-2026', 'run_id':RUN_ID}, 'verified', 'within_validity'),
])
def test_restore_api_and_runner_agree_on_recorded_target_evidence(tmp_path, evidence, status, reason):
    cfg = {'RESTORE_TEST_STATUS_DIR':str(tmp_path)}
    repository = info()
    job = {**repository['job'], 'location':'local', 'repo_path':repository['repo'],
           'restore_test_policy':{'mode':'scheduled','interval_days':30,'validity_days':30}}
    report = {'schema_version':1, 'job_id':JOB_ID, 'repository':'/repo',
              'type':'archive', 'location':'local', 'tested_archive':'archive-2026',
              'test_date':datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'test_result':'success', **evidence}
    path = tmp_path/f'{JOB_ID}.test'; path.write_text(json.dumps(report)); before = path.read_bytes()
    proof = tests_api.build_restore_verification_map(cfg, [job])[JOB_ID]
    assert (proof['status'], proof['reason']) == (status, reason)
    assert not proof['is_overdue']
    runner = _load_restore_runner(); tester = object.__new__(runner.RestoreTest)
    tester.args=SimpleNamespace(force=False); tester.status_dir=tmp_path; tester.test_interval=30; tester.log=lambda *a:None
    assert tester._should_test(repository) == (status != 'verified')
    assert path.read_bytes() == before


@pytest.mark.parametrize('target', ['/different', ''])
def test_expired_restore_evidence_stays_overdue_with_unverified_target(tmp_path, target):
    cfg = {'RESTORE_TEST_STATUS_DIR':str(tmp_path)}
    report = {'job_id':JOB_ID, 'repository':target, 'tested_archive':'archive-2026',
              'test_result':'success', 'test_date':(datetime.now()-timedelta(days=32)).strftime('%Y-%m-%d %H:%M:%S')}
    (tmp_path/f'{JOB_ID}.test').write_text(json.dumps(report))
    job = {'job_id':JOB_ID, 'repo_path':'/repo', 'archive_prefixes':['archive'], 'location':'local',
           'restore_test_policy':{'mode':'scheduled','interval_days':30,'validity_days':30}}
    proof = tests_api.build_restore_verification_map(cfg, [job])[JOB_ID]
    assert proof['status'] == 'stale' and proof['reason'] in {'target_unknown', 'target_changed'}
    assert proof['is_overdue']


@pytest.mark.parametrize('time_evidence', [{}, {'test_date':'invalid'}])
@pytest.mark.parametrize('mode', ['scheduled', 'manual_only'])
@pytest.mark.parametrize('native', [False, True])
def test_restore_file_mtime_cannot_replace_missing_recorded_test_date(tmp_path, monkeypatch, time_evidence, mode, native):
    cfg = {'BACKUP_SCRIPTS_DIR':str(tmp_path), 'RESTORE_TEST_STATUS_DIR':str(tmp_path)}
    report = {'job_id':JOB_ID, 'repository':'/repo', 'tested_archive':'archive-2026',
              'test_result':'success', **time_evidence}
    if native:
        report.update(run_id=RUN_ID, repository_snapshot='/repo', archive_prefix_snapshot='archive')
    path = tmp_path/f'{JOB_ID}.test'; path.write_text(json.dumps(report)); before = path.read_bytes()
    assert path.stat().st_mtime > (datetime.now()-timedelta(minutes=1)).timestamp()
    job = {'job_id':JOB_ID, 'repo_path':'/repo', 'archive_prefixes':['archive'], 'location':'local',
           'restore_test_policy':{'mode':mode,'interval_days':30,'validity_days':30}}
    proof = tests_api.build_restore_verification_map(cfg, [job])[JOB_ID]
    assert (proof['status'], proof['reason']) == ('stale', 'test_date_unknown')
    assert proof['last_test_date'] == proof['valid_until'] == '' and not proof['is_overdue']
    monkeypatch.setattr('status_read_model.configured_jobs', lambda conf: {JOB_ID:job})
    plan = tests_api.list_restore_test_plan(cfg)['jobs'][0]
    assert plan['verification_reason'] == 'test_date_unknown'
    assert plan['last_test_date'] == plan['next_due_at'] == ''
    assert plan['is_overdue'] == (mode == 'scheduled')
    runner = _load_restore_runner(); tester = object.__new__(runner.RestoreTest)
    tester.args=SimpleNamespace(force=False); tester.status_dir=tmp_path; tester.test_interval=30; tester.log=lambda *a:None
    assert tester._should_test(info())
    assert path.read_bytes() == before


@pytest.mark.parametrize('field', ['start_ts', 'end_ts'])
def test_restore_recorded_time_fallback_preserves_age_after_file_copy(tmp_path, field):
    cfg = {'RESTORE_TEST_STATUS_DIR':str(tmp_path)}
    recorded_date = (datetime.now()-timedelta(days=32)).strftime('%Y-%m-%d %H:%M:%S')
    report = {'job_id':JOB_ID, 'repository':'/repo', 'tested_archive':'archive-2026',
              'test_result':'success', 'test_date':'invalid', field:recorded_date}
    (tmp_path/f'{JOB_ID}.test').write_text(json.dumps(report))
    job = {'job_id':JOB_ID, 'repo_path':'/repo', 'archive_prefixes':['archive'], 'location':'local',
           'restore_test_policy':{'mode':'scheduled','interval_days':30,'validity_days':30}}
    proof = tests_api.build_restore_verification_map(cfg, [job])[JOB_ID]
    assert (proof['status'], proof['reason']) == ('stale', 'validity_expired')
    assert proof['last_test_date'] == recorded_date and proof['is_overdue']
    runner = _load_restore_runner(); tester = object.__new__(runner.RestoreTest)
    tester.args=SimpleNamespace(force=False); tester.status_dir=tmp_path; tester.test_interval=30; tester.log=lambda *a:None
    assert tester._should_test(info())


def test_result_payload_authority_does_not_create_ghost_plan(setup):
    result, _ = create(setup); cfg=setup[0]; directory=setup[3]/'tests';directory.mkdir()
    cfg['RESTORE_TEST_STATUS_DIR']=str(directory)
    for name, data in [('deleted', {'job_id':OTHER_ID,'job_name_snapshot':'Removed'}),
                       (result['job_id'], {'job_key':'legacy_local'})]:
        (directory/f'{name}.test').write_text(json.dumps(data))
    rows = tests_api.list_restore_tests(cfg)
    assert {r['identity_scope'] for r in rows} == {'deleted','unassigned'}
    assert all(not r['deletable'] for r in rows)
    plan=tests_api.list_restore_test_plan(cfg)
    assert [r['job_id'] for r in plan['jobs']] == [result['job_id']]
    assert plan['jobs'][0]['verification_status'] == 'never'
    with pytest.raises(ValueError): tests_api.delete_restore_test(cfg, result['job_id'])


def test_runner_selects_latest_from_prefix_union_only(monkeypatch):
    runner=_load_restore_runner(); instance=object.__new__(runner.RestoreTest); repo=info()
    repo['job']['archive_prefixes']=['new','old']; calls=[]
    def borg(args, env):
        calls.append(args); prefix=args[3][:-2]
        return SimpleNamespace(returncode=0, stdout=json.dumps({'archives':[{'name':prefix+'-1','start':'2026-09-02' if prefix=='old' else '2026-09-01'}]}))
    instance._borg=borg
    _, archive=instance._latest_owned_archive(repo,{})
    assert archive=='old-1' and [c[3] for c in calls]==['new-*','old-*']
    instance._borg=lambda *a: SimpleNamespace(returncode=0,stdout=json.dumps({'archives':[{'name':'foreign-1'}]}))
    with pytest.raises(ValueError): instance._latest_owned_archive(repo,{})


@pytest.mark.parametrize('query', ['job=photos_local','job_id=photos_local',f'job_id={JOB_ID}&job_id={OTHER_ID}',f'job_id={JOB_ID}&job=photos_local'])
def test_restore_http_rejects_aliases_duplicates_and_mixed_identity(query):
    from borg_backup_ui import BackupUIHandler
    handler=BackupUIHandler.__new__(BackupUIHandler);handler.config={};handler._require_data_dir_ready=lambda:None
    with pytest.raises(ValueError): handler._get_restore_archives(query)
    with pytest.raises(ValueError): handler._get_restore_files(query+'&archive=archive-1')


def test_restore_precheck_passes_frozen_identity_and_rejects_foreign_archive(monkeypatch, tmp_path):
    monkeypatch.setattr(restore,'_get_job_repo_info',lambda *a: info())
    monkeypatch.setattr(restore,'ensure_restore_repository_available',lambda *a:None)
    monkeypatch.setattr(restore,'_repository_borg_env',lambda *a:{})
    monkeypatch.setattr(restore,'_validate_target_dir',lambda *a:tmp_path)
    monkeypatch.setattr(restore,'_precheck_metadata',lambda *a: {'ok':True,'exit_code':0,'stdout':'','stderr':'','basename':'file','source_type':'-'})
    data=restore.restore_precheck({},JOB_ID,'archive-1','file',str(tmp_path),'skip')
    assert data['job_id']==JOB_ID and data['repo']=='/repo'
    with pytest.raises(ValueError):restore.restore_precheck({},JOB_ID,'foreign-1','file',str(tmp_path),'skip')


def test_finished_restore_history_failure_is_retried_after_restart(monkeypatch, tmp_path):
    cfg={'BACKUP_SCRIPTS_DIR':str(tmp_path)};work=[]
    ready_gate(cfg, monkeypatch, tmp_path / "writer-gate")
    monkeypatch.setattr(restore, '_get_job_repo_info',lambda *a: info())
    monkeypatch.setattr(restore.threading,'Thread',lambda **kw:SimpleNamespace(start=lambda:work.append(kw['target'])))
    monkeypatch.setattr(restore,'start_restore',lambda *a,**kw:{'destination_path':'/finished'})
    record=restore._record_restore_history
    monkeypatch.setattr(restore,'_record_restore_history',lambda *a:(_ for _ in ()).throw(OSError('full')))
    run_id=restore.start_restore_async(cfg,JOB_ID,'archive-1','file','/target','skip')['restore_id'];work[0]()
    pending=read_json(restore._restore_runs_file(cfg))['runs'][run_id]
    assert pending['state']=='done' and pending['job_id']==JOB_ID
    monkeypatch.setattr(restore,'_record_restore_history',record)
    restore._RESTORE_RUNS.clear();restore._RESTORE_RUNS_LOADED=False
    history=restore.list_restore_history(cfg)['runs']
    assert len(history)==1 and history[0]['state']=='done' and history[0]['run_id']==run_id
    assert read_json(restore._restore_runs_file(cfg))['runs']=={}


def test_running_and_unpersisted_history_are_not_trimmed(tmp_path):
    cfg={'BACKUP_SCRIPTS_DIR':str(tmp_path)}
    for number in range(30):
        restore._RESTORE_RUNS[str(number)]={'restore_id':str(number),'state':'running','job_id':JOB_ID}
    restore._RESTORE_RUNS['pending']={'restore_id':'pending','state':'done','job_id':JOB_ID}
    restore._trim_runs(cfg)
    assert len(restore._RESTORE_RUNS)==31


def test_result_writer_saves_uuid_snapshots_and_refuses_ambiguous_overwrite(tmp_path,monkeypatch):
    runner=_load_restore_runner();monkeypatch.setenv('BORG_UI_DATA_ROOT',str(tmp_path))
    monkeypatch.setattr(runner,'_refresh_unraid_dashboard_widget_cache',lambda *a:None)
    instance=object.__new__(runner.RestoreTest)
    instance.status_dir=tmp_path/'tests';instance.conf={};instance.test_level=1;instance.sample_size=2
    instance.log=lambda *a:None;instance._notify_event=lambda *a:None
    repo=info();repo['run_id']=RUN_ID
    def write(): instance._write(JOB_ID,repo,'success',1,0,0,0,'not_applicable','archive-1',{},[])
    write();target=instance.status_dir/f'{JOB_ID}.test';data=read_json(target)
    assert data['report_id']==data['run_id']==RUN_ID and data['job_id']==JOB_ID
    assert data['repository_snapshot']=='/repo' and data['archive_prefix_snapshot']=='archive'
    assert data['job_name_snapshot']=='Photos' and data['location_snapshot']=='local'
    assert not {'passphrase_file','storage','job'}.intersection(data)
    target.write_text(json.dumps({'job_key':'ambiguous_legacy'}));original=target.read_bytes()
    with pytest.raises(ValueError,match='ownership'): write()
    assert target.read_bytes()==original


def test_restore_test_notification_and_reminder_use_same_uuid(tmp_path,monkeypatch):
    runner=_load_restore_runner();instance=object.__new__(runner.RestoreTest)
    instance.conf={};instance.args=SimpleNamespace(scheduled=True);instance.test_level=1
    instance.mail_config=None;instance.log=lambda *a:None;repo=info();repo['run_id']=RUN_ID
    events=[];cleared=[]
    monkeypatch.setattr('lib.notification_events.send_event',lambda config,event,**kw:events.append(event))
    monkeypatch.setattr('lib.notification_events.clear_reminder_prefix',lambda config,prefix:cleared.append(prefix))
    instance._notify_event('restore_test_success',repo,'Successful')
    assert events[0].job_id==JOB_ID and events[0].run_id==RUN_ID
    assert events[0].job_name_snapshot=='Photos'
    assert cleared==[f'restore_test_overdue:{JOB_ID}:']


def test_http_manual_and_scheduled_tests_submit_ids_with_policy(setup,monkeypatch):
    from borg_backup_ui import BackupUIHandler
    import jobs_api
    result,_=create(setup);job_id=result['job_id'];cfg=setup[0]
    tests_api.update_restore_test_policy(cfg,job_id,{'mode':'scheduled','level':3,'interval_days':7})
    scripts=setup[3]/'scripts';scripts.mkdir(exist_ok=True);(scripts/'borg_restore_test.py').write_text('# synthetic')
    monkeypatch.setattr(jobs_api,'resolve_scripts_dir',lambda config:scripts)
    starts=[]
    manager=SimpleNamespace(start=lambda *a,**kw:starts.append((a,kw)) or (True,''),get_state=lambda job:{'run_id':RUN_ID}, get_all_states=lambda:{})
    monkeypatch.setattr(jobs_api.JobManager,'get',lambda:manager)
    handler=BackupUIHandler.__new__(BackupUIHandler);handler.config=cfg
    handler._require_data_dir_ready=lambda:None;handler._get_current_session_meta=lambda:{}
    handler._has_valid_api_token_header=lambda:False
    handler._read_json_body=lambda:{'job_id':job_id}
    response=handler._post_run_restore_test_job()
    assert response['selected_jobs']==[job_id]
    command=starts[-1][0][1]
    assert command[command.index('--job-id')+1]==job_id and command[command.index('--level')+1]=='3'
    assert '--force' in command and '--job-key' not in command
    response=handler._start_restore_test_from_body({'scheduled':True})
    assert response['selected_jobs']==[job_id] and '--scheduled' in starts[-1][0][1]
    assert starts[-1][1]['extra_env']['BORG_UI_DATA_ROOT']==str(setup[3])


def test_ambiguous_json_proof_cannot_satisfy_job_or_overwrite_existing_result(tmp_path):
    directory=tmp_path/'tests';directory.mkdir();target=directory/f'{JOB_ID}.test'
    raw='{"job_id":"'+OTHER_ID+'","job_id":"'+JOB_ID+'","test_result":"success"}'
    target.write_text(raw)
    job={'job_id':JOB_ID,'location':'local','restore_test_policy':{'mode':'scheduled'},'repo_path':'/repo','archive_prefixes':['archive']}
    proof=tests_api.build_restore_verification_map({'RESTORE_TEST_STATUS_DIR':str(directory)},[job])
    assert proof[JOB_ID]['status']=='never' and target.read_text()==raw


def test_configured_chunk_rules_survive_renaming_and_prefix_changes():
    runner=_load_restore_runner();instance=object.__new__(runner.RestoreTest)
    instance.force_chunk_types={'vms'}
    repo=info();repo['job'].update(name='Renamed VM job',archive_prefixes=['new','vms-backup'])
    assert instance._force_chunk_for_repo(repo)
    repo['job']['archive_prefixes']=['unrelated']
    assert not instance._force_chunk_for_repo(repo)
