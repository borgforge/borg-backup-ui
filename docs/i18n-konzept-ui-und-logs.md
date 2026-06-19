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
3. Die dauerhafte globale Sprache wird in einer spaeteren Teilumsetzung zentral
   in `backup.conf` gespeichert:
   - `UI_LANGUAGE=de` oder `UI_LANGUAGE=en`
4. Die Infrastruktur aus Issue `#12` speichert die UI-Auswahl zunaechst lokal
   unter `borg-backup-ui.language`. Die Settings-Umsetzung ersetzt diese
   Zwischenloesung durch die globale Konfiguration.
5. Wechsel in Einstellungen wirkt:
   - Sofort für UI (nach Reload oder dynamischem Re-Render)
   - Für neue Logs ab nächstem Joblauf
6. Alte Logs bleiben in bisheriger Sprache erhalten.

## Architektur

### 1) Zentrale i18n-Schicht UI
- `ui/js/components/i18n.js` stellt die Funktionen `t()`, `setLanguage()` und
  `translate()` bereit.
- `ui/i18n/de.json` und `ui/i18n/en.json` enthalten die Ressourcen.
- Markup kann Text und Attribute ueber `data-i18n*` referenzieren.
- Dynamisch eingefuegte markierte Elemente werden ebenfalls uebersetzt.
- Fallback-Kette: `selected -> de -> key`.
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
1. UI-i18n-Layer (`t()`) und Sprachressourcen einführen.
2. Auswahl lokal speichern, bis die Settings-Anbindung umgesetzt ist.
3. Navigation und Sidebar als kleine Referenzflaeche umstellen.
4. `UI_LANGUAGE` in Config und Settings-Select in der zugeordneten
   Teilumsetzung ergänzen.

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
- Automatisiert:
  - Ressourcen muessen gueltiges JSON enthalten.
  - Deutsche und englische Schluessel muessen identisch sein.
  - Im HTML referenzierte Schluessel muessen in beiden Ressourcen existieren.
  - Der deutsche Fallback darf nicht durch Browser-Spracherkennung ersetzt
    werden.

## Wiederholbares Hardcode-Audit
- Jede Seitenmigration sucht in den zugeordneten HTML- und JavaScript-Dateien
  nach sichtbaren Texten und ueberfuehrt sie domaenenweise.
- Vor Abschluss des Umbrella-Issues prueft Issue `#25` alle UI-Dateien erneut.
- Hilfreiche Ausgangssuche:
  `rg -n "textContent|innerHTML|placeholder|title=|aria-label|>[^<]+<" ui`
- Externe Borg-, SSH- und Betriebssystemausgaben werden dabei nicht als eigene
  UI-Texte bewertet.

## Risiken & Gegenmaßnahmen
- Risiko: Inkonsistente Texte bei gemischter Hardcode/i18n-Nutzung.
  - Maßnahme: schrittweise aber domänenweise komplett umstellen.
- Risiko: Lange EN-Texte sprengen Layout.
  - Maßnahme: UI-Review je Seite, responsive Nacharbeit.
- Risiko: Fehlertexte aus externen Tools nicht übersetzbar.
  - Maßnahme: klar trennen zwischen internen und externen Meldungen.

## Offene Entscheidungen
1. Soll `UI_LANGUAGE` auch E-Mail-Report-Texte steuern?
2. Soll Sprache langfristig global bleiben oder pro Benutzer gelten?

## Empfohlener Start
- Nach der Infrastruktur aus Issue `#12` die Seiten schrittweise und
  domaenenweise umstellen.
- Danach `UI_LANGUAGE` global anbinden sowie Logs in Restore-Test und Runner
  umstellen.
- So ist der sichtbare Mehrwert früh da, mit kontrolliertem Risiko.
