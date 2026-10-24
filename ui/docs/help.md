# Borg Backup UI - Benutzerleitfaden

Diese Hilfe begleitet Einsteiger, fortgeschrittene Anwender und Administratoren durch den vollständigen Backup-Lebenszyklus. Wählen Sie links ein Kapitel oder suchen Sie nach einer Aufgabe, einem Status oder einer Fehlermeldung.

> [!IMPORTANT] Backups sind erst belastbar, wenn mindestens ein Restore-Test und eine manuelle Wiederherstellung in ein Testziel erfolgreich waren.

## 1. Erste Schritte

### Vor dem ersten Backup

1. Öffnen Sie **Einstellungen > Allgemein** und prüfen Sie den Systemzustand.
2. Legen Sie unter **Lokale Profile**, **USB-Profile**, **SMB-Profile** oder **SSH-Profile** ein Speicherziel an.
3. Erstellen oder importieren Sie unter **Repositories** ein Borg-Repository.
4. Erstellen Sie unter **Jobs** einen Backup-Job und wählen Sie das vorhandene Repository.
5. Starten Sie den Job zuerst manuell und prüfen Sie Live-Log und **History**.
6. Stellen Sie eine bekannte Datei über **Browse & Restore** in ein separates Ziel wieder her; **Testlauf** dafür ausschalten. Vergleichen Sie den Inhalt.
7. Aktivieren Sie erst danach Zeitplan, Restore-Test und Benachrichtigungen.

[Vollständiger Schnellstart mit Beispielpfaden](../../docs/user-manual/de/user-manual.md#schnellstart-erstes-backup-und-geprüfter-restore).

### Grundbegriffe

- **Speicherziel:** Physischer oder entfernter Ort, zum Beispiel ein Unraid-Pool, USB-Datenträger, SMB-Share oder SSH-Server.
- **Repository:** Borg-Datenspeicher auf einem Speicherziel. Er enthält die Archive und besitzt Verschlüsselung sowie Passphrase oder Keyfile.
- **Job:** Legt Quellen, Ausschlüsse, Kompression, Aufbewahrung, Docker-/VM-Steuerung und Zeitplan fest.
- **Archiv:** Ein einzelner Sicherungsstand innerhalb eines Repositorys.
- **Restore-Test:** Automatisierte Prüfung, ob Daten aus einem Archiv wiederhergestellt werden können.

> [!TIP] Richten Sie zuerst Speicherziel und Repository ein. Der Job-Wizard legt keine Repositorys mehr nebenbei an.

## 2. Oberfläche und Rollen

### Navigation

Das Hauptmenü folgt dem Betriebsablauf: **Dashboard**, **Jobs**, **Repositories**, **History**, **Berichte**, **Browse & Restore**, **Restore Tests**, **Einstellungen** und **Hilfe**. Unten links befinden sich Systemstatus, Sprache, Anmeldung und Version.

### Rollen

- **viewer:** Darf Zustände und Berichte lesen, aber keine Änderungen speichern.
- **operator:** Darf betriebliche Aktionen ausführen, jedoch keine administrativen Einstellungen verwalten.
- **admin:** Darf Benutzer, Einstellungen, Speicherziele, Repositorys und Jobs verwalten.

### Statusfarben

- **Grün:** Erfolgreich, bereit oder verifiziert.
- **Orange:** Warnung, überfällig oder Aufmerksamkeit erforderlich.
- **Rot:** Fehlgeschlagen, nicht erreichbar oder blockiert.
- **Grau:** Nicht geplant, nicht ausgeführt oder unbekannt.

## 3. Dashboard

Zwei Kreise zeigen die letzten Backup-Ergebnisse und Restore-Nachweise. Überfällige Backups werden zusätzlich unter dem ersten Kreis angezeigt, ohne das letzte Laufergebnis zu verändern. Der Restore-Kreis bezieht sich auf Jobs mit Testplan; Jobs ohne Plan oder mit unbekanntem Status stehen separat darunter.

**Handlungsbedarf** zeigt Fehlertexte, Warnungen, übersprungene Läufe und überfällige Backups oder Restore-Nachweise. **Ansehen** öffnet den betroffenen Job. Die Standort-Sidebar behält ihre Icons und filtert nach Lokal, USB, SMB oder Storagebox. Leere Standorte werden ausgeblendet; **Alle Standorte** bleibt nach Standorten gruppiert.

### Wichtige Spalten

- **Backup:** Job-Icon mit konfigurierter Farbe, Jobname und letzter Archivname.
- **Laufstatus:** Ergebnis, relativer Zeitpunkt und Dauer des letzten Backup-Laufs sowie vorhandene Fehlertexte.
- **Nächster Lauf:** Nächster geplanter Lauf einschließlich Gruppenzeitplänen und zusätzlichem Überfälligkeitshinweis.
- **Restore:** Nachweisstatus und Gültigkeit.
- **Repository:** Repository-Größe und **Details** zum Aufklappen. Die Details enthalten Quellgröße, komprimierte und deduplizierte Daten, Wachstum, Borg-Check im letzten Lauf, gespeicherten Repository-Check, Restore-Daten und den vollständigen Archivnamen. Es gibt keinen zusätzlichen Checkplan. Geöffnete Details bleiben bei Aktualisierung, Standort- und Sprachwechsel erhalten.

> [!NOTE] Das Dashboard zeigt zuletzt gespeicherte Statusdaten. Für technische Details öffnen Sie **History**, **Berichte** oder **Repositories**.

## 4. Speicherziele und Profile

Speicherziele werden zentral unter **Einstellungen** verwaltet. Ein Profil darf erst gelöscht werden, wenn kein Repository oder Job mehr darauf verweist.

### Lokale Profile

Verwenden Sie konkrete Pfade unter `/mnt`, zum Beispiel `/mnt/backup`, `/mnt/cache/backups` oder einen Unraid-Pool. Zu breite Wurzeln und Systempfade werden abgelehnt.

### USB-Profile

Ein USB-Profil verweist auf einen vorhandenen Mount-Pfad. Der Datenträger muss zum Laufzeitpunkt gemountet sein; andernfalls wird der Lauf geschützt übersprungen oder abgebrochen.

### SMB-Profile

Der Verbindungstest prüft Port 445, Anmeldung, temporären Mount, Share, Schreibzugriff und Unmount. Verwenden Sie SMB 2 oder 3; SMB 1 wird nicht unterstützt.

### SSH-Profile

SSH-Profile enthalten Host, Port, Benutzer, Basispfad und SSH-Key. Vorhandene Schlüssel werden nicht überschrieben. Prüfen und deployen Sie den öffentlichen Schlüssel, bevor Sie ein Repository importieren.

## 5. Repositories

Die Seite **Repositories** gruppiert Borg-Repositorys nach Speicherziel. Ein Repository besitzt einen Anzeigenamen, einen vollständigen Repository-Pfad, Verschlüsselungsmetadaten und optionale Job-Zuordnungen.

### Repository erstellen

1. Klicken Sie auf **Repository hinzufügen**.
2. Wählen Sie ein vorhandenes Speicherziel.
3. Wählen Sie **Neues Repository erstellen**.
4. Geben Sie Anzeigename, Pfad im Speicherziel und Verschlüsselung an.
5. Hinterlegen Sie die Passphrase oder wählen Sie ein Keyfile-Verfahren.
6. Prüfen Sie die Zusammenfassung und speichern Sie das Repository.

### Repository importieren

Wählen Sie **Vorhandenes Repository importieren** und anschließend ein Verzeichnis innerhalb des Speicherziels. Bei verschlüsselten Repositorys ist die passende Passphrase oder ein vorhandener beziehungsweise importierter Borg-Key erforderlich.

### Reiter

- **Übersicht:** Borg-Größen, Archivanzahl, Zustand, Pfad, Speicherziel, Verschlüsselung und Job-Zuordnung.
- **Archive:** Archive, technische IDs, Zeitpunkte und Dauer; neueste Archive stehen zuerst. Wählen Sie ein Archiv aus, um dessen Ordner und Dateien direkt in einer schreibgeschützten Ansicht zu durchsuchen. Dies funktioniert auch für importierte Archive ohne Job-Zuordnung. Beim ersten Öffnen kann das Einlesen des Archivindex bei großen oder entfernten Repositorys länger dauern. Wiederherstellung, Download und Dateivorschau bleiben dem separaten **Browse & Restore**-Ablauf vorbehalten.
- **Wartung:** Check, vollständige Datenprüfung, Prune und Compact.
- **Verwaltung:** Job-Verknüpfungen, Entfernen aus der UI und geschützte endgültige Löschung.

> [!WARNING] Eine endgültige Repository-Löschung entfernt Borg-Daten. Sie ist nur ohne Job-Zuordnung und nach mehrstufiger Bestätigung möglich.

## 6. Backup-Jobs

Ein Job verbindet Quellen mit genau einem vorhandenen Repository. Verschlüsselung gehört zum Repository; Kompression und Aufbewahrung gehören zum Job.

### Job-Wizard

1. **Grunddaten:** Job-Name, dauerhafte Job-ID, Archivpräfix, Icon und optionale Docker-/VM-Steuerung.
2. **Quellen & Ziel:** Zu sichernde Ordner oder Dateien, Speichertyp, Speicherziel, Repository und Kompression.
3. **Ausschlüsse:** Pfade, Markerdateien und eine hochgeladene Ausschlussdatei, gemeinsam sichtbar in einem eigenen Schritt.
4. **Docker:** alle laufenden Container, nur ausgewählte Container oder alle außer ausgewählte Container stoppen und danach neu starten; optional nacheinander mit einem Archiv pro Container.
5. **VMs:** alle laufenden oder nur ausgewählte VMs herunterfahren und danach neu starten.
6. **Retention:** gestaffelt mit optionalem Zeitfenster, letzte X Archive oder alle behalten.
7. **Beschreibung:** verständliche Beschreibung mit optionalem Markdown.
8. **Zeitplan:** einfache Planung oder Cron-Ausdruck.
9. **Pre-/Post-Skripte:** optionale, zentral gespeicherte Skripte zuordnen.
10. **Flow-Vorschau:** endgültige Prüfung des geplanten Ablaufs.

Docker und VMs werden bei ausgeschalteter Steuerung übersprungen. Jobname, dauerhafte Job-ID und Archivpräfix sind getrennt; Umbenennen verändert die Identität nicht. Prune verwendet nur den aktuellen Präfix, Browse & Restore auch die gespeicherten früheren Präfixe.

> [!IMPORTANT] Retention-Werte zählen Zeiträume mit Backups. Wählen Sie „Gestaffelt“, „Letzte X Archive“ oder „Alle behalten“. Ein Zeitfenster wie „alle Archive der letzten 7 Tage“ ergänzt Zählregeln und darf nicht allein aktiv sein. `0` deaktiviert eine Regel. Leere Regeln und „letzte 0“ sind gesperrt. Eine kleine Anzahl kann viele ältere Archive zur Löschung freigeben. Das Info-i erklärt jede Strategie und ihre Löschwirkung, ohne den Wizard zu verlängern.

Beispiel: Werden an einem Tag Backups um 08:00 und 08:30 Uhr erstellt, behält die tägliche Regel nur einen Wiederherstellungspunkt für diesen Tag – normalerweise das neuere Archiv von 08:30 Uhr. Details und weitere Beispiele enthält das vollständige Handbuch unter **Backup-Jobs > Retention, Kompression und Beschreibung**.

### Quellen und Ausschlüsse

Quellen sind die Ordner oder Dateien, die ein Backup-Job sichern soll. Typische Beispiele sind `/mnt/user/appdata/`, `/mnt/user/domains/` oder eine eigene Share unter `/mnt/user/...`.

Mindestens eine Quelle ist erforderlich, weil der Job sonst nicht weiß, welche Daten gesichert werden sollen. Quellen müssen existieren und für den Backup-Prozess lesbar sein. Fehlende Pflichtquellen stoppen den Lauf, damit kein scheinbar erfolgreiches, aber unvollständiges Archiv entsteht.

Ausschlüsse sind optionale Unterordner oder Dateien innerhalb einer Quelle, die nicht ins Backup sollen. Ausschlüsse müssen deshalb unterhalb einer ausgewählten Quelle liegen.

> [!TIP] Starten Sie jeden neuen oder grundlegend geänderten Job einmal manuell, bevor Sie seinen Zeitplan aktivieren.

### Laufenden Job kontrolliert abbrechen

Bei einem laufenden Job fordert **Job abbrechen** einen kontrollierten Abbruch an. Ein aktiver Borg-Schritt wird unterbrochen. Läuft gerade das Stoppen von Docker-Containern oder VMs, wird dieser Vorgang vollständig beendet und anschließend werden die zuvor laufenden Systeme wieder gestartet. Während des Neustarts ist kein weiterer Abbruch möglich. Schlägt die Wiederherstellung fehl, endet der Lauf als Fehler und der Runtime-Recovery-Hinweis bleibt sichtbar.

Ein abgebrochener Lauf wird mit dem Status **Abgebrochen** gespeichert. Die Anwendung startet danach nicht automatisch einen Repository-Check und entfernt keine Borg-Locks. Prüfen Sie bei auffälligen Meldungen das Live- beziehungsweise gespeicherte Log.

### Jobgruppen

Unter **Jobs > Jobgruppen** können Administratoren vorhandene Jobs zu einer Reihenfolge mit eigenem Zeitplan zusammenfassen. Die Einzeljobs behalten ihre Einstellungen und zeigen ihre Gruppenzuordnung. Der nächste Job startet erst nach dem vollständigen Ende seines Vorgängers, einschließlich Wartung und Post-Skript. Einzelzeitpläne werden nicht automatisch geändert.

**Nach aktuellem Job stoppen** beendet die Folge nach dem laufenden Job. Bei Fehlern stoppt die Gruppe standardmäßig; eine Fortsetzung ist einstellbar. Andere Jobs können unabhängig starten. Ein Shutdown im letzten Job erfolgt nur, wenn dieser Job ausgeführt wird. Prüfen Sie zusätzliche Einzelzeitpläne und Skripte vor dem ersten automatischen Lauf.

[Einrichtung, Logansicht, Fehlerverhalten und Export](../../docs/user-manual/de/user-manual.md#38-jobgruppen).


## 7. Zeitplanung

Cron verwendet fünf Felder: Minute, Stunde, Tag, Monat und Wochentag. `0 3 * * *` startet einen Job täglich um 03:00 Uhr. Planen Sie große Jobs mit ausreichendem Abstand und vermeiden Sie parallele Zugriffe auf dasselbe Repository.

### Überfälligkeit

Die Anwendung berechnet den erwarteten Lauf aus dem Zeitplan. Nach Ablauf der konfigurierten Toleranz kann sie ueber Unraid, E-Mail oder Apprise-Profile informieren. Das Reminder-Intervall verhindert sofortige Wiederholungen.

## 8. Docker und VMs

Bei Docker kann die Auswahl positiv oder negativ verwendet werden. **Nur ausgewählte Container** stoppt exakt die markierten Container. **Alle außer ausgewählte Container** stoppt alle laufenden Container, lässt aber die markierten Container aktiv.

Mit **Container nacheinander stoppen und sichern** wird jeder Container nur gestoppt, solange seine eigenen Ordner gesichert werden, und danach sofort wieder gestartet. Die Ordner stammen aus den beschreibbaren Volume-Zuordnungen innerhalb der Backup-Quellen. Jeder Container erhält ein eigenes Archiv `<präfix>@<container>-<datum>`; Container mit gemeinsamen Ordnern werden zusammen gestoppt. Alle übrigen Pfade landen danach im normalen Archiv `<präfix>-<datum>`. Jede Archivserie wird mit der Aufbewahrung des Jobs separat bereinigt. Details: [Container nacheinander sichern](../../docs/user-manual/de/user-manual.md#container-nacheinander-sichern).

Die Anwendung zeichnet vor dem Backup auf, welche Container oder VMs tatsächlich liefen. Nur diese Ziele werden danach wieder gestartet. Bei einem Abbruch oder Serverneustart weist **Runtime-Recovery** im Systemstatus auf offene Neustarts hin.

### Appdata und Domains

- Bei einer vollständigen Sicherung von `/mnt/user/appdata` sollten alle schreibenden Container gestoppt werden.
- Bei einer vollständigen Sicherung von `/mnt/user/domains` sollten die betroffenen VMs heruntergefahren werden.
- Selektive Steuerung ist sinnvoll, wenn Quellen und abhängige Dienste eindeutig bekannt sind.

## 9. History und Live-Logs

**History** zeigt Backup-Läufe nach Standort, Typ und Status. Öffnen Sie einen Eintrag für Archivname, Größen, Dauer, Exit-Code, Repository-Check und Logdatei. Laufende Jobs besitzen ein Live-Log; abgeschlossene Läufe verweisen auf das gespeicherte Log.

Im Schritt **Grunddaten** des Job-Wizards kann **Dateiaktivität im Live-Log** pro Job aktiviert werden. Borg zeigt dann hinzugefügte (`A`), geänderte (`M`) und fehlerhafte (`E`) Einträge; unveränderte Einträge werden ausgelassen. Diese Angaben stammen aus Borgs Datei-Cache und sind weder eine Byte-Übertragungsanzeige noch eine vollständige Archivliste. Datei- und Verzeichnisnamen werden auch im gespeicherten Lauf-Log sichtbar und können in Support-Paketen enthalten sein.

### Borg-Ergebnisse

- Exit-Code `0` bedeutet Erfolg.
- Warnungen können ein nutzbares Archiv erzeugen, müssen aber geprüft werden.
- Fehler bedeuten, dass der Lauf nicht als verlässliche Sicherung gilt.
- Übersprungen bedeutet, dass eine Schutzbedingung wie fehlender Mount oder aktiver Parity-Check gegriffen hat.

## 10. Berichte

Berichte zeigen Kennzahlen und Trends pro Job. Dazu gehören Laufzahlen, Erfolgsquote, Dauer, Wachstum, Repository-Größe, Borg-Informationen und Restore-Nachweis. Wählen Sie links einen Job und aktualisieren Sie Borg-Informationen nur bei Bedarf.

## 11. Browse & Restore

Der Restore-Wizard führt durch Job, Archiv, Auswahl, Ziel und Prüfung. Im Zielschritt bezeichnet **Archiv-Pfad** die Auswahl innerhalb des Archivs; Repository und Archiv werden darunter separat angezeigt. Wiederherstellungen dürfen nur in freigegebene Zielbereiche geschrieben werden.

### Sicherer Ablauf

1. Wählen Sie Job und Archiv.
2. Markieren Sie Dateien oder Verzeichnisse.
3. Wählen Sie einen separaten Zielordner.
4. Verwenden Sie im Zweifel **Nicht überschreiben**.
5. Prüfen Sie die Zusammenfassung und Bestätigung.
6. Beobachten Sie Live-Log und anschließend **Restore History**.

> [!WARNING] Stellen Sie produktive Daten nicht ohne Prüfung direkt über vorhandene Dateien wieder her. Nutzen Sie zuerst ein Testziel.

## 12. Restore Tests

Unter **Planung & Policy > Plan bearbeiten** legen Administratoren Kalendertermin,
Testlevel und getrennte Nachweisgültigkeit fest. **Jetzt testen** startet manuell.
Die Serverzeitzone gilt; verpasste/übersprungene Termine werden nicht nachgeholt.
Ein Skip erneuert keinen Nachweis. Legacy-Intervalltests bleiben getrennt unter
**Einstellungen > Restore**. Ohne bisherigen Bericht gibt es keinen entsprechenden
Überfälligkeits-Reminder.

### Testlevel

- **L1:** Archivliste und Metadaten; kein vollständiger Datencheck.
- **L2:** `borg extract --dry-run` liest Daten und prüft sie mit Borg, schreibt aber keine wiederhergestellten Nutzdateien.
- **L3:** Zusätzlich ausgewählte Dateien über `--stdout` lesen und SHA-256 berechnen; kein unabhängiger Soll-Hash-Vergleich.

> [!WARNING] Die Auswahl ist das neueste Archiv des Repositorys, nicht zwingend
> des Jobs. Prüfen Sie den Archivnamen und die Einzelschritte. Im dokumentierten
> Stand können L1-Infofehler oder ein L2-Timeout hinter einem erfolgreichen
> Gesamtstatus stehen. Ein solcher Lauf ist kein belastbarer vollständiger Nachweis.

[Verfahren, Schreibzugriffe, Abdeckung und Grenzen](../../docs/user-manual/de/user-manual.md#83-testlevel).
Ein echter Restore in ein separates Ziel mit Inhalts- und Anwendungstest bleibt nötig.

## 13. Einstellungen

### Allgemein

Verwaltet Datenpfade, Theme, Log-Aufbewahrung, Borg-Cache, Parity-Schutz und Homepage-Widget. SMTP, Benachrichtigungskanäle und eigene Benachrichtigungstexte liegen unter **Benachrichtigungen**, der Wochenbericht unter **Backup**, Versionsinformationen unter **About**. Die Benachrichtigungstexte bieten eine zentrale Platzhalterübersicht, eine Ereignisauswahl und gleich große Vorlage-/Vorschaufelder. Noch nicht konfigurierte Ereignisse zeigen bearbeitbare Beispiele in der Oberflächensprache. Titel und Nachricht der Vorschau entsprechen diesen Vorlagen; **Speichern** übernimmt sie für den Versand. Eigene Texte, Platzhalternamen und eingesetzte Werte werden nicht übersetzt. Unraid zeigt die vollständige Nachricht mit Zeilenumbrüchen; die Weiterleitung an Unraid-Agenten wie Discord erhält dieselben Textzeilen.

### Benutzer

Administratoren verwalten Benutzer, Rollen, Passwörter und Sessions. Deaktivieren Sie einen Benutzer zunächst, bevor Sie ihn dauerhaft löschen.

### Backup und Restore

**Backup** enthält globale Laufzeit-, Docker-, VM- und Reportvorgaben. **Restore** enthält Restore-Test-Standards und erlaubte Zielbereiche für Browse & Restore.

### Import / Export

Exporte sichern Jobs, Profile und Secrets. Das aktuelle verschlüsselte Format erkennt falsche Passwörter und manipulierte Dateien vor dem Schreiben. Die Vorschau zeigt Konflikte vor dem Import. Profil-Secret-Importe werden erst nach einer erfolgreichen Vorschau angewendet.

### Erweitert und Werkseinstellungen

**Erweitert** zeigt Reminder-Diagnose und Per-Repository-Passphrasen. **Werkseinstellungen** löscht Anwendungskonfiguration und Betriebsdaten nach mehrstufiger Bestätigung, jedoch keine externen Borg-Repositorys.

## 14. Systemstatus, Migration und Support

Der Systemstatus prüft Datenpfade, Jobs, Secrets, Profile, Repository-Verweise, Migrationen und Runtime-Recovery. Eine fehlgeschlagene Pflichtmigration versetzt die Anwendung in einen eingeschränkten Wartungsmodus, bis der Fehler behoben ist.

### Supportpaket

Supportpakete sind **bereinigt, aber nicht anonym**. Secrets werden maskiert, dennoch können Pfade, Jobnamen, Hostnamen oder andere Metadaten Rückschlüsse auf das System erlauben. Prüfen Sie das Paket vor der Weitergabe.

## 15. Fehlerbehebung und FAQ

### Kein Repository im Job-Wizard

Prüfen Sie, ob ein passendes Speicherziel und darauf ein verwaltetes Repository existieren. Der Wizard zeigt nur Repositorys des ausgewählten Speicherziels.

### Repository gesperrt

Ein laufender Borg-Prozess oder eine unterbrochene Verbindung kann einen Lock halten. Warten Sie laufende Prozesse ab. Entfernen Sie Locks nur nach sicherer Prüfung gemäß Troubleshooting-Dokumentation.

### Netzwerk- oder SSH-Abbruch

Prüfen Sie WAN-Verbindung, Servererreichbarkeit und SSH-Keepalive. Ein abgebrochener Check muss erneut gestartet werden; ein Teilfortschritt wird von Borg nicht fortgesetzt.

### Backup enthält keine Daten

Prüfen Sie Schreibweise, Groß-/Kleinschreibung, Inhalt und Lesbarkeit der ausgewählten Ordner oder Dateien. Ein vorhandenes, aber leeres Verzeichnis ist technisch gültig und erzeugt ein leeres Archiv.

### Welche Backup-Strategie ist sinnvoll?

Nutzen Sie mehrere Kopien auf unterschiedlichen Medien, mindestens eine Offsite-Kopie, automatische Fehlerüberwachung und regelmäßige Restore-Tests. Passphrasen und Keyfiles müssen zusätzlich außerhalb des Servers gesichert werden.

## Notfall und Konfigurationssicherung

Sichern Sie Repository, Passphrase, Borg-Key, Profile/Secrets und Plugin-Konfiguration getrennt vom Server. Jobexporte enthalten keine Archive und keine zentralen Skriptdefinitionen. Profil-Secret-Import und Jobimport haben getrennte Formate.

[Notfallleitfaden und genaue Exportgrenzen](../../docs/user-manual/de/user-manual.md#16-notfallwiederherstellung). Vorhandene Repositorys importieren, niemals neu initialisieren.

Praktische Erweiterungen: [Pre/Post scripts](../../docs/user-manual/de/user-manual.md#116-pre-post-skripte-einrichten-und-prüfen) und [Grafana](../../docs/user-manual/de/user-manual.md#117-backup-zustand-in-grafana-verfolgen).

## Datenbank-Sicherungen

MariaDB-/MySQL-/PostgreSQL-Profile unter Einstellungen > Datenbank-Sicherungen anlegen und in Wizard-Schritt 2 auswählen. Die mitgelieferten Skripte werden vom Plugin gepflegt; Updates können direkte Änderungen überschreiben. Zugangsdaten in den Plugin-Secrets speichern, Datenbanken laden und per Checkbox auswählen. Unter Skripte sind eigene Skripte, kopierbare Vorlagen und schreibgeschützte Datenbankhelfer getrennt; Quelltexte werden mit Syntaxhervorhebung angezeigt. Wiederherstellung separat testen. Siehe Handbuch Abschnitt 19.

Neue lokale Datenbank-Dumps werden mit gzip komprimiert. Ordnernamen zeigen Profil und Zeitpunkt; die Übersicht zeigt komprimierte und ursprüngliche Größe. Vor Wiederherstellung `.gz`-Dateien prüfen und entpacken; bestehende Dumps bleiben unverändert.
