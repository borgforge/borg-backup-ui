"""GitHub-bound CI reuse: exact trees, successful attempts and safe artifacts."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
import ci_evidence as evidence

SHA = 'a' * 40
TREE = 'b' * 40
EXPECTED = {'tree': TREE, 'policy': 'policy', 'environment': evidence.ENVIRONMENT}


@pytest.mark.parametrize('title', [
    f'CI {SHA}',
    f'CI | PR #688 | Checks and audit | source={SHA}',
    f'CI | main update | Checks and audit | source={SHA}',
    f'CI | Requested source | Checks and audit | source={SHA}',
])
def test_source_identity_accepts_current_and_historical_titles(title):
    assert evidence.run_source_sha({'display_title': title}) == SHA


@pytest.mark.parametrize('title', [
    None, 42, '', f'Other CI {SHA}', f'CI {SHA}\n',
    f'CI | PR #0 | Checks and audit | source={SHA}',
    f'CI | PR #688 | Checks and audit | source={SHA[:7]}',
    f'CI | PR #688 | Checks and audit | source={SHA} extra',
    f'CI | PR #688 | Checks and audit | source={SHA} | source={"c" * 40}',
    f'CI | Untrusted free text | Checks and audit | source={SHA}',
])
def test_source_identity_rejects_partial_or_ambiguous_titles(title):
    assert evidence.run_source_sha({'display_title': title}) is None


def test_identity_reuses_content_not_commit_and_invalidates_test_or_policy_changes(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], text=True).strip()
    git('init', '-b', 'main')
    git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
    (tmp_path / '.github').mkdir(); (tmp_path / '.github/policy').write_text('one')
    (tmp_path / 'tests.py').write_text('test one')
    git('add', '.'); git('commit', '-m', 'First')
    original = evidence.identity(tmp_path, git('rev-parse', 'HEAD'))
    git('commit', '--allow-empty', '-m', 'Same tree, new commit')
    assert evidence.identity(tmp_path, git('rev-parse', 'HEAD')) == original
    (tmp_path / 'tests.py').write_text('test two')
    git('add', '.'); git('commit', '-m', 'Tests changed')
    changed = evidence.identity(tmp_path, git('rev-parse', 'HEAD'))
    assert changed['tree'] != original['tree'] and changed['policy'] == original['policy']
    (tmp_path / '.github/policy').write_text('two')
    git('add', '.'); git('commit', '-m', 'Policy changed')
    assert evidence.identity(tmp_path, git('rev-parse', 'HEAD'))['policy'] != original['policy']


def artifact_api(monkeypatch, files, *, expired=False, digest=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, content in files:
            archive.writestr(name, content)
    data = stream.getvalue()
    artifact = {'id': 7, 'name': 'proof', 'expired': expired, 'size_in_bytes': len(data),
                'digest': digest or 'sha256:' + hashlib.sha256(data).hexdigest()}
    def api(endpoint, *, binary=False):
        return data if binary else {'artifacts': [artifact]}
    monkeypatch.setattr(evidence, 'api', api)
    return artifact


def test_download_checks_github_digest_and_expiry(monkeypatch):
    metadata = artifact_api(monkeypatch, [('ci-proof.json', '{}')])
    assert evidence.artifact_files(1, 'proof') == {'ci-proof.json': b'{}'}
    metadata['digest'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError, match='digest'):
        evidence.artifact_files(1, 'proof')
    metadata['expired'] = True
    with pytest.raises(ValueError, match='unexpired'):
        evidence.artifact_files(1, 'proof')


@pytest.mark.parametrize('names', [['../escape'], ['/absolute'], ['folder/file'], ['same', 'same']])
def test_download_rejects_zip_paths_and_duplicates(monkeypatch, names):
    artifact_api(monkeypatch, [(name, 'data') for name in names])
    with pytest.raises(ValueError, match='unsafe or duplicate'):
        evidence.artifact_files(1, 'proof')


def proof_api(monkeypatch):
    """Serve genuine-shaped runs, jobs and receipts; keep verifier logic real."""
    runs = {n: {'id': n, 'run_attempt': 1, 'path': evidence.WORKFLOW,
                'repository': {'full_name': evidence.REPOSITORY}, 'event': 'push',
                'head_sha': SHA, 'status': 'completed', 'conclusion': 'success'} for n in (1, 2)}
    receipts = {n: {**EXPECTED, 'schema': 1, 'run_id': n, 'attempt': 1,
                    'checked_sha': SHA, 'tests_run_id': 1} for n in runs}
    jobs = {n: [{'name': name, 'conclusion': 'success'} for name in
                ['CI result', 'audit / audit', 'checks / quality', 'checks / tests']] for n in runs}
    def api(endpoint, *, binary=False):
        if '/git/commits/' in endpoint:
            return {'tree': {'sha': TREE}, 'parents': []}
        number = int(endpoint.split('/runs/')[1].split('/')[0])
        return {'jobs': jobs[number]} if '/jobs?' in endpoint else runs[number]
    monkeypatch.setattr(evidence, 'api', api)
    monkeypatch.setattr(evidence, 'artifact_files', lambda n, name, limit: {
        'ci-proof.json': json.dumps(receipts[n]).encode()})
    return runs, receipts, jobs


def test_reuse_requires_actual_original_full_jobs_and_same_attempt(monkeypatch):
    runs, receipts, jobs = proof_api(monkeypatch)
    assert evidence.verify_proof(2, EXPECTED)['tests_run_id'] == 1
    jobs[1][-1]['conclusion'] = 'skipped'
    with pytest.raises(ValueError, match='Required CI job'):
        evidence.verify_proof(2, EXPECTED)
    jobs[1][-1]['conclusion'] = 'success'
    runs[1]['run_attempt'] = 2
    with pytest.raises(ValueError, match='run attempt'):
        evidence.verify_proof(2, EXPECTED)


@pytest.mark.parametrize('title', [f'CI {SHA}', f'CI | Requested source | Checks and audit | source={SHA}'])
def test_dispatched_evidence_checks_selected_source_after_title_change(monkeypatch, title):
    runs, _, _ = proof_api(monkeypatch)
    for run in runs.values():
        run.update(event='workflow_dispatch', head_sha='c' * 40, display_title=title)
    assert evidence.verify_proof(2, EXPECTED)['tests_run_id'] == 1
    runs[2]['display_title'] = title.replace(SHA, 'd' * 40)
    with pytest.raises(ValueError, match='dispatch identity'):
        evidence.verify_proof(2, EXPECTED)
    runs[2]['display_title'] = title
    runs[1]['display_title'] = title.replace(SHA, 'd' * 40)
    with pytest.raises(ValueError, match='dispatch identity'):
        evidence.verify_proof(2, EXPECTED)


@pytest.mark.parametrize('mutation', ['failed', 'tree', 'policy', 'environment', 'chain', 'head', 'workflow'])
def test_reuse_fails_closed(monkeypatch, mutation):
    runs, receipts, _ = proof_api(monkeypatch)
    if mutation == 'failed':
        runs[1]['conclusion'] = 'failure'
    elif mutation == 'chain':
        receipts[1]['tests_run_id'] = 2
    elif mutation == 'head':
        runs[1]['head_sha'] = 'c' * 40
    elif mutation == 'workflow':
        runs[1]['path'] = '.github/workflows/other.yml'
    else:
        receipts[1][mutation] = 'different'
    with pytest.raises(ValueError):
        evidence.verify_proof(2, EXPECTED)


def test_missing_proof_triggers_fresh_ci_but_api_failure_never_means_pass(monkeypatch):
    runs, _, _ = proof_api(monkeypatch)
    def missing(*args):
        raise ValueError('expired')
    monkeypatch.setattr(evidence, 'artifact_files', missing)
    assert evidence.find_proof(EXPECTED, list(runs.values())) is None
    def failed(*args):
        raise RuntimeError('API unavailable')
    monkeypatch.setattr(evidence, 'artifact_files', failed)
    with pytest.raises(RuntimeError, match='API unavailable'):
        evidence.find_proof(EXPECTED, list(runs.values()))
