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

    assert "function renderDashboardLocationGroups(backups)" in script
    assert "function renderDashboardLocationGroupRow(location, count)" in script
    assert 'class="dashboard-location-group-row"' in script
    assert 'colspan="5"' in script
    assert "dashboard.locationColumn" not in script


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
        'data-jobs-action="delete-job"',
        "group-log-slot",
    ):
        assert contract in script
    assert 'data-jobs-action="adopt-legacy"' not in script


def test_jobs_log_shows_resource_lock_exit_as_skipped() -> None:
    script = _read("ui/js/pages/jobs.js")
    german = _read("ui/i18n/de.json")
    english = _read("ui/i18n/en.json")

    assert "function isResourceLockSkipExit(exitCode)" in script
    assert "Job is being skipped: resource locked by" in script
    assert "setLogStatus(state, code)" in script
    assert "badge.className = 'badge skipped'" in script
    assert '"logSkipped": "Übersprungen (Exit {code})"' in german
    assert '"logSkipped": "Skipped (exit {code})"' in english


def test_jobs_live_log_transport_errors_reconnect_instead_of_false_failure() -> None:
    script = _read("ui/js/pages/jobs.js")
    backend = _read("api/jobs_api.py")
    german = _read("ui/i18n/de.json")
    english = _read("ui/i18n/en.json")

    assert "SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0" in backend
    assert "time.monotonic() - last_heartbeat >= SSE_HEARTBEAT_INTERVAL_SECONDS" in backend
    assert "function handleLogTransportError(es, jobKey)" in script
    assert "es.addEventListener('open'" in script
    assert "typeof e.data === 'string' && e.data" in script
    assert "setLogStatus('reconnecting')" in script
    assert "if (state.running) {\n        setLogStatus('running');" in script
    assert "fetch('/api/jobs/running')" in script
    assert "setLogStatus('error', '?');" in script
    assert "logReconnecting" in script
    assert '"logReconnecting": "Live-Protokoll verbindet neu..."' in german
    assert '"logReconnecting": "Live log reconnecting..."' in english


def test_wizard_and_jobs_support_docker_exclusion_mode() -> None:
    html = _read("ui/index.html")
    wizard = _read("ui/js/pages/wizard.js")
    jobs = _read("ui/js/pages/jobs.js")
    german = _read("ui/i18n/de.json")
    english = _read("ui/i18n/en.json")

    assert '<option value="except_selected" data-i18n="wizard.runtimeExceptSelectedDocker">' in html
    assert "mode === 'except_selected'" in wizard
    assert "runtimeExclusionCount" in wizard
    assert "runtimeExceptSelectedDocker" in wizard
    assert "dockerExceptSelectedWarning" in jobs
    assert '"runtimeExceptSelectedDocker": "Alle außer ausgewählte Container"' in german
    assert '"dockerExceptSelectedWarning": "Alle Docker-Container außer diesen werden' in german
    assert '"runtimeExceptSelectedDocker": "All except selected containers"' in english
    assert '"dockerExceptSelectedWarning": "All Docker containers except these will' in english


def test_wizard_prunes_stale_docker_runtime_selections() -> None:
    script = _read("ui/js/pages/wizard.js")

    assert "function _wizardPruneMissingDockerSelections()" in script
    assert "_wizardPruneMissingDockerSelections();" in script
    assert "if (!rows.length) return;" in script
    assert ".filter(name => available.has(name))" in script


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


def test_dashboard_summary_uses_subtle_status_surfaces() -> None:
    css = _read("ui/dashboard-jobs.css")
    script = _read("ui/js/pages/dashboard.js")
    german = _read("ui/i18n/de.json")
    english = _read("ui/i18n/en.json")

    assert "statTile('total'" in script
    assert "statTile('success'" in script
    assert "statTile('skipped'" in script
    assert "statTile('warning'" in script
    assert "statTile('error'" in script
    assert "statTile('unknown'" in script
    assert ".dashboard-summary-grid .stat-tile.total" in css
    assert ".dashboard-summary-grid .stat-tile.success" in css
    assert ".dashboard-summary-grid .stat-tile.skipped" in css
    assert ".dashboard-summary-grid .stat-tile.warning" in css
    assert ".dashboard-summary-grid .stat-tile.error" in css
    assert "background: var(--ui-state-success-bg)" in css
    assert "background: var(--ui-state-neutral-bg)" in css
    assert "background: var(--ui-state-info-bg)" in css
    assert "background: var(--ui-state-warning-bg)" in css
    assert "background: var(--ui-state-error-bg)" in css
    assert "border-radius: var(--ui-radius-sm)" in css
    assert "min-height: 5.125rem" in css
    assert "--dashboard-summary-fg: var(--ui-state-success-fg)" in css
    assert "--dashboard-summary-fg: var(--ui-state-warning-fg)" in css
    assert "--dashboard-summary-fg: var(--ui-state-error-fg)" in css
    assert "color: var(--dashboard-summary-fg)" in css
    assert "justify-content: center" in css
    assert "text-align: center" in css
    assert ".dashboard-summary-title" in css
    assert "font-size: var(--ui-font-size-md)" in css
    assert "font-weight: var(--ui-font-weight-bold)" in css
    assert '"restoreVerified": "Verifiziert"' in german
    assert '"restoreOverdue": "Überfällig"' in german
    assert '"restoreFailed": "Fehlgeschlagen"' in german
    assert '"restoreOpen": "Offen"' in german
    assert '"restoreNotScheduled": "Nicht geplant"' in german
    assert '"restoreVerified": "Verified"' in english
    assert '"restoreOverdue": "Overdue"' in english
    assert '"restoreFailed": "Failed"' in english
    assert '"restoreOpen": "Pending"' in english
    assert '"restoreNotScheduled": "Not scheduled"' in english


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
        '"backupOverdue"',
        '"backupOverdueDetails"',
    ):
        assert key in english
        assert key in german
    assert '"locationStoragebox": "Storagebox"' in english


def test_dashboard_uses_configured_job_icons() -> None:
    script = _read("ui/js/pages/dashboard.js")

    assert "b.icon = job.icon || b.icon || '';" in script
    assert "b.icon_color = job.icon_color || b.icon_color || '';" in script
    assert "const iconKey = typeof resolveJobIcon === 'function' ? resolveJobIcon(backup)" in script
    assert "typeIcon(iconKey)" in script
    assert "iconColorClass" in script


def test_dashboard_labels_relative_time_and_duration_separately() -> None:
    script = _read("ui/js/pages/dashboard.js")
    css = _read("ui/dashboard-jobs.css")
    german = _read("ui/i18n/de.json")
    english = _read("ui/i18n/en.json")
    help_de = _read("ui/docs/help.md")
    help_en = _read("ui/docs/help.en.md")
    manual_de = _read("docs/user-manual/de/user-manual.md")
    manual_en = _read("docs/user-manual/en/user-manual.md")

    assert "function dashboardRelativeRunTime(timestamp)" in script
    assert "new Intl.RelativeTimeFormat" in script
    assert "function dashboardRunDuration(seconds)" in script
    assert "function fetchDashboardSchedules()" in script
    assert "window.BBUI.core.setSchedulesData(schedulesData);" in script
    assert "function dashboardFormatNextRunDate(date)" in script
    assert "function dashboardNextRun(jobKey, enabled)" in script
    assert "typeof calcNextRun === 'function' ? calcNextRun(sched.cron)" in script
    assert "return `${datePart} ${timePart}`;" in script
    assert "const rowClass = cls ? ` ${cls}` : '';" in script
    assert "dashboard-fact-row${rowClass}" in script
    assert "'next-run'" in script
    assert "dashboard.lastRunTime" in script
    assert "dashboard.runDuration" in script
    assert "dashboard.nextRunTime" in script
    assert "dashboard.notScheduled" in script
    assert "dashboard.scheduleDisabled" in script
    assert "backup.time_ago" not in script
    assert ".dashboard-run-facts" in css
    assert ".dashboard-run-facts .dashboard-fact-row > span" in css
    assert "overflow-wrap: anywhere" in css
    assert ".dashboard-run-facts .dashboard-fact-row.next-run > span" in css
    assert "white-space: nowrap" in css
    assert '"nextRunTime": "Nächster Lauf"' in german
    assert '"notScheduled": "Nicht geplant"' in german
    assert '"scheduleDisabled": "Zeitplan deaktiviert"' in german
    assert '"nextRunTime": "Next run"' in english
    assert '"notScheduled": "Not scheduled"' in english
    assert '"scheduleDisabled": "Schedule disabled"' in english
    assert "nächste geplante Lauf" in help_de
    assert "next scheduled run" in help_en
    assert "Wann läuft ein geplanter Job das nächste Mal?" in manual_de
    assert "When will a scheduled job run next?" in manual_en


def test_dashboard_shows_backup_overdue_before_last_run_success() -> None:
    script = _read("ui/js/pages/dashboard.js")

    assert "backup.backup_overdue" in script
    assert "dashboardT('dashboard.backupOverdue')" in script
    assert "dashboardT('dashboard.backupOverdueDetails'" in script
    assert "function dashboardAbsoluteTimestamp(timestamp)" in script


def test_dashboard_keeps_run_restore_and_storage_facts_aligned() -> None:
    script = _read("ui/js/pages/dashboard.js")
    css = _read("ui/dashboard-jobs.css")

    assert "dashboard-restore-facts" in script
    assert "details.map(([label, value])" in script
    assert "dashboard.deduplicated" in script
    assert "dashboard-fact-row" in script
    assert "grid-template-columns: 6.5rem minmax(0, 1fr)" in css
    assert ".dashboard-inventory-table th:nth-child(2) { width: 18%; }" in css
    assert ".dashboard-inventory-table th:nth-child(3) { width: 21%; }" in css
    assert ".dashboard-inventory-table th:nth-child(4) { width: 18%; }" in css
    assert ".dashboard-inventory-table th:nth-child(5) { width: 19%; }" in css
    assert ".dashboard-location-group-row td" in css
    assert ".dashboard-location-group__identity" in css
    assert "white-space: nowrap" in css
