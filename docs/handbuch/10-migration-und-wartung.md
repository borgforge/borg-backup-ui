# 10 - Migration und Wartung

## Ziel

Dieses Kapitel erklärt Migrationen, Setup-Checks und Wartungspunkte.

## Migration

Eine Migration ist eine echte Änderung an vorhandenen Dateien, Verzeichnissen oder Einstellungen. Beispiele sind das Verschieben von Laufzeitpfaden oder das Umstellen einer Statusdatei auf ein neues Format.

Migrationen werden in `migration-state.json` nachgehalten. Echte Änderungen können zusätzlich in `migrations.log.jsonl` protokolliert werden.

## Setup-Checks

Setup-Checks beschreiben vorhandene Strukturen. Sie sind keine Migration, wenn nichts geändert werden muss.

Beispiele:

- Jobs-Verzeichnis vorhanden.
- `settings.json` vorhanden.
- `backup.conf` enthält aktuelle Schema-Keys.

## Wartung und Cleanup

Cleanup-Kandidaten sind alte oder nicht mehr benötigte Konfigurationseinträge. Sie werden nicht automatisch entfernt, sondern als Wartungspunkt angezeigt.

Eine Cleanup-Aktion sollte:

- vorher ein Config-Backup erstellen,
- anzeigen, welche Keys betroffen sind,
- bewusst vom Benutzer gestartet werden,
- nachher im Systemstatus nachvollziehbar sein.

## Ergebnis prüfen

Der Migrationsbereich ist gesund, wenn der letzte Lauf erfolgreich war, keine fehlerhaften Migrationen offen sind und Wartungspunkte verständlich beschrieben werden.

## Fehlerbilder

- **Migration offen**: Beschreibung lesen und prüfen, ob eine Aktion angeboten wird.
- **Migration fehlerhaft**: Details öffnen und nicht blind erneut anwenden.
- **Cleanup-Kandidaten vorhanden**: Backup prüfen und Cleanup bewusst starten.
- **Unklare alte Keys in `backup.conf`**: Schema-Abgleich und Cleanup-Details prüfen.
