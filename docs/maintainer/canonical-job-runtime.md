# Canonical backup runtime

Issue #475, phase 5/9 of #447. This integration branch is not yet installable.
The complete migration/startup gate and test-channel candidate belong to #479.

## A run owns a frozen configuration

Manual and scheduled starts accept a full UUIDv4 `job_id`. Start preparation
validates the complete inventory, enabled setting and credential references
under the inventory lock. It allocates an independent UUIDv4 `run_id` and writes
one private, exclusive `context.json` under `/run/borg-backup-ui/jobs/<run_id>`.
The directory is private and the context file is mode 0600. It contains the
canonical job, resolved repository/storage and expanded settings. It can
contain private configuration; never return the context or settings in an API,
log, support summary or public migration preview. The descriptor projection
is the only public subset.

The runner verifies this context and freezes the job name, complete current
prefix, ordered prefix history, source/exclude paths, compression, retention,
file-activity mode, runtime selections, repository key/path and location. An
edit to a job does not change a started run. Environment overrides cannot
replace its job ID, run ID or file-activity setting. New archive names use
`archive_prefixes[0]` exactly, followed by Borg's timestamp. No `-backup` suffix
or job UUID is inserted into Borg archive names or credentials.

In-process admission covers the check, subprocess launch and state publication.
Runner resource locks include `job:<job_id>`, the exact repository URI and any
shared Docker/VM/SMB resource. Lock files use a bounded hash of the full resource
name and carry authoritative IDs, readable snapshots and the process start
token. Stale replacement is serialized; heartbeats are atomic and releasing a
lock requires both the owning process and run. Restore operations still use a
separate service lock until their per-job cutover in #477.

## Status, logs and recovery

New status files contain full job/run IDs and start-time name, prefix history,
repository key/path and location snapshots alongside archive name, Borg exit
code and statistics. Filenames use a bounded readable slug, short job UUID and
full run UUID. New writes never overwrite an existing status. Legacy status
filenames/bytes remain unchanged. Only payload job IDs group records; missing
historical run IDs remain missing and unassigned history cannot create a job.
Dashboard/report/history presentation is converted in #476; see
[canonical-status-views.md](canonical-status-views.md).

Log requests use `job_id` and `run_id`. SSE stays pinned to the selected run;
starting another run never retargets an open stream. Completed run references
come from status payloads, not globbing filenames derived from a job name.
Without file activity, the existing compact SSE behavior remains. With file
activity, the existing bounded log windows and independent RAM capture worker
remain: every byte is retained, and the worker persists the complete log only
after the backup process exits. The capture record keeps the saved path and
file identity across the RAM-to-disk copy and a WebUI restart.

Cooperative cancellation checks the active job/run pair directly, without
waiting for a configuration lock during retention. It preserves the existing
Docker/VM recovery phases and rejects cancellation during recovery. Recovery
records store the same snapshots and exact stopped target IDs. Restarting or
acknowledging those records does not resolve an edited job name.

Backup notifications, queue entries, delivery history and reminder keys use
job IDs. Run events also include run IDs and readable snapshots. The migration
preserves reminder timestamps while changing their correlation keys, so a
rename does not resend an existing reminder. Non-job notifications use an
explicit service field. Restore verification consumers finish their cutover
in #477; old unassigned records remain available for diagnosis.

## Shared retention across prefix history

The bundled Borg 1.4.5 accepts one shell glob without alternation. A shared
retention planner therefore selects one keep set across the union of all
start-time prefixes in the start-time repository. It matches Borg's daily,
ISO-week, monthly and yearly rules, including the oldest-archive fallback and
checkpoint treatment. Manual retention uses this same engine and a frozen run
context, including when the selected job is disabled.

The engine reads the complete archive inventory, filters only explicit
`prefix-` ownership, computes one policy and verifies that names, IDs and
timestamps have not changed before deletion. A nonempty discard set is passed
as exact archive names to one `borg delete` invocation with `--` separating
options. An empty set never invokes delete. Oversized argument lists, malformed
inventories, zero-only policies or changed ownership stop retention. The plugin
repository lock spans the operation, and the configuration lock prevents
assignment changes during selection/deletion. Cancellation and live-log reads
remain independent of that configuration lock.

A job moved to another repository during backup skips maintenance of its old
target. Normal name/prefix edits retain the original run's scope. Borg acquires
its own repository lock for the deletion command. Its CLI has no conditional
archive-ID delete or transaction spanning separate list/delete commands: an
external Borg process can still modify the repository between the final list
and delete lock acquisition. Concurrent external rename/delete/recreate work
must therefore not be run alongside plugin retention. No Borg lock is bypassed
or broken, and archives are never renamed to implement filtering.

Tests compare the selected set with the shipped Borg binary, delete from an
isolated synthetic repository, preserve an unrelated archive and run Borg
check afterward. References: [Borg 1.4.5 archive commands](https://github.com/borgbackup/borg/blob/1.4.5/src/borg/archiver.py),
[calendar retention rules](https://github.com/borgbackup/borg/blob/1.4.5/src/borg/helpers/misc.py).

## Cache continuity

The migration records the old effective cache directory and check marker as
an explicit `cache_reference`, with the original repository key. It does not
move, rename, clear or copy cache contents. Name/prefix edits continue using
that directory. Borg's repository-ID subdirectories isolate repository caches;
a repository reassignment uses a separate check marker, so an old repository
check does not suppress checking the new target. New and duplicated jobs get
an independent UUID cache namespace. Credentials and archive names retain
their own references.

## Remaining integration work

- #476: dashboard, widget, history, reports and overdue presentation/joins.
- #477: per-job restore and verification workflows.
- #478: transfer, historical artifact deletion and recovery workflows.
- #479: startup/writer gate, approved migration assistant, full integration
  checks, final preflight and first test-channel candidate. The assistant must
  verify quiescence of backup runners, control records, restore operations,
  notification writers and the independent activity-capture worker.

No stable files, version bump, full source preflight or test package are part
of this intermediate phase, as allowed by the #447 integration exception.
