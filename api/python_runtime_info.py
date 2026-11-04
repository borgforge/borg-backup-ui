"""Diagnostics for the interpreter executing this process (#548)."""
from pathlib import Path
import sys


def runtime_info() -> dict:
    """Return the actual interpreter, not a PATH lookup or inherited selection.

    Private bundles carry provenance at sys.prefix. No subprocess is started,
    and no configuration or environment values are included in diagnostics.
    """
    return {
        'version': '.'.join(map(str, sys.version_info[:3])),
        'path': sys.executable,
        'source': 'bundled' if (Path(sys.prefix) / 'provenance.json').is_file() else 'external',
        'isolated_dependencies': bool(sys.flags.no_site and sys.flags.ignore_environment),
    }


def runtime_log_line() -> str:
    """Format safe, single-line runtime diagnostics for job logs."""
    info = runtime_info()
    path = info['path'].replace('\r', '\\r').replace('\n', '\\n')
    return f"Active Python: {info['version']} | source={info['source']} | executable={path}"
