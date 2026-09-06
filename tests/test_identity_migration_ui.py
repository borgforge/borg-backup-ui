"""User actions, reconnects and protected snapshot pauses for #479."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_migration_assistant_requires_separate_actions_and_observes_reconnects():
    node = os.environ.get('BBUI_TEST_NODE') or shutil.which('node')
    if not node:
        pytest.skip('Node.js unavailable')
    result = subprocess.run([node, str(ROOT / 'tests/identity_migration_ui.cjs')],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
