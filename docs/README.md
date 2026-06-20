# borg-backup-ui

Web UI for Borg Backup on Unraid. The plugin uses only the Python standard
library, but requires an installed Python 3 runtime on Unraid.

## Purpose

`borg-backup-ui` provides a central interface for:

- backup jobs (wizard and execution)
- storage and manual Borg checks
- history and reports
- browse and restore
- restore tests
- settings, including system status and migration

## Runtime Architecture

- UI/server: `borg_backup_ui.py` (Python standard-library HTTP server)
- API modules: `api/`
- frontend: `ui/`
- runtime code: `runtime/`
  - `runtime/lib/`
  - `runtime/scripts/`
  - `runtime/config/`
  - `runtime/bin/borg/` (bundled Borg binary)

## Runtime Requirement

- Python 3.10 or newer.
- Recommended and officially required on Unraid: `Python 3 for Unraid` from
  Community Applications.
- The Unraid control page checks the `python3` path and version, and disables
  start/restart actions when the runtime is missing or too old.

## Target Paths on Unraid

- Plugin code:
  - `/boot/config/plugins/borg-backup-ui/`
- Runtime data:
  - `/boot/config/borg-backup/`
    - `config/backup.conf`
    - `config/jobs/`
    - `secrets/`
    - `locks/`
    - `scripts/`

Logs, status files, and restore status files are stored below the
`GLOBAL_DATA_DIR` configured in the settings.

## Start and Stop

The plugin uses:

- `plugin/rc.borg_backup_ui`

Typical commands on Unraid:

```bash
/etc/rc.d/rc.borg_backup_ui start
/etc/rc.d/rc.borg_backup_ui stop
/etc/rc.d/rc.borg_backup_ui restart
/etc/rc.d/rc.borg_backup_ui status
```

Log file:

- `/var/log/borg_backup_ui.log`

## First-Install Behavior

On startup, missing base directories below `/boot/config/borg-backup` are
created automatically:

- `config/`, `config/jobs/`, `secrets/`, `locks/`, `scripts/`

If `config/backup.conf` is missing, it is initialized from
`runtime/config/backup.conf.example`.

## Migration for Existing Installations

The app runs an idempotent migration for:

- job metadata to `/boot/config/borg-backup/config/jobs`
- secrets to `/boot/config/borg-backup/secrets`
- passphrase paths in job metadata and `backup.conf`

The latest migration status is stored in:

- `/boot/config/borg-backup/config/migration-state.json`

## Build and Release

Build a release:

```bash
./plugin/build.sh
```

The build:

- sets `APP_VERSION` in `borg_backup_ui.py`
- updates version and MD5 in `borg-backup-ui.plg`
- creates `releases/borg-backup-ui-<version>.txz`

## Development

Syntax check example:

```bash
python3 -m py_compile borg_backup_ui.py api/*.py runtime/scripts/*.py
```

## Manual Release Validation

- [Manual maintenance tests on Unraid](./manual-maintenance-tests.md)
- [Release workflow](./release-workflow.md)
- [Bilingual documentation plan](./bilingual-documentation-plan.md)

## License

- Project: MIT
- BorgBackup: BSD-3-Clause (third-party license)
