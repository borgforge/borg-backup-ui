"""Offline upstream/schema and idempotent issue coverage for the Python monitor."""
from datetime import date
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
import python_monitor as monitor


def inputs():
    lock = {'version': '3.13.1', 'build': '20260101', 'components': {'openssl-3.5': {'version': '3.5.1'}}}
    pep = {'metadata': {'3.13': {'end_of_life': '2029-10-31'}},
           'releases': {'3.13': [{'stage': '3.13.1', 'state': 'actual', 'date': '2026-01-01'}]}}
    release = {'tag_name': '20260101', 'draft': False, 'prerelease': False, 'assets': [
        {'name': 'cpython-3.13.1+20260101-x86_64-unknown-linux-gnu-pgo+lto-full.tar.zst'},
        {'name': 'cpython-3.13.1+20260101-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz'}]}
    return lock, pep, release


def test_unchanged_versions_produce_no_release_issue():
    assert monitor.release_findings(*inputs(), date(2026, 1, 5)) == []


def test_patch_security_and_new_series_are_separate_reviews():
    lock, pep, release = inputs()
    pep['releases']['3.13'].append({'stage': '3.13.2', 'state': 'actual', 'date': '2026-01-02'})
    pep['releases']['3.14'] = [{'stage': '3.14.0 final', 'state': 'actual', 'date': '2026-01-02'}]
    pep['releases']['3.15'] = [{'stage': '3.15.0', 'state': 'expected', 'date': '2026-01-02'},
                             {'stage': '3.15.0 alpha 1', 'state': 'actual', 'date': '2026-01-02'}]
    keys = {f['key'] for f in monitor.release_findings(lock, pep, release, date(2026, 1, 5))}
    assert keys == {'release:patch-3.13.2', 'release:series-3.14'}


def test_same_python_version_new_supplier_build_requires_review():
    lock, pep, release = inputs()
    release['tag_name'] = '20260102'
    for asset in release['assets']:
        asset['name'] = asset['name'].replace('20260101', '20260102')
    found = monitor.release_findings(lock, pep, release, date(2026, 1, 5))
    assert [f['key'] for f in found] == ['release:build-3.13.1-20260102']


@pytest.mark.parametrize('today, threshold', [('2029-06-01', 180), ('2029-09-01', 90), ('2029-11-01', 0)])
def test_support_lifecycle_escalations(today, threshold):
    found = monitor.release_findings(*inputs(), date.fromisoformat(today))
    assert found[0]['key'] == f'release:eol-3.13-{threshold}'


def nvd(*, vulnerable=True, version='*', end='3.5.2'):
    return {'startIndex': 0, 'totalResults': 1, 'vulnerabilities': [{'cve': {
        'id': 'CVE-2026-12345', 'vulnStatus': 'Analyzed', 'lastModified': '2026-01-03',
        'configurations': [{'nodes': [{'cpeMatch': [{'vulnerable': vulnerable,
            'criteria': f'cpe:2.3:a:openssl:openssl:{version}:*:*:*:*:*:*:*', 'versionEndExcluding': end}]}]}],
    }}]}


@pytest.mark.parametrize('vulnerable, end, expected', [(True, '3.5.2', 1), (False, '3.5.2', 0), (True, '3.5.1', 0)])
def test_native_security_range_and_context_filter(vulnerable, end, expected):
    lock, _, _ = inputs()
    found = monitor.security_findings(lock, request=lambda url: nvd(vulnerable=vulnerable, end=end), pause=lambda _: None)
    assert len(found) == expected
    if found:
        assert found[0]['key'] == 'security:CVE-2026-12345'
        assert 'openssl-3.5 3.5.1' in found[0]['text']


def test_no_change_dedup_preserves_notes_and_respects_deferral():
    lock, _, _ = inputs()
    found = monitor.security_findings(lock, request=lambda url: nvd(), pause=lambda _: None)
    plan = monitor.monitor.plan_updates
    actions, _ = plan(found, [], namespace='python', checklist=monitor.CHECKLIST)
    issue = {'number': 12, 'user': {'login': 'borg-codex-bot'}, 'state': 'open', 'state_reason': None,
             'labels': [], 'body': actions[0]['payload']['body'] + '\nMaintainer notes'}
    assert plan(found, [issue], namespace='python')[0] == []
    found[0]['text'] += '\nUpdated security facts.'
    updated, _ = plan(found, [issue], namespace='python')
    assert updated[0]['payload']['body'].endswith('Maintainer notes')
    issue['labels'] = [{'name': 'status::waiting'}]
    assert plan(found, [issue], namespace='python') == ([], 1)
    # Apprise ignores Python blocks, and Python ignores Apprise blocks.
    assert plan([], [issue]) == ([], 0)


@pytest.mark.parametrize('data', [{}, {'startIndex': 0, 'totalResults': 1, 'vulnerabilities': []},
                                  {'startIndex': 1, 'totalResults': 0, 'vulnerabilities': []}])
def test_incomplete_security_data_fails(data):
    with pytest.raises((ValueError, KeyError)):
        monitor.security_findings(inputs()[0], request=lambda _: data, pause=lambda _: None)


def test_source_failure_never_becomes_empty_success():
    def fail(_):
        raise OSError('offline')
    with pytest.raises(OSError):
        monitor.security_findings(inputs()[0], request=fail, pause=lambda _: None)


def test_unknown_native_library_requires_coverage():
    lock, _, _ = inputs()
    lock['components']['unknown'] = {'version': '1.0'}
    with pytest.raises(KeyError):
        monitor.security_findings(lock, request=lambda _: {'startIndex': 0, 'totalResults': 0, 'vulnerabilities': []}, pause=lambda _: None)


def test_missing_supplier_platform_fails():
    lock, pep, release = inputs()
    release['assets'] = []
    with pytest.raises(ValueError, match='lacks'):
        monitor.release_findings(lock, pep, release, date(2026, 1, 5))


def test_missing_supplier_stripped_binary_fails():
    lock, pep, release = inputs()
    release['assets'].pop()
    with pytest.raises(ValueError, match='stripped'):
        monitor.release_findings(lock, pep, release, date(2026, 1, 5))


def test_python_workflow_requires_its_own_main_identity(monkeypatch):
    monkeypatch.setattr(monitor.monitor.security, 'guard_public', lambda _: None)
    for key, value in {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': monitor.monitor.REPO,
                       'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                       'BBUI_ENVIRONMENT': 'dependency-monitor',
                       'GITHUB_WORKFLOW_REF': f'{monitor.monitor.REPO}/.github/workflows/apprise-monitor.yml@refs/heads/main'}.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match='protected'):
        monitor.monitor.require_main_job('python-monitor.yml')


def test_windows_only_context_is_not_a_linux_finding():
    data = nvd()
    config = data['vulnerabilities'][0]['cve']['configurations'][0]
    config['operator'] = 'AND'
    config['nodes'].append({'operator': 'OR', 'negate': False, 'cpeMatch': [
        {'vulnerable': False, 'criteria': 'cpe:2.3:o:microsoft:windows:-:*:*:*:*:*:*:*'}]})
    assert monitor.security_findings(inputs()[0], request=lambda _: data, pause=lambda _: None) == []
    config['operator'] = 'OR'
    assert len(monitor.security_findings(inputs()[0], request=lambda _: data, pause=lambda _: None)) == 1


def test_shipped_runtime_remains_monitored_before_new_source_release(tmp_path, monkeypatch):
    import io
    import tarfile
    source = {'version': '3.13.2', 'build': '20260202', 'components': {'cpython': {'version': '3.13.2'}}, 'sha256': 'new'}
    shipped = {**source, 'version': '3.13.1', 'build': '20260101', 'sha256': 'old'}
    runtime = tmp_path / 'runtime/python'
    runtime.mkdir(parents=True)
    (runtime / 'runtime.lock.json').write_text(json.dumps(source))
    (tmp_path / 'borg-backup-ui.plg').write_text('<!ENTITY version "2026.01.01.1200">')
    packages = tmp_path / 'releases'
    packages.mkdir()
    package = packages / 'borg-backup-ui-2026.01.01.1200.txz'
    content = json.dumps(shipped).encode()
    with tarfile.open(package, 'w:xz') as archive:
        member = tarfile.TarInfo('boot/config/plugins/borg-backup-ui/runtime/python/python-runtime.json')
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    monkeypatch.setattr(monitor.release, 'package_provenance', lambda _: {'python_runtime_lock_sha256': 'verified'})
    baseline = monitor.baselines(tmp_path)
    assert [entry['version'] for _, entry in baseline] == ['3.13.1', '3.13.2']
    assert baseline[0][0].startswith('published stable')
    (runtime / 'runtime.lock.json').write_text(json.dumps(shipped))
    assert len(monitor.baselines(tmp_path)) == 1
    monkeypatch.setattr(monitor.release, 'package_provenance', lambda _: {})
    assert 'stable has no private runtime yet' in monitor.baselines(tmp_path)[0][0]


def test_one_cve_across_two_baselines_becomes_one_issue():
    item = monitor.finding('security:CVE-2026-12345', 'Review CVE', 'Affected', security=True)
    found = monitor.merge_findings([('stable', [item]), ('planned', [item])])
    assert len(found) == 1
    assert 'Scope: stable' in found[0]['text'] and 'Scope: planned' in found[0]['text']
    actions, _ = monitor.monitor.plan_updates(found, [], namespace='python')
    assert len(actions) == 1


def test_keyword_security_candidates_are_not_silently_discarded():
    lock = {'version': '3.13.1', 'build': '20260101', 'components': {'mpdecimal': {'version': '4.0.0'}}}
    data = nvd()
    data['vulnerabilities'][0]['cve'].pop('configurations')
    data['vulnerabilities'][0]['cve']['descriptions'] = [{'lang': 'en', 'value': 'A vulnerability in mpdecimal.'}]
    urls = []
    def request(url):
        urls.append(url)
        return data
    found = monitor.security_findings(lock, request=request, pause=lambda _: None)
    assert len(found) == 1 and 'keywordSearch=mpdecimal' in urls[0]


@pytest.mark.parametrize('description, expected', [
    ('editorconfig-core-c affects libeditorconfig.', False),
    ('A libedit vulnerability.', True), ('The editline library is affected.', True)])
def test_libedit_keyword_does_not_match_editorconfig(description, expected):
    cve = {'descriptions': [{'lang': 'en', 'value': description}]}
    assert monitor.keyword_mentions_component(cve, 'libedit') is expected


def test_unanalysed_versioned_hit_requires_triage():
    data = nvd()
    cve = data['vulnerabilities'][0]['cve']
    cve.pop('configurations')
    cve['vulnStatus'] = 'Awaiting Analysis'
    found = monitor.security_findings(inputs()[0], request=lambda _: data, pause=lambda _: None)
    assert len(found) == 1
    assert 'Classification: potential' in found[0]['text']


@pytest.mark.parametrize('platform', ['windows', 'mac_os', 'android'])
def test_target_platform_in_application_cpe_is_respected(platform):
    data = nvd()
    match = data['vulnerabilities'][0]['cve']['configurations'][0]['nodes'][0]['cpeMatch'][0]
    fields = match['criteria'].split(':')
    fields[10] = platform
    match['criteria'] = ':'.join(fields)
    assert monitor.security_findings(inputs()[0], request=lambda _: data, pause=lambda _: None) == []


def test_nested_and_or_platform_conditions():
    data = nvd()
    config = data['vulnerabilities'][0]['cve']['configurations'][0]
    windows = {'vulnerable': False, 'criteria': 'cpe:2.3:o:microsoft:windows:-:*:*:*:*:*:*:*'}
    linux = {'vulnerable': False, 'criteria': 'cpe:2.3:o:linux:linux_kernel:*:*:*:*:*:*:*:*'}
    nested = {'operator': 'OR', 'cpeMatch': [windows]}
    config['nodes'] = [{'operator': 'AND', 'nodes': [*config['nodes'], nested]}]
    scan = lambda: monitor.security_findings(inputs()[0], request=lambda _: data, pause=lambda _: None)
    assert scan() == []
    nested['cpeMatch'].append(linux)
    assert len(scan()) == 1
    nested['operator'] = 'AND'
    assert scan() == []
    nested['negate'] = True
    assert len(scan()) == 1  # Unknown negation must not suppress a candidate.


@pytest.mark.parametrize('bound,current,expected', [
    ('versionStartIncluding', '3.5.2', True), ('versionStartExcluding', '3.5.2', False),
    ('versionEndIncluding', '3.5.2', True), ('versionEndExcluding', '3.5.2', False)])
def test_inclusive_and_exclusive_range_boundaries(bound, current, expected):
    match = {'vulnerable': True, 'criteria': 'cpe:2.3:a:openssl:openssl:*:*:*:*:*:*:*:*', bound: '3.5.2'}
    assert monitor.relevant_match(match, 'openssl:openssl', current) is expected


@pytest.mark.parametrize('damage', ['overflow', 'changed_total', 'duplicate'])
def test_inconsistent_pagination_never_reports_success(damage):
    first = nvd()
    second = nvd()
    if damage == 'overflow':
        first['totalResults'] = 0
    else:
        first['totalResults'] = 2
        second.update(startIndex=1, totalResults=3 if damage == 'changed_total' else 2)
    pages = iter([first, second])
    with pytest.raises(ValueError, match='NVD'):
        monitor.security_findings(inputs()[0], request=lambda _: next(pages), pause=lambda _: None)


def test_reordered_advisory_facts_do_not_reopen_reviewed_issue():
    data = nvd()
    cve = data['vulnerabilities'][0]['cve']
    cve['references'] = [{'url': 'https://example.test/a'}, {'url': 'https://example.test/b'}]
    scan = lambda: monitor.security_findings(inputs()[0], request=lambda _: data, pause=lambda _: None)
    first = scan()
    cve['references'].reverse()
    assert scan() == first
    cve['references'].append({'url': 'https://example.test/new-fix'})
    assert scan() != first


def test_disappeared_finding_does_not_auto_close_or_claim_fix():
    found = monitor.security_findings(inputs()[0], request=lambda _: nvd(), pause=lambda _: None)
    action = monitor.monitor.plan_updates(found, [], namespace='python')[0][0]
    issue = {'number': 12, 'user': {'login': 'borg-codex-bot'}, 'state': 'open',
             'state_reason': None, 'labels': [], 'body': action['payload']['body']}
    assert monitor.monitor.plan_updates([], [issue], namespace='python') == ([], 0)
