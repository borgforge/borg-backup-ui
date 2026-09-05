# Immutable job identity contract

Issue #447, phase 1/9 (#471). Baseline: `origin/main` at `fcd2117`
(stable package 2026.09.05.1319). This is the target contract, **not a claim
that the current application or a migration already implements it**.

## Delivery and precedence

Work stays on `codex/issue-447-immutable-job-ids` in one draft PR. Phases
#471-#478 receive local automated tests; they are not independently merged,
installed, or published. #479 integrates and verifies the complete cutover
before the first test-channel candidate. Main remains available for hotfixes;
integrate relevant main changes before final verification. Never promote an
intermediate phase as an installable upgrade.

This contract consolidates the #447 body, its migration-safety and
production-analysis comments, and the later prefix/retention clarification.
The following resolutions replace contradictory earlier suggestions:

| Topic | Binding resolution | Owner |
| --- | --- | --- |
| Current prefix | Derive the legacy runner's actual `<backup_type>-backup` first, then retain valid existing prefixes. Do not blindly adopt an old list's first entry. | #472, #473 |
| Prefixes and prune | Apply one retention policy to the union of a job's prefixes in its current repository. Do not prune each prefix independently. | #474, #475 |
| Installation/startup | Detect and enter maintenance; require a verified snapshot and explicit administrator confirmation before conversion. Installation is not consent. | #472, #479 |
| Atomic migration | Crash-consistent journal and resumable per-file replacements across filesystems, not a fictional single cross-filesystem atomic rename. | #472, #479 |
| Aliases and reverse links | Keep the body's bounded `legacy_job_keys` and UUID repository reverse references. Suggestions to remove these stores were not approved scope changes. | #473, #474 |
| Status/log filenames | Readability is secondary; new records need collision-safe run identity, not just second-resolution time plus eight UUID characters. Existing logs are immutable. | #475 |
| Restore-test proof | Preserve the tested archive and its scope; retaining a result does not mean a new prefix or repository has been tested. | #477 |
| Full configuration restore | The current product restores `backup.conf` and imports partial job bundles; it has no complete installation restore feature. Do not invent one here. | #478 |
| Archived files/manifests | Inventory actual owned stores. Do not recursively migrate arbitrary `.status` files or implement hypothetical source manifests. | #472, #478 |

Related issues #452 (repository-change confirmation), #459 (retention
options), #414 and #470 (future source features) remain separate. None may
reintroduce mutable job identity. An implementation that cannot satisfy this
contract must document the conflict before changing it.

## C1. Canonical identity and metadata

- `schema_version` is the integer `4` for canonical job metadata. Other
  stores have independently versioned schemas; do not globally set them to 4.
- `job_id` is a canonical lowercase, hyphenated, RFC 4122-variant UUIDv4.
  Generate it once using the platform UUID generator, not from a name,
  prefix, timestamp, location, repository, or hash of personal information.
- The metadata filename is exactly `<job_id>.json`. Full IDs must be unique
  across the inventory; a valid UUID string with a mismatching filename is
  not a valid canonical job. UUIDs are identifiers, not authorization tokens.
- New metadata has no active `job_key`, `backup_type`, `type_id`, or
  `location`. Historical records may retain those values as descriptors.
- `name` is editable; `repository_key` selects one current repository;
  `archive_prefixes` holds complete readable prefixes. Retain every other
  operational setting, including fields the wizard does not currently expose.
- Before removing Type ID, materialize any effective Docker/VM/config
  defaults still derived from it. Evaluate the existing metadata and runtime
  precedence, not a guess based on names such as `appdata` or `vms`.
- `legacy_job_keys` is an ordered, duplicate-free list of exact legacy
  identifiers evidenced by the migration. Each alias has at most one owner.
  It is not a new foreign key, and edits never append new aliases. New or
  duplicated/imported-as-new jobs start with an empty alias list.

Example (operational fields omitted only in this illustration):

```json
{
  "schema_version": 4,
  "job_id": "11111111-1111-4111-8111-111111111111",
  "name": "Synthetic documents",
  "repository_key": "repo_docs",
  "archive_prefixes": ["documents-backup", "config-backup"],
  "legacy_job_keys": ["documents_local"]
}
```

All job-dependent APIs, scheduling, runtime, joins, caches and UI selections
use the full ID. A bounded legacy API adapter may resolve an exact known
alias centrally and report deprecation; no permanent dual writes. Never
interpret an arbitrary unknown key as a request to create a job. Reject
conflicting `job_id` and legacy-key arguments. Before release, document the
adapter's supported endpoints and removal boundary; an undocumented fallback
in individual readers is not an acceptable compatibility policy.

## C2. Names, archive prefixes and repositories

For an eligible legacy job, normalize prefixes as follows:

1. Determine the current prefix from the actual legacy runner input:
   `<backup_type>-backup`.
2. Validate all stored prefixes. A missing or empty list is a supported
   legacy state. A wrong type, empty element, unsafe element or non-string
   element blocks planning rather than being silently discarded.
3. Emit the derived current prefix followed by valid old prefixes in their
   original order, removing exact duplicates. Do not infer aliases from
   prefix history.

For the new model, store the complete prefix entered by the user. Use the
existing safe ASCII character family `[A-Za-z0-9_.-]+`, with no path
separators, whitespace, wildcard or Borg `::` selector; `.` and `..` are not
usable prefixes. Do not require or append `-backup`. New archives use
`<complete-prefix>-<timestamp>` and the wizard previews that exact name.
Changing the prefix moves the new value to the front, retaining previous
values without duplicates. This is a naming change, not a new job.

One job has one current repository. Multiple jobs may share a repository.
Do not enforce repository uniqueness, split repositories, move archives, or
change repository IDs. Preserve the repository deletion guard: any assigned
job prevents deletion. Convert `used_by`/`source_job_keys` to
`job_ids`/`source_job_ids` consistent with canonical job assignments, using
the inventory's existing assignment semantics. Never quietly repair an
unexplained conflicting active assignment.

Archive discovery and retention use current plus historical prefixes, **only
in the current repository**. Retention operates on their combined archive
set as one job, preserving keep-N semantics. Reject ambiguous/overlapping
ownership of matching archive names between jobs in a shared repository
before destructive maintenance. Do not just compare current prefixes for
equality; historical and delimiter-prefix overlaps matter too. Ambiguity is
not permission to prune another job's archives. #459 owns policy expansion;
the identity migration must not alter existing retention values.

Changing repositories keeps `job_id`; old archives remain in the old
repository and are not reachable through this job's Browse & Restore.
Repository-level read-only browsing (#464) is a separate, repository-owned
view and must still work for archives without a configured job. No repository
history is added to jobs.

## C3. Evidence, legacy history and continuity

Build a validated exact legacy-key-to-ID map before rewriting references.
Cross-check canonical filename, payload key, backup type and location.
Underscores inside a type are legitimate; do not split at the first
underscore. Explicit aliases require unique ownership and traceable evidence.
Names, similar prefixes and the mere existence of an archive are not identity
evidence. An operator-approved repair mapping, if supported later, must be
explicitly recorded and reviewed; do not generate one automatically.

The reported `config` -> `pfsense` failure is a blocking fixture:
`pfsense_local.json` exists, but `schedules.json` still addresses
`config_local`. The current wizard first saves metadata/repository changes,
then updates schedules. `write_schedules` validates the entire old map, so
the orphan key can raise `Unknown job key: config_local`. Existing cron may
also still contain the old key. Prefix history alone cannot safely repair it.
Block the active reference before conversion; preserve old statuses/reports
as unassigned unless an authoritative mapping exists. Do not run automatic
orphan-schedule cleanup during preflight.

| Record | Target treatment |
| --- | --- |
| Schedule, active restore, pending job notification, unresolved runtime recovery | Resolve exactly or block; disabled schedules are still configuration, not disposable history. |
| Unambiguously mapped active top-level `.status` | Enrich payload in place with schema/ID; preserve timestamps, outcome, archive, descriptors, filename and `log_file`. |
| Orphan/ambiguous historical status, delivery or finished restore | Retain original data and source provenance as explicitly unassigned; do not create a configured job or include it in active counters. |
| Unknown/malformed owned input | Block with a sanitized path/reason. Do not silently treat a failed read as an empty store. |
| Logs, unowned archive directories, recycle bin, cache contents | Preserve bytes and paths; not recursive migration inputs. |

Old records lack some snapshots and usually lack `run_id`. Keep missing
values unknown; do not fabricate historical repository/name from the current
job, invent an old run ID, or rewrite log text. New runs carry full `job_id`,
independent `run_id`, and name/prefix/repository/location snapshots. New
status/log/control names must be collision-safe even for simultaneous jobs
with equal names/prefixes and equal timestamp seconds. Short UUID display
suffixes may be added, but never identify or join records.

Dashboard and widgets start from configured IDs, overlaying runtime,
schedule, status and restore proof. Exactly one active row per job; unassigned
history cannot create ghost jobs. Reports/History join by ID and can display
run snapshots. Keep clearly separated access to deleted-job and unassigned
history. A name edit must not split reports or reset the last-run state.

Weekly snapshots have two known live locations: configured `SNAPSHOT_FILE`
(default: parent of `STATUS_DIR` / `weekly-snapshots.json`) and legacy
`STATUS_DIR/weekly-snapshots.json`. Inventory both even if the current reader
ignores one. Deduplicate equal key/week/value observations with provenance;
retain both conflicting values with an explicit conflict marker instead of
choosing max, min or newest. Do not turn uncertainty into reported growth.

Restore results use `<job_id>.test` and retain the tested archive/prefix and
available original descriptors. A rename preserves proof; a prefix change
does not prove an archive under the new prefix. After a repository change,
old proof must not attest the current repository. New results replace the
per-job result atomically. Keep independent `restore_id` values for restore
execution/history. Restore index and detail must refer to the same job ID.

Preserve notification queue/delivery IDs, attempts, retry times and reminder
deduplication state. Do not send again merely because a key changed. Explicit
system events/schedules such as the existing `restore_test` service entry
are not jobs and must not receive fabricated job IDs. Retain historical
orphan deliveries, but do not silently dispatch orphan pending job events.

## C4. Migration eligibility and execution boundary

Migration ID: `immutable_job_id_v1`.

Planning classification and execution state are different:

- `not_applicable`: genuinely empty installation, or a completely valid
  already-converted inventory with no active mutable references. Preserve
  existing IDs. Old unassigned historical data alone does not trigger replay.
- `applicable`: supported input with a fully consistent proposed mapping.
  This is **not** permission to apply; execution remains `pending` until the
  snapshot, quiescence and administrator gate have passed.
- `blocked`: unknown schema, corrupt owned data, ambiguous active reference,
  duplicate ID/alias, unsafe ownership/path or unavailable required input.

An interrupted attempt with a valid journal is a resume candidate, not a
fresh allocation. A partially converted installation without its journal is
blocked. Reuse every persisted allocated ID; never generate a second identity
after interruption. A future schema is not an empty/legacy installation.

Execution uses `pending`, `applied`, `skipped`, `failed`, `blocked` or
`not_applicable`, with migration ID, timestamps, affected objects/actions,
source fingerprints and masked error details in the journal/audit. Follow
the central runner contract (`detect` mapping with boolean `required`,
`apply` mapping with validated status). The current runner cannot yet safely
represent a pending confirmation: phases #472/#479 must extend the gate and
tests. `pending` or `blocked` must never be treated as normal startup success.
After a failed migration, later migrations stay blocked without detection or
application. A known existing migration must not mutate input before the
appropriate snapshot/approval boundary either.

Before any user-data rewrite:

1. Enter maintenance and quiesce **all** writers: HTTP writes, scheduler,
   backup/restore/test workers, detached backup and notification processes,
   background cleanup, cache refresh and widgets. Do not kill an active job
   just to make migration proceed. Show why it blocks.
2. Read owned stores directly without invoking lazy migration, discovery,
   schedule pruning, snapshot auto-write or repair helpers. Capture the
   exact planned file set and fingerprints. Validate configured roots,
   mounts, symlinks, permissions and space without executing Borg.
3. Persist the ID map/plan durably. Create and verify an exact-file snapshot
   of affected configuration/data and managed cron state. The snapshot is
   not a recursive copy of a backup share or repository. Re-read and verify
   bytes/checksums, not just existence or a successful copy return code.
4. Offer a protected download/export and explain that an independent copy is
   required. Require explicit administrator acknowledgement bound to this
   verified plan/snapshot. A click cannot verify that an external copy exists.
   Do not expose plaintext secrets in a public/downloadable diagnostic bundle.
5. Revalidate all preconditions immediately before apply. Source changes
   invalidate the plan/confirmation. After partial application, allow only
   journaled old/new fingerprints; an unexplained external edit blocks resume.

Stage replacements on each destination filesystem, flush, atomically rename
per file and verify again. Journal enough to resume after every boundary.
Keep the app in maintenance until referential-integrity verification passes.
Rebuild only managed cron entries at the final commit boundary; retain
unrelated cron content. Failure must not start writers against half-converted
data. Pending Docker/VM recovery with no live owner remains actionable and
must keep its exact stopped targets; migration must not mark them recovered.

Snapshots stay protected until explicit administrator deletion; the existing
keep-five cleanup must not silently remove this recovery snapshot. Snapshot
restoration is not a plugin downgrade: Unraid supplies the installed/current
package. Document repair with that or a corrected version and auditable manual
data restoration. Do not promise an automatic package rollback.

This validates states observed on each installation, not a claim that one
production copy represents every user. Unknown states block before rewrites.
Extend synthetic fixtures when new supported states are discovered.

## C5. Owned storage and excluded data

Resolve roots from configuration, not production paths in a migration script.
The machine-readable inventory in
[`identity-dependencies.json`](identity-dependencies.json) assigns source
readers/writers and boundary checks to phases #472-#479.

| Store | Ownership and cutover |
| --- | --- |
| Job metadata under the canonical configured jobs directory | Exact immediate JSON files; validate before filename/payload conversion. Explicit known legacy locations need their own audited detection, not arbitrary recursion. |
| `config/repositories.json`, storage profiles | Convert job reverse references; preserve repository/storage identity, paths, encryption and secret references. |
| `config/schedules.json`, managed crontab section | Convert job references, preserve cron/enabled; service entries stay service entries. |
| Runtime control/locks/recovery | Quiesce live owners first; convert persistent ownership safely, never guess from a prefix. |
| Immediate `STATUS_DIR/*.status` | Classify from validated payload/evidence; no recursive glob. |
| Both known weekly snapshot locations | Read both; preserve conflicting/unassigned observations. |
| Actual configured restore-test directory, immediate `*.test` | Convert known owners to UUID filenames without guessing filename splits. |
| `config/restore-runs.json`, `config/restore-history/index.json`, `runs/<restore_id>.json` | Preserve restore execution IDs and links across all three stores. |
| `config/notification-queue.json`, `notification-deliveries.json`, `notification-state.json` | Convert job correlation/deduplication without dropping queue or retry metadata. |
| Widget caches | Derived data; rebuild only after cutover using canonical IDs, under the writer gate. |
| Existing referenced secrets and Borg caches | Validate ownership/reference existence without reading secret contents into diagnostics; do not rename a secret merely because its basename contains a job key. Preserve existing cache contents; any new namespace must avoid old ownership collisions. |
| Logs, `.Recycle.Bin`, runtime/vendor, plugin packages, nested status archives without a reader | Excluded from conversion. Preserve paths/bytes; do not traverse them as migration inputs. |

The exact paths, source hashes, permissions and excluded boundaries belong in
the plan. No `rglob('*.json')` / `rglob('*.status')` over a data share. An
unknown record inside an owned store blocks; an unrelated file outside the
allowlist stays untouched. Neither rule justifies deleting unknown data.

## C6. Lifecycle, transfer and deletion

| Operation | Identity rule |
| --- | --- |
| Create or duplicate | New UUID; no imported aliases. Check prefix ownership in the selected repository separately. |
| Edit name, prefix, sources, schedule or repository | Retain UUID and all unrelated settings; no identity change. |
| Import as new | New destination UUID, even when the bundle contains one. Maintain a single import mapping for all selected dependent references. |
| Explicit update of selected target job | Retain target UUID; source UUID is provenance, not replacement identity. |
| Name/prefix/repository collision | Do not silently merge; explicit action/remap or reject. |
| Existing settings restore | Restore only its supported scope (`backup.conf`); do not pretend it restores jobs/history/secrets as a consistent installation. |
| Future complete-configuration restore | Preserve IDs only after full integrity validation; collisions require explicit remapping. Conditional contract, not a new #447 feature. |
| Delete job | Remove only the selected ID's active references and explicitly authorized artifacts. Retained history keeps former ID/descriptors; never delete by broad type/prefix patterns. |
| Factory reset | Preserve existing confirmation boundaries; enumerate any newly added owned stores. |

The existing `bbui-job-bundle-v2` transfer is a partial bundle, not disaster
recovery. Phase #478 must define its versioned ID-based successor and reject
inconsistent references before writes. Preserve supported legacy import
through a bounded conversion, not a second canonical identity system.

## Verification assets and remaining gates

[`tests/fixtures/immutable_job_id_v1/README.md`](../../tests/fixtures/immutable_job_id_v1/README.md)
describes the synthetic fixtures, deterministic test UUID allocation and
normalized observation format. Phase #471 tests fixture schema, privacy,
expected graph integrity and negative mutations of reusable assertions.
These are **not migration execution tests**. #472 must run its real detector
and planner against these inputs, and #479 must test actual on-disk results,
interruption/resume, no-write blocking and UI/HTTP maintenance behavior.

Phase #472 now provides the inactive planner, dependent-record verification
and private plan/snapshot/journal primitives described in
[Identity-migration foundation](identity-migration-foundation.md). Its tests
exercise actual planning and private recovery-state operations against the
synthetic inputs. No production apply engine, startup registration or installable
test candidate is enabled; the execution and integration gates above remain
owned by #479.

Before the first candidate: cover each journal write/rename boundary, stale
source fingerprints, unavailable mounts, disk/permission failures, live
workers, same-second runs, renamed jobs, partial imports, rejected corrupt
inputs and repeated startup. Verify snapshots independently, old archives
and log bytes unchanged, no wrong-job joins, and no background writes during
maintenance. A passing fixture schema test alone cannot authorize release.
