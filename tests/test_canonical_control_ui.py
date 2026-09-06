import os
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_uuid_actions_current_labels_and_complete_prefix_preview_in_both_languages():
    node = os.environ.get('BBUI_TEST_NODE') or shutil.which('node')
    if not node:
        pytest.skip('Node.js unavailable')
    result = subprocess.run([node, str(ROOT / 'tests/canonical_control_ui.cjs')], capture_output=True,
                            text=True, timeout=30, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
