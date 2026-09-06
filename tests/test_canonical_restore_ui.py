"""Executable DE/EN restore selection, history and action contracts (#477)."""
import os
from pathlib import Path
import shutil
import subprocess
import pytest


def test_canonical_restore_in_both_languages():
    node=os.environ.get('BBUI_TEST_NODE') or shutil.which('node')
    if not node: pytest.skip('Node.js unavailable')
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([node,str(root/'tests/canonical_restore_ui.cjs')],cwd=root,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
