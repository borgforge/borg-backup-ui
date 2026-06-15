# borg-backup-ui

Web-UI fuer Borg Backup auf Unraid. Das Plugin nutzt nur die Python-Standardbibliothek,
benoetigt auf Unraid aber eine installierte Python-3-Runtime.

## Zweck

`borg-backup-ui` bietet eine zentrale Oberflaeche fuer:

- Backup-Jobs (Wizard + Ausfuehrung)
- Storage / Manueller Borg Check
- History / Berichte
- Browse & Restore
- Restore-Tests
- Einstellungen (inkl. Systemzustand & Migration)

## Laufzeit-Architektur

- UI/Server: `borg_backup_ui.py` (Python stdlib HTTP-Server)
- API-Module: `api/`
- Frontend: `ui/`
- Runtime-Code: `runtime/`
  - `runtime/lib/`
  - `runtime/scripts/`
  - `runtime/config/`
  - `runtime/bin/borg/` (gebuendelte Borg-Binary)

## Laufzeit-Voraussetzung

- Python 3.10 oder neuer.
- Empfohlen und offiziell vorausgesetzt auf Unraid: `Python 3 for Unraid` aus den Community Applications.
- Die Unraid-Control-Page prueft Pfad und Version von `python3` und deaktiviert Start/Restart, wenn die Runtime fehlt oder zu alt ist.

## Zielpfade auf Unraid

- Plugin-Code:
  - `/boot/config/plugins/borg-backup-ui/`
- Betriebsdaten:
  - `/boot/config/borg-backup/`
    - `config/backup.conf`
    - `config/jobs/`
    - `secrets/`
    - `locks/`
    - `scripts/`

Hinweis: Logs/Status/Restore-Status liegen unter dem in den Einstellungen gesetzten `GLOBAL_DATA_DIR`.

## Start / Stop

Das Plugin nutzt:

- `plugin/rc.borg_backup_ui`

Typische Kommandos auf Unraid:

```bash
/etc/rc.d/rc.borg_backup_ui start
/etc/rc.d/rc.borg_backup_ui stop
/etc/rc.d/rc.borg_backup_ui restart
/etc/rc.d/rc.borg_backup_ui status
```

Logfile:

- `/var/log/borg_backup_ui.log`

## First-Install Verhalten

Beim Start werden fehlende Basisverzeichnisse unter `/boot/config/borg-backup` automatisch angelegt:

- `config/`, `config/jobs/`, `secrets/`, `locks/`, `scripts/`

Wenn `config/backup.conf` fehlt, wird aus `runtime/config/backup.conf.example` initialisiert.

## Migration (Bestandsinstallationen)

Die App fuehrt eine idempotente Migration aus:

- Job-Metadaten auf `/boot/config/borg-backup/config/jobs`
- Secrets auf `/boot/config/borg-backup/secrets`
- Anpassung von Passphrase-Pfaden in Job-Metadaten und `backup.conf`

Der letzte Migrationsstatus wird gespeichert in:

- `/boot/config/borg-backup/config/migration-state.json`

## Build / Release

Release bauen:

```bash
./plugin/build.sh
```

Der Build:

- setzt `APP_VERSION` in `borg_backup_ui.py`
- aktualisiert Version + MD5 in `borg-backup-ui.plg`
- erzeugt `releases/borg-backup-ui-<version>.txz`

## Entwicklung

Syntaxcheck (Beispiel):

```bash
python3 -m py_compile borg_backup_ui.py api/*.py runtime/scripts/*.py
```

## Security-Entscheidung: HTTPS (P2-6)

Stand 2026-05-30:

- HTTPS/TLS im eingebauten HTTP-Server (`SSL_CERT`/`SSL_KEY`) ist bewusst **zurueckgestellt**.
- Grund: aktueller Betrieb nur im **lokalen Netz** oder per **VPN**.
- Prioritaet liegt zunaechst auf funktionaler Stabilitaet und Abschluss der verbleibenden Review-Punkte.

Geplanter spaeterer Schritt:

- Umsetzung von P2-6 mit optionalem TLS im Server plus Hinweis im UI bei unverschluesseltem Zugriff.

## Troubleshooting

- **HTTP 500 bei `/api/jobs` oder `/api/status`**:
  - `/var/log/borg_backup_ui.log` pruefen
  - Runtime-Struktur unter `/boot/config/plugins/borg-backup-ui/runtime/` verifizieren
- **Jobs fehlen in der UI**:
  - `config/jobs` unter `/boot/config/borg-backup/config/jobs` pruefen
- **Passphrase-Probleme**:
  - Dateien unter `/boot/config/borg-backup/secrets` pruefen
- **Borg nicht gefunden**:
  - gebuendelte Binary in `runtime/bin/borg/` pruefen
  - rc-restart ausfuehren

## Lizenz

- Projekt: MIT
- BorgBackup: BSD-3-Clause (Drittanbieterlizenz)
