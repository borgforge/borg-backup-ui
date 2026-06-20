import json
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = ROOT / "ui" / "i18n"


def _load_i18n_audit():
    path = ROOT / "plugin" / "i18n_audit.py"
    spec = importlib.util.spec_from_file_location("i18n_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _flatten_keys(value, prefix=""):
    keys = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            keys.update(_flatten_keys(child, path))
        else:
            keys.add(path)
    return keys


def _load(language):
    return json.loads((I18N_DIR / f"{language}.json").read_text(encoding="utf-8"))


def _flatten_values(value, prefix=""):
    values = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            values.update(_flatten_values(child, path))
        else:
            values[path] = child
    return values


def test_german_and_english_resources_have_matching_keys():
    assert _flatten_keys(_load("de")) == _flatten_keys(_load("en"))


def test_user_facing_ui_and_backend_have_no_untracked_hardcoded_text():
    audit = _load_i18n_audit()
    findings = audit.audit(ROOT, include_backend=True)

    assert not findings, "Hardcoded UI text found:\n" + "\n".join(
        finding.format() for finding in findings
    )


def test_historical_german_compatibility_parsers_remain_available():
    settings = (ROOT / "ui" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")
    report_mail = (ROOT / "api" / "report_mail_api.py").read_text(encoding="utf-8")

    assert "Verschiebe-Fehler" in settings
    assert "Job-Layout geprüft" in settings
    assert "move errors" in settings
    assert "Storage paths updated" in settings
    assert "FEHLER|WARNUNG" in report_mail
    assert "FEHLGESCHLAGEN" in report_mail


def test_resources_have_no_duplicate_keys_and_matching_placeholders():
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, f"duplicate translation key: {key}"
            result[key] = value
        return result

    resources = {}
    for language in ("de", "en"):
        resources[language] = json.loads(
            (I18N_DIR / f"{language}.json").read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )

    de_values = _flatten_values(resources["de"])
    en_values = _flatten_values(resources["en"])
    for key in de_values:
        assert set(re.findall(r"\{([a-zA-Z0-9_]+)\}", de_values[key])) == set(
            re.findall(r"\{([a-zA-Z0-9_]+)\}", en_values[key])
        ), key


def test_index_translation_keys_exist_in_both_resources():
    index = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    referenced = set(re.findall(r'data-i18n(?:-[a-z-]+)?="([^"]+)"', index))

    assert referenced
    assert referenced <= _flatten_keys(_load("de"))
    assert referenced <= _flatten_keys(_load("en"))


def test_javascript_translation_keys_exist_in_both_resources():
    referenced = set()
    for path in (ROOT / "ui" / "js").rglob("*.js"):
        source = path.read_text(encoding="utf-8")
        referenced.update(re.findall(
            r"['\"]((?:api|app|dashboard|history|jobs|language|nav|reports|restore|restoreTests|schedule|settings|sidebar|storage|wizard)\.[a-zA-Z0-9.]+)['\"]",
            source,
        ))
        referenced.update(
            f"restore.{key}" for key in re.findall(r"restoreT\(['\"]([a-zA-Z0-9.]+)['\"]", source)
        )
        referenced.update(
            f"restoreTests.{key}" for key in re.findall(r"restoreTestsT\(['\"]([a-zA-Z0-9.]+)['\"]", source)
        )

    assert referenced
    assert referenced <= _flatten_keys(_load("de"))
    assert referenced <= _flatten_keys(_load("en"))


def test_i18n_initializes_before_application_modules():
    bootstrap = (ROOT / "ui" / "js" / "app-main.js").read_text(encoding="utf-8")

    assert bootstrap.index("/ui/js/components/i18n.js") < bootstrap.index("/ui/js/api/client.js")
    assert "initI18n" in bootstrap


def test_i18n_keeps_german_as_explicit_fallback():
    component = (ROOT / "ui" / "js" / "components" / "i18n.js").read_text(encoding="utf-8")

    assert "const fallbackLanguage = 'de';" in component
    assert "navigator.language" not in component


def test_settings_dynamic_content_uses_localization_helpers():
    settings = (ROOT / "ui" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")

    assert "bbui:language-changed" in settings
    assert "renderSettings(settingsState.data, settingsState.systemHealth)" in settings
    assert "toLocaleString(settingsLocale())" in settings
    assert "toLocaleDateString(settingsLocale())" in settings
    assert "health.jobErrors.${code}" in settings

    hardcoded_user_text = (
        "Benutzer hart löschen",
        "Passwort zurücksetzen",
        "Keine Job-Vorschau vorhanden",
        "Lade Config-Backups...",
        "Systemzustand & Migration",
        "Einstellungen gespeichert.",
        "SSH-Key vorhanden",
    )
    for text in hardcoded_user_text:
        assert text not in settings


def test_job_health_error_codes_have_translations():
    source = (ROOT / "api" / "system_health_api.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'(?:add_error\(|"code":\s*)"([a-z0-9_]+)"', source))
    keys = _flatten_keys(_load("de"))

    assert codes
    assert {f"settings.health.jobErrors.{code}" for code in codes} <= keys


def test_backend_message_codes_have_translations():
    codes = set()
    for path in (ROOT / "api").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        codes.update(re.findall(r'["\']message_code["\']\s*:\s*["\']([a-z0-9_]+)["\']', source))

    keys = _flatten_keys(_load("de"))
    assert codes
    assert {f"api.messages.{code}" for code in codes} <= keys


def test_authentication_pages_reference_existing_translation_keys():
    source = (ROOT / "borg_backup_ui.py").read_text(encoding="utf-8")
    referenced = set(re.findall(r'data-i18n="([a-zA-Z0-9.]+)"', source))
    referenced.update(re.findall(r"authT\(['\"]([a-zA-Z0-9.]+)['\"]", source))

    assert referenced
    assert referenced <= _flatten_keys(_load("de"))
    assert referenced <= _flatten_keys(_load("en"))


def test_issue_59_dynamic_status_text_uses_localization_contracts():
    wizard = (ROOT / "ui" / "js" / "pages" / "wizard.js").read_text(encoding="utf-8")
    history = (ROOT / "ui" / "js" / "pages" / "history.js").read_text(encoding="utf-8")
    restore_tests = (ROOT / "ui" / "js" / "pages" / "restore-tests.js").read_text(encoding="utf-8")

    step_codes = {
        "prechecks", "resourceLocksAcquire", "dockerStop", "vmStop", "borgCreate",
        "borgMaintenance", "statusNotification", "vmStart", "dockerStart", "resourceLocksRelease",
    }
    for language in ("de", "en"):
        keys = _flatten_keys(_load(language))
        assert {f"wizard.flowSteps.{code}" for code in step_codes} <= keys
        assert "restoreTests.cleanupCompleted" in keys

    assert "wizard.flowSteps.${code}" in wizard
    assert "if (status !== 'skipped') return '';" in history
    assert "const detailError = historyRunDetailMessage(e);" in history
    assert "[restoreTestsT('cleanupStatus'), step.message]" not in restore_tests
    assert "[restoreTestsT('cleanupStatus'), restoreTestStepMessage(step)]" in restore_tests


def test_api_client_resolves_codes_without_displaying_raw_messages():
    source = (ROOT / "ui" / "js" / "api" / "client.js").read_text(encoding="utf-8")

    assert "api.messages.${messageCode}" in source
    assert "api.errors.${errorCode}" in source
    assert "data.message || data.error" not in source


def test_restore_pages_use_localization_helpers_for_dynamic_content():
    restore = (ROOT / "ui" / "js" / "pages" / "restore.js").read_text(encoding="utf-8")
    restore_tests = (ROOT / "ui" / "js" / "pages" / "restore-tests.js").read_text(encoding="utf-8")

    assert "bbui:language-changed" in restore
    assert "bbui:language-changed" in restore_tests
    assert "restoreT('confirmStart')" in restore
    assert "restoreTestsT('confirmTitle')" in restore_tests
    assert "toLocaleTimeString(restoreTestsLocale())" in restore_tests

    for text in (
        "Plan nicht verfügbar.",
        "Keine Prüfberichte für den aktuellen Filter gefunden.",
        "Restore-Test starten",
        "Geprüfte Stichproben-Dateien",
    ):
        assert text not in restore_tests


def test_migrated_pages_do_not_display_raw_backend_errors():
    pages = (
        "history.js",
        "jobs.js",
        "reports.js",
        "restore.js",
        "restore-tests.js",
        "storage.js",
        "wizard.js",
    )
    for name in pages:
        source = (ROOT / "ui" / "js" / "pages" / name).read_text(encoding="utf-8")
        assert "throw new Error(data.error" not in source, name
        assert "message: data.message" not in source, name

    settings = (ROOT / "ui" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")
    assert "throw new Error(data.error" not in settings
    assert "storageboxConnMsg = d.message" not in settings
