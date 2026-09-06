# Immutable identity migration qualification

Issue #479 integrates the nine phases of #447. The binding behavior is in the
[identity contract](immutable-job-identity.md); implementation boundaries are in
the [foundation and activation notes](identity-migration-foundation.md).

## Current classification

The dependency inventory is `integrated_pending_final_qualification`. Source
integration and focused automated evidence do not authorize a stable release.
The final pushed commit must pass its complete source preflight before the
first test-channel package is built and verified. The maintainer then tests
that exact package on Unraid. Stable promotion requires explicit approval and
a separate release PR under the [release workflow](release-workflow.md).

The final PR/test-channel report records the source commit, package version,
preflight result, package verification and manual results. This document does
not replace those commit-specific attestations.

## Dependency ownership

[`identity-dependencies.json`](identity-dependencies.json) retains the phase-1
baseline and ownership groups and includes the #479 coordinator, apply engine,
admission gate, startup observer, async owners, UI and packaged entry points.
Its 85 entries include both readers and writers.

The contract test verifies indexed paths/anchors and scans Python, JavaScript,
shell, PHP and Unraid page sources for the declared legacy identity tokens.
The integration scan found 36 matching source modules and no unowned matches.
This inventory check alone does not prove writer exclusion: token-free HTTP,
cron, subprocess, scheduler, widget and support paths are covered by the
explicit ownership audit and tests below.

Legacy historical fields remain preserved evidence. The unused `archive_prefix`
and type-derived storage-URI helpers have no production call sites and do not
resolve canonical jobs. Active mutable references, request aliases, type/name
filenames and runtime ownership have moved to UUIDs.

## Automated coverage

| Boundary | Evidence |
| --- | --- |
| Contract and dependency ownership | `test_immutable_job_identity_contract.py`, `test_identity_planner.py`, `test_identity_records.py`: golden fixtures, malformed/ambiguous inputs, exact aliases, historical unassigned evidence and source inventory. |
| Settings and lifecycle | `test_identity_lifecycle.py`, `test_canonical_job_wizard.py`, `test_canonical_job_control.py`: UUID preservation, rename/repository changes, deletion confirmation and archive-prefix behavior. |
| Snapshot and approval | `test_identity_storage.py`, `test_identity_migration_assistant.py`, `test_identity_migration_review.py`: exact originals, private storage, missing mounts, changed inputs, snapshot binding, separate acknowledgement/apply and protected metadata. |
| Conversion and resume | `test_identity_apply.py`: actual canonical destinations for the phase-1 matrix, actual graph verification, file/cron/directory publication interruptions, idempotency, original UUID reuse, disk-full failure and unexplained edits. |
| Writer exclusion | `test_migration_barrier.py`: real subprocess leases, transferred async ownership, admission races, default-deny restart proof, durable block, bounded old-process evidence, lock safety and unleased scheduler sleeps. |
| Startup and maintenance | `test_startup_maintenance_mode.py`, `test_status_storage_guard.py`, `test_identity_startup_watch.py`, `test_identity_migration_assistant.py`: storage gating, no automatic preparation, no maintenance widget/support writes, readiness recovery without consent bypass, failed-apply restart and no duplicate activation. |
| HTTP and UI | `test_identity_migration_review.py`, `test_identity_migration_ui.py`: administrator/session and same-origin enforcement, real protected tar contents/length, changed-export aborts, visible blockers, backup-check pause and explicit continuation. |
| Backup/restore after conversion | `test_identity_migration_end_to_end.py`: legacy migration followed by real Borg backup and restoration of original bytes. `test_canonical_job_runtime.py`, `test_canonical_restore.py`, `test_canonical_restore_borg.py`: runtime, retention and restore history. |
| Reports and services | `test_canonical_status_views.py`, `test_notification_events.py`, `test_repository_info_refresh_scheduler.py`, `test_storage_repository_manager.py`: canonical joins, preserved delivery state, refresh state and async operations. |

Focused qualification includes a migrated real Borg backup/restore and live
HTTP migration, protected snapshot download and safe support diagnostics.
Private-permission rejection/acceptance is also tested with simulated filesystem
semantics. Actual Unraid and PHP platform execution is unavailable in the
source-test environment and remains a packaged maintainer test.

Normal-runtime fixtures explicitly initialize readiness to model validated
startup. Migration fixtures remain default denied; no suite-wide fixture
silently approves every temporary data root. Development scratch and test
roots stay inside the repository.

## Final candidate checks

The final source preflight must run the complete suite and resolve failures,
including stale fixture assumptions from earlier phases. Confirm that:

- Fresh setup and missing mounts create no shadow data directories and leave
  no previous runtime ready proof active. Recovery resumes normal startup only
  when no conversion or explicit continuation is required.
- Restart during a backup or detached worker blocks new admission, allows
  existing work and final writes to finish, and activates services once.
- Maintenance status, setup and support leave snapshot inputs, lock files and
  widgets unchanged. Normal write-capable diagnostics use writer admission.
- Managed cron uses guarded routes, unknown direct commands block and unrelated
  cron survives byte-for-byte.
- A completed migration followed by normal backups/cache updates restarts
  without repeating conversion or allocating new IDs.
- Protected export contains every advertised member, uses no public staging
  and never changes acknowledgement or starts conversion.
- Packaging includes the gate, observer, coordinator and UI assets, and the
  verified test-channel snapshot contains exactly its manifest and package.

## Maintainer tests on Unraid

Temporary-directory tests cannot establish actual Unraid mounts, Docker/VM or
filesystem behavior. Record results for the tested package using the
[English](../user-manual/en/migration-guide.md) or
[German](../user-manual/de/migration-guide.md) assistant instructions.

1. Install fresh and verify setup, page loading, job creation and first backup.
   Check startup with the array unavailable and recovery when storage appears.
2. Upgrade representative existing Local, SMB and SSH jobs where available.
   Confirm maintenance precedes scheduling and page loading never prepares or
   applies conversion automatically.
3. Select private persistent snapshot storage. Check missing/read-only storage
   and FAT `/boot` produce blockers. Prepare and download the snapshot, verify
   an independent backup, acknowledge and separately start conversion.
4. Reopen the browser and restart the service at the backup-check pause.
   Confirm the same snapshot, map and pause remain. On a disposable installation,
   test interrupted continuation, retained history and rejection of unexplained
   file changes without overwriting them.
5. Restart the UI during a job. Confirm it finishes and persists final logs and
   status while new work waits. Afterwards schedules, refreshes and notifications
   must run once.
6. Verify real Docker/VM recovery targets, retained logs, restore history,
   restore-test proof, weekly reports, repository assignments and notification
   retries. Compare original evidence and log bytes. Back up and restore files,
   verify bytes and exercise rename/repository changes without identity loss.
7. Restart after conversion and further normal activity. Confirm no repeated
   migration or new map and a working dashboard/live log. Check normal and
   maintenance support bundles exclude private recovery state and credentials.

Snapshots are data-recovery evidence, not plugin downgrades. Manual repair must
be documented; automatic restoration or deletion of uncertain state is outside
this qualification.
