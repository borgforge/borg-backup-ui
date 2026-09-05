# Immutable identity fixtures (#471 / #447)

These are synthetic contract examples, not anonymized copies of a complete
production installation. They capture structures and failure modes discussed
in #447. They contain no repository data, credentials or real user paths.
`backup.example.invalid`, `/fixture/` and the fixed UUIDs are test values only.

## Format

- `base.json` contains configuration, directories and file contents for one
  legacy schema-3 job and its immediate dependencies.
- `cases.json` overlays whole files on that base: `{ "json": ... }` serializes
  JSON; `{ "text": ... }` preserves exact text, including malformed JSON.
  `null` removes a base file. There is no implicit recursive object merge.
- `allocation_order` injects deterministic UUIDv4 values into future planner
  tests. Production must generate random UUIDs once and persist the mapping.
- `preconditions` describes controlled test hooks, not a production journal
  format. In particular the journal case models a durable mapping and one
  completed replacement, **not** a real verified snapshot or real journal
  bytes. #472 must supply its real journal and filesystem failure adapters.
- `/fixture/` is relocated by the test materializer to an isolated directory
  under repository-local `.release-tmp/`. No Borg commands, network calls,
  crontab updates, actual process checks or production reads are performed.

## Expected observations

`expected` defines a normalized test observation, not the API response or
every dependent store's future wire format:

- `classification`: `applicable`, `blocked` or `not_applicable`.
- `execution`: supported apply/resume **after confirmation**, pending without
  user-data writes, or no user-data writes. Applicability is not approval.
- `reason_codes`: exact machine-readable fixture reason vocabulary; real
  planner adapters must explicitly map any differently named diagnostics.
- `jobs`: complete expected canonical metadata keyed by the injected full ID.
  Assert `<job_id>.json` filenames separately with `assert_canonical_job_files`.
- `bindings`: original `file#JSON-pointer` evidence -> resulting job ID or
  `null`. Values identify source records/references, not destination filenames.
  Extract actual destination IDs in the adapter; never just echo this map.
- `unassigned`: every null binding has an explicit retention/classification
  reason. No implicit deletion and no invented active job.
- `preserved`: original provenance -> exact value that must survive in the
  destination (possibly enriched with additional fields). For an entire
  historical object, compare all original members; new schema/ID fields may
  coexist. Preserve both weekly observations even when values conflict.
- `unchanged_files`: byte-identical files at their original paths after apply.
  Blocked/pending/not-applicable cases additionally require **all** user-data
  paths and bytes unchanged. Migration's own dedicated audit/plan/snapshot
  files must be checked separately, not silently excluded by a broad filter.

Bindings also cover service-versus-job distinctions, disabled schedules,
restore result/index/detail continuity, notifications, runtime recovery and
both live weekly stores. Explicit complete prefixes no longer require a
`-backup` suffix. The old runner's suffix is derived only during conversion.

## Test coverage and limitations

`tests/identity_contract_support.py` supplies reusable assertions for UUIDs,
canonical metadata files, aliases, referential integrity, unassigned history,
preservation and no-write outcomes. Negative tests deliberately corrupt these
observations to ensure the assertions fail.

In phase #471, tests validate the fixture data, source inventory and the
assertions themselves. The materialization self-check passes an expected
observation to the assertion only to validate the oracle; **it is not evidence
of an implemented or successful migration**.

Phase #472 must execute the actual read-only detector/planner on each input,
inject the UUID allocator and model real source fingerprints/journal actions.
Phase #479 must execute the real migration and read back destination files,
test every interruption boundary, retry/resume, missing mounts/space,
permissions/symlinks, all live writers and the administrator gate. Extend
fixtures with concrete bytes and OS hooks as those implementations are added.
Do not replace a regression golden merely to make a wrong migration pass.

The source dependency checklist is in
[`docs/maintainer/identity-dependencies.json`](../../../docs/maintainer/identity-dependencies.json).
Its test detects new files matching known mutable-key spellings and validates
reviewed source anchors. This is a regression guard, not a proof that a text
search can find every semantic dependency. Update anchors and ownership
deliberately as phases replace legacy code. Replace the phase-1
"not registered" assertion only when #479 intentionally enables the migration.

Run focused validation from the repository root:

```bash
python -m pytest -q tests/test_immutable_job_identity_contract.py
```

No test-channel package or stable release is created in this phase.
