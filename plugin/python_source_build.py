#!/usr/bin/env python3
"""Build a pinned CPython supplier source with the SQLite update for #732.

Run explicitly on a Docker/Buildx host, outside privileged publishing jobs.
All source, downloads and scratch data stay inside the repository. Outputs are
build inputs requiring review, GitHub CI and testing; they authorize no release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import python_runtime as runtime

ROOT = runtime.ROOT


def recipe(root: Path = ROOT) -> tuple[dict, str]:
    """Read the committed source recipe and return its SHA256 identity."""
    path = root / 'runtime/python/source-build.lock.json'
    data = json.loads(path.read_text())
    if data['schema'] != 1 or data['supplier'] != 'astral-sh/python-build-standalone':
        raise ValueError('Unsupported source-build recipe')
    return data, runtime.sha256(path)


def prepare(work: Path, root: Path = ROOT) -> Path:
    """Verify/extract upstream source and apply the pinned inventory, test and build-option changes.

    Existing source trees must already contain the expected patched inventory;
    source compilation can then resume using upstream's dependency cache.
    """
    lock, _ = recipe(root)
    work = work.resolve()
    if not work.is_relative_to(root.resolve() / '.release-tmp'):
        raise ValueError('Source build work must be inside repository .release-tmp')
    work.mkdir(parents=True, exist_ok=True)
    archive = work / 'supplier-source.tar.gz'
    runtime.fetch(f'https://codeload.github.com/{lock["supplier"]}/tar.gz/{lock["supplier_commit"]}',
                  archive, lock['source_archive_sha256'])
    source = work / ('python-build-standalone-' + lock['supplier_commit'])
    if not source.exists():
        with tarfile.open(archive) as tar:
            tar.extractall(work, filter='data')
    inventory = source / 'pythonbuild/downloads.json'
    digest = runtime.sha256(inventory)
    if digest == lock['original_downloads_sha256']:
        downloads = json.loads(inventory.read_text())
        downloads['sqlite'].update({key: lock['sqlite'][key] for key in
                                   ('version', 'actual_version', 'url', 'sha256', 'size')})
        inventory.write_text(json.dumps(downloads, indent=4) + '\n')
    if runtime.sha256(inventory) != lock['patched_downloads_sha256']:
        raise ValueError('Supplier SQLite inventory patch differs from recipe')
    changed_paths = {inventory}
    for patch in [lock['test_expectation_patch'], *lock.get('build_patches', [])]:
        patch_path = source / patch['path']
        if runtime.sha256(patch_path) == patch['before_sha256']:
            contents = patch_path.read_text()
            if contents.count(patch['old']) != 1:
                raise ValueError('Source patch must match exactly once')
            patch_path.write_text(contents.replace(patch['old'], patch['new']))
        if runtime.sha256(patch_path) != patch['after_sha256']:
            raise ValueError('Supplier source patch differs from recipe')
        changed_paths.add(patch_path)
    # A recorded commit must describe the source actually compiled, including
    # resumed builds. Only the declared inventory/test/build patches are permitted.
    with tarfile.open(archive) as tar:
        for member in tar:
            path = work / member.name
            if path in changed_paths:
                continue
            if member.isfile():
                if not path.is_file() or path.is_symlink():
                    raise ValueError('Supplier source file missing or replaced')
                expected = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
                if runtime.sha256(path) != expected:
                    raise ValueError('Unrecorded supplier source change')
            elif member.issym() and (not path.is_symlink() or os.readlink(path) != member.linkname):
                raise ValueError('Unrecorded supplier source symlink change')
    sqlite = work / ('sqlite-autoconf-' + lock['sqlite']['version'] + '.tar.gz')
    runtime.fetch(lock['sqlite']['url'], sqlite, lock['sqlite']['sha256'])
    with tarfile.open(sqlite) as tar:
        code = tar.extractfile('sqlite-autoconf-' + lock['sqlite']['version'] + '/sqlite3.c').read()
    if hashlib.sha3_256(code).hexdigest() != lock['sqlite']['sqlite3_c_sha3_256']:
        raise ValueError('SQLite amalgamation differs from the published release hash')
    return source


def compile_source(work: Path, uv: Path, python: Path, root: Path = ROOT) -> None:
    """Build all upstream dependencies and CPython in Docker with pinned source inputs.

    Require the pinned uv driver and an explicit bootstrap Python. Drop GitHub
    credentials from child environments. Failures keep work for diagnosis/resume.
    """
    lock, _ = recipe(root)
    source = prepare(work, root)
    uv, python, work = uv.resolve(), python.resolve(), work.resolve()
    version = subprocess.check_output([str(uv), '--version'], text=True).split()[1]
    if version != lock['uv']['version']:
        raise ValueError('uv driver version differs from source recipe')
    env = {key: value for key, value in os.environ.items()
           if key not in ('GH_TOKEN', 'GITHUB_TOKEN', 'BBUI_BOT_TOKEN')}
    env.update(UV_CACHE_DIR=str(work / 'uv-cache'), UV_PYTHON_DOWNLOADS='never',
               TMPDIR=str(work), PYTHONPATH=str(source), PYTHON_CPU_COUNT=str(lock['cpu_count']),
               PYBUILD_RELEASE_TAG=lock['release_tag'])
    subprocess.run([str(uv), 'sync', '--python', str(python), '--frozen', '--no-dev', '--no-install-project'],
                   cwd=source, env=env, check=True)
    env['PATH'] = str(source / '.venv/bin') + ':' + str(uv.parent) + ':' + env['PATH']
    subprocess.run([str(source / '.venv/bin/python'), 'build.py', '--python', lock['series'],
                    '--target-triple', lock['target'], '--options', lock['options'], '--serial',
                    '--compression', 'fast'], cwd=source, env=env, check=True)


def package_input(work: Path, destination: Path, root: Path = ROOT) -> dict:
    """Strip a completed source build and package install tree, metadata and receipt.

    Keep full upstream outputs in work for inspection. Preserve native symbols
    and licenses; discard only debug sections and unshipped development archives.
    Return the verified runtime lock; do not overwrite the repository lockfile.
    """
    lock, recipe_sha = recipe(root)
    work, destination = work.resolve(), destination.resolve()
    if not destination.is_relative_to(root.resolve()):
        raise ValueError('Source build output must stay inside the repository')
    source = prepare(work, root)
    original = source / 'build' / f'cpython-{lock["python"]}-{lock["target"]}-{lock["options"]}.tar'
    stage = work / 'input-stage'
    if stage.exists():
        raise ValueError('Input staging directory already exists; use a fresh packaging stage')
    stage.mkdir()
    with tarfile.open(original) as tar:
        for member in tar:
            if (member.name == 'python/PYTHON.json' or member.name.startswith(('python/install/', 'python/licenses/'))):
                tar.extract(member, stage, filter='data')
    install = stage / 'python/install'
    for path in install.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix == '.a':
            path.unlink()
            continue
        with path.open('rb') as handle:
            is_elf = handle.read(4) == b'\x7fELF'
        if is_elf:
            subprocess.run(['strip', '--strip-debug', str(path)], check=True)
    shutil.copy2(source / 'pythonbuild/downloads.json', stage / 'python/supplier-downloads.json')
    shutil.copy2(source / 'LICENSE', stage / 'python/SUPPLIER-LICENSE.txt')
    metadata = json.loads((stage / 'python/PYTHON.json').read_text())
    result = {'schema': 2, 'version': lock['python'], 'build': lock['supplier_build'],
              'supplier': lock['supplier'], 'target': lock['target'], 'glibc_minimum': lock['glibc_minimum'],
              'excluded_extensions': ['_dbm', '_tkinter'], 'minimum_component_versions': {'sqlite': '3.54.1'}}
    result['components'] = runtime.inventory(metadata, json.loads((stage / 'python/supplier-downloads.json').read_text()), result)
    runtime.validate_component_floors(result, result['components'])
    native = runtime.native_facts(install / 'bin/python3.13', result)
    result['native_facts'] = native
    config = json.loads(subprocess.check_output(
        [str((install / 'bin/python3.13').resolve()), '-I', '-S', '-c',
         'import json,sysconfig; print(json.dumps({k:sysconfig.get_config_var(k) for k in ("CONFIG_ARGS","Py_GIL_DISABLED")}))'],
        text=True))
    flags = config['CONFIG_ARGS']
    if (metadata.get('build_options') != lock['options'] or '--enable-optimizations' not in flags
            or '--with-lto' not in flags or '--enable-bolt' in flags or config['Py_GIL_DISABLED']):
        raise ValueError('Executed source-build configuration differs from the intended PGO/LTO GIL runtime')
    test_env = {key: value for key, value in os.environ.items()
                if key not in ('GH_TOKEN', 'GITHUB_TOKEN', 'BBUI_BOT_TOKEN', 'PYTHONPATH', 'PYTHONHOME')}
    test_env.update(TARGET_TRIPLE=lock['target'], BUILD_OPTIONS=lock['options'], TMPDIR=str(work.resolve()))
    if not sys.stdout.isatty():
        # Upstream uses TERM to enable a test that requires a real terminal.
        test_env.pop('TERM', None)
    code = f'import sys,unittest; sys.path.insert(0, {str(source)!r}); unittest.main(module="pythonbuild.disttests")'
    subprocess.run([str((install / 'bin/python3.13').resolve()), '-I', '-c', code], env=test_env, check=True)
    def native_test_stack():
        """Set only the test child's explicit stack requirement; preserve runtime defaults (#733)."""
        _, hard = resource.getrlimit(resource.RLIMIT_STACK)
        resource.setrlimit(resource.RLIMIT_STACK, (lock['native_test_stack_bytes'], hard))

    subprocess.run([str((install / 'bin/python3.13').resolve()), '-I', '-m', 'test', *lock['native_test_modules'], '-j', '2'],
                   env=test_env, cwd=work, preexec_fn=native_test_stack, check=True)

    # Check every ELF before accepting a source build, independently of metadata.
    import re
    for path in install.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open('rb') as handle:
            is_elf = handle.read(4) == b'\x7fELF'
        if is_elf:
            symbols = subprocess.check_output(['readelf', '--dyn-syms', '--wide', str(path)], text=True)
            versions = [tuple(map(int, v.split('.'))) for v in re.findall(r'@GLIBC_([0-9.]+)', symbols)]
            if versions and max(versions) > tuple(map(int, lock['glibc_minimum'].split('.'))):
                raise ValueError('Source-built ELF exceeds the required glibc ceiling')
    receipt = {'schema': 1, 'id': lock['id'], 'recipe_sha256': recipe_sha,
               'python_version': lock['python'], 'target': lock['target'],
               'supplier_commit': lock['supplier_commit'], 'full_build_sha256': runtime.sha256(original),
               'native_facts': native, 'native_tests': ['supplier distribution tests passed', *[name + ' passed' for name in lock['native_test_modules']]],
               'bolt_enabled': lock['bolt_enabled'], 'build_configuration': config,
               'native_test_stack_bytes': lock['native_test_stack_bytes'],
               'known_limitations': lock['known_limitations'],
               'strip': subprocess.check_output(['strip', '--version'], text=True).splitlines()[0],
               'input_type': 'locally source-built input; requires independent GitHub CI before testing publication'}
    (stage / 'python/source-build.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / (lock['id'] + '.tar.xz')
    subprocess.run(['tar', '--create', '--xz', '--file', str(archive.resolve()), '--directory', str(stage),
                    '--sort=name', '--mtime=UTC 2024-01-01', '--owner=0', '--group=0', '--numeric-owner', 'python'], check=True)
    result.update(archive=archive.name, install_archive=archive.name,
                  sha256=runtime.sha256(archive), install_sha256=runtime.sha256(archive),
                  metadata_sha256=runtime.sha256(stage / 'python/PYTHON.json'),
                  downloads_sha256=runtime.sha256(stage / 'python/supplier-downloads.json'),
                  supplier_license_sha256=runtime.sha256(stage / 'python/SUPPLIER-LICENSE.txt'),
                  custom_build={'id': lock['id'], 'artifact': 'inputs/' + archive.name,
                                'recipe_sha256': recipe_sha,
                                'receipt_sha256': runtime.sha256(stage / 'python/source-build.json')})
    (destination / 'runtime.lock.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'build', 'package'))
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--uv', type=Path)
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.work)
    elif args.action == 'build':
        if args.uv is None:
            parser.error('--uv is required for building')
        compile_source(args.work, args.uv, args.python)
    else:
        if args.destination is None:
            parser.error('--destination is required for packaging')
        package_input(args.work, args.destination)
