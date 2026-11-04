"""Offline upstream/schema and idempotent issue coverage for the Python monitor."""
from datetime import date
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
        {'name': 'cpython-3.13.1+20260101-x86_64-unknown-linux-gnu-pgo+lto-full.tar.zst'}]}
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
    release['assets'][0]['name'] = release['assets'][0]['name'].replace('20260101', '20260102')
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
