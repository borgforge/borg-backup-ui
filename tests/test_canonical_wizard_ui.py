import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_wizard_identity_translations_and_markup():
    html = (ROOT / "ui/index.html").read_text()
    assert 'id="wiz-archive-prefix"' in html
    assert 'id="wiz-type-id"' not in html
    assert 'id="wiz-job-id"' not in html
    keys = {"archivePrefix", "archivePrefixHint", "archivePrefixHistoryHint", "archiveNamePreview",
            "previewArchiveName", "validationArchivePrefix", "validationArchivePrefixFormat", "defaultIcon",
            "identityMismatch", "jobEditConflict", "legacyWizardRequest", "jobMigrationRequired",
            "ambiguousArchiveOwnership", "duplicateTitle", "duplicateName"}
    for lang in ("de", "en"):
        strings = json.loads((ROOT / f"ui/i18n/{lang}.json").read_text())["wizard"]
        assert keys <= strings.keys()
        assert all(strings[key].strip() for key in keys)
        assert "typeId" not in strings


def test_wizard_javascript_lifecycle_and_both_languages():
    node = os.environ.get("BBUI_TEST_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable; set BBUI_TEST_NODE to run executable wizard tests")
    result = subprocess.run([node, str(ROOT / "tests/canonical_wizard_ui.cjs")], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
