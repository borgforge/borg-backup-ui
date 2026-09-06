# Dauerhafte Job-Identitäten: Migrationsanleitung

Dieses Update gibt jedem Backup-Job eine dauerhafte Identität. Beim Umbenennen bleiben Zeitpläne, Berichte, Restore-Ergebnisse und Historie miteinander verbunden. Die Migration stellt die eigenen Installationsdaten des Plugins um. Bestehende Borg-Repositories und Archivnamen bleiben erhalten.

## Vor dem Test des Updates

Der erste Kandidat ist eine Test-Channel-Version und benötigt freiwillige Tests auf unterschiedlichen unterstützten Installationen, bevor eine stabile Version freigegeben wird. Nutze eine Testinstallation oder ein System mit einer geprüften Wiederherstellungskopie. Sichere zusätzlich zu den Plugin-Daten auch die Unraid-Flash-Konfiguration separat. Die Migrationssicherung enthält die exakt betroffenen Dateien; sie ersetzt keine vollständige Unraid-Flash-Sicherung und keine Sicherung deiner Borg-Repositories.

Lass laufende Backups, Wiederherstellungen, Tests und Benachrichtigungen sicher enden. Stelle sicher, dass die vom Plugin verwendeten Speicher und der geplante Sicherungsort eingehängt sind. Der Sicherungsort benötigt dauerhaften Speicher mit privaten Dateirechten. Das Dateisystem des Unraid-USB-Bootdatenträgers ist für die vertrauliche Migrationssicherung ungeeignet.

## Den Migrationsassistenten verwenden

1. Öffne **Einstellungen > Systemzustand & Migration**. Ist eine Migration erforderlich oder kann der vorhandene Datenbestand nicht sicher eingeordnet werden, bleibt das Plugin im Wartungsmodus. Installation, Start und Öffnen dieser Seite erlauben noch keine Umstellung. Unraid sowie seine Array- und Pool-Steuerung bleiben verfügbar.
2. Wähle einen privaten Sicherungsort und **Migration vorbereiten**. Die Anwendung prüft die Voraussetzungen, speichert den ursprünglichen Migrationsplan und erstellt eine exakte Sicherung betroffener Daten und verwalteter Cron-Einstellungen. Vollständigkeit, Größen und Prüfsummen werden automatisch geprüft. Wartegründe bleiben sichtbar; ein laufender Job wird nicht für die Migration abgebrochen.
3. Prüfe bei **Sicherung geprüft** den angezeigten Ort, Erstellungszeitpunkt, die Größe und das Prüfergebnis. Wähle **Geschützte Sicherung herunterladen**, speichere eine separate Kopie auf unabhängigem Speicher und prüfe, dass sie dort verfügbar ist. Die Sicherung kann Zugangsdaten und andere vertrauliche Informationen enthalten. Lade sie nicht in ein öffentliches Issue oder einen Forumsbeitrag hoch.
4. Wähle die Bestätigung, dass du eine separate Kopie gespeichert und geprüft hast, und danach **Gespeicherte Kopie bestätigen**. Damit wird deine Bestätigung festgehalten; eine Kopie auf einem anderen Gerät lässt sich dadurch nicht nachweisen. Dieser Schritt startet die Umstellung nicht.
5. Wähle separat **Migration jetzt ausführen**. Der Server prüft vor der Umstellung erneut den exakten Plan und die Sicherung, verfügbare Speicher, unveränderte Quell- und Cron-Daten sowie die Sperre aller Schreibzugriffe. Der Fortschritt bleibt sichtbar. Normale Funktionen bleiben pausiert, bis Abschlussprüfung und Startfreigabe erfolgreich sind.

Geänderte Quelldaten oder eine geänderte Sicherung machen die bisherige Freigabe ungültig. Der Assistent kann den Plan nicht stillschweigend unter einer früheren Bestätigung ersetzen. Bewahre die vorhandenen Wiederherstellungsdaten auf und beachte die angezeigten Diagnosehinweise.

### Sicherungsort und Diagnosehinweise

Das Pfadfeld ist eine freie Eingabe. Verwende für die erste Vorbereitung ein eigenes neues Unterverzeichnis unter einem bereits vorhandenen Verzeichnis auf dauerhaftem Speicher. Die Anwendung legt das neue Unterverzeichnis mit privaten Dateirechten an. Die Eingabe allein bestätigt weder einen eingehängten Speicher noch passende Dateirechte; die Vorbereitung prüft beides serverseitig. Bereits vorhandene Daten werden nicht durch eine andere Ordnerwahl repariert.

Nach **Migration vorbereiten** zeigt der Assistent die laufende Anfrage und anschließend den Vorbereitungsstand oder einen verständlichen Fehler. Der letzte fehlgeschlagene Versuch bleibt auch bei automatischen Statusprüfungen sichtbar, bis du die Vorbereitung erneut startest; ohne gespeicherten Migrationsort gilt dies bis zum Plugin-Neustart. Gleiche Diagnosecodes werden mit der Anzahl ihrer Meldungen zusammengefasst. Diese Anzahl entspricht nicht zwingend der Zahl betroffener Jobs.

`invalid_identity_descriptor` bedeutet, dass gespeicherte Job- oder Laufdaten unvollständige oder ungültig formatierte Angaben zur bisherigen Zuordnung enthalten. Der Code betrifft nicht den Sicherungsordner. Gültige ältere Restore-Test-Berichte mit `type` und `location` werden bei der Migration berücksichtigt. Bleibt der Code sichtbar, bewahre die Daten auf und melde ihn zusammen mit dem angezeigten Schritt; ändere die Zuordnungsfelder nicht von Hand.

## Browser schließen oder Plugin neu starten

Du kannst den Browser schließen und später den gespeicherten Schritt ansehen. Eine bereits freigegebene Aktion kann auf dem Server weiterlaufen; beim erneuten Öffnen wird sie nicht erneut gestartet. Ein Neustart erhält die ursprünglich vergebenen Identitäten, den Plan, die Sicherung und das Journal und gibt die Umstellung nicht automatisch frei.

Nach einer Unterbrechung ist nur eine geprüfte, ausdrückliche Fortsetzung zulässig. **Migration jetzt fortsetzen** ist nur verfügbar, wenn der Server den ursprünglichen Versuch als sicher fortsetzbar einstuft. Unbekannte oder widersprüchliche Teilzustände bleiben blockiert. Behebe nach einem Migrationsfehler die gemeldete Ursache und starte das Plugin erfolgreich neu, bevor der Normalbetrieb wieder freigegeben werden kann.

## Wiederherstellung und Problemmeldung

Bewahre das ursprüngliche Migrationsverzeichnis und die separat heruntergeladene Kopie auf. Das normale Aufräumen alter Sicherungen darf diesen Wiederherstellungsstand nicht löschen. Benenne keine Dateien um, bearbeite keine Job-Identitäten von Hand, lösche nicht das Journal und erstelle zur Reparatur keine zweite Identitätszuordnung.

Notiere den angezeigten Schritt und die Diagnosecodes. Ein geschütztes Support-Bundle enthält begrenzte, maskierte Diagnosedaten; der Migrationssnapshot ist ein separates, vertrauliches Wiederherstellungsartefakt. Teile dem Maintainer die Diagnosecodes und den betroffenen Ablauf mit und gib an, ob ein Backup, eine Wiederherstellung oder Benachrichtigung aktiv war. Freiwillige Tests sollten nach der Migration auch Jobs, Zeitpläne, Historien und Restore-Ergebnisse prüfen.

Der Snapshot dient der Datenwiederherstellung und ist kein automatisches Plugin-Downgrade. Unraid bestimmt das installierte Plugin-Paket. Reparaturen erfolgen mit der installierten oder einer korrigierten Version. Ist eine manuelle Datenwiederherstellung nötig, halte das Plugin gestoppt, bewahre den unterbrochenen Stand auf und arbeite nach einem ausdrücklich geprüften Wiederherstellungsplan. Dokumentiere Snapshot-Identität, jede exakte Quelle und jedes Ziel, Prüfsummen, Dateirechte und den Zeitpunkt jeder Aktion. Prüfe die wiederhergestellten Daten und den verwalteten Cron-Stand, bevor ein erfolgreicher Start normale Arbeiten freigibt. Kopiere nicht einen ganzen Datenbereich über eine teilweise umgestellte Installation und stelle zusammengehörige Datensätze nicht ohne Konsistenzprüfung nur teilweise wieder her.
