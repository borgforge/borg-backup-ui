# Konzept: Spracheinstellung Deutsch / English (UI + Logs)

## Ziel
- In **Einstellungen** als erstes Feld: `Sprache / Language` mit `de` und `en`.
- Alle sichtbaren UI-Texte zweisprachig.
- Log-Ausgaben (UI-Joblogs, Restore-Test-Logs, Runner-Logs) ebenfalls nach Sprache.
- Rückwärtskompatibel für bestehende Installationen.

## Nicht-Ziele (Phase 1)
- Keine automatische Browser-Spracherkennung als Primärmechanismus.
- Keine dritte Sprache.
- Keine vollständige Retro-Migration alter Logdateien.

## UX/Produktentscheidung
1. Standardwert bei Neuinstallation: `de`.
2. Bestehende Installationen ohne gesetzte Sprache: Fallback `de`.
3. Sprache wird zentral gespeichert in `backup.conf`:
   - `UI_LANGUAGE=de` oder `UI_LANGUAGE=en`
4. Wechsel in Einstellungen wirkt:
   - Sofort für UI (nach Reload oder dynamischem Re-Render)
   - Für neue Logs ab nächstem Joblauf
5. Alte Logs bleiben in bisheriger Sprache erhalten.

## Architektur

### 1) Zentrale i18n-Schicht UI
- Neue Datei z. B. `ui/i18n.js`:
  - `const I18N = { de: {...}, en: {...} }`
  - `function t(key, params={})`
  - Fallback-Kette: `selected -> de -> key`
- UI-Rendering in `ui/app.js`:
  - harte Texte durch `t("...")` ersetzen
  - Navigation, Buttons, Dialoge, Tabellenköpfe, Statusmeldungen

### 2) API/Settings
- `api/config_api.py`:
  - Default ergänzen: `UI_LANGUAGE=de`
  - `get_settings_data()` liefert `UI_LANGUAGE`
- Settings-UI:
  - Erste Karte/Feld: Sprache (Deutsch/English)
  - Speichern über bestehenden `/api/settings`-Flow

### 3) Server/Backend-Meldungen
- Backend-Fehlermeldungen aktuell oft als Klartext in Exceptions.
- Einführung einfacher Übersetzungshilfe in Python:
  - `lib/i18n.py` mit `tr(lang, key, **kwargs)`
  - Sprache aus expandierter Config
- Schrittweise Umstellung:
  - zuerst nutzernahe API-Meldungen (Validation, Jobstart, Restore-Test)
  - danach restliche Admin/Fehlermeldungen

### 4) Logs (Runner + Restore-Test)
- `wizard_runner.py`, `borg_restore_test.py`, relevante APIs:
  - feste Logtexte auf `tr(...)` umstellen
  - Sprachwert beim Start des Jobs einmal ermitteln und konstant verwenden
- Wichtig:
  - Tool-Ausgaben von borg/ssh bleiben unverändert (extern erzeugt)
  - nur unsere eigenen Präfix-/Statuszeilen werden übersetzt

## Schlüsselstruktur (Vorschlag)
- UI Keys:
  - `nav.dashboard`, `nav.jobs`, `jobs.run_now`, `restore.level`, ...
- Backend Keys:
  - `err.global_data_dir_required`, `err.job_not_found`, ...
- Log Keys:
  - `log.backup_start`, `log.level1_start`, `log.restore_success`, ...

Konvention:
- Namespace nach Domäne (`nav.*`, `settings.*`, `restore.*`, `log.*`, `err.*`)
- Keine Sätze als Schlüssel, nur stabile IDs.

## Migrationsplan

### Phase A: Grundlage
1. `UI_LANGUAGE` in Config + Settings-Select.
2. UI-i18n-Layer (`t()`) einführen.
3. Top-20 UI-Texte umstellen (Navigation, Seitenheader, Hauptbuttons).

### Phase B: Vollständige UI
1. Alle statischen UI-Texte ersetzen.
2. Dialoge/Toasts/Statusmeldungen ersetzen.
3. Fehlermeldungen aus API konsistent darstellen.

### Phase C: Logs & Backend
1. Restore-Test-Logs übersetzen.
2. Wizard-Runner-Logs übersetzen.
3. API-Fehlermeldungen mit `tr()` konsolidieren.

### Phase D: Qualität
1. Missing-Key-Check (de/en-Parität).
2. Snapshot/Testfälle für beide Sprachen.
3. Review auf Textlängen/Umbrüche in EN.

## Teststrategie
- Manuell:
  - Sprache de/en wechseln -> UI neu rendern -> Texte korrekt.
  - Job starten in de/en -> neue Logdatei in korrekter Sprache.
  - Restore-Test starten in de/en -> Status/Logs korrekt.
- Automatisiert (später):
  - Unit-Test `t()`/`tr()` Fallback.
  - Lint-Script: fehlende Keys de/en.

## Risiken & Gegenmaßnahmen
- Risiko: Inkonsistente Texte bei gemischter Hardcode/i18n-Nutzung.
  - Maßnahme: schrittweise aber domänenweise komplett umstellen.
- Risiko: Lange EN-Texte sprengen Layout.
  - Maßnahme: UI-Review je Seite, responsive Nacharbeit.
- Risiko: Fehlertexte aus externen Tools nicht übersetzbar.
  - Maßnahme: klar trennen zwischen internen und externen Meldungen.

## Offene Entscheidungen
1. Sofortiger Live-Switch ohne Reload oder einfacher Full-Refresh nach Speichern?
2. Soll `UI_LANGUAGE` auch E-Mail-Report-Texte steuern?
3. Soll Sprache pro Benutzer oder global (aktuell global) sein?

## Empfohlener Start
- Zuerst `UI_LANGUAGE` + UI-Navigation/Settings/Restore-Tests umstellen.
- Danach Logs in Restore-Test und Runner.
- So ist der sichtbare Mehrwert früh da, mit kontrolliertem Risiko.
