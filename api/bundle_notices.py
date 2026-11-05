"""Build and read bundle-attributed original license notices (#548)."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import re
import tarfile


def read_bundles(app: Path) -> list[dict]:
    """Read packaged bundle notices; source-only development has no generated index.

    Only the fixed plugin-owned path is read. Malformed installed data raises
    rather than presenting incomplete or invented license information.
    """
    index = app / 'runtime/licenses/bundles.json'
    if not index.is_file():
        return []
    data = json.loads(index.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('bundles'), list):
        raise ValueError('Unsupported bundle license index')
    return data['bundles']


def notice(name: str, content: str) -> dict:
    """Keep the original notice text; reject missing/empty build inputs."""
    if not content.strip():
        raise ValueError(f'Empty license notice: {name}')
    return {'name': name, 'content': content}


def build(app: Path, vendor: Path) -> dict:
    """Write a deterministic index using the exact Python/vendor build inputs.

    License text is read as data, never executed or extracted to host paths.
    Missing distribution licenses or Python notices fail the package build.
    The index is available even when the private runtime is not selected.
    """
    bundles = []
    borg_names = sorted((app / 'runtime/bin/borg').glob('borg-linux-*-x86_64-*'))
    if len(borg_names) != 1:
        raise ValueError('Expected one versioned bundled Borg binary')
    borg_version = borg_names[0].name.rsplit('-', 1)[1]
    prism_source = (app / 'ui/vendor/prism/README.md').read_text()
    prism_version = re.search(r'# Prism ([0-9.]+)', prism_source)
    if not prism_version:
        raise ValueError('Bundled Prism version is missing')
    for key, name, version, license_name in (
        ('borg', 'BorgBackup', borg_version, 'BSD-3-Clause'),
        ('prism', 'Prism', prism_version[1], 'MIT'),
    ):
        path = app / 'runtime/licenses' / key / 'LICENSE'
        bundles.append({'id': key, 'name': name, 'version': version, 'license': license_name,
                        'components': [], 'notices': [notice('LICENSE', path.read_text())]})
    meta = json.loads((app / 'runtime/vendor-bundles/apprise-vendor.json').read_text())
    components, notices = [], []
    for dist in sorted(importlib.metadata.distributions(path=[str(vendor)]), key=lambda d: d.metadata['Name'].lower()):
        name = dist.metadata['Name']
        components.append({'name': name, 'version': dist.version})
        files = [p for p in dist.files or [] if any(
            part.lower().startswith(('license', 'licence', 'copying', 'notice')) for part in p.parts)]
        if not files:
            raise ValueError(f'Missing packaged license for {name}')
        for relative in sorted(files, key=str):
            path = Path(dist.locate_file(relative)).resolve()
            if not path.is_relative_to(vendor.resolve()) or not path.is_file():
                raise ValueError(f'Invalid license path for {name}')
            notices.append(notice(f'{name} {dist.version} / {relative}', path.read_text(encoding='utf-8')))
    if not any(c['name'].lower() == 'apprise' and c['version'] == meta['version'] for c in components):
        raise ValueError('Apprise version does not match bundle metadata')
    bundles.append({'id': 'apprise', 'name': 'Apprise runtime', 'version': meta['version'],
                    'license': 'BSD-2-Clause + dependencies', 'sha256': meta['sha256'],
                    'components': components, 'notices': notices})
    python_dir = app / 'runtime/python'
    meta = json.loads((python_dir / 'python-runtime.json').read_text())
    notices = []
    with tarfile.open(python_dir / 'python-runtime.tar.xz') as archive:
        for member in sorted(archive.getmembers(), key=lambda m: m.name):
            name = member.name.removeprefix('./')
            if name.startswith('licenses/') and member.isfile():
                notices.append(notice(name, archive.extractfile(member).read().decode('utf-8')))
    if not any(n['name'] == 'licenses/LICENSE.cpython.txt' for n in notices):
        raise ValueError('Missing CPython license in private bundle')
    bundles.append({'id': 'python', 'name': 'CPython runtime', 'version': meta['version'],
                    'build': meta['build'], 'license': 'PSF License + dependencies',
                    'sha256': meta['bundle_sha256'],
                    'components': [{'name': name, 'version': item['version']} for name, item in sorted(meta['components'].items())],
                    'notices': notices})
    order = ['borg', 'apprise', 'python', 'prism']
    result = {'schema_version': 1, 'bundles': sorted(bundles, key=lambda b: order.index(b['id']))}
    destination = app / 'runtime/licenses/bundles.json'
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('vendor', type=Path)
    args = parser.parse_args()
    build(args.app, args.vendor)
