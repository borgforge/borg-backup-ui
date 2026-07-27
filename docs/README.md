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

## Build and test a package

Run focused tests during development. Commit and push the final source, then
run the complete preflight exactly once:

```bash
./plugin/mr-preflight.sh
```

Publish the attested commit to the test channel:

```bash
./plugin/deploy-test.sh <version>
```

The direct `plugin/build.sh` entry point is intentionally restricted to an
exported staging tree. After explicit test approval, stable promotion copies
the exact tested package into a separate release PR without rebuilding it.
See [release-workflow.md](release-workflow.md).

## Development

Syntax check example:

```bash
python3 -m py_compile borg_backup_ui.py api/*.py runtime/scripts/*.py
```

## Manual Release Validation

- [Bilingual user manual](./user-manual/README.md)
- [Manual maintenance tests on Unraid](./manual-maintenance-tests.md)
- [Release workflow](./release-workflow.md)
- [Bilingual documentation plan](./bilingual-documentation-plan.md)

## License

- Project: MIT, see `LICENSE`
- BorgBackup: BSD-3-Clause (third-party license)
- Apprise notification runtime: BSD-2-Clause plus permissive Python dependency
  licenses, see `runtime/licenses/THIRD-PARTY-NOTICES.md`
