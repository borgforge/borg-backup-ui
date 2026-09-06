import shutil
import subprocess
from pathlib import Path

import pytest


def test_activity_log_browser_logic():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the activity-log UI behavior tests")
    root = Path(__file__).resolve().parents[1]
    subprocess.run([node, "tests/activity_log_ui.cjs"], cwd=root, check=True)
