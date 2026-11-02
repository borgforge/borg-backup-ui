#!/usr/bin/env python3
"""Publish approved stable artifacts as GitHub Releases without rebuilding (#685).

Only reviewed main workflows may use the release-publish environment. Historical
commits are read as data; their code is never executed with publishing credentials.
Every write uses ci_release's verified bot identity. Conflicts fail without edits
to existing tags/assets; interrupted drafts can resume with the same exact bytes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import ci_evidence as evidence
import ci_pipeline as pipeline
import ci_release as hosted
import release_workflow as release
import security_workflow as security
from build_targets import validate_version

ROOT = Path(__file__).resolve().parents[1]
REPO = evidence.REPOSITORY
REQUIRED_JOBS = {'plan', 'release-artifacts', 'audit / audit', 'CI result'}


def list_api(endpoint: str) -> list:
    """Read a GitHub array collection; fail closed beyond 1,000 entries."""
    separator = '&' if '?' in endpoint else '?'
    result = []
    for page in range(1, 11):
        batch = evidence.api(f'{endpoint}{separator}per_page=100&page={page}')
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise RuntimeError('GitHub collection exceeds the verification limit')


def ancestor(sha: str, main: str) -> None:
    """Require a commit on reviewed main history; never check it out."""
    evidence.exact_sha(sha)
    evidence.exact_sha(main)
    if sha == main:
        return
    comparison = evidence.api(f'repos/{REPO}/compare/{sha}...{main}')
    if (comparison['status'] not in {'ahead', 'identical'}
            or comparison['base_commit']['sha'] != sha
            or comparison['merge_base_commit']['sha'] != sha):
        raise ValueError('Publication commit is not on main history')


def fetch_data(sha: str) -> None:
    """Fetch only a missing commit/tree, without downloading all old packages."""
    evidence.exact_sha(sha)
    if subprocess.run(['git', '-C', str(ROOT), 'cat-file', '-e', f'{sha}^{{commit}}'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        subprocess.run(['git', '-C', str(ROOT), 'fetch', '--no-tags', '--depth=1',
                        'origin', sha], check=True)


def trusted_job(automatic: bool) -> str:
    """Require the main-only publisher and return its reviewed controller SHA.

    Main may advance while metadata is published: neither the Unraid feed nor a
    source branch is changed here. Both controller and release must remain on main.
    GitHub's environment branch rule is the credential boundary.
    """
    security.guard_public(ROOT)
    workflow = 'ci.yml' if automatic else 'github-release.yml'
    event = 'push' if automatic else 'workflow_dispatch'
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_REPOSITORY') != REPO
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') != event
            or os.environ.get('GITHUB_WORKFLOW_REF') != f'{REPO}/.github/workflows/{workflow}@refs/heads/main'
            or os.environ.get('BBUI_ENVIRONMENT') != 'release-publish'):
        raise RuntimeError('Publication requires the protected main release-publish workflow')
    sha = evidence.exact_sha(os.environ.get('GITHUB_SHA', ''))
    if hosted.git(ROOT, 'rev-parse', 'HEAD') != sha:
        raise RuntimeError('Publisher checkout differs from the reviewed controller')
    main = evidence.api(f'repos/{REPO}/git/ref/heads/main')['object']['sha']
    ancestor(sha, main)
    return sha


def merged_release(version: str) -> dict:
    """Resolve exactly one merged, bot-owned stable PR for a validated version."""
    branch = f'codex/release-{validate_version(version)}'
    matches = list_api(f'repos/{REPO}/pulls?state=closed&base=main&head=borgforge:{branch}')
    matches = [pr for pr in matches if pr.get('merged_at')]
    if len(matches) != 1:
        raise ValueError('Expected exactly one merged stable release PR')
    pr = evidence.api(f'repos/{REPO}/pulls/{int(matches[0]["number"])}')
    if (pr.get('merged') is not True or pr['state'] != 'closed'
            or pr['user']['login'] != hosted.BOT or pr['base']['ref'] != 'main'
            or pr['base']['repo']['full_name'] != REPO or pr['head']['ref'] != branch
            or (pr['head'].get('repo') or {}).get('full_name') != REPO):
        raise ValueError('Stable release PR identity or approval does not match')
    sha = evidence.exact_sha(pr['merge_commit_sha'])
    main = evidence.api(f'repos/{REPO}/git/ref/heads/main')['object']['sha']
    ancestor(sha, main)
    return pr


def release_ci(sha: str, automatic: bool) -> dict:
    """Verify artifact/audit jobs in one main-push CI attempt for this release.

    Automatic publishing belongs to the still-running CI itself. A manual retry
    may recover from a failed publisher, but never from failed prerequisite jobs
    or by mixing jobs from different attempts or an older successful run.
    """
    if automatic:
        run = evidence.api(f'repos/{REPO}/actions/runs/{int(os.environ["GITHUB_RUN_ID"])}')
        if run['run_attempt'] != int(os.environ['GITHUB_RUN_ATTEMPT']):
            raise ValueError('CI attempt changed during publication')
    else:
        runs = evidence.pages(
            f'repos/{REPO}/actions/workflows/ci.yml/runs?event=push&head_sha={sha}&branch=main',
            'workflow_runs')
        if not runs:
            raise ValueError('No main CI run exists for this stable release')
        run = evidence.api(f'repos/{REPO}/actions/runs/{max(runs, key=lambda item: item["id"])["id"]}')
        if run['status'] != 'completed':
            raise ValueError('Release CI is still active; wait before retrying publication')
    if (run['repository']['full_name'] != REPO or run['path'] != evidence.WORKFLOW
            or run['event'] != 'push' or run['head_branch'] != 'main' or run['head_sha'] != sha):
        raise ValueError('CI does not belong to the selected main release commit')
    evidence.require_jobs(run, REQUIRED_JOBS)
    return run


def copy_blob(sha: str, name: str, destination: Path) -> None:
    """Copy one regular Git blob as inert data; reject symlinks and tree entries."""
    fetch_data(sha)
    entry = hosted.git(ROOT, 'ls-tree', sha, '--', name)
    if not re.fullmatch(r'100644 blob [0-9a-f]{40}\t' + re.escape(name), entry):
        raise ValueError(f'Release data must be a regular Git blob: {name}')
    destination.write_bytes(release.run_git(ROOT, 'show', f'{sha}:{name}', text=False))


def prepare_assets(sha: str, version: str, directory: Path) -> tuple[dict[str, Path], str]:
    """Verify stable/candidate/source/notes and stage four deterministic assets.

    The returned body is exactly the tested version's changelog. Only data files
    are written below directory; no package extraction, build or source execution.
    """
    assets_dir = directory / 'assets'
    assets_dir.mkdir()
    manifest = assets_dir / 'borg-backup-ui.plg'
    package = assets_dir / f'borg-backup-ui-{validate_version(version)}.txz'
    copy_blob(sha, manifest.name, manifest)
    copy_blob(sha, 'releases/' + package.name, package)
    result = pipeline.verify_candidate(manifest, package, 'unraid-legacy', 'stable', version,
                                       release.source_digest(ROOT, sha))
    app = release.run_git(ROOT, 'show', f'{sha}:borg_backup_ui.py')
    if f'APP_VERSION = "{version}"' not in app:
        raise ValueError('Stable application version differs from its manifest')
    snapshot = hosted.snapshot(version)
    if not snapshot:
        raise ValueError('Immutable tested candidate is missing')
    if hosted.git(ROOT, 'rev-parse', f'{snapshot}:releases/{package.name}') != hosted.git(
            ROOT, 'rev-parse', f'{sha}:releases/{package.name}'):
        raise ValueError('Stable package differs from the immutable tested candidate')
    test_manifest = directory / 'borg-backup-ui-test.plg'
    copy_blob(snapshot, test_manifest.name, test_manifest)
    source = evidence.exact_sha(result['provenance'].get('source_commit', ''))
    fetch_data(source)
    hosted.verify_package(test_manifest, package, version, source)
    body = re.search(rf'###{re.escape(version)}###\n(.*?)(?=\n###[^#\n]+###\n|\n\]\]>|\Z)',
                     manifest.read_text(encoding='utf-8'), re.DOTALL).group(1).strip()
    provenance = assets_dir / 'provenance.json'
    provenance.write_text(json.dumps(result['provenance'], indent=2, sort_keys=True) + '\n', encoding='utf-8')
    assets = {path.name: path for path in (manifest, package, provenance)}
    sums = assets_dir / 'SHA256SUMS'
    sums.write_text(''.join(f'{pipeline.sha256(assets[name])}  {name}\n' for name in sorted(assets)), encoding='utf-8')
    assets[sums.name] = sums
    return assets, body


def api_write(method: str, endpoint: str, payload: dict, directory: Path) -> dict:
    """Send structured JSON through the identity-checked writer; no shell quoting."""
    request = directory / 'request.json'
    request.write_text(json.dumps(payload), encoding='utf-8')
    return json.loads(hosted.gh_write('api', '--method', method, endpoint, '--input', str(request)))


def tag_sha(tag: str) -> str | None:
    """Read the lightweight tag without treating API/network errors as absence."""
    lines = hosted.git(ROOT, 'ls-remote', '--refs', 'origin', f'refs/tags/{tag}').splitlines()
    if not lines:
        return None
    if len(lines) != 1:
        raise ValueError('Ambiguous stable tag')
    return evidence.exact_sha(lines[0].split()[0])


def release_metadata(record: dict, version: str, sha: str, body: str) -> None:
    """Reject a release with a different owner, target, title, notes or channel."""
    if (record['author']['login'] != hosted.BOT or record['tag_name'] != 'v' + version
            or record['target_commitish'] != sha or record['name'] != version
            or record['body'] != body or record['prerelease']):
        raise ValueError('Existing GitHub release metadata conflicts with the approved release')


def download_asset(asset_id: int, destination: Path) -> None:
    """Download bytes from the fixed repository asset endpoint for SHA256 checks."""
    with destination.open('wb') as handle:
        result = subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream',
                                 f'repos/{REPO}/releases/assets/{int(asset_id)}'],
                                stdout=handle, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError('Release asset download failed; publication is not verified')


def verify_assets(release_id: int, assets: dict[str, Path], directory: Path,
                  verified: dict[int, str], *, complete: bool) -> set[str]:
    """Verify existing upload owners, names and bytes, caching immutable asset IDs.

    Missing assets are allowed only for an unfinished draft. Extra, duplicate,
    partial or differing assets always fail; this function never deletes them.
    """
    records = list_api(f'repos/{REPO}/releases/{int(release_id)}/assets')
    found = set()
    for record in records:
        name = record['name']
        if name not in assets or name in found:
            raise ValueError('Unexpected or duplicate GitHub release asset')
        found.add(name)
        path = assets[name]
        digest = pipeline.sha256(path)
        if (record['state'] != 'uploaded' or record['size'] != path.stat().st_size
                or record['uploader']['login'] != hosted.BOT
                or (record.get('digest') and record['digest'] != 'sha256:' + digest)):
            raise ValueError(f'GitHub release asset metadata conflicts: {name}')
        asset_id = int(record['id'])
        if verified.get(asset_id) != digest:
            download = directory / f'download-{asset_id}'
            download_asset(asset_id, download)
            if download.stat().st_size != path.stat().st_size or pipeline.sha256(download) != digest:
                raise ValueError(f'GitHub release asset bytes differ: {name}')
            download.unlink()
            verified[asset_id] = digest
    if complete and found != set(assets):
        raise ValueError('Published release is missing required assets')
    return found


def latest_allowed(version: str, records: list) -> bool:
    """Keep a newer published stable version latest during historical backfill."""
    for record in records:
        if record['draft'] or record['prerelease']:
            continue
        tag = record['tag_name']
        if not tag.startswith('v'):
            continue
        try:
            other = validate_version(tag[1:])
        except ValueError:
            continue
        if other > version:
            return False
    return True


def publish(version: str, sha: str, body: str, assets: dict[str, Path], directory: Path) -> dict:
    """Create a protected tag/draft, resume missing uploads and publish once complete.

    A matching published release is a read-only retry. No tag, existing asset or
    published metadata is overwritten. A failure may leave a tag or partial draft
    which the same version can safely resume after the underlying error is fixed.
    """
    tag = 'v' + validate_version(version)
    existing_sha = tag_sha(tag)
    if existing_sha is not None and existing_sha != sha:
        raise ValueError('Stable tag already points to a different commit')
    records = list_api(f'repos/{REPO}/releases')
    matching = [record for record in records if record['tag_name'] == tag]
    if len(matching) > 1:
        raise ValueError('Ambiguous GitHub release for stable tag')
    record = matching[0] if matching else None
    verified = {}
    present = set()
    if record:
        release_metadata(record, version, sha, body)
        if existing_sha != sha:
            raise ValueError('Existing release is missing its protected stable tag')
        present = verify_assets(record['id'], assets, directory, verified, complete=not record['draft'])
        if not record['draft']:
            if not record.get('published_at'):
                raise ValueError('Existing release has no publication timestamp')
            return record
    if existing_sha is None:
        api_write('POST', f'repos/{REPO}/git/refs', {'ref': 'refs/tags/' + tag, 'sha': sha}, directory)
    if tag_sha(tag) != sha:
        raise ValueError('Stable tag verification failed')
    if not record:
        record = api_write('POST', f'repos/{REPO}/releases', {
            'tag_name': tag, 'target_commitish': sha, 'name': version, 'body': body,
            'draft': True, 'prerelease': False, 'make_latest': 'false',
        }, directory)
        record = evidence.api(f'repos/{REPO}/releases/{int(record["id"])}')
        release_metadata(record, version, sha, body)
        if not record['draft']:
            raise ValueError('New GitHub release must remain draft until uploads are verified')
    for name in sorted(set(assets) - present):
        hosted.gh_write('release', 'upload', tag, str(assets[name]), '--repo', REPO)
    verify_assets(record['id'], assets, directory, verified, complete=True)
    # Re-read immediately before making a draft public; never edit changed notes.
    record = evidence.api(f'repos/{REPO}/releases/{int(record["id"])}')
    release_metadata(record, version, sha, body)
    if tag_sha(tag) != sha:
        raise ValueError('Stable tag changed during upload')
    if record['draft']:
        make_latest = latest_allowed(version, list_api(f'repos/{REPO}/releases'))
        api_write('PATCH', f'repos/{REPO}/releases/{int(record["id"])}',
                  {'draft': False, 'make_latest': str(make_latest).lower()}, directory)
    record = evidence.api(f'repos/{REPO}/releases/{int(record["id"])}')
    release_metadata(record, version, sha, body)
    if record['draft'] or not record.get('published_at'):
        raise ValueError('GitHub release publication did not complete')
    verify_assets(record['id'], assets, directory, verified, complete=True)
    return record


def main() -> None:
    """Run the protected automatic publisher or explicitly selected version retry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--automatic', action='store_true')
    args = parser.parse_args()
    controller = trusted_job(args.automatic)
    temporary = ROOT / '.release-tmp'
    temporary.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='github-release-', dir=temporary) as temp:
        directory = Path(temp)
        if args.automatic:
            manifest = directory / 'selected.plg'
            copy_blob(controller, 'borg-backup-ui.plg', manifest)
            version = validate_version(release.manifest_version(manifest))
        else:
            version = validate_version(os.environ.get('RELEASE_VERSION', ''))
        pr = merged_release(version)
        sha = pr['merge_commit_sha']
        if args.automatic and sha != controller:
            raise ValueError('Automatic publication must run on the stable release merge commit')
        run = release_ci(sha, args.automatic)
        assets, body = prepare_assets(sha, version, directory)
        record = publish(version, sha, body, assets, directory)
        summary = (f'GitHub release: {record["html_url"]}\n\nVersion: `{version}`\n\n'
                   f'Release commit: `{sha}` (PR #{pr["number"]})\n\n'
                   f'Artifact/audit CI: https://github.com/{REPO}/actions/runs/{run["id"]}\n\n'
                   'Verified the original package, manifest, provenance and SHA256SUMS. '
                   'No rebuild or repeated source suite; Unraid continues using main.\n')
        print(summary)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as handle:
                handle.write(summary)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'ERROR: {error}') from None
