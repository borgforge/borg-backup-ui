# Canonical job control plane

Issue #474, phase 4/9 of #447. Integration-only, not installable or released.
The binding contract is [immutable-job-identity.md](immutable-job-identity.md).

## Configuration and API boundary

Discovery reads only validated `<job_id>.json` metadata. It never moves legacy
files, infers identity from a descriptor, silently skips malformed jobs, or
returns stale cached metadata after an external edit. Repository and storage
context is derived from the current assignment. Job responses expose `job_id`,
`name`, `archive_prefix`, `archive_prefixes`, and repository/storage descriptors
separately. The job list and maintenance selectors use these fields.

| Operation | Target request |
| --- | --- |
| Enable/disable | `PUT /api/jobs/enabled`, `job_id`, boolean `enabled` |
| Schedule save | `PUT /api/schedules`, `job_id`, `cron`, boolean `enabled` |
| Schedule deletion | `DELETE /api/schedules`, `job_id` |
| Run preparation | `POST /api/jobs/run`, `job_id`, optional `scheduled` |
| Cancellation identity | `POST /api/jobs/cancel`, `job_id`, `run_id` |
| Job configuration deletion | `DELETE /api/jobs`, `job_id` |
| Retention source selection | `POST /api/storage/check/run`, `repository_key`, optional `job_id` |

The singleton restore-test service is not a backup job. Its schedule requests
use `service: "restore_test"` without `job_id` or `job_key`. Its existing entry
in `schedules.json` remains `restore_test`; per-job restore-test policy and
runtime cutover belong to #477.

The temporary HTTP adapter in `api/job_actions.py` is limited to run, cancel,
enable, configuration delete and schedule save/delete. It resolves `job_key`
only through an exact, uniquely owned `legacy_job_keys` alias in the validated
inventory. Unknown/case-changed/ambiguous aliases and conflicting simultaneous
`job_id`/`job_key` fields are rejected. Successful boundary use logs a deprecated
request with endpoint and resolved UUID, without logging the supplied alias.
Wizard and maintenance requests have no adapter. Remove this bounded adapter
at the final #479 API cutover; it is not a persistent dual-writer promise.

## Transactions and integrity

Metadata saves validate the complete job, repository and schedule inventories
under the shared cross-process inventory lock before replacing any file.
Renames and prefix/repository changes update the existing UUID file. Schedule
bytes and the original alias list remain unchanged, so `config_local` cannot
be orphaned by saving a new `pfsense_local` identity. An already orphaned legacy
schedule blocks the edit, including when disabled; only the explicit migration
can resolve old references using authoritative evidence.

Repository references are `job_ids` and `source_job_ids`. API display labels
come from the current job inventory, not retained repository names or Type IDs.
Reassignment changes the affected ID in both old/new lists under one lock and
rolls back bytes on an ordinary write failure. Other repository settings and
root extensions remain intact. Standalone repository writers validate the
proposed assignments and never write `used_by` or `source_job_keys`.

The reconciliation endpoint is read-only: missing repositories/storage targets,
dangling IDs, duplicate references, legacy fields and conflicting assignments
are errors, never reasons to rebuild or discard user data. Repository deletion
continues to reject a linked job, including a disabled one.

Schedule reads are strict and never prune unknown entries. Save/delete verify
the complete map before installing managed cron. Unknown fields in existing
entries and the restore-test service entry are retained. Cron submits `job_id`;
disabling a job suspends its cron line while preserving its schedule settings.
Enabling it restores its scheduled line. Configuration deletion removes exactly
one metadata file, its reverse references and its schedule together.

Ordinary file/cron failures restore original file bytes and reinstall the old
managed cron lines. Rollback failure is reported as
`job_transaction_recovery_required`, never success. Individual replacements are
durable; a multi-file update is **not crash-atomic**. #479 must integrate the
startup/writer gate and recovery path for crashes or incomplete rollback before
any candidate is published. No automatic migration or downgrade is introduced.

## Explicit remaining boundaries

- #475 implements the UUID runner, immutable run snapshots, log/status/recovery
  correlation and shared retention over the prefix union. The RAM activity
  capture from #463 remains intact. See [canonical-job-runtime.md](canonical-job-runtime.md).
- #476 converts status/dashboard/history consumers to configured UUIDs and
  historical payload snapshots; see [canonical-status-views.md](canonical-status-views.md).
  #477 still converts restore selection, execution and result writers.
- #478 handles historical artifact/secret deletion, transfer and recovery.
  Configuration-only deletion preserves existing logs/status/secrets/scripts.
  Requests to delete artifacts or passphrases stop before any write in this
  phase. Existing tests of the old runtime/restore/transfer/artifact contracts
  are not evidence of a working integrated installation yet.
- #479 owns the explicitly approved migration assistant, complete end-to-end
  verification, final preflight and first test-channel candidate.

User manuals remain unchanged until the complete migration can be tested. The
pending release fragment is intended for the final integrated candidate only.
