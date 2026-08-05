# Manuelle Maintests auf Unraid

Diese Checkliste definiert die manuellen Abnahmetests fuer eine frische
Installation und ein Update von Borg Backup UI. Ein vollstaendiger Durchlauf
ist vor der ersten Veroeffentlichung ueber Unraid Community Apps erforderlich.
Bei spaeteren Releases werden mindestens der Update-Durchlauf und alle vom
Release betroffenen bedingten Pruefungen wiederholt.

Die Checkliste ergaenzt automatisierte Tests und den Preflight. Sie ersetzt
weder ein Backup noch die bewusste Pruefung eines Release-Diffs.

## Sicherheitsregeln

- Ausschliesslich ein separates Unraid-Testsystem und Testdaten verwenden.
- Keine Produktiv-Repositories, Produktiv-Secrets oder produktiven Zeitplaene
  verwenden.
- Eine Neuinstallation nur auf einem System pruefen, auf dem Borg Backup UI
  noch nie installiert war. Bestehende Nutzerdaten nicht loeschen, um einen
  vermeintlich frischen Zustand herzustellen.
- Testpfade eindeutig kennzeichnen und vor jeder Aktion kontrollieren.
- Passphrases, Tokens, private Keys und SMB-Zugangsdaten weder in Screenshots
  noch im Testprotokoll erfassen.
- Bei unerwartetem Datenverlust, Secret-Leak oder Zugriff auf Produktivdaten den
  Test sofort abbrechen und die Freigabe blockieren.

## Testumfang und Bewertung

Kennzeichnung:

- **P**: Pflicht fuer die Community-Apps-Erstveroeffentlichung.
- **U**: Pflicht fuer jeden finalen Update-/Release-Kandidaten.
- **B**: Bedingt erforderlich, wenn der Release den genannten Bereich aendert
  oder die benoetigte Hardware im offiziell zugesagten Testumfang liegt.

Jeder Schritt wird mit einem Ergebnis dokumentiert:

- `PASS`: Erwartetes Verhalten vollstaendig beobachtet.
- `FAIL`: Erwartetes Verhalten nicht erreicht; Freigabe blockiert.
- `BLOCKED`: Testumgebung oder Voraussetzung fehlt; fuer Pflichtschritte wie
  `FAIL` behandeln.
- `N/A`: Nur fuer bedingte Schritte mit dokumentierter Begruendung.

## Testprotokoll vorbereiten

Vor dem Test folgende Daten erfassen:

| Feld | Wert |
|---|---|
| Datum und Tester | |
| Source-Branch und Commit | |
| Testversion | |
| Vorherige Version beim Update | |
| Unraid-Version | |
| Python-Version | |
| Browser und Version | |
| Verwendete Storage-Arten | |
| Ergebnis Fresh Install | `PASS / FAIL / BLOCKED` |
| Ergebnis Update | `PASS / FAIL / BLOCKED` |

Als Evidenz genuegen Schritt-ID, Ergebnis und eine kurze Beobachtung. Bei einem
Fehler zusaetzlich Request-ID, Uhrzeit und bereinigte relevante Logzeilen
notieren. Screenshots sind optional und muessen frei von Secrets sein.

## Voraussetzungen

- Der Release-Kandidat wurde ueber `./plugin/deploy-test.sh <version>` in den
  internen Test-Channel bereitgestellt.
- Version, Paket-URL und MD5 im Remote-Testmanifest wurden gemaess
  [Release-Workflow](./release-workflow.md) verifiziert.
- `./plugin/mr-preflight.sh` war fuer den zu testenden Commit erfolgreich.
- Das Unraid-Array ist gestartet.
- `Python 3 for Unraid` stellt Python 3.10 oder neuer bereit.
- Fuer den Basistest stehen vier ausschliessliche Testpfade zur Verfuegung:
  - Quelle: `/mnt/user/borg-ui-maintest-source`
  - Repository: `/mnt/user/borg-ui-maintest-repository`
  - Restore-Ziel: `/mnt/user/borg-ui-maintest-restore`
  - Betriebsdaten: `/mnt/user/borg-ui-maintest-data`
- Die Quelle enthaelt mindestens eine kleine Textdatei und eine Datei in einem
  Unterverzeichnis. Vor dem Backup werden Dateiname, Groesse und SHA-256 der
  Textdatei im Testprotokoll notiert.

Andere Pfade sind erlaubt, muessen aber im Testprotokoll festgehalten werden.

## A. Frische Installation

### A1 - Ausgangszustand und Installation

- [ ] **A1.1 (P)** Bestaetigen, dass Borg Backup UI auf diesem Testsystem noch
  nie installiert war und keine frueheren Borg-Backup-UI-Betriebsdaten
  vorhanden sind.
- [ ] **A1.2 (P)** Test-Plugin mit dem vom Maintainer bereitgestellten internen
  Testmanifest ueber die Unraid-Plugininstallation installieren.
- [ ] **A1.3 (P)** Installationsausgabe endet ohne Fehler; die erwartete
  Testversion wird angezeigt.
- [ ] **A1.4 (P)** Die Unraid-Control-Page zeigt einen laufenden Dienst sowie den
  erkannten Python-Pfad und eine unterstuetzte Python-Version.
- [ ] **A1.5 (P)** `/var/log/borg_backup_ui.log` enthaelt keine Secrets und keine
  unerwarteten Tracebacks. Von Borg Backup UI erzeugte Meldungen sind Englisch.

### A2 - Erstkonfiguration und Anmeldung

- [ ] **A2.1 (P)** Beim ersten Oeffnen erscheint die Erstkonfiguration auf
  Deutsch, wenn im Browser noch keine Sprache fuer Borg Backup UI gespeichert
  ist.
- [ ] **A2.2 (P)** Einen ausschliesslichen Test-Administrator mit einem Passwort
  von mindestens 12 Zeichen anlegen. Validierungsfehler werden in der UI
  angezeigt, ohne rohe Servermeldung oder Secret auszugeben.
- [ ] **A2.3 (P)** Nach erfolgreicher Anlage erfolgt die Anmeldung und die
  Hauptoberflaeche wird geladen.
- [ ] **A2.4 (P)** Abmelden und mit korrekten Zugangsdaten erneut anmelden.
- [ ] **A2.5 (P)** Eine falsche Anmeldung wird abgelehnt und gibt keinen Hinweis,
  welcher Teil der Zugangsdaten falsch war.

### A3 - Grundeinstellungen und Systemzustand

- [ ] **A3.1 (P)** In **Einstellungen** `GLOBAL_DATA_DIR` auf den vorbereiteten
  Testpfad setzen und speichern.
- [ ] **A3.2 (P)** Seite neu laden. Einstellung und Anmeldung bleiben erhalten.
- [ ] **A3.3 (P)** **Systemzustand & Migration** laedt ohne Serverfehler. Pfade,
  Python/Borg-Status und offene Punkte sind plausibel.
- [ ] **A3.4 (P)** Es gibt keine fehlgeschlagene Startmigration. Eventuelle
  Hinweise fuer eine leere Neuinstallation sind verstaendlich und nicht als
  erfolgreicher Backup-Nachweis dargestellt.

### A4 - Sprache Deutsch und Englisch

- [ ] **A4.1 (P)** Sprache auf Englisch umstellen und nacheinander Dashboard,
  Jobs, Storage, History, Reports, Browse & Restore, Restore Tests, Settings und
  Help oeffnen. Navigation, Ueberschriften, Aktionen, leere Zustaende und
  Dialoge sind Englisch und enthalten keine sichtbaren i18n-Schluessel.
- [ ] **A4.2 (P)** Seite neu laden. Englisch bleibt im selben Browser aktiv.
- [ ] **A4.3 (P)** Abmelden. Die Login-Seite erscheint Englisch; eine
  fehlgeschlagene Anmeldung zeigt eine englische UI-Meldung.
- [ ] **A4.4 (P)** Wieder anmelden, auf Deutsch wechseln und die Seiten aus
  A4.1 stichprobenartig erneut oeffnen. Deutsche Texte und Layout bleiben
  nutzbar.
- [ ] **A4.5 (P)** Ein neuer Backup-Log bleibt unabhaengig von der UI-Sprache
  Englisch. Unveraenderte Ausgaben externer Werkzeuge wie Borg oder SSH duerfen
  deren eigene Sprache verwenden.

### A5 - Job anlegen und Backup ausfuehren

- [ ] **A5.1 (P)** Im Wizard einen eindeutig benannten lokalen Testjob mit der
  vorbereiteten Quelle und dem Test-Repository anlegen. Ausschliesslich eine
  Test-Passphrase verwenden.
- [ ] **A5.2 (P)** Wizard-Vorschau zeigt Quelle, Repository und Location korrekt;
  der Job laesst sich ohne Validierungsfehler speichern.
- [ ] **A5.3 (P)** Job manuell starten. Live-Ausgabe erreicht einen erfolgreichen
  Endstatus und enthaelt keine Secrets.
- [ ] **A5.4 (P)** Dashboard und Jobs zeigen den erfolgreichen Lauf.
- [ ] **A5.5 (P)** History enthaelt genau den erwarteten Lauf mit plausibler Zeit,
  Dauer und Datenmenge. Das Archiv ist im Repository vorhanden.

### A6 - Storage- und Repository-Pruefung

- [ ] **A6.1 (P)** Auf der Storage-Seite den lokalen Testjob auswaehlen und den
  schnellen Repository-Test ausfuehren.
- [ ] **A6.2 (P)** Der Test endet erfolgreich und zeigt keine Authentifizierungs-,
  Pfad- oder Passphrase-Fehler.
- [ ] **A6.3 (B)** Fuer SMB: Testprofil anlegen, Verbindung testen, mounten,
  Repository pruefen, wieder unmounten und den Status nach jedem Schritt
  kontrollieren.
- [ ] **A6.4 (B)** Fuer Storagebox/SSH: Testprofil und Test-Key verwenden,
  Verbindung sowie konkretes Repository pruefen.
- [ ] **A6.5 (B)** Fuer USB: Testprofil mit eindeutigem Testdatentraeger pruefen
  und sicherstellen, dass kein anderer Datentraeger als Ziel akzeptiert wird.

### A7 - Browse und Restore

- [ ] **A7.1 (P)** **Browse & Restore** oeffnen, Testjob und neu erzeugtes Archiv
  auswaehlen und die gesicherte Verzeichnisstruktur anzeigen.
- [ ] **A7.2 (P)** Die vorbereitete Textdatei in das leere Restore-Testziel
  wiederherstellen.
- [ ] **A7.3 (P)** Name, Groesse, Inhalt und SHA-256 der wiederhergestellten Datei
  stimmen mit der Quelle ueberein.
- [ ] **A7.4 (P)** Ein Ziel ausserhalb der erlaubten Restore-Roots wird abgelehnt,
  ohne dort Daten anzulegen.
- [ ] **A7.5 (P)** Restore-Status und History zeigen einen erfolgreichen Vorgang
  ohne Secret-Inhalte.

### A8 - Restore-Test

- [ ] **A8.1 (P)** Fuer den Testjob eine manuelle Restore-Test-Policy mit Level 1
  konfigurieren.
- [ ] **A8.2 (P)** Restore-Test manuell starten und bis zum Endstatus beobachten.
- [ ] **A8.3 (P)** Ergebnis ist erfolgreich; Bericht nennt Archiv, gepruefte
  Schritte und Zeitpunkt plausibel.
- [ ] **A8.4 (P)** Restore-Tests-Seite, Dashboard und History zeigen einen
  konsistenten Status.

### A9 - Dienstneustart und Systemneustart

- [ ] **A9.1 (P)** Dienst ueber die Unraid-Control-Page neu starten. Danach sind
  Login, Einstellungen, Job, History und Restore-Test-Bericht weiterhin da.
- [ ] **A9.2 (P)** Unraid-Testsystem einmal neu starten. Das Plugin startet
  automatisch und die in A9.1 genannten Daten bleiben erhalten.
- [ ] **A9.3 (P)** Nach dem Neustart erneut Systemzustand und Repository-Zugriff
  pruefen.

## B. Update einer bestehenden Installation

Der Update-Test beginnt auf einem separaten Testsystem oder einem bewusst
vorbereiteten Ausgangszustand mit der vorherigen stabilen Plugin-Version. Vor
dem Update muessen mindestens ein Benutzer, `GLOBAL_DATA_DIR`, ein Storage-
Profil, ein erfolgreicher Testjob, ein Archiv, ein Restore-Test-Bericht und eine
von Deutsch abweichende gespeicherte UI-Sprache vorhanden sein.

### B1 - Update vorbereiten

- [ ] **B1.1 (U)** Vorherige Plugin-Version und Systemzustand dokumentieren.
- [ ] **B1.2 (U)** Letzten erfolgreichen Backup- und Restore-Test-Lauf
  dokumentieren.
- [ ] **B1.3 (U)** Konfiguration und Jobs ueber die vorhandenen Export-/Backup-
  Funktionen sichern. Export ausserhalb der Plugin-Betriebsdaten ablegen.
- [ ] **B1.4 (U)** Sicherstellen, dass kein Backup, Restore, Check oder
  Restore-Test laeuft.

### B2 - Update installieren

- [ ] **B2.1 (U)** Exakt den vorbereiteten Test-Channel-Release ueber die
  Unraid-Pluginaktualisierung installieren.
- [ ] **B2.2 (U)** Installation endet ohne Fehler und zeigt die erwartete neue
  Version.
- [ ] **B2.3 (U)** Dienst laeuft; Serverlog enthaelt keine unerwarteten
  Tracebacks und keine Secrets.
- [ ] **B2.4 (U)** Bestehende Anmeldung oder erneute Anmeldung funktioniert nach
  dem Update wie erwartet.

### B3 - Bestand und Migration pruefen

- [ ] **B3.1 (U)** `GLOBAL_DATA_DIR`, Benutzer, Rollen, Jobs, Schedules,
  Storage-Profile und Secret-Referenzen sind erhalten.
- [ ] **B3.2 (U)** Die zuvor gewaehlte UI-Sprache bleibt im Browser aktiv; Login
  und Hauptoberflaeche verwenden dieselbe Sprache.
- [ ] **B3.3 (U)** Systemzustand und letzter Migrationslauf sind erfolgreich oder
  enthalten nur erklaerte, nicht blockierende Hinweise.
- [ ] **B3.4 (U)** Vorhandene Archive, History-Eintraege und Restore-Test-Berichte
  sind weiterhin sichtbar.
- [ ] **B3.5 (U)** Bestehende Konfigurationsdateien wurden nicht unerwartet durch
  Defaults ersetzt.

### B4 - Funktions-Smoke-Test nach Update

- [ ] **B4.1 (U)** Bestehenden Testjob manuell erfolgreich ausfuehren.
- [ ] **B4.2 (U)** Repository-Test fuer diesen Job erfolgreich ausfuehren.
- [ ] **B4.3 (U)** Neues Archiv browsen und die Markerdatei in ein leeres Ziel
  restoren; SHA-256 stimmt mit der Quelle ueberein.
- [ ] **B4.4 (U)** Manuellen Restore-Test erfolgreich ausfuehren.
- [ ] **B4.5 (U)** Dienst neu starten und Bestand aus B3 erneut stichprobenartig
  pruefen.
- [ ] **B4.6 (B)** Alle vom Release geaenderten Profile, Benachrichtigungen,
  E-Mail-/Report-Funktionen oder Import-/Export-Pfade gezielt testen.

## C. Abschluss und Freigabeentscheidung

- [ ] **C1 (P/U)** Alle Pflichtschritte besitzen ein Ergebnis und eine kurze
  Beobachtung.
- [ ] **C2 (P/U)** Keine offenen `FAIL`- oder `BLOCKED`-Ergebnisse.
- [ ] **C3 (P/U)** Keine Regression bei Authentifizierung, Backup, Repository-
  Zugriff, Restore, Restore-Test oder Sprachwahl.
- [ ] **C4 (P/U)** Keine Secrets oder unerwarteten personenbezogenen Daten in
  Logs, Reports, Screenshots oder Support-Dateien gefunden.
- [ ] **C5 (P/U)** Getestete Version und Commit stimmen mit dem zu promotenden
  Release-Artefakt ueberein.
- [ ] **C6 (P/U)** Gesamtergebnis und verbleibende `N/A`-Begruendungen im
  Release-/PR-Protokoll dokumentiert.

Freigaberegel: Community-Apps-Veroeffentlichung oder Promotion duerfen nur
fortgesetzt werden, wenn alle fuer den Durchlauf erforderlichen Schritte
`PASS` sind. Ein `FAIL` oder `BLOCKED` benoetigt ein Issue, einen neuen
Release-Kandidaten und die Wiederholung aller durch die Korrektur betroffenen
Schritte.

