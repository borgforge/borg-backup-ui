# 08 - Browse, Restore und Restore Tests

## Ziel

Dieses Kapitel beschreibt, wie Archive durchsucht, Daten wiederhergestellt und Restore-Tests genutzt werden.

## Browse & Restore

1. **Browse & Restore** öffnen.
2. Job oder Repository auswählen.
3. Archiv auswählen.
4. Dateien oder Verzeichnisse durchsuchen.
5. Restore-Ziel wählen.
6. Restore starten und Ergebnis prüfen.

Restore-Ziele sind auf sichere Pfade unter `/mnt/user/...` begrenzt.

## Zielverhalten bei Verzeichnissen

Wenn der Quellordnername bereits dem letzten Zielordner entspricht, wird direkt in diesen Zielordner restored. Sonst wird ein Unterordner mit Quellordnernamen angelegt.

## Restore Tests

Restore Tests prüfen regelmäßig, ob eine Wiederherstellung technisch funktioniert. Sie sind kein vollständiger fachlicher Datenvergleich, aber ein wichtiger Betriebsnachweis.

Typische Einstellungen:

- Job
- Zielort
- Intervall
- Testlevel
- Scheduler-Status

## Ergebnis prüfen

Ein Restore ist erfolgreich, wenn die erwarteten Dateien am Ziel liegen, Dateigrößen plausibel sind und der Restore-Test-Status grün ist.

## Fehlerbilder

- **Archiv nicht sichtbar**: Repository-Zugriff und Passphrase prüfen.
- **Restore-Ziel abgelehnt**: Zielpfad muss unter erlaubtem Root liegen.
- **Restore scheitert trotz Backup OK**: Borg-Zugriff, Passphrase und freien Speicher prüfen.
- **Restore Test überfällig**: Zeitplan oder letzten Testlauf prüfen.
