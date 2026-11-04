"""Bundle attribution, actual runtime diagnostics and job-log regressions (#548)."""
import io
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT, ROOT / 'api', ROOT / 'plugin'):
    sys.path.insert(0, str(entry))
import bundle_notices
import python_runtime_info


@pytest.fixture
def bundle_inputs(tmp_path):
    app = tmp_path / 'app'
    for key in ('borg', 'prism'):
        directory = app / 'runtime/licenses' / key
        directory.mkdir(parents=True)
        (directory / 'LICENSE').write_text(f'{key} original notice\n')
    borg = app / 'runtime/bin/borg'
    borg.mkdir(parents=True)
    (borg / 'borg-linux-glibc231-x86_64-1.4.5').touch()
    prism = app / 'ui/vendor/prism'
    prism.mkdir(parents=True)
    (prism / 'README.md').write_text('# Prism 1.30.0\n')
    vendor = tmp_path / 'vendor'
    for name, version, relative in [('apprise', '2.1.0', 'licenses/LICENSE'), ('dependency', '9.1', 'LICENSE')]:
        dist = vendor / f'{name}-{version}.dist-info'
        (dist / relative).parent.mkdir(parents=True)
        (dist / 'METADATA').write_text(f'Name: {name}\nVersion: {version}\n')
        (dist / relative).write_text(f'{name} original notice <script>window.licenseExecuted=true</script>\n')
        (dist / 'RECORD').write_text(f'{dist.name}/{relative},,\n')
    apprise = app / 'runtime/vendor-bundles'
    apprise.mkdir(parents=True)
    (apprise / 'apprise-vendor.json').write_text(json.dumps({'version': '2.1.0', 'sha256': 'a' * 64}))
    python = app / 'runtime/python'
    python.mkdir(parents=True)
    (python / 'python-runtime.json').write_text(json.dumps({
        'version': '3.13.18', 'build': '20261026', 'bundle_sha256': 'b' * 64,
        'components': {'cpython': {'version': '3.13.18'}, 'openssl': {'version': '3.5.4'}}}))
    with tarfile.open(python / 'python-runtime.tar.xz', 'w:xz') as archive:
        for name, text in [('LICENSE.cpython.txt', 'PSF full original\n'), ('LICENSE.openssl.txt', 'OpenSSL full original\n')]:
            info = tarfile.TarInfo('./licenses/' + name)
            content = text.encode()
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return app, vendor


def test_bundle_notices_preserve_complete_texts_and_shipped_versions(bundle_inputs):
    app, vendor = bundle_inputs
    result = bundle_notices.build(app, vendor)
    bundles = {b['id']: b for b in result['bundles']}
    assert list(bundles) == ['borg', 'apprise', 'python', 'prism']
    assert bundles['python']['version'] == '3.13.18'
    assert bundles['python']['build'] == '20261026'
    assert bundles['python']['notices'][0]['content'] == 'PSF full original\n'
    assert len(bundles['python']['notices']) == 2
    assert [c['version'] for c in bundles['apprise']['components']] == ['2.1.0', '9.1']
    assert len(bundles['apprise']['notices']) == 2
    assert all('original notice <script>' in n['content'] for n in bundles['apprise']['notices'])
    assert bundles['borg']['notices'][0]['content'] == 'borg original notice\n'
    assert bundles['prism']['notices'][0]['content'] == 'prism original notice\n'
    before = (app / 'runtime/licenses/bundles.json').read_bytes()
    bundle_notices.build(app, vendor)
    assert (app / 'runtime/licenses/bundles.json').read_bytes() == before


def test_missing_dependency_notice_blocks_packaging(bundle_inputs):
    app, vendor = bundle_inputs
    (vendor / 'dependency-9.1.dist-info/LICENSE').unlink()
    with pytest.raises(ValueError, match='license'):
        bundle_notices.build(app, vendor)


def test_license_api_keeps_bundle_and_active_python_versions_separate(bundle_inputs, monkeypatch):
    import borg_backup_ui as server
    app, vendor = bundle_inputs
    result = bundle_notices.build(app, vendor)
    legacy = app / 'runtime/licenses/THIRD-PARTY-NOTICES.md'
    legacy.write_text('# Third-party license notices\n')
    monkeypatch.setattr(server, 'SCRIPT_DIR', app)
    monkeypatch.setattr(server, 'LICENSE_FILES', {'third-party': legacy})
    monkeypatch.setattr(python_runtime_info, 'runtime_info', lambda: {'version': '3.12.4', 'source': 'external', 'path': '/usr/bin/python3'})
    handler = server.BackupUIHandler.__new__(server.BackupUIHandler)
    response = handler._get_license_file('id=third-party')
    assert response['bundles'] == result['bundles']
    assert response['python_runtime']['version'] == '3.12.4'
    assert next(b for b in response['bundles'] if b['id'] == 'python')['version'] == '3.13.18'


@pytest.mark.parametrize('private', [False, True])
def test_actual_runtime_ignores_inherited_source_and_escapes_log_lines(tmp_path, monkeypatch, private):
    monkeypatch.setattr(sys, 'prefix', str(tmp_path))
    monkeypatch.setattr(sys, 'executable', '/chosen/python\nforged-entry')
    monkeypatch.setenv('BBUI_PYTHON_SOURCE', 'external' if private else 'bundled')
    if private:
        (tmp_path / 'provenance.json').write_text('{}')
    info = python_runtime_info.runtime_info()
    assert info['source'] == ('bundled' if private else 'external')
    assert info['version'] == '.'.join(map(str, sys.version_info[:3]))
    assert '\n' not in python_runtime_info.runtime_log_line()
    assert r'executable=/chosen/python\nforged-entry' in python_runtime_info.runtime_log_line()


def test_backup_logs_interpreter_before_loading_job(tmp_path, monkeypatch, caplog):
    import wizard_runner
    import job_control
    monkeypatch.setattr(wizard_runner, '_setup_stdout_logging', lambda: None)
    monkeypatch.setattr(wizard_runner, '_ensure_borg_available', lambda: '/fake/borg')
    monkeypatch.setattr(job_control, 'JobControl', lambda *_: SimpleNamespace(update_phase=lambda *a, **kw: None))
    monkeypatch.setenv('BORG_UI_JOB_KEY', 'fixture')
    monkeypatch.setenv('BORG_UI_BORG_SCRIPTS_DIR', str(tmp_path))
    monkeypatch.setenv('BORG_SCRIPT_DIR', str(tmp_path))
    def stop(*args):
        raise ValueError('stop after startup logging')
    monkeypatch.setattr(wizard_runner, '_load_env_from_job', stop)
    with caplog.at_level(logging.INFO):
        assert wizard_runner.main() == 2
    assert python_runtime_info.runtime_log_line() in caplog.text


@pytest.mark.parametrize('worker', [False, True])
def test_restore_main_logs_actual_interpreter_including_resource_worker(monkeypatch, worker):
    from test_restore_test_runner_profiles import _load_restore_runner
    runner = _load_restore_runner()
    lines = []
    tester = SimpleNamespace(log=lines.append, close=lambda: None, log_path='/fixture/restore.log',
                             _test_repo_locked=lambda repo: 0)
    monkeypatch.setattr(runner, 'RestoreTest', lambda *args: tester)
    monkeypatch.setattr(runner, 'load_conf', lambda: {})
    monkeypatch.setattr(runner, 'discover_repos', lambda conf: [{'job_key': 'fixture'}] if worker else [])
    monkeypatch.setattr(runner, 'emit_lifecycle', lambda *args, **kw: None)
    monkeypatch.setattr(sys, 'argv', ['restore', '--job-key', 'fixture', *(['--resource-worker'] if worker else [])])
    with pytest.raises(SystemExit):
        runner.main()
    assert lines[0] == python_runtime_info.runtime_log_line()


@pytest.mark.skipif(not shutil.which('node'), reason='Node/browser available in required GitHub CI')
def test_bundle_cards_contain_only_their_own_full_notices(bundle_inputs, tmp_path):
    app, vendor = bundle_inputs
    bundle_notices.build(app, vendor)
    subprocess.run(['node', str(ROOT / 'tests/about_bundles_browser.cjs'), str(app / 'runtime/licenses/bundles.json')],
                   cwd=ROOT, check=True, timeout=45)


def test_missing_python_license_blocks_packaging(bundle_inputs):
    app, vendor = bundle_inputs
    with tarfile.open(app / 'runtime/python/python-runtime.tar.xz', 'w:xz'):
        pass
    with pytest.raises(ValueError, match='Missing CPython license'):
        bundle_notices.build(app, vendor)


def test_apprise_version_drift_blocks_packaging(bundle_inputs):
    app, vendor = bundle_inputs
    meta = app / 'runtime/vendor-bundles/apprise-vendor.json'
    meta.write_text(json.dumps({'version': '9.0.0', 'sha256': 'a' * 64}))
    with pytest.raises(ValueError, match='version does not match'):
        bundle_notices.build(app, vendor)
