# 11 - Troubleshooting

## Ziel

Dieses Kapitel sammelt typische Fehlerbilder und die ersten sinnvollen Prüfschritte.

## Systemstatus nicht OK

1. Sidebar-Indikator anklicken.
2. **Offene Punkte** lesen.
3. Zwischen Fehler, offenem Punkt und Cleanup-Kandidat unterscheiden.
4. Technische Details nur bei Bedarf öffnen.

## Job startet nicht

- `GLOBAL_DATA_DIR` gesetzt?
- Job aktiviert?
- Quellpfade vorhanden?
- Passphrase-Datei vorhanden?
- Zielprofil vorhanden und vollständig?

## Repository nicht erreichbar

- **Repositories** öffnen.
- Repository auswählen und Informationen aktualisieren.
- Bei SMB vorher mounten.
- Bei SSH Profiltest und Repository-URI prüfen.

## Repository ist durch `lock.exclusive` gesperrt

Borg schützt ein Repository mit einem exklusiven Lock vor gleichzeitigen,
konkurrierenden Zugriffen. Repository-Wartungen warten bis zu 30 Sekunden auf
einen vorübergehend belegten Lock. Bleibt die Meldung
`Failed to create/acquire the lock .../lock.exclusive` bestehen, läuft entweder
noch ein Borg-Vorgang oder ein abgebrochener Vorgang hat einen verwaisten Lock
hinterlassen.

1. Prüfen, dass in Borg Backup UI weder Backup, Restore, Restore-Test noch
   Repository-Wartung für dieses Repository laufen.
2. Sicherstellen, dass auch kein anderes System auf dasselbe Repository
   zugreift.
3. Auf Unraid ausschließlich nach einem Borg-Programmprozess suchen:

   ```bash
   pgrep -ax borg
   ```

   Der dauerhaft laufende Borg-Backup-UI-Pythonprozess und eine inaktive
   SSH-Multiplex-Verbindung sind keine Borg-Repository-Operationen.
4. Läuft ein Borg-Prozess, den Vorgang beenden lassen und die Wartung danach
   erneut starten.
5. Läuft auf keinem beteiligten System ein Borg-Prozess und bleibt die Sperre
   bestehen, kann ein Administrator den verwaisten Lock einmalig aufheben.

   Lokales Repository:

   ```bash
   borg break-lock '/mnt/<storage>/<repository>'
   ```

   Repository über SSH:

   ```bash
   borg break-lock 'ssh://<user>@<host>:<port>/<repository-path>'
   ```

6. Den Rückgabecode mit `echo $?` prüfen. `0` bedeutet, dass der Befehl
   erfolgreich abgeschlossen wurde.
7. Anschließend in der UI zuerst **Info aktualisieren** und danach einen
   schnellen **Check** starten.

> **Warnung:** `borg break-lock` nur ausführen, wenn sicher kein Borg-Prozess
> auf irgendeinem System auf das Repository zugreift. Die Datei
> `lock.exclusive` niemals manuell mit `rm` löschen.

## SMB-Probleme

- CIFS-Unterstützung im Systemstatus prüfen.
- SMB-Profil speichern und testen.
- Mount-Status des SMB-Profils prüfen.
- Credentials und Share-Namen kontrollieren.

## SSH-Probleme

- Host, Port und User prüfen.
- SSH-Key-Pfad und Rechte prüfen.
- Basispfad prüfen.
- Bei Storagebox auf Slash nach Port achten: `:23/./backup/...`.

## Restore-Probleme

- Repository-Informationen aktualisieren und Wartungsstatus prüfen.
- Passphrase prüfen.
- Erlaubtes Restore-Ziel verwenden.
- Freien Speicher am Ziel prüfen.

## Supportfall vorbereiten

1. Support-Paket erstellen.
2. Keine Secrets manuell in Text kopieren.
3. Version, Jobname, Zeitpunkt und sichtbare Fehlermeldung notieren.
4. Letzten betroffenen Lauf in History prüfen.
