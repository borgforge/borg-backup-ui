# Konzept: Spracheinstellung Deutsch / English (UI)

## Ziel
- In **Einstellungen** als erstes Feld: `Sprache / Language` mit `de` und `en`.
- Alle sichtbaren UI-Texte zweisprachig.
- Alle Ausgaben ausserhalb der interaktiven UI bleiben ausschliesslich Englisch.
- Rückwärtskompatibel für bestehende Installationen.

## Nicht-Ziele (Phase 1)
- Keine automatische Browser-Spracherkennung als Primärmechanismus.
- Keine dritte Sprache.
- Keine vollständige Retro-Migration alter Logdateien.

## UX/Produktentscheidung
1. Standardwert bei Neuinstallation: `de`.
2. Bestehende Installationen ohne gesetzte Sprache: Fallback `de`.
3. Die UI-Auswahl wird im Browser unter `borg-backup-ui.language` gespeichert.
4. Ein Wechsel wirkt sofort auf die UI (nach Reload oder dynamischem Re-Render).
5. Die UI-Sprache beeinflusst keine technischen oder automatisch erzeugten
   Ausgaben.
6. Logs, E-Mails, Wochenberichte, Unraid-Benachrichtigungen und Meldungen an
   VMs werden durch Borg Backup UI ausschliesslich auf Englisch erzeugt.
7. Alte Logs und bereits gespeicherte Statusdaten werden nicht umgeschrieben.

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
- Die Spracheinstellung ist eine reine UI-Einstellung.
- APIs liefern stabile `message_code`- und `message_params`-Werte fuer
  lokalisierbare UI-Rueckmeldungen.
- Englische Klartexte bleiben als maschinen- und clientkompatible Fallbacks
  erhalten.

### 3) Server/Backend-Meldungen
- Backend-Fallbacktexte, technische Fehler und Fehlercodes bleiben Englisch.
- Die UI uebersetzt bekannte Meldungscodes ueber ihre Sprachressourcen.
- Maschinenlesbare Werte und Fehlercodes werden nicht lokalisiert.

### 4) Externe Ausgaben
- Eigene Logtexte, Runner-Ausgaben und Restore-Test-Logs sind Englisch.
- E-Mail-Betreff und -Inhalt, einschliesslich Test- und Backup-Fehlermails,
  sind Englisch.
- Der automatisch erzeugte Wochenbericht ist in Text- und HTML-Form Englisch.
- Unraid- und VM-Benachrichtigungen sind Englisch.
- Wichtig:
  - Tool-Ausgaben von borg/ssh bleiben unverändert (extern erzeugt)
  - Inhalte aus alten Logs oder Statusdateien koennen weiterhin historischen
    deutschen Text enthalten

## Schlüsselstruktur (Vorschlag)
- UI Keys:
  - `nav.dashboard`, `nav.jobs`, `jobs.run_now`, `restore.level`, ...
- API message codes:
  - `smtp_test_sent`, `weekly_report_sent`, `job_not_found`, ...

Konvention:
- Namespace nach Domäne (`nav.*`, `settings.*`, `restore.*`, `log.*`, `err.*`)
- Keine Sätze als Schlüssel, nur stabile IDs.

## Migrationsplan

### Phase A: Grundlage
1. UI-i18n-Layer (`t()`) und Sprachressourcen einführen.
2. Auswahl lokal speichern, bis die Settings-Anbindung umgesetzt ist.
3. Navigation und Sidebar als kleine Referenzflaeche umstellen.

### Phase B: Vollständige UI
1. Alle statischen UI-Texte ersetzen.
2. Dialoge/Toasts/Statusmeldungen ersetzen.
3. Fehlermeldungen aus API konsistent darstellen.

### Phase C: Externe Ausgaben & Backend
1. Eigene technische Logs auf Englisch vereinheitlichen.
2. E-Mails, Wochenberichte und Benachrichtigungen auf Englisch vereinheitlichen.
3. API-Meldungscodes fuer lokalisierbare UI-Rueckmeldungen konsolidieren.

### Phase D: Qualität
1. Missing-Key-Check (de/en-Parität).
2. Snapshot/Testfälle für beide Sprachen.
3. Review auf Textlängen/Umbrüche in EN.

## Teststrategie
- Manuell:
  - Sprache de/en wechseln -> UI neu rendern -> Texte korrekt.
  - Job in beiden UI-Sprachen starten -> neue Logdatei bleibt Englisch.
  - Testmail und Wochenbericht senden -> Betreff und Inhalt sind Englisch.
- Automatisiert:
  - Ressourcen muessen gueltiges JSON enthalten.
  - Deutsche und englische Schluessel muessen identisch sein.
  - Im HTML referenzierte Schluessel muessen in beiden Ressourcen existieren.
  - Der deutsche Fallback darf nicht durch Browser-Spracherkennung ersetzt
    werden.
  - Eigene technische Logtexte und erzeugte Mailinhalte muessen Englisch sein.

## Wiederholbares Hardcode-Audit
- Jede Seitenmigration sucht in den zugeordneten HTML- und JavaScript-Dateien
  nach sichtbaren Texten und ueberfuehrt sie domaenenweise.
- Der wiederholbare Abschlusscheck aus Issue `#25` wird ausgefuehrt mit:
  `python3 plugin/i18n_audit.py`
- Der Audit prueft `ui/index.html` auf sichtbare Textknoten ohne
  `data-i18n*`-Markierung und `ui/js/**/*.js` auf deutsche String-Literale.
- `python3 plugin/i18n_audit.py --backend` erweitert den Check um deutsche
  String-Literale in `borg_backup_ui.py`, `api/**/*.py` und `runtime/**/*.py`.
  Seit Issue `#47` ist dieser Modus Teil des automatisierten Merge-Gates; Issue
  `#49` hat den Hauptserver in denselben Check aufgenommen.
- `tests/test_i18n_resources.py` fuehrt denselben Audit bei jedem Testlauf aus.
- Technische Produktnamen, Pfade, Konfigurationswerte, Formatnamen und reine
  interne Routen-IDs sind keine zu uebersetzenden UI-Texte.
- Historische deutsche Backendtexte, die nur zur Rueckwaertskompatibilitaet
  erkannt und anschliessend auf lokalisierte Codes abgebildet werden, sind
  explizit als Kompatibilitaetswerte dokumentiert.
- Externe Borg-, SSH- und Betriebssystemausgaben werden dabei nicht als eigene
  UI-Texte bewertet.

### Abschlussinventar aus Issue #25
- Migriert wurden die verbliebenen Texte der Hilfe-Seite, generische Dialog- und
  Logtitel, Rollenhinweise und Toast-Fallbacktitel.
- Die Unraid-Control-Page bleibt bewusst Englisch und wird durch
  `tests/test_plugin_control_page.py` abgesichert.
- Eigene Logs, E-Mails, Reports und Benachrichtigungen bleiben gemaess Issue
  `#23` bewusst Englisch.
- API-Klartexte bleiben englische Fallbacks; die UI verwendet uebersetzte
  `message_code`- und `error_code`-Werte.
- Der eigentliche Inhalt von `ui/docs/help.md` gehoert zur zweisprachigen
  Dokumentationsstrategie in Issue `#22` und ist nicht Teil dieses UI-Audits.
- Backend-Fallbacks, Diagnosetexte und generierte Runner-Texte wurden in Issue
  `#47` auf Englisch vereinheitlicht. Historische deutsche Migrationswerte und
  Logmarker werden weiterhin gelesen, aber nicht neu erzeugt.
- Die in `borg_backup_ui.py` eingebetteten Login- und Erstsetup-Seiten verwenden
  seit Issue `#49` dieselbe browserlokale Sprachwahl und dieselben Ressourcen
  wie die Hauptoberflaeche. Sie zeigen lokalisierte Fehlercodes statt roher
  Servermeldungen; verbleibende Hauptserver-Fallbacks sind Englisch.

## Risiken & Gegenmaßnahmen
- Risiko: Inkonsistente Texte bei gemischter Hardcode/i18n-Nutzung.
  - Maßnahme: schrittweise aber domänenweise komplett umstellen.
- Risiko: Lange EN-Texte sprengen Layout.
  - Maßnahme: UI-Review je Seite, responsive Nacharbeit.
- Risiko: Fehlertexte aus externen Tools nicht übersetzbar.
  - Maßnahme: klar trennen zwischen internen und externen Meldungen.

## Offene Entscheidung
1. Soll die UI-Sprache langfristig browserlokal bleiben oder pro Benutzer
   gespeichert werden?

## Empfohlener Start
- Nach der Infrastruktur aus Issue `#12` die Seiten schrittweise und
  domaenenweise umstellen.
- Danach externe Ausgaben auf Englisch vereinheitlichen.
- So ist der sichtbare Mehrwert früh da, mit kontrolliertem Risiko.
