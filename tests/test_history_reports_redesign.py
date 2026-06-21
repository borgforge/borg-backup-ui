from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_history_reports_styles_load_after_foundation() -> None:
    html = _read("ui/index.html")
    assert html.index('/ui/design-system.css') < html.index('/ui/history-reports.css')


def test_history_preserves_filter_pagination_and_detail_contracts() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/history.js")
    for element_id in (
        "history-location-list", "history-filter-type", "history-filter-location",
        "history-filter-status", "history-content", "history-selection-count",
    ):
        assert f'id="{element_id}"' in html
    for contract in (
        "data-history-location", 'data-history-action="toggle-detail"',
        'data-history-action="open-log"', 'data-history-action="page-prev"',
        'data-history-action="page-next"', "repository_check_status",
        "renderRestoreReportSteps",
    ):
        assert contract in script


def test_reports_preserves_selection_search_and_analysis_contracts() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/reports.js")
    for element_id in (
        "bericht-job-sel", "report-job-search", "report-job-list",
        "bericht-body", "bericht-borginfo-btn", "bericht-size-chart",
        "bericht-dedup-chart", "bericht-dur-chart", "bericht-status-chart",
    ):
        assert f'id="{element_id}"' in html
    for contract in (
        "data-report-job", "/api/reports/data?job=", "/api/restore/repo-stats?job=",
        "_berichtRenderGrowthCards", "_berichtRestoreVerification",
        "_berichtStatusChart",
    ):
        assert contract in script


def test_history_reports_layout_is_responsive_and_compact() -> None:
    css = _read("ui/history-reports.css")
    assert "@media (max-width: 1023px)" in css
    assert "@media (max-width: 767px)" in css
    assert "overflow-x: auto" in css
    assert ".history-detail-panel" in css
    assert ".report-job-list" in css
    assert "max-height: 11rem" in css
