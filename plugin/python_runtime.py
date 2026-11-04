#!/usr/bin/env python3
"""Build the private, offline Python bundle from pinned upstream inputs (#548)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
# Every linked non-system library must map to supplier provenance. Preserve all
# upstream licenses, including libraries not used by the application's modules.
LIBRARIES = {
    'bz2': 'bzip2', 'ffi': 'libffi', 'ncursesw': 'ncurses', 'panelw': 'ncurses',
    'db': 'bdb', 'mpdec': 'mpdecimal', 'crypto': 'openssl-3.5', 'ssl': 'openssl-3.5',
    'lzma': 'xz', 'sqlite3': 'sqlite', 'X11': 'libX11', 'Xau': 'libXau',
    'tclstub': 'tcl', 'tkstub': 'tk', 'xcb': 'libxcb', 'z': 'zlib',
    'uuid': 'uuid', 'expat': 'expat', 'edit': 'libedit',
}


def sha256(path: Path) -> str:
    """Hash a regular file without loading an archive into memory."""
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch(url: str, destination: Path, expected: str) -> None:
    """Cache an upstream input only after matching its committed SHA256 pin."""
    if not destination.is_file() or sha256(destination) != expected:
        temporary = destination.with_suffix('.download')
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as out:
            shutil.copyfileobj(response, out)
        if sha256(temporary) != expected:
            temporary.unlink()
            raise ValueError('Python supplier input checksum mismatch')
        temporary.replace(destination)


def inventory(metadata: dict, downloads: dict, lock: dict) -> dict:
    """Resolve native versions from the pinned build's link and source inventory.

    Unknown libraries fail the build, forcing review when the supplier layout
    changes. SQLite's numeric archive version is normalized to its runtime form.
    System glibc remains host-owned; it is not part of the private library set.
    """
    if (metadata['python_version'] != lock['version'] or metadata['target_triple'] != lock['target']
            or f"glibc-max-symbol-version:{lock['glibc_minimum']}" not in metadata['crt_features']):
        raise ValueError('Python distribution metadata does not match the lock')
    names = set()
    sections = [metadata['build_info']['core']]
    sections += [entry for name, variants in metadata['build_info']['extensions'].items()
                 if name not in lock['excluded_extensions'] for entry in variants]
    for section in sections:
        for link in section['links']:
            if not link.get('system'):
                names.add(LIBRARIES[link['name']])
    components = {'cpython': {'version': lock['version'], 'source': 'https://www.python.org/'}}
    for name in sorted(names):
        source = downloads[name]
        version = source['version']
        if name == 'sqlite':
            version = '.'.join(str(int(part)) for part in (version[0], version[1:3], version[3:5]))
        components[name] = {'version': version, 'source': source['url'], 'source_sha256': source['sha256']}
    return components


def build(destination: Path, cache: Path, root: Path = ROOT) -> dict:
    """Verify upstream provenance and create a deterministic portable bundle.

    Only the install tree and licenses are shipped; compiler objects, headers,
    pip, ensurepip and stdlib tests are omitted. No interpreter is installed on
    the build host. Errors prevent package publication.
    """
    lock = json.loads((root / 'runtime/python/runtime.lock.json').read_text())
    cache.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    release = f"https://github.com/{lock['supplier']}/releases/download/{lock['build']}"
    raw = f"https://raw.githubusercontent.com/{lock['supplier']}/{lock['build']}"
    archive = cache / lock['archive']
    fetch(release + '/' + urllib.parse.quote(lock['archive']), archive, lock['sha256'])
    downloads_path = cache / 'downloads.json'
    license_path = cache / 'SUPPLIER-LICENSE.txt'
    fetch(raw + '/pythonbuild/downloads.json', downloads_path, lock['downloads_sha256'])
    fetch(raw + '/LICENSE', license_path, lock['supplier_license_sha256'])
    unpacked = cache / 'unpacked'
    if unpacked.exists():
        shutil.rmtree(unpacked)
    unpacked.mkdir()
    tar_path = cache / 'upstream.tar'
    with tar_path.open('wb') as out:
        subprocess.run(['zstd', '-d', '-c', str(archive)], stdout=out, check=True)
    with tarfile.open(tar_path) as source:
        source.extractall(unpacked, filter='data')
    tar_path.unlink()
    metadata_path = unpacked / 'python/PYTHON.json'
    if sha256(metadata_path) != lock['metadata_sha256']:
        raise ValueError('Python metadata checksum mismatch')
    metadata = json.loads(metadata_path.read_text())
    components = inventory(metadata, json.loads(downloads_path.read_text()), lock)
    if components != lock['components']:
        raise ValueError('Committed Python inventory differs from supplier provenance')
    install = unpacked / 'python/install'
    for path in list(install.rglob('*.a')) + [install / 'include']:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    stdlib = install / 'lib' / ('python' + metadata['python_major_minor_version'])
    for name in ('site-packages', 'ensurepip', 'test', 'tkinter', 'idlelib', 'turtledemo', 'dbm'):
        shutil.rmtree(stdlib / name, ignore_errors=True)
    # Omit GUI and Berkeley DB extensions, which BBUI never imports. Their
    # separately linked native libraries/resources must not remain hidden in
    # the runtime inventory. Required built-in modules are never stripped.
    for name in lock['excluded_extensions']:
        for entry in metadata['build_info']['extensions'][name]:
            relative = Path(entry['shared_lib']).relative_to('install')
            (install / relative).unlink()
    for path in list((install / 'lib').glob('libtcl*.so*')) + [
            install / 'lib' / name for name in ('tcl', 'tcl9', 'tcl9.0', 'tk9.0', 'thread3.0.6', 'itcl4.3.8')]:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
    for path in (install / 'bin').glob('pip*'):
        path.unlink()
    shutil.copytree(unpacked / 'python/licenses', install / 'licenses')
    shutil.copy2(license_path, install / 'licenses/PYTHON-BUILD-STANDALONE.txt')
    shutil.copy2(metadata_path, install / 'PYTHON.json')
    shutil.copy2(downloads_path, install / 'supplier-downloads.json')
    provenance = {**lock, 'components': components}
    (install / 'provenance.json').write_text(json.dumps(provenance, indent=2, sort_keys=True) + '\n')
    bundle = destination / 'python-runtime.tar.xz'
    subprocess.run(['tar', '--create', '--xz', '--file', str(bundle.resolve()),
                    '--directory', str(install), '--sort=name', '--mtime=UTC 2024-01-01',
                    '--owner=0', '--group=0', '--numeric-owner', '.'], check=True)
    provenance.update(bundle=bundle.name, bundle_sha256=sha256(bundle),
                      executable='bin/python' + metadata['python_major_minor_version'])
    (destination / 'python-runtime.json').write_text(json.dumps(provenance, indent=2, sort_keys=True) + '\n')
    return provenance


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    args = parser.parse_args()
    build(args.destination, args.cache)
