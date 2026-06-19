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


def test_german_and_english_resources_have_matching_keys():
    assert _flatten_keys(_load("de")) == _flatten_keys(_load("en"))


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
            r"['\"]((?:app|dashboard|history|jobs|language|nav|reports|schedule|sidebar|storage|wizard)\.[a-zA-Z0-9.]+)['\"]",
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
