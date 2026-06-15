# 07 - Backup-Lauf, History und Berichte

## Ziel

Dieses Kapitel beschreibt den manuellen Backup-Lauf und die Auswertung über History und Berichte.

## Manuellen Lauf starten

1. **Jobs** öffnen.
2. Job auswählen.
3. Start-Aktion ausführen.
4. Laufende Ausgabe beobachten.
5. Bei Fehlern Details und Log prüfen.

Ein neuer oder geänderter Job sollte immer einmal manuell laufen, bevor der Zeitplan als produktiv betrachtet wird.

## Während des Laufs beachten

- Quellpfade müssen erreichbar sein.
- Ziel muss verfügbar sein.
- Passphrase muss passen.
- Bei SMB müssen Mount-Optionen zum Profil passen.
- Bei SSH müssen Profil und Repository-Pfad stimmen.

## History

**History** zeigt vergangene Läufe mit Status, Zeit, Job und Detailinformationen. Sie ist der erste Ort, um nach einem Lauf zu prüfen, ob der Job erfolgreich war.

## Berichte

**Berichte** fassen Laufdaten über mehrere Jobs und Zeitpunkte zusammen. Sie helfen bei Trends, Laufzeiten, Größenentwicklung und wiederkehrenden Fehlern.

## Ergebnis prüfen

Ein Lauf gilt als erfolgreich, wenn der Exit-Status OK ist, keine relevanten Warnungen im Log stehen und das Repository danach testbar bleibt.

## Fehlerbilder

- **Job startet nicht**: `GLOBAL_DATA_DIR` und Systemstatus prüfen.
- **Lauf bricht ab**: History-Details und Log lesen.
- **Ziel nicht erreichbar**: Storage-Profil und Repository-Test prüfen.
- **Ungewöhnlich lange Laufzeit**: Datenmenge, Netzwerk und Borg-Check/Prune-Aktivität prüfen.
