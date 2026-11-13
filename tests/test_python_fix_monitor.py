"""Positive fix evidence, persistent deduplication and protected mentions (#720)."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
import python_fix_monitor as fixes
import python_monitor as monitor


def fixtures():
    """Return compatible builds and an explicitly bounded, analysed SQLite CVE."""
    lock = {'version': '3.13.1', 'build': '20260101', 'target': 'x86_64-unknown-linux-gnu',
            'supplier': fixes.SUPPLIER, 'glibc_minimum': '2.17', 'excluded_extensions': [],
            'components': {'sqlite': {'version': '3.53.1'}}}
    candidate = {**lock, 'build': '20260102', 'components': {'sqlite': {'version': '3.54.0'}},
                 'evidence': {'archive_sha256': 'a' * 64, 'install_sha256': 'b' * 64,
                              'source_commit': 'c' * 40, 'downloads_sha256': 'd' * 64}}
    cve = {'id': 'CVE-2026-12345', 'vulnStatus': 'Analyzed',
           'descriptions': [{'lang': 'en', 'value': 'A SQLite vulnerability.'}],
           'configurations': [{'nodes': [{'operator': 'OR', 'cpeMatch': [
               {'vulnerable': True, 'criteria': 'cpe:2.3:a:sqlite:sqlite:*:*:*:*:*:*:*:*',
                'versionEndExcluding': '3.54.0'}]}]}]}
    return lock, candidate, cve


def issue(number=706, identifier='CVE-2026-12345'):
    """Build a bot-managed open CVE issue with preserved manual notes."""
    return {'number': number, 'user': {'login': 'borg-codex-bot'}, 'state': 'open',
            'state_reason': None, 'labels': [], 'body':
            f'<!-- bbui-python-monitor:security:{identifier}:start -->\nold facts\n'
            '<!-- bbui-python-monitor:end -->\nManual assessment stays.'}


def found(key='a' * 64, number=706):
    """Represent one positively correlated fix for notification tests."""
    lock, candidate, cve = fixtures()
    return {'key': key, 'cve': cve['id'], 'issue': number, 'candidate': candidate, 'scope': 'planned',
            'parts': fixes.fixed_components(cve, lock, candidate, monitor)}


def test_fix_requires_positive_affected_and_upper_bound_evidence():
    lock, candidate, cve = fixtures()
    result = fixes.fixed_components(cve, lock, candidate, monitor)
    assert result[0]['component'] == 'sqlite'
    assert result[0]['before'] == '3.53.1' and result[0]['after'] == '3.54.0'
    assert '3.54.0' in result[0]['bounds'][0]


@pytest.mark.parametrize('damage', ['unchanged', 'still_affected', 'older', 'missing', 'exact_only',
                                     'no_bound', 'unanalysed', 'rejected', 'no_config', 'negated',
                                     'malformed_version', 'keyword', 'windows', 'other_component'])
def test_ambiguous_or_unfixed_build_never_notifies(damage):
    lock, candidate, cve = fixtures()
    match = cve['configurations'][0]['nodes'][0]['cpeMatch'][0]
    if damage in ('unchanged', 'still_affected', 'older', 'malformed_version'):
        candidate['components']['sqlite']['version'] = {
            'unchanged': '3.53.1', 'still_affected': '3.53.2', 'older': '3.52.0',
            'malformed_version': 'not-a-version'}[damage]
    elif damage == 'missing':
        candidate['components'] = {}
    elif damage in ('exact_only', 'no_bound'):
        match.pop('versionEndExcluding')
        if damage == 'exact_only':
            match['criteria'] = match['criteria'].replace('sqlite:*:', 'sqlite:3.53.1:')
    elif damage in ('unanalysed', 'rejected'):
        cve['vulnStatus'] = 'Awaiting Analysis' if damage == 'unanalysed' else 'Rejected'
    elif damage == 'no_config':
        cve.pop('configurations')
    elif damage == 'negated':
        cve['configurations'][0]['negate'] = True
    elif damage == 'keyword':
        lock['components']['mpdecimal'] = {'version': '4.0.0'}
        cve['descriptions'][0]['value'] += ' mpdecimal is also affected.'
    elif damage == 'windows':
        cve['configurations'][0]['operator'] = 'AND'
        cve['configurations'][0]['nodes'].append({'cpeMatch': [{'vulnerable': False,
            'criteria': 'cpe:2.3:o:microsoft:windows:-:*:*:*:*:*:*:*'}]})
    elif damage == 'other_component':
        lock['components']['openssl-3.5'] = {'version': '3.5.1'}
        candidate['components']['openssl-3.5'] = {'version': '3.5.1'}
        cve['configurations'][0]['nodes'][0]['cpeMatch'].append({
            'vulnerable': True, 'criteria': 'cpe:2.3:a:openssl:openssl:*:*:*:*:*:*:*:*',
            'versionEndExcluding': '3.5.2'})
    assert fixes.fixed_components(cve, lock, candidate, monitor) == []


def test_inclusive_upper_bound_requires_strictly_later_version():
    lock, candidate, cve = fixtures()
    match = cve['configurations'][0]['nodes'][0]['cpeMatch'][0]
    match['versionEndIncluding'] = match.pop('versionEndExcluding')
    assert fixes.fixed_components(cve, lock, candidate, monitor) == []
    candidate['components']['sqlite']['version'] = '3.54.1'
    assert fixes.fixed_components(cve, lock, candidate, monitor)


def test_multiple_ranges_must_all_be_fixed():
    lock, candidate, cve = fixtures()
    newer = deepcopy(cve['configurations'][0])
    newer['nodes'][0]['cpeMatch'][0]['versionEndExcluding'] = '3.55.0'
    cve['configurations'].append(newer)
    assert fixes.fixed_components(cve, lock, candidate, monitor) == []


def release_inputs():
    lock, candidate, cve = fixtures()
    supplier = {'tag_name': candidate['build'], 'draft': False, 'prerelease': False, 'assets': [
        {'name': f'cpython-3.13.1+{candidate["build"]}-x86_64-unknown-linux-gnu{suffix}'}
        for suffix in ('-pgo+lto-full.tar.zst', '-install_only_stripped.tar.gz')]}
    pep = {'metadata': {'3.13': {'end_of_life': '2029-10-31'}},
           'releases': {'3.13': [{'stage': '3.13.1', 'state': 'actual', 'date': '2026-01-01'}]}}
    response = {'totalResults': 1, 'startIndex': 0, 'vulnerabilities': [{'cve': cve}]}
    return lock, candidate, supplier, pep, response


def test_discover_rebuilds_reuses_inventory_and_deduplicates_scopes():
    lock, candidate, supplier, pep, response = release_inputs()
    calls = []
    def inventory(*args):
        calls.append(args)
        return candidate
    result = fixes.discover([('stable', lock), ('planned', lock)], supplier, pep, [issue()],
                            lambda _: response, monitor, inventory)
    assert len(result) == 1 and len(calls) == 1
    original = result[0]['key']
    candidate['build'] = '20260103'
    candidate['components']['sqlite']['version'] = '3.55.0'
    assert fixes.discover([('planned', lock)], supplier, pep, [issue()], lambda _: response,
                          monitor, inventory)[0]['key'] == original


@pytest.mark.parametrize('state', ['closed', 'waiting', 'not_planned'])
def test_deferred_issues_do_not_trigger_candidate_reads(state):
    lock, _, supplier, pep, _ = release_inputs()
    item = issue()
    if state == 'waiting':
        item['labels'] = [{'name': 'status::waiting'}]
    elif state == 'not_planned':
        item['state_reason'] = state
    else:
        item['state'] = state
    def unexpected(*args):
        pytest.fail('Deferred issue triggered upstream read')
    assert fixes.discover([('planned', lock)], supplier, pep, [item], unexpected, monitor, unexpected) == []


def test_missing_cve_is_not_a_fix():
    lock, candidate, supplier, pep, _ = release_inputs()
    with pytest.raises(ValueError, match='Incomplete CVE'):
        fixes.discover([('planned', lock)], supplier, pep, [issue()],
                       lambda _: {'totalResults': 0, 'startIndex': 0, 'vulnerabilities': []},
                       monitor, lambda *args: candidate)


def test_notification_is_one_mention_and_repeat_is_silent():
    rows = [issue(), issue(707, 'CVE-2026-12346')]
    candidates = [found(), found('b' * 64, 707)]
    notice = fixes.notification(candidates, rows, lambda _: [])
    assert notice['count'] == 2 and notice['issue'] == 706
    assert notice['body'].count('@TheTwist76') == 1
    assert '#706' in notice['body'] and '#707' in notice['body']
    saved = {'body': notice['body'], 'user': {'login': 'borg-codex-bot'}}
    rows[0]['state'] = 'closed'  # Closing the comment's anchor must not lose dedup.
    history = lambda number: [saved] if number == 706 else []
    assert fixes.notification(candidates, rows, history) is None
    assert fixes.notification(candidates + [found('c' * 64, 707)], rows, history)['count'] == 1


def test_foreign_marker_cannot_suppress_notice():
    foreign = {'body': '<!-- bbui-python-fix:v1:' + 'a' * 64 + ' -->', 'user': {'login': 'stranger'}}
    assert fixes.notification([found()], [issue()], lambda _: [foreign])['count'] == 1


def test_history_failure_stops_notification():
    def failed(_):
        raise RuntimeError('history unavailable')
    with pytest.raises(RuntimeError):
        fixes.notification([found()], [issue()], failed)


def test_post_timeout_then_retry_does_not_duplicate(monkeypatch):
    ledger = []
    guards = []
    monkeypatch.setattr(fixes.shared, 'require_main_job', lambda name: guards.append(name))
    monkeypatch.setattr(fixes.shared.hosted, 'bot', lambda: guards.append('bot'))
    monkeypatch.setattr(fixes.shared, 'existing_issues', lambda: [issue()])
    monkeypatch.setattr(fixes.shared.evidence, 'api', lambda _: ledger)
    def sent_but_timeout(command, **kwargs):
        ledger.append({'body': json.loads(kwargs['input'])['body'], 'user': {'login': 'borg-codex-bot'}})
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(fixes.subprocess, 'run', sent_but_timeout)
    with pytest.raises(RuntimeError, match='rerun'):
        fixes.publish([found()])
    assert guards[-1] == 'bot'
    assert fixes.publish([found()]) == 0
    assert len(ledger) == 1


def test_publish_verifies_comment_author_and_body(monkeypatch):
    monkeypatch.setattr(fixes.shared, 'require_main_job', lambda _: None)
    monkeypatch.setattr(fixes.shared.hosted, 'bot', lambda: None)
    monkeypatch.setattr(fixes.shared, 'existing_issues', lambda: [issue()])
    def api(endpoint):
        if '/comments?' in endpoint:
            return []
        return {'body': 'wrong', 'user': {'login': 'TheTwist76'}}
    monkeypatch.setattr(fixes.shared.evidence, 'api', api)
    monkeypatch.setattr(fixes.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"id": 123}'))
    with pytest.raises(ValueError, match='author/body'):
        fixes.publish([found()])


def test_complete_bounded_comment_pagination(monkeypatch):
    calls = []
    def api(endpoint):
        calls.append(endpoint)
        return [{}] * 100 if len(calls) == 1 else [{'last': True}]
    monkeypatch.setattr(fixes.shared.evidence, 'api', api)
    assert fixes.comments(706)[-1] == {'last': True}
    assert len(calls) == 2


def test_asset_digest_and_size_are_required():
    asset = {'name': 'archive', 'size': 10, 'digest': 'sha256:' + 'a' * 64, 'state': 'uploaded'}
    assert fixes.asset_identity(asset, 'archive') == 'a' * 64
    for change in ({'digest': None}, {'size': fixes.MAX_ARCHIVE + 1}, {'state': 'new'}, {'name': 'other'}):
        with pytest.raises((ValueError, TypeError)):
            fixes.asset_identity({**asset, **change}, 'archive')


def test_download_rejects_wrong_digest_and_excess_bytes(tmp_path, monkeypatch):
    asset = {'name': 'cpython-3.13.1+20260101-x86_64-unknown-linux-gnu-pgo+lto-full.tar.zst',
             'size': 5, 'digest': 'sha256:' + hashlib.sha256(b'right').hexdigest(), 'state': 'uploaded'}
    monkeypatch.setattr(fixes.urllib.request, 'build_opener',
                        lambda *args: SimpleNamespace(open=lambda *a, **k: io.BytesIO(b'wrong')))
    with pytest.raises(ValueError, match='checksum'):
        fixes.download_asset('20260101', asset, tmp_path / 'archive')
    asset['size'] = 1
    with pytest.raises(ValueError, match='exceeds'):
        fixes.download_asset('20260101', asset, tmp_path / 'archive')


def test_asset_redirect_rejects_external_or_cleartext_hosts():
    handler = fixes.AssetRedirect()
    for url in ('https://attacker.test/file', 'http://github.com/file', 'https://github.com@attacker.test/file'):
        with pytest.raises(ValueError, match='redirect'):
            handler.redirect_request(None, None, 302, '', {}, url)


def test_archive_reader_only_reads_metadata_without_extracting(tmp_path):
    archive = tmp_path / 'supplier.tar'
    with tarfile.open(archive, 'w') as out:
        body = b'{"python_version": "3.13.1"}'
        member = tarfile.TarInfo('python/PYTHON.json')
        member.size = len(body)
        out.addfile(member, io.BytesIO(body))
        evil = tarfile.TarInfo('../../should-not-exist')
        out.addfile(evil)
    subprocess.run(['zstd', '-q', str(archive)], check=True)
    assert fixes.archive_metadata(archive.with_suffix('.tar.zst')) == {'python_version': '3.13.1'}
    assert not (tmp_path / 'python').exists()


def test_reader_budget_is_enforced():
    reader = fixes.MetadataReader(io.BytesIO(b'abc'))
    reader.remaining = 1
    with pytest.raises(ValueError, match='limit'):
        reader.read(2)


def test_wrong_platform_or_series_never_downloads(tmp_path):
    lock, _, supplier, _, _ = release_inputs()
    for version, change in [('3.15.0', {}), ('3.13.1', {'target': 'aarch64-unknown-linux-gnu'})]:
        with pytest.raises(ValueError, match='platform/series'):
            fixes.candidate_inventory({**lock, **change}, supplier, version, tmp_path)


def test_inventory_checks_actual_metadata_and_source_versions(tmp_path, monkeypatch):
    lock, _, supplier, _, _ = release_inputs()
    for asset in supplier['assets']:
        asset.update(size=10, state='uploaded', digest='sha256:' + 'a' * 64)
    metadata = {'python_version': lock['version'], 'target_triple': lock['target'],
                'build_options': 'pgo+lto', 'crt_features': ['glibc-max-symbol-version:2.17'],
                'build_info': {'core': {'links': [{'name': 'sqlite3', 'system': False}]}, 'extensions': {}}}
    downloads = {'sqlite': {'version': '3540000', 'url': 'https://www.sqlite.org/source', 'sha256': 'b' * 64}}
    monkeypatch.setattr(fixes, 'supplier_commit', lambda _: 'c' * 40)
    monkeypatch.setattr(fixes, 'download_asset', lambda *args: 'a' * 64)
    monkeypatch.setattr(fixes, 'archive_metadata', lambda _: metadata)
    monkeypatch.setattr(fixes.urllib.request, 'build_opener', lambda *args: SimpleNamespace(
        open=lambda *a, **k: io.BytesIO(json.dumps(downloads).encode())))
    result = fixes.candidate_inventory(lock, supplier, lock['version'], tmp_path)
    assert result['components']['sqlite']['version'] == '3.54.0'
    assert result['evidence']['source_commit'] == 'c' * 40
    metadata['crt_features'] = ['glibc-max-symbol-version:2.28']
    with pytest.raises(ValueError, match='metadata'):
        fixes.candidate_inventory(lock, supplier, lock['version'], tmp_path)
    metadata['crt_features'] = ['glibc-max-symbol-version:2.17']
    metadata['build_options'] = 'freethreaded+pgo+lto'
    with pytest.raises(ValueError, match='build options'):
        fixes.candidate_inventory(lock, supplier, lock['version'], tmp_path)


def test_run_completes_fix_evidence_before_any_issue_write(monkeypatch):
    lock, candidate, supplier, pep, response = release_inputs()
    monkeypatch.setattr(monitor, 'baselines', lambda _: [('planned', lock)])
    monkeypatch.setattr(monitor, 'read_json', lambda url: {'tag': supplier['tag_name']} if url == monitor.LATEST else pep)
    monkeypatch.setattr(monitor, 'security_findings', lambda *a, **k: [])
    monkeypatch.setattr(monitor.monitor.evidence, 'api', lambda _: supplier)
    monkeypatch.setattr(monitor.monitor, 'existing_issues', lambda: [issue()])
    monkeypatch.setattr(monitor.monitor, 'require_main_job', lambda _: None)
    monkeypatch.setattr(monitor.monitor.hosted, 'bot', lambda: None)
    writes = []
    monkeypatch.setattr(monitor.monitor, 'write_issue', lambda *a, **k: writes.append(a))
    def fail(*args):
        raise ValueError('candidate metadata unavailable')
    monkeypatch.setattr(fixes, 'discover', fail)
    with pytest.raises(monitor.monitor.MonitorFailure, match='fix candidate evidence: invalid or incomplete metadata'):
        monitor.run(apply=True)
    assert writes == []


def test_preview_never_posts_and_reports_new_fixes(monkeypatch):
    lock, _, supplier, pep, _ = release_inputs()
    monkeypatch.setattr(monitor, 'baselines', lambda _: [('planned', lock)])
    monkeypatch.setattr(monitor, 'read_json', lambda url: {'tag': supplier['tag_name']} if url == monitor.LATEST else pep)
    monkeypatch.setattr(monitor, 'security_findings', lambda *a, **k: [])
    monkeypatch.setattr(monitor.monitor.evidence, 'api', lambda _: supplier)
    monkeypatch.setattr(monitor.monitor, 'existing_issues', lambda: [issue()])
    monkeypatch.setattr(fixes, 'discover', lambda *args: [found()])
    monkeypatch.setattr(fixes, 'notification', lambda *args: {'count': 1})
    monkeypatch.setattr(fixes, 'publish', lambda *args: pytest.fail('Preview attempted notification'))
    monkeypatch.setattr(monitor.monitor, 'write_issue', lambda *a, **k: pytest.fail('Preview attempted issue write'))
    result = monitor.run()
    assert result['fix_candidates'] == 1 and result['new_fix_notifications'] == 1
    assert result['notified_fixes'] == 0 and result['release_authorized'] is False


def test_new_candidate_component_cannot_retain_the_same_cve():
    lock, candidate, cve = fixtures()
    candidate['components']['openssl-3.5'] = {'version': '3.5.1'}
    cve['configurations'][0]['nodes'][0]['cpeMatch'].append({
        'vulnerable': True, 'criteria': 'cpe:2.3:a:openssl:openssl:*:*:*:*:*:*:*:*',
        'versionEndExcluding': '3.5.2'})
    assert fixes.fixed_components(cve, lock, candidate, monitor) == []
