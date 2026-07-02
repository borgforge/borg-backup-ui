from io import BytesIO
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import borg_backup_ui


def test_restore_download_timeout_default_and_minimum() -> None:
    assert borg_backup_ui._restore_download_timeout_seconds({}) == 6 * 60 * 60
    assert borg_backup_ui._restore_download_timeout_seconds({"RESTORE_DOWNLOAD_TIMEOUT_SECONDS": "5"}) == 60
    assert borg_backup_ui._restore_download_timeout_seconds({"RESTORE_DOWNLOAD_TIMEOUT_SECONDS": "120"}) == 120
    assert borg_backup_ui._restore_download_timeout_seconds({"RESTORE_DOWNLOAD_TIMEOUT_SECONDS": "bad"}) == 6 * 60 * 60


def test_bounded_stderr_collector_keeps_tail() -> None:
    payload = b"a" * 9000 + b"important-tail"
    thread, snapshot = borg_backup_ui._start_bounded_stderr_collector(BytesIO(payload), limit=64)
    thread.join(timeout=1)

    captured = snapshot()

    assert "important-tail" in captured
    assert len(captured.encode("utf-8")) <= 64
