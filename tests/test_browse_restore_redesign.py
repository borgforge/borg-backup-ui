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
        "restore-browser", "restore-target-path", "restore-conflict-mode",
        "restore-dry-run", "restore-preserve-owner", "restore-confirm-check",
        "restore-start-btn", "restore-precheck-output",
    ):
        assert f'id="{element_id}"' in html
    for contract in (
        "/api/restore/archives", "/api/restore/files", "/api/restore/download-check",
        "/api/restore/precheck", "/api/restore/start", "/api/restore/state",
        "/api/restore/runs",
    ):
        assert contract in script


def test_browse_restore_uses_configured_icons_and_structured_precheck() -> None:
    script = _read("ui/js/pages/restore.js")
    assert "resolveJobIcon(job)" in script
    assert "resolveJobIconColor(job)" in script
    assert "renderRestorePrecheck" in script
    assert "restore-precheck-verdict" in script
    assert "restore-system-check-facts" in script


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
    assert "restore-recent-runs" in css
    assert "function restoreLoadRuns()" in script
    assert "function restoreOpenRun(restoreId)" in script
    assert "resumeLiveLog" in script
    assert "data-restore-run-action=\"open\"" in script
