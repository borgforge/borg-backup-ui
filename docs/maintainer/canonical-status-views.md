# Canonical status views

Issue #476, phase 6/9 of #447. This integration branch is not installable yet.
The guarded migration, final preflight and first test candidate belong to #479.

## Current jobs and historical runs

`api/status_read_model.py` reads the strict configured inventory. Every current
UUID produces exactly one dashboard row, including disabled jobs and jobs that
have never run. Runtime, schedules and restore proof join on that full UUID.
Running jobs count as running until the process owner finishes, even when a
completed status has already been saved. An earlier error or success is not
counted again while the job is running. Disabled jobs remain visible but do not
contribute to enabled-job outcome or restore-proof counts.

Current names, storage and repository settings describe navigation. Historical
rows retain payload name, archive prefix, repository and location snapshots.
Missing historical snapshots and run IDs remain missing. A legacy payload's
`backup_type` and `location` may be displayed as historical descriptors; neither
those fields nor filenames determine ownership. The first native UUID run
supersedes migrated legacy status, including after a clock correction. Growth
never uses a future historical status as its baseline.

History accepts `job_id`, `scope`, location, outcome and pagination filters.
Scopes are `all`, `configured`, `deleted` and `unassigned`. Reports select a full
`job_id` or the explicit `scope=unassigned` view. Deleted UUIDs and unassigned
records remain accessible but cannot create active dashboard or widget jobs.
Unassigned reports show retained observations and outcome totals without
claiming a shared job growth/trend series. DE/EN labels distinguish current
navigation, historical descriptors and earlier migrated runs.

Restore proof is read from the UUID file only when the payload owns that UUID.
A known repository snapshot must match the current repository, and the
recorded archive prefix must belong to the job's ordered prefix history. Unknown or changed targets produce stale proof
with an explanation. Changing the job name or current prefix does not invalidate proof for a
retained prefix in that same repository. This is
the status reader boundary; restore execution, result writers, selection and
history are completed in #477.

## Weekly observations

`api/weekly_snapshots.py` reads both the configured snapshot path and the known
historical path under the status directory. It accepts the canonical schema-1
observation envelope only. Normal reads and writes never convert legacy stores;
the approved migration owns that conversion.

Equivalent observations merge provenance. Conflicting values for the same
job/week remain separate observations and are marked as conflicts. Charts use
an unavailable size for that week rather than selecting a maximum or newest
value. Growth requires an unambiguous baseline from the same known repository.
A repository change or unknown historical target does not produce a growth
claim. Historical source files and observations are retained.

The dashboard retains its existing weekly-sample write behavior. Under a file
inventory lock it replaces only its own `observation_kind=runtime` sample for
the current job/week. Migrated and unassigned observations are preserved. Writes
are atomic; repeating the same sample leaves the file unchanged. Native samples
remain compatible with the migration's record verifier. Widget reads pass
`write_snapshots=False` and do not create weekly observations or run Borg.

## Widgets, reports and reminders

Homepage and Unraid widgets use the configured UUID inventory and shared status
categories. The Homepage response keeps friendly `active.jobs` labels and
adds the matching full `active.job_ids`. The Unraid cache retains schema 1 and adds
`identity_schema_version=1`, full job IDs and native/legacy run metadata. Legacy
cache generations are rejected by startup reuse and the dashboard page; they
cannot restore ghost jobs or stale aggregate counters. The browser recomputes
exclusive enabled-job counters from unique canonical cache items.

The existing boot policy still avoids waking array storage. A valid canonical
cache can be retained until a permitted event refresh; #479 owns cutover cache
invalidation. No cache read performs a Borg call or migration.

Weekly mail joins configured jobs, schedules and status payloads by UUID and
uses current labels, while preserving historical run names. Deleted/unassigned
history does not enter active report totals. Repository growth comparisons need
the same known target. Overdue schedule joins and persisted reminder keys keep
the UUID introduced in #475, so a rename does not reset reminder deduplication.

## Validation and remaining integration

Focused tests cover config-to-pfsense continuity, identical names with distinct
IDs, repository moves, missing historical snapshots, deleted/unassigned history,
running/never/disabled counters, weekly conflicts and provenance, native record
verification, reminder deduplication and target-scoped restore proof. Executable
Node tests exercise DE/EN navigation, growth and Unraid cache counters. Local
HTTP smoke checks exercise the actual router, authorization, canonical status,
history/report filters, frontend assets and completed-run log reconnect.

#477 and #478 still own restore and transfer/cleanup cutover. This phase does
not activate migrations, change the stable version or publish a package. The
shared draft PR remains pending integrated validation and maintainer testing.
