from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _assert_required_i18n_label(html: str, key: str) -> None:
    pattern = (
        r'<label[^>]*class="[^"]*\bform-label-required\b[^"]*"[^>]*>'
        r'(?:(?!</label>).)*class="form-required-marker"'
        r'(?:(?!</label>).)*data-i18n="' + re.escape(key) + r'"'
    )
    assert re.search(pattern, html, re.S), key


def test_required_marker_has_shared_visual_style() -> None:
    css = _read("ui/style.css")
    settings_css = _read("ui/settings-redesign.css")

    assert ".form-label.form-label-required" in css
    assert ".form-required-marker" in css
    assert "color: var(--error)" in css
    assert ".settings-profile-editor.readonly .settings-profile-field .form-required-marker" in settings_css
    readonly_rule = settings_css.split(
        ".settings-profile-editor.readonly .settings-profile-field .form-required-marker",
        1,
    )[1].split("}", 1)[0]
    assert "display: none" in readonly_rule


def test_restore_job_and_repository_wizards_mark_required_fields() -> None:
    html = _read("ui/index.html")

    for key in (
        "restore.selectJob",
        "restore.selectArchive",
        "restore.sourcePath",
        "restore.targetDirectory",
        "storage.storageTargetExistingLabel",
        "storage.repositoryDisplayName",
        "storage.repositoryRelativePath",
        "storage.repositoryPassphrase",
        "storage.repositoryKeyExport",
        "wizard.jobName",
        "wizard.typeId",
        "wizard.sourcePaths",
        "wizard.storageTarget",
        "wizard.repositorySelect",
    ):
        _assert_required_i18n_label(html, key)

    exclude_label = re.search(
        r'<label[^>]*>[^<]*(?:(?!</label>).)*data-i18n="wizard.excludePaths"(?:(?!</label>).)*</label>',
        html,
        re.S,
    )
    assert exclude_label
    assert "form-label-required" not in exclude_label.group(0)


def test_dynamic_settings_forms_mark_required_profile_fields() -> None:
    script = _read("ui/js/pages/settings.js")

    for selector in (
        "[data-local-profile-name]",
        "[data-local-profile-path]",
        "[data-usb-profile-name]",
        "[data-usb-profile-path]",
        "[data-smb-profile-name]",
        "[data-smb-profile-server]",
        "[data-smb-profile-share]",
        "[data-smb-profile-path]",
        "[data-smb-profile-username]",
        "[data-storage-profile-name]",
        "[data-storage-profile-host]",
        "[data-storage-profile-user]",
        "[data-storage-profile-base-path]",
    ):
        assert f"['{selector}'," in script
        field_config = script.split(f"['{selector}',", 1)[1].split("],", 1)[0]
        assert "{ required: true }" in field_config

    assert "requiredMarkerHtml" in script
    assert "formLabelHtml" in script
    assert "settingsFieldRequired" in script
    assert "data-smb-profile-password-set" in script
    assert "GLOBAL_DATA_DIR', settingsT('general.dataDir')" in script
    assert "{ required: true })" in script
    assert "apprise-profile-name" in script
    assert "apprise-profile-provider" in script


def test_repository_lifecycle_and_conditional_passphrase_marker_are_wired() -> None:
    html = _read("ui/index.html")
    storage_js = _read("ui/js/pages/storage.js")

    assert 'id="repository-manager-passphrase-required-marker"' in html
    assert "passphraseRequired = action === 'create' && encryption !== 'none'" in storage_js
    assert "repository-manager-passphrase-required-marker" in storage_js
    assert "repositoryConfirmName" in storage_js
    assert "repositoryConfirmDeletePhrase" in storage_js
