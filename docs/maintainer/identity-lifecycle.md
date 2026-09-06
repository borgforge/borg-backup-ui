# Job identity lifecycle (#447, #478)

This implements phase 8 on the integration branch. The approved scope in
[the identity contract, C6](immutable-job-identity.md#c6-lifecycle-transfer-and-deletion)
takes precedence over the earlier full-recovery wording in #478. Existing
settings recovery still restores **only `backup.conf`**. It neither restores
job/history/secret stores nor downgrades plugin code. A complete installation
restore remains a conditional future contract, not a new #447 product feature.
The migration assistant's protected, verified snapshot/export is owned by #479
and remains separate from ordinary job/configuration exports.

## Partial job transfer

`bbui-job-bundle-v3` contains selected schema-v4 jobs, their repositories and
storages, their schedules, and an explicit reference map. Repository reverse
references are filtered to the selected jobs. Service schedules, history,
runtime control/recovery, notification queues and unrelated profiles are not
part of a job copy. Unknown dependent-object fields and incomplete references
are rejected before writes. An explicitly empty selection imports nothing.

- `new` always allocates a fresh destination UUID and clears source aliases/cache
  references. Reusing a source ID, name, repository or prefix cannot select an
  existing target. Overlapping prefix ownership requires an explicit different
  prefix or an explicit merge; no prefix is silently invented.
- `merge` requires `target_jobs[source_id]`. It retains the target UUID, aliases,
  cache reference, unknown settings and prefix history. Two sources cannot
  target the same destination in one transaction.
- `skip` changes neither the job nor its protected files. Secret-only transfer
  requires an explicit existing target using the same repository.
- The reference map must match the entire included graph. Selected schedules
  and repository reverse links are remapped together. Shared storage/repository
  identifiers must describe the same target; collisions do not overwrite them.
- Encryption retains the authenticated v2 envelope. The job payload is
  `bbui-job-bundle-secure-v3`. Passphrases and keyfiles are decoded, size/digest
  checked, and staged before writes. Imported source-host paths cannot select
  secret write destinations. Existing different secrets require the separate
  explicit secrets/repository-key workflow. Job import never runs Borg key
  import against a repository.

Known v2 job bundles have a bounded conversion boundary in
`api/legacy_job_transfer.py`. It reuses only the inactive migration's pure
metadata validation/default projection, not its filesystem planner or runner.
Preview generates temporary source selectors and returns `legacy_source_ids`;
apply must return that exact map when selecting preview rows. Destination UUIDs
are independently allocated. Legacy names are never matched to live jobs.
Known schemas 1-3 preserve operational settings and materialize the legacy
`<backup_type>-backup` prefix; ambiguous or incomplete input is rejected.
Unrelated profiles and the restore-test service schedule in older bundles are
outside the job scope, which the import dialog explains.

Inventory, schedules and protected files share one configuration transaction.
All validation precedes replacement. Ordinary file/cron failures restore old
bytes and managed cron; failed rollback raises a recovery-required error.
This is not crash-atomic across filesystems. The global maintenance/writer and
restart/recovery gate remains #479 work. No intermediate package is published.

## Owned stores, deletion and reset

`api/identity_lifecycle.py` is the closed registry for immediate canonical job
files, repository/storage/schedule stores, restore active/index/detail stores,
notifications and reminder state, runtime recovery, status/proof and weekly
observations. Runtime controls and resource locks are separately inventoried for
diagnostics. Logical names do not authorize arbitrary client-provided paths.
Its typed reference map includes payload values, reverse-link arrays, schedule
keys and reminder keys. It never rewrites descriptive strings or log text.

Job deletion removes the exact metadata file, reverse links and schedule.
Pending notifications, runtime recovery, active restores or a running backup
block deletion. Repository objects, Borg repositories, repository-owned secrets,
cache contents and log files are preserved.

Optional history deletion uses a preview listing each exact owned record and a
content-bound identifier. The client explicitly returns selected identifiers;
changed/missing records invalidate the request. Status/proof/detail files are
selected by payload `job_id`, never by filename/prefix. Collection records are
removed individually. Restore summary and detail must be confirmed together.
Unselected and deleted-job history retains its former ID and descriptors.

Factory reset keeps its existing hostname/phrase/risk confirmations and
repository-inside-root blocker. The configuration and operational roots cover
all registered persistent ID stores. Existing stores outside those confirmed
roots block reset instead of expanding deletion scope. The fixed
`/run/borg-backup-ui/jobs` control directory is removed after service shutdown.

For future managed files (#470), ownership must be an explicit validated
`job_id` association in a registered store. A friendly filename, prefix,
source path or exclusion-rule content is never ownership evidence. New managed
stores must extend transfer selection, the reference map, migration inventory,
reset coverage and diagnostics before use. Unregistered files stay untouched;
this phase does not invent or traverse future rule manifests.

## Health and support

System Health shows duplicate/missing IDs, invalid filenames, dangling active
references, unresolved legacy history, retained deleted-job history and orphaned
terminal controls. Findings contain codes, logical filenames, bounded names and
IDs, not record bodies or rule contents. Historical evidence and cleanup
candidates are distinguished from active-reference errors. No cleanup runs on a
health read.

Support bundles use a bounded job descriptor projection and selected settings
instead of dumping complete job/backup.conf content. Exclusion/rule fields are
masked recursively, protected files remain excluded, and text tails are read
with a bounded seek. Existing secret/URI/email sanitization remains active.

Remaining mutable identity terms are inventoried in `identity-dependencies.json`:
explicit migration conversion, bounded v2 import, historical payload readers,
and the temporary exact-alias HTTP adapter in `job_actions.py`. The latter is
removed at #479. Storage `location` and readable historical descriptors are not
job identities. No new job or dependent writer adds a mutable identity field.

## Qualification

Focused tests cover canonical/legacy encrypted imports, explicit target merges,
duplication, complete reference remapping, rejected partial bundles, secret and
cron rollback, exact/changed history confirmation, paired restore deletion,
blocked pending work, reset, health, support privacy, existing backup.conf-only
recovery, and executable DE/EN UI payloads. Local HTTP tests exercise real
handlers with synthetic files; normal/activity runner regressions use Borg 1.4.5.

There is no full installation restore endpoint to qualify. Its future
same-installation ID preservation and cross-installation collision/remap rules
remain specified in C6. #479 must qualify all startup/writer exclusion, migration
snapshot/apply/resume, real Unraid pages and the first installable test candidate.
