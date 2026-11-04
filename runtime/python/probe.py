"""Check the actual interpreter and packaged imports without host sites (#548)."""
import importlib
import json
import os
from pathlib import Path
import sys


def probe(root: Path) -> dict:
    """Return safe runtime diagnostics or raise for an unsupported/incomplete runtime.

    Executed with -E -s -S so user sites, sitecustomize, PYTHONHOME and PYTHONPATH
    cannot satisfy imports. The private vendor tree is the only dependency path.
    No network, configuration changes or notification delivery occur.
    """
    if not (3, 10) <= sys.version_info[:2] < (3, 14):
        raise RuntimeError('Unsupported Python series')
    for name in ('ssl', 'hashlib', 'sqlite3', 'bz2', 'lzma', 'zlib', 'ctypes', 'fcntl',
                 'socket', 'threading', 'multiprocessing', 'xml.etree.ElementTree',
                 'xml.parsers.expat', 'zoneinfo', 'http.server', 'email', 'asyncio'):
        importlib.import_module(name)
    import ssl
    import hashlib
    import sqlite3
    hashlib.scrypt(b'probe', salt=b'probe', n=1024, r=8, p=1)
    with sqlite3.connect(':memory:') as db:
        db.execute('select 1').fetchone()
    vendor = root / 'runtime/vendor'
    sys.path.insert(0, str(vendor))
    for name in ('apprise', 'requests', 'yaml', 'certifi', 'cryptography' if (vendor / 'cryptography').exists() else 'oauthlib'):
        module = importlib.import_module(name)
        if not Path(module.__file__).resolve().is_relative_to(vendor.resolve()):
            raise RuntimeError('Dependency resolved outside packaged vendor tree')
    import certifi
    ssl.create_default_context(cafile=certifi.where())
    return {'ok': True, 'path': sys.executable, 'version': '.'.join(map(str, sys.version_info[:3])),
            'source': os.environ.get('BBUI_PYTHON_SOURCE', 'external'), 'reason': '', 'min_version': '3.10'}


if __name__ == '__main__':
    try:
        print(json.dumps(probe(Path(sys.argv[1]))))
    except Exception:
        # Import exceptions and external interpreter output can contain paths or
        # environment details. The shell launcher reports a fixed repair hint.
        raise SystemExit(1) from None
