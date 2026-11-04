# borg-backup-ui

Start with the [bilingual user guide](user-manual/README.md): tutorial, tasks,
reference and concepts. During an outage use [German recovery](user-manual/de/user-manual.md#16-notfallwiederherstellung)
or [English recovery](user-manual/en/user-manual.md#16-disaster-recovery).
The technical installation/development reference below is separate from that
user journey. See [documentation maintenance](maintainer/documentation-style.md)
for review and validation rules.


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

- Unraid 6.12.5 through 7.x; Unraid 8 remains outside this plugin line.
- Builds containing #548 use compatible external Python 3.10-3.13 or a bundled,
  isolated fallback. No extra Python download or pip installation at boot.
- The first stable release with this feature is pending Unraid validation and
  release approval. Earlier stable versions still require Python 3 for Unraid.
- See [private runtime ownership and validation](maintainer/python-runtime.md).

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
See [maintainer/release-workflow.md](maintainer/release-workflow.md).

## Development

Syntax check example:

```bash
python3 -m py_compile borg_backup_ui.py api/*.py runtime/scripts/*.py
```

## Manual Release Validation

- [Bilingual user manual](./user-manual/README.md)
- [Manual maintenance tests on Unraid](./maintainer/manual-maintenance-tests.md)
- [Pre-beta regression tests](./maintainer/pre-beta-regression-tests.md)
- [Release workflow](./maintainer/release-workflow.md)

## License

- Project: MIT, see `LICENSE`
- BorgBackup: BSD-3-Clause (third-party license)
- Apprise notification runtime: BSD-2-Clause plus permissive Python dependency
  licenses, see `runtime/licenses/THIRD-PARTY-NOTICES.md`
