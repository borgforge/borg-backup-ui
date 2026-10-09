"""Browser-independent regression checks for the native Unraid widget (#546)."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest


def test_widget_rendering():
    """Execute the actual page script with controlled clocks and fetch responses."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for widget rendering tests")
    subprocess.run([node, "--test", "tests/unraid_widget.cjs"],
                   cwd=Path(__file__).resolve().parents[1],
                   env={**os.environ, "TZ": "UTC"}, check=True)
