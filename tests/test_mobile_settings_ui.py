"""Integrated settings view and fixed, non-reflected login target (#741)."""
from io import BytesIO
import shutil
import subprocess
from pathlib import Path
import pytest
from borg_backup_ui import BackupUIHandler

ROOT = Path(__file__).resolve().parents[1]


def test_mobile_settings_browser():
    if not shutil.which('node'):
        pytest.skip('Node.js is required for browser checks')
    available = subprocess.run(['node', '-e', "const fs=require('fs');const {chromium}=require('playwright');process.exit(fs.existsSync(process.env.BBUI_CHROMIUM || chromium.executablePath())?0:1)"], capture_output=True)
    if available.returncode:
        pytest.skip('Playwright and Chromium are required for browser checks')
    subprocess.run(['node', 'tests/mobile_devices_browser.cjs'], cwd=ROOT, check=True)


@pytest.mark.parametrize('signed_in,target', [(False,'/login#mobile-devices'),(True,'/#mobile-devices')])
def test_existing_pairing_link_enters_application(signed_in, target):
    h = BackupUIHandler.__new__(BackupUIHandler)
    h.path = '/ui/mobile-devices.html?next=https://untrusted.invalid'
    h._is_ui_session_valid = lambda: signed_in
    response = {}
    h.send_response = lambda status: response.update(status=status)
    h.send_header = lambda key,value: response.update({key:value})
    h.end_headers = lambda: None
    h.do_GET()
    assert response == {'status':302,'Location':target,'Cache-Control':'no-store'}


def test_login_returns_only_to_fixed_device_target():
    h = BackupUIHandler.__new__(BackupUIHandler)
    h._bootstrap_required = lambda: False
    h._ui_auth_enabled = lambda: True
    h.send_response = lambda _: None
    h.send_header = lambda *_: None
    h.end_headers = lambda: None
    h.wfile = BytesIO()
    h._serve_login_page()
    html = h.wfile.getvalue().decode()
    assert "window.location.hash==='#mobile-devices'?'/#mobile-devices':'/'" in html
    assert 'searchParams.get' not in html
