"""Custom runtime integrity, remediation scopes and upstream regression guards (#732)."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
import python_runtime as runtime
import python_source_build as source_build
import python_monitor as monitor
import python_fix_monitor as fixes
from test_python_fix_monitor import fixtures, issue, release_inputs


def sha(content):
    return hashlib.sha256(content).hexdigest()


def custom_input(tmp_path):
    """Create a small locked source-build archive with recipe and receipt evidence."""
    folder = tmp_path / 'runtime/python'
    (folder / 'inputs').mkdir(parents=True)
    recipe = b'{"schema":1}\n'
    (folder / 'source-build.lock.json').write_bytes(recipe)
    receipt = json.dumps({'id':'fixture-r1', 'recipe_sha256':sha(recipe),
                          'python_version':'3.13.18', 'target':'x86_64-unknown-linux-gnu'}).encode()
    payload = {'python/source-build.json': receipt,
               'python/supplier-downloads.json': b'{}', 'python/SUPPLIER-LICENSE.txt': b'license'}
    archive = folder / 'inputs/runtime.tar.xz'
    with tarfile.open(archive, 'w:xz') as output:
        for name, data in payload.items():
            member = tarfile.TarInfo(name); member.size = len(data)
            output.addfile(member, io.BytesIO(data))
    lock = {'version':'3.13.18', 'target':'x86_64-unknown-linux-gnu', 'sha256':runtime.sha256(archive),
            'downloads_sha256':sha(b'{}'), 'supplier_license_sha256':sha(b'license'),
            'custom_build':{'id':'fixture-r1', 'artifact':'inputs/runtime.tar.xz',
                            'recipe_sha256':sha(recipe), 'receipt_sha256':sha(receipt)}}
    return folder, lock


def test_custom_input_verifies_recipe_archive_receipt_and_sources(tmp_path):
    _, lock = custom_input(tmp_path)
    inventory, license_path = runtime.custom_inputs(lock, tmp_path, tmp_path / 'unpacked')
    assert inventory.read_bytes() == b'{}'
    assert license_path.read_bytes() == b'license'


@pytest.mark.parametrize('damage', ['archive','recipe','receipt','inventory','license','identity','path'])
def test_custom_input_rejects_changed_evidence(tmp_path, damage):
    folder, lock = custom_input(tmp_path)
    if damage == 'archive':
        (folder / 'inputs/runtime.tar.xz').write_bytes(b'wrong')
    elif damage == 'recipe':
        (folder / 'source-build.lock.json').write_bytes(b'changed')
    elif damage == 'receipt':
        lock['custom_build']['receipt_sha256'] = '0' * 64
    elif damage == 'inventory':
        lock['downloads_sha256'] = '0' * 64
    elif damage == 'license':
        lock['supplier_license_sha256'] = '0' * 64
    elif damage == 'identity':
        lock['custom_build']['id'] = 'another-build'
    else:
        lock['custom_build']['artifact'] = '../outside.tar.xz'
    with pytest.raises(ValueError):
        runtime.custom_inputs(lock, tmp_path, tmp_path / 'unpacked')


@pytest.mark.parametrize('version', ['3.53.1', '', 'unknown', None])
def test_builder_rejects_security_floor_regressions(version):
    lock = {'minimum_component_versions': {'sqlite':'3.54.1'}}
    with pytest.raises(ValueError):
        runtime.validate_component_floors(lock, {'sqlite':{'version':version}})
    runtime.validate_component_floors(lock, {'sqlite':{'version':'3.54.1'}})
    runtime.validate_component_floors(lock, {'sqlite':{'version':'3.55.0'}})


def test_source_build_work_cannot_escape_repository(tmp_path, monkeypatch):
    monkeypatch.setattr(source_build, 'recipe', lambda _: ({}, 'a' * 64))
    with pytest.raises(ValueError, match='inside repository'):
        source_build.prepare(tmp_path / 'outside', tmp_path / 'repo')


def test_runtime_identity_distinguishes_custom_from_upstream():
    lock, _, _ = fixtures()
    assert monitor.runtime_identity(lock) == '3.13.1+20260101'
    lock['custom_build'] = {'id':'bbui-sqlite-r1'}
    assert monitor.runtime_identity(lock) == '3.13.1+20260101 / bbui-sqlite-r1'
    lock['custom_build']['id'] = 'bad\n@someone'
    with pytest.raises(ValueError):
        monitor.runtime_identity(lock)


def test_fixed_planned_scope_does_not_hide_affected_stable():
    old, fixed, cve = fixtures()
    fixed['custom_build'] = {'id':'bbui-sqlite-r1'}
    detected = monitor.finding('security:'+cve['id'], 'CVE', 'Still affected stable', security=True)
    scoped = [('published stable', [detected]), ('planned source', [])]
    merged = monitor.merge_findings(scoped)
    monitor.annotate_remediation(merged, scoped, [('published stable',old),('planned source',fixed)],
                                 [{'vulnerabilities':[{'cve':cve}]}])
    assert len(merged) == 1
    assert 'Still affected stable' in merged[0]['text']
    assert 'Fix present by explicit advisory version bounds: sqlite 3.54.0' in merged[0]['text']
    assert 'bbui-sqlite-r1' in merged[0]['text']
    actions, _ = monitor.monitor.plan_updates(merged, [issue()], namespace='python')
    assert actions[0]['method'] == 'PATCH' and 'state' not in actions[0]['payload']


def test_absent_scan_result_does_not_claim_a_fix():
    old, _, cve = fixtures()
    detected = monitor.finding('security:'+cve['id'], 'CVE', 'Affected', security=True)
    scoped = [('stable',[detected]),('planned',[])]
    merged = monitor.merge_findings(scoped)
    monitor.annotate_remediation(merged, scoped, [('stable',old),('planned',old)],
                                 [{'vulnerabilities':[{'cve':cve}]}])
    assert 'Fix present' not in merged[0]['text']


def test_floor_combination_and_unknown_replacement_versions():
    old, candidate, _ = fixtures()
    old['minimum_component_versions'] = {'sqlite':'3.54.0'}
    new = {**old,'minimum_component_versions':{'sqlite':'3.54.1'}}
    floors = fixes.required_floors([('stable',old),('planned',new)])
    assert floors == {'sqlite':'3.54.1'}
    assert fixes.replacement_regressions(candidate,floors)
    candidate['components']['sqlite']['version']='3.54.1'
    assert fixes.replacement_regressions(candidate,floors) == []
    candidate['components']['sqlite']['version']='unknown'
    assert fixes.replacement_regressions(candidate,floors)


def test_new_supplier_build_issue_explains_custom_regression():
    old, candidate, supplier, pep, _ = release_inputs()
    old['minimum_component_versions']={'sqlite':'3.54.1'}
    candidate['components']['sqlite']['version']='3.53.1'
    reviews=fixes.review_replacements([('planned',old)],supplier,pep,monitor,lambda *args:candidate)
    text=next(iter(reviews.values()))
    assert 'Replacement blocked' in text and 'candidate 3.53.1, required >= 3.54.1' in text


def test_supplier_cannot_notify_fix_while_regressing_planned_floor():
    old, candidate, supplier, pep, response = release_inputs()
    planned=deepcopy(old)
    planned['components']['sqlite']['version']='3.54.1'
    planned['minimum_component_versions']={'sqlite':'3.54.1'}
    candidate['components']['sqlite']['version']='3.54.0'
    def unexpected(_):
        pytest.fail('Regressive candidate must be rejected before fix notification lookup')
    assert fixes.discover([('stable',old),('planned',planned)],supplier,pep,[issue()],unexpected,
                          monitor,lambda *args:candidate)==[]


def test_native_absence_requires_verified_facts_and_does_not_hide_findings():
    _, _, cve = fixtures()
    cve['id']='CVE-2026-119586'
    lock={'version':'3.13.18','build':'20261110','components':{'sqlite':{'version':'3.53.1'}},
          'native_facts':{'sqlite_cli':False}}
    response={'startIndex':0,'totalResults':1,'vulnerabilities':[{'cve':{**cve,'lastModified':'2026-11-01'}}]}
    found=monitor.security_findings(lock,request=lambda _:response,pause=lambda _:None)
    assert len(found)==1 and found[0]['applicability']=='not_applicable'
    assert 'Native SQLite CLI is absent' in found[0]['text']
    lock.pop('native_facts')
    assert monitor.security_findings(lock,request=lambda _:response,pause=lambda _:None)[0]['applicability']=='potential'


def test_manually_closed_native_issue_stays_closed_until_prerequisites_change():
    closed=issue(717,'CVE-2026-119586');closed['state']='closed';closed['state_reason']='completed'
    finding=monitor.finding('security:CVE-2026-119586','CVE','Updated build facts',security=True)
    finding['applicability']='not_applicable'
    actions,_=monitor.monitor.plan_updates([finding],[closed],namespace='python')
    assert actions[0]['payload']['state']=='open'
    monitor.preserve_native_triage(actions,[finding],[closed])
    assert 'state' not in actions[0]['payload'] and 'Updated build facts' in actions[0]['payload']['body']
    finding['applicability']='potential'
    actions,_=monitor.monitor.plan_updates([finding],[closed],namespace='python')
    monitor.preserve_native_triage(actions,[finding],[closed])
    assert actions[0]['payload']['state']=='open'


def test_one_applicable_baseline_prevents_native_issue_suppression():
    item=monitor.finding('security:CVE-2026-119586','CVE','CLI absent',security=True)
    item['applicability']='not_applicable'
    other={**item,'applicability':'potential','text':'CLI unknown'}
    assert monitor.merge_findings([('planned',[item]),('stable',[other])])[0]['applicability']=='potential'
    assert monitor.merge_findings([('stable',[other]),('planned',[item])])[0]['applicability']=='potential'


def test_prepare_allows_only_recorded_source_changes_and_rechecks_resume(tmp_path, monkeypatch):
    root=tmp_path/'repo';work=root/'.release-tmp/work';work.mkdir(parents=True)
    commit='a'*40; prefix='python-build-standalone-'+commit
    initial={'sqlite':{'version':'old','actual_version':'old','url':'old','sha256':'old','size':1}}
    original=json.dumps(initial,indent=4).encode()+b'\n'
    test=b'assert sqlite3.sqlite_version_info == (3, 53, 1)\n'
    changed=test.replace(b'(3, 53, 1)',b'(3, 54, 1)')
    sqlite_c=b'fixture amalgamation'
    sqlite=work/'sqlite-autoconf-3540100.tar.gz'
    with tarfile.open(sqlite,'w:gz') as tar:
        member=tarfile.TarInfo('sqlite-autoconf-3540100/sqlite3.c');member.size=len(sqlite_c)
        tar.addfile(member,io.BytesIO(sqlite_c))
    sql={'version':'3540100','actual_version':'3.54.1.0','url':'https://example.test/sqlite',
         'sha256':runtime.sha256(sqlite),'size':sqlite.stat().st_size,
         'sqlite3_c_sha3_256':hashlib.sha3_256(sqlite_c).hexdigest()}
    patched=deepcopy(initial);patched['sqlite'].update({k:sql[k] for k in ('version','actual_version','url','sha256','size')})
    archive=work/'supplier-source.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name,data in {'pythonbuild/downloads.json':original,'pythonbuild/disttests/__init__.py':test,
                          'build.py':b'unchanged build driver', 'targets.yml':b'bolt_capable: true\n'}.items():
            member=tarfile.TarInfo(prefix+'/'+name);member.size=len(data);tar.addfile(member,io.BytesIO(data))
    recipe={'supplier':'astral-sh/python-build-standalone','supplier_commit':commit,
            'source_archive_sha256':runtime.sha256(archive),'original_downloads_sha256':sha(original),
            'patched_downloads_sha256':sha((json.dumps(patched,indent=4)+'\n').encode()),'sqlite':sql,
            'build_patches':[{'path':'targets.yml','before_sha256':sha(b'bolt_capable: true\n'),
                              'after_sha256':sha(b'bolt_capable: false\n'),
                              'old':'bolt_capable: true','new':'bolt_capable: false'}],
            'test_expectation_patch':{'path':'pythonbuild/disttests/__init__.py','before_sha256':sha(test),
                                      'after_sha256':sha(changed),'old':'(3, 53, 1)','new':'(3, 54, 1)'}}
    monkeypatch.setattr(source_build,'recipe',lambda _: (recipe,'b'*64))
    source=source_build.prepare(work,root)
    assert (source/'pythonbuild/disttests/__init__.py').read_bytes()==changed
    assert (source/'targets.yml').read_text() == 'bolt_capable: false\n'
    assert source_build.prepare(work,root)==source
    (source/'build.py').write_text('unrecorded change')
    with pytest.raises(ValueError,match='Unrecorded supplier source change'):
        source_build.prepare(work,root)
