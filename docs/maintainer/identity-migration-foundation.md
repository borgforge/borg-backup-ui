# Identity-migration foundation and activation

Issues #472 and #479, phases 2 and 9 of #447. This documents the planning,
private recovery-state and activation implementation. The binding model is the
[immutable job identity contract](immutable-job-identity.md). The
[qualification record](identity-migration-qualification.md) separates automated
source evidence from the packaged Unraid test and stable-release approval.

## Current boundary

The read-only planner remains independent of execution. Startup registers
`immutable_job_id_activation` before other migrations. Required, blocked or
interrupted conversion keeps the application in maintenance without automatically
preparing a plan, snapshotting data or applying changes. An authenticated
administrator prepares a verified snapshot, pauses to check an independent
backup, acknowledges that exact snapshot and separately starts conversion.

The #479 coordinator owns writer exclusion, actual crontab capture, protected
export, approval and resumable execution. Only validated normal startup or
successful final verification enables normal services. Canonical job-options
validators remain authoritative alongside identity/reference validation.
Calling a planner or verifier alone never authorizes writers.

## APIs and responsibilities

| Module / entry point | Responsibility and limitation |
| --- | --- |
| `api/migrations/immutable_job_id_v1.py`: `build_plan` | Read owned stores and propose a plan. `journal_plan` must be the original validated plan, not an arbitrary repair map. |
| `detect` | Read-only summary with boolean `required`, classification, execution status and safe reasons. Blocked inventory never reports `required=False`. |
| `verify_target` | Re-read actual target stores and verify canonical cutover integrity; never authorize services by itself. |
| `api/migrations/identity_records.py`: `project_records`, `verify_records` | Pure projection and independent actual-reference validation; preserve history and block conflicting active ownership. |
| `api/migrations/identity_storage.py`: `seal_plan`, `persist_plan`, `load_plan` | Validate, hash, durably publish and reload the same allocation without replacing conflicting state. |
| `create_snapshot`, `verify_snapshot`, `verify_inputs` | Copy and verify exact originals, hashes and immediate directory inventories. No production replacement. |
| `verify_preconditions` | Default-deny check for bound confirmation, verified snapshot, unchanged inputs, exact quiescence and external-input recheck. |
| `append_journal`, `read_journal` | Private sequenced, hash-linked JSONL with fixed statuses, phases, safe reasons and known action IDs. |
| `api/migration_barrier.py` | Persistent admission block, shared worker leases and exclusive conversion ownership. Readiness is published only under exclusive ownership. |
| `api/identity_migration_api.py`: `IdentityMigrationAssistant` | Explicit preparation, protected export, snapshot-bound acknowledgement and separate apply; read-only startup/status detection. |
| `api/migrations/identity_apply.py`: `apply_plan` | Original sealed plan, exact old/new fingerprints, per-action journal, directory receipts, managed cron replacement and actual-target verification. |
| `api/migrations/immutable_job_id_activation.py` | First registry entry; required conversion returns pending/blocked instead of executing at startup. |
| `api/identity_startup_watch.py` | Retry read-only readiness after mounts or old workers recover. Resume ordinary startup only if no conversion or explicit continuation is required. |

These are internal APIs. Users operate the protected
`/api/migration/identity/...` assistant through the UI. The request handler
retains administrator/session and same-origin requirements.

## Read-only inventory and plan

The scanner derives configured roots and reads the owned stores in contract
C5, including both weekly-snapshot locations and known legacy job locations.
It captures immediate directory membership and individual fingerprints, so
new or disappeared inputs cannot hide behind checking only surviving objects.

Reads reject symlinks, unsafe paths, non-regular inputs, malformed JSON,
duplicate members, unsupported schemas and inconsistent ownership. Known Unraid
mounts must be available. Scanning does not invoke lazy migration, cleanup,
auto-write or repair helpers. Logs, unrelated nested files, recycle bins,
runtime/vendor contents and Borg repository/cache data are not recursively
inventoried or converted.

A supported plan contains the full UUIDv4 map, canonical jobs, exact aliases,
bindings, preserved unassigned history, fingerprints, directory inventories and
actions. Each replacement describes exact destination bytes and each retirement
identifies an individual superseded source. The coordinator includes canonical
`backup.conf` changes and obsolete configuration auxiliaries in the same sealed
plan and snapshot before replacement.

Proposed UUIDs exist only in memory until explicit preparation persists the
plan. Its content digest identifies the complete proposal; it is neither a
signature nor approval. Valid empty/canonical installations are not applicable.
Unsupported or uncertain states block without proposed production changes.

Stopped recovery targets, notification retries/reminders, independent restore
IDs and historical descriptors are preserved. Deleted-job UUIDs remain evidence
without becoming active bindings. Weekly values retain provenance and explicit
conflicts. Restore index/detail pairs must agree; missing peers and contradictory
records are not silently repaired.

## Private recovery state and export

Library callers supply `state_dir`. The assistant suggests
`<data_root>/.identity-migration-v1`, validates the location and provides no
automatic fallback. It must be outside owned inputs and inventory roots on an
available persistent filesystem supporting private POSIX permissions and hard
links. Directories belong to the process with mode `0700`; files use `0600`.

The FAT `/boot` filesystem is unsuitable for private state. Originals on `/boot`
can still be read and snapshotted, but installations with a suggested `/boot`
state path must select suitable persistent storage. Missing mounts, unsupported
permissions or publication semantics block instead of weakening protection.
The location must remain available throughout conversion and recovery.

A nonsensitive selector at `<data_root>/.identity-migration-location.json` is
persisted before the UUID map. Browser reconnection does not relocate a plan.
Private state can contain:

```text
state_dir/
  assistant.json
  plan.json
  journal.jsonl
  apply-roots.json
  apply-cron.json
  directory-<path-hash>.json
  snapshot/
    metadata.json
    manifest.json
    files/
      <source-path-hash>.bin
      external-managed_cron.bin
```

Execution receipts appear only when their stages begin. Private staging, flushes
and exclusive final-name publication prevent overwriting conflicts. Metadata
records the original UTC creation time before copying. The manifest binds the
snapshot to its plan, complete ID map and actions. Verification checks exact
members, sizes, hashes and binding; existence alone is insufficient.

Treat all private state as secret-bearing. Original configuration, notification
content and proposed settings can contain credentials. Permissions are not
encryption. State must not appear in ordinary support bundles, public issues,
application logs or public staging directories.

The authenticated administrator download streams a verified tar with the sealed
plan and complete snapshot metadata, manifest and originals. Execution journals
and mutable assistant state are excluded. Exact member hashes and declared
archive length are checked; a changed source during export aborts the stream.
Download grants no approval and never starts conversion. Public diagnostics
contain selected metadata and fixed reasons, not private payloads.

## Confirmation and writer exclusion

The assistant implements [contract C4.1](immutable-job-identity.md#c41-approved-user-initiated-migration-assistant-479):
read-only detection, explicit preparation, verified snapshot, mandatory backup
check pause, bound acknowledgement and separate apply. Closing the browser or
restarting preserves the pause and original map. Acknowledgement records the
user's independent-backup check; it cannot prove an external copy was made.

Execution requires the applicable plan, verified snapshot, approval bound to
both plan ID and snapshot digest, unchanged originals and cron, and a quiescence
callback returning exactly `True`. Missing or failed checks block. The
coordinator holds exclusive ownership during preparation, apply and verification;
scanner process evidence alone is not admission control.

`<data_root>/.migration-gate/blocked.json` blocks new work across service
restarts. An installation-specific runtime ready proof under
`/run/borg-backup-ui/migration-gate/` is absent by default, revoked at startup
and bound to the gate protocol. Tests can redirect the runtime root with
`BORG_UI_MIGRATION_GATE_ROOT`; that does not bypass checks.

Write-capable HTTP requests, backup/restore/test runners, cleanup, repository
refresh, checks, SSH deployment, retained-log capture, notifications and factory
reset use shared leases. Async owners retain admission through final result
persistence. Maintenance waits for existing work without terminating it;
scheduler sleeps hold no lease. Exclusive conversion checks known pre-upgrade
processes and blocks on unreadable evidence. Maintenance starts no widgets,
schedulers or warm-up writers, and health/setup/support use read-only diagnostics.

Missing data/runtime mounts keep startup blocked. A read-only observer can resume
ordinary startup after storage or old workers recover only when no conversion
is needed. Pending snapshots and interrupted plans still require explicit
actions. Failed apply requires a restart before explicit continuation. An
already normal state stops the observer without starting services twice.

## Cron, execution and recovery

The coordinator captures actual crontab bytes. Empty capture is explicit;
missing capture never means empty cron. Captured text is snapshotted and
rechecked before preparation, approval and execution. Known managed entries
must use guarded HTTP routes; unknown direct legacy commands block. Execution
replaces only the managed backup section, preserving unrelated cron bytes.
Repository, notification and restore-test service schedules retain their
separate identity. The planner itself executes neither crontab nor Borg.

Apply requires exact original/target fingerprints and journaled write intent.
An unexplained existing target, even with expected bytes, is not completion
authority. Destination directories have durable ownership receipts. A retired
source requires its authorized expected replacement and journal evidence.
Membership, permissions, unrelated inputs and referenced secret-file type and
existence are revalidated. The actual graph is verified before cron installation
and before recording the commit. The engine is crash-consistent and resumable;
it does not claim one atomic transaction across filesystems.

Explicit continuation reloads the original plan, UUID map, snapshot and actions.
It never snapshots partially converted data as a new starting point. Completed
actions are not replayed. Unknown staging contents, corrupted blobs, conflicting
links, truncated journals and unexplained edits block without silent deletion
or repair. Apply failures retain evidence and keep normal writers disabled.

There is no automatic rollback, snapshot restore or plugin downgrade. Manual
repair uses the installed or a corrected plugin and must be documented. See
[release limitations](release-workflow.md#7-rollback-limitation) and the
[user migration guide](../user-manual/en/migration-guide.md).

## Verification boundary

Coverage includes supported legacy fixtures, actual snapshot/destination writes,
publication-boundary resume, writer races, protected HTTP export and a migrated
job's real Borg backup and restore. Unknown states still block and require an
explicit supported fixture before becoming eligible.

Source tests do not establish every filesystem or real installation. Final
preflight, test-channel package verification and maintainer Unraid tests remain
required by the [qualification record](identity-migration-qualification.md).
Stable promotion requires separate explicit approval.
