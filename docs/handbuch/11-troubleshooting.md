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

- Storage-Seite öffnen.
- Passenden Repo-Test ausführen.
- Bei SMB vorher mounten.
- Bei SSH Profiltest und Repository-URI prüfen.

## SMB-Probleme

- CIFS-Unterstützung im Systemstatus prüfen.
- SMB-Profil speichern und testen.
- Mount-Status in Storage prüfen.
- Credentials und Share-Namen kontrollieren.

## SSH-Probleme

- Host, Port und User prüfen.
- SSH-Key-Pfad und Rechte prüfen.
- Basispfad prüfen.
- Bei Storagebox auf Slash nach Port achten: `:23/./backup/...`.

## Restore-Probleme

- Repository-Test ausführen.
- Passphrase prüfen.
- Erlaubtes Restore-Ziel verwenden.
- Freien Speicher am Ziel prüfen.

## Supportfall vorbereiten

1. Support-Paket erstellen.
2. Keine Secrets manuell in Text kopieren.
3. Version, Jobname, Zeitpunkt und sichtbare Fehlermeldung notieren.
4. Letzten betroffenen Lauf in History prüfen.
