from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dashboard_jobs_styles_load_after_design_foundation() -> None:
    html = _read("ui/index.html")
    assert html.index('/ui/design-system.css') < html.index('/ui/dashboard-jobs.css')
    assert '<link rel="stylesheet" href="/ui/dashboard-jobs.css">' in html


def test_dashboard_keeps_location_inventory_contract() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/dashboard.js")

    for element_id in (
        "dashboard-location-list",
        "dashboard-selection-title",
        "dashboard-selection-count",
        "backup-grid",
    ):
        assert f'id="{element_id}"' in html

    for contract in (
        "data-dashboard-location",
        "repository_check_status",
        "restore_verification_status",
        "skip_reason_code",
        "error_message",
        "never_run",
        "enabled === false",
    ):
        assert contract in script


def test_jobs_keeps_location_actions_and_live_log_contract() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/jobs.js")

    for element_id in (
        "jobs-location-list",
        "jobs-selection-title",
        "jobs-selection-count",
        "jobs-grid",
        "log-panel",
        "log-output",
    ):
        assert f'id="{element_id}"' in html

    for contract in (
        "data-jobs-location",
        'data-jobs-action="start-job"',
        'data-jobs-action="toggle-menu"',
        'data-jobs-action="edit-job"',
        'data-jobs-action="show-schedule"',
        'data-jobs-action="adopt-legacy"',
        'data-jobs-action="delete-job"',
        "group-log-slot",
    ):
        assert contract in script


def test_dashboard_jobs_layout_is_tablet_and_mobile_responsive() -> None:
    css = _read("ui/dashboard-jobs.css")
    foundation = _read("ui/design-system.css")
    assert "@media (max-width: 1023px)" in css
    assert "@media (max-width: 767px)" in css
    assert "overflow-x: auto" in foundation
    assert ".dashboard-inventory-table" in css
    assert ".jobs-redesign-row" in css
    assert "var(--ui-state-running-bg)" in css
    assert "var(--ui-state-neutral-bg)" in css


def test_dashboard_jobs_locale_contract_matches() -> None:
    english = _read("ui/i18n/en.json")
    german = _read("ui/i18n/de.json")
    for key in (
        '"allLocations"',
        '"inventorySubtitle"',
        '"workspaceSubtitle"',
        '"operatingState"',
        '"noLocationBackups"',
        '"noLocationJobs"',
        '"lastRunTime"',
        '"runDuration"',
        '"lastTestLabel"',
        '"validUntilLabel"',
        '"durationSecondsShort"',
    ):
        assert key in english
        assert key in german
    assert '"locationStoragebox": "Storagebox"' in english


def test_dashboard_labels_relative_time_and_duration_separately() -> None:
    script = _read("ui/js/pages/dashboard.js")
    css = _read("ui/dashboard-jobs.css")

    assert "function dashboardRelativeRunTime(timestamp)" in script
    assert "new Intl.RelativeTimeFormat" in script
    assert "function dashboardRunDuration(seconds)" in script
    assert "dashboard.lastRunTime" in script
    assert "dashboard.runDuration" in script
    assert "backup.time_ago" not in script
    assert ".dashboard-run-facts" in css


def test_dashboard_keeps_run_restore_and_storage_facts_aligned() -> None:
    script = _read("ui/js/pages/dashboard.js")
    css = _read("ui/dashboard-jobs.css")

    assert "dashboard-restore-facts" in script
    assert "details.map(([label, value])" in script
    assert "dashboard.deduplicated" in script
    assert "dashboard-fact-row" in script
    assert "grid-template-columns: 6.5rem minmax(0, 1fr)" in css
    assert ".dashboard-inventory-table th:nth-child(3) { width: 16%; }" in css
    assert ".dashboard-inventory-table th:nth-child(4) { width: 19%; }" in css
    assert ".dashboard-inventory-table th:nth-child(5) { width: 17%; }" in css
    assert ".dashboard-inventory-table .loc-badge" in css
    assert "white-space: nowrap" in css
