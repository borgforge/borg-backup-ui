# 03 - Grundeinstellungen und Systemstatus

## Ziel

Dieses Kapitel erklärt die Grundeinstellungen und wie der Systemstatus gelesen wird.

## `GLOBAL_DATA_DIR`

`GLOBAL_DATA_DIR` ist das Hauptverzeichnis für Betriebsdaten der Anwendung. Es sollte auf persistentem Unraid-Speicher liegen, z. B.:

```text
/mnt/user/borg-backup-ui
```

Daraus werden unter anderem Laufzeitpfade für Logs, Status, Cache, Remotes und Restore-Status abgeleitet.

## Grundeinstellungen prüfen

1. **Einstellungen** öffnen.
2. `GLOBAL_DATA_DIR` setzen.
3. Einstellungen speichern.
4. **Systemzustand & Migration** prüfen.
5. Optional E-Mail/SMTP einrichten und Test-E-Mail senden.

## Systemstatus in der Sidebar

- **alles OK**: Keine offenen System-, Job- oder Wartungspunkte.
- **Punkt(e) offen**: Es gibt mindestens einen Punkt, den der Benutzer prüfen sollte.
- **unbekannt**: Der Status konnte nicht geladen werden.

Ein Klick auf den Sidebar-Status öffnet den Bereich **Einstellungen > Systemzustand & Migration**.

## Systemzustand & Migration

- **System**: Prüft Verzeichnisse, Tools, CIFS-Unterstützung und Secret-Dateirechte.
- **Migration**: Zeigt letzten Lauf und echte protokollierte Änderungen.
- **Setup & Konfiguration**: Zeigt Bestand, offene Punkte, Fehler und Cleanup-Kandidaten.
- **Offene Punkte**: Zeigt konkrete Benutzeraktionen.
- **Technische Details**: Zeigt Pfade, Statusdateien und Diagnoseinformationen.

## Ergebnis prüfen

Der Bereich ist plausibel, wenn Systemchecks grün sind, offene Punkte verständlich beschrieben werden und Wartungspunkte nicht als akute Backup-Fehler missverstanden werden.

## Fehlerbilder

- **`GLOBAL_DATA_DIR` leer**: Start-Aktionen bleiben gesperrt.
- **CIFS-Unterstützung fehlt**: SMB-Ziele können nicht zuverlässig verwendet werden.
- **Secret-Dateirechte fehlerhaft**: Secret-Dateien auf restriktive Rechte setzen.
- **Cleanup-Kandidaten vorhanden**: Beschreibung lesen und nur nach Backup bewusst ausführen.
