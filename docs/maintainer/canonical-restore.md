# Canonical restore identity

Issue #477, phase 7/9 of #447. Delivered on the shared integration branch and
draft PR #480. Migration activation, final preflight and the first test-channel
candidate remain gated by #479; this phase is not independently installable.

## Archive ownership and execution

Browse, precheck, download and restore requests select exactly one full
`job_id`. Old names/keys, duplicate query IDs and mixed identifiers are rejected.
The canonical inventory resolves the job's current repository under the shared
inventory lock. Only the literal ordered `archive_prefixes` are used for archive
discovery. The first prefix is current; the UI distinguishes retained prefixes.
An empty prefix set cannot cause an unfiltered repository browse, and direct
file/precheck/extract/download requests must belong to that prefix scope.
Repository statistics continue to describe the complete current repository.

A restore captures the repository/storage context before launching its worker.
The worker's Borg and SMB operations use that captured context, including when
the job is subsequently renamed, reprefixed, moved or removed. It does not
re-resolve the job mid-run. Existing path, symlink, conflict-mode, staging and
ownership checks still protect extraction. Repository locks carry the job ID,
run ID and readable start-time descriptors. Old repositories are never searched
or modified merely because the current assignment changes. Repository-change
confirmation remains owned by #452.

## Run history and recovery

New restore IDs are full UUIDv4 values, also stored as `run_id`. Active state,
summary and detail retain `job_id`, job-name, repository key/path, prefix/history,
location and selected archive snapshots. Current names describe navigation;
details describe the original operation. Legacy restore IDs remain unchanged.
Missing old descriptors are not invented from today's job metadata or filenames.
Deleted and unassigned history remains visible without creating configured jobs.

Writes use atomic durable JSON replacement. A run cannot launch if its initial
ownership cannot be saved. Terminal state is retained until history recording
succeeds; restart retries the same restore ID without creating duplicate rows.
Corrupt history blocks replacement rather than becoming an empty index. In-memory
retention removes only completed, recorded runs, never active or pending history.

## Restore tests and proof

Plans and policy updates use configured job IDs. Policy updates hold the inventory
lock, validate metadata and replace the selected job atomically without discarding
unrelated settings. Manual and scheduled invocations send `--job-id`; scheduled
runs use each job's captured level and interval. Disabled jobs cannot become due
or be selected for execution. The existing service-level live log remains intact.

The runner captures each enabled job's current repository context once. It selects
the latest archive from the union of the job's stored prefixes, rather than using
the latest archive of an entire shared repository. Each test gets a full run ID.
Results are atomically written to `<job_id>.test` with payload ownership,
report/run IDs, actual tested archive/prefix, repository, name, location and policy
snapshots. An existing file with unresolved ownership is never overwritten.
Notifications and overdue-reminder clearing use the same job ID. Existing chunked
probe performance rules match owned prefix history, including migrated prefixes,
so name/current-prefix edits do not silently disable those rules.

Proof is valid only for its payload job ID, the current repository and a prefix
still in that job's owned history. Name/current-prefix changes retain suitable
proof; changing repositories makes it stale and a scheduled job due again.
Missing/ambiguous proof, including JSON with duplicate ownership fields, cannot
satisfy a current plan. Deleted and unassigned
results remain historical; filenames cannot assign them to an active job.

## Migration boundary and validation

The inactive #472 planner already maps unambiguous legacy `.test` names and restore
references, snapshots originals and rejects collisions or inconsistent peers.
The restore-peer verifier now also checks run IDs, repository-key/location
snapshots and ordered prefix histories. No migration runs on ordinary reads.
Activation and interrupted application across the complete installation remain
#479 work; configuration transfer and lifecycle cleanup remain #478 work.

Focused coverage includes payload/filename conflicts, canonical plans/policies,
proof continuity, scheduled/manual HTTP contracts, restart after history write
failure, prefix discovery, repository locks, extraction safety, deleted history,
planner retry/partial-state checks, DE/EN rendering and real Borg 1.4.5 extraction
and proof writing. The final combined preflight/build is intentionally deferred.
