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

Drei Karten zeigen **Letzte Backup-Läufe**, **Restore-Abdeckung** und **Aktive Läufe**. Der Standortfilter gilt für diese Kennzahlen, Handlungsbedarf, historische Statistiken und die Standortübersicht. Die erste Karte zählt das letzte gespeicherte Ergebnis pro Job. Restore-Abdeckung zählt gültige Nachweise gegenüber allen Jobs; die Quote innerhalb vorhandener Testpläne steht separat daneben. Fehlende Statusdaten sind kein Erfolg.

**Handlungsbedarf** zeigt vollständige Fehlertexte, Warnungen, übersprungene oder abgebrochene Läufe und überfällige Backups oder Restore-Nachweise. **Job ansehen** öffnet den passenden Job samt Status. Jobs ohne Testplan werden separat mit einem Link zu Restore Tests genannt.

**Entwicklung** wertet gespeicherte Backup-Läufe über 7, 30 oder 90 Kalendertage einschließlich heute in der Server-Zeitzone aus. Die Erfolgsquote ist erfolgreiche Läufe / (erfolgreiche Läufe + Warnungen + Fehler). Übersprungene, abgebrochene und unbekannte Läufe zählen separat. Das ist eine historische Quote und nicht der Anteil der aktuell erfolgreichen Jobs.

**Repository-Speicher** verwendet tatsächliche Größen aus gespeicherten Berichten, je gemeinsam genutztem Repository einmal. Der letzte Messwert wird bis zur nächsten Messung fortgeführt. Fehlende Größen werden nicht durch deduplizierte Archivgrößen ersetzt; unvollständige Messreihen bleiben als Lücken sichtbar. Die Zuordnung folgt der aktuellen Job-Konfiguration, da ältere Berichte keine Repository-ID enthalten. Nach einer Änderung der Repository-Zuordnung sind ältere Werte deshalb nur eingeschränkt vergleichbar. Der letzte Messzeitpunkt steht an der Grafik. Gelöschte Jobs sind nicht Teil dieser Übersicht.

Die **Standorte**-Tabelle fasst Jobanzahl, letzte Erfolge, Jobs mit Hinweisen und Restore-Abdeckung zusammen. **Jobs öffnen** in der jeweiligen Standortzeile zeigt nur die Jobs dieses Standorts, zum Beispiel USB. Einzelne Jobdetails und Aktionen befinden sich auf der Jobs-Seite.

Die **Server-Auslastung** direkt unter der Kennzahlenreihe mit **Letzte Backup-Läufe** bleibt standortübergreifend. CPU und RAM sowie der aufklappbare Verlauf nutzen die gesamte Breite. Laufende geschützte Restore-Tests erscheinen ebenfalls über die volle Breite, auch bei geschlossenem Verlauf. Auf schmalen Bildschirmen stehen die Diagramme untereinander.

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

Alle Repository-Reiter verwenden eine gemeinsame, kompakte Höhe passend zur Übersicht und Fenstergröße. Beim Reiterwechsel und Nachladen bleibt die Karte gleich hoch. Die Archivseiten passen sich diesem Bereich an; längere Inhalte lassen sich innerhalb des gewählten Reiters scrollen. Die Verwaltung zeigt Key-Wiederherstellung, Entfernen und Löschen auf breiten Bildschirmen in durch senkrechte Linien getrennten Spalten, mit den Aktionsbuttons auf gleicher Höhe. Die Repository-ID bleibt einzeilig; bei gekürzter Anzeige ist sie beim Darüberfahren vollständig sichtbar. Auf schmalen Bildschirmen stehen die Verwaltungsbereiche sowie Archivliste und Dateibrowser untereinander. Beim Zurückkehren zu den Repositories werden Job-Verknüpfungen und die Verfügbarkeit der Verwaltungsaktionen automatisch neu geprüft. Nach dem Löschen eines Jobs ist kein zusätzlicher Klick auf „Aktualisieren“ nötig; andere bestehende Sperren bleiben wirksam.

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

- **Übersicht:** Kompakte Größen, Archivanzahl und Dateien im neuesten Archiv. **Statistik aktualisieren** ruft diese Werte von Borg ab; der Zeitstempel daneben zeigt den Abrufzeitpunkt. Wartungsergebnisse behalten ihre eigenen Zeitpunkte. Beim Aufklappen scrollt die Karte bei Bedarf in den sichtbaren Bereich.
- **Archive:** Archivname und Erstellungszeit; neueste Archive stehen zuerst. Lange Namen bleiben einzeilig und sind beim Darüberfahren oder im geöffneten Archiv vollständig lesbar. Die Anzahl der Einträge pro Seite passt sich an Fenster- und Zeilenhöhe an. Seitenanzeige und Schaltflächen zum Blättern stehen direkt oberhalb und unterhalb der linken Archivliste, zum Beispiel „1–5 von 14 geladenen Archiven“. Wählen Sie ein Archiv aus, um dessen Ordner und Dateien direkt in einer schreibgeschützten Ansicht zu durchsuchen. Dies funktioniert auch für importierte Archive ohne Job-Zuordnung. Beim ersten Öffnen kann das Einlesen des Archivindex bei großen oder entfernten Repositorys länger dauern. Wiederherstellung, Download und Dateivorschau bleiben dem separaten **Browse & Restore**-Ablauf vorbehalten.
- **Wartung:** Check, vollständige Datenprüfung, Prune und Compact. Auf breiten Bildschirmen stehen die vier Aktionen in zwei Spalten mit ausgerichteten Startbuttons. Längere aufgeklappte Ausführungsdetails scrollen im jeweiligen Ergebnisbereich; die Buttons behalten ihre Position. Auf schmalen Bildschirmen stehen die Aktionen untereinander.
- **Verwaltung:** Job-Verknüpfungen, Entfernen aus der UI und geschützte endgültige Löschung.

> [!WARNING] Eine endgültige Repository-Löschung entfernt Borg-Daten. Sie ist nur ohne Job-Zuordnung und nach mehrstufiger Bestätigung möglich.

## 6. Backup-Jobs

Ein Job verbindet Quellen mit genau einem vorhandenen Repository. Verschlüsselung gehört zum Repository; Kompression und Aufbewahrung gehören zum Job.

**Nächster Lauf** zeigt den geplanten Termin. Zeitpunkt und Dauer des letzten Laufs bleiben getrennte Angaben.

Die Jobs stehen in einzelnen kompakten Karten mit Abstand. Die Reiter **Einzeljobs/Jobgruppen** sind direkt an den Arbeitsbereich angesetzt. Die Jobanzahl steht bei **Alle Standorte** und bei jedem einzelnen Standort in derselben dezent umrahmten Zählmarke. Darunter liegt die beschriftete Standortleiste in einem gemeinsamen Rahmen, ohne Dropdown oder Pillen; die eigene Terminspalte zeigt Zeitpläne, letzten Restore-Test und Gültigkeit des Nachweises. Der Pfeil am Job öffnet einen gemeinsamen Detailbereich mit **Ablauf** und **Daten & Einstellungen**. Letzterer fasst Speicherdaten, Richtlinie, Archivpräfix, Beschreibung, Borg-/Repository-Checks und Restore-Nachweise zusammen. Beide Ansichten reservieren die Höhe des größeren Inhalts; beim Wechsel springt die Liste nicht. Geöffnete Details und die ausgewählte Ansicht bleiben bei Aktualisierungen erhalten.

Dezente Marker unter dem Jobnamen zeigen konfigurierte **VMs**, **Docker**, **Pre-Skript** und **Post-Skript**. Skriptmarker zeigen aktuelle Zuweisungen, keine früheren Laufergebnisse; der Tooltip nennt den Skriptnamen und beim Post-Skript die Ausführungsbedingung.

Status und Restore-Nachweis verwenden eindeutige Symbole und dezente Hintergrundfarben ohne Umrandung und ohne Fettschrift. Letzter Test und Gültigkeitsende stehen mit getrennten Beschriftungen und bündigen Datumswerten untereinander.

**Starten**, **Log** und **Abbrechen** haben passende Symbole und behalten ihre Position und Beschriftung unter der mittig ausgerichteten Überschrift **Aktionen**. Nicht verfügbare Aktionen bleiben deaktiviert. **Log** öffnet während eines Laufs das Live-Log (mit Live-Punkt), sonst das gespeicherte Log; ohne verfügbares Log ist der Button deaktiviert. Während Docker/VMs wieder starten, bleibt **Abbrechen** deaktiviert, mit der Erklärung als Tooltip statt zusätzlicher Textzeile. Ein angeforderter Abbruch wird im Status angezeigt.

Eingeklappte Karten zeigen Fehler, Warnungen, übersprungene oder abgebrochene Läufe nur als Status. Die vollständige Meldung erscheint genau einmal unter **Ablauf**, gekennzeichnet als **Letztes gespeichertes Ergebnis**. Das gilt auch während eines neuen Laufs. Problemverweise aus dem Dashboard öffnen diesen Bereich direkt. Lange Live-Log-Zeilen lassen sich horizontal scrollen. Fehlende Statusdateien werden nicht als Erfolg gewertet.

### Job-Wizard

1. **Grunddaten:** Job-Name, dauerhafte Job-ID, Archivpräfix, Icon und optionale Docker-/VM-Steuerung.
2. **Quellen & Ziel:** Zu sichernde Ordner oder Dateien, Speichertyp, Speicherziel, Repository und Kompression.
3. **Ausschlüsse:** Pfade, Markerdateien und eine hochgeladene Ausschlussdatei, gemeinsam sichtbar in einem eigenen Schritt.
4. **Docker:** alle laufenden Container, nur ausgewählte Container oder alle außer ausgewählte Container stoppen und danach neu starten; Reihenfolge per Ziehen oder Pfeilen festlegen.
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

Bei einem laufenden Job fordert **Abbrechen** einen kontrollierten Abbruch an. Ein aktiver Borg-Schritt wird unterbrochen. Läuft gerade das Stoppen von Docker-Containern oder VMs, wird dieser Vorgang vollständig beendet und anschließend werden die zuvor laufenden Systeme wieder gestartet. Während des Neustarts ist kein weiterer Abbruch möglich. Schlägt die Wiederherstellung fehl, endet der Lauf als Fehler und der Runtime-Recovery-Hinweis bleibt sichtbar.

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

Die Liste **Reihenfolge** im Docker-Schritt legt fest, in welcher Reihenfolge die Container nach dem Backup von oben nach unten starten; gestoppt werden sie dann einzeln in umgekehrter Reihenfolge. Datenbanken gehören daher nach oben. Eine eigene Reihenfolge ersetzt für die aufgeführten Container die Prioritätsgruppen samt Pausen; gewartet wird weder auf Docker-Health-Checks noch auf die Betriebsbereitschaft einer Anwendung. Ohne Änderung gilt die Standardreihenfolge nach dem Label `backup.start.priority`, und die Container werden gemeinsam gestoppt.

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

Ein abgebrochener Restore-Test ist ein unvollständiger Testversuch und kein fehlgeschlagener Nachweis. In Jobs und im gespeicherten Status wird der **letzte Testversuch als abgebrochen** mit Datum angezeigt; der vorherige abgeschlossene Test behält seinen Status und sein ursprüngliches Gültigkeitsende. Ein Abbruch verlängert keinen Nachweis und verdeckt keinen vorherigen echten Fehler. Ohne verwertbaren vorherigen Bericht bleibt der Nachweis offen. Bereits gespeicherte Abbrüche werden anhand der vorhandenen Berichtshistorie genauso ausgewertet; die Berichte bleiben erhalten.

Unter **Planung & Policy > ⋯ > Plan bearbeiten** legen Administratoren Kalendertermin,
Testlevel und getrennte Nachweisgültigkeit fest. **Jetzt testen** startet manuell.
Die Serverzeitzone gilt; verpasste/übersprungene Termine werden nicht nachgeholt.
Ein Skip erneuert keinen Nachweis. Legacy-Intervalltests bleiben getrennt unter
**Einstellungen > Restore**. Ohne bisherigen Bericht gibt es keinen entsprechenden
Überfälligkeits-Reminder.

Die Planung bündelt die Informationen in vier Spalten, gegliedert nach Standort mit Jobanzahl. Leere Standorte werden ausgeblendet; die Standortangabe unter jedem Job entfällt. **Nachweis & Verlauf** öffnet die Berichte des Jobs. Erfolgreiche Berichte erscheinen als **Wiederherstellungsnachweis** mit Archiv und aufbauendem Prüfumfang L1, L1 + L2 oder L1 + L2 + L3. Die Gültigkeit wird getrennt vom Ergebnis des Versuchs ausgewiesen. Bei einem Abbruch ist ein weiterhin gültiger vorheriger Nachweis direkt erreichbar. Ein Bereich **Technische Nachweise** bündelt Prüfschritte und Logdiagnose; **Prüfdaten anzeigen** öffnet die zugehörigen Werte direkt beim Schritt; vorhandene Berichte bleiben unverändert.

### Testlevel

- **L1:** Archivliste und Metadaten; kein vollständiger Datencheck.
- **L2:** `borg extract --dry-run` liest Daten und prüft sie mit Borg, schreibt aber keine wiederhergestellten Nutzdateien.
- **L3:** Zusätzlich ausgewählte Dateien über `--stdout` lesen und SHA-256 berechnen; kein unabhängiger Soll-Hash-Vergleich.

> [!WARNING] Die Auswahl ist das neueste Archiv des Repositorys, nicht zwingend
> des Jobs. Prüfen Sie den Archivnamen und die Einzelschritte. Metadatenfehler,
> Timeout und Speicherabbruch ergeben einen fehlgeschlagenen Test.

Dateilisten werden speichersparend verarbeitet. Standardmäßig gelten 2048 MiB
RAM-Limit und 1024 MiB Hostreserve; begrenzte Tests laufen nacheinander und
benötigen cgroup v2. Ohne wirksame Begrenzung startet kein Test. Prüfberichte
bleiben pro Lauf erhalten; ihre Details nennen die Logdatei.

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
