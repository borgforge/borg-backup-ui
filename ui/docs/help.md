# Borg Backup UI - Kurzhilfe

Diese Hilfe ist als schnelle Orientierung gedacht. Sie ersetzt kein vollständiges Handbuch, sondern fasst die wichtigsten Bedienwege, Prüfungen und typischen Fehlerbilder zusammen.

## Wofür ist die Anwendung?

Borg Backup UI verwaltet Borg-Backup-Jobs auf Unraid. Die Anwendung hilft beim Einrichten von Jobs, Speicherzielen, Zeitplänen, Restore-Tests und beim Prüfen des Systemzustands.

## Schnellstart

### 1) Systemstatus prüfen

- In der Sidebar zeigt **Systemstatus**, ob alles OK ist oder ob Punkte offen sind.
- Bei Warnung auf **Systemstatus** klicken und in **Einstellungen > Systemzustand & Migration** die offenen Punkte ansehen.
- Wichtig: Der Bereich trennt Systemprüfungen, Job-Prüfungen, letzte Migration und Konfigurations-/Wartungspunkte.

### 2) Profile vorbereiten

- **Local/USB**: Zielpfad bzw. USB-Profil prüfen.
- **SMB**: In **Einstellungen > SMB-Profile** Profil anlegen, speichern und testen.
- **SSH/Storagebox/Synology**: In **Einstellungen > SSH-Profile** Host, Port, User, Basispfad und SSH-Key pflegen und den Profiltest ausführen.

Tipp: Repository-URIs für SSH-Ziele sollten aus dem Profil entstehen. Nicht manuell raten oder den Pfad frei zusammenbauen.

### 3) Job anlegen oder bearbeiten

- In **Jobs** auf **Neuer Job** klicken oder einen bestehenden Job bearbeiten.
- Jobname, Typ und Ziel-Location wählen.
- Quellpfade eintragen.
- Repository, Verschlüsselung, Passphrase, Kompression und Aufbewahrung prüfen.
- Zeitplan aktivieren, falls der Job automatisch laufen soll.

### 4) Vorschau und Prüfungen beachten

- Der Wizard zeigt eine Vorschau des Repository-Pfads.
- Bei SSH-/Storagebox-Jobs wird angezeigt, ob das Repository gefunden wurde oder eine Anlage bestätigt werden muss.
- Die schnelle Job-Prüfung ist eine lokale Plausibilitätsprüfung. Sie ersetzt keinen vollständigen Borg-Repo-Test.

### 5) Ersten Lauf manuell starten

- Nach dem Speichern den Job einmal manuell starten.
- Log-Ausgabe beobachten.
- Danach **History** und **Berichte** prüfen.

Empfehlung: Einen neuen Job erst nach einem erfolgreichen manuellen Lauf dauerhaft per Zeitplan verwenden.

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

## Storage

- **Storage** ist der richtige Ort für Repository-Tests.
- Repo-Tests prüfen den Zugriff auf das Borg-Repository.
- SMB-Repos müssen vorher gemountet sein.
- SSH-Profiltests bestätigen das Profil, prüfen aber nicht automatisch jedes einzelne Job-Repository.

## Restore und Restore Tests

- **Browse & Restore** dient zum Durchsuchen von Archiven und Wiederherstellen einzelner Daten.
- Restore-Ziele sind auf sichere Zielpfade unter `/mnt/user/...` begrenzt.
- **Restore Tests** prüfen regelmäßig, ob Wiederherstellungen technisch funktionieren.
- Restore-Tests sind keine vollständige Datenkontrolle, aber ein wichtiger Nachweis, dass Repository, Archiv und Restore-Pfad zusammen funktionieren.

## Import, Export und Backups

- **Einstellungen > Import / Export** bietet verschlüsselte Exporte für Jobs, Passphrases, Profile und Secrets.
- Vor Importen wird eine Vorschau angezeigt.
- Import-Modi wie `skip`, `overwrite` oder `rename` steuern den Umgang mit bestehenden Daten.
- Config-Backups dienen als Rückfallpunkt vor Wartungs- oder Cleanup-Aktionen.
- Support-Pakete sollten keine Secrets im Klartext enthalten.

## Migration und Wartung

- Migrationen sind echte Änderungen an bestehenden Dateien, Verzeichnissen oder Einstellungen.
- Setup-Checks beschreiben vorhandene Strukturen und sind nicht automatisch eine Migration.
- Cleanup-Kandidaten sind Hinweise auf alte oder nicht mehr benötigte Konfigurationseinträge.
- Cleanup-Aktionen erstellen vorher ein Backup und müssen bewusst gestartet werden.

## Häufige Probleme

### Systemstatus zeigt Warnung

- Auf **Systemstatus** in der Sidebar klicken.
- In **Offene Punkte** die konkrete Meldung lesen.
- Wenn nur Cleanup-Kandidaten angezeigt werden, ist das meist Wartung und kein akuter Backup-Fehler.

### Repository-Anlage muss bestätigt werden

- Der Wizard konnte das Repository nicht sicher als vorhanden erkennen.
- In **Storage** den passenden Repo-Test ausführen.
- Bei SMB zuerst mounten.
- Bei SSH Profiltest und Repository-Pfad prüfen.

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
