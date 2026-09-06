from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_remaining_ui_redesign_styles_are_loaded_last() -> None:
    html = _read("ui/index.html")
    assert html.index("/ui/browse-restore-redesign.css") < html.index(
        "/ui/remaining-ui-redesign.css"
    )


def test_storage_uses_approved_variant_a_and_preserves_controls() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/storage.js")
    for element_id in (
        "storage-location-list",
        "storage-workspace-header",
        "storage-content",
        "storage-add-repository-btn",
        "storage-maintenance-confirm-modal",
        "storage-maintenance-confirm-start-btn",
        "repository-manager-modal",
        "repository-manager-storage",
        "repository-manager-next-btn",
    ):
        assert f'id="{element_id}"' in html
    for contract in (
        "STORAGE_LOCATION_ORDER = ['local', 'usb', 'smb', 'storagebox']",
        "renderStorageRepositoryWorkspace",
        "renderStorageLocationSidebar",
        "renderStorageRepositoryArchives",
        "openStorageMaintenanceConfirm",
        "storage.repositoryArchiveCreated",
        "repositoryPruneDetails",
        "deleted_archives",
        'data-storage-action="select-repository-tab"',
        'data-storage-action="repository-maintenance"',
        "/api/storages/test",
        "/api/storage/check/run",
        "/api/storage/check/stream",
    ):
        assert contract in script
    assert 'id="check-log-panel"' not in html
    assert 'id="check-log-output"' not in html
    assert "window.confirm" not in script
    assert "repository-manager-storage-mode" not in html
    assert "repositoryManagerNewStoragePayload" not in script
    assert "fetch('/api/storages'," not in script
    assert "renderStorageRepositoryActivities" not in script
    assert "repositoryTabActivities" not in script
    assert "storage.repositoryRelativePath', repo.relative_path" not in script
    assert "storage.repositoryPathLabel', repo.path_display || repo.path_raw || '', 'span-3'" in script


def test_storage_prune_confirmation_shows_archive_filter() -> None:
    script = _read("ui/js/pages/storage.js")
    bindings = _read("ui/js/components/app-bindings.js")
    de = _read("ui/i18n/de.json")
    en = _read("ui/i18n/en.json")

    assert "function storageJobsForRepository(repo)" in script
    assert "function storageArchivePrefixFromJob(job)" in script
    assert "function storageArchiveFilterFromJob(job)" in script
    assert "function storageRetentionSummary(job)" in script
    assert "function storageMaintenancePruneDetailsHtml(repo, job)" in script
    assert "function updateStorageMaintenanceRetentionPreview()" in script
    assert 'id="storage-maintenance-retention-job"' in script
    assert 'id="storage-maintenance-retention-preview"' in script
    assert "if (action === 'prune' && confirmation.jobId) payload.job_id = confirmation.jobId" in script
    assert "payload.job_key" not in script
    assert "updateStorageMaintenanceRetentionPreview()" in bindings
    assert "storage.repositoryMaintenanceRetentionSource" in script
    assert "storage.repositoryMaintenanceArchiveFilter" in script
    assert "storage.repositoryMaintenanceRetention" in script
    assert "storage.repositoryMaintenanceMultipleJobsHint" in script
    assert '"repositoryMaintenanceRetentionSource": "Retention-Quelle: {job}"' in de
    assert '"repositoryMaintenanceArchiveFilter": "Archivfilter: {filter}"' in de
    assert '"repositoryMaintenanceRetention": "Retention: {retention}"' in de
    assert '"repositoryMaintenanceRetentionSource": "Retention source: {job}"' in en
    assert '"repositoryMaintenanceArchiveFilter": "Archive filter: {filter}"' in en
    assert '"repositoryMaintenanceRetention": "Retention: {retention}"' in en


def test_repository_information_has_a_background_refresh_loop() -> None:
    backend = _read("borg_backup_ui.py")
    repository_api = _read("api/repositories_api.py")
    assert "def _start_repository_info_refresh_loop(config: dict)" in backend
    assert "_start_repository_info_refresh_loop(config)" in backend
    assert "def _start_apprise_runtime_warmup(config: dict)" in backend
    assert "_start_apprise_runtime_warmup(config)" in backend
    assert "def refresh_due_repository_info(" in repository_api
    assert "max_age_hours: int = 24" in repository_api
    assert "retry_after_hours: int = 1" in repository_api


def test_storage_reuses_location_icons_without_summary_ledger() -> None:
    script = _read("ui/js/pages/storage.js")
    for distinctive_path in (
        '<rect x="2" y="2" width="20" height="8" rx="2"/>',
        '<path d="M17 8h1a4 4 0 0 1 0 8h-1"/>',
        '<path d="M3 7h18"/><path d="M3 12h18"/><path d="M3 17h18"/>',
        '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    ):
        assert distinctive_path in script
    assert "storage-summary" not in script


def test_storage_maintenance_uses_minimal_status_icons() -> None:
    script = _read("ui/js/pages/storage.js")
    css = _read("ui/remaining-ui-redesign.css")

    assert "function storageMaintenanceIcon(status)" in script
    assert 'idle: \'<circle cx="12" cy="12" r="8.5"/><path d="M8 12h8"/>\'' in script
    assert 'success: \'<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.5 2.2 2.2 4.8-5.4"/>\'' in script
    assert 'warning: \'<path d="M10.3 4.4a2 2 0 0 1 3.4 0l7.4 12.8a2 2 0 0 1-1.7 3H4.6a2 2 0 0 1-1.7-3z"/>' in script
    assert 'error: \'<circle cx="12" cy="12" r="8.5"/><path d="m9 9 6 6"/><path d="m15 9-6 6"/>\'' in script
    assert 'running: \'<path class="storage-maintenance-spinner" d="M21 12a9 9 0 1 1-6.2-8.6"/>\'' in script
    assert "${storageMaintenanceIcon(status)}" in script
    assert "status === 'success' ? '\\u2713'" not in script
    assert ".storage-maintenance-icon svg" in css
    assert "animation: storage-maintenance-spin 1s linear infinite" in css
    assert ".status-success .storage-maintenance-icon { color: var(--ui-state-success-fg); }" in css
    assert ".status-success .storage-maintenance-icon { background:" not in css


def test_help_has_generated_table_of_contents() -> None:
    html = _read("ui/index.html")
    script = _read("ui/js/pages/help.js")
    assert 'id="help-toc"' in html
    assert 'id="help-search-input"' in html
    assert 'id="help-search-clear-btn"' in html
    assert 'id="help-search-status"' in html
    assert 'id="help-view-quick-btn"' in html
    assert 'id="help-view-manual-btn"' in html
    assert "function _renderHelpToc(content)" in script
    assert "content.querySelectorAll('h2, h3')" in script
    assert "_renderHelpToc(box);" in script
    assert "function helpFilter(rawQuery = '')" in script
    assert "section.tocTargets" in script
    assert "node.matches?.('h2, h3')" in script
    assert "function helpSetView(rawView)" in script
    assert "function openHelpTopic(topic)" in script
    assert "const helpDocument = await fetchHelpDocument(language)" in script
    assert "const document = await fetchHelpDocument(language)" not in script
    assert "window.helpSetView = helpSetView" in script
    assert "window.openHelpTopic = openHelpTopic" in script


def test_help_renders_operational_callouts_and_ordered_steps() -> None:
    script = _read("ui/js/pages/help.js")
    css = _read("ui/remaining-ui-redesign.css")
    assert "NOTE|TIP|WARNING|IMPORTANT" in script
    assert "Hinweis|Tipp|Warnung|Wichtig|Note|Tip|Warning|Important" in script
    assert "'<a href=\"#help-' + target.slice(1)" in script
    assert "<ol>" in script
    assert "help-callout--warning" in css
    assert "help-callout--tip" in css
    assert ".help-search-hidden" in css


def test_remaining_surfaces_are_responsive_and_modal_content_is_contained() -> None:
    css = _read("ui/remaining-ui-redesign.css")
    assert "@media (max-width: 1023px)" in css
    assert "@media (max-width: 767px)" in css
    assert ".storage-repository-master-detail" in css
    assert ".storage-repository-tabs { overflow-x: auto; }" in css
    assert ".storage-archive-row { grid-template-columns: .5rem minmax(0, 1fr) 1rem; }" in css
    assert ".modal-body" in css
    assert "overflow-y: auto" in css
    assert ".modal-wizard" in css
