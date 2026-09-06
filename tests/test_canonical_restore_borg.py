"""Real Borg archive scope, extraction and UUID restore proof (#477)."""
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
for folder in (ROOT,ROOT/'api',ROOT/'runtime',ROOT/'runtime/lib'):
    sys.path.insert(0,str(folder))
from test_canonical_job_wizard import setup,create,edit
from test_restore_test_runner_profiles import _load_restore_runner
from restore_identity import capture_repository
from job_store import read_json
import restore_api
import restore_tests_api


def test_real_borg_prefix_union_frozen_extract_and_result_writer(setup,monkeypatch):
    cfg,_,_,root=setup
    binary=ROOT/'runtime/bin/borg/borg-linux-glibc231-x86_64-1.4.5'
    if not binary.is_file(): pytest.skip('Bundled Borg unavailable')
    bindir=root/'bin';bindir.mkdir();(bindir/'borg').symlink_to(binary)
    monkeypatch.setenv('PATH',str(bindir)+os.pathsep+os.environ['PATH'])
    for key in ['BORG_CACHE_DIR','BORG_SECURITY_DIR','BORG_KEYS_DIR']:
        monkeypatch.setenv(key,str(root/key.lower()))
    monkeypatch.setenv('BORG_UI_DATA_ROOT',str(root))
    cfg.update(STATUS_DIR=str(root/'status'),RESTORE_TEST_STATUS_DIR=str(root/'proof'),GLOBAL_LOG_DIR=str(root/'logs'),BORG_RESOURCE_LOCK_DIR=str(root/'locks'))
    result,_=create(setup,job_name='Original',archive_prefix='old');job_id=result['job_id']
    edit(setup,job_id,archive_prefix='new')
    restore_tests_api.update_restore_test_policy(cfg,job_id,{'mode':'scheduled','level':1,'interval_days':30})
    captured=capture_repository(cfg,job_id);repository=Path(captured['repo']);repository.parent.mkdir(parents=True,exist_ok=True)
    source=root/'source';(source/'payload.txt').write_text('Synthetic restore payload\n')
    def borg(*args):
        result=subprocess.run([str(binary),*args],cwd=source,capture_output=True,text=True,timeout=120)
        assert result.returncode==0,result.stderr
    borg('init','--encryption=none',str(repository))
    for index,prefix in enumerate(['new','old','foreign'],1):
        borg('create','--timestamp',f'2026-09-0{index}T00:00:00',f'{repository}::{prefix}-2026','payload.txt')
    archives=restore_api.list_archives(cfg,job_id)
    assert [a['name'] for a in archives]==['old-2026','new-2026']
    files=restore_api.list_files(cfg,job_id,'old-2026','')
    assert any(row['name']=='payload.txt' for row in files)
    target=root/'target';target.mkdir()
    monkeypatch.setattr(restore_api,'_get_restore_allowed_roots',lambda cfg:[target])
    precheck=restore_api.restore_precheck(cfg,job_id,'old-2026','payload.txt',str(target),'skip')
    assert precheck['ok'] and precheck['job_id']==job_id
    edit(setup,job_id,repository_key='repo_b',job_name='Moved')
    restored=restore_api.start_restore(cfg,job_id,'old-2026','payload.txt',str(target),'skip',_info=captured)
    assert Path(restored['destination_path']).read_text()=='Synthetic restore payload\n'
    runner=_load_restore_runner()
    monkeypatch.setattr(runner,'_refresh_unraid_dashboard_widget_cache',lambda *a:None)
    tester=runner.RestoreTest(cfg,SimpleNamespace(level=1,force=True,dry_run=False,scheduled=False,smb_auto_mount=False))
    repo={**captured,'path':captured['repo'],'type':'new','policy':{'mode':'scheduled','level':1,'interval_days':30}}
    try: assert tester.test_repo(repo)==0
    finally: tester.close()
    proof=read_json(root/'proof'/f'{job_id}.test')
    assert proof['tested_archive']=='old-2026' and proof['archive_prefix_snapshot']=='old'
    assert proof['job_name_snapshot']=='Original' and proof['repository_snapshot']==str(repository)
    plan=restore_tests_api.list_restore_test_plan(cfg)['jobs'][0]
    assert plan['verification_reason']=='target_changed'
    assert list((root/'locks').glob('*.lock.json'))==[]
