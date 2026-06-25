from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_restore_tests_redesign_styles_are_loaded() -> None:
    html = _read("ui/index.html")
    assert html.index('/ui/design-system.css') < html.index('/ui/restore-tests-redesign.css')


def test_restore_tests_keeps_sidebar_modes_and_actions() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/restore-tests.js")
    for element_id in (
        "rt-subtab-plan-btn", "rt-subtab-reports-btn", "rt-sidebar-search",
        "rt-sidebar-job-list", "restore-tests-plan", "restore-tests-reports",
        "rt-run-btn", "rt-log-panel", "rt-log-output",
    ):
        assert f'id="{element_id}"' in html
    for contract in (
        "data-rt-sidebar-job", 'data-rt-plan-action="save"',
        'data-rt-plan-action="run"', "/api/restore-tests/policy",
        "/api/restore-tests/run-job", "/api/restore-tests/log/stream",
        "renderRTReportRow", "rtStepChecksumsBlock", "rtStepEntriesBlock",
    ):
        assert contract in script


def test_restore_tests_sidebar_uses_configured_job_icons() -> None:
    script = _read("ui/js/pages/restore-tests.js")
    assert "resolveJobIcon(job)" in script
    assert "resolveJobIconColor(job)" in script
    assert "typeIcon(icon)" in script
    assert "!j.is_utility" in script


def test_restore_tests_layout_is_responsive_and_prioritizes_summaries() -> None:
    css = _read("ui/restore-tests-redesign.css")
    assert "@media (max-width: 1100px)" in css
    assert ".rt-redesign-layout { grid-template-columns: minmax(0, 1fr); }" in css
    assert "@media (max-width: 767px)" in css
    assert ".rt-plan-summary" in css
    assert ".rt-sidebar-job-list" in css
    assert "overflow-x: auto" in css
    assert "#restore-tests-summary" in css


def test_verification_report_matches_approved_detail_hierarchy() -> None:
    script = _read("ui/js/pages/restore-tests.js")
    css = _read("ui/restore-tests-redesign.css")
    for contract in (
        "rt-report-result", "rt-report-verdict", "rt-report-sections",
        "rt-steps-heading", "rt-technical-evidence", "renderRTTechnicalEvidence",
    ):
        assert contract in script or contract in css
    assert "const successful = t.test_result === 'success'" in script
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in css
