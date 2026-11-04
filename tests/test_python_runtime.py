"""Runtime selection, isolation and packaging contracts for #548."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin'))
import python_runtime as builder
import release_workflow as release


@pytest.fixture
def launcher(tmp_path):
    """Run the real shell selector against tiny synthetic interpreters."""
    root = tmp_path / 'app'
    runtime = root / 'runtime/python'
    runtime.mkdir(parents=True)
    shutil.copy2(ROOT / 'runtime/python/launch.sh', runtime / 'launch.sh')
    commands = tmp_path / 'bin'
    commands.mkdir()
    for name in ('dirname', 'install', 'flock', 'timeout', 'cat', 'sed', 'sha256sum',
                 'tar', 'xz', 'mktemp', 'rm', 'touch', 'mv'):
        (commands / name).symlink_to(shutil.which(name))
    env = {**os.environ, 'PATH': str(commands), 'BBUI_RUNTIME_STATE': str(tmp_path / 'ram'),
           'BBUI_SERVICE_PIDFILE': str(tmp_path / 'service.pid')}
    def interpreter(path, version='3.13.18'):
        path.write_text('#!/bin/bash\nif [ "$1" = -E ]; then\n'
                        'printf \'{"ok":true,"source":"%s","path":"%s","version":"' + version + '"}\\n\' "$BBUI_PYTHON_SOURCE" "$0"\nfi\n')
        path.chmod(0o755)
    private = tmp_path / 'private'
    interpreter(private)
    bundle = runtime / 'python-runtime.tar.xz'
    with tarfile.open(bundle, 'w:xz') as archive:
        archive.add(private, arcname='bin/python3.13')
    meta = {'bundle_sha256': hashlib.sha256(bundle.read_bytes()).hexdigest(), 'executable': 'bin/python3.13'}
    (runtime / 'python-runtime.json').write_text(json.dumps(meta, indent=2) + '\n')
    def run(mode='--status'):
        return subprocess.run(['/bin/bash', str(runtime / 'launch.sh'), mode], env=env, capture_output=True, text=True, timeout=10)
    return run, commands, env, runtime, interpreter


@pytest.mark.parametrize('external', ['missing', 'broken', 'old', 'usable'])
def test_selection_and_private_ram_layout(launcher, external):
    run, commands, env, runtime, interpreter = launcher
    if external == 'usable':
        interpreter(commands / 'python3', '3.12.4')
    elif external != 'missing':
        path = commands / 'python3'
        path.write_text('#!/bin/bash\nexit 1\n')
        path.chmod(0o755)
    result = run()
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status['source'] == ('external' if external == 'usable' else 'bundled')
    if external != 'usable':
        assert status['path'].startswith(env['BBUI_RUNTIME_STATE'] + '/python/')
        assert not (runtime / 'bin').exists()
        before = Path(status['path']).stat().st_mtime_ns
        assert run().returncode == 0
        assert Path(status['path']).stat().st_mtime_ns == before
    assert Path(env['BBUI_RUNTIME_STATE']).stat().st_mode & 0o777 == 0o700


def test_running_service_keeps_selection_and_restart_reconsiders(launcher):
    run, commands, env, _, interpreter = launcher
    selected = run('--select').stdout.strip()
    Path(env['BBUI_SERVICE_PIDFILE']).write_text(str(os.getpid()))
    interpreter(commands / 'python3')
    assert json.loads(run().stdout)['path'] == selected
    Path(env['BBUI_SERVICE_PIDFILE']).unlink()
    assert json.loads(run().stdout)['source'] == 'external'
    (commands / 'python3').unlink()
    assert json.loads(run().stdout)['source'] == 'bundled'


def test_removed_active_external_does_not_silently_switch(launcher):
    run, commands, env, _, interpreter = launcher
    interpreter(commands / 'python3')
    assert run('--select').returncode == 0
    Path(env['BBUI_SERVICE_PIDFILE']).write_text(str(os.getpid()))
    (commands / 'python3').unlink()
    result = run()
    assert result.returncode != 0 and 'Reinstall' in result.stderr


def test_corrupt_bundle_fails_before_extracting(launcher):
    run, _, env, runtime, _ = launcher
    (runtime / 'python-runtime.tar.xz').write_bytes(b'corrupt')
    assert run().returncode != 0
    assert not (Path(env['BBUI_RUNTIME_STATE']) / 'python').exists()


def test_native_inventory_matches_committed_provenance():
    lock = json.loads((ROOT / 'runtime/python/runtime.lock.json').read_text())
    assert lock['components']['cpython']['version'] == lock['version']
    assert lock['glibc_minimum'] == '2.17'
    assert all(len(lock[key]) == 64 for key in ('sha256', 'metadata_sha256', 'downloads_sha256'))
    import python_monitor
    assert set(lock['components']) <= set(python_monitor.PRODUCTS)


def test_download_integrity_never_accepts_wrong_bytes(tmp_path, monkeypatch):
    class Response(io.BytesIO):
        pass
    monkeypatch.setattr(builder.urllib.request, 'urlopen', lambda *a, **k: Response(b'wrong'))
    with pytest.raises(ValueError, match='checksum'):
        builder.fetch('https://example.test', tmp_path / 'input', '0' * 64)
    assert not (tmp_path / 'input').exists()


def test_manifest_generation_uses_native_unraid_version_gate():
    original = (ROOT / 'borg-backup-ui.plg').read_text()
    changed = release.rewrite_host_compatibility(original)
    assert 'Min="6.12.5" Max="7.99.99"' in changed
    assert release.rewrite_host_compatibility(changed) == changed
    assert 'Max="7.99.99"' not in original  # source PR does not edit stable artifact


@pytest.mark.skipif(not shutil.which('php'), reason='PHP version_compare is checked in GitHub quality image')
def test_unraid_native_boundary_with_php():
    script = '''foreach (['6.12.4','6.12.5','7.0.0','7.99.9','8.0.0-beta.1','8.0.0'] as $v) {
        echo (version_compare($v,'6.12.5','>=') && version_compare($v,'7.99.99','<=')) ? '1' : '0';
    }'''
    assert subprocess.check_output(['php', '-r', script], text=True) == '011100'


@pytest.mark.parametrize('damage', [None, 'lock', 'metadata', 'bundle', 'missing'])
def test_package_validation_binds_private_runtime_to_source(tmp_path, damage):
    prefix = 'boot/config/plugins/borg-backup-ui/'
    vendor = b'vendor fixture'
    lock = {'version': '3.13.18', 'components': {'cpython': {'version': '3.13.18'}}}
    lock_bytes = json.dumps(lock).encode()
    bundle = b'private runtime fixture'
    meta = {**lock, 'bundle': 'python-runtime.tar.xz', 'bundle_sha256': hashlib.sha256(bundle).hexdigest()}
    provenance = {'python_runtime_lock_sha256': hashlib.sha256(lock_bytes).hexdigest()}
    payload = {name: b'fixture' for name in release.EXPECTED_PACKAGE_MEMBERS}
    payload[release.PROVENANCE_MEMBER] = json.dumps(provenance).encode()
    payload[prefix + 'runtime/vendor-bundles/apprise-vendor.json'] = json.dumps(
        {'version': '2.1.0', 'bundle': 'apprise.tar.xz', 'sha256': hashlib.sha256(vendor).hexdigest()}).encode()
    payload[prefix + 'runtime/vendor-bundles/apprise.tar.xz'] = vendor
    for name, content in {'runtime.lock.json': lock_bytes, 'python-runtime.json': json.dumps(meta).encode(),
                          'python-runtime.tar.xz': bundle, 'launch.sh': b'launcher', 'probe.py': b'probe'}.items():
        payload[prefix + 'runtime/python/' + name] = content
    if damage == 'lock':
        payload[prefix + 'runtime/python/runtime.lock.json'] = b'{}'
    elif damage == 'metadata':
        meta['version'] = 'different'
        payload[prefix + 'runtime/python/python-runtime.json'] = json.dumps(meta).encode()
    elif damage == 'bundle':
        payload[prefix + 'runtime/python/python-runtime.tar.xz'] = b'corrupt'
    elif damage == 'missing':
        del payload[prefix + 'runtime/python/probe.py']
    package = tmp_path / 'candidate.txz'
    with tarfile.open(package, 'w:xz') as archive:
        for name, content in payload.items():
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(content), 0o644
            archive.addfile(member, io.BytesIO(content))
    if damage:
        with pytest.raises(RuntimeError):
            release.package_provenance(package)
    else:
        assert release.package_provenance(package) == provenance


def test_real_http_setup_page_api_and_runtime_diagnostics(tmp_path, monkeypatch):
    """Start the real HTTP handler with isolated data and no host startup hooks."""
    import http.client
    import threading
    monkeypatch.syspath_prepend(str(ROOT / 'api'))
    monkeypatch.syspath_prepend(str(ROOT / 'runtime'))
    monkeypatch.syspath_prepend(str(ROOT / 'runtime/lib'))
    import borg_backup_ui as app
    from system_health_api import get_system_health_data
    config = app.load_ui_config()
    config.update(BACKUP_SCRIPTS_DIR=str(tmp_path), STATUS_DIR=str(tmp_path / 'status'), BIND='127.0.0.1')
    monkeypatch.setattr(app.BackupUIHandler, 'config', config)
    server = app.ThreadedHTTPServer(('127.0.0.1', 0), app.BackupUIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path in ('/setup-admin', '/api/auth/status'):
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            client.request('GET', path)
            response = client.getresponse()
            body = response.read()
            assert response.status == 200
            if path.startswith('/api'):
                assert isinstance(json.loads(body), dict)
            else:
                assert b'<html' in body
            client.close()
        runtime = get_system_health_data(config)['python_runtime']
        assert runtime['path'] == sys.executable
        assert runtime['version'] == '.'.join(map(str, sys.version_info[:3]))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
