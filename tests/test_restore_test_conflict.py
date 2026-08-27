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
    conflict_handler = source.split(
        "function handleRestoreTestAlreadyRunning", 1
    )[1].split("function restoreTestsLocationLabel", 1)[0]

    assert "function handleRestoreTestAlreadyRunning" in source
    assert "restore_test_already_running" in source
    assert "resumeRestoreTestLiveLog('alreadyRunningOpenLog');" in conflict_handler


def test_restore_tests_ui_opens_live_log_when_refresh_detects_running_test() -> None:
    source = (ROOT / "ui/js/pages/restore-tests.js").read_text(encoding="utf-8")
    refresh_handler = source.split("async function refreshRestoreTests", 1)[1].split(
        "function switchRestoreTestsSubtab", 1
    )[0]

    assert "function resumeRestoreTestLiveLog" in source
    assert "_openRTLogPanel();" in source
    assert "resumeRestoreTestLiveLog('runningWithoutFinalLog');" in refresh_handler


def test_restore_tests_live_log_transport_errors_do_not_show_false_failure() -> None:
    source = (ROOT / "ui/js/pages/restore-tests.js").read_text(encoding="utf-8")
    german = (ROOT / "ui/i18n/de.json").read_text(encoding="utf-8")
    english = (ROOT / "ui/i18n/en.json").read_text(encoding="utf-8")

    assert "function handleRTLogTransportError(es)" in source
    assert "es.addEventListener('open'" in source
    assert "typeof e.data === 'string' && e.data" in source
    assert "setRTLogStatus('running', null);\n  restoreTestsState.logTransportCheckTimer = setTimeout" in source
    assert "if (restoreTestsState.logTransportCheckTimer) {\n    return;" in source
    assert "if (state.running) {\n        setRTLogStatus('running', null);" in source
    assert "fetch('/api/restore-tests/running')" in source
    assert "setRTLogStatus('unknown', null)" in source
    assert '"logReconnecting"' not in german
    assert '"logStatusUnknown": "Live-Protokoll getrennt - Status aktualisieren"' in german
    assert '"logReconnecting"' not in english
    assert '"logStatusUnknown": "Live log disconnected - refresh status"' in english
