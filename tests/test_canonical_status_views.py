"""#476: configured UUID authority across dashboard, widgets and history."""
from copy import deepcopy
from datetime import datetime, date, timedelta, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / 'api', ROOT / 'runtime', ROOT / 'runtime/lib'):
    sys.path.insert(0, str(directory))

from test_canonical_job_wizard import setup, create, edit
from inventory_store import atomic_write_json
from status import BackupStatus
from status_api import get_status_data
from history_api import get_history_data
from reports_api import get_report_jobs, get_report_data
from status_read_model import configured_jobs
from weekly_snapshots import read_observations, write_current, chart_series


@pytest.fixture(autouse=True)
def isolated(setup, monkeypatch):
    config, _, _, root = setup
    config.update(STATUS_DIR=str(root / 'status'), SNAPSHOT_FILE=str(root / 'weekly-snapshots.json'),
                  RESTORE_TEST_DIR=str(root / 'restore-tests'))
    monkeypatch.setenv('BORG_UI_CONTROL_ROOT', str(root / 'run'))
    monkeypatch.setattr('config_api.read_expanded_conf', lambda cfg: {})
    monkeypatch.setattr('jobs_api.get_all_runtime_states', lambda cfg: {})
    monkeypatch.setattr('schedule_api._update_crontab', lambda rows: {})


def saved(setup, job_id, **overrides):
    job = configured_jobs(setup[0])[job_id]
    status = BackupStatus(job_id=job_id, run_id=str(uuid4()), job_name_snapshot=job['name'],
        archive_prefix_snapshot=job['archive_prefix'], archive_prefixes_snapshot=job['archive_prefixes'],
        repository_key_snapshot=job['repository_key'], repository_snapshot=job['repo_path'],
        location_snapshot=job['location'], status='success', exit_code=0,
        timestamp='2026-09-01 12:00:00', repository_size=100, original_size=200, duration_seconds=10)
    for key, value in overrides.items(): setattr(status, key, value)
    status.save(Path(setup[0]['STATUS_DIR']))
    return status


def test_config_to_pfsense_retains_one_current_card_and_historical_snapshots(setup):
    result, _ = create(setup, job_name='config', archive_prefix='config')
    job_id = result['job_id']
    old = saved(setup, job_id)
    edit(setup, job_id, job_name='pfsense', archive_prefix='pfsense', repository_key='repo_b')
    saved(setup, job_id, timestamp='2026-09-02 12:00:00')
    data = get_status_data(setup[0], write_snapshots=False)
    assert len(data['backups']) == data['summary']['total'] == 1
    assert data['backups'][0]['job_id'] == job_id and data['backups'][0]['name'] == 'pfsense'
    assert data['backups'][0]['location'] == 'storagebox'
    assert data['backups'][0]['growth_bytes'] is None
    history = get_history_data(setup[0], {'job_id':job_id})['entries']
    assert len(history) == 2 and {row['current_job_name'] for row in history} == {'pfsense'}
    assert history[1]['job_name_snapshot'] == 'config' and history[1]['location_snapshot'] == 'local'
    report = get_report_data(setup[0], job_id)
    assert report['run_count'] == 2 and report['display_name'] == 'pfsense'
    assert report['runs'][0]['repository_snapshot'] == old.repository_snapshot
    assert [row['job_id'] for row in get_report_jobs(setup[0])] == [job_id]


def test_payload_identity_ignores_filename_and_does_not_invent_legacy_snapshots(setup):
    result, _ = create(setup, job_name='pfsense')
    directory = Path(setup[0]['STATUS_DIR']); directory.mkdir()
    path = directory / '2026-09-01_12-00-00_some_other_name_usb.status'
    payload = {'job_id':result['job_id'], 'backup_type':'config', 'location':'local',
               'timestamp':'2026-09-01 12:00:00', 'status':'success', 'exit_code':0}
    path.write_text(json.dumps(payload)); original = path.read_bytes()
    row = get_status_data(setup[0], write_snapshots=False)['backups'][0]
    assert row['legacy_status'] and row['name'] == 'pfsense' and row['status'] == 'success'
    assert row['job_name_snapshot'] == row['run_id'] == row['repository_snapshot'] == ''
    assert row['historical_name'] == 'config' and row['location'] == 'local'
    native = saved(setup, result['job_id'], timestamp='2026-08-01 12:00:00')
    row = get_status_data(setup[0], write_snapshots=False)['backups'][0]
    assert row['run_id'] == native.run_id and not row['legacy_status']
    assert path.read_bytes() == original


def test_unassigned_and_deleted_statuses_never_create_active_jobs(setup):
    result, _ = create(setup)
    live = saved(setup, result['job_id'])
    root = Path(setup[0]['STATUS_DIR'])
    deleted = str(uuid4())
    (root / 'deleted.status').write_text(json.dumps({'job_id':deleted, 'job_name_snapshot':'Deleted job',
        'identity_state':'unassigned', 'identity_reason':'deleted_job', 'status':'error'}))
    (root / 'orphan.status').write_text(json.dumps({'backup_type':'ghost', 'location':'usb','status':'error'}))
    data = get_status_data(setup[0], write_snapshots=False)
    assert data['summary']['total'] == data['summary']['success'] == 1
    assert data['summary']['error'] == 0
    assert get_history_data(setup[0], {'scope':'deleted'})['total'] == 1
    assert get_history_data(setup[0], {'scope':'unassigned'})['total'] == 1
    assert get_report_data(setup[0], deleted)['identity_scope'] == 'deleted'
    assert get_report_data(setup[0], scope='unassigned')['run_count'] == 1
    assert len(get_report_jobs(setup[0])) == 3


def test_same_display_name_never_merges_distinct_jobs(setup):
    one, _ = create(setup, job_name='Identical name', archive_prefix='one')
    two, _ = create(setup, job_name='Identical name', archive_prefix='two')
    saved(setup, one['job_id']); saved(setup, two['job_id'], status='error')
    data = get_status_data(setup[0], write_snapshots=False)
    assert data['summary']['total'] == 2 and data['summary']['success'] == data['summary']['error'] == 1
    assert get_report_data(setup[0], one['job_id'])['success_count'] == 1
    assert get_report_data(setup[0], two['job_id'])['success_count'] == 0


def test_runtime_precedes_last_failure_in_dashboard_and_widget_counts(setup, monkeypatch):
    result, _ = create(setup)
    saved(setup, result['job_id'], status='error', exit_code=2)
    run_id = str(uuid4())
    monkeypatch.setattr('jobs_api.get_all_runtime_states', lambda cfg: {result['job_id']:{'running':True,'run_id':run_id,'start_time':'2026-09-06T12:00:00'}})
    data = get_status_data(setup[0], write_snapshots=False)
    assert data['summary']['running'] == 1 and data['summary']['error'] == 0
    assert data['backups'][0]['active_run_id'] == run_id
    from homepage_widget_api import build_homepage_widget_summary
    from unraid_dashboard_widget import build_unraid_dashboard_widget_cache
    widget = build_unraid_dashboard_widget_cache(setup[0], data)
    homepage = build_homepage_widget_summary(setup[0])
    assert widget['jobs']['running'] == homepage['active']['count'] == 1
    assert widget['jobs']['failed'] == homepage['backups']['failed'] == 0
    assert widget['jobs']['items'][0]['job_id'] == result['job_id']
    assert widget['status']['state'] == 'running'


def test_never_run_and_disabled_jobs_have_consistent_counts(setup):
    first, _ = create(setup, archive_prefix='first')
    second, _ = create(setup, archive_prefix='second')
    saved(setup, second['job_id'], status='error', exit_code=2)
    from job_actions import set_job_enabled
    set_job_enabled(setup[0], second['job_id'], False)
    data = get_status_data(setup[0], write_snapshots=False)
    assert data['summary']['total'] == 2 and data['summary']['never'] == data['summary']['disabled'] == 1
    assert data['summary']['error'] == 0
    from homepage_widget_api import build_homepage_widget_summary
    from unraid_dashboard_widget import build_unraid_dashboard_widget_cache
    widget = build_unraid_dashboard_widget_cache(setup[0], data)
    homepage = build_homepage_widget_summary(setup[0])
    assert widget['jobs']['total'] == homepage['backups']['total'] == 2
    assert widget['jobs']['failed'] == homepage['backups']['failed'] == 0
    assert widget['jobs']['never'] == homepage['backups']['never'] == 1


def observation(job_id, week, size, **extra):
    return {'job_id':job_id,'week':week,'size':size,
            'source_records':[{'source':'/fixture/weekly.json','locator':'/old/0'}], **extra}


def snapshot(path, rows):
    atomic_write_json(path, {'schema_version':1,'identity_schema_version':1,'observations':rows})


def test_weekly_both_locations_deduplicate_equal_and_preserve_conflicting_values(setup):
    result, _ = create(setup); job_id = result['job_id']
    first = Path(setup[0]['SNAPSHOT_FILE']); second = Path(setup[0]['STATUS_DIR']) / 'weekly-snapshots.json'
    row = observation(job_id,'2026-08-24',100)
    snapshot(first,[row]); snapshot(second,[row,observation(job_id,'2026-08-24',150)])
    before = second.read_bytes()
    rows = read_observations(first,second)
    assert len(rows) == 2 and all(row['conflict'] for row in rows)
    assert chart_series(rows,{job_id})[job_id][0]['size'] is None
    st = saved(setup,job_id,repository_size=200)
    write_current(first,{job_id:st},legacy_file=second)
    once = first.read_bytes()
    write_current(first,{job_id:st},legacy_file=second)
    assert first.read_bytes() == once and second.read_bytes() == before
    assert {row['size'] for row in read_observations(first,second) if row['week']=='2026-08-24'} == {100,150}
    dashboard = get_status_data(setup[0],write_snapshots=False)
    assert dashboard['backups'][0]['growth_bytes'] is None


def test_weekly_writer_does_not_silently_convert_legacy_or_drop_unassigned(setup):
    result, _ = create(setup); status = saved(setup,result['job_id'])
    path = Path(setup[0]['SNAPSHOT_FILE'])
    path.write_text(json.dumps({'legacy_local':[{'week':'2026-08-24','size':100}]}))
    before=path.read_bytes()
    with pytest.raises(ValueError,match='approved identity migration'): write_current(path,{result['job_id']:status})
    assert path.read_bytes()==before
    row=observation(None,'2026-08-24',100,identity_state='unassigned',legacy_job_key='legacy_local')
    snapshot(path,[row]);write_current(path,{result['job_id']:status})
    assert row in read_observations(path)


def test_overdue_and_report_mail_follow_id_after_rename(setup):
    result,_=create(setup,job_name='config');job_id=result['job_id']
    saved(setup,job_id,timestamp='2026-09-01 12:00:00')
    from schedule_api import write_schedules
    write_schedules(setup[0],{job_id:{'enabled':True,'cron':'0 12 * * *'}})
    edit(setup,job_id,job_name='pfsense',archive_prefix='pfsense')
    data=get_status_data(setup[0],write_snapshots=False,now=datetime(2026,9,6,20))
    assert data['backups'][0]['backup_overdue'] and data['summary']['warning']==1
    from report_mail_api import _build_html_report
    html=_build_html_report(setup[0],now=datetime(2026,9,6,20))
    assert 'pfsense' in html and 'Run name: config' in html


def test_restore_proof_requires_matching_payload_and_current_target(setup):
    result,meta=create(setup)
    meta['restore_test_policy'] = {'mode':'manual_only','interval_days':30,'validity_days':30,'level':2,'max_runtime_minutes':0}
    atomic_write_json(Path(result['metadata_path']),meta)
    job=configured_jobs(setup[0])[result['job_id']]
    from restore_tests_api import resolve_restore_test_dir
    path=resolve_restore_test_dir(setup[0])/(job['job_id']+'.test')
    proof={'job_id':job['job_id'],'test_result':'success','test_date':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
           'archive_prefix_snapshot':job['archive_prefix'],'repository_snapshot':job['repo_path']}
    atomic_write_json(path,proof)
    assert get_status_data(setup[0],write_snapshots=False)['backups'][0]['restore_verification_status']=='verified'
    assert get_report_jobs(setup[0])[0]['restore_verification_status'] == 'verified'
    assert get_report_data(setup[0], job['job_id'])['restore_verification_status'] == 'verified'
    edit(setup,job['job_id'],job_name='renamed')
    assert get_status_data(setup[0],write_snapshots=False)['backups'][0]['restore_verification_status']=='verified'
    edit(setup,job['job_id'],archive_prefix='new-prefix')
    assert get_status_data(setup[0],write_snapshots=False)['backups'][0]['restore_verification_status']=='verified'
    atomic_write_json(path,{**proof,'archive_prefix_snapshot':'unrelated-prefix'})
    assert get_status_data(setup[0],write_snapshots=False)['backups'][0]['restore_verification_status']=='stale'
    atomic_write_json(path,proof)
    edit(setup,job['job_id'],repository_key='repo_b')
    assert get_status_data(setup[0],write_snapshots=False)['backups'][0]['restore_verification_status']=='stale'
    atomic_write_json(path,{**proof,'job_id':str(uuid4())})
    assert get_status_data(setup[0],write_snapshots=False)['backups'][0]['restore_verification_status']=='never'


def test_old_widget_cache_is_invalidated_without_adopting_ghost_jobs(setup):
    from unraid_dashboard_widget import write_unraid_dashboard_widget_startup_cache
    result,_=create(setup)
    path=setup[3]/'widget.json';setup[0]['UNRAID_DASHBOARD_WIDGET_FILE']=str(path)
    atomic_write_json(path,{'schema_version':1,'cache_state':'fresh','jobs':{'enabled':1,'successful':1,'items':[{'key':'ghost_local','last_status':'success'}]}})
    output=write_unraid_dashboard_widget_startup_cache(setup[0])
    assert output['identity_schema_version']==1
    assert output['jobs']['total']==1 and output['jobs']['items'][0]['job_id']==result['job_id']
    assert 'ghost' not in json.dumps(output)
