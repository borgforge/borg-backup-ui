"""Exercise shared feedback across page and dialog contexts."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_page_feedback():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for page feedback tests")
    subprocess.run([node, "tests/page_feedback.cjs"],
                   cwd=Path(__file__).resolve().parents[1], check=True)
