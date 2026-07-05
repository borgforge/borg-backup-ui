from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_restore_test_already_running_uses_conflict_response() -> None:
    source = (ROOT / "borg_backup_ui.py").read_text(encoding="utf-8")

    assert "class ApiConflictError" in source
    assert '"restore_test_already_running"' in source
    assert "self._send_api_error(409, exc.code" in source
    assert "already running" in source


def test_restore_tests_ui_opens_live_log_on_running_conflict() -> None:
    source = (ROOT / "ui/js/pages/restore-tests.js").read_text(encoding="utf-8")

    assert "function handleRestoreTestAlreadyRunning" in source
    assert "restore_test_already_running" in source
    assert "_openRTLogPanel();" in source
    assert "alreadyRunningOpenLog" in source
    assert "runningWithoutFinalLog" in source

