"""Scoped monitoring projections and exact read contracts (#745)."""
import json
import pytest
from test_mobile_auth import config, paired, handler  # noqa: F401
from test_mobile_controls import make_handler
import mobile_auth as auth
import mobile_api as api
import mobile_monitoring as monitoring


@pytest.fixture
def mobile(config):
    _, credentials = paired(config)
    return make_handler(config, auth.authenticate(config, credentials['access_token']))


def test_locations_match_browser():
    assert monitoring.LOCATIONS == ('local', 'usb', 'smb', 'storagebox', 'utility')
    assert monitoring.location({'location':'USB'}) == 'usb'
    assert monitoring.location({'location':'smb','is_utility':True}) == 'utility'
    assert monitoring.location({'location':'other'}) == 'local'


def test_archives_identity_bound_and_revocation(mobile, monkeypatch):
    import repositories_api as repos
    monkeypatch.setattr(repos, 'read_repository_store', lambda _: {'repositories':[{'repository_key':'repo','display_name':'Vault'}]})
    calls=[]
    def read(config, key, limit):
        calls.append((key,limit))
        return {'archive_count':150,'archives':[{'name':'synthetic-archive','start':'2026-11-17T01:00:00Z','end':'2026-11-17T01:02:03Z','path':'/private','passphrase':'secret'}]}
    monkeypatch.setattr(repos, 'get_repository_archives', read)
    body={'repository_id':api._id('repo')}
    data=monitoring.handle(mobile,'repositories/archives',body)
    assert data['items'][0]['duration_seconds']==123 and data['total']==150
    assert calls==[('repo',100)] and '/private' not in json.dumps(data)
    for invalid in ({'repository_id':'../private'}, {**body,'path':'/private'}, {'repository_id':'f'*32}):
        with pytest.raises(auth.MobileError): monitoring.handle(mobile,'repositories/archives',invalid)
    assert len(calls)==1
    def revoke(*args,**kwargs):
        auth.revoke(mobile.config,'viewer',mobile._mobile_session['id'])
        return read(*args,**kwargs)
    monkeypatch.setattr(repos,'get_repository_archives',revoke)
    with pytest.raises(auth.MobileError) as exc: monitoring.handle(mobile,'repositories/archives',body)
    assert exc.value.api_status==401


def test_reports_validate_days_preserve_denominator_and_nulls(mobile):
    source={'from':'2026-11-11','to':'2026-11-17','counts':dict(success=2,warning=1,error=1,skipped=7,cancelled=3,unknown=1),'success_rate':50.0,'average_duration_seconds':None,'daily':[],'private':'secret'}
    calls=[]
    mobile._get_report_overview=lambda query: calls.append(query) or source
    for days in (7,30,90):
        data=monitoring.handle(mobile,'reports/read',{'days':days})
        assert data['success_rate']==50 and data['counts']['skipped']==7
        assert data['average_duration_seconds'] is None and 'private' not in data
    assert calls==[f'days={n}&location=all' for n in (7,30,90)]
    for body in ({'days':True},{'days':14},{'days':'7'},{'days':7,'location':'x'}):
        with pytest.raises(auth.MobileError):monitoring.handle(mobile,'reports/read',body)


def test_monitoring_optional_sections_and_private_fields(mobile,monkeypatch):
    import resource_metrics,restore_tests_api,job_groups
    monkeypatch.setattr(resource_metrics,'get_resource_metrics',lambda _: {'available':True,'stale':False,'timestamp':1794880800,'host':{'cpu_percent':None,'memory_total_bytes':100,'memory_available_bytes':40},'runs':[{'path':'/private'}]})
    monkeypatch.setattr(restore_tests_api,'list_restore_test_plan',lambda _: {'jobs':[{'job_key':'photos','display_name':'Photos','is_overdue':True,'last_test_result':'cancelled','verification_status':'verified','verification_evidence_date':'2026-11-01T01:00:00Z','next_due_at':'2026-11-08T01:00:00Z','policy':{'mode':'scheduled','interval_days':7},'job_meta_file':'/private'}]})
    monkeypatch.setattr(restore_tests_api,'list_restore_tests',lambda _: [{'job_key':'photos','steps':[{'step_id':'integrity_check','status':'failed','duration_ms':1200,'command':'secret command','message':'/private','error_code':'RT_CHECK_FAILED'}]}])
    monkeypatch.setattr(job_groups,'list_groups',lambda _: {'groups':[]})
    data=monitoring.handle(mobile,'monitoring',{})
    assert data['resources']['cpu_percent'] is None
    row=data['restore_tests']['items'][0]
    assert row['overdue'] and row['status']=='cancelled' and row['verification']=='verified'
    assert row['steps'][0]['duration_ms']==1200
    assert not any(x in json.dumps(data) for x in ('/private','secret command','job_meta_file'))
    def unavailable(_):raise OSError('private')
    monkeypatch.setattr(job_groups,'list_groups',unavailable)
    assert monitoring.handle(mobile,'monitoring',{})['groups'] is None


def test_group_details_are_bounded_and_separate_not_run(mobile,monkeypatch):
    import job_groups
    run={'status':'failed','steps':[{'job_key':'photos','status':'failed','error':'/private'},{'job_key':'removed','status':'not_run'}]}
    monkeypatch.setattr(job_groups,'list_groups',lambda _: {'groups':[{'id':'group','name':'Nightly','jobs':['photos','removed'],'run':run,'missing_jobs':['removed']}]})
    def history(config,key,limit):
        assert limit==5
        return {'runs':[run]}
    monkeypatch.setattr(job_groups,'group_history',history)
    data=monitoring.handle(mobile,'groups/read',{'group_id':api._id('group')})
    assert data['run']['completed']==1 and data['run']['total']==2
    assert data['run']['steps'][1]['job_name'] is None
    assert '/private' not in json.dumps(data)
    with pytest.raises(auth.MobileError):monitoring.handle(mobile,'groups/read',{'group_id':'f'*32})


@pytest.mark.parametrize('method,path', [('GET','resources'),('GET','monitoring'),('POST','repositories/archives'),('POST','reports/read'),('POST','groups/read')])
def test_new_routes_require_mobile_auth(config,method,path):
    route='/api/mobile/v1/'+path
    assert route in api.ROUTES[method]
    h=handler(config,method,route,{'Content-Type':'application/json'})
    assert not api.authorize(h,route,'request')
    h=handler(config,method,route+'?token=wrong',{'Content-Type':'application/json'})
    assert not api.authorize(h,route,'request')
