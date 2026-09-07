import shutil
import subprocess
from pathlib import Path
import pytest


def test_job_identity_browser_logic():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for the job identity UI tests')
    subprocess.run([node, 'tests/job_identity_ui.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)
