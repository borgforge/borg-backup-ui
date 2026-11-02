#!/usr/bin/env python3
"""Trusted GitHub release orchestration and local dispatch wrappers (#677).

Only protected workflow_dispatch jobs on main can publish or prepare a stable
PR. They execute this reviewed controller, never candidate scripts. Builds run
in separate read-only jobs. Every GitHub mutation verifies borg-codex-bot.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

import ci_evidence as evidence
import ci_pipeline as pipeline
import release_workflow as release
import security_workflow as security
from build_targets import target, validate_version

ROOT = Path(__file__).resolve().parents[1]
REPO = evidence.REPOSITORY
BOT = 'borg-codex-bot'


def bot() -> None:
    """Verify the actual process identity before each write; never switch accounts."""
    if evidence.api('user').get('login') != BOT:
        raise RuntimeError('This GitHub write requires borg-codex-bot credentials')


def gh_write(*args: str) -> str:
    """Perform one authorized gh mutation without logging credentials or raw errors."""
    bot()
    result = subprocess.run(['gh', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('GitHub write failed; inspect repository permissions and workflow logs')
    return result.stdout.strip()


def git(repo: Path, *args: str) -> str:
    """Run Git with process-scoped bot author metadata; no credential persistence."""
    env = dict(os.environ, GIT_AUTHOR_NAME=BOT, GIT_COMMITTER_NAME=BOT,
               GIT_AUTHOR_EMAIL=f'{BOT}@users.noreply.github.com',
               GIT_COMMITTER_EMAIL=f'{BOT}@users.noreply.github.com')
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, env=env).strip()


def push(repo: Path, *refs: str) -> None:
    """Push through gh's current bot token, without token arguments/config writes."""
    bot()
    git(repo, '-c', 'url.https://github.com/.insteadOf=git@github.com:',
        '-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential',
        'push', 'origin', *refs)


def trusted_job(workflow: str, environment: str) -> str:
    """Require the public main workflow and configured environment before writing.

    GitHub environment branch/reviewer rules enforce the secret boundary. This
    runtime check additionally rejects accidental local/branch execution and
    main movement while an approval or build was pending.
    """
    security.guard_public(ROOT)
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_REPOSITORY') != REPO
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_WORKFLOW_REF') != f'{REPO}/.github/workflows/{workflow}@refs/heads/main'
            or os.environ.get('BBUI_ENVIRONMENT') != environment):
        raise RuntimeError('Publication requires the protected workflow dispatched on main')
    main = evidence.api(f'repos/{REPO}/git/ref/heads/main')['object']['sha']
    if main != os.environ.get('GITHUB_SHA') or git(ROOT, 'rev-parse', 'HEAD') != main:
        raise RuntimeError('Main changed; start a new workflow for the current main')
    return evidence.exact_sha(main)


def selection(pr_number: str = '') -> dict:
    """Resolve current main or a mergeable PR to an immutable integration commit.

    Refuse stale synthetic merge refs and changed bases. Candidate generation
    includes current main rather than silently building an outdated PR head.
    """
    main = evidence.api(f'repos/{REPO}/git/ref/heads/main')['object']['sha']
    if not pr_number:
        return {'sha': main, 'base': main, 'head': main, 'pr': ''}
    if not re.fullmatch(r'[1-9][0-9]*', pr_number):
        raise ValueError('PR number must be a positive integer, or empty for main')
    pr = evidence.api(f'repos/{REPO}/pulls/{pr_number}')
    if (pr['state'] != 'open' or pr['base']['repo']['full_name'] != REPO
            or pr['base']['ref'] != 'main' or pr['base']['sha'] != main
            or pr.get('mergeable') is not True):
        raise ValueError('PR must be open, mergeable and resolved against current main; retry if GitHub is still calculating')
    sha = evidence.exact_sha(pr['merge_commit_sha'])
    commit = evidence.api(f'repos/{REPO}/git/commits/{sha}')
    if [p['sha'] for p in commit['parents']] != [main, pr['head']['sha']]:
        raise ValueError('PR merge ref is stale; wait for GitHub to update it')
    return {'sha': sha, 'base': main, 'head': pr['head']['sha'], 'pr': pr_number}


def current_selection(expected: dict) -> None:
    """Abort rather than publish after a PR or main changes during CI/build."""
    if selection(str(expected['pr'])) != expected:
        raise RuntimeError('Selected PR/main changed; request a new candidate')


def ensure_ci(selected: dict, *, dispatch: bool, timeout: int = 2700) -> dict:
    """Reuse matching GitHub evidence, wait for active CI or dispatch it once.

    Failed CI blocks this request. A manual CI rerun/new commit can repair it.
    The dispatcher is serialized by the testing workflow; it never starts a
    second check while the selected PR's automatic CI is running.
    """
    expected = evidence.identity(ROOT, selected['sha'])
    deadline = time.monotonic() + timeout
    requested = False
    while time.monotonic() < deadline:
        current_selection(selected)
        runs = evidence.recent_runs()
        # Dispatch runs all report main as head_sha, even when checking a PR.
        # The run title binds both automatic and dispatched CI to the actual
        # integration SHA; an unrelated PR failure must not block main.
        matching = [r for r in runs if r.get('display_title') == f'CI {selected["sha"]}']
        if matching and matching[0]['status'] == 'completed' and matching[0]['conclusion'] != 'success':
            raise RuntimeError(f'CI run {matching[0]["id"]} did not succeed; repair or rerun CI first')
        active = any(r['status'] != 'completed' for r in matching)
        if not active:
            proof = evidence.find_proof(expected, runs)
            if proof:
                return proof
            if not dispatch:
                raise RuntimeError('No matching GitHub CI proof; create/update the PR or request a test workflow')
            if not requested:
                gh_write('workflow', 'run', 'ci.yml', '--repo', REPO, '--ref', 'main',
                         '-f', f'source_sha={selected["sha"]}')
                requested = True
        print('Waiting for exact-source GitHub CI...', flush=True)
        time.sleep(15)
    raise RuntimeError('Timed out waiting for GitHub CI; no candidate was authorized')


def candidate_ref(version: str) -> str:
    """Return the immutable candidate tag for one validated plugin version."""
    return 'test-candidates/' + validate_version(version)


def snapshot(version: str) -> str | None:
    """Read an optional immutable candidate tag; remote errors are not absence."""
    ref = candidate_ref(version)
    lines = git(ROOT, 'ls-remote', '--refs', 'origin', 'refs/tags/' + ref).splitlines()
    if not lines:
        return None
    if len(lines) != 1:
        raise RuntimeError('Ambiguous candidate ref')
    sha = evidence.exact_sha(lines[0].split()[0])
    evidence.fetch_commit(ROOT, sha)
    if git(ROOT, 'show', '-s', '--format=%P', sha):
        raise ValueError('Candidate must be a root snapshot commit')
    names = git(ROOT, 'ls-tree', '-r', '--name-only', sha).splitlines()
    if names != ['borg-backup-ui-test.plg', f'releases/borg-backup-ui-{version}.txz']:
        raise ValueError('Candidate snapshot must contain exactly its manifest and package')
    return sha


def snapshot_files(version: str, directory: Path) -> tuple[Path, Path, str]:
    """Copy data from the selected tag, never from the rotating test feed."""
    sha = snapshot(version)
    if not sha:
        raise ValueError('Immutable candidate not found; create a testing candidate first')
    directory.mkdir(parents=True, exist_ok=False)
    manifest = directory / 'borg-backup-ui-test.plg'
    package = directory / f'borg-backup-ui-{version}.txz'
    manifest.write_bytes(release.run_git(ROOT, 'show', f'{sha}:{manifest.name}', text=False))
    package.write_bytes(release.run_git(ROOT, 'show', f'{sha}:releases/{package.name}', text=False))
    return manifest, package, sha


def verify_package(manifest: Path, package: Path, version: str, source: str) -> dict:
    """Verify candidate bytes and bind source/notes to the selected immutable commit."""
    evidence.fetch_commit(ROOT, source)
    result = pipeline.verify_candidate(manifest, package, 'unraid-legacy', 'testing',
                                       version, release.source_digest(ROOT, source))
    provenance = result['provenance']
    if provenance.get('source_commit') != source:
        raise ValueError('Candidate provenance does not identify the selected source commit')
    # Read blobs as data into fresh regular files; never extract PR symlinks.
    notes = ROOT / '.release-tmp' / f'notes-{os.getpid()}-{time.time_ns()}'
    pending = notes / 'release-notes/pending'
    pending.mkdir(parents=True)
    try:
        for entry in git(ROOT, 'ls-tree', '-r', source, '--', 'release-notes/pending').splitlines():
            mode, kind, rest = entry.split(' ', 2)
            _, path = rest.split('\t', 1)
            if path.endswith('/README.md'):
                continue
            if mode != '100644' or kind != 'blob' or not re.fullmatch(r'release-notes/pending/[0-9]+\.md', path):
                raise ValueError('Unexpected release-note entry')
            (pending / Path(path).name).write_bytes(release.run_git(ROOT, 'show', f'{source}:{path}', text=False))
        _, fragments, digest = release.rendered_release_notes(notes)
        if provenance.get('release_note_fragments') != fragments or provenance.get('release_notes_sha256') != digest:
            raise ValueError('Candidate release notes differ from the selected source')
    finally:
        shutil.rmtree(notes)
    return result


def resolve(version: str, pr_number: str) -> None:
    """Authorize an immutable build selection using trusted main and GitHub evidence."""
    main = trusted_job('testing-release.yml', 'testing')
    validate_version(version)
    selected = selection(pr_number)
    expected = evidence.identity(ROOT, selected['sha'])
    if expected['policy'] != evidence.identity(ROOT, main)['policy']:
        raise ValueError('CI policy changes must be reviewed/merged before protected publication')
    proof = ensure_ci(selected, dispatch=True)
    existing = snapshot(version)
    if existing:
        directory = ROOT / '.release-tmp' / f'existing-{os.getpid()}'
        manifest, package, _ = snapshot_files(version, directory)
        verify_package(manifest, package, version, selected['sha'])
    evidence.output({**selected, 'ci_run': proof['run_id'], 'existing': 'true' if existing else 'false'})


def download_candidate(version: str) -> None:
    """Download build data from this workflow attempt using only the read token."""
    validate_version(version)
    run_id = int(os.environ['GITHUB_RUN_ID'])
    name = f'candidate-{run_id}-{int(os.environ["GITHUB_RUN_ATTEMPT"])}'
    files = evidence.artifact_files(run_id, name)
    if set(files) != {'borg-backup-ui-test.plg', f'borg-backup-ui-{version}.txz',
                      'candidate.json', 'SHA256SUMS'}:
        raise ValueError('Unexpected build artifact files')
    directory = ROOT / '.release-tmp/incoming'
    directory.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        (directory / name).write_bytes(data)


def publish(version: str, selected: dict, ci_run: int, existing: bool) -> None:
    """Publish verified data via the bot; candidate code is never executed here."""
    main = trusted_job('testing-release.yml', 'testing')
    expected = evidence.identity(ROOT, selected['sha'])
    if expected['policy'] != evidence.identity(ROOT, main)['policy']:
        raise ValueError('Candidate CI policy differs from trusted main')
    evidence.verify_proof(ci_run, expected)
    current_selection(selected)
    if existing:
        manifest, package, _ = snapshot_files(version, ROOT / '.release-tmp/retry-candidate')
    else:
        manifest = ROOT / '.release-tmp/incoming/borg-backup-ui-test.plg'
        package = manifest.parent / f'borg-backup-ui-{validate_version(version)}.txz'
    result = verify_package(manifest, package, version, selected['sha'])
    bot()
    subprocess.run(['bash', str(ROOT / 'plugin/publish-test-snapshot.sh'),
                    f'https://github.com/{REPO}.git', 'test-channel', str(manifest), str(package),
                    f'Publish testing {version} from {selected["sha"]} (#677)',
                    str(ROOT / '.release-tmp'), candidate_ref(version)], check=True)
    pinned = snapshot(version)
    remote = git(ROOT, 'ls-remote', 'origin', 'refs/heads/test-channel').split()[0]
    if remote != pinned:
        raise RuntimeError('Published test feed does not match its immutable candidate')
    # Read the published commit back rather than trusting local inputs alone.
    downloaded_manifest, downloaded_package, _ = snapshot_files(version, ROOT / '.release-tmp/published')
    verified = verify_package(downloaded_manifest, downloaded_package, version, selected['sha'])
    if verified['package_sha256'] != result['package_sha256']:
        raise RuntimeError('Published package differs from the verified build')
    summary(f'Test version **{version}**\n\n[Test URL]({target("unraid-legacy", "testing")["plugin_url"]})'
            f'\n\nCandidate: `{candidate_ref(version)}` / `{pinned}`'
            f'\n\nSource: `{selected["sha"]}`\n\nSHA256: `{result["package_sha256"]}`')


def summary(text: str) -> None:
    """Expose non-secret verification results in the workflow summary."""
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
            handle.write(text + '\n')
    print(text)


def stable(version: str, confirmed: bool) -> None:
    """Prepare a bot-owned release PR from an approved immutable candidate.

    Requires the protected stable environment, explicit test confirmation and
    unchanged main. Copies tested bytes and consumes only matching note fragments;
    never runs candidate scripts, builds a package, or merges the release PR.
    """
    main = trusted_job('stable-release.yml', 'stable')
    if not confirmed:
        raise ValueError('Explicit successful Unraid test confirmation is required')
    ensure_ci(selection(), dispatch=False)
    manifest, package, pinned = snapshot_files(version, ROOT / '.release-tmp/stable-candidate')
    result = pipeline.verify_candidate(manifest, package, 'unraid-legacy', 'testing', version,
                                       release.source_digest(ROOT, main))
    # Check the original source and rendered notes before promoting against main.
    verify_package(manifest, package, version, result['provenance']['source_commit'])
    if version <= release.manifest_version(ROOT / 'borg-backup-ui.plg'):
        raise ValueError('Stable version must advance the current stable version')
    branch = 'codex/release-' + version
    existing_prs = evidence.api(f'repos/{REPO}/pulls?state=open&head=borgforge:{branch}&base=main')
    for pr in existing_prs:
        if pr['user']['login'] != BOT:
            raise ValueError('Existing release PR is not owned by borg-codex-bot')
    worktree = ROOT / '.release-tmp/stable-tree'
    remote_branch = git(ROOT, 'ls-remote', '--heads', 'origin', 'refs/heads/' + branch)
    if remote_branch:
        evidence.fetch_commit(ROOT, remote_branch.split()[0])
        git(ROOT, 'worktree', 'add', '-b', branch, str(worktree), remote_branch.split()[0])
        git(worktree, 'merge', '--no-edit', main)
    else:
        git(ROOT, 'worktree', 'add', '-b', branch, str(worktree), main)
    try:
        (worktree / 'releases').mkdir(exist_ok=True)
        shutil.copy2(package, worktree / 'releases' / package.name)
        release.promote_artifacts(worktree, manifest, version, release.file_md5(package), result['provenance'])
        packages = sorted((worktree / 'releases').glob('borg-backup-ui-*.txz'))
        for old in packages[:-5]:
            old.unlink()
        release.verify_release_artifacts(worktree, main, ROOT)
        if pipeline.sha256(worktree / 'releases' / package.name) != result['package_sha256']:
            raise ValueError('Stable bytes differ from the tested candidate')
        git(worktree, 'add', 'borg-backup-ui.plg', 'borg_backup_ui.py', 'releases', 'release-notes/pending')
        if git(worktree, 'diff', '--cached', '--name-only'):
            git(worktree, 'commit', '-m', f'Promote tested {version} to stable (#677)')
        # Reject unexpected existing-branch changes, including CI/config changes.
        import ci_checks
        if ci_checks.classify_changes(worktree, main) != 'artifact':
            raise ValueError('Release PR contains unexpected source changes')
        trusted_job('stable-release.yml', 'stable')
        push(worktree, f'HEAD:refs/heads/{branch}')
        body = (f'Promote the approved candidate {version} byte-for-byte.\n\n'
                f'- Immutable candidate: `{candidate_ref(version)}` / `{pinned}`.\n'
                f'- Package SHA256: `{result["package_sha256"]}`.\n'
                '- Main source, release notes, package integrity and retention verified.\n'
                '- Maintainer confirmed the Unraid test and approved the stable environment.\n'
                '- No rebuild or repeated full source tests. Merge remains a maintainer action.\n')
        body_file = ROOT / '.release-tmp/release-pr.md'
        body_file.write_text(body)
        if existing_prs:
            payload = ROOT / '.release-tmp/release-pr.json'
            payload.write_text(json.dumps({'body': body}))
            number = existing_prs[0]['number']
            gh_write('api', '--method', 'PATCH', f'repos/{REPO}/pulls/{number}', '--input', str(payload))
        else:
            gh_write('pr', 'create', '--repo', REPO, '--base', 'main', '--head', branch,
                     '--title', f'Promote {version} to stable', '--body-file', str(body_file))
            rows = evidence.api(f'repos/{REPO}/pulls?state=open&head=borgforge:{branch}&base=main')
            if len(rows) != 1:
                raise RuntimeError('Cannot identify the created release PR')
            number = rows[0]['number']
        pr = evidence.api(f'repos/{REPO}/pulls/{number}')
        if pr['user']['login'] != BOT:
            raise RuntimeError('Release PR author verification failed')
        summary(f'Stable preparation **{version}**: [release PR]({pr["html_url"]})\n\n'
                f'Tested SHA256: `{result["package_sha256"]}`')
    finally:
        # All files are generated in this task-owned worktree; keep failures for inspection.
        if not git(worktree, 'status', '--porcelain'):
            git(ROOT, 'worktree', 'remove', str(worktree))


def local_pr() -> str:
    """Identify the clean, exactly pushed local branch's open PR without mutations."""
    release.require_clean(ROOT)
    if security.github_repository(git(ROOT, 'remote', 'get-url', 'origin')) != REPO:
        raise ValueError('Unexpected origin repository')
    git(ROOT, 'fetch', '--prune', 'origin')
    branch = git(ROOT, 'branch', '--show-current')
    if branch == 'main':
        if git(ROOT, 'rev-parse', 'HEAD') != selection()['sha']:
            raise ValueError('Local main is stale')
        return ''
    raw = subprocess.check_output(['gh', 'pr', 'list', '--repo', REPO, '--head', branch,
                                   '--state', 'open', '--json', 'number,headRefOid'], text=True)
    rows = json.loads(raw)
    if len(rows) != 1 or rows[0]['headRefOid'] != git(ROOT, 'rev-parse', 'HEAD'):
        raise ValueError('Create/update an open PR for the exact pushed local commit first')
    return str(rows[0]['number'])


def main() -> None:
    """Validate dispatch inputs and enforce private/public boundaries at entry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('resolve', 'download', 'publish', 'stable',
                                           'dispatch-test', 'dispatch-stable', 'preflight'))
    parser.add_argument('--version', default=os.environ.get('VERSION', ''))
    parser.add_argument('--pr', default=os.environ.get('PR_NUMBER', ''))
    parser.add_argument('--platform', default=os.environ.get('PLATFORM', 'unraid-legacy'))
    parser.add_argument('--confirm-tested', action='store_true')
    args = parser.parse_args()
    security.guard_public(ROOT)
    target(args.platform, 'stable' if 'stable' in args.command else 'testing')
    if args.command != 'preflight':
        validate_version(args.version)
    if args.command == 'resolve':
        resolve(args.version, args.pr)
    elif args.command == 'download':
        download_candidate(args.version)
    elif args.command == 'publish':
        selected = {key: os.environ[key.upper()] for key in ('sha', 'base', 'head', 'pr')}
        publish(args.version, selected, int(os.environ['CI_RUN']), os.environ['EXISTING'] == 'true')
    elif args.command == 'stable':
        stable(args.version, os.environ.get('CONFIRM_TESTED') == 'true')
    elif args.command == 'preflight':
        pr_number = local_pr()
        # Release PRs intentionally have no full-source receipt.
        import ci_checks
        base = selection(pr_number)['base']
        if ci_checks.classify_changes(ROOT, base) == 'artifact':
            ci_checks.verify_ci_release(ROOT, base, True)
            return
        proof = ensure_ci(selection(pr_number), dispatch=False)
        print(f'GitHub CI verified: run {proof["run_id"]}; no local full suite repeated.')
    else:
        workflow = 'testing-release.yml' if args.command == 'dispatch-test' else 'stable-release.yml'
        fields = ['-f', f'version={args.version}', '-f', f'platform={args.platform}']
        if args.command == 'dispatch-test':
            fields += ['-f', f'pr_number={args.pr or local_pr()}']
        else:
            if not args.confirm_tested:
                raise ValueError('Use --confirm-tested only after the successful maintainer Unraid test')
            fields += ['-f', 'confirm_tested=true']
        gh_write('workflow', 'run', workflow, '--repo', REPO, '--ref', 'main', *fields)
        print(f'Workflow requested: https://github.com/{REPO}/actions/workflows/{workflow}')


if __name__ == '__main__':
    main()
