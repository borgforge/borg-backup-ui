"""Browser interaction checks for both database settings translations (#591)."""
import subprocess
import shutil
from pathlib import Path

import pytest


def test_database_profiles_browser():
    if not shutil.which('node'):
        pytest.skip('Node.js is required for the database settings browser test')
    available = subprocess.run(['node', '-e', "const fs=require('fs'); const {chromium}=require('playwright'); process.exit(fs.existsSync(process.env.BBUI_CHROMIUM || chromium.executablePath()) ? 0 : 1)"], capture_output=True)
    if available.returncode:
        pytest.skip('Playwright and Chromium are required for the database settings browser test')
    subprocess.run(['node','tests/database_profiles_ui.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)

    subprocess.run(['node','tests/wizard_sources_ui.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)


def test_storage_profile_save_workflow_browser():
    if not shutil.which('node'):
        pytest.skip('Node.js is required for profile workflow checks')
    available = subprocess.run(['node', '-e', "const fs=require('fs'); const {chromium}=require('playwright'); process.exit(fs.existsSync(process.env.BBUI_CHROMIUM || chromium.executablePath()) ? 0 : 1)"], capture_output=True)
    if available.returncode:
        pytest.skip('Playwright and Chromium are required for profile workflow checks')
    subprocess.run(['node', 'tests/profile_save_workflow_ui.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)
    subprocess.run(['node', 'tests/smb_mount_status_ui.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)
