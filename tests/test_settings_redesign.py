from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_settings_redesign_styles_load_after_shared_surfaces() -> None:
    html = _read("ui/index.html")
    assert html.index("/ui/remaining-ui-redesign.css") < html.index(
        "/ui/settings-redesign.css"
    )


def test_settings_keeps_all_nine_areas_in_grouped_side_menu() -> None:
    script = _read("ui/js/pages/settings.js")
    for key in (
        "general",
        "users",
        "backup",
        "restore",
        "usb",
        "smb",
        "storagebox",
        "transfer",
        "advanced",
    ):
        assert f"key: '{key}'" in script
    for group in ("system", "operations", "storage", "maintenance"):
        assert f"group: '{group}'" in script
    assert "function renderSettingsMenu(tabs)" in script
    assert "function settingsHealthNeedsAttention(health)" in script
    assert 'class="settings-redesign-layout"' in script


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
    assert "const profileTab = ['usb', 'smb', 'storagebox'].includes" in script
    assert "saveBtn.classList.toggle('hidden', profileTab)" in script
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


def test_settings_layout_is_sticky_and_responsive() -> None:
    css = _read("ui/settings-redesign.css")
    assert ".settings-page-header" in css
    assert "position: sticky" in css
    assert "@media (max-width: 1050px)" in css
    assert "@media (max-width: 767px)" in css
    assert ".settings-profile-field" in css
    assert ".settings-workspace-header" in css


def test_settings_menu_translations_live_in_settings_namespace() -> None:
    import json

    for language in ("de", "en"):
        payload = json.loads(_read(f"ui/i18n/{language}.json"))
        menu = payload["settings"]["menu"]
        assert menu["areas"]
        assert menu["saved"]


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
