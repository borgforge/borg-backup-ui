#!/usr/bin/env python3
"""Read and verify GitHub CI evidence for exact Git trees (#677).

Evidence is data, never executable code. Reuse requires the complete tree,
check-policy fingerprint, successful GitHub jobs and an unexpired artifact.
GitHub remains the authority; a local JSON file alone grants no permission.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

import release_workflow as release

REPOSITORY = 'borgforge/borg-backup-ui'
WORKFLOW = '.github/workflows/ci.yml'
ENVIRONMENT = 'ubuntu-24.04-python3.12-node24-unraid-legacy-v1'
ROOT = Path(__file__).resolve().parents[1]


def exact_sha(value: str) -> str:
    """Accept a full commit/tree SHA; reject refs and command/path fragments."""
    if not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('An exact 40-character Git SHA is required')
    return value


def api(endpoint: str, *, binary: bool = False):
    """Read GitHub using gh credentials; never expose raw error bodies/secrets."""
    result = subprocess.run(['gh', 'api', endpoint], capture_output=True)
    if result.returncode:
        raise RuntimeError('GitHub API read failed; no verification is assumed')
    return result.stdout if binary else json.loads(result.stdout)


def pages(endpoint: str, collection: str) -> list:
    """Read a bounded paginated collection, failing closed if it exceeds 1000."""
    result = []
    separator = '&' if '?' in endpoint else '?'
    for page in range(1, 11):
        batch = api(f'{endpoint}{separator}per_page=100&page={page}')[collection]
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise RuntimeError('GitHub collection exceeds the verification limit')


def fetch_commit(repo: Path, sha: str) -> None:
    """Fetch only a missing immutable commit; never check it out or execute it."""
    exact_sha(sha)
    if subprocess.run(['git', '-C', str(repo), 'cat-file', '-e', f'{sha}^{{commit}}'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        subprocess.run(['git', '-C', str(repo), 'fetch', '--no-tags', 'origin', sha], check=True)


def identity(repo: Path, sha: str) -> dict:
    """Fingerprint the full tree and CI implementation, including dependency locks.

    Unlike the release source digest, this includes tests, workflows and docs.
    Only the complete tree can authorize reuse of full-source verification.
    """
    fetch_commit(repo, sha)
    tree = str(release.run_git(repo, 'rev-parse', f'{sha}^{{tree}}')).strip()
    names = str(release.run_git(repo, 'ls-tree', '-r', '--name-only', sha)).splitlines()
    selected = [p for p in names if p.startswith('.github/') or p in {
        'plugin/ci_evidence.py', 'plugin/ci_checks.py', 'plugin/build_metrics.py',
    }]
    digest = hashlib.sha256(ENVIRONMENT.encode())
    for name in sorted(selected):
        blob = release.run_git(repo, 'show', f'{sha}:{name}', text=False)
        digest.update(name.encode() + b'\0' + hashlib.sha256(blob).digest())
    return {'tree': tree, 'policy': digest.hexdigest(), 'environment': ENVIRONMENT}


def artifact_files(run_id: int, name: str, limit: int = 512 * 1024 * 1024) -> dict[str, bytes]:
    """Download one GitHub-bound artifact, validate its digest and flat ZIP entries.

    Reject duplicates, paths, links, expired artifacts and excessive expansion.
    No archive paths are ever extracted into the controller checkout.
    """
    entries = pages(f'repos/{REPOSITORY}/actions/runs/{int(run_id)}/artifacts', 'artifacts')
    matches = [a for a in entries if a['name'] == name and not a['expired']]
    if len(matches) != 1:
        raise ValueError('Exactly one unexpired artifact is required')
    artifact = matches[0]
    if artifact['size_in_bytes'] > limit:
        raise ValueError('Artifact exceeds its size limit')
    raw = api(f'repos/{REPOSITORY}/actions/artifacts/{int(artifact["id"])}/zip', binary=True)
    digest = artifact.get('digest', '')
    if len(raw) > limit or digest != 'sha256:' + hashlib.sha256(raw).hexdigest():
        raise ValueError('GitHub artifact digest mismatch or missing digest')
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(info.file_size for info in archive.infolist()) > limit:
            raise ValueError('Expanded artifact exceeds its size limit')
        for info in archive.infolist():
            mode = (info.external_attr >> 16) & 0o170000
            if (not re.fullmatch(r'[A-Za-z0-9_.-]+', info.filename) or info.filename in files
                    or info.is_dir() or mode not in (0, 0o100000)):
                raise ValueError('Artifact contains an unsafe or duplicate entry')
            files[info.filename] = archive.read(info)
    return files


def run_record(run_id: int) -> dict:
    """Require a successful CI run from this repository and supported trigger."""
    run = api(f'repos/{REPOSITORY}/actions/runs/{int(run_id)}')
    if (run['repository']['full_name'] != REPOSITORY or run['path'] != WORKFLOW
            or run['event'] not in {'push', 'pull_request', 'workflow_dispatch'}
            or run['status'] != 'completed' or run['conclusion'] != 'success'):
        raise ValueError('CI run is not successful verification from the expected workflow')
    return run


def receipt(run: dict) -> dict:
    """Load the receipt of the current run attempt, not an earlier rerun."""
    files = artifact_files(run['id'], f'ci-proof-{run["id"]}-{run["run_attempt"]}', 128 * 1024)
    if set(files) != {'ci-proof.json'}:
        raise ValueError('Unexpected CI evidence files')
    result = json.loads(files['ci-proof.json'])
    if (result.get('schema') != 1 or result.get('run_id') != run['id']
            or result.get('attempt') != run['run_attempt']):
        raise ValueError('CI evidence does not belong to this run attempt')
    return result


def require_jobs(run: dict, names: set[str]) -> None:
    """Require actual successful jobs; a JSON assertion alone is insufficient."""
    jobs = pages(f'repos/{REPOSITORY}/actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs', 'jobs')
    for name in names:
        matches = [job for job in jobs if job['name'] == name]
        if len(matches) != 1 or matches[0]['conclusion'] != 'success':
            raise ValueError(f'Required CI job did not pass: {name}')


def verify_proof(run_id: int, expected: dict) -> dict:
    """Verify the approval and original full test run without recursive reuse chains."""
    run = run_record(run_id)
    proof = receipt(run)
    require_jobs(run, {'CI result', 'audit / audit'})
    if any(proof.get(key) != value for key, value in expected.items()):
        raise ValueError('CI tree, policy or environment differs')
    commit = api(f'repos/{REPOSITORY}/git/commits/{exact_sha(proof["checked_sha"])}')
    if commit['tree']['sha'] != expected['tree']:
        raise ValueError('CI checked commit does not have the expected tree')
    original = run_record(int(proof['tests_run_id']))
    original_proof = proof if original['id'] == run['id'] else receipt(original)
    if (original_proof.get('tests_run_id') != original['id']
            or any(original_proof.get(key) != value for key, value in expected.items())):
        raise ValueError('Original full-source verification is incompatible')
    original_commit = api(f'repos/{REPOSITORY}/git/commits/{exact_sha(original_proof["checked_sha"])}')
    if original_commit['tree']['sha'] != expected['tree']:
        raise ValueError('Original CI commit does not have the expected tree')
    for checked_run, checked_proof, checked_commit in ((run, proof, commit),
                                                      (original, original_proof, original_commit)):
        event = checked_run['event']
        sha = checked_proof['checked_sha']
        if event == 'push' and checked_run['head_sha'] != sha:
            raise ValueError('CI push identity mismatch')
        if event == 'pull_request' and (len(checked_commit['parents']) != 2
                or checked_commit['parents'][1]['sha'] != checked_run['head_sha']):
            raise ValueError('CI PR merge identity mismatch')
        if event == 'workflow_dispatch' and checked_run.get('display_title') != f'CI {sha}':
            raise ValueError('CI dispatch identity mismatch')
    require_jobs(original, {'checks / quality', 'checks / tests', 'CI result'})
    return proof


def recent_runs() -> list:
    """Read the most recent 100 CI runs; older evidence simply requires new CI."""
    return api(f'repos/{REPOSITORY}/actions/workflows/ci.yml/runs?per_page=100')['workflow_runs']


def find_proof(expected: dict, runs: list | None = None) -> dict | None:
    """Find matching successful evidence; absent/expired evidence never means pass.

    API failures propagate. Missing or incompatible receipts are skipped so
    initial activation and expired artifacts naturally request a fresh CI run.
    """
    for run in recent_runs() if runs is None else runs:
        if run['status'] != 'completed' or run['conclusion'] != 'success':
            continue
        try:
            proof = receipt(run)
            if all(proof.get(key) == value for key, value in expected.items()):
                return verify_proof(run['id'], expected)
        except (ValueError, KeyError, TypeError, zipfile.BadZipFile):
            continue
    return None


def output(values: dict) -> None:
    """Write validated single-line workflow outputs, or printable local JSON."""
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
            for key, value in values.items():
                text = str(value)
                if '\n' in text or '\r' in text or not re.fullmatch(r'\w+', key):
                    raise ValueError('Unsafe workflow output')
                handle.write(f'{key}={text}\n')
    print(json.dumps(values, sort_keys=True))


def main() -> None:
    """Plan source/artifact CI or record its successful exact-source evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'record'))
    args = parser.parse_args()
    sha = exact_sha(os.environ.get('SOURCE_SHA') or os.environ['GITHUB_SHA'])
    expected = identity(ROOT, sha)
    if args.command == 'plan':
        import ci_checks
        # Dispatch checks a selected immutable source; normal CI checks its actual delta.
        mode = ('source' if os.environ.get('SOURCE_SHA') else
                ci_checks.classify_changes(ROOT, os.environ.get('BASE_SHA', '')))
        proof = find_proof(expected) if mode == 'source' else None
        output({'sha': sha, 'mode': mode, 'tests_run_id': proof['tests_run_id'] if proof else '',
                'base': os.environ.get('BASE_SHA', '')})
    else:
        run_id = int(os.environ['GITHUB_RUN_ID'])
        proof = {**expected, 'schema': 1, 'run_id': run_id,
                 'attempt': int(os.environ['GITHUB_RUN_ATTEMPT']), 'checked_sha': sha,
                 'tests_run_id': int(os.environ.get('TESTS_RUN_ID') or run_id)}
        path = ROOT / '.release-tmp/ci/ci-proof.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(proof, indent=2) + '\n')


if __name__ == '__main__':
    main()
