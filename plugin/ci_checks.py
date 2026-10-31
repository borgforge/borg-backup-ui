#!/usr/bin/env python3
"""Read-only CI quality checks and explicit dependency checks (#671)."""
import argparse
import hashlib
from pathlib import Path
import py_compile
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import release_workflow as release

ROOT = Path(__file__).resolve().parents[1]
INVALID_HOOK_EXAMPLES = {
    ROOT / 'docs/examples/job-hooks/pre-syntax-error.sh',
    ROOT / 'docs/examples/job-hooks/post-syntax-error.sh',
}


def tracked_files() -> list[Path]:
    """List tracked source files, excluding Git history and local test output."""
    return [ROOT / name for name in subprocess.check_output(
        ['git', 'ls-files'], cwd=ROOT, text=True).splitlines()]


def check() -> None:
    """Check source syntax, static errors and bundled Borg integrity; fail fast."""
    for tool in ('node', 'php', 'ruff'):
        if not shutil.which(tool):
            raise RuntimeError(f'Required CI tool is unavailable: {tool}')
    for path in tracked_files():
        if path.suffix == '.py':
            py_compile.compile(str(path), doraise=True)
        elif path.suffix in ('.sh',) or path.name == 'rc.borg_backup_ui':
            if path in INVALID_HOOK_EXAMPLES:
                # #550 ships negative examples for save-time validation. They
                # must still fail parsing, not be silently omitted from checks.
                result = subprocess.run(['bash', '-n', str(path)], capture_output=True)
                if result.returncode == 0:
                    raise RuntimeError(f'Negative syntax fixture unexpectedly parses: {path}')
            else:
                subprocess.run(['bash', '-n', str(path)], check=True)
        elif path.suffix in ('.js', '.cjs'):
            subprocess.run(['node', '--check', str(path)], check=True, stdout=subprocess.DEVNULL)
        elif path.suffix in ('.php', '.page'):
            subprocess.run(['php', '-l', str(path)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['ruff', 'check', '--select', 'E9,F63,F7,F82', 'borg_backup_ui.py',
                    'api', 'runtime/lib', 'runtime/scripts', 'plugin'], cwd=ROOT, check=True)
    verify_borg()


def verify_borg() -> Path:
    """Verify the tracked Borg binary before test execution; return its path."""
    line = (ROOT / 'runtime/bin/borg/SHA256SUMS').read_text().strip()
    expected, name = line.split()
    binary = ROOT / name
    with binary.open('rb') as handle:
        actual = hashlib.file_digest(handle, 'sha256').hexdigest()
    if expected != actual:
        raise RuntimeError('Bundled Borg SHA256 mismatch')
    return binary


def test_dependencies() -> None:
    """Require real Node/browser/Borg tools so missing dependencies cannot skip CI."""
    subprocess.run(['node', '-e', "const fs=require('fs');const {chromium}=require('playwright');if(!fs.existsSync(process.env.BBUI_CHROMIUM||chromium.executablePath()))process.exit(1)"], check=True)
    binary = verify_borg()
    tools = ROOT / '.release-tmp/ci/bin'; tools.mkdir(parents=True, exist_ok=True)
    link = tools / 'borg'
    if not link.exists():
        link.symlink_to(binary)
    subprocess.run([str(binary), '--version'], check=True)


def classify_changes(repo: Path, base: str) -> str:
    """Select source tests or artifact verification from the actual Git delta.

    A release must change manifest/package only, except a version-only app edit
    and consumed note fragments. Mixed source/release changes fail. Missing
    history is fetched read-only by exact SHA; branch names do not grant bypasses.
    """
    if not base or base == '0' * 40:
        return 'source'
    if not re.fullmatch('[0-9a-f]{40}', base):
        raise ValueError('CI base must be an exact Git commit SHA')
    if subprocess.run(['git', 'cat-file', '-e', f'{base}^{{commit}}'], cwd=repo,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        subprocess.run(['git', 'fetch', '--no-tags', '--depth=1', 'origin', base], cwd=repo, check=True)
    changes = [line.split('\t') for line in str(release.run_git(
        repo, 'diff', '--no-renames', '--name-status', base, 'HEAD')).splitlines()]
    names = {row[1] for row in changes}
    packages = {name for name in names if re.fullmatch(r'releases/borg-backup-ui-[^/]+\.txz', name)}
    if 'borg-backup-ui.plg' not in names and not packages:
        return 'source'
    if 'borg-backup-ui.plg' not in names or not packages:
        raise ValueError('Release delta requires both stable manifest and package')
    for status, name in changes:
        if name in {'borg-backup-ui.plg', 'borg_backup_ui.py'} or name in packages:
            continue
        if name.startswith('release-notes/pending/') and status == 'D':
            continue
        raise ValueError(f'Mixed source/release delta is forbidden: {name}')
    if release.source_digest(repo, base) != release.source_digest(repo, 'HEAD'):
        raise ValueError('Release changes deployable source beyond the version')
    return 'artifact'


def verify_ci_release(repo: Path, base: str, compare_test: bool) -> None:
    """Verify a pure release delta without rerunning source tests or publishing.

    PRs also compare bytes against a fetched immutable test snapshot. Main pushes
    validate their committed release; a later rotating test feed is irrelevant.
    """
    if classify_changes(repo, base) != 'artifact':
        raise ValueError('Artifact checks require a pure release delta')
    release.require_clean(repo)
    provenance = release.verify_release_artifacts(repo, base)
    consumed = {item['path']: item['sha256'] for item in provenance.get('release_note_fragments', [])}
    deleted = {name for name in str(release.run_git(
        repo, 'diff', '--no-renames', '--diff-filter=D', '--name-only', base, 'HEAD')).splitlines()
        if name.startswith('release-notes/pending/')}
    if deleted != set(consumed):
        raise ValueError('Deleted note fragments differ from the tested provenance')
    for name, expected in consumed.items():
        original = release.run_git(repo, 'show', f'{base}:{name}', text=False)
        if hashlib.sha256(original).hexdigest() != expected:
            raise ValueError(f'Consumed note fragment differs from tested content: {name}')
    if compare_test:
        subprocess.run(['git', 'fetch', '--no-tags', '--depth=1', 'origin', 'test-channel'], cwd=repo, check=True)
        snapshot = str(release.run_git(repo, 'rev-parse', 'FETCH_HEAD')).strip()
        manifest = ET.fromstring(release.run_git(repo, 'show', f'{snapshot}:borg-backup-ui-test.plg', text=False))
        version = release.manifest_version(repo/'borg-backup-ui.plg')
        if manifest.attrib.get('version') != version:
            raise ValueError('Release version differs from the test snapshot')
        package = repo/'releases'/f'borg-backup-ui-{version}.txz'
        tested = release.run_git(repo, 'show', f'{snapshot}:releases/{package.name}', text=False)
        with package.open('rb') as handle:
            if hashlib.file_digest(handle, 'sha256').digest() != hashlib.sha256(tested).digest():
                raise ValueError('Release package differs from the exact tested bytes')
    print('Release artifact checks passed; no source tests or build repeated.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'test-dependencies', 'classify', 'verify-release'))
    parser.add_argument('--base', default='')
    parser.add_argument('--compare-test', action='store_true')
    args = parser.parse_args()
    if args.command == 'classify':
        print(classify_changes(ROOT, args.base))
    elif args.command == 'verify-release':
        verify_ci_release(ROOT, args.base, args.compare_test)
    else:
        (check if args.command == 'check' else test_dependencies)()
