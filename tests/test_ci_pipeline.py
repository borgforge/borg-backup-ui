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
import ci_checks as checks
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


def candidate_files(tmp_path, source_digest='exact'):
    """Make a synthetic package with real vendor/provenance validation inputs."""
    package = tmp_path / 'borg-backup-ui-2026.10.31.1600.txz'
    prefix = 'boot/config/plugins/borg-backup-ui/'
    vendor = b'synthetic vendor content'
    meta = dict(version='test', bundle='apprise-test.tar.xz', sha256=hashlib.sha256(vendor).hexdigest())
    notes = '### Improvements\n\n- Synthetic candidate.'
    provenance = dict(platform='unraid-legacy', version='2026.10.31.1600', source_digest=source_digest,
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
    template = (ROOT/'borg-backup-ui.plg').read_text()
    if digest == 'legacy':
        # The real manifest now declares SHA256. An omitted replacement preserves
        # it intentionally, so model an actual MD5-only legacy input explicitly.
        template = re.sub(r'EXPECTED_SHA256="[^"]*"', 'EXPECTED_SHA256=""', template)
    manifest = release.rewrite_package_installer(template,
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


def test_preview_output_rejects_escaping_temporary_root_symlink(tmp_path):
    repo = tmp_path / 'repo'; repo.mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    (repo/'.release-tmp').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='below repository'):
        ci.local_output(repo, repo/'.release-tmp/candidate')
    assert not (outside/'candidate').exists()


def test_metrics_capture_failure_without_command_arguments(tmp_path):
    path = tmp_path / 'metrics.jsonl'
    assert measure(path, 'failed-check', [sys.executable, '-c', 'raise SystemExit(7)', 'secret-argument']) == 7
    row = json.loads(path.read_text())
    assert row['exit_code'] == 7 and row['seconds'] >= 0
    assert 'secret-argument' not in path.read_text()


def release_fixture(tmp_path):
    """Create a tiny committed source/release pair with real provenance checks."""
    repo = tmp_path/'repo'; repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
    git('init', '-b', 'feature')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    (repo/'borg_backup_ui.py').write_text('APP_VERSION = "old"\nVALUE = 1\n')
    # Keep this historical candidate newer than its fixture baseline regardless
    # of which stable version is currently committed in the real repository.
    manifest = re.sub(r'<!ENTITY version\s+"[^"]*">', '<!ENTITY version "2026.10.30.1200">',
                      (ROOT/'borg-backup-ui.plg').read_text())
    (repo/'borg-backup-ui.plg').write_text(manifest)
    (repo/'release-notes/pending').mkdir(parents=True)
    (repo/'release-notes/pending/README.md').write_text('Keep fragment instructions.\n')
    git('add', '.'); git('commit', '-m', 'Source')
    base = git('rev-parse', 'HEAD')
    output = tmp_path/'candidate'; output.mkdir()
    manifest, package = candidate_files(output, release.source_digest(repo, base))
    (repo/'releases').mkdir()
    (repo/'releases'/package.name).write_bytes(package.read_bytes())
    release.promote_artifacts(repo, manifest, '2026.10.31.1600', release.file_md5(package),
                              release.package_provenance(package))
    git('add', '.'); git('commit', '-m', 'Release')
    return repo, base, git


def test_pure_release_uses_artifact_checks_and_rejects_corruption(tmp_path):
    repo, base, git = release_fixture(tmp_path)
    assert checks.classify_changes(repo, base) == 'artifact'
    checks.verify_ci_release(repo, base, False)
    package = next((repo/'releases').glob('*.txz'))
    package.write_bytes(package.read_bytes()+b'corrupted')
    git('add', '.'); git('commit', '-m', 'Corruption')
    with pytest.raises(RuntimeError, match='MD5'):
        checks.verify_ci_release(repo, base, False)


@pytest.mark.parametrize('path, content', [
    ('borg_backup_ui.py', 'APP_VERSION = "2026.10.31.1600"\nVALUE = 2\n'),
    ('.github/workflows/ci.yml', 'unreviewed workflow change'),
    ('release-notes/pending/new.md', 'untested release note'),
])
def test_release_delta_cannot_hide_source_workflow_or_new_notes(tmp_path, path, content):
    repo, base, git = release_fixture(tmp_path)
    target = repo/path; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git('add', '.'); git('commit', '-m', 'Mixed release')
    with pytest.raises(ValueError, match='[Rr]elease'):
        checks.classify_changes(repo, base)


def test_source_only_delta_keeps_full_checks_even_on_release_named_branch(tmp_path):
    repo, _, git = release_fixture(tmp_path)
    base = git('rev-parse', 'HEAD')
    git('switch', '-c', 'codex/release-name-is-not-authority')
    (repo/'borg_backup_ui.py').write_text('APP_VERSION = "2026.10.31.1600"\nVALUE = 2\n')
    git('add', '.'); git('commit', '-m', 'Source change')
    assert checks.classify_changes(repo, base) == 'source'


def test_release_cannot_delete_untested_note_fragments(tmp_path):
    repo, base, git = release_fixture(tmp_path)
    (repo/'release-notes/pending/README.md').unlink()
    git('add', '.'); git('commit', '-m', 'Unexpected deletion')
    assert checks.classify_changes(repo, base) == 'artifact'
    with pytest.raises(ValueError, match='Deleted note fragments'):
        checks.verify_ci_release(repo, base, False)


def test_release_pr_must_match_immutable_test_snapshot_bytes(tmp_path):
    """Exercise real fetch/verification against a repository-local fake remote."""
    repo, base, git = release_fixture(tmp_path)
    remote = tmp_path/'remote.git'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
    snapshot = tmp_path/'snapshot'; snapshot.mkdir()
    def snapshot_git(*args):
        return subprocess.check_output(['git', '-C', str(snapshot), *args], text=True).strip()
    snapshot_git('init', '-b', 'test-channel')
    snapshot_git('config', 'user.name', 'Fixture')
    snapshot_git('config', 'user.email', 'fixture@example.invalid')
    (snapshot/'borg-backup-ui-test.plg').write_bytes((tmp_path/'candidate/borg-backup-ui-test.plg').read_bytes())
    (snapshot/'releases').mkdir()
    package = next((tmp_path/'candidate').glob('*.txz'))
    tested_package = snapshot/'releases'/package.name
    tested_package.write_bytes(package.read_bytes())
    snapshot_git('add', '.'); snapshot_git('commit', '-m', 'Test snapshot')
    snapshot_git('tag', 'test-candidates/2026.10.31.1600')
    snapshot_git('push', str(remote), 'test-channel', 'refs/tags/test-candidates/2026.10.31.1600')
    git('remote', 'add', 'origin', str(remote))
    checks.verify_ci_release(repo, base, True)
    tested_package.write_bytes(b'different package bytes')
    snapshot_git('add', '.'); snapshot_git('commit', '-m', 'Changed test snapshot')
    snapshot_git('push', str(remote), 'test-channel')
    # A later rotating feed must not change the stable candidate's identity.
    checks.verify_ci_release(repo, base, True)
    (repo/'releases'/package.name).write_bytes(b'tampered stable bytes')
    git('add', '.'); git('commit', '-m', 'Corrupted stable bytes')
    with pytest.raises(RuntimeError, match='MD5'):
        checks.verify_ci_release(repo, base, True)


def test_workflows_isolate_publication_authority_to_protected_main_jobs():
    """Keep PR/build jobs read-only and bot secrets inside protected main jobs."""
    for path in (ROOT / '.github/workflows').glob('*.yml'):
        text = path.read_text()
        workflow = yaml.load(text, Loader=yaml.BaseLoader)
        assert workflow['permissions'].get('contents') == 'read', path
        assert set(workflow['permissions'].values()) == {'read'}, path
        assert not {'pull_request_target', 'workflow_run'} & workflow['on'].keys(), path
        assert 'secrets: inherit' not in text, path
        for job_id, job in workflow['jobs'].items():
            if 'secrets.' in str(job):
                if path.name == 'ci.yml':
                    assert job_id == 'github-release'
                    assert job['environment'] == 'release-publish'
                    assert set(job['needs']) == {'plan', 'result'}
                elif path.name in ('apprise-monitor.yml', 'python-monitor.yml'):
                    assert set(workflow['on']) == {'schedule', 'workflow_dispatch'}
                    assert job_id == 'monitor'
                    assert job['environment'] == 'dependency-monitor'
                    assert job['if'] == ("github.ref == 'refs/heads/main' && "
                                         "(github.event_name == 'schedule' || github.event_name == 'workflow_dispatch')")
                else:
                    assert set(workflow['on']) == {'workflow_dispatch'}
                    assert job['environment'] in {'testing', 'stable', 'release-publish'}
                for step in job['steps']:
                    if step.get('uses', '').startswith('actions/checkout@'):
                        assert 'ref' not in step['with']  # guarded push/dispatch main, never PR
                assert 'refs/heads/main' in text
            else:
                assert 'environment' not in job
            for step in job.get('steps', []):
                action = step.get('uses', '')
                if action:
                    assert re.fullmatch(r'actions/[\w-]+@[0-9a-f]{40}', action), action
                if action.startswith('actions/checkout@'):
                    assert step['with']['persist-credentials'] == 'false'
                if action.startswith('actions/upload-artifact@'):
                    assert 'github.run_attempt' in step['with']['name'], 'Reruns must not collide with earlier artifacts'
    ci_workflow = yaml.load((ROOT/'.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
    assert ci_workflow['on']['push']['branches'] == ['main']
    assert ci_workflow['concurrency']['cancel-in-progress'] == "${{ github.event_name == 'pull_request' }}"
    publisher = yaml.load((ROOT/'.github/workflows/github-release.yml').read_text(), Loader=yaml.BaseLoader)
    assert publisher['jobs']['publish']['if'] == "github.ref == 'refs/heads/main'"
    assert publisher['jobs']['publish']['concurrency'] == ci_workflow['jobs']['github-release']['concurrency']
    assert publisher['jobs']['publish']['concurrency']['cancel-in-progress'] == 'false'
    testing = yaml.load((ROOT/'.github/workflows/testing-release.yml').read_text(), Loader=yaml.BaseLoader)
    assert 'secrets.' not in str(testing['jobs']['build'])
    assert 'checks.yml' not in str(testing)  # the resolver reuses/requests CI evidence
    assert 'push' not in testing['on']


def publisher_condition_matches(condition, context, *, cancelled, source_result):
    """Evaluate the publisher's conjunction-only condition for policy tests.

    Supports context/string equality and status predicates, rejecting other
    syntax. Models GitHub's implicit success gate over the dependency chain
    when no status function is present; this is not a general Actions runner.
    """
    condition = condition.strip().removeprefix('${{').removesuffix('}}').strip()
    ancestor_results = [context['needs.plan.result'], context['needs.result.result'], source_result]
    success = not cancelled and all(result == 'success' for result in ancestor_results)
    statuses = {'always()': True, 'cancelled()': cancelled, '!cancelled()': not cancelled,
                'success()': success, 'failure()': 'failure' in ancestor_results}
    clauses = [clause.strip() for clause in condition.split('&&')]
    if not any(clause in statuses for clause in clauses) and not success:
        return False
    outcomes = []
    for clause in clauses:
        if clause in statuses:
            outcomes.append(statuses[clause])
        else:
            match = re.fullmatch(r"([\w.]+)\s*==\s*'([^']*)'", clause)
            assert match, f'Unsupported publisher predicate: {clause}'
            key, expected = match.groups()
            outcomes.append(context[key] == expected)
    return all(outcomes)


@pytest.mark.parametrize('source_result', ['skipped', 'success'])
@pytest.mark.parametrize('overrides,cancelled,expected', [
    pytest.param({}, False, True, id='successful-release'),
    pytest.param({}, True, False, id='cancelled-run'),
    *[pytest.param({f'needs.{job}.result': result}, False, False, id=f'{job}-{result}')
      for job in ('plan', 'result') for result in ('failure', 'cancelled', 'skipped', '')],
    *[pytest.param({'github.event_name': event}, False, False, id=event)
      for event in ('pull_request', 'workflow_dispatch', 'pull_request_target')],
    *[pytest.param({'github.ref': ref}, False, False, id=ref)
      for ref in ('refs/heads/codex/feature', 'refs/pull/695/merge', 'refs/tags/v2026.11.03.1237')],
    *[pytest.param({'needs.plan.outputs.mode': mode}, False, False, id=f'mode-{mode}')
      for mode in ('source', '', 'unknown')],
])
def test_automatic_publisher_condition(overrides, cancelled, expected, source_result):
    """Exercise the actual YAML guard, including skipped source-test ancestors (#696)."""
    workflow = yaml.load((ROOT / '.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
    context = {'github.event_name': 'push', 'github.ref': 'refs/heads/main',
               'needs.plan.outputs.mode': 'artifact', 'needs.plan.result': 'success',
               'needs.result.result': 'success', **overrides}
    assert publisher_condition_matches(workflow['jobs']['github-release']['if'], context,
                                       cancelled=cancelled, source_result=source_result) is expected
