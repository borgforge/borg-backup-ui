#!/usr/bin/env python3
"""Exercise the real private and host interpreters with packaged dependencies (#548)."""
import argparse
import json
import os
from pathlib import Path
import shutil
import site
import subprocess
import sys

import python_runtime

ROOT = Path(__file__).resolve().parents[1]


def check(work: Path, tests: bool = False) -> None:
    """Build a non-publishing bundle and run isolated probes/provider contracts.

    All scratch data lives below work. Host sitecustomize and PYTHONPATH poison
    must not execute, and both runtimes must import the actual shipped vendor.
    Also validate every shipped ELF's advertised glibc ceiling with readelf.
    """
    work = work.resolve()
    app = work / 'app'
    runtime = app / 'runtime/python'
    shutil.copytree(ROOT / 'runtime/python', runtime, dirs_exist_ok=True)
    meta = python_runtime.build(runtime, work / 'cache')
    vendor = app / 'runtime/vendor'
    if vendor.exists():
        shutil.rmtree(vendor)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-compile',
                    '--only-binary=:all:', '--require-hashes', '--target', str(vendor),
                    '-r', str(ROOT / 'plugin/apprise-requirements.lock')], check=True)
    private = work / 'cache/unpacked/python/install' / meta['executable']
    poison = work / 'poison'
    poison.mkdir(exist_ok=True)
    marker = work / 'poison-executed'
    for name in ('sitecustomize', 'usercustomize', 'apprise', 'ssl'):
        (poison / (name + '.py')).write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\nraise RuntimeError("poison")\n')
    env = {**os.environ, 'PYTHONPATH': str(poison), 'PYTHONHOME': str(poison)}
    for source, interpreter in (("external", Path(sys.executable)), ("bundled", private)):
        details = subprocess.check_output([str(interpreter), "-E", "-s", "-S", "-c",
                                           "import sys; print(sys.version.split()[0], sys.executable)"], text=True).strip()
        print(f"Runtime contract tests: source={source}; {details}", flush=True)
        command = [str(interpreter), '-E', '-s', '-S', '-B']
        result = subprocess.check_output([*command, str(runtime / 'probe.py'), str(app)], env=env, text=True)
        assert json.loads(result)['ok']
        assert not marker.exists()
        subprocess.run([*command, str(ROOT / 'plugin/check_apprise_runtime.py'), str(vendor)], env=env, check=True)
    # Test real offline extraction too, forcing an incompatible external candidate.
    commands = work / 'commands'
    commands.mkdir(exist_ok=True)
    (commands / 'python3').write_text('#!/bin/sh\nexit 1\n')
    (commands / 'python3').chmod(0o755)
    launch_env = {**env, 'PATH': str(commands) + ':' + os.environ['PATH'],
                  'BBUI_RUNTIME_STATE': str(work / 'ram'), 'BBUI_SERVICE_PIDFILE': str(work / 'service.pid')}
    status = json.loads(subprocess.check_output(['bash', str(runtime / 'launch.sh'), '--status'], env=launch_env, text=True))
    assert status['source'] == 'bundled' and status['version'] == meta['version']
    assert Path(status['path']).is_relative_to(work / 'ram')
    import re
    ceiling = tuple(map(int, meta['glibc_minimum'].split('.')))
    install = private.parent.parent
    for path in install.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open('rb') as handle:
            is_elf = handle.read(4) == b'\x7fELF'
        if is_elf:
            symbols = subprocess.check_output(['readelf', '--dyn-syms', '--wide', str(path)], text=True)
            versions = [tuple(map(int, v.split('.'))) for v in re.findall(r'@GLIBC_([0-9.]+)', symbols)]
            if versions and max(versions) > ceiling:
                raise ValueError('Shipped ELF exceeds the locked glibc baseline')
    if tests:
        print(f"Application regression tests: source=bundled; Python {meta['version']}; interpreter={private}", flush=True)
        paths = [str(ROOT), str(ROOT / 'api'), str(ROOT / 'runtime'), *site.getsitepackages()]
        code = f'import sys,runpy; sys.path[:0]={paths!r}; runpy.run_module("pytest",run_name="__main__")'
        subprocess.run([str(private), '-E', '-s', '-S', '-B', '-c', code, '-q',
                        'tests/test_auth.py', 'tests/test_job_groups.py', 'tests/test_wizard_runner_runtime_path.py',
                        'tests/test_restore_test_scheduling.py', 'tests/test_job_scripts.py', 'tests/test_python_runtime.py',
                        'tests/test_restore_test_memory.py', 'tests/test_notification_events.py',
                        '--basetemp=' + str(work / 'tests')], cwd=ROOT,
                       env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}, check=True)
    print('Private/external Python, isolation, offline extraction, Apprise and ELF checks passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--tests', action='store_true', help='Run focused application tests with private Python')
    args = parser.parse_args()
    check(args.work, args.tests)
