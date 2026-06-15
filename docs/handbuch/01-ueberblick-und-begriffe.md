# 01 - Überblick und Begriffe

## Ziel

Dieses Kapitel erklärt, wofür Borg Backup UI gedacht ist und welche Begriffe in der Anwendung verwendet werden.

## Was die Anwendung macht

Borg Backup UI ist eine Weboberfläche für Borg-Backups auf Unraid. Sie verwaltet Backup-Jobs, Speicherprofile, Zeitpläne, Statusinformationen, Restore-Tests und unterstützende Wartungsfunktionen.

Die Anwendung ersetzt nicht das Verständnis für die eigenen Daten. Sie hilft aber dabei, wiederholbare Backups und Restore-Prüfungen über eine einheitliche Oberfläche zu bedienen.

## Wichtige Begriffe

- **Job**: Eine Backup-Aufgabe mit Quellen, Ziel, Repository, Passphrase, Retention und optionalem Zeitplan.
- **Repository**: Das Borg-Ziel, in dem Archive gespeichert werden.
- **Archiv**: Ein einzelner Backup-Stand innerhalb eines Repositorys.
- **Location**: Zieltyp eines Jobs, z. B. `local`, `usb`, `smb` oder `storagebox`.
- **Profil**: Wiederverwendbare Zielkonfiguration, z. B. USB-, SMB- oder SSH-Profil.
- **Passphrase**: Geheimnis zum Öffnen eines verschlüsselten Borg-Repositorys.
- **Retention**: Aufbewahrungsregel, die steuert, wie viele alte Archive behalten werden.
- **Restore Test**: Geplanter oder manueller Test, ob ein Restore technisch funktioniert.
- **Systemstatus**: Zusammenfassung aus System-, Job- und Wartungsprüfungen.
- **Migration**: Einmalige Änderung an vorhandenen Dateien, Verzeichnissen oder Konfigurationen nach einem Update.

## Welche Daten verwaltet werden

- `backup.conf` für zentrale Konfigurationswerte.
- `settings.json` für Profile und UI-nahe Einstellungen.
- Job-Metadaten im Jobs-Verzeichnis.
- Secret-Dateien für Passphrases, Profil-Credentials und SSH-Schlüssel.
- Status-, History-, Report- und Restore-Test-Daten.
- Migration-State und Migrations-Log für nachvollziehbare Wartung.

## Ergebnis prüfen

Nach diesem Kapitel sollte klar sein, dass Jobs die Backup-Logik enthalten, Profile Zielzugänge beschreiben und Repository-Tests nicht dasselbe sind wie reine Profiltests.

## Hinweise

Secrets gehören nicht in Screenshots, Tickets oder Supporttexte. Für Diagnosezwecke sollte das Support-Paket verwendet werden, weil es sensible Werte maskiert.
