"""Stable GitHub publication gates, exact artifacts and resumable uploads (#685)."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
import github_release as pub

SHA = 'a' * 40
OTHER = 'b' * 40
VERSION = '2026.11.02.1337'
BODY = '### Improvements\n\n- Tested feature. Contributed by [JonaxScript](https://github.com/JonaxScript). (#670)'


def environment(monkeypatch, automatic=False):
    workflow = 'ci.yml' if automatic else 'github-release.yml'
    values = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': pub.REPO,
              'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': SHA,
              'GITHUB_EVENT_NAME': 'push' if automatic else 'workflow_dispatch',
              'GITHUB_WORKFLOW_REF': f'{pub.REPO}/.github/workflows/{workflow}@refs/heads/main',
              'BBUI_ENVIRONMENT': 'release-publish', 'GITHUB_RUN_ID': '12', 'GITHUB_RUN_ATTEMPT': '1'}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(pub.security, 'guard_public', lambda *_: None)
    monkeypatch.setattr(pub.hosted, 'git', lambda *_: SHA)
    monkeypatch.setattr(pub.evidence, 'api', lambda _: {'object': {'sha': SHA}})


@pytest.mark.parametrize('automatic', [False, True])
def test_only_reviewed_main_controller_can_publish(monkeypatch, automatic):
    environment(monkeypatch, automatic)
    assert pub.trusted_job(automatic) == SHA
    for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_REPOSITORY', 'fork/project'),
                       ('GITHUB_REF', 'refs/pull/42/merge'), ('GITHUB_EVENT_NAME', 'pull_request'),
                       ('GITHUB_WORKFLOW_REF', 'unreviewed'), ('BBUI_ENVIRONMENT', 'testing')]:
        with monkeypatch.context() as altered:
            altered.setenv(key, value)
            with pytest.raises(RuntimeError, match='protected main'):
                pub.trusted_job(automatic)
    monkeypatch.setattr(pub.hosted, 'git', lambda *_: OTHER)
    with pytest.raises(RuntimeError, match='checkout differs'):
        pub.trusted_job(automatic)


@pytest.mark.parametrize('status,base,allowed', [('ahead', SHA, True), ('identical', SHA, True),
                                              ('behind', SHA, False), ('diverged', OTHER, False),
                                              ('ahead', OTHER, False)])
def test_main_may_advance_but_unrelated_commits_cannot_publish(monkeypatch, status, base, allowed):
    monkeypatch.setattr(pub.evidence, 'api', lambda _: {
        'status': status, 'base_commit': {'sha': SHA}, 'merge_base_commit': {'sha': base}})
    if allowed:
        pub.ancestor(SHA, OTHER)
    else:
        with pytest.raises(ValueError, match='not on main'):
            pub.ancestor(SHA, OTHER)


def merged_pr(monkeypatch):
    pr = {'number': 42, 'merged_at': '2026-11-02T12:00:00Z', 'merged': True, 'state': 'closed',
          'user': {'login': pub.hosted.BOT}, 'merge_commit_sha': SHA,
          'base': {'ref': 'main', 'repo': {'full_name': pub.REPO}},
          'head': {'ref': 'codex/release-' + VERSION, 'repo': {'full_name': pub.REPO}}}
    monkeypatch.setattr(pub, 'list_api', lambda _: [pr])
    monkeypatch.setattr(pub.evidence, 'api', lambda endpoint: (
        {'object': {'sha': SHA}} if '/git/ref/' in endpoint else pr))
    return pr


def test_only_merged_bot_release_pr_can_authorize_version(monkeypatch):
    pr = merged_pr(monkeypatch)
    assert pub.merged_release(VERSION)['merge_commit_sha'] == SHA
    for path, value in [('merged', False), ('state', 'open')]:
        old = pr[path]; pr[path] = value
        with pytest.raises(ValueError, match='approval'):
            pub.merged_release(VERSION)
        pr[path] = old
    pr['user']['login'] = 'TheTwist76'
    with pytest.raises(ValueError, match='identity'):
        pub.merged_release(VERSION)
    pr['user']['login'] = pub.hosted.BOT
    pr['head']['repo'] = None
    with pytest.raises(ValueError, match='identity'):
        pub.merged_release(VERSION)
    pr['merged_at'] = None
    with pytest.raises(ValueError, match='exactly one merged'):
        pub.merged_release(VERSION)


def ci_run(monkeypatch):
    run = {'id': 12, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'failure',
           'repository': {'full_name': pub.REPO}, 'path': pub.evidence.WORKFLOW,
           'event': 'push', 'head_branch': 'main', 'head_sha': SHA}
    jobs = [{'name': name, 'conclusion': 'success'} for name in sorted(pub.REQUIRED_JOBS)]
    jobs.append({'name': 'Publish GitHub release', 'conclusion': 'failure'})
    def api(endpoint):
        if '/attempts/' in endpoint:
            assert '/attempts/1/jobs?' in endpoint
            return {'jobs': jobs}
        if '/workflows/' in endpoint:
            return {'workflow_runs': [run, dict(run, id=11, conclusion='success')]}
        return run
    monkeypatch.setattr(pub.evidence, 'api', api)
    monkeypatch.setenv('GITHUB_RUN_ID', '12')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '1')
    return run, jobs


def test_retry_accepts_publisher_failure_but_never_failed_prerequisites(monkeypatch):
    run, jobs = ci_run(monkeypatch)
    assert pub.release_ci(SHA, False)['id'] == 12
    jobs[0]['conclusion'] = 'failure'
    with pytest.raises(ValueError, match='Required CI job'):
        pub.release_ci(SHA, False)
    jobs[0]['conclusion'] = 'success'
    jobs.append(jobs[0].copy())
    with pytest.raises(ValueError, match='Required CI job'):
        pub.release_ci(SHA, False)


def test_automatic_publisher_checks_current_attempt_while_ci_is_running(monkeypatch):
    run, _ = ci_run(monkeypatch)
    run['status'] = 'in_progress'; run['conclusion'] = None
    assert pub.release_ci(SHA, True)['id'] == 12
    with pytest.raises(ValueError, match='still active'):
        pub.release_ci(SHA, False)
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    with pytest.raises(ValueError, match='attempt changed'):
        pub.release_ci(SHA, True)


@pytest.mark.parametrize('field,value', [('event', 'pull_request'), ('head_branch', 'feature'),
                                       ('head_sha', OTHER), ('path', 'other.yml'),
                                       ('repository', {'full_name': 'fork/project'})])
def test_wrong_ci_identity_never_authorizes_publication(monkeypatch, field, value):
    run, _ = ci_run(monkeypatch)
    run[field] = value
    with pytest.raises(ValueError, match='selected main release'):
        pub.release_ci(SHA, False)


def artifact_repo(tmp_path, monkeypatch):
    """Build inert test blobs with real source/note/package verification."""
    from test_ci_pipeline import candidate_files
    repo = tmp_path / 'repo'; repo.mkdir()
    def git(*args, input=None):
        return subprocess.check_output(['git', '-C', str(repo), *args], input=input, text=True).strip()
    git('init', '-b', 'main')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    (repo / 'borg_backup_ui.py').write_text('APP_VERSION = "old"\nVALUE = 1\n')
    (repo / 'borg-backup-ui.plg').write_text((pub.ROOT / 'borg-backup-ui.plg').read_text())
    notes_dir = repo / 'release-notes/pending'; notes_dir.mkdir(parents=True)
    (notes_dir / '670.md').write_text('### Improvements\n\n- Synthetic candidate.\n')
    git('add', '.'); git('commit', '-m', 'Source')
    source = git('rev-parse', 'HEAD')
    build = tmp_path / 'build'; build.mkdir()
    manifest, package = candidate_files(build, pub.release.source_digest(repo, source))
    with tarfile.open(package, 'r:xz') as archive:
        payload = {member.name: (member, archive.extractfile(member).read()) for member in archive}
    member, data = payload[pub.release.PROVENANCE_MEMBER]
    provenance = json.loads(data)
    provenance.update(source_commit=source, release_note_fragments=pub.release.rendered_release_notes(repo)[1])
    payload[member.name] = (member, json.dumps(provenance).encode())
    with tarfile.open(package, 'w:xz') as archive:
        for member, data in payload.values():
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    manifest.write_text(pub.release.rewrite_package_installer(
        manifest.read_text(), pub.release.file_md5(package), pub.pipeline.sha256(package)))
    (repo / 'releases').mkdir()
    (repo / 'releases' / package.name).write_bytes(package.read_bytes())
    version = '2026.10.31.1600'
    pub.release.promote_artifacts(repo, manifest, version, pub.release.file_md5(package), provenance)
    git('add', '.'); git('commit', '-m', 'Stable release')
    sha = git('rev-parse', 'HEAD')
    test_blob = git('hash-object', '-w', '--stdin', input=manifest.read_text())
    tree = git('mktree', input=f'100644 blob {test_blob}\t{manifest.name}\n040000 tree {git("rev-parse", "HEAD:releases")}\treleases\n')
    snapshot = git('commit-tree', tree, input='Test snapshot\n')
    monkeypatch.setattr(pub, 'ROOT', repo)
    monkeypatch.setattr(pub.hosted, 'ROOT', repo)
    monkeypatch.setattr(pub.hosted, 'snapshot', lambda _: snapshot)
    return repo, sha, version, package, git


def test_assets_are_original_bytes_and_exact_tested_notes(tmp_path, monkeypatch):
    repo, sha, version, package, git = artifact_repo(tmp_path, monkeypatch)
    output = tmp_path / 'output'; output.mkdir()
    assets, body = pub.prepare_assets(sha, version, output)
    assert body == '### Improvements\n\n- Synthetic candidate.'
    assert assets[package.name].read_bytes() == package.read_bytes()
    assert assets['borg-backup-ui.plg'].read_bytes() == (repo / 'borg-backup-ui.plg').read_bytes()
    assert json.loads(assets['provenance.json'].read_text()) == pub.release.package_provenance(package)
    assert len(assets) == 4
    for line in assets['SHA256SUMS'].read_text().splitlines():
        digest, name = line.split()
        assert digest == pub.pipeline.sha256(assets[name])
    assert git('status', '--porcelain') == ''


@pytest.mark.parametrize('tamper', ['notes', 'package', 'symlink', 'candidate', 'source'])
def test_altered_release_data_cannot_be_published(tmp_path, monkeypatch, tamper):
    repo, _, version, package, git = artifact_repo(tmp_path, monkeypatch)
    manifest = repo / 'borg-backup-ui.plg'
    if tamper == 'notes':
        manifest.write_text(manifest.read_text().replace('Synthetic candidate.', 'Untested notes.'))
    elif tamper == 'package':
        (repo / 'releases' / package.name).write_bytes(b'wrong bytes')
    elif tamper == 'symlink':
        manifest.unlink(); manifest.symlink_to('borg_backup_ui.py')
    elif tamper == 'candidate':
        monkeypatch.setattr(pub.hosted, 'snapshot', lambda _: None)
    else:
        (repo / 'borg_backup_ui.py').write_text(f'APP_VERSION = "{version}"\nVALUE = 2\n')
    git('add', '.'); git('commit', '--allow-empty', '-m', 'Changed release data')
    output = tmp_path / 'output'; output.mkdir()
    with pytest.raises((ValueError, RuntimeError)):
        pub.prepare_assets(git('rev-parse', 'HEAD'), version, output)


def remote(tmp_path, monkeypatch):
    """Simulate GitHub at read/write boundaries, including uploaded bytes."""
    assets = {}
    for name in ('borg-backup-ui.plg', f'borg-backup-ui-{VERSION}.txz', 'provenance.json', 'SHA256SUMS'):
        path = tmp_path / name; path.write_bytes(('expected ' + name).encode())
        assets[name] = path
    state = {'tag': None, 'release': None, 'assets': [], 'bytes': {}, 'writes': [], 'others': []}
    def list_api(endpoint):
        if '/assets' in endpoint:
            return copy.deepcopy(state['assets'])
        return ([copy.deepcopy(state['release'])] if state['release'] else []) + state['others']
    def write(method, endpoint, payload, _):
        state['writes'].append((method, endpoint, payload.copy()))
        if endpoint.endswith('/git/refs'):
            assert state['tag'] is None
            state['tag'] = payload['sha']
            return {'object': {'sha': state['tag']}}
        if method == 'POST':
            assert state['release'] is None
            state['release'] = dict(payload, id=21, author={'login': pub.hosted.BOT},
                                    html_url='https://example.invalid/release', published_at=None)
        else:
            assert state['release']['draft']
            assert len(state['assets']) == 4
            state['release'].update(payload, published_at='2026-11-02T15:00:00Z')
        return copy.deepcopy(state['release'])
    def upload(*args):
        assert args[:3] == ('release', 'upload', 'v' + VERSION)
        assert '--clobber' not in args
        path = Path(args[3])
        state['writes'].append(('upload', path.name))
        if state.get('fail_upload') == path.name:
            raise RuntimeError('Interrupted upload')
        assert path.name not in {item['name'] for item in state['assets']}
        asset_id = len(state['assets']) + 30
        state['assets'].append({'id': asset_id, 'name': path.name, 'size': path.stat().st_size,
                                'digest': 'sha256:' + pub.pipeline.sha256(path), 'state': 'uploaded',
                                'uploader': {'login': pub.hosted.BOT}})
        state['bytes'][asset_id] = path.read_bytes()
    monkeypatch.setattr(pub, 'list_api', list_api)
    monkeypatch.setattr(pub, 'tag_sha', lambda _: state['tag'])
    monkeypatch.setattr(pub, 'api_write', write)
    monkeypatch.setattr(pub.hosted, 'gh_write', upload)
    monkeypatch.setattr(pub.evidence, 'api', lambda _: copy.deepcopy(state['release']))
    monkeypatch.setattr(pub, 'download_asset', lambda asset_id, path: path.write_bytes(state['bytes'][asset_id]))
    return state, assets


def test_complete_release_is_published_after_verified_uploads_and_retry_is_read_only(tmp_path, monkeypatch):
    state, assets = remote(tmp_path, monkeypatch)
    result = pub.publish(VERSION, SHA, BODY, assets, tmp_path)
    assert state['tag'] == SHA
    assert result['body'] == BODY and result['draft'] is False
    assert state['writes'][-1][2] == {'draft': False, 'make_latest': 'true'}
    before = state['writes'].copy()
    pub.publish(VERSION, SHA, BODY, assets, tmp_path)
    assert state['writes'] == before


@pytest.mark.parametrize('tag_only', [False, True])
def test_interrupted_draft_or_tag_resumes_without_reuploading_existing_files(tmp_path, monkeypatch, tag_only):
    state, assets = remote(tmp_path, monkeypatch)
    if tag_only:
        state['tag'] = SHA
    state['fail_upload'] = 'borg-backup-ui.plg'
    with pytest.raises(RuntimeError, match='Interrupted'):
        pub.publish(VERSION, SHA, BODY, assets, tmp_path)
    assert state['release']['draft'] is True
    existing = {item['name'] for item in state['assets']}
    state['writes'].clear(); state.pop('fail_upload')
    pub.publish(VERSION, SHA, BODY, assets, tmp_path)
    assert {write[1] for write in state['writes'] if write[0] == 'upload'} == set(assets) - existing
    assert not any(write[0] == 'POST' for write in state['writes'])


@pytest.mark.parametrize('tamper', ['tag', 'author', 'body', 'target', 'extra', 'missing', 'size', 'uploader', 'bytes', 'partial', 'timestamp'])
def test_conflicting_published_releases_fail_without_any_writes(tmp_path, monkeypatch, tamper):
    state, assets = remote(tmp_path, monkeypatch)
    pub.publish(VERSION, SHA, BODY, assets, tmp_path)
    state['writes'].clear()
    if tamper == 'tag':
        state['tag'] = OTHER
    elif tamper == 'author':
        state['release']['author']['login'] = 'TheTwist76'
    elif tamper == 'body':
        state['release']['body'] = 'different notes'
    elif tamper == 'target':
        state['release']['target_commitish'] = OTHER
    elif tamper == 'extra':
        state['assets'].append(dict(state['assets'][0], name='unexpected'))
    elif tamper == 'missing':
        state['assets'].pop()
    elif tamper == 'size':
        state['assets'][0]['size'] += 1
    elif tamper == 'uploader':
        state['assets'][0]['uploader']['login'] = 'someone-else'
    elif tamper == 'bytes':
        state['bytes'][state['assets'][0]['id']] = b'corrupted download'
    elif tamper == 'timestamp':
        state['release']['published_at'] = None
    else:
        state['assets'][0]['state'] = 'starter'
    with pytest.raises(ValueError):
        pub.publish(VERSION, SHA, BODY, assets, tmp_path)
    assert state['writes'] == []


def test_older_backfill_does_not_replace_newer_latest(tmp_path, monkeypatch):
    state, assets = remote(tmp_path, monkeypatch)
    state['others'] = [{'tag_name': 'v2026.11.03.1200', 'draft': False, 'prerelease': False}]
    pub.publish(VERSION, SHA, BODY, assets, tmp_path)
    assert state['writes'][-1][2]['make_latest'] == 'false'


def test_structured_write_still_checks_bot_identity_before_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(pub.evidence, 'api', lambda _: {'login': 'TheTwist76'})
    monkeypatch.setattr(pub.hosted.subprocess, 'run', lambda *_a, **_k: pytest.fail('Unauthorized write'))
    with pytest.raises(RuntimeError, match='borg-codex-bot'):
        pub.api_write('POST', f'repos/{pub.REPO}/releases', {'body': BODY}, tmp_path)


def test_asset_download_uses_fixed_repository_binary_endpoint(tmp_path, monkeypatch):
    def execute(command, **kwargs):
        assert command == ['gh', 'api', '-H', 'Accept: application/octet-stream',
                           f'repos/{pub.REPO}/releases/assets/42']
        kwargs['stdout'].write(b'exact bytes')
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(pub.subprocess, 'run', execute)
    destination = tmp_path / 'download'
    pub.download_asset(42, destination)
    assert destination.read_bytes() == b'exact bytes'
