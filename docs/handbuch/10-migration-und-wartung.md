# 10 - Migration und Wartung

## Ziel

Dieses Kapitel erklärt Migrationen, Setup-Checks und Wartungspunkte.

## Migration

Eine Migration ist eine echte Änderung an vorhandenen Dateien, Verzeichnissen oder Einstellungen. Beispiele sind das Verschieben von Laufzeitpfaden oder das Umstellen einer Statusdatei auf ein neues Format.

Migrationen werden in `migration-state.json` nachgehalten. Jeder wirksame Lauf
schreibt zusätzlich strukturierte Ereignisse in `migrations.log.jsonl`. Bei der
Umstellung auf das kanonische Storage-/Repository-Modell nennt der Audit unter
anderem Lauf-ID, Ausgangszustand, Phasen, Backup-Verzeichnis, betroffene
Objekte, Validierung und ein mögliches Rollback. Secrets werden nicht geloggt.

Die Beta-Version gilt als neuer initialer unterstützter Stand. Direkte
Upgrades von alten internen Testversionen vor dem Beta-Stand sind nicht als
öffentlicher Upgrade-Pfad vorgesehen. Ab der Beta werden neue Migrationen als
unterstützte Upgrade-Schritte versioniert und langfristiger behandelt.

Die Anzeige unter **Einstellungen > Systemzustand & Migration** unterscheidet:

- **Ausgeführt**: Zeitpunkt, zu dem die Migration die Daten tatsächlich
  geändert und den Status `angewendet` erreicht hat. Dieser Zeitpunkt bleibt
  bei späteren Pluginstarts unverändert.
- **Zuletzt geprüft**: Zeitpunkt des letzten Starts, bei dem der zentrale
  Migrations-Runner den gespeicherten Status kontrolliert hat. Das ist keine
  erneute Ausführung der Migration.
- **Audit-Details**: Lesbare Zusammenfassung der protokollierten Aktionen,
  geänderten Schlüssel, betroffenen Dateien und des Sicherungsverzeichnisses,
  soweit die jeweilige Migration diese Angaben geliefert hat.

Bei älteren Migrationsständen wird der Ausführungszeitpunkt nur übernommen,
wenn ein erfolgreicher Eintrag im strukturierten Audit-Log ihn belegt. Fehlt
dieser Nachweis, kennzeichnet die Oberfläche den historischen Zeitpunkt als
nicht separat protokolliert, statt das Datum des aktuellen Pluginstarts
anzuzeigen.

Die Oberfläche zeigt fehlerhafte, blockierte oder offene Migrationen immer an.
Erfolgreiche oder nicht mehr notwendige Migrationshistorie wird standardmäßig
auf die letzten fünf Einträge begrenzt; vollständige Details bleiben im
Migrationslog für Diagnosezwecke erhalten.

## Setup-Checks

Setup-Checks beschreiben vorhandene Strukturen. Sie sind keine Migration, wenn nichts geändert werden muss.

Beispiele:

- Jobs-Verzeichnis vorhanden.
- `storages.json` als kanonisches Speicherziel-Inventar vorhanden.
- `backup.conf` enthält aktuelle Schema-Keys.

## Wartung und Cleanup

Cleanup-Kandidaten sind alte oder nicht mehr benötigte Konfigurationseinträge. Sie werden nicht automatisch entfernt, sondern als Wartungspunkt angezeigt.

Eine Cleanup-Aktion sollte:

- vorher ein Config-Backup erstellen,
- anzeigen, welche Keys betroffen sind,
- bewusst vom Benutzer gestartet werden,
- nachher im Systemstatus nachvollziehbar sein.

## Werkseinstellungen

**Einstellungen > Werkseinstellungen** ist der letzte Eintrag in der Gruppe
**Wartung**. Der Vorgang entfernt die Anwendungskonfiguration sowie die
konfigurierten Betriebs-, Log-, Status- und Verlaufsdaten und startet danach
die Admin-Erstkonfiguration.

Die Plugin-Installation und externe Borg-Repositories bleiben erhalten. Ein
Reset wird blockiert, wenn ein verwaltetes Repository innerhalb eines zu
löschenden Verzeichnisses liegt oder gerade ein Backup, Restore, Restore-Test
oder eine Repository-Wartung ausgeführt wird.

Vor dem Reset `/boot/config/borg-backup` sichern. Die Freigabe erfordert alle
Risikobestätigungen, den Servernamen, das aktuelle Admin-Passwort und den
Bestätigungstext `FACTORY RESET`.

## Ergebnis prüfen

Der Migrationsbereich ist gesund, wenn der letzte Lauf erfolgreich war, keine fehlerhaften Migrationen offen sind und Wartungspunkte verständlich beschrieben werden. Ein neuer Wert bei **Zuletzt geprüft** ist nach einem Pluginstart normal; **Ausgeführt** darf sich dabei nicht ändern.

## Fehlerbilder

- **Migration offen**: Beschreibung lesen und prüfen, ob eine Aktion angeboten wird.
- **Migration fehlerhaft**: Details öffnen und nicht blind erneut anwenden.
- **Cleanup-Kandidaten vorhanden**: Backup prüfen und Cleanup bewusst starten.
- **Unklare alte Keys in `backup.conf`**: Schema-Abgleich und Cleanup-Details prüfen.
