# 02 - Installation und Update auf Unraid

## Ziel

Dieses Kapitel beschreibt die Installation, Updates und die wichtigsten Prüfungen nach einem Update.

## Voraussetzungen

- Unraid-System mit gestartetem Array.
- Python 3 for Unraid mit Python 3.10 oder neuer.
- Netzwerkzugriff auf die Plugin-URL.
- Speicherort für Betriebsdaten, empfohlen unter `/mnt/user/...`.

## Installation

1. Plugin über die Unraid-Plugin-URL installieren.
2. Nach der Installation die Borg Backup UI öffnen.
3. In **Einstellungen** zuerst das Hauptverzeichnis `GLOBAL_DATA_DIR` setzen.
4. Danach **Systemzustand & Migration** prüfen.

Wenn Python fehlt oder zu alt ist, zeigt die Unraid-Control-Page einen Hinweis mit erkanntem Pfad und Version. Python 3 for Unraid kann über die Community Applications installiert oder aktualisiert werden.

## Update

1. Plugin aktualisieren.
2. Borg Backup UI neu öffnen.
3. Sidebar-Indikator **Systemstatus** prüfen.
4. **Einstellungen > Systemzustand & Migration** öffnen.
5. Offene Punkte prüfen und nur bewusst ausführen.
6. Einen wichtigen Job manuell testen, bevor alle Zeitpläne unbeaufsichtigt laufen.

## Was nach einem Update wichtig ist

- Version in Sidebar oder About-Bereich prüfen.
- Letzten Migrationslauf prüfen.
- Offene Wartungs- oder Cleanup-Punkte lesen.
- Storage-Profile nicht blind ändern, wenn bestehende Jobs funktionieren.
- Restore-Test-Status prüfen.

## Ergebnis prüfen

Ein Update gilt als erfolgreich, wenn die UI startet, der Systemstatus plausibel ist, Jobs geladen werden und mindestens ein manuell gestarteter Testlauf oder Repo-Test erfolgreich ist.

## Fehlerbilder

- **UI startet nicht**: Plugin-Service und Python-Runtime auf der Unraid-Control-Page prüfen.
- **Systemstatus unbekannt**: Seite neu laden, Backend-Status prüfen.
- **Jobs fehlen**: `GLOBAL_DATA_DIR`, Jobs-Verzeichnis und Import/Export-Status prüfen.
- **Repository nicht erreichbar**: Storage-Profil und Storage-Seite prüfen.
