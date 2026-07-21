from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_settings_redesign_styles_load_after_shared_surfaces() -> None:
    html = _read("ui/index.html")
    assert html.index("/ui/remaining-ui-redesign.css") < html.index(
        "/ui/settings-redesign.css"
    )


def test_settings_keeps_all_areas_in_grouped_side_menu() -> None:
    script = _read("ui/js/pages/settings.js")
    for key in (
        "general",
        "users",
        "notifications",
        "backup",
        "restore",
        "usb",
        "smb",
        "storagebox",
        "transfer",
        "advanced",
        "factory-reset",
    ):
        assert f"key: '{key}'" in script
    for group in ("system", "operations", "storage", "maintenance"):
        assert f"group: '{group}'" in script
    assert "function renderSettingsMenu(tabs)" in script
    assert 'class="settings-redesign-layout"' in script


def test_notifications_are_a_dedicated_settings_area_with_apprise_profiles() -> None:
    script = _read("ui/js/pages/settings.js")
    css = _read("ui/settings-redesign.css")
    for contract in (
        "key: 'notifications'",
        'data-settings-panel="notifications"',
        "renderSettingsNotifications(data)",
        "renderSettingsAppriseProfiles()",
        "/api/notification-profiles",
        "/api/notification-profiles/providers",
        "/api/notification-profiles/validate",
        "/api/notification-profiles/test",
        "apprise-profile-duplicate",
        "apprise-provider-select",
        "onAppriseProviderSelect",
        "_renderAppriseProviderOptions",
        "_renderAppriseProviderAdvanced",
        "_appriseProviderTemplates",
        "_renderAppriseUrlHelp",
        "_renderAppriseProfileSummary",
        "_appriseProviderSchema",
        'data-apprise-field="apprise_url"',
        'data-apprise-field="provider"',
        "settingsState.appriseDraftProfile",
    ):
        assert contract in script
    assert 'data-apprise-field="id"' not in script
    assert ".apprise-provider-picker" in css
    assert ".apprise-provider-advanced" in css
    assert ".apprise-profile-manager" in css
    assert ".apprise-profile-summary" in css
    assert ".apprise-profile-summary-main" in css
    assert ".apprise-provider-name" in css
    assert ".apprise-url-help" in css


def test_apprise_profiles_are_compact_until_edit_and_explain_urls_from_provider_metadata() -> None:
    script = _read("ui/js/pages/settings.js")
    german = _read("ui/i18n/de.json")
    english = _read("ui/i18n/en.json")

    assert "${editing ? `<div class=\"settings-body two-col\">" in script
    assert ": _renderAppriseProfileSummary(current, events)" in script
    assert "service.toLowerCase() === provider ? service" in script
    assert "apprise-profile-summary-main" in script
    assert "<dl>" in script
    assert "templates.map((item)" in script
    assert "_renderAppriseTokenSummary(tokens, (item) => item.required" in script
    assert "_renderAppriseTokenSummary(tokens, (item) => item.private" in script
    assert "_renderAppriseUrlBuilder(provider, current)" in script
    assert "data-apprise-url-token" in script
    assert "function _appriseTokenFieldExamples(provider, key)" in script
    assert "settingsT('apprise.fieldExamples'" in script
    assert "data-apprise-field=\"url_template\"" in script
    assert "function _appriseTemplateSignature(template)" in script
    assert "_appriseTemplateSignature(item) === signature" in script
    assert "onAppriseTemplateSelect" in script
    assert "payload.url_template" in script
    assert "payload.url_fields = Object.fromEntries" in script
    assert ".filter(Boolean);\n}" in script
    assert "templates.slice(0, 5).map((template)" in script
    assert "_appriseUrlPlaceholder(provider, current.url_set)" in script
    assert "apprise-ntfy-builder" not in script
    assert "_buildAppriseNtfyUrl" not in script
    assert "einfaches Formular" not in german
    assert "simple form" not in english
    assert "dynamicUrlHint" in german
    assert "dynamicUrlHint" in english
    assert "urlFieldsHint" in german
    assert "urlFieldsHint" in english
    assert "fieldExamples" in german
    assert "fieldExamples" in english


def test_factory_reset_is_the_last_maintenance_area() -> None:
    script = _read("ui/js/pages/settings.js")
    transfer = "{ key: 'transfer'"
    advanced = "{ key: 'advanced'"
    factory_reset = "{ key: 'factory-reset'"

    assert script.index(transfer) < script.index(advanced) < script.index(factory_reset)
    assert 'data-settings-panel="factory-reset"' in script
    transfer_panel = script.split('data-settings-panel="transfer"', 1)[1].split(
        'data-settings-panel="advanced"', 1
    )[0]
    assert "renderSettingsFactoryReset()" not in transfer_panel
    assert "const hideGlobalSave = profileTab || settingsState.activeTab === 'factory-reset';" in script


def test_profile_pages_use_master_detail_and_explicit_edit_mode() -> None:
    script = _read("ui/js/pages/settings.js")
    css = _read("ui/settings-redesign.css")
    for contract in (
        "SETTINGS_PROFILE_CONFIG",
        "initializeSettingsProfileManagers",
        "syncSettingsProfileManager",
        "decorateSettingsProfileFields",
        "settingsState.profileEditing",
        "data-profile-edit",
        "data-profile-cancel",
        "data-profile-save",
    ):
        assert contract in script
    assert "control.disabled = !editing || !selected" in script
    assert "row.dataset.profileUiKey" in script
    assert ".settings-profile-manager" in css
    assert ".settings-profile-editor.readonly input:disabled" in css
    assert ".settings-profile-list-item.active" in css


def test_profile_pages_hide_global_save_and_keep_local_actions() -> None:
    script = _read("ui/js/pages/settings.js")
    assert "const profileTab = ['local', 'usb', 'smb', 'storagebox'].includes" in script
    assert "saveBtn.classList.toggle('hidden', hideGlobalSave)" in script
    assert "const saved = await saveSettings();" in script
    for action in (
        "usb-profile-check",
        "smb-profile-check",
        "storagebox-key-status",
        "storagebox-key-generate",
        "storagebox-key-public",
        "storagebox-key-deploy",
        "storagebox-test",
    ):
        assert action in script


def test_local_profile_paths_are_validated_before_save_in_both_languages() -> None:
    import json

    script = _read("ui/js/pages/settings.js")
    german = json.loads(_read("ui/i18n/de.json"))
    english = json.loads(_read("ui/i18n/en.json"))

    assert "function normalizeCanonicalStoragePath(value)" in script
    assert "submitted.includes('//')" in script
    assert "segment === '.' || segment === '..'" in script
    assert "classList.toggle('input-error', !normalized)" in script
    assert "activeTab === 'local' && !validateLocalProfilesForSave()" in script
    assert german["settings"]["profiles"]["invalidLocalPath"]
    assert english["settings"]["profiles"]["invalidLocalPath"]
    for payload in (german, english):
        health = payload["settings"]["health"]
        assert health["registryCanonicalModelTitle"]
        assert health["registryCanonicalModelFailed"]
        assert health["registryStorageInventoryTitle"]
        assert health["failedPhase"]
        assert health["failureReason"]
        assert health["rollbackStatus"]
        assert health["missingKeys"]
        assert health["unknownKeys"]
        assert health["canonicalContentChanged"]
    assert "details.failed_phase" in script
    assert "details.rollback_status" in script
    assert "reason: status === 'applied' ? 'registrySchemaComplete' : ''" in script
    assert "function _migrationRegistryAffectedCount(details = {})" in script
    assert "details.missing_keys" in script
    assert "details.unknown_keys" in script
    assert "details.canonical_content_changed === true" in script


def test_settings_layout_is_sticky_and_responsive() -> None:
    css = _read("ui/settings-redesign.css")
    assert ".settings-page-header" in css
    assert "position: sticky" in css
    assert "@media (max-width: 1050px)" in css
    assert "@media (max-width: 767px)" in css
    assert ".settings-profile-field" in css
    assert ".settings-workspace-header" in css


def test_advanced_settings_separates_reminders_and_passphrases_into_subtabs() -> None:
    script = _read("ui/js/pages/settings.js")
    css = _read("ui/settings-redesign.css")
    assert "settingsState.advancedTab" in script
    assert 'data-settings-advanced-tab="reminders"' in script
    assert 'data-settings-advanced-tab="passphrases"' in script
    assert "renderSettingsNotificationReminderDiagnostics" in script
    assert "renderSettingsPerRepoPassphrases" in script
    assert "systemHealth?.notification_reminders" in script
    assert "/api/notification-reminders/diagnostics" in script
    assert "notificationReminderDiagnosticsHint" in script
    assert "backupOverdueDiagnostics" in script
    assert "restoreTestOverdueDiagnostics" in script
    assert "next_scheduled_run" in script
    assert "nextScheduledRun" in script
    assert "monitoredRun" in script
    assert "reminderInfo" in script
    assert "_renderReminderDetailLine" in script
    assert "_renderReminderStackLine" in script
    assert "function _formatReminderTimestamp" in script
    assert "day: '2-digit'" in script
    assert "month: '2-digit'" in script
    assert ".settings-subtab-card" in css
    assert "settings-reminder-diagnostics-card" in script
    assert "reminder-diagnostics-table" in script
    assert ".reminder-diagnostics-table-wrap" in css
    assert "table-layout: fixed" in css
    assert "overflow-x: hidden" in css
    assert ".reminder-detail-line" in css
    assert ".reminder-detail-label" in css
    assert ".reminder-detail-stack" in css
    assert ".reminder-stack-line" in css
    assert "settings-passphrase-card" in script
    assert "settings-passphrase-table" in script
    assert ".settings-passphrase-table-wrap" in css
    assert "white-space: nowrap" in css


def test_settings_primary_tab_switch_reuses_existing_dom() -> None:
    script = _read("ui/js/pages/settings.js")
    assert "function activateSettingsTab(tabKey)" in script
    assert "panel.dataset.settingsPanel !== active.key" in script
    assert "activateSettingsTab(tab);" in script
    assert "usersPanel.innerHTML = renderSettingsUsers();" in script


def test_settings_menu_translations_live_in_settings_namespace() -> None:
    import json

    for language in ("de", "en"):
        payload = json.loads(_read(f"ui/i18n/{language}.json"))
        menu = payload["settings"]["menu"]
        assert menu["areas"]
        assert menu["saved"]


def test_settings_about_and_sidebar_show_current_project_contact_metadata() -> None:
    script = _read("ui/js/pages/settings.js")
    bindings = _read("ui/js/components/app-bindings.js")

    assert "thorsten.steinberg@gmx.de" in script
    assert "mailto:${escAttr(info.contactEmail)}" in script
    assert "https://github.com/borgforge/borg-backup-ui" in script
    assert "borgforge/borg-backup-ui" in script
    assert "gitlab.thetwist.de" not in script
    assert "settings-about-contact" in script
    assert "settings-about-repository" in script
    assert "settingsState.appInfo" in script
    assert "v.contact_email, v.repository_url" in bindings


def test_settings_status_checks_do_not_reload_the_page() -> None:
    script = _read("ui/js/pages/settings.js")
    key_status = script.split("async function storageboxKeyStatus()", 1)[1].split(
        "async function storageboxKeyGenerate()", 1
    )[0]
    connection_test = script.split("async function storageboxTest()", 1)[1].split(
        "async function sendWeeklyReport()", 1
    )[0]
    assert "refreshSettings()" not in key_status
    assert "refreshSettings()" not in connection_test
    assert "_storageboxRenderChecks()" in key_status
    assert "_storageboxRenderChecks()" in connection_test


def test_existing_storagebox_ssh_key_is_shown_as_warning() -> None:
    script = _read("ui/js/pages/settings.js")
    generate = script.split("async function storageboxKeyGenerate()", 1)[1].split(
        "async function storageboxKeyPublic()", 1
    )[0]

    assert "const generated = d?.generated !== false;" in generate
    assert "const type = generated ? 'success' : 'warning';" in generate
    assert "showMsg('storagebox-setup-msg', type, apiMessage(d, settingsT('storagebox.keyGenerated')));" in generate
    assert "_storageboxRefreshWithFlash" not in script


def test_smtp_test_mail_uses_persisted_settings_only() -> None:
    script = _read("ui/js/pages/settings.js")
    send_test = script.split("async function sendTestEmail()", 1)[1].split(
        "function _notificationEventEnabled", 1
    )[0]

    assert "saveBeforeTestEmail" in send_test
    assert "'GLOBAL_MAIL_RECIPIENT'" in send_test
    assert "'GLOBAL_SMTP_PASSWORD'" in send_test
    assert "settingsState.data?.smtp?.[key]" in send_test
    assert "body: JSON.stringify({})," in send_test
    assert "JSON.stringify({ recipient })" not in send_test
    assert "document.querySelector('[data-key=\"GLOBAL_MAIL_RECIPIENT\"]')?.value" not in send_test


def test_settings_menu_reuses_storage_icons_and_has_no_duplicate_health_footer() -> None:
    script = _read("ui/js/pages/settings.js")
    css = _read("ui/settings-redesign.css")

    for location in ("usb", "smb", "storagebox"):
        assert f"icon: locationIcon('{location}')" in script
    assert "function settingsMenuIcon(key)" in script
    assert "settings-menu-status-dot" not in script
    assert ".settings-menu-icon svg" in css


def test_profile_lists_reuse_storage_icons_and_hide_duplicate_config_path() -> None:
    script = _read("ui/js/pages/settings.js")
    html = _read("ui/index.html")

    for location in ("usb", "smb", "storagebox"):
        assert f"icon: locationIcon('{location}')" in script
        assert f'class="settings-profile-symbol ${{type}}"' in script
    assert "settings-conf-path" not in html
    assert "`Config: ${data.conf_file}`" not in script


def test_profile_pages_keep_local_save_and_block_in_use_deletes() -> None:
    script = _read("ui/js/pages/settings.js")

    assert "footer.classList.toggle('hidden', !editing)" in script
    assert "async function blockProfileRemovalIfInUse(row, type)" in script
    assert "await reloadSettingsDataAfterSave(type);" in script
    assert "profiles.cannotRemoveUsb" in script
    assert "if (await blockProfileRemovalIfInUse(row, 'usb')) return;" in script
    assert "if (await blockProfileRemovalIfInUse(row, 'smb')) return;" in script
    assert "if (await blockProfileRemovalIfInUse(row, 'storage')) return;" in script


def test_profile_save_uses_live_dom_payload_and_dynamic_empty_state() -> None:
    script = _read("ui/js/pages/settings.js")

    assert "if (activeTab === 'usb') profileUpdates.usb = getUsbProfilesFromDom();" in script
    assert "if (activeTab === 'smb') profileUpdates.smb = getSmbProfilesFromDom();" in script
    assert "if (activeTab === 'storagebox') profileUpdates.storagebox = getStorageProfilesFromDom();" in script
    assert "profile_updates: profileUpdates" in script
    assert "function updateUsbProfilesEmptyState()" in script
    assert 'id="usb-profiles-empty-state"' in script
    assert "empty.classList.toggle('hidden', getUsbProfilesFromDom().length > 0);" in script
    assert "fetch('/api/settings/basic')" in script


def test_settings_save_is_scoped_to_active_panel_and_reloads_backend_state() -> None:
    script = _read("ui/js/pages/settings.js")

    assert "const activePanel = document.querySelector('#settings-content .settings-tab-panel:not(.hidden)');" in script
    assert "activePanel?.querySelectorAll('[data-key]').forEach(el => {" in script
    assert "Object.prototype.hasOwnProperty.call(updates, 'GLOBAL_DATA_DIR')" in script
    assert "await reloadSettingsDataAfterSave();" in script


def test_profile_secret_import_allows_missing_profiles_from_bundle_settings() -> None:
    script = _read("ui/js/pages/settings.js")

    assert "const canImportMissingProfile = String(r.status) !== 'profile_missing' || !!(sp && sp.present);" in script
    assert 'data-profile-secret-preview-select="${idx}" ${canImportMissingProfile ? \'checked\' : \'disabled\'}' in script


def test_editable_backup_conf_keys_are_part_of_runtime_schema() -> None:
    script = _read("ui/js/pages/settings.js")
    example = _read("runtime/config/backup.conf.example")
    schema_keys = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", example, re.MULTILINE))
    literal_keys = set(re.findall(r"data-key=[\"']([A-Z][A-Z0-9_]*)[\"']", script))
    literal_keys.update(re.findall(r"f(?:text|num|mono|pwd)\('([A-Z][A-Z0-9_]*)'", script))

    assert literal_keys <= schema_keys
