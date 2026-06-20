import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = ROOT / "ui" / "i18n"


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
            r"['\"]((?:app|dashboard|history|jobs|language|nav|reports|schedule|settings|sidebar|storage|wizard)\.[a-zA-Z0-9.]+)['\"]",
            source,
        ))

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
