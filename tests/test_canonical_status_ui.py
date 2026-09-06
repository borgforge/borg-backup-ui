import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_status_navigation_and_counters_in_both_languages():
    node = os.environ.get('BBUI_TEST_NODE') or shutil.which('node')
    if not node:
        pytest.skip('Node.js unavailable')
    result = subprocess.run([node, str(ROOT / 'tests/canonical_status_ui.cjs')], capture_output=True,
                            text=True, timeout=30, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_history_and_report_http_selectors_reject_mutable_or_duplicate_identity():
    import sys
    for directory in (ROOT, ROOT / 'api', ROOT / 'runtime', ROOT / 'runtime/lib'):
        sys.path.insert(0, str(directory))
    from borg_backup_ui import BackupUIHandler
    handler = BackupUIHandler.__new__(BackupUIHandler)
    handler.config = {}
    handler._require_data_dir_ready = lambda: None
    for query in ('type=config', 'job_id=x&job_id=y', 'scope=all&scope=configured'):
        with pytest.raises(ValueError):
            handler._get_history(query)
    for query in ('job=config', 'job_id=config', 'job_id=x&job_id=y'):
        with pytest.raises(ValueError):
            handler._get_repo_stats(query)
