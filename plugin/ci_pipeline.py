#!/usr/bin/env python3
"""Prepare and verify local CI artifacts; never publish, push or install (#671).

These previews are not release attestations. Existing release entrypoints remain
responsible for pushed-commit checks, user approval and public/private guards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

from build_targets import PLATFORMS, target, validate_version
import release_workflow as release


def sha256(path: Path) -> str:
    """Hash a local artifact using bounded memory."""
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def local_output(repo: Path, output: Path) -> Path:
    """Create a new repository-local preview directory; never overwrite output."""
    output = output.resolve()
    if not output.is_relative_to((repo / '.release-tmp').resolve()):
        raise ValueError('Output must be below repository .release-tmp')
    output.mkdir(parents=True, exist_ok=False)
    return output


def testing_manifest(text: str, version: str) -> str:
    """Render the existing testing channel identity without modifying its feed."""
    spec = target('unraid-legacy', 'testing')
    text = re.sub(r'<!ENTITY pluginURL\s+"[^"]*">', f'<!ENTITY pluginURL "{spec["plugin_url"]}">', text)
    text = re.sub(r'<!ENTITY pkgurl\s+"[^"]*">', f'<!ENTITY pkgurl "{spec["package_url"].format(version=version)}">', text)
    return re.sub(r'description="[^"]*"', 'description="TEST CHANNEL - Web UI for Borg Backup. Install this only on test systems."', text, count=1)


def verify_candidate(manifest: Path, package: Path, platform: str, channel: str,
                     version: str, source_digest: str | None = None) -> dict:
    """Validate channel identity, checksums, version and payload provenance.

    Old legacy manifests with MD5 only remain readable; new previews include
    SHA256. A channel/platform mismatch, corrupted package or wrong source fails.
    No archive is extracted or installed.
    """
    spec = target(platform, channel)
    validate_version(version)
    xml = ET.parse(manifest).getroot()
    if xml.attrib.get('name') != release.NAME or xml.attrib.get('version') != version:
        raise ValueError('Manifest identity/version mismatch')
    if xml.attrib.get('pluginURL') != spec['plugin_url']:
        raise ValueError('Manifest update channel mismatch')
    if release.manifest_md5(manifest) != release.file_md5(package):
        raise ValueError('Package MD5 mismatch')
    installers = [node.findtext('INLINE', '') for node in xml.findall('FILE')
                  if 'package-install-' in node.attrib.get('Name', '')]
    expected_url = spec['package_url'].format(version=version)
    if len(installers) != 1 or f'PACKAGE_URL="{expected_url}"' not in installers[0]:
        raise ValueError('Package download channel mismatch')
    release.verify_manifest_sha256(manifest, package)
    actual_sha = sha256(package)
    provenance = release.package_provenance(package)
    if provenance.get('platform', 'unraid-legacy') != platform:
        raise ValueError('Package platform mismatch')
    if provenance.get('version') != version:
        raise ValueError('Package version mismatch')
    if source_digest and provenance.get('source_digest') != source_digest:
        raise ValueError('Package source digest mismatch')
    notes = re.search(rf'###{re.escape(version)}###\n(.*?)(?=\n###[^#\n]+###\n|\n\]\]>|\Z)',
                      manifest.read_text(), re.DOTALL)
    if not notes or hashlib.sha256(notes.group(1).strip().encode()).hexdigest() != provenance.get('release_notes_sha256'):
        raise ValueError('Manifest release notes mismatch')
    return {'platform': platform, 'channel': channel, 'version': version,
            'package_sha256': actual_sha, 'package_bytes': package.stat().st_size,
            'provenance': provenance, 'published': False}


def write_result(output: Path, manifest: Path, package: Path, result: dict) -> None:
    """Write a review bundle and checksums; no production approval is asserted."""
    artifacts = output / 'artifacts'
    artifacts.mkdir()
    for path in (manifest, package):
        shutil.copy2(path, artifacts / path.name)
    (artifacts / 'candidate.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    files = sorted(artifacts.iterdir())
    (artifacts / 'SHA256SUMS').write_text(''.join(f'{sha256(path)}  {path.name}\n' for path in files))
    print(json.dumps(result, indent=2, sort_keys=True))


def prepare(repo: Path, output: Path, version: str, platform: str) -> None:
    """Build the exact clean HEAD through the shared builder, without publication.

    Intended after CI checks or local preflight. This does not issue the local
    release attestation or bypass the deploy entrypoint's separate requirements.
    """
    target(platform, 'testing')
    validate_version(version)
    release.require_clean(repo)
    head = str(release.run_git(repo, 'rev-parse', 'HEAD')).strip()
    base = str(release.run_git(repo, 'merge-base', 'HEAD', 'origin/main')).strip()
    output = local_output(repo, output)
    digest = release.source_digest(repo, head)
    subprocess.run(['bash', str(repo / 'plugin/build-candidate.sh'), version,
                    head, base, digest, str(output)], cwd=repo, check=True)
    manifest = output / 'borg-backup-ui-test.plg'
    manifest.write_text(testing_manifest((output / 'source/borg-backup-ui.plg').read_text(), version))
    package = output / 'releases' / f'borg-backup-ui-{version}.txz'
    result = verify_candidate(manifest, package, platform, 'testing', version, digest)
    result['source_commit'] = head
    result['approval'] = 'preview-only; not authorized for publication'
    write_result(output, manifest, package, result)


def stable_preview(repo: Path, output: Path, version: str, platform: str) -> None:
    """Prepare stable metadata from an exact test snapshot without rebuilding.

    Requires HEAD == origin/main and matching tested source/notes. Fetching refs
    is read-only; callers must fetch main/test-channel before invoking this.
    The exported source tree is disposable, and no Git refs are changed here.
    """
    target(platform, 'stable')
    validate_version(version)
    release.require_clean(repo)
    head = str(release.run_git(repo, 'rev-parse', 'HEAD')).strip()
    if head != str(release.run_git(repo, 'rev-parse', 'origin/main')).strip():
        raise ValueError('Stable preview requires the exact origin/main commit')
    snapshot = str(release.run_git(repo, 'rev-parse', 'origin/test-channel')).strip()
    output = local_output(repo, output)
    package = output / f'borg-backup-ui-{version}.txz'
    manifest = output / 'borg-backup-ui-test.plg'
    manifest.write_bytes(release.run_git(repo, 'show', f'{snapshot}:borg-backup-ui-test.plg', text=False))
    package.write_bytes(release.run_git(repo, 'show', f'{snapshot}:releases/{package.name}', text=False))
    digest = release.source_digest(repo, head)
    result = verify_candidate(manifest, package, platform, 'testing', version, digest)
    stage = output / 'stable'; stage.mkdir()
    # Only promotion inputs, not retained binary packages, are needed for preview.
    exporter = subprocess.Popen(['git', '-C', str(repo), 'archive', head, '--',
                                 'borg-backup-ui.plg', 'borg_backup_ui.py', 'release-notes/pending'],
                                stdout=subprocess.PIPE)
    try:
        subprocess.run(['tar', '-x', '-C', str(stage)], stdin=exporter.stdout, check=True)
    finally:
        exporter.stdout.close()
        if exporter.wait() != 0:
            raise RuntimeError('Stable source export failed')
    (stage / 'releases').mkdir()
    shutil.copy2(package, stage / 'releases' / package.name)
    release.promote_artifacts(stage, manifest, version, release.file_md5(package), result['provenance'])
    release.verify_release_artifacts(stage, head, repo)
    stable_manifest = stage / 'borg-backup-ui.plg'
    result = verify_candidate(stable_manifest, package, platform, 'stable', version, digest)
    result.update(test_snapshot=snapshot, source_commit=head,
                  approval='preview-only; explicit user approval and release PR required',
                  proposed_tag=f'{platform}/{version}',
                  github_release='not created; asset publication requires a separate reviewed workflow')
    write_result(output, stable_manifest, package, result)


def main() -> None:
    """Validate public/private context and CLI arguments before any build output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'stable-preview'))
    parser.add_argument('--platform', choices=PLATFORMS, default='unraid-legacy')
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    subprocess.run(['python3', str(repo / 'plugin/security_workflow.py'), 'guard-public'], check=True)
    try:
        (prepare if args.command == 'prepare' else stable_preview)(repo, args.output, args.version, args.platform)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'ERROR: {exc}\n')


if __name__ == '__main__':
    main()
