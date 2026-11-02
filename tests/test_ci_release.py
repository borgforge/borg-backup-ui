"""Hosted release controls without publishing or accessing real credentials."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
import ci_release as ci

MAIN = 'a' * 40
HEAD = 'b' * 40
MERGE = 'c' * 40
SELECTED = {'sha': MERGE, 'base': MAIN, 'head': HEAD, 'pr': '42'}


def fake_selection(monkeypatch):
    pr = {'state': 'open', 'base': {'ref': 'main', 'sha': MAIN,
          'repo': {'full_name': ci.REPO}}, 'head': {'sha': HEAD},
          'mergeable': True, 'merge_commit_sha': MERGE}
    parents = [{'sha': MAIN}, {'sha': HEAD}]
    def api(endpoint):
        if '/pulls/' in endpoint:
            return pr
        if '/git/commits/' in endpoint:
            return {'parents': parents}
        return {'object': {'sha': MAIN}}
    monkeypatch.setattr(ci.evidence, 'api', api)
    return pr, parents


def test_selection_checks_actual_integration_parents_and_open_pr(monkeypatch):
    pr, parents = fake_selection(monkeypatch)
    assert ci.selection('42') == SELECTED
    parents[0]['sha'] = 'd' * 40
    with pytest.raises(ValueError, match='stale'):
        ci.selection('42')
    parents[0]['sha'] = MAIN
    pr['state'] = 'closed'
    with pytest.raises(ValueError, match='open, mergeable'):
        ci.selection('42')
    with pytest.raises(ValueError, match='positive integer'):
        ci.selection('42; echo token')


def test_publication_stops_when_source_moves(monkeypatch):
    monkeypatch.setattr(ci, 'selection', lambda _: {**SELECTED, 'head': 'd' * 40})
    with pytest.raises(RuntimeError, match='changed'):
        ci.current_selection(SELECTED)


def test_trusted_job_rejects_local_branch_execution_and_stale_main(monkeypatch):
    monkeypatch.setattr(ci.security, 'guard_public', lambda *_: None)
    fake_selection(monkeypatch)
    monkeypatch.setattr(ci, 'git', lambda *_: MAIN)
    for key, value in {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': ci.REPO,
                       'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
                       'GITHUB_WORKFLOW_REF': f'{ci.REPO}/.github/workflows/testing-release.yml@refs/heads/main',
                       'BBUI_ENVIRONMENT': 'testing', 'GITHUB_SHA': MAIN}.items():
        monkeypatch.setenv(key, value)
    assert ci.trusted_job('testing-release.yml', 'testing') == MAIN
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/feature')
    with pytest.raises(RuntimeError, match='protected workflow'):
        ci.trusted_job('testing-release.yml', 'testing')
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    monkeypatch.setenv('GITHUB_SHA', HEAD)
    with pytest.raises(RuntimeError, match='Main changed'):
        ci.trusted_job('testing-release.yml', 'testing')


def test_bot_identity_mismatch_prevents_write(monkeypatch):
    monkeypatch.setattr(ci.evidence, 'api', lambda _: {'login': 'TheTwist76'})
    def unexpected(*args, **kwargs):
        pytest.fail('A write was attempted with the wrong identity')
    monkeypatch.setattr(ci.subprocess, 'run', unexpected)
    with pytest.raises(RuntimeError, match='borg-codex-bot'):
        ci.gh_write('workflow', 'run', 'ci.yml')


def test_stable_requires_confirmation_before_reading_candidate(monkeypatch):
    monkeypatch.setattr(ci, 'trusted_job', lambda *_: MAIN)
    with pytest.raises(ValueError, match='confirmation'):
        ci.stable('2026.11.02.1200', False)


def prepare_wait(monkeypatch, runs, proof):
    monkeypatch.setattr(ci, 'current_selection', lambda _: None)
    monkeypatch.setattr(ci.evidence, 'identity', lambda *_: {'tree': 'tree'})
    monkeypatch.setattr(ci.evidence, 'recent_runs', lambda: runs)
    monkeypatch.setattr(ci.evidence, 'find_proof', lambda *_: proof)


def test_existing_ci_is_reused_without_dispatch(monkeypatch):
    prepare_wait(monkeypatch, [], {'run_id': 7})
    monkeypatch.setattr(ci, 'gh_write', lambda *_: pytest.fail('Redundant CI dispatch'))
    assert ci.ensure_ci(SELECTED, dispatch=True)['run_id'] == 7


def test_failed_ci_blocks_even_with_older_success(monkeypatch):
    prepare_wait(monkeypatch, [{'id': 8, 'head_sha': HEAD, 'status': 'completed', 'conclusion': 'failure'}],
                 {'run_id': 7})
    with pytest.raises(RuntimeError, match='did not succeed'):
        ci.ensure_ci(SELECTED, dispatch=True)


def test_running_ci_is_waited_for_without_duplicate_dispatch(monkeypatch):
    runs = [{'id': 8, 'head_sha': HEAD, 'status': 'in_progress', 'conclusion': None}]
    prepare_wait(monkeypatch, runs, {'run_id': 8})
    monkeypatch.setattr(ci.time, 'sleep', lambda _: runs[0].update(status='completed', conclusion='success'))
    monkeypatch.setattr(ci, 'gh_write', lambda *_: pytest.fail('Redundant CI dispatch'))
    assert ci.ensure_ci(SELECTED, dispatch=True)['run_id'] == 8


def test_missing_ci_dispatches_once_then_reads_hosted_proof(monkeypatch):
    prepare_wait(monkeypatch, [], None)
    writes = []
    monkeypatch.setattr(ci, 'gh_write', lambda *args: writes.append(args))
    monkeypatch.setattr(ci.time, 'sleep', lambda _: monkeypatch.setattr(
        ci.evidence, 'find_proof', lambda *_: {'run_id': 9}))
    assert ci.ensure_ci(SELECTED, dispatch=True)['run_id'] == 9
    assert len(writes) == 1 and f'source_sha={MERGE}' in writes[0]


def test_stable_prepares_real_artifact_only_branch_without_rebuilding(tmp_path, monkeypatch):
    """Exercise real Git/worktree and release validation; stub only remote authority."""
    from test_ci_pipeline import release_fixture
    repo, base, git = release_fixture(tmp_path)
    git('switch', '--detach', base)
    version = '2026.10.31.1600'
    candidate_dir = tmp_path / 'candidate'
    package = candidate_dir / f'borg-backup-ui-{version}.txz'
    manifest = candidate_dir / 'borg-backup-ui-test.plg'
    monkeypatch.setattr(ci, 'ROOT', repo)
    monkeypatch.setattr(ci, 'trusted_job', lambda *_: base)
    monkeypatch.setattr(ci, 'ensure_ci', lambda *_args, **_kwargs: {'run_id': 1})
    monkeypatch.setattr(ci, 'selection', lambda: {'sha': base})
    monkeypatch.setattr(ci, 'snapshot_files', lambda *_: (manifest, package, MERGE))
    # Source/notes binding has separate tests; this fixture predates source_commit.
    original_verify = ci.pipeline.verify_candidate
    def verify(*args):
        result = original_verify(*args)
        result['provenance']['source_commit'] = base
        return result
    monkeypatch.setattr(ci.pipeline, 'verify_candidate', verify)
    monkeypatch.setattr(ci, 'verify_package', lambda *_: None)
    original_git = ci.git
    def local_git(directory, *args):
        if args[:2] == ('ls-remote', '--heads'):
            return ''
        return original_git(directory, *args)
    monkeypatch.setattr(ci, 'git', local_git)
    writes = []
    created = []
    monkeypatch.setattr(ci, 'push', lambda *args: writes.append(args))
    monkeypatch.setattr(ci, 'gh_write', lambda *args: created.append(args))
    pr = {'number': 123, 'user': {'login': ci.BOT}, 'html_url': 'https://example.invalid/pr/123'}
    def api(endpoint):
        return ([pr] if created else []) if '?' in endpoint else pr
    monkeypatch.setattr(ci.evidence, 'api', api)
    ci.stable(version, True)
    branch = 'codex/release-' + version
    assert len(writes) == 1 and writes[0][1] == f'HEAD:refs/heads/{branch}'
    assert created[0][:2] == ('pr', 'create')
    import subprocess
    promoted = subprocess.check_output(['git', '-C', str(repo), 'show', f'{branch}:releases/{package.name}'])
    assert promoted == package.read_bytes()
    assert not (repo / '.release-tmp/stable-tree').exists()


def test_verify_package_binds_source_and_note_provenance(tmp_path, monkeypatch):
    """A self-consistent package still needs the selected source and note content."""
    monkeypatch.setattr(ci, 'ROOT', tmp_path)
    monkeypatch.setattr(ci.evidence, 'fetch_commit', lambda *_: None)
    monkeypatch.setattr(ci.release, 'source_digest', lambda *_: 'source')
    result = {'provenance': {'source_commit': MAIN}}
    monkeypatch.setattr(ci.pipeline, 'verify_candidate', lambda *_: result)
    with pytest.raises(ValueError, match='selected source commit'):
        ci.verify_package(tmp_path/'manifest', tmp_path/'package', '2026.11.02.1200', HEAD)
    monkeypatch.setattr(ci, 'git', lambda *_: '')
    with pytest.raises(ValueError, match='release notes differ'):
        ci.verify_package(tmp_path/'manifest', tmp_path/'package', '2026.11.02.1200', MAIN)
