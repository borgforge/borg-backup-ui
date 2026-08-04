from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_storage_uses_repository_master_detail_navigation() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/storage.js")
    assert '<small data-i18n="storage.locationsHint">' not in html
    assert "function renderStorageLocationSidebar(data, repos)" in script
    assert "function renderStorageRepositoryWorkspace(repo, job)" in script
    assert "function storageGroupRows(data, repos)" in script
    assert 'data-storage-repository-key=' in script
    assert 'data-storage-action="select-repository-tab"' in script
    assert "renderStorageSmbProfiles" not in script


def test_storage_repository_details_focus_on_user_facing_metadata() -> None:
    script = _read("ui/js/pages/storage.js")
    css = _read("ui/remaining-ui-redesign.css")
    details_panel = script.split("function renderStorageRepositoryOverview(repo, job)", 1)[1].split(
        "function renderStorageRepositoryArchives", 1
    )[0]
    assert "function storageRepositoryEncryption(repo, job)" in script
    assert "storage.repositoryDisplayNameLabel" in details_panel
    assert "storage.repositoryDirectoryLabel" in details_panel
    assert "storage.storageNameLabel" in details_panel
    assert "storage.jobNameLabel" in details_panel
    assert "storage.location" not in details_panel
    assert "storage.repositoryPathLabel" in details_panel
    assert "storage.repositoryEncryption" in details_panel
    assert "storage.repositoryRelativePath" not in details_panel
    assert "'span-3'" in details_panel
    assert "storage.repositoryIdLabel" not in details_panel
    assert "storage.storageIdLabel" not in details_panel
    assert "storage.jobIdLabel" not in details_panel
    assert "storage.repoConfKeyLabel" not in details_panel
    assert 'data-storage-action="test-repo"' not in script
    assert ".storage-repository-master-detail" in css
    assert ".storage-maintenance-summary-grid" in css


def test_storage_repositories_use_configured_job_icons() -> None:
    script = _read("ui/js/pages/storage.js")
    css = _read("ui/remaining-ui-redesign.css")
    assert "fetch('/api/jobs')" in script
    assert "function storageJobForRepository(repo)" in script
    assert "function storageRepositoryTitle(repo, job)" in script
    assert "resolveJobIcon(job || repo)" in script
    assert "resolveJobIconColor(job || repo)" in script
    assert ".storage-repository-icon-large" in css
    assert "justify-content: center" in css
    title_helper = script.split("function storageRepositoryTitle(repo, job)", 1)[1].split(
        "function storageRepositoryName", 1
    )[0]
    assert "repo?.display_name" in title_helper
    assert "storageLocationLabel" not in title_helper
    repository_row = script.split("function renderStorageLocationSidebar(data, repos)", 1)[1].split(
        "function onStorageLocationClick", 1
    )[0]
    assert "storageRepositoryIcon(repo, job)" in repository_row
    assert "storageRepositoryTitle(repo, job)" in repository_row
    assert "storageRepositoryName(repo)" in repository_row
    assert "storageRepositoryStatus(repo)" in repository_row
    assert ".storage-repository-nav-item" in css
    assert "function toggleStorageRepositoryDetails" not in script


def test_repository_manager_uses_single_visible_repository_path_field() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/storage.js")
    german = _read("ui/i18n/de.json")
    css = _read("ui/remaining-ui-redesign.css")
    assert 'id="repository-manager-repository-name"' in html
    assert 'type="hidden" id="repository-manager-repository-name"' in html
    assert 'id="repository-manager-relative-path"' in html
    assert "storage.repositoryRelativePath" in html
    assert "Repository-Pfad im Speicherziel" in german
    assert "function repositoryManagerNameFromRelativePath" in script
    assert "function repositoryManagerPathInputChanged" in script
    assert "addEventListener('input', repositoryManagerPathInputChanged)" in _read("ui/js/components/app-bindings.js")
    assert "function repositoryManagerPathChanged" in script
    assert "repositoryManagerPathChanged();" in script
    assert ".repository-manager-form-grid" in css
    assert "--ui-color-primary" not in css
    assert "background: var(--ui-color-accent);" in css
    assert '"repositorySummaryRepository": "Anzeigename"' in german
    assert '"repositorySummaryPath": "Pfad im Speicherziel"' in german


def test_wizard_source_autocomplete_cancels_stale_requests() -> None:
    script = _read("ui/js/pages/wizard.js")
    german = _read("ui/i18n/de.json")
    english = _read("ui/i18n/en.json")
    assert "function wizardCancelSourceSuggestRequest" in script
    assert "new AbortController()" in script
    assert "requestId !== wizardState.sourceSuggestRequest" in script
    assert "}, 180);" in script
    assert "event.key === 'ArrowRight' && rows.length" in script
    assert "input.value = selected" in script
    assert "→ Verzeichnis öffnen" in german
    assert "→ open directory" in english


def test_wizard_source_paths_are_explained_for_normal_users() -> None:
    html = _read("ui/index.html")
    german = _read("ui/i18n/de.json")
    english = _read("ui/i18n/en.json")
    help_de = _read("ui/docs/help.md")
    help_en = _read("ui/docs/help.en.md")

    assert 'data-i18n="wizard.sourcePathsHelp"' in html
    assert '"sourcePaths": "Zu sichernde Ordner"' in german
    assert '"sourcePathsHelp": "Wähle hier die Ordner oder Dateien aus, die dieser Backup-Job sichern soll.' in german
    assert '"noSourcePaths": "Noch keine zu sichernden Ordner hinzugefügt."' in german
    assert '"validationSource": "Bitte mindestens einen Ordner oder eine Datei auswählen, die gesichert werden soll."' in german
    assert '"sourcePaths": "Folders to back up"' in english
    assert '"sourcePathsHelp": "Choose the folders or files this backup job should back up.' in english
    assert "Quellen sind die Ordner oder Dateien" in help_de
    assert "Sources are the folders or files" in help_en


def test_wizard_sources_and_target_use_compact_two_column_layout() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/wizard.js")
    css = _read("ui/style.css")

    step = html.split('id="wizard-step-2"', 1)[1].split('id="wizard-step-3"', 1)[0]
    assert 'class="wizard-step2-layout"' in step
    assert step.index('id="wizard-step2-sources-title"') < step.index('id="wizard-step2-target-title"')
    assert 'class="wizard-path-control"' in step
    assert 'wizard-step2-path-list' in step
    assert "wizard-step-scroll-hint" not in step
    assert "wizardUpdateStep2ScrollHint" not in script
    assert "wizardEnsureScrollHintBinding" not in script
    assert ".wizard-step2-layout" in css
    assert "grid-template-columns: minmax(0, 1.08fr) minmax(0, .92fr)" in css
    assert ".wizard-path-suggest.hidden" in css
    assert "display: none !important" in css
    assert "@media (max-width: 700px)" in css


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
    assert ".dashboard-inventory-table th:nth-child(1) { width: 24%; }" in css
    assert "renderDashboardLocationGroups(visible)" in dashboard
    assert ".dashboard-location-group-row td" in css
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
    assert ".sidebar-language select" in _read("ui/style.css")
    assert "height: 30px" in _read("ui/style.css")


def test_sidebar_footer_keeps_version_only_and_direct_theme_toggle() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/settings.js")
    bindings = _read("ui/js/components/app-bindings.js")
    theme = _read("ui/js/components/theme.js")
    css = _read("ui/style.css")
    german = _read("ui/i18n/de.json")
    english = _read("ui/i18n/en.json")

    version_block = script.split("const el = document.getElementById('app-version-info');", 1)[1].split(
        "const aboutEl = document.getElementById('settings-about-version');", 1
    )[0]
    theme_binding = bindings.split("document.querySelectorAll('[data-theme-choice]')", 1)[1].split(
        "document.getElementById('log-viewer-close-btn')", 1
    )[0]

    assert "app-version" in version_block
    assert "app-author" not in version_block
    assert "app-contact" not in version_block
    assert "mailto:" not in version_block
    assert 'data-theme-choice="light"' in html
    assert 'data-theme-choice="dark"' in html
    assert "sidebar-theme-btn" in html
    assert "updateThemeControls(clean)" in theme
    assert "aria-pressed" in theme
    assert "applyThemePreference?.(choice, true)" in theme_binding
    assert "saveSettings" not in theme_binding
    assert "fetch(" not in theme_binding
    assert ".sidebar-theme-toggle" in css
    assert ".sidebar-theme-btn.active" in css
    assert ".sidebar-language" in css
    assert "grid-template-columns: minmax(0, 1fr)" in css
    assert "width: 100%" in css
    assert "height: 30px" in css
    assert "height: 100%" in css
    assert '"themeLight": "Helles Theme"' in german
    assert '"themeDark": "Dunkles Theme"' in german
    assert '"themeLight": "Light theme"' in english
    assert '"themeDark": "Dark theme"' in english
