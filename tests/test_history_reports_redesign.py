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
    assert "data.location_counts" in script
    assert "locationIcon(location)" in script
    assert "'custom'" not in script.split("const HISTORY_LOCATIONS", 1)[1].split(";", 1)[0]
    for obsolete_id in (
        "bericht-size-chart", "bericht-dedup-chart",
        "bericht-dur-chart", "bericht-status-chart",
    ):
        assert f'id="{obsolete_id}"' not in html
    assert 'class="report-metric-ledger"' in html
    assert 'class="report-trend-table"' in html
    assert 'class="report-status-table"' in html


def test_reports_preserves_selection_search_and_analysis_contracts() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/reports.js")
    for element_id in (
        "bericht-job-sel", "report-job-search", "report-job-list",
        "bericht-body", "bericht-borginfo-btn", "br-run-badge",
        "bericht-trend-body", "bericht-status-body",
    ):
        assert f'id="{element_id}"' in html
    for contract in (
        "data-report-job", "/api/reports/data?job=", "/api/restore/repo-stats?job=",
        "_berichtRenderGrowthCards", "_berichtRestoreVerification",
        "_berichtTrendTable", "_berichtSparkline", "_berichtStatusTable",
        "resolveJobIcon(job)", "resolveJobIconColor(job)", "typeIcon(icon)",
        "configured?.icon", "configured?.icon_color",
    ):
        assert contract in script


def test_history_reports_layout_is_responsive_and_compact() -> None:
    css = _read("ui/history-reports.css")
    assert "@media (max-width: 1023px)" in css
    assert "@media (max-width: 767px)" in css
    assert "overflow-x: auto" in css
    assert ".history-detail-panel" in css
    assert ".report-job-list" in css
    assert ".report-job-icon" in css
    assert ".report-metric-ledger" in css
    assert ".report-sparkline" in css
    assert ".report-status-distribution" in css


def test_location_sidebars_reuse_storage_icons() -> None:
    formatting = _read("ui/js/utils/format.js")
    dashboard = _read("ui/js/pages/dashboard.js")
    jobs = _read("ui/js/pages/jobs.js")
    storage = _read("ui/js/pages/storage.js")
    for distinctive_path in (
        'M17 8h1a4 4 0 0 1 0 8h-1',
        'M3 7h18',
        'M22 12h-4l-3 9L9 3l-3 9H2',
    ):
        assert distinctive_path in formatting
        assert distinctive_path in storage
    assert "return locationIcon(location);" in dashboard
    assert "return locationIcon(location);" in jobs
