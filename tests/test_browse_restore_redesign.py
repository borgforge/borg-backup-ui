from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_browse_restore_redesign_styles_are_loaded() -> None:
    html = _read("ui/index.html")
    assert html.index("/ui/design-system.css") < html.index("/ui/browse-restore-redesign.css")


def test_browse_restore_keeps_five_step_workflow_and_api_contracts() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/restore.js")
    for element_id in (
        "restore-sidebar-job-list", "restore-job-sel", "restore-archive-sel",
        "restore-archive-filter-summary",
        "restore-browser", "restore-target-path", "restore-conflict-mode",
        "restore-dry-run", "restore-preserve-owner", "restore-confirm-check",
        "restore-start-btn", "restore-precheck-output",
    ):
        assert f'id="{element_id}"' in html
    for contract in (
        "/api/restore/archives", "/api/restore/files", "/api/restore/download-check",
        "/api/restore/precheck", "/api/restore/start", "/api/restore/state",
        "/api/restore/runs", "/api/restore/history", "/api/restore/history/detail",
    ):
        assert contract in script


def test_browse_restore_uses_configured_icons_and_structured_precheck() -> None:
    script = _read("ui/js/pages/restore.js")
    css = _read("ui/browse-restore-redesign.css")
    assert "resolveJobIcon(job)" in script
    assert "resolveJobIconColor(job)" in script
    assert "renderRestorePrecheck" in script
    assert "restore-precheck-verdict" in script
    assert "restore-system-check-facts" in script
    assert "function restoreStatusIcon(status)" in script
    assert "restoreStatusIcon(ok ? 'success' : 'error')" in script
    assert "ok ? '\\u2713' : '!'" not in script
    assert ".restore-precheck-verdict-mark svg" in css
    assert ".restore-precheck-verdict.error .restore-precheck-verdict-mark { color: var(--ui-state-error-fg); }" in css
    assert ".restore-precheck-verdict-mark { display: grid; place-items: center; width: 2.125rem; height: 2.125rem; color: var(--ui-state-success-fg); }" in css


def test_browse_restore_shows_archive_filters() -> None:
    script = _read("ui/js/pages/restore.js")
    css = _read("ui/browse-restore-redesign.css")
    german = _read("ui/i18n/de.json")
    english = _read("ui/i18n/en.json")
    assert "restoreState.archiveFilters" in script
    assert "data.archive_filters" in script
    assert "archiveFilterCurrent" in script
    assert "archiveFilterPrevious" in script
    assert ".restore-archive-filter-summary" in css
    assert ".restore-archive-filter-chip.is-current" in css
    assert '"archiveFiltersLabel": "Archivfilter"' in german
    assert '"archiveFiltersLabel": "Archive filters"' in english


def test_browse_restore_precheck_shows_backend_validation_reason() -> None:
    script = _read("ui/js/pages/restore.js")
    assert "function restorePrecheckErrorMessage(payload, status = 0)" in script
    helper = script.split("function restorePrecheckErrorMessage(payload, status = 0)", 1)[1].split("function restoreStatusIcon", 1)[0]
    assert "code === 'bad_request' && serverMessage" in helper
    assert "return apiErrorMessage(payload, status);" in helper
    precheck = script.split("async function restoreRunPrecheck()", 1)[1].split("function renderRestorePrecheck", 1)[0]
    assert "throw new Error(restorePrecheckErrorMessage(data, res.status));" in precheck


def test_browse_restore_layout_is_responsive_and_contained() -> None:
    css = _read("ui/browse-restore-redesign.css")
    assert "@media (max-width: 1100px)" in css
    assert "@media (max-width: 767px)" in css
    assert ".restore-browser-layout" in css
    assert ".restore-review-grid" in css
    assert "overflow-x: auto" in css
    assert ".restore-precheck-output { width: 100%; max-width: 100%; min-width: 0;" in css


def test_browse_restore_keeps_review_and_completion_status_in_sync() -> None:
    script = _read("ui/js/pages/restore.js")
    assert "function setRestoreHeaderStatus(state)" in script
    assert "setRestoreHeaderStatus('success')" in script
    assert "function restorePrecheckInputsChanged()" in script
    precheck_change = script.split("function restorePrecheckInputsChanged()", 1)[1]
    assert "_restoreRenderSelectionSummary();" in precheck_change


def test_browse_restore_can_resume_restore_runs() -> None:
    html = _read("ui/index.html")
    css = _read("ui/browse-restore-redesign.css")
    script = _read("ui/js/pages/restore.js")
    assert 'id="restore-runs-panel"' in html
    assert "restore-run-card" in css
    assert "restore-recent-runs" not in css
    assert "restore-live-mode" in css
    assert "function restoreLoadRuns()" in script
    assert "function restoreOpenRun(restoreId)" in script
    assert "function restoreSetLiveMode(enabled)" in script
    assert "next === 5 && !restoreState.liveMode" in script
    assert "resumeLiveLog" in script
    assert "data-restore-run-action=\"open\"" in script


def test_browse_restore_has_dedicated_restore_history() -> None:
    html = _read("ui/index.html")
    css = _read("ui/browse-restore-redesign.css")
    script = _read("ui/js/pages/restore.js")
    bindings = _read("ui/js/components/app-bindings.js")
    german = _read("ui/i18n/de.json")
    english = _read("ui/i18n/en.json")
    assert 'id="restore-view-wizard-btn"' in html
    assert 'id="restore-view-history-btn"' in html
    assert 'id="restore-history-panel" class="restore-history-panel hidden"' in html
    assert 'id="restore-history-content"' in html
    assert 'id="restore-history-delete-confirm-modal"' in html
    assert 'id="restore-history-delete-confirm-delete-btn"' in html
    assert '<div class="modal-info-item"><span data-i18n="restore.restoreIdLabel">Restore-ID:</span><strong id="restore-history-delete-confirm-id"></strong></div>' in html
    assert ".restore-view-tabs" in css
    assert ".restore-history-card" in css
    assert ".restore-history-detail-grid" in css
    assert "function restoreSwitchView(view)" in script
    assert "function restoreLoadHistory()" in script
    assert "function openRestoreHistoryDeleteConfirmModal(label, id)" in script
    assert "function closeRestoreHistoryDeleteConfirmModal(confirmed = false)" in script
    assert "function restoreLoadHistoryDetail(restoreId)" in script
    assert "function onRestoreHistoryClick(event)" in script
    delete_fn = script.split("async function restoreDeleteHistoryEntry(restoreId)", 1)[1].split(
        "function openRestoreHistoryDeleteConfirmModal", 1
    )[0]
    assert "await openRestoreHistoryDeleteConfirmModal(label, id)" in delete_fn
    assert "window.confirm" not in delete_fn
    assert "closeRestoreHistoryDeleteConfirmModal(true)" in bindings
    assert "deleteHistoryRunModalTitle" in german
    assert "deleteHistoryRunModalMessage" in german
    assert "deleteHistoryRunModalWarning" in german
    assert '"restoreIdLabel": "Restore-ID:"' in german
    assert "Verlaufsdaten von Borg Backup UI" in german
    assert "deleteHistoryRunModalTitle" in english
    assert "deleteHistoryRunModalMessage" in english
    assert "deleteHistoryRunModalWarning" in english
    assert '"restoreIdLabel": "Restore ID:"' in english
    assert "Borg Backup UI history data" in english
