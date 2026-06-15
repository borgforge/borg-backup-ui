# 09 - Import, Export, Backups und Support-Paket

## Ziel

Dieses Kapitel erklärt Datentransfer, Config-Backups, Rollback und Support-Pakete.

## Import / Export

Der Bereich **Einstellungen > Import / Export** unterstützt verschlüsselte Exporte und Importe für:

- Jobs und Passphrases.
- Profile und Secrets.
- Ausgewählte Import-Vorschauen.

Importe sollten immer zuerst als Vorschau geprüft werden.

## Import-Modi

- `skip`: Bestehende Einträge behalten.
- `overwrite`: Bestehende Einträge ersetzen.
- `rename`: Konflikte durch neuen Namen vermeiden, soweit im jeweiligen Import unterstützt.

## Config-Backups & Rollback

Beim Speichern von Einstellungen und vor Wartungsaktionen können Backups der `backup.conf` entstehen. Über **Config-Backups & Rollback** können Backups geprüft, verglichen und wiederhergestellt werden.

Vor einem Rollback wird die aktuelle `backup.conf` zusätzlich gesichert.

## Support-Paket

Das Support-Paket sammelt Diagnoseinformationen und maskiert sensible Daten. Es ist der bevorzugte Weg, um Fehler nachvollziehbar weiterzugeben.

Trotz Maskierung gilt: Support-Pakete nur gezielt weitergeben und bei Bedarf vorher prüfen.

## Ergebnis prüfen

Ein Export ist erfolgreich, wenn eine Datei erstellt wurde und die Vorschau beim Import die erwarteten Jobs, Profile oder Secrets zeigt.

## Fehlerbilder

- **Import-Passwort falsch**: Export-Passwort prüfen.
- **Profil fehlt nach Job-Import**: Profile separat importieren oder manuell anlegen.
- **Passphrase fehlt**: Jobs+Passphrases-Export statt reinem Job-Export verwenden.
- **Rollback unklar**: Diff zwischen aktiver `backup.conf` und Backup anzeigen.
