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
    ):
        assert key in english
        assert key in german
