"""Job retention and exclusion behavior, including real Borg 1.4 (#459/#469/#470)."""
import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / 'api', ROOT / 'runtime'):
    sys.path.insert(0, str(folder))

from runtime.lib.retention_policy import normalize_retention, prune_arguments, RetentionError
from runtime.lib.borg_runner import BorgConfig, BorgRunner
from job_exclusions import marker_names, upload_bytes, prepare_file, read_file, cleanup_files, ExclusionError
from wizard_api import _retention_from_params
from check_api import CheckManager
from test_settings_transfer_repository_model import _canonical_source
from settings_transfer_api import export_jobs_bundle, import_jobs_bundle, ConfigurationExportError
from job_fixtures import job_id


def upload(data=b'# comment\r\nfm:*.tmp\r\n', name='exclude.txt'):
    return {'original_name': name, 'content_b64': base64.b64encode(data).decode()}


def test_wizard_exclusions_step_navigation():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    subprocess.run([node, 'tests/wizard_exclusions_step_ui.cjs'], cwd=ROOT, check=True)


def test_modes_disable_inactive_counts_and_keep_old_defaults():
    original = {'daily':'7','weekly':'4','monthly':'6','yearly':'3'}
    assert normalize_retention(original) == original
    for mode in ('last','all'):
        saved = _retention_from_params({'retention_mode':mode,'keep_last':'3','keep_daily':'99','keep_within':'7d'})
        assert not any(int(saved[p]) for p in original)
        assert saved['within'] == ''
    assert prune_arguments(_retention_from_params({'retention_mode':'last','keep_last':'3'})) == ['--keep-last','3']
    with pytest.raises(RetentionError, match='disabled'):
        prune_arguments({'mode':'all'})
    with pytest.raises(RetentionError):
        normalize_retention({'mode':'unknown'})
    with pytest.raises(RetentionError):
        normalize_retention({'mode':'last','last':0})


@pytest.mark.parametrize('value', ['-1','1.5','yes','1000001',True])
def test_invalid_counts_rejected_at_both_entry_points(value):
    with pytest.raises(ValueError):
        _retention_from_params({'retention_mode':'last','keep_last':value})
    with pytest.raises(ValueError):
        prune_arguments({'mode':'last','last':value})


def test_hourly_and_within_can_be_combined():
    source = {'mode':'tiered','hourly':'24','within':'2d','daily':'7','weekly':'0','monthly':'0','yearly':'0'}
    assert prune_arguments(source) == ['--keep-within','2d','--keep-hourly','24','--keep-daily','7','--keep-weekly','0','--keep-monthly','0','--keep-yearly','0']
    for interval in ('0d','-1d','1D','1d;rm','1.5d','1000000d'):
        with pytest.raises(RetentionError): normalize_retention({**source,'within':interval})


def test_keep_all_skips_prune_but_preserves_compact_checks_and_logging(monkeypatch, caplog):
    runner = BorgRunner(BorgConfig(retention_policy={'mode':'all'}))
    steps=[]
    monkeypatch.setattr(runner,'prune',lambda *_: pytest.fail('Prune must not run'))
    monkeypatch.setattr(runner,'compact',lambda: steps.append('compact') or 0)
    monkeypatch.setattr(runner,'check',lambda: steps.append('check') or 0)
    with caplog.at_level('INFO'): assert runner.maintenance('job-backup') == 0
    assert steps == ['compact','check']
    assert 'Keep all archives; prune disabled' in caplog.text


def test_manual_prune_uses_same_policy_and_remains_job_scoped(tmp_path):
    config,_=_canonical_source(tmp_path)
    path=tmp_path/'config/jobs'/f'{job_id("appdata_local")}.json'
    job=json.loads(path.read_text());job['retention']={'mode':'last','last':'3'};path.write_text(json.dumps(job))
    command=CheckManager()._repository_command(config, {'repository_key':'repo_appdata'},'/test/repo','prune','quick')
    assert command[command.index('--keep-last')+1]=='3'
    assert '--keep-daily' not in command
    assert command[command.index('--glob-archives')+1] == job['archive_prefix']+'-*'
    job['retention']={'mode':'all'};path.write_text(json.dumps(job))
    with pytest.raises(RetentionError, match='disabled'):
        CheckManager()._repository_command(config, {'repository_key':'repo_appdata'},'/test/repo','prune','quick')


def test_marker_names_are_optional_case_sensitive_and_validated():
    assert marker_names() == []
    assert marker_names(['.nobackup','.NOBACKUP','.nobackup']) == ['.nobackup','.NOBACKUP']
    for bad in ([''],['..'],['../tag'],['/tag'],['a\n'],['x\0'],['a'*256],['x']*33,'a'):
        with pytest.raises(ExclusionError): marker_names(bad)


def test_file_copy_preserves_bytes_and_has_explicit_lifecycle(tmp_path):
    key=job_id('test');original=b'# Umlaut: \xc3\xa4\r\nfm:*.tmp\r\n'
    first=prepare_file(upload(original),tmp_path,key)
    assert read_file(first,tmp_path,key)==original
    assert 'content_b64' not in first
    second=prepare_file(upload(b'pp:other\n'),tmp_path,key)
    (tmp_path/f'{key}.json').write_text(json.dumps({'exclude_from':second}))
    cleanup_files(tmp_path,key)
    assert not (tmp_path/'exclusions'/key/f'{first["sha256"]}.txt').exists()
    assert read_file(second,tmp_path,key)==b'pp:other\n'
    (tmp_path/f'{key}.json').unlink();cleanup_files(tmp_path,key)
    assert not (tmp_path/'exclusions'/key).exists()


@pytest.mark.parametrize('data', [b'',b'\0',b'\xff',b'a'*65537,b'a'*4097,b'\xef\xbb\xbffm:*.tmp',b're:[',b'a\x0bb'])
def test_bad_uploads_rejected_without_files(tmp_path,data):
    with pytest.raises(ExclusionError): prepare_file(upload(data),tmp_path,job_id('test'))
    assert list(tmp_path.iterdir())==[]


def test_file_reference_cannot_escape_job_and_detects_corruption(tmp_path):
    key=job_id('test');saved=prepare_file(upload(),tmp_path,key)
    with pytest.raises(ExclusionError): read_file(saved,tmp_path,job_id('different'))
    with pytest.raises(ExclusionError): read_file({**saved,'managed_file':'../../secret'},tmp_path,key)
    path=tmp_path/'exclusions'/saved['managed_file'];path.write_bytes(b'corrupt')
    with pytest.raises(ExclusionError): read_file(saved,tmp_path,key)
    path.unlink();path.symlink_to(tmp_path/'other')
    with pytest.raises(ExclusionError): read_file(saved,tmp_path,key)


def test_export_import_roundtrip_includes_exact_file_and_rejects_bad_digest(tmp_path):
    config,_=_canonical_source(tmp_path/'source')
    jobs=tmp_path/'source/config/jobs';key=job_id('appdata_local');path=jobs/f'{key}.json'
    job=json.loads(path.read_text());job['retention']={'mode':'all'};job['exclude_if_present']=['.nobackup']
    job['exclude_from']=prepare_file(upload(),jobs,key);path.write_text(json.dumps(job))
    bundle=export_jobs_bundle(config)['bundle'];assert bundle['format']=='bbui-job-bundle-v4'
    target={'BACKUP_SCRIPTS_DIR':str(tmp_path/'target')}
    import_jobs_bundle(target,bundle,dry_run=False,settings_mode='ignore')
    target_jobs=tmp_path/'target/config/jobs';copy=json.loads((target_jobs/f'{key}.json').read_text())
    assert copy['retention']['mode']=='all'
    assert copy['exclude_if_present']==['.nobackup']
    assert read_file(copy['exclude_from'],target_jobs,key)==upload_bytes(upload())[0]
    bundle['jobs'][0]['exclude_from']['sha256']='0'*64
    before=(target_jobs/f'{key}.json').read_bytes()
    with pytest.raises(ConfigurationExportError): import_jobs_bundle(target,bundle,dry_run=False)
    assert (target_jobs/f'{key}.json').read_bytes()==before


def test_real_borg_exclusions_and_last_three_leave_other_job_untouched(tmp_path,monkeypatch):
    borg=shutil.which('borg')
    if not borg: pytest.skip('Borg binary unavailable')
    # Runner tests populate process-wide Borg settings; isolate this real repository.
    env={key:value for key,value in os.environ.items() if not key.startswith('BORG_')}
    env.update(BORG_BASE_DIR=str(tmp_path/'borg-home'), BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK='yes')
    def run(*args):
        result=subprocess.run([borg,*args],env=env,cwd=tmp_path,text=True,capture_output=True,timeout=30)
        assert result.returncode==0,result.stderr
        return result
    repo=tmp_path/'repo';source=tmp_path/'source';source.mkdir()
    for name in ('tagged','upper','ordinary','explicit'):
        (source/name).mkdir();(source/name/'keep.txt').write_text('data')
    (source/'tagged/.nobackup').touch();(source/'upper/.NOBACKUP').touch()
    (source/'ordinary/file.tmp').write_text('excluded');patterns=tmp_path/'exclude.txt';patterns.write_bytes(b'fm:*.tmp\n')
    run('init','--encryption=none',str(repo))
    common=['--exclude-if-present','.nobackup','--exclude-from',str(patterns),'--exclude','pp:source/explicit']
    for n in range(5): run('create','--timestamp',f'2026-09-10T12:00:0{n}',*common,f'{repo}::job-{n}','source')
    run('create',f'{repo}::another-job','source')
    listing=run('list','--short',f'{repo}::job-0').stdout
    assert 'source/ordinary/keep.txt' in listing and 'source/upper/keep.txt' in listing
    assert 'tagged' not in listing and 'file.tmp' not in listing and 'explicit' not in listing
    dry=run('prune','--dry-run','--list','--glob-archives','job-*','--keep-last','3',str(repo))
    assert 'job-0' in dry.stderr+dry.stdout
    run('prune','--glob-archives','job-*','--keep-last','3',str(repo))
    assert set(run('list','--short',str(repo)).stdout.splitlines())=={'job-2','job-3','job-4','another-job'}
    # A backup gap longer than the window must still leave the explicit daily point.
    for n in range(2): run('create','--timestamp',f'2000-01-01T12:00:0{n}',f'{repo}::gap-{n}','source')
    policy={'mode':'tiered','within':'7d','daily':'1','weekly':'0','monthly':'0','yearly':'0'}
    run('prune','--glob-archives','gap-*',*prune_arguments(policy),str(repo))
    assert set(run('list','--short',str(repo)).stdout.splitlines())=={'job-2','job-3','job-4','another-job','gap-1'}


def test_within_only_is_blocked_for_save_automatic_and_manual_prune(tmp_path, monkeypatch, caplog):
    values={period:'0' for period in ('hourly','daily','weekly','monthly','yearly')}
    policy={'mode':'tiered','within':'7d',**values}
    with pytest.raises(RetentionError) as error:
        normalize_retention(policy)
    assert error.value.api_code=='retention_within_only'
    with pytest.raises(ValueError) as error:
        _retention_from_params({'retention_mode':'tiered','keep_within':'7d',**{f'keep_{k}':v for k,v in values.items()}})
    assert error.value.api_code=='retention_within_only'
    monkeypatch.setattr('runtime.lib.borg_runner._run_borg', lambda *_: pytest.fail('Unsafe prune must not start'))
    assert BorgRunner(BorgConfig(retention_policy=policy)).prune('appdata-backup')==2
    assert 'backup gap' in caplog.text
    config,_=_canonical_source(tmp_path/'source')
    path=tmp_path/'source/config/jobs'/f'{job_id("appdata_local")}.json'
    job=json.loads(path.read_text());job['retention']=policy;path.write_text(json.dumps(job))
    with pytest.raises(RetentionError) as error:
        CheckManager()._repository_command(config, {'repository_key':'repo_appdata'},'/test/repo','prune','quick')
    assert error.value.api_code=='retention_within_only'
    # No implicit rule is added; an explicit positive count makes the policy valid.
    assert policy['daily']=='0'
    assert '--keep-within' in prune_arguments({**policy,'daily':'1'})


def test_wizard_validates_whole_policy_and_explains_selected_mode():
    node=shutil.which('node')
    if not node: pytest.skip('Node unavailable')
    script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
for(const lang of ['de','en']){
 const labels=JSON.parse(fs.readFileSync('ui/i18n/'+lang+'.json'));
 const fields={};const context={window:{addEventListener(){},BBUI:{components:{i18n:{t:(key,p={})=>key.split('.').reduce((v,k)=>v[k],labels).replace(/\{(\w+)\}/g,(_,k)=>p[k]??'')}}}},document:{getElementById:id=>fields[id]||null},escHtml:s=>s};
 vm.createContext(context);vm.runInContext(fs.readFileSync('ui/js/pages/wizard.js','utf8'),context);
 const zero={keep_hourly:'0',keep_daily:'0',keep_weekly:'0',keep_monthly:'0',keep_yearly:'0',keep_within:'7d'};
 assert.equal(context._wizardRetentionValidationKey(zero),'wizard.validationRetentionWithinOnly');
 assert.equal(context._wizardRetentionValidationKey({...zero,keep_daily:'1'}),'');
 assert.equal(context._wizardRetentionValidationKey({...zero,retention_mode:'last',keep_last:'3'}),'');
 assert.equal(context._wizardRetentionValidationKey({...zero,retention_mode:'all'}),'');
 assert.equal(context._wizardRetentionValidationKey({...zero,retention_mode:'last',keep_last:'0'}),'wizard.validationRetentionInvalid');
 for(const [key,value] of Object.entries(zero)) fields['wiz-'+key.replaceAll('_','-')]={value};
 fields['wiz-keep-within-count']={value:'7'};fields['wiz-keep-within-unit']={value:'d'};
 fields['wiz-retention-mode']={value:'tiered'};
 let help=context.wizardPolicyHelpContent('retention');
 assert.equal(help.sections[0].warning,true);
 assert.equal(help.sections[0].text,labels.wizard.validationRetentionWithinOnly);
 fields['wiz-keep-daily']={value:'1'};
 assert.equal(context.wizardPolicyHelpContent('retention').sections[0].warning,false);
 fields['wiz-retention-mode'].value='last';fields['wiz-keep-last']={value:'3'};
 help=context.wizardPolicyHelpContent('retention');assert.equal(help.title,labels.wizard.policyHelp.lastTitle);
 assert(help.sections.some(s=>s.text.includes('97')));
 assert(context.wizardPolicyHelpContent('within').sections.some(s=>s.text.includes('24')));
 fields['wiz-retention-mode'].value='all';help=context.wizardPolicyHelpContent('retention');
 assert.equal(help.title,labels.wizard.policyHelp.allTitle);
 for(const topic of ['markers','file']) assert.equal(context.wizardPolicyHelpContent(topic).retention,false);
}
'''
    result=subprocess.run([node,'-e',script],cwd=ROOT,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
