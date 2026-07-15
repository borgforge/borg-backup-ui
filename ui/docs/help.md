# Borg Backup UI - Kurzhilfe

Diese Hilfe ist als schnelle Orientierung gedacht. Sie ersetzt kein vollständiges Handbuch, sondern fasst die wichtigsten Bedienwege, Prüfungen und typischen Fehlerbilder zusammen.

## Wofür ist die Anwendung?

Borg Backup UI verwaltet Borg-Backup-Jobs auf Unraid. Die Anwendung hilft beim Einrichten von Jobs, Speicherzielen, Zeitplänen, Restore-Tests und beim Prüfen des Systemzustands.

## Schnellstart

### 1) Systemstatus prüfen

- In der Sidebar zeigt **Systemstatus**, ob alles OK ist oder ob Punkte offen sind.
- Bei Warnung auf **Systemstatus** klicken und in **Einstellungen > Systemzustand & Migration** die offenen Punkte ansehen.
- Wichtig: Der Bereich trennt Systemprüfungen, Job-Prüfungen, letzte Migration und Konfigurations-/Wartungspunkte.

### 2) Speicherziel und Repository vorbereiten

- Das Speicherziel zuerst unter **Einstellungen** bei den lokalen, USB-, SMB- oder SSH-Profilen anlegen und prüfen.
- In **Repositories** auf **Repository hinzufügen** klicken.
- Das vorhandene Speicherziel auswählen.
- Anschließend ein neues Borg-Repository erstellen oder ein vorhandenes Repository importieren.

Tipp: Beim Import wird das Repository mit `borg info` geprüft, aber nicht verändert oder initialisiert.

### 3) Job anlegen oder bearbeiten

- In **Jobs** auf **Neuer Job** klicken oder einen bestehenden Job bearbeiten.
- Jobname und Typ wählen.
- Quellpfade eintragen.
- Speichertyp, Speicherziel und ein dazugehöriges vorhandenes Repository wählen.
- Kompression und Aufbewahrung prüfen. Verschlüsselung und Passphrase gehören zum Repository und werden nicht im Job geändert.
- Zeitplan aktivieren, falls der Job automatisch laufen soll.

### 4) Vorschau und Prüfungen beachten

- Der Wizard zeigt das ausgewählte verwaltete Repository und dessen Pfad.
- Die schnelle Job-Prüfung ist eine lokale Plausibilitätsprüfung. Sie ersetzt keinen vollständigen Borg-Repo-Test.

### 5) Ersten Lauf manuell starten

- Nach dem Speichern den Job einmal manuell starten.
- Log-Ausgabe beobachten.
- Danach **History** und **Berichte** prüfen.

Empfehlung: Einen neuen Job erst nach einem erfolgreichen manuellen Lauf dauerhaft per Zeitplan verwenden.

### 6) Benachrichtigungen optional einrichten

- SMTP wird unter **Einstellungen > Allgemein** gepflegt.
- Nach dem Speichern eine Test-E-Mail senden.
- ntfy wird ebenfalls unter **Einstellungen > Allgemein** gepflegt.
- Für ntfy werden Server-URL, Topic und optional Authentifizierung benötigt. Passwort und Token werden als Secret-Dateien gespeichert.
- Nach dem Eintragen eine ntfy-Testnachricht senden.
- E-Mail, Unraid-Systemmeldungen und ntfy besitzen eigene Ereignis-Auswahlen. Reminder werden zentral begrenzt, damit überfällige Prüfungen nicht bei jedem Poll erneut melden.
- Für geplante Backups kann eine Überfälligkeits-Toleranz in Stunden gesetzt werden. Eine Meldung erfolgt, wenn ein erwarteter Lauf nicht innerhalb dieser Toleranz erfolgreich abgeschlossen wurde.
- Der Wochenbericht wird unter **Einstellungen > Backup** aktiviert und terminiert.
- Der Wochenbericht nutzt entweder seinen eigenen Empfänger oder, wenn leer, den globalen E-Mail-Empfänger.

## Systemstatus verstehen

### Sidebar

- **alles OK**: Die letzte Systemprüfung war erfolgreich.
- **Punkt(e) offen**: Mindestens eine System-, Job- oder Wartungsprüfung braucht Aufmerksamkeit.
- **unbekannt**: Status konnte noch nicht geladen werden oder der Backend-Check ist fehlgeschlagen.

### Einstellungen > Systemzustand & Migration

- **System** prüft Basisverzeichnisse, Tools, CIFS-Unterstützung und Secret-Dateirechte.
- **Migration** zeigt den letzten Lauf und ob echte Änderungen protokolliert wurden.
- **Setup & Konfiguration** zeigt Bestand, offene Punkte, fehlerhafte Punkte und Cleanup-Kandidaten.
- **Offene Punkte** zeigt konkrete Aktionen, wenn etwas vom Benutzer erledigt werden kann.
- **Technische Details** enthalten Pfade, Registry-Details und Diagnoseinformationen.

## Jobs und Speicherziele

### Local und USB

- Repository-Pfade sind normale Dateisystempfade.
- Bei USB-Zielen muss das Ziel verfügbar sein, bevor ein Lauf erfolgreich sein kann.

### SMB

- SMB-Jobs nutzen ein gespeichertes SMB-Profil.
- Der Job-Check prüft Profilreferenz und Pfad-Plausibilität.
- Der eigentliche Repository-Zugriff ist erst sinnvoll prüfbar, wenn das SMB-Ziel gemountet ist.
- In **Storage > SMB** zuerst mounten, dann Repo-Test ausführen.

### SSH, Storagebox und Synology

- SSH-Ziele nutzen ein SSH-Profil mit Host, Port, User, Basispfad und Key.
- Der Profiltest prüft SSH, Borg, Basispfad und Schreibzugriff.
- Der konkrete Repository-Test erfolgt über **Storage** oder im Wizard über die Repo-Vorschau.
- Ein korrekter relativer Basispfad sieht z. B. wie `./backup` aus und wird in der URI als `/./backup/...` verwendet.

## Repositories

- **Repositories** ist der Ort zum Einrichten, Importieren und Warten von Borg-Repositories.
- Links werden Repositorys nach dem konkreten Speicherziel gruppiert. Die Suche filtert die Repository-Liste, ohne den ausgewählten Speicherort zu verändern.
- **Übersicht** zeigt Borg-Kennzahlen, den letzten bekannten Wartungszustand und die verständlichen Repository-Daten.
- Borg-Kennzahlen werden im Hintergrund mindestens alle 24 Stunden neu geladen und zwischengespeichert. Nach einem Verbindungsfehler versucht die Anwendung die Aktualisierung nach einer Stunde erneut.
- Der Kopfbereich verwendet den konfigurierten Anzeigenamen des Repositorys. Repository-Verzeichnis, absoluter Repository-Pfad und Pfad im Speicherziel werden getrennt bezeichnet.
- **Archive** lädt die aktuelle Archivliste direkt aus dem ausgewählten Repository.
- **Wartung** bietet Check, Datenprüfung, Prune und Compact. Der Status und das Ergebnis bleiben nach Abschluss sichtbar; ein technisches Live-Log ist dafür nicht erforderlich.
- **Verwaltung** zeigt Job-Verknüpfungen. Dort kann ein ungenutztes Repository nur aus der UI entfernt oder nach erneuter Identitätsprüfung endgültig gelöscht werden.
- Prune verwendet die Aufbewahrungsrichtlinie des verknüpften Jobs und ist ohne Job-Zuordnung deaktiviert.
- Nach Prune werden die entfernten Archive zusammengefasst. Compact zeigt den freigegebenen Speicherplatz, wenn Borg diesen Wert ausgibt.
- Bei Fehlern können maskierte technische Details im betreffenden Statusfeld geöffnet werden.
- Datenprüfung, Prune und Compact müssen ausdrücklich bestätigt werden.
- Eine endgültige Löschung ist gesperrt, solange Jobs oder laufende Aktionen das Repository verwenden, und verlangt Anzeigename sowie `DELETE` als doppelte Bestätigung.

## Restore und Restore Tests

- **Browse & Restore** dient zum Durchsuchen von Archiven und Wiederherstellen einzelner Daten.
- Restore-Ziele sind auf sichere Zielpfade unter `/mnt/user/...` begrenzt.
- **Restore Tests** prüfen regelmäßig, ob Wiederherstellungen technisch funktionieren.
- Restore-Tests sind keine vollständige Datenkontrolle, aber ein wichtiger Nachweis, dass Repository, Archiv und Restore-Pfad zusammen funktionieren.

## Benachrichtigungen, E-Mail und Berichte

- SMTP-Konfiguration und Testmail liegen unter **Einstellungen > Allgemein**.
- Das SMTP-Passwort wird nach dem Speichern nicht im Klartext angezeigt. Ein gesetztes Passwort wird nur als Status angezeigt.
- E-Mail-Benachrichtigungen folgen den ausgewählten Benachrichtigungsereignissen; reguläre Zusammenfassungen laufen über den Wochenbericht.
- ntfy-Konfiguration und Testnachricht liegen ebenfalls unter **Einstellungen > Allgemein**.
- ntfy kann Backup-Erfolg, Backup-Fehler/Warnungen und übersprungene Backups als Push-Benachrichtigung senden.
- Überfällige geplante Backups und Restore-Tests können als Reminder gemeldet werden, wenn das jeweilige Ereignis im Kanal aktiviert ist.
- ntfy-Passwort und Access Token werden nach dem Speichern nicht im Klartext angezeigt.
- Der Wochenbericht wird unter **Einstellungen > Backup** aktiviert. Er verwendet die gespeicherte SMTP-Konfiguration.
- Testmails, Wochenberichte und technische Ausgaben werden immer auf Englisch versendet.

## Import, Export und Backups

- **Einstellungen > Import / Export** bietet verschlüsselte Exporte für Jobs, Passphrases, Profile und Secrets.
- Neue verschlüsselte Exporte sind versioniert und gegen unbemerkte Änderungen geschützt. Ein falsches Passwort sowie beschädigte oder manipulierte Dateien werden vor dem Import abgewiesen.
- Ältere AES-CBC-Exporte können weiterhin importiert werden, werden aber als Legacy-Format ohne Integritätsschutz gekennzeichnet. Erstellen Sie nach einem solchen Import einen neuen Export.
- Vor Importen wird eine Vorschau angezeigt.
- Import-Modi wie `skip`, `overwrite` oder `rename` steuern den Umgang mit bestehenden Daten.
- Jobs-Importe können passende USB-/SMB-Profile aus dem Paket mitbringen.
- Profil-Secret-Importe können fehlende SMB-/SSH-Profile aus dem Paket anlegen, wenn der Settings-Import nicht auf `ignore` steht.
- Config-Backups dienen als Rückfallpunkt vor Wartungs- oder Cleanup-Aktionen.
- Support-Pakete sollten keine Secrets im Klartext enthalten.

## Migration und Wartung

- Migrationen sind echte Änderungen an bestehenden Dateien, Verzeichnissen oder Einstellungen.
- Setup-Checks beschreiben vorhandene Strukturen und sind nicht automatisch eine Migration.
- Cleanup-Kandidaten sind Hinweise auf alte oder nicht mehr benötigte Konfigurationseinträge.
- Cleanup-Aktionen erstellen vorher ein Backup und müssen bewusst gestartet werden.
- **Einstellungen > Werkseinstellungen** ist der letzte Wartungseintrag und setzt die Anwendung nach mehrfacher Sicherheitsbestätigung auf den Erstinstallationszustand zurück. Borg-Repositories werden nicht gelöscht.

## Häufige Probleme

### Systemstatus zeigt Warnung

- Auf **Systemstatus** in der Sidebar klicken.
- In **Offene Punkte** die konkrete Meldung lesen.
- Wenn nur Cleanup-Kandidaten angezeigt werden, ist das meist Wartung und kein akuter Backup-Fehler.

### Kein Repository im Job-Wizard auswählbar

- Unter **Repositories** zuerst ein Repository erstellen oder importieren.
- Prüfen, ob Speichertyp und Speicherziel im Job-Wizard richtig gewählt wurden.
- Es werden nur Repositorys angezeigt, die zum exakten Speicherziel gehören.

### SMB-Repo-Test funktioniert nicht

- SMB-Profil in **Einstellungen > SMB-Profile** prüfen.
- In **Storage > SMB** Mount-Status prüfen.
- Falls nicht gemountet: mounten, dann erneut testen.

### SSH-URI sieht falsch aus

- SSH-Profil prüfen: Host, Port, User und Basispfad.
- Basispfad für Storagebox-Ziele typischerweise `./backup`.
- Die resultierende URI enthält dann nach dem Port einen Slash, z. B. `:23/./backup/...`.

### Passphrase oder Secret fehlt

- Job bearbeiten und Passphrase-Datei prüfen.
- Import/Export nur mit verschlüsselten Secret-Paketen für Passphrases und Profil-Secrets verwenden.
- Secret-Dateien sollten restriktive Dateirechte haben.

### SMTP-, ntfy- oder Wochenberichtswerte fehlen nach Reload

- Die Werte zuerst im passenden Bereich speichern: SMTP und ntfy unter **Allgemein**, Wochenbericht unter **Backup**.
- Nach dem Speichern wird der Zustand aus `backup.conf` neu geladen.
- SMTP-Passwort, ntfy-Passwort und ntfy-Token bleiben absichtlich leer sichtbar, wenn sie bereits gespeichert sind.
