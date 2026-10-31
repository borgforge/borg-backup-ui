#!/usr/bin/env python3
"""Read-only CI quality checks and explicit dependency checks (#671)."""
import argparse
import hashlib
from pathlib import Path
import py_compile
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INVALID_HOOK_EXAMPLES = {
    ROOT / 'docs/examples/job-hooks/pre-syntax-error.sh',
    ROOT / 'docs/examples/job-hooks/post-syntax-error.sh',
}


def tracked_files() -> list[Path]:
    """List tracked source files, excluding Git history and local test output."""
    return [ROOT / name for name in subprocess.check_output(
        ['git', 'ls-files'], cwd=ROOT, text=True).splitlines()]


def check() -> None:
    """Check source syntax, static errors and bundled Borg integrity; fail fast."""
    for tool in ('node', 'php', 'ruff'):
        if not shutil.which(tool):
            raise RuntimeError(f'Required CI tool is unavailable: {tool}')
    for path in tracked_files():
        if path.suffix == '.py':
            py_compile.compile(str(path), doraise=True)
        elif path.suffix in ('.sh',) or path.name == 'rc.borg_backup_ui':
            if path in INVALID_HOOK_EXAMPLES:
                # #550 ships negative examples for save-time validation. They
                # must still fail parsing, not be silently omitted from checks.
                result = subprocess.run(['bash', '-n', str(path)], capture_output=True)
                if result.returncode == 0:
                    raise RuntimeError(f'Negative syntax fixture unexpectedly parses: {path}')
            else:
                subprocess.run(['bash', '-n', str(path)], check=True)
        elif path.suffix in ('.js', '.cjs'):
            subprocess.run(['node', '--check', str(path)], check=True, stdout=subprocess.DEVNULL)
        elif path.suffix in ('.php', '.page'):
            subprocess.run(['php', '-l', str(path)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['ruff', 'check', '--select', 'E9,F63,F7,F82', 'borg_backup_ui.py',
                    'api', 'runtime/lib', 'runtime/scripts', 'plugin'], cwd=ROOT, check=True)
    verify_borg()


def verify_borg() -> Path:
    """Verify the tracked Borg binary before test execution; return its path."""
    line = (ROOT / 'runtime/bin/borg/SHA256SUMS').read_text().strip()
    expected, name = line.split()
    binary = ROOT / name
    with binary.open('rb') as handle:
        actual = hashlib.file_digest(handle, 'sha256').hexdigest()
    if expected != actual:
        raise RuntimeError('Bundled Borg SHA256 mismatch')
    return binary


def test_dependencies() -> None:
    """Require real Node/browser/Borg tools so missing dependencies cannot skip CI."""
    subprocess.run(['node', '-e', "const fs=require('fs');const {chromium}=require('playwright');if(!fs.existsSync(process.env.BBUI_CHROMIUM||chromium.executablePath()))process.exit(1)"], check=True)
    binary = verify_borg()
    tools = ROOT / '.release-tmp/ci/bin'; tools.mkdir(parents=True, exist_ok=True)
    link = tools / 'borg'
    if not link.exists():
        link.symlink_to(binary)
    subprocess.run([str(binary), '--version'], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'test-dependencies'))
    args = parser.parse_args()
    (check if args.command == 'check' else test_dependencies)()
