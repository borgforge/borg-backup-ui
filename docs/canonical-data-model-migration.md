# Canonical data-model migration

## Purpose

PR #189 changes the ownership of storage, repository and job data:

- `storages.json` owns Local, USB, SMB and SSH/Storagebox targets and profiles.
- `repositories.json` owns repository paths relative to a storage target,
  encryption metadata and secret/keyfile references.
- Job JSON files own source paths, runtime behavior, compression, retention,
  scheduling-related metadata and one `repository_key` reference.
- `backup.conf` owns global application settings.
- `settings.json` is obsolete after the migration succeeds.

## Configuration authority after Issue #143

The runtime has one authoritative owner for each configuration class:

| Configuration class | Authoritative file | Notes |
| --- | --- | --- |
| Storage targets and profiles | `config/storages.json` | Local, USB, SMB and SSH/Storagebox data is not duplicated in `backup.conf`. |
| Borg repositories | `config/repositories.json` | Paths, encryption and secret/keyfile references are resolved from the repository and its storage target. |
| Backup-job behavior | `config/jobs/*.json` | Each job references one repository by `repository_key`. |
| Global application settings | `config/backup.conf` | Contains only keys declared by the installed version's schema. |
| Global settings schema and defaults | `runtime/config/backup.conf.example` | Version-owned and read-only at runtime. It is not copied into persistent configuration. |

`config/settings.json` and the persistent copy
`config/backup.conf.example` have no runtime ownership role. The application
does not maintain storage or repository compatibility values in
`backup.conf`, and it does not read those values as fallbacks.

Every normal settings write renders the complete persistent `backup.conf`
from `runtime/config/backup.conf.example`. Missing schema keys receive the
installed version's default, accepted updates replace their current value and
unknown keys are removed. This makes the installed schema and the effective
configuration directly comparable instead of accumulating obsolete keys.

## Baseline migration

The only registered PR #189 model migration is:

```text
canonical_data_model_v1
```

It supersedes the intermediate migration IDs used by earlier test-channel
builds. Existing state entries for those IDs remain historical audit data but
are hidden from the normal migration list and never control startup again.

Supported source states:

1. Published stable layout with legacy repository/profile fields in jobs and
   profile arrays in `settings.json`.
2. Partially migrated test-channel installations containing some canonical
   objects or earlier migration-state entries.
3. Already canonical installations.
4. Fresh installations without storage, repository or job data.

## Transaction and phase order

The application completes startup migrations before enabling normal API and
runtime services. If a required migration fails, the HTTP server starts only
in restricted maintenance mode so authenticated administrators can inspect the
failure and create a support bundle. Backup, restore, scheduling, reminder,
repository refresh and configuration-changing operations remain disabled.

The baseline acquires the shared inventory lock and performs these internal
transformation phases:

1. Build or complete repository objects from legacy jobs.
2. Normalize repository display metadata and deterministic IDs.
3. Complete encryption metadata from the authoritative legacy job value.
4. Build or complete storage targets and profile details.
5. Validate effective repository paths and secret references.
6. Convert jobs to schema version 2 and remove legacy repository fields.
7. Remove transitional repository fields.
8. Remove `settings.json`.
9. Validate every storage, repository and job relationship.

Local, USB and SMB filesystem targets are validated without silently repairing
malformed input. They must name a dedicated directory below `/mnt`. Collection
roots such as `/mnt`, `/mnt/disks` and `/mnt/remotes`, unsafe `.` or `..`
segments, and empty segments such as `/mnt//backup` are rejected. A single
trailing slash is normalized before the canonical value is stored.

No legacy Borg keyfile migration is registered: keyfile encryption was first
introduced inside PR #189, so the three existing tester installations have no
pre-PR keyfiles to import. Newly created keyfile repositories already write to
the persistent canonical key directory.

The phase implementation remains split into small internal Python modules for
testability, but only the baseline migration is registered and visible.

## Canonical backup.conf migration

Issue #143 adds the ordered startup migration:

```text
canonical_backup_conf_v1
```

It runs after `canonical_data_model_v1` and performs the final configuration
ownership cutover:

1. Read the installed schema from `runtime/config/backup.conf.example`.
2. Parse the existing persistent `config/backup.conf`.
3. Preserve values for keys that still exist in the installed schema.
4. Add missing schema keys with the installed defaults.
5. Remove unknown keys, including obsolete storage and repository values.
6. Atomically write and verify the canonical `backup.conf`.
7. Remove the obsolete persistent `config/backup.conf.example` only after the
   effective configuration is verified as canonical.

Before writing, the migration stores the affected persistent files in its own
protected snapshot below `config/migration-backups/`. Its manifest records
which keys were added, removed or retained without recording their values.
If writing, cleanup or verification fails, the original files are restored and
the migration is reported as failed. The central startup runner then leaves
the application in restricted maintenance mode; later migrations and normal
write operations do not continue.

The migration is idempotent. A repeated detection after successful application
finds neither non-canonical keys nor an obsolete persistent schema copy and
therefore performs no additional write.

## Backup and rollback

Before the first data change, the baseline writes a protected snapshot below:

```text
config/migration-backups/canonical_data_model_v1-<run-id>/
```

The snapshot contains only affected configuration inventories, job metadata,
`backup.conf`, legacy settings and the persistent Borg key directory when it
exists. It does not modify or copy Borg repository contents.

If a transformation or final validation fails, the migration attempts to
restore all affected source files. The application keeps the migration in
`failed` state and does not start normal operation with a partially accepted
model. Later migrations are recorded as `blocked` and are not executed during
that startup.

The snapshot is a data-recovery safeguard, not an automatic plugin rollback.
The application cannot make Unraid install an older plugin package. Operators
repair the reported input with the currently installed version or install a
corrected version, then restart the plugin. Manual restoration from a migration
snapshot is reserved for a documented recovery procedure.

## Migration runner contract

Every registered migration follows the same contract:

- `detect(config)` returns a mapping containing a boolean `required` field.
- `apply(config)` returns a mapping with one of the supported terminal statuses.
- Detection, application and contract errors are attributed to the migration
  ID and phase and are masked before they reach state, audit log or UI.
- The first failed migration stops the ordered migration chain; later entries
  are neither detected nor applied and are reported as blocked by the failed
  migration in the central status.
- A clean restart retries failed and blocked migrations after the underlying
  problem has been corrected.

## Audit files

Current compact state:

```text
config/migration-state.json
```

Append-only events:

```text
config/migrations.log.jsonl
```

The audit records migration/run IDs, start and finish times, source
classification, phase status, affected files, backup directory, created,
updated, preserved and removed object IDs, validation counts and rollback
outcome. It never records passphrases, credentials, tokens or key material.

## Idempotence

After an `applied` or `not_applicable` result, the central registry skips the
baseline on later starts. If an older test build stopped part way through, the
baseline detects the actual files rather than trusting superseded state entries,
completes missing metadata and preserves existing canonical IDs.

## Operator recovery

Open **Settings > Advanced > System health and migration** and inspect:

- migration status and failed phase;
- sanitized error type/message;
- backup directory;
- rollback outcome;
- storage/repository/job assignment diagnostics.

When rollback succeeded, correct the reported legacy input (for example a
missing passphrase file or an unreadable JSON file) and restart the plugin.
When rollback failed, do not edit multiple inventories independently. Preserve
the support bundle and restore the affected files from the recorded migration
backup before another attempt.

The support bundle contains sanitized copies of `storages.json`,
`repositories.json`, `migration-state.json` and `migrations.log.jsonl`.
