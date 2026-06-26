from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_storage_groups_locations_and_scopes_smb_profiles() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/storage.js")
    assert '<small data-i18n="storage.locationsHint">' not in html
    assert "function renderStorageRepositoryRows(repos, profiles)" in script
    assert "STORAGE_LOCATION_ORDER.map((location)" in script
    assert "const showSmbProfiles = (storageState.selectedLocation || 'all') === 'smb';" in script


def test_storage_test_details_are_visible_after_success_or_failure() -> None:
    script = _read("ui/js/pages/storage.js")
    css = _read("ui/remaining-ui-redesign.css")
    test_repo = script.split("async function testRepo", 1)[1].split(
        "function openStorageTestDetails", 1
    )[0]
    assert "if (detailsBtn) detailsBtn.classList.remove('hidden');" in test_repo
    assert "el.dataset.fullOutput = String(data.output || '');" in test_repo
    assert 'class="test-result hidden"' in script
    assert ".storage-row-actions .test-result:empty { display: none; }" in css


def test_storage_repositories_use_configured_job_icons() -> None:
    script = _read("ui/js/pages/storage.js")
    assert "fetch('/api/jobs')" in script
    assert "function storageJobForRepository(repo)" in script
    assert "resolveJobIcon(job || repo)" in script
    assert "resolveJobIconColor(job || repo)" in script
    repository_row = script.split("function renderStorageRepositoryRow", 1)[1].split(
        "function storageJobForRepository", 1
    )[0]
    assert "typeIcon(icon)" in repository_row
    assert "storageLocationIcon(repo.location)" not in repository_row


def test_restore_tests_use_quiet_overdue_tile_and_consistent_sidebar_states() -> None:
    script = _read("ui/js/pages/restore-tests.js")
    css = _read("ui/restore-tests-redesign.css")
    assert "const configured = !!planJob" in script
    assert "planJob?.is_overdue ? 'warning' : configured ? 'success' : 'disabled'" in script
    assert "planSummary.overdue > 0 ? 'has-value' : ''" in script
    assert ".rt-plan-summary .attention { background: var(--ui-color-surface); }" in css
    assert ".rt-plan-summary .attention.has-value b" in css
    assert ".rt-technical-evidence .rt-step-details" in css
    assert "display: flex" in css


def test_dashboard_and_jobs_preserve_readable_content() -> None:
    css = _read("ui/dashboard-jobs.css")
    dashboard = _read("ui/js/pages/dashboard.js")
    jobs = _read("ui/js/pages/jobs.js")
    german = _read("ui/i18n/de.json")
    assert "min-width: 1280px" in css
    assert ".dashboard-inventory-table th:nth-child(1) { width: 22%; }" in css
    assert "dashboard-storage-facts" in dashboard
    assert "function renderDashboardRepositoryCheck" in dashboard
    assert "dashboard-check-date" in css
    assert ".dashboard-backup-identity > span:last-child" in css
    assert "text-overflow: ellipsis" in css
    assert "white-space: nowrap" in css
    assert ".jobs-redesign-main .job-description" in css
    assert "-webkit-line-clamp: unset" in css
    assert "jobs-restore-dates" in css
    assert "details.map((detail)" in jobs
    assert '"policy": "Richtlinie"' in german


def test_history_formats_status_errors_and_detail_values() -> None:
    script = _read("ui/js/pages/history.js")
    css = _read("ui/history-reports.css")
    german = _read("ui/i18n/de.json")
    assert '"statusSuccess": "Erfolgreich"' in german
    assert "function renderHistoryError(message, isNotice = false)" in script
    assert "history-detail-group--log" in script
    assert "detailGroup(historyT('archive'), e.archive_name || '-', 'archive')" in script
    assert "detailGroup(historyT('lastCheck'), e.repository_check_date, 'datetime')" in script
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in css
    assert ".history-detail-group--archive { grid-column: span 2; }" in css
    assert ".history-detail-group--wide { grid-column: 1 / -1; }" in css
    assert "detailGroup(historyT('checkStatus'), e.repository_check_status, 'wide')" in script
    detail_panel = css.split(".history-detail-panel", 1)[1].split(
        ".history-detail-group", 1
    )[0]
    assert "background: var(--ui-color-surface-subtle)" in detail_panel


def test_reports_repository_facts_do_not_leave_a_filler_column() -> None:
    css = _read("ui/history-reports.css")
    block = css.split("#bericht-body .repo-stats-cards", 1)[1].split(
        "#bericht-body .repo-stat-value", 1
    )[0]
    assert "display: flex" in block
    assert "flex-wrap: wrap" in block
    assert "flex: 1 1 12rem" in block
    assert "repeat(6" not in block


def test_language_selector_keeps_names_and_accessible_flag_symbols() -> None:
    html = _read("ui/index.html")
    german = _read("ui/i18n/de.json")
    english = _read("ui/i18n/en.json")
    assert 'id="ui-language-select"' in html
    assert 'data-i18n-aria-label="language.label"' in html
    assert "🇩🇪 Deutsch" in german
    assert "🇬🇧 English" in german
    assert "🇩🇪 German" in english
    assert "🇬🇧 English" in english
