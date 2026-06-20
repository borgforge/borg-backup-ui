#!/usr/bin/env python3
"""Repeatable audit for hardcoded user-facing UI text (Issue #25)."""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

_TRANSLATABLE_ATTRIBUTES = {
    "title": "data-i18n-title",
    "placeholder": "data-i18n-placeholder",
    "aria-label": "data-i18n-aria-label",
}
_IGNORED_TAGS = {"script", "style", "svg"}
_NEUTRAL_HTML_TEXT = re.compile(
    r"^(?:"
    r"Borg Backup(?: Manager)?|UI|Dashboard|Jobs|Storage|History|"
    r"Flash|Appdata|Photos|VMs|USB|SMB|Custom|Docker|Cloud|Server|Home|Video|Code|"
    r"Verbose|Verify Data|Indigo|Pink|Lime|Amber|Orange|Rose|Cyan|"
    r"zstd,[1369]|repokey|keyfile(?:-blake2)?|"
    r"[0-9A-Za-z_./,*:+%() <>-]*[/_.:*][0-9A-Za-z_./,*:+%() <>-]*"
    r")$"
)
_GERMAN_JS_TEXT = re.compile(
    r"[ÄÖÜäöüß]|\b(?:Aktualisieren|Ansicht|Auswahl|Berechtigung|Bestätigen|"
    r"Angemeldet|Bitte|Datei|Dokumentation|Eingabe|Einstellungen|Erfolg|Fehler|Hilfe|Hinweis|"
    r"Keine|Lade|Log-Datei|Nur|Schließen|Verzeichnis|konnte|laden|möglich|"
    r"speichern|überschreiben|wählt)\b",
    re.IGNORECASE,
)
_GERMAN_BACKEND_TEXT = re.compile(
    r"[ÄÖÜäöüß]|\b(?:Alle|Alter|Änderung|Datei|Elemente|Entschlüsselung|Fehler|"
    r"Fehlgeschlagen|gefunden|geprüft|gestern|Jahren|Kein|Keine|konnte|läuft|"
    r"Bestaetigung|Monaten|Nachweis|nicht|Noch|Passwort|Pfad|Profil|Prüfung|Stunden|Tagen|"
    r"Ungültig|Ungültige|Unbekanntes|verschoben|Verschlüsselung|vor|Warnung)\b",
    re.IGNORECASE,
)

# Compatibility parsers consume historical backend strings but never render them.
_JS_COMPATIBILITY_LITERALS = {
    "Verschiebe-Fehler",
    "Job-Layout geprüft",
}
_JS_INTERNAL_LITERALS = {"hilfe"}
_BACKEND_COMPATIBILITY_LITERALS = {
    "sonstiges",
    "fehler",
    "migration-state.json",
    "warnung",
    r"(^|\s)(FEHLER|WARNUNG)[:\s]",
    r"(^|\s)(FAILED|FEHLGESCHLAGEN)[:\s]?",
}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    text: str

    def format(self) -> str:
        return f"{self.path.relative_to(ROOT)}:{self.line}: {self.text}"


class _VisibleTextParser(HTMLParser):
    def __init__(self, path: Path):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.stack: list[tuple[str, bool]] = []
        self.findings: list[Finding] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        inherited = self.stack[-1][1] if self.stack else False
        attributes = dict(attrs)
        localized = inherited or "data-i18n" in attributes
        self.stack.append((tag, localized))
        for name, marker in _TRANSLATABLE_ATTRIBUTES.items():
            value = str(attributes.get(name) or "").strip()
            if not value or marker in attributes or _is_neutral_html_text(value):
                continue
            self.findings.append(Finding(self.path, self.getpos()[0], f'{name}="{value}"'))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or not self.stack:
            return
        tag, localized = self.stack[-1]
        if localized or tag in _IGNORED_TAGS or _is_neutral_html_text(text):
            return
        self.findings.append(Finding(self.path, self.getpos()[0], text))


def _is_neutral_html_text(text: str) -> bool:
    text = " ".join(text.split())
    if not re.search(r"[A-Za-zÄÖÜäöüß]", text):
        return True
    return bool(_NEUTRAL_HTML_TEXT.fullmatch(text))


def audit_html(path: Path) -> list[Finding]:
    parser = _VisibleTextParser(path)
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.findings


def _javascript_literals(source: str):
    index = 0
    line = 1
    length = len(source)
    while index < length:
        char = source[index]
        next_char = source[index + 1] if index + 1 < length else ""
        if char == "\n":
            line += 1
            index += 1
            continue
        if char == "/" and next_char == "/":
            index += 2
            while index < length and source[index] != "\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            index += 2
            while index < length - 1 and source[index:index + 2] != "*/":
                if source[index] == "\n":
                    line += 1
                index += 1
            index += 2
            continue
        if char not in {"'", '"', "`"}:
            index += 1
            continue

        quote = char
        literal_line = line
        value = []
        index += 1
        while index < length:
            char = source[index]
            if char == "\\":
                if index + 1 < length:
                    value.extend(source[index:index + 2])
                    index += 2
                    continue
            if char == quote:
                index += 1
                break
            if char == "\n":
                line += 1
            value.append(char)
            index += 1
        yield literal_line, "".join(value)


def audit_javascript(path: Path) -> list[Finding]:
    findings = []
    source = path.read_text(encoding="utf-8")
    for line, text in _javascript_literals(source):
        if not _GERMAN_JS_TEXT.search(text):
            continue
        if any(allowed in text for allowed in _JS_COMPATIBILITY_LITERALS):
            continue
        if text in _JS_INTERNAL_LITERALS:
            continue
        findings.append(Finding(path, line, " ".join(text.split())[:180]))
    return findings


def audit_backend_python(path: Path) -> list[Finding]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    docstrings.add(id(value))

    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        text = " ".join(node.value.split())
        if not text or text in _BACKEND_COMPATIBILITY_LITERALS:
            continue
        if _GERMAN_BACKEND_TEXT.search(text):
            findings.append(Finding(path, node.lineno, text[:180]))
    return findings


def audit(root: Path = ROOT, *, include_backend: bool = False) -> list[Finding]:
    findings = audit_html(root / "ui" / "index.html")
    for path in sorted((root / "ui" / "js").rglob("*.js")):
        findings.extend(audit_javascript(path))
    if include_backend:
        for path in sorted((root / "api").rglob("*.py")):
            findings.extend(audit_backend_python(path))
        for path in sorted((root / "runtime").rglob("*.py")):
            findings.extend(audit_backend_python(path))
    return findings


def main() -> int:
    include_backend = "--backend" in sys.argv[1:]
    findings = audit(include_backend=include_backend)
    if findings:
        scope = "UI/backend" if include_backend else "UI"
        print(f"Hardcoded user-facing {scope} text found:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding.format()}", file=sys.stderr)
        return 1
    scope = "UI/backend" if include_backend else "UI"
    print(f"OK: no hardcoded user-facing {scope} text found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
