# Canonical job model and wizard boundary

Issue #473, phase 3/9 of #447. Integration-only; **not installable or released**.
The binding contract remains [immutable-job-identity.md](immutable-job-identity.md).

## Implemented boundary

- `api/job_model.py`: strict UUIDv4/schema-v4/filename validation, complete
  prefix validation and preview, ordered prefix history, alias/ownership
  checks, and settings-preserving create/edit/duplicate metadata operations.
- `api/job_store.py`: direct strict JSON reads and a serialized metadata plus
  repository-assignment write transaction. Reads reject duplicate JSON keys,
  symlinks, malformed records, missing IDs and unsupported schemas. They do
  not discover legacy jobs, migrate files or clean schedules.
- `api/wizard_api.py`: the wizard validates effective settings and existing
  repository/storage selection. Location comes from that selection and is
  returned for display; it is not persisted as job identity.
- `ui/js/pages/wizard.js`: name, complete archive prefix, repository selection;
  UUID remains internal. A new job receives an editable name-based suggestion,
  but manual prefix edits and existing jobs are never auto-renamed. The preview
  is `<complete-prefix>-YYYY-MM-DD_HH-mm-ss`, with no hidden `-backup` suffix.
  The existing history tooltip explains current-repository-only archive scope.

Changing a prefix retains all earlier prefixes, including when switching back
to a previous value. Duplicating creates a new ID, clears aliases and old
prefix history, and requires independent archive ownership. It preserves
operational settings but does not copy schedule, status, logs or restore proof.
Multiple jobs may use the same repository with nonoverlapping archive scopes.
Name equality alone is not a conflict.

## Wizard request contract

This is the **target API**, not a published compatibility promise for the
current stable version. No mutable-key fallback or dual writer is installed.

| Operation | Request | Result |
| --- | --- | --- |
| Load | `GET /api/wizard/job?job_id=<full-uuid>` | Exposed job settings, `job_id`, `revision`, prefix/history/preview, derived location and saved UUID schedule |
| Preview | `POST /api/wizard/preview`, wizard fields and `_wizard_mode` | Effective flow and exact archive-name pattern; no allocated ID or metadata write |
| Create | `POST /api/wizard/save`, `_wizard_mode: "create"`, no ID | Server-generated UUID, `<uuid>.json`, empty aliases |
| Edit | Same endpoint, `_wizard_mode: "edit"`, `job_id`, changed fields | Same ID/file, preserved unknown settings, updated prefix history |
| Duplicate | Same endpoint, `_wizard_mode: "duplicate"`, source `job_id`, new prefix/name | New ID/file, empty aliases/history except the chosen new prefix |

The form sends `expected_revision` for edits/duplicates. It is the SHA-256 of
the complete opened metadata, checked again under the inventory lock. A stale
editor is rejected. Ordinary saves cannot submit `legacy_job_keys` or replace
`archive_prefixes`; the server owns both lists. Unknown IDs never imply create.

Create/save returns `job_id`, `revision`, `job_name`, `archive_name_preview`
and the existing scriptless result fields. The UI uses the returned ID for
`PUT /api/schedules`; it never reconstructs a key from name/prefix/location.
If schedule saving fails after job creation, a retry edits the returned ID
instead of creating another job. The schedule API is now converted in #474;
see [canonical-job-control.md](canonical-job-control.md).

## Persistence and failure limits

The transaction reads the complete canonical job and repository inventories
under the existing inventory lock. Before changing anything it verifies
aliases, prefix ownership and both repository reverse-reference lists against
job assignments. It patches only the affected ID in `job_ids` and
`source_job_ids`, retaining order and unrelated repository fields.

Normal I/O failures restore original bytes. Each file replacement is durable;
the metadata/repository pair is **not claimed to be crash-atomic**. A process
crash between replacements can leave a detectable assignment conflict, which
must block operation rather than trigger silent reconciliation. #479 must wire
the global startup/API gate for this state before any candidate is published.
The existing migration storage module supplies only pure/direct safe-read
primitives here; its planner, snapshotter and applier are never invoked by a
wizard read/save.

The migration planner now validates its proposed schema-v4 jobs through the
same model. Legacy conversion remains explicit and inactive. These checks do
not claim full cross-store migration or whole-installation verification.

## Remaining phase owners and release gate

- #474: general discovery, repository references, UUID configuration actions
  and managed cron are implemented; see the control-plane boundary document
  for transaction guarantees and explicit pending runtime/retention guards.
- #475: runner, archive creation with the exact prefix, status, logs, recovery
  and notifications. Model
  and preview tests are not evidence of an end-to-end backup yet.
- #476-#478: dashboards/reports, restore, imports and remaining
  persistence boundaries. Duplicating through the wizard is available at its
  API/entry-point boundary; general job actions are not cut over here.
- #479: approved manual migration assistant, snapshot/independent backup
  acknowledgement, final verification and first installable test candidate.
- #452: repository-change warning and explicit confirmation is separate and
  was not implemented at the start of #473. Nothing here replaces that issue
  with a repository-history feature or claims the confirmation is complete.

User manuals/screenshots describing the published product remain unchanged
until the integrated workflow is ready. The pending release-note fragment is
held for the final #447 candidate, not an intermediate release.

## Focused verification

- `test_canonical_job_wizard.py`: real metadata/assignment lifecycle, ID
  retention, exact prefixes, unknown settings, stale revisions, corrupt inputs,
  write-failure rollback, HTTP handler boundaries and synthetic planner output.
- `test_canonical_wizard_ui.py` plus `canonical_wizard_ui.cjs`: execute the
  JavaScript collector/preview/save retry in both languages. Node.js is needed;
  set `BBUI_TEST_NODE` if it is not on PATH. A skipped JS test is not a pass.
- Existing wizard, source/exclusion, retention, activity-log and schedule-load
  regressions use explicit synthetic target fixtures. The test-only fixture
  helper is not a migration engine and is not imported by production code.
- The legacy runner's file-activity tests remain independent until #475;
  they do not pretend to prove the new wizard-to-runner end-to-end path.
- Full preflight, packages and Unraid migration/backup acceptance tests remain
  deferred under the approved #447 integration exception.
