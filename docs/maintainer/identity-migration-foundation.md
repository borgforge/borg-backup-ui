# Inactive identity-migration foundation

Issue #472, phase 2/9 of #447. This documents the implemented planning and
private recovery-state primitives, not an installable migration. The binding
target model remains the [immutable job identity contract](immutable-job-identity.md).

## Current boundary

The implementation is deliberately absent from the migration registry,
application startup and HTTP routes. It has no `apply()` function and performs
no installation-data conversion, cron update, Borg operation or background
service activation. Calling a planner or verifier never grants permission to
start writers. Separate explicit storage calls may write only their dedicated
private migration-state directory.

Phases #473-#478 still own the application consumers and writers. #479 must
provide the complete maintenance, confirmation, execution and final-verification
coordinator. There is no test-channel candidate for this intermediate phase;
the first candidate remains gated on the complete, testable cutover in #479.
The verifier is an identity/reference verifier, not a replacement for the full
job-options validation still owned by #473. Settings are preserved; the later
coordinator must combine both validators before allowing normal operation.

## APIs and responsibilities

| Module / entry point | Responsibility and limitation |
| --- | --- |
| `api/migrations/immutable_job_id_v1.py`: `build_plan(config, *, uuid_factory, journal_plan, control_root, cron_text)` | Read owned installation stores, validate identities and dependencies, and return a proposed plan. Optional arguments have defaults; tests inject UUIDs and isolated roots. `journal_plan` is the original validated persisted plan, not an arbitrary repair map. |
| `detect(config, *, control_root)` | Read-only, runner-shaped summary with boolean `required`, classification, execution status and reason codes. It is not registered with the runner. A blocked inventory never reports `required=False`. |
| `verify_target(config, *, control_root)` | Re-read actual on-disk stores and check canonical cutover integrity. It does not verify merely the proposed replacement objects. Even a valid result keeps `activation_allowed` and `writable_services_allowed` false. |
| `api/migrations/identity_records.py`: `project_records(records, jobs, aliases)` | Deterministic, no-I/O projection of dependent records. Preserve original historical evidence; block unresolved or conflicting active ownership. |
| `verify_records(records, jobs, aliases)` | Validate actual target references without repairing active mutable keys through aliases. Filesystem ownership and snapshot-byte checks remain separate responsibilities. |
| `api/migrations/identity_storage.py`: `seal_plan`, `persist_plan`, `load_plan` | Validate and content-hash a complete plan; durably publish and reload the same proposed allocation without overwriting a conflicting plan. |
| `create_snapshot`, `verify_snapshot`, `verify_inputs` | Copy and independently verify the exact captured originals; recheck file fingerprints and immediate directory inventories. No restoration or production replacement is performed. |
| `verify_preconditions` | Default-deny library gate requiring the bound confirmation, verified snapshot, unchanged inputs, explicit quiescence check and external-input recheck. It is not an authenticated UI or an execution transaction. |
| `append_journal`, `read_journal` | Maintain a private, sequenced, hash-linked JSONL record with fixed statuses, phases, reason codes and known action IDs. No free-form exception or payload text is accepted as a journal reason. |

These are internal Python APIs for the staged implementation and automated
tests. They are not user-facing maintenance commands or instructions to run
against a production installation now.

## Read-only inventory and proposed plan

The scanner derives configured roots and reads only the owned stores listed
in contract C5, including both known weekly-snapshot locations and the exact
known legacy job locations. It records immediate directory membership as well
as individual files; a newly added file or disappeared input cannot be hidden
by checking only objects that remain discoverable.

Reads reject symlinks, unsafe paths, non-regular matching inputs, malformed
JSON, duplicate JSON members, unsupported schemas and inconsistent ownership.
Known Unraid mount paths are checked for availability. The scanner does not
call application discovery, lazy migration, orphan-schedule cleanup, weekly
auto-write or repair helpers. Logs, unrelated nested files, recycle bins,
runtime/vendor contents and Borg repository/cache data are not recursively
inventoried or converted.

A supported plan contains the full UUIDv4 job map, canonical proposed jobs,
exact aliases, record bindings, preserved unassigned history, input
fingerprints, directory inventories and proposed actions. `write_json`
actions include the exact expected destination bytes' fingerprint;
`retire_source` identifies only an individual superseded source and its
canonical replacement. These are descriptions, not executed writes.

`build_plan` may propose fresh UUIDs in memory. The allocation becomes durable
only after explicit `persist_plan`. The full plan receives a `plan_id`
content digest; it is not a cryptographic signature or an administrator's
approval. An applicable plan remains `pending`. An empty or completely valid
canonical installation is `not_applicable`; uncertain or unsupported states
are `blocked` with no proposed production actions.

The foundation preserves stopped runtime-recovery targets, notification retry
and reminder state, independent restore IDs and original history descriptors.
Historical UUIDs belonging to deleted jobs remain in the records while their
bindings to the active job graph remain unassigned. Weekly observations retain
source provenance: equal observations are deduplicated and conflicting values
remain explicit. Restore-history index/detail pairs must agree; the planner
does not invent missing peers or silently select one contradictory record.

## Explicit private state directory

The caller must supply `state_dir`. No production default is selected and no
automatic fallback to another directory or weaker permissions is implemented.
It must be outside the plan's owned input files and inventory roots, on an
available **persistent filesystem supporting private POSIX permissions and
hard links**. The process must own directories with mode `0700` and stored
files with mode `0600`.

The Unraid FAT `/boot` USB filesystem is unsuitable for this private state
store. This does not prohibit reading job/configuration originals on `/boot`;
it means the protected plan, snapshot and journal must live on a suitable
separate filesystem. Lack of required permission or publication semantics
blocks storage; the code does not silently relax them. The later coordinator
must select and validate a persistent mounted location and keep it available
through the entire migration. Library calls alone do not prove persistence or
that every required mount will remain available.

The private layout is:

```text
state_dir/
  plan.json
  journal.jsonl
  snapshot/
    metadata.json
    manifest.json
    files/
      <source-path-hash>.bin
      external-managed_cron.bin
```

The journal exists only after an explicit append. The external cron blob exists
only for a supplied capture. Publication uses private staging files, flushes
and exclusive final-name publication without overwriting a conflicting file.
`metadata.json` durably records the snapshot's UTC creation time before blob
copying; retries retain that time rather than inventing a new snapshot age.
The manifest binds it to the original plan, complete ID map and ordered action
summaries, and distinguishes file artifacts from externally captured cron.
Action summaries contain IDs, kinds and source/target paths, not replacement
payloads; the overall snapshot still remains private and potentially sensitive.
Snapshot verification checks the exact expected blob set, sizes, hashes and
binding to the persisted plan; existence alone is not sufficient.

Treat **the entire state directory as secret-bearing**. Snapshot originals can
contain raw, secret-bearing configuration and notification content. Plan payloads
can also contain sensitive settings, paths, messages or fields retained from
existing records. Private file permissions are not encryption. Never attach
these files to public issues, logs, normal support packages or an unprotected
download. Only sanitized reason codes and deliberately selected metadata
belong in public diagnostics. A secure export/download design remains future
coordinator work; no such endpoint exists in this phase.

## Confirmation, quiescence and cron

The approved user-facing sequence is specified in
[contract C4.1](immutable-job-identity.md#c41-approved-user-initiated-migration-assistant-479):
automatic read-only detection, explicit preparation, verified snapshot,
mandatory user backup-check pause, then a separate explicit apply action.
This remains #479 implementation work; the foundation does not expose an
assistant or turn snapshot completion/acknowledgement into automatic execution.

`verify_preconditions` denies by default. It requires an applicable pending
plan, a verified snapshot, an explicit approval tied to `plan_id` and the
snapshot digest, and acknowledgement that an independent backup is required.
Acknowledgement is not proof that an external copy was actually made.

The gate also requires a supplied quiescence callback returning exactly `True`.
Missing callbacks, failures or negative results block. Existing owner checks
in the scanner are useful evidence, but are not a complete exclusion barrier
against detached workers or new concurrent activity. #479 must authenticate
the administrator, enter maintenance, prevent all writers and retain the
necessary exclusion across snapshot, apply and verification. It must cover
backup/restore/test workers, notification delivery, scheduler, cleanup,
widgets and other write-capable background activity without killing a live
job to force progress.

The planner never executes `crontab`. A future coordinator must capture actual
cron text and supply `cron_text`; omitting it does not mean the crontab is
empty. A plan without the capture may be inspected, but cannot pass snapshot
and execution preconditions. A genuinely empty captured crontab is supplied
explicitly as an empty string. The captured bytes are included in the private
snapshot, and an external-input callback must return the same capture before
the gate passes. Rebuilding only the managed cron section, preserving unrelated
entries, remains the final execution boundary in #479.

## Interruption and resume boundaries

A resume loads the original sealed plan and reuses its complete UUID map,
plan ID, original snapshot footprint and expected actions. It must not allocate
fresh identities or snapshot partially converted data as a new starting point.
The scanner checks every saved input, including files that have disappeared.

Each observed file must match its exact original fingerprint or its plan's
exact expected post-replacement fingerprint. A superseded source may be
absent only when the matching canonical destination exists with the expected
replacement fingerprint. Equivalent parsed JSON is insufficient: unexplained
byte changes or permission changes block. Directory membership and unrelated
inputs are revalidated as well. Missing both a source and its replacement is
not a completed retirement.
Mixed legacy/UUID job files require the original plan even when their current
references could be resolved. Referenced repository secret files are checked
again for existence, regular-file type and symlinks, without reading their
contents into the plan.

Snapshot creation can resume between completely published blobs when the
persisted plan, originals and completed blobs are unchanged. A crash during
publication may instead leave an incomplete staging/publication state,
unexpected snapshot file, inconsistent link count or truncated journal.
These conditions block verification and require explicit diagnosis; no
automatic cleanup of questionable recovery evidence is provided. A malformed
or truncated journal is not silently repaired or treated as an empty log.

There is no production apply engine, automatic rollback or snapshot-restore
operation in #472. The eventual cross-filesystem migration must remain
crash-consistent and resumable, not claim a single atomic filesystem
transaction. Journal entries alone do not demonstrate that installation data
was converted or verified. Data recovery is distinct from downgrading the
installed Unraid plugin; the existing rollback limitations still apply.

## Verification and remaining work

The tests now exercise the actual read-only planner with the phase-1 synthetic
fixtures, pure record projection, default-deny gates and private snapshot and
journal primitives. Negative cases cover malformed/ambiguous inputs, changed
sources, partial states, denied permissions, snapshot corruption and preserved
historical identity. They do not exercise a production apply path because none
exists yet.

The final coordinator must integrate the existing migration runner's pending
and maintenance behavior, authenticate confirmation, supply live cron and
writer checks, perform and journal the replacements, handle protected snapshot
retention/export, and verify complete startup and UI behavior before the first
test candidate. Passing this phase does not assert coverage of every existing
installation or guarantee migration success on unknown states. Unknown states
must continue to block before modification and gain explicit supported
fixtures when their semantics are understood.
