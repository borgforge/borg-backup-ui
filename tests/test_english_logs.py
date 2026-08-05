import ast
import importlib.util
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_CALLS = {"_append", "_log", "_log_section", "_write_mini_log", "log_line", "log", "print"}
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
GERMAN_LOG_TEXT = re.compile(
    r"[ÄÖÜäöüß]|\b(?:Fehler|Warnung|Keine|nicht|ungültig|prüf\w*|erfolgreich|"
    r"fehlgeschlagen|gestartet|gespeichert|gelöscht|gefunden|erstellt|überspr\w*|"
    r"läuft|sende|starte|stoppe|warte|konnte|Verwendung|Befehle|Pfad|Datei|"
    r"Verzeichnis|Archiv|Zusammenfassung)\b",
    re.IGNORECASE,
)


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _literal_text(node):
    return " ".join(
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    )


def test_technical_log_literals_are_english_only():
    paths = [ROOT / "borg_backup_ui.py"]
    paths.extend((ROOT / "api").rglob("*.py"))
    paths.extend((ROOT / "runtime").rglob("*.py"))
    violations = []

    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = _call_name(node.func)
            if name not in LOG_CALLS | LOG_METHODS:
                continue
            text = " ".join(_literal_text(arg) for arg in node.args)
            if GERMAN_LOG_TEXT.search(text):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {text}")

    assert not violations, "German technical log text found:\n" + "\n".join(violations)


def test_scriptless_job_runner_forces_english_subprocess_locale():
    source = (ROOT / "api" / "wizard_runner.py").read_text(encoding="utf-8")

    assert 'os.environ["LC_ALL"] = "C"' in source
    assert 'os.environ["LANG"] = "C"' in source


def test_public_plugin_install_and_service_messages_are_english():
    spec = importlib.util.spec_from_file_location(
        "release_workflow",
        ROOT / "plugin" / "release_workflow.py",
    )
    assert spec and spec.loader
    release_workflow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release_workflow)

    installer = release_workflow.package_install_block("abcdef0123456789abcdef0123456789")
    service_script = (ROOT / "plugin" / "rc.borg_backup_ui").read_text(encoding="utf-8")

    public_text = installer + "\n" + service_script
    assert not GERMAN_LOG_TEXT.search(public_text)
    assert "downloading package" in installer
    assert "installing package" in installer
    assert "Python runtime is not available yet" in service_script
    assert "Borg Backup UI started" in service_script
