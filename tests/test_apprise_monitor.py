"""Apprise metadata, issue lifecycle and protected writer regressions (#699)."""
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import urllib.error

import pytest
import yaml
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin'))
import apprise_monitor as monitor


def index(*versions):
    """Make a minimal Simple API index without downloading any distribution."""
    return {'name': 'apprise', 'meta': {'api-version': '1.4'},
            'files': [{'filename': f'apprise-{v}.tar.gz', 'yanked': False} for v in versions]}


def metadata(*entries, current='2.1.0'):
    """Make installed-release JSON with explicit empty or supplied advisories."""
    return {'info': {'name': 'apprise', 'version': current}, 'vulnerabilities': list(entries)}


def advisory(**changes):
    """Return public security facts; arbitrary prose/link fields remain untrusted."""
    return {'id': 'PYSEC-2026-1', 'aliases': ['CVE-2026-12345'], 'fixed_in': ['2.2.0'],
            'summary': 'Public advisory', 'details': 'Details', 'withdrawn': None, **changes}


def detected(latest='2.2.0', entries=()):
    """Create validated findings using the installed 2.1.0 fixture."""
    return monitor.findings(Version('2.1.0'), Version(latest),
                            monitor.advisories(metadata(*entries), Version('2.1.0')))


def issue(finding, **changes):
    """Materialize a create plan as a bot issue for reconciliation tests."""
    actions, _ = monitor.plan_updates([finding], [])
    payload = actions[0]['payload']
    return {'number': 700, 'user': {'login': monitor.hosted.BOT}, 'state': 'open',
            'state_reason': None, 'body': payload['body'], 'title': payload['title'],
            'labels': [{'name': name} for name in payload['labels']], **changes}


@pytest.mark.parametrize('pins', ['apprise==2.1.0 \\\n    --hash=sha256:test\n', 'apprise==2.1.0\n'])
def test_read_bundled_pin(tmp_path, pins):
    path = tmp_path / 'runtime.lock'
    path.write_text('# fixture\n' + pins)
    assert monitor.bundled_version(path) == Version('2.1.0')


@pytest.mark.parametrize('pins', ['', 'apprise>=2.1.0', 'apprise==2.1.0\napprise==2.2.0\n',
                                  'apprise==2.2rc1\n', 'apprise==invalid\n', 'apprise==2.1+local\n'])
def test_reject_missing_ambiguous_or_unstable_pin(tmp_path, pins):
    path = tmp_path / 'runtime.lock'
    path.write_text(pins)
    with pytest.raises(ValueError):
        monitor.bundled_version(path)


def test_numeric_order_stability_and_partly_yanked_release():
    data = index('2.9.0', '2.10.0', '3.0.0rc1', '4.0.0.dev1', '2.11.0', '2.12.0')
    data['files'][-2]['yanked'] = True
    data['files'][-1]['yanked'] = ''  # Empty reason still indicates withdrawal.
    data['files'].append({'filename': 'apprise-2.10.0-py3-none-any.whl', 'yanked': 'bad wheel'})
    assert monitor.latest_stable(data) == Version('2.10.0')


@pytest.mark.parametrize('data', [
    {}, index(), index('3.0rc1'), {'name': 'other', 'meta': {'api-version': '1.4'}, 'files': []},
    {'name': 'apprise', 'meta': {'api-version': '2.0'}, 'files': []},
    {**index(), 'files': [{'filename': 'apprise-2.0.tar.gz', 'yanked': None}]},
    {**index(), 'files': [{'filename': 'apprise-2.0+local.tar.gz'}]},
    {**index(), 'files': [{'filename': 'other-2.0.tar.gz'}]},
    {**index(), 'files': [{'filename': '../apprise-2.0.tar.gz'}]},
    {**index(), 'files': [{'filename': 'unrecognized.zip'}]},
])
def test_invalid_index_fails_instead_of_claiming_no_update(data):
    with pytest.raises(ValueError):
        monitor.latest_stable(data)


@pytest.mark.parametrize('latest', ['2.0', '2.1.0'])
def test_no_new_version(latest):
    assert detected(latest) == []


def test_new_release_finding_has_actionable_sources_and_no_upgrade_instruction():
    actions, _ = monitor.plan_updates(detected(), [])
    payload = actions[0]['payload']
    assert payload['title'] == 'Review Apprise 2.2.0 update'
    for text in ('2.1.0', '2.2.0', 'https://github.com/caronc/apprise/releases',
                 'https://pypi.org/project/apprise/2.2.0/', 'lockfile and hashes', 'maintainer testing'):
        assert text in payload['body']
    assert 'no automatic update is authorized' in payload['body']


@pytest.mark.parametrize('data', [
    {'info': {'name': 'apprise', 'version': '2.1.0'}},
    metadata(current='2.0.0'), metadata(advisory(id='@everyone')), metadata(advisory(aliases=None)),
    metadata(advisory(fixed_in=['$(touch evil)'])), metadata(advisory(withdrawn='not-a-date')),
    metadata(advisory(aliases=['CVE-2026-12345\n::warning::injected'])),
    metadata(advisory(details={'unexpected': 'object'})),
    metadata(advisory(), advisory(fixed_in=[])),
])
def test_invalid_security_metadata_fails(data):
    with pytest.raises(ValueError):
        monitor.advisories(data, Version('2.1.0'))


def test_advisory_order_dedup_and_withdrawal():
    data = metadata(advisory(), advisory(), advisory(id='PYSEC-2026-2', withdrawn='2026-11-04T10:00:00Z'))
    assert len(monitor.advisories(data, Version('2.1.0'))) == 1
    assert detected('2.1.0', [advisory()])[0]['key'] == 'security:PYSEC-2026-1'


def test_shared_aliases_merge_and_keep_existing_issue_when_primary_id_changes():
    original = advisory()
    second = advisory(id='GHSA-abcd-1234-efgh', aliases=['CVE-2026-12345'])
    third = advisory(id='PYSEC-2026-3', aliases=['GHSA-abcd-1234-efgh'])
    findings = detected('2.1.0', [third, original, second])
    assert len(findings) == 1
    existing = issue(detected('2.1.0', [original])[0])
    actions, _ = monitor.plan_updates(findings, [existing])
    assert len(actions) == 1 and actions[0]['method'] == 'PATCH'
    assert 'security:PYSEC-2026-1:start' in actions[0]['payload']['body']
    assert 'security:GHSA-abcd-1234-efgh:start' not in actions[0]['payload']['body']
    assert findings == detected('2.1.0', [second, original, third])
    existing.update(actions[0]['payload'])
    assert monitor.plan_updates(findings, [existing]) == ([], 0)


def test_conflicting_alias_issues_require_reconciliation():
    first = issue(detected('2.1.0', [advisory()])[0])
    second = issue(detected('2.1.0', [advisory(id='GHSA-abcd-1234-efgh')])[0], number=701)
    findings = detected('2.1.0', [advisory(), advisory(id='GHSA-abcd-1234-efgh')])
    with pytest.raises(ValueError, match='Overlapping'):
        monitor.plan_updates(findings, [first, second])


def test_whitespace_only_advisory_changes_are_quiet():
    original = detected('2.1.0', [advisory()])[0]
    reformatted = detected('2.1.0', [advisory(summary=' Public\n advisory ', details='Details\n')])[0]
    assert monitor.plan_updates([reformatted], [issue(original)]) == ([], 0)


def test_untrusted_prose_and_links_never_enter_issue_body():
    hostile = '@everyone <script>bad</script> <!-- bbui-apprise-monitor:end --> $(touch bad)'
    findings = detected(entries=[advisory(summary=hostile, details=hostile, link='https://evil.invalid')])
    rendered = json.dumps(monitor.plan_updates(findings, [])[0])
    assert hostile not in rendered and 'evil.invalid' not in rendered
    assert 'https://osv.dev/vulnerability/PYSEC-2026-1' in rendered


def test_repeat_run_preserves_checkboxes_and_notes_without_writes():
    finding = detected()[0]
    existing = issue(finding)
    existing['body'] = ('Maintainer introduction\n\n' + existing['body'].replace('- [ ] Review', '- [x] Review')
                        + '\nMaintainer notes: wait for review.\n')
    assert monitor.plan_updates([finding], [existing]) == ([], 0)


def test_version_upgrade_updates_open_issue_without_losing_notes():
    finding = detected()[0]
    existing = issue(finding)
    existing['body'] += '\nKeep this note.\n'
    finding['text'] = finding['text'].replace('2.1.0', '2.1.1')
    actions, _ = monitor.plan_updates([finding], [existing])
    assert actions[0]['method'] == 'PATCH'
    assert actions[0]['payload']['body'].endswith('\nKeep this note.\n')
    assert set(actions[0]['payload']) == {'body'}


@pytest.mark.parametrize('state,reason,labels', [
    ('closed', 'completed', []), ('closed', 'not_planned', []),
    ('open', None, [{'name': 'status::waiting'}]),
])
def test_closed_or_deferred_release_is_not_recreated(state, reason, labels):
    finding = detected()[0]
    existing = issue(finding, state=state, state_reason=reason, labels=labels)
    finding['text'] += '\nChanged facts.'
    assert monitor.plan_updates([finding], [existing]) == ([], 1)


@pytest.mark.parametrize('change', [{'fixed_in': ['2.3.0']}, {'details': 'New security information'},
                                  {'aliases': ['CVE-2026-12345', 'GHSA-abcd-1234-efgh']}])
def test_changed_security_reopens_completed_issue_and_then_is_quiet(change):
    original = detected('2.1.0', [advisory()])[0]
    existing = issue(original, state='closed', state_reason='completed')
    finding = detected('2.1.0', [advisory(**change)])[0]
    actions, _ = monitor.plan_updates([finding], [existing])
    assert actions[0]['payload']['state'] == 'open'
    existing.update(actions[0]['payload'])
    assert monitor.plan_updates([finding], [existing]) == ([], 0)


@pytest.mark.parametrize('changes', [{'labels': [{'name': 'status::waiting'}]},
                                   {'state': 'closed', 'state_reason': 'not_planned'}])
def test_security_deferral_is_respected(changes):
    existing = issue(detected('2.1.0', [advisory()])[0], **changes)
    finding = detected('2.1.0', [advisory(fixed_in=['2.3.0'])])[0]
    assert monitor.plan_updates([finding], [existing]) == ([], 1)


def test_new_advisory_is_not_hidden_by_closed_release():
    release = detected()[0]
    actions, _ = monitor.plan_updates(detected(entries=[advisory()]), [issue(release, state='closed')])
    assert len(actions) == 1 and 'security' in actions[0]['payload']['title']


@pytest.mark.parametrize('kind', ['duplicate', 'other-author', 'broken-block', 'multiple-blocks'])
def test_ambiguous_history_fails_without_recreating_issues(kind):
    existing = issue(detected()[0])
    history = [existing]
    if kind == 'duplicate':
        history.append(deepcopy(existing))
    elif kind == 'other-author':
        existing['user']['login'] = 'someone-else'
    elif kind == 'broken-block':
        existing['body'] = existing['body'].replace(monitor.END, '')
    else:
        existing['body'] += existing['body']
    with pytest.raises(ValueError):
        monitor.plan_updates(detected(), history)


def test_history_paginates_and_keeps_closed_issues_even_without_labels(monkeypatch):
    calls = []
    existing = issue(detected()[0], state='closed', labels=[])

    def api(endpoint):
        calls.append(endpoint)
        return [{'pull_request': {}}] * 100 if endpoint.endswith('page=1') else [existing]

    monkeypatch.setattr(monitor.evidence, 'api', api)
    assert monitor.existing_issues() == [existing]
    assert len(calls) == 2 and all('state=all&creator=borg-codex-bot' in c for c in calls)


def test_history_limit_and_api_failure_are_not_empty_history(monkeypatch):
    monkeypatch.setattr(monitor.evidence, 'api', lambda endpoint: [{}] * 100)
    with pytest.raises(RuntimeError, match='2,000'):
        monitor.existing_issues()
    monkeypatch.setattr(monitor.evidence, 'api', lambda endpoint: {'message': 'rate limit'})
    with pytest.raises(ValueError):
        monitor.existing_issues()


def protected_env(monkeypatch):
    """Model a reviewed main checkout; callers can invalidate one boundary."""
    values = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': monitor.REPO,
              'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'schedule',
              'GITHUB_WORKFLOW_REF': f'{monitor.REPO}/.github/workflows/apprise-monitor.yml@refs/heads/main',
              'BBUI_ENVIRONMENT': 'dependency-monitor', 'GITHUB_SHA': 'a' * 40}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(monitor.security, 'guard_public', lambda root: None)
    monkeypatch.setattr(monitor.hosted, 'git', lambda *args: 'a' * 40)
    monkeypatch.setattr(monitor.evidence, 'api', lambda endpoint: {'object': {'sha': 'a' * 40}})


@pytest.mark.parametrize('event', ['schedule', 'workflow_dispatch'])
def test_protected_main_events(monkeypatch, event):
    protected_env(monkeypatch)
    monkeypatch.setenv('GITHUB_EVENT_NAME', event)
    monitor.require_main_job()


@pytest.mark.parametrize('key,value', [('GITHUB_ACTIONS', ''), ('GITHUB_REPOSITORY', 'other/repo'),
    ('GITHUB_REF', 'refs/pull/699/merge'), ('GITHUB_EVENT_NAME', 'pull_request'),
    ('GITHUB_EVENT_NAME', 'push'), ('BBUI_ENVIRONMENT', 'testing'),
    ('GITHUB_WORKFLOW_REF', 'untrusted'), ('GITHUB_SHA', 'b' * 40)])
def test_untrusted_jobs_cannot_write(monkeypatch, key, value):
    protected_env(monkeypatch)
    monkeypatch.setenv(key, value)
    monkeypatch.setattr(monitor.hosted, 'bot', lambda: pytest.fail('identity read after failed job guard'))
    with pytest.raises(RuntimeError):
        monitor.write_issue(monitor.plan_updates(detected(), [])[0][0])


def test_main_movement_blocks_writes(monkeypatch):
    protected_env(monkeypatch)
    monkeypatch.setattr(monitor.evidence, 'api', lambda endpoint: {'object': {'sha': 'b' * 40}})
    with pytest.raises(RuntimeError, match='Main changed'):
        monitor.require_main_job()


def test_missing_bot_credentials_fail_even_with_no_new_version(monkeypatch):
    monkeypatch.setattr(monitor, 'require_main_job', lambda: None)

    def fail():
        raise RuntimeError('GitHub API read failed')

    monkeypatch.setattr(monitor.hosted, 'bot', fail)
    monkeypatch.setattr(monitor, 'pypi_json', lambda url: pytest.fail('must check bot first'))
    with pytest.raises(monitor.MonitorFailure, match='bot identity'):
        monitor.run(apply=True)


@pytest.mark.parametrize('field,value', [('body', 'New maintainer notes'), ('state', 'closed'),
                                       ('labels', [{'name': 'status::waiting'}])])
def test_concurrent_issue_edit_blocks_update(monkeypatch, field, value):
    existing = issue(detected()[0])
    finding = detected()[0]
    finding['text'] += '\nChanged version facts.'
    actions, _ = monitor.plan_updates([finding], [existing])
    existing[field] = value
    monkeypatch.setattr(monitor, 'require_main_job', lambda: None)
    monkeypatch.setattr(monitor.evidence, 'api', lambda endpoint: existing)
    monkeypatch.setattr(monitor.hosted, 'bot', lambda: pytest.fail('no write after issue changed'))
    with pytest.raises(RuntimeError, match='Issue changed'):
        monitor.write_issue(actions[0])


@pytest.mark.parametrize('login', ['TheTwist76', '', 'another-bot'])
def test_wrong_identity_prevents_mutation(monkeypatch, login):
    monkeypatch.setattr(monitor, 'require_main_job', lambda: None)
    monkeypatch.setattr(monitor.evidence, 'api', lambda endpoint: {'login': login})
    monkeypatch.setattr(monitor.subprocess, 'run', lambda *args, **kwargs: pytest.fail('unexpected write'))
    with pytest.raises(RuntimeError, match='borg-codex-bot'):
        monitor.write_issue(monitor.plan_updates(detected(), [])[0][0])


def test_write_checks_identity_each_time_and_verifies_persisted_author(monkeypatch):
    calls = []
    monkeypatch.setattr(monitor, 'require_main_job', lambda: calls.append('guard'))

    def api(endpoint):
        calls.append(endpoint)
        return {'login': monitor.hosted.BOT} if endpoint == 'user' else {'user': {'login': monitor.hosted.BOT}}

    def command(args, **kwargs):
        calls.append('write')
        assert args[-2:] == ['--input', '-'] and 'shell' not in kwargs
        assert json.loads(kwargs['input'])['body']
        return subprocess.CompletedProcess(args, 0, json.dumps({'number': 700}), '')

    monkeypatch.setattr(monitor.evidence, 'api', api)
    monkeypatch.setattr(monitor.subprocess, 'run', command)
    actions, _ = monitor.plan_updates(detected(entries=[advisory()]), [])
    for action in actions:
        monitor.write_issue(action)
    assert calls == ['guard', 'user', 'write', f'repos/{monitor.REPO}/issues/700'] * 2


@pytest.mark.parametrize('failure', ['http', 'author', 'malformed'])
def test_write_failure_and_wrong_author_fail(monkeypatch, failure):
    monkeypatch.setattr(monitor, 'require_main_job', lambda: None)
    monkeypatch.setattr(monitor.hosted, 'bot', lambda: None)
    monkeypatch.setattr(monitor.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a, 1 if failure == 'http' else 0, 'oops' if failure == 'malformed' else '{"number":700}', 'secret error'))
    monkeypatch.setattr(monitor.evidence, 'api', lambda endpoint: {'user': {'login': 'other'}})
    with pytest.raises(RuntimeError) as error:
        monitor.write_issue(monitor.plan_updates(detected(), [])[0][0])
    assert 'secret error' not in str(error.value)


@pytest.mark.parametrize('failure', ['timeout', 'rate-limit', 'json', 'size', 'redirect'])
def test_metadata_transport_fails_closed(monkeypatch, failure):
    class Opener:
        """Supply transport errors without real network calls."""

        def open(self, request, timeout):
            assert timeout == 30
            assert not request.has_header('Authorization')
            if failure == 'timeout':
                raise TimeoutError('untrusted detail')
            if failure in ('rate-limit', 'redirect'):
                raise urllib.error.HTTPError(request.full_url, 429 if failure == 'rate-limit' else 302, '', {}, None)
            return io.BytesIO(b'not-json' if failure == 'json' else b'x' * (monitor.MAX_RESPONSE + 1))

    monkeypatch.setattr(monitor.urllib.request, 'build_opener', lambda *args: Opener())
    with pytest.raises((ValueError, RuntimeError)):
        monitor.pypi_json(monitor.INDEX)


def test_successful_bounded_metadata_read_and_redirect_policy(monkeypatch):
    class Opener:
        """Return only JSON metadata, never a package."""

        def open(self, request, timeout):
            assert request.full_url == monitor.INDEX
            return io.BytesIO(json.dumps(index('2.1.0')).encode())

    monkeypatch.setattr(monitor.urllib.request, 'build_opener', lambda *args: Opener())
    assert monitor.latest_stable(monitor.pypi_json(monitor.INDEX)) == Version('2.1.0')
    assert monitor.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid') is None
    with pytest.raises(ValueError):
        monitor.pypi_json('https://evil.invalid')


def test_preview_and_no_change_do_not_write(monkeypatch):
    monkeypatch.setattr(monitor, 'pypi_json', lambda url: index('2.1.0') if url == monitor.INDEX else metadata())
    monkeypatch.setattr(monitor, 'existing_issues', lambda: [])
    monkeypatch.setattr(monitor, 'write_issue', lambda action: pytest.fail('preview wrote an issue'))
    result = monitor.run()
    assert result['findings'] == result['creates'] == result['updates'] == 0
    assert result['mode'] == 'preview'


def test_apply_round_trip_creates_updates_and_then_stays_quiet(monkeypatch):
    history = []
    source = [advisory()]
    calls = []
    monkeypatch.setattr(monitor, 'require_main_job', lambda: calls.append('guard'))
    monkeypatch.setattr(monitor, 'pypi_json', lambda url: index('2.2.0') if url == monitor.INDEX else metadata(*source))

    def api(endpoint):
        if endpoint == 'user':
            calls.append('identity')
            return {'login': monitor.hosted.BOT}
        if '?' in endpoint:
            return deepcopy(history)
        return deepcopy(next(item for item in history if endpoint.endswith('/' + str(item['number']))))

    def command(args, **kwargs):
        calls.append('write')
        payload = json.loads(kwargs['input'])
        if args[3] == 'POST':
            saved = {'number': 700 + len(history), 'user': {'login': monitor.hosted.BOT},
                     'state': 'open', 'state_reason': None, **payload}
            saved['labels'] = [{'name': name} for name in payload['labels']]
            history.append(saved)
        else:
            saved = next(item for item in history if args[4].endswith('/' + str(item['number'])))
            saved.update(payload)
        return subprocess.CompletedProcess(args, 0, json.dumps(saved), '')

    monkeypatch.setattr(monitor.evidence, 'api', api)
    monkeypatch.setattr(monitor.subprocess, 'run', command)
    result = monitor.run(apply=True)
    assert result['creates'] == 2 and len(history) == 2
    assert monitor.run(apply=True)['creates'] == 0
    assert calls.count('write') == 2
    source[0]['fixed_in'] = ['2.3.0']
    assert monitor.run(apply=True)['updates'] == 1
    assert monitor.run(apply=True)['updates'] == 0
    assert calls.count('write') == 3


def test_failure_before_reconciliation_cannot_create_partial_findings(monkeypatch):
    monkeypatch.setattr(monitor, 'require_main_job', lambda: None)
    monkeypatch.setattr(monitor.hosted, 'bot', lambda: None)
    monkeypatch.setattr(monitor, 'pypi_json', lambda url: index('2.2.0') if url == monitor.INDEX else {})
    monkeypatch.setattr(monitor, 'write_issue', lambda action: pytest.fail('partial metadata caused write'))
    with pytest.raises(monitor.MonitorFailure, match='security metadata validation'):
        monitor.run(apply=True)


def test_cli_failure_does_not_echo_upstream_text(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['apprise_monitor.py'])

    def fail(apply):
        monitor.checked('PyPI security metadata request', lambda: (_ for _ in ()).throw(ValueError('::warning::token-secret')))

    monkeypatch.setattr(monitor, 'run', fail)
    assert monitor.main() == 1
    output = capsys.readouterr()
    assert 'no all-clear' in output.err and 'token-secret' not in output.err and not output.out


def test_workflow_has_daily_main_only_bot_boundary():
    workflow = yaml.load((ROOT / '.github/workflows/apprise-monitor.yml').read_text(), Loader=yaml.BaseLoader)
    assert set(workflow['on']) == {'schedule', 'workflow_dispatch'}
    assert workflow['on']['schedule'] == [{'cron': '41 6 * * *'}]
    assert workflow['permissions'] == {'contents': 'read'}
    assert workflow['concurrency'] == {'group': 'apprise-monitor', 'cancel-in-progress': 'false'}
    job = workflow['jobs']['monitor']
    assert job['environment'] == 'dependency-monitor'
    assert 'refs/heads/main' in job['if']
    assert 'env' not in job
    secret_steps = [step for step in job['steps'] if 'secrets.' in str(step)]
    assert len(secret_steps) == 1
    assert secret_steps[0]['run'] == 'python plugin/apprise_monitor.py --apply'
    assert secret_steps[0]['env']['BBUI_ENVIRONMENT'] == 'dependency-monitor'
