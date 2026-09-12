"""Run the real restore-page JavaScript against controlled API responses."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_restore_browse_state():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for restore UI tests")
    subprocess.run([node, "tests/restore_browse_state.cjs"],
                   cwd=Path(__file__).resolve().parents[1], check=True)
