"""Non-publishing candidate boundaries, channel integrity and CI policy (#671)."""
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin'))
import build_targets as targets
import ci_pipeline as ci
import release_workflow as release
from build_metrics import measure


@pytest.mark.parametrize('channel', targets.CHANNELS)
def test_unimplemented_generation_cannot_fall_back(channel):
    with pytest.raises(ValueError, match='blocked'):
        targets.target('unraid-8', channel)
    assert targets.target('unraid-legacy', channel)['channel'] == channel


@pytest.mark.parametrize('version', ['8.0.0', '8.0.0-beta.1', '9.1', 'unknown'])
def test_legacy_host_gate_rejects_next_generation(version):
    with pytest.raises(ValueError):
        targets.require_host_generation('unraid-legacy', version)


@pytest.mark.parametrize('version', ['7.4.0-beta.2', '6.12.5', '7.2'])
def test_host_gate_accepts_legacy_and_rejects_next_adapter(version):
    targets.require_host_generation('unraid-legacy', version)
    with pytest.raises(ValueError):
        targets.require_host_generation('unraid-8', version)


@pytest.mark.parametrize('version', ['2026.13.01.1200', '2026.10.01.2400', '../../evil', '2026.1.1.1200'])
def test_invalid_version_cannot_become_a_path(version):
    with pytest.raises(ValueError):
        targets.validate_version(version)


def candidate_files(tmp_path):
    """Make a synthetic package with real vendor/provenance validation inputs."""
    package = tmp_path / 'borg-backup-ui-2026.10.31.1600.txz'
    prefix = 'boot/config/plugins/borg-backup-ui/'
    vendor = b'synthetic vendor content'
    meta = dict(version='test', bundle='apprise-test.tar.xz', sha256=hashlib.sha256(vendor).hexdigest())
    notes = '### Improvements\n\n- Synthetic candidate.'
    provenance = dict(platform='unraid-legacy', version='2026.10.31.1600', source_digest='exact',
                      release_notes_sha256=hashlib.sha256(notes.encode()).hexdigest())
    payload = {name: b'fixture' for name in release.EXPECTED_PACKAGE_MEMBERS}
    payload[release.PROVENANCE_MEMBER] = json.dumps(provenance).encode()
    payload[prefix+'runtime/vendor-bundles/apprise-vendor.json'] = json.dumps(meta).encode()
    payload[prefix+'runtime/vendor-bundles/apprise-test.tar.xz'] = vendor
    with tarfile.open(package, 'w:xz') as archive:
        for name, content in payload.items():
            member = tarfile.TarInfo(name); member.size = len(content); member.mode = 0o644
            archive.addfile(member, io.BytesIO(content))
    manifest = tmp_path / 'borg-backup-ui-test.plg'
    text = (ROOT / 'borg-backup-ui.plg').read_text()
    text = re.sub(r'<!ENTITY version\s+"[^"]*">', '<!ENTITY version "2026.10.31.1600">', text)
    text = release.replace_changelog_block(text, '2026.10.31.1600', notes)
    text = release.rewrite_package_installer(text, release.file_md5(package), ci.sha256(package))
    manifest.write_text(ci.testing_manifest(text, '2026.10.31.1600'))
    return manifest, package


def test_candidate_rejects_wrong_channel_source_or_checksum(tmp_path):
    manifest, package = candidate_files(tmp_path)
    result = ci.verify_candidate(manifest, package, 'unraid-legacy', 'testing', '2026.10.31.1600', 'exact')
    assert result['published'] is False
    with pytest.raises(ValueError, match='update channel'):
        ci.verify_candidate(manifest, package, 'unraid-legacy', 'stable', '2026.10.31.1600')
    with pytest.raises(ValueError, match='source digest'):
        ci.verify_candidate(manifest, package, 'unraid-legacy', 'testing', '2026.10.31.1600', 'other')
    manifest.write_text(manifest.read_text().replace(ci.sha256(package), '0'*64))
    with pytest.raises(RuntimeError, match='SHA256'):
        ci.verify_candidate(manifest, package, 'unraid-legacy', 'testing', '2026.10.31.1600')
    package.write_bytes(package.read_bytes()+b'tampered')
    with pytest.raises(ValueError, match='MD5'):
        ci.verify_candidate(manifest, package, 'unraid-legacy', 'testing', '2026.10.31.1600')


def test_candidate_rejects_changed_notes_and_malformed_sha256(tmp_path):
    manifest, package = candidate_files(tmp_path)
    original = manifest.read_text()
    manifest.write_text(original.replace('Synthetic candidate.', 'Different notes.'))
    with pytest.raises(ValueError, match='release notes'):
        ci.verify_candidate(manifest, package, 'unraid-legacy', 'testing', '2026.10.31.1600')
    manifest.write_text(original.replace(ci.sha256(package), 'invalid'))
    with pytest.raises(RuntimeError, match='SHA256 is malformed'):
        ci.verify_candidate(manifest, package, 'unraid-legacy', 'testing', '2026.10.31.1600')


@pytest.mark.parametrize('cached', [False, True])
@pytest.mark.parametrize('digest', ['valid', 'wrong', 'legacy'])
def test_installer_checks_sha256_for_download_and_cache(tmp_path, cached, digest):
    """Execute only real download/cache functions, with local data and fake curl."""
    content = b'isolated package fixture'
    package = tmp_path / 'cached.txz'
    (tmp_path / 'download.txz').write_bytes(content)
    if cached:
        package.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest() if digest == 'valid' else '0'*64
    if digest == 'legacy':
        checksum = ''
    manifest = release.rewrite_package_installer((ROOT/'borg-backup-ui.plg').read_text(),
                                                hashlib.md5(content).hexdigest(), checksum)
    xml = ET.fromstring(manifest)
    script = next(node.findtext('INLINE') for node in xml.findall('FILE')
                  if 'package-install-' in node.attrib.get('Name', ''))
    # Definitions only: never call install/remove, extract to /, or touch a host path.
    script = script.split('\nmkdir -p "${PLUGIN_DIR}"\n', 1)[0] + '''
FIXTURE="$1"
PACKAGE_INSTALL_SCRIPT="$FIXTURE/unused-installer.sh"
PACKAGE_FILE="$FIXTURE/cached.txz"
PACKAGE_TMP="$FIXTURE/cached.tmp"
curl() { touch "$FIXTURE/download-called"; cp "$FIXTURE/download.txz" "$PACKAGE_TMP"; }
ensure_package_file
'''
    result = subprocess.run(['bash', '-c', script, 'fixture', str(tmp_path)],
                            capture_output=True, text=True)
    assert (result.returncode == 0) == (digest != 'wrong'), result.stdout + result.stderr
    assert (tmp_path/'download-called').exists() == (not cached or digest == 'wrong')
    assert not (tmp_path/'cached.tmp').exists()
    if digest == 'wrong' and not cached:
        assert not package.exists()
    else:
        assert package.read_bytes() == content


def test_preview_output_never_overwrites_or_leaves_repository(tmp_path):
    repo = tmp_path / 'repo'; repo.mkdir()
    with pytest.raises(ValueError, match='below repository'):
        ci.local_output(repo, tmp_path / 'outside')
    output = ci.local_output(repo, repo / '.release-tmp/candidate')
    with pytest.raises(FileExistsError):
        ci.local_output(repo, output)


def test_metrics_capture_failure_without_command_arguments(tmp_path):
    path = tmp_path / 'metrics.jsonl'
    assert measure(path, 'failed-check', [sys.executable, '-c', 'raise SystemExit(7)', 'secret-argument']) == 7
    row = json.loads(path.read_text())
    assert row['exit_code'] == 7 and row['seconds'] >= 0
    assert 'secret-argument' not in path.read_text()


def test_public_workflows_have_no_publication_authority():
    """Reject privilege regressions and mutable third-party actions in all workflows."""
    for path in (ROOT / '.github/workflows').glob('*.yml'):
        text = path.read_text()
        workflow = yaml.load(text, Loader=yaml.BaseLoader)
        assert workflow['permissions'] == {'contents': 'read'}, path
        assert not {'pull_request_target', 'workflow_run'} & workflow['on'].keys(), path
        assert 'secrets.' not in text and 'secrets: inherit' not in text, path
        assert not re.search(r'\bgit push\b|\bgh release\b|\./plugin/(deploy-test|promote-release)', text), path
        for job in workflow['jobs'].values():
            assert 'environment' not in job  # Activation needs a separate reviewed change.
            for step in job.get('steps', []):
                action = step.get('uses', '')
                if action:
                    assert re.fullmatch(r'actions/[\w-]+@[0-9a-f]{40}', action), action
                if action.startswith('actions/checkout@'):
                    assert step['with']['persist-credentials'] == 'false'
    ci_workflow = yaml.load((ROOT/'.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
    assert ci_workflow['on']['push']['branches'] == ['main']
    assert 'push' not in yaml.load((ROOT/'.github/workflows/testing-release.yml').read_text(), Loader=yaml.BaseLoader)['on']
