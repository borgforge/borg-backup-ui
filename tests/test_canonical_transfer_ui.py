import os
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]

def test_explicit_transfer_targets_and_exact_deletion_payloads_in_de_and_en():
    node = os.environ.get('BBUI_TEST_NODE') or shutil.which('node')
    if not node: pytest.skip('Node.js unavailable')
    result = subprocess.run([node, str(ROOT / 'tests/canonical_transfer_ui.cjs')], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
