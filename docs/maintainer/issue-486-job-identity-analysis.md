# Job identity dependency analysis (#486)

Status: implementation on the isolated #486 branch; awaiting the maintainer test.
No live Unraid data has been migrated by the development agent.

## Baseline and use of #447

- Main reviewed: `3f4058ca4d8a9b947c46467706e4bbd0d4c31de5`, version `2026.09.07.0935`.
- Feature branch: `codex/issue-486-job-ids`. Keep one implementation PR unmerged
  until the maintainer completes the feature test.
- Reuse the original dependency inventory from #447/#471 at commit `9ac8715`
  (`docs/maintainer/identity-dependencies.json`) as a discovery checklist.
- Cross-check the frozen #447 inventory at `6e0261a` for subsequently discovered
  dependencies. Its implementation-specific modules and target behaviors are
  not requirements for #486.
- Source of authority: [#486](https://github.com/borgforge/borg-backup-ui/issues/486)
  and the maintainer's subsequent approvals. #447 remains frozen. Its code is not
  merged or cherry-picked into this branch.

A static scan of Main's application, API, runtime, UI and plugin sources finds
44 files containing the old identity tokens (`job_key`, `type_id`, `backup_type`
and their runtime/JavaScript variants). This is a candidate list, not a count of
files that must change. Some matches only describe a job or are unused helpers.
Activity-log capture and lookup are present on Main but were not in the original
#471 inventory; the later frozen inventory includes them.

## Starting records and path rules

The canonical starting objects are the existing JSON files under
`<data-root>/config/jobs/`, resolved by `jobs_api.get_jobs_meta_dir()` and
`repository_context.jobs_dir()`. Their current `job_key` and filename are mapping
evidence. `backup_type` plus location is secondary evidence to validate, not a
reason to guess that two records belong to the same job. Names alone are never
identity evidence.

For an installation whose data root is `/mnt/user/borg_backup_ui`, the canonical
job directory is `/mnt/user/borg_backup_ui/config/jobs/`. This is a path example,
not a read of the maintainer's current Unraid installation.

Resolve status, restore-test, weekly-snapshot, cache and log paths from the actual
configuration. They can live outside the data root. In particular, Main supports
both the configured/current weekly snapshot location and a legacy copy under
the status directory. Inventory both before normal readers can import or write
them. Preserve application-owned data and unrelated fields in every affected file.

## Persistent files: readers, writers and required identity work

Names below refer to existing Main functions. A function listed as a reader may
also cause a write through a helper; notable examples are called out explicitly.

| Existing store | Main writers | Main readers | Required work in #486 |
| --- | --- | --- | --- |
| `config/jobs/<job_key>.json` | `wizard_api.save_job()` through `repositories_api.save_job_repository_transaction()`; `BackupUIHandler._put_job_enabled()`; `restore_tests_api.update_restore_test_policy()`; `settings_transfer_api.import_jobs_bundle()` | `jobs_api._discover_jobs_uncached()` / `discover_jobs()` / `list_jobs()`; `wizard_api.load_job_for_wizard()`; `repository_context.load_job_metadata()`; direct readers listed below | Persist one UUID per job; address that job by UUID across reads and edits. Preserve all settings and unknown JSON fields, including policies, icons/colors and original timestamps. Persist the full current archive prefix and retain all prior prefixes. |
| `config/schedules.json` and managed root crontab block | `schedule_api.save_schedule()`, `write_schedules()`, `delete_schedule()`, `apply_all_schedules()`; import; existing orphan cleanup | `get_schedules()`; Jobs, Dashboard, notifications, widgets, report mail, wizard | Convert backup-job map keys and generated run requests to IDs. Keep expressions/enabled flags. The service key `restore_test` remains a service key. Finish conversion before orphan cleanup can inspect the new inventory. |
| `config/repositories.json`: `used_by`, `source_job_keys` | `save_job_repository_transaction()`, `_link_repository_to_job_locked()`, `_unlink_job_from_repositories_locked()`, `reconcile_repository_usage()`, import | `repository_assignment_report()`, `resolve_job_repository_context()`, `CheckManager._repository_command()`, repository/storage UI and health | Convert contained job references consistently. Preserve repository IDs, storage references, credentials, paths and statistics. Do not introduce a new repository model or rename fields solely for cleanup. |
| `STATUS_DIR/*.status`, and archived status files where configured/present | `BackupJob._save_status()`, `_save_skip_status()` -> `status.BackupStatus.save()`; `StatusStore.load(move_to_archive=True)` can move files | `BackupStatus.from_file()`, `StatusStore.get_latest_per_key()`; `status_api.get_status_data()`; `history_api.get_history_data()`; `reports_api`; report mail and widgets | Add IDs to unambiguous historical records, preserve their evidence and filenames, and write IDs on future runs. Select/group by payload ID rather than parsing names. Inventory archived copies without changing Main's retention or display coverage. |
| `weekly-snapshots.json` at configured/current and legacy paths | `status_api._auto_write_weekly_snapshot()`; `_import_legacy_snapshot_if_needed()` copies a legacy file | `_load_last_week_sizes()`, `_load_all_snapshots()`, `_load_previous_status_sizes()` | Remap the existing job-keyed arrays to IDs; preserve week/size observations and both original inputs. Handle ambiguous keys without silently merging or discarding values. No new weekly-observation schema. |
| `<restore-test-status-dir>/<job_key>.test` | `runtime/scripts/borg_restore_test.py: RestoreTest._write()`; explicit delete handler | `restore_tests_api.list_restore_tests()`, `list_restore_test_plan()`, `build_restore_verification_map()`, `_load_test_file()`; runtime test reader; widget readers | Preserve complete result payloads, test dates, validity, level, report details and archive references. Use IDs for lookup and ownership, including any necessary filename change. Policies remain in their existing job JSON. |
| `config/restore-runs.json` | `restore_api._persist_restore_runs()` from the existing async lifecycle | `_ensure_restore_runs_loaded()`, `list_restore_runs()`, `get_restore_state()` | Enrich existing run records with the job ID. Preserve the independent `restore_id`, selected archive, paths, state and recovery details. Do not treat an active operation as safe to rewrite while it is running. |
| `config/restore-history/index.json` and `runs/<restore_id>.json` | `_record_restore_history()`, `_history_summary_from_run()`, `_history_detail_from_run()`, `_write_history_index()` | `_read_history_index()`, `list_restore_history()`, `get_restore_history_detail()` | Keep the existing index/detail structure and restore IDs; update job references consistently in both. Preserve historical names, repositories, results and chronological order. |
| `config/notification-state.json` | `write_notification_state()`, `mark_reminder_sent()`, `clear_reminder_prefix()`, `cleanup_reminder_state()` | `read_notification_state()`, `reminder_allowed()`, reminder diagnostics | Remap only job identity in existing reminder keys. Preserve sent timestamps and due markers so migration does not reset reminders. |
| `config/notification-queue.json`, `config/notification-deliveries.json` | `enqueue_event_apprise()`, `_append_queue_item()`, `drain_notification_queue()`, `_record_delivery_status_unlocked()` | Queue drain, `read_notification_delivery_status()`, system health | Enrich/remap job references in pending events and delivery records where resolvable. Preserve event IDs, retry state, messages and delivery history. Do not send notifications during migration. |
| `config/runtime-recovery.json` | `record_runtime_stopped()`, `mark_runtime_restarted()`, `acknowledge_runtime_recovery()` | `read_runtime_recovery_state()`, `pending_runtime_recovery_entries()`, `summarize_runtime_recovery()` | Carry stable job attribution alongside existing recovery entries. Their entry IDs and Docker/VM targets are separate identities and remain unchanged. No new recovery workflow. |
| Widget cache, normally `/boot/config/plugins/borg-backup-ui/widget-status.json` | `write_unraid_dashboard_widget_cache()`, startup/status-file cache writers | Cache readers, `plugin/widget-status.php`, Unraid widget | Rebuild derived job references from migrated data after startup is safe. Preserve widget structure, labels and existing counters. This cache is not authoritative job/history evidence. |

Backup History does not have a separate canonical history database on Main:
`history_api` and `reports_api` read `.status` files. Restore History has the
separate index/detail files shown above. Updating only `config/jobs` leaves both
sets of consumers disconnected.

`status.SnapshotManager`, `status.RestoreTest` and `StatusStore.aggregate_by_key()`
contain older key-based helpers. The production-tree search found no external
call sites for these helpers. They are not a reason to add another live migration
path or modernize unused code. Verify call sites again when implementation changes
their callers.

## Functions that construct or decode the mutable identity

| Main function | Existing dependency | Required separation |
| --- | --- | --- |
| `wizard_api.validate_params()`, `generate_flow_preview()`, `save_job()` | Construct `type_id + '_' + location`; filename doubles as conflict/identity check | UUID owns the job. Validate the complete prefix independently, including the approved repository-scoped overlap rule. |
| `jobs_api._discover_jobs_uncached()` and its `_make_job()` helper | Read `job_key`; can synthesize `backup_type + '_' + location` | Read the persisted ID; preserve descriptive/default inputs independently. |
| `status.BackupStatus.key`, `status_api._status_key()` | Return/reconstruct `backup_type + '_' + location` | Read the ID from the record; do not recreate a second active identity after migration. |
| `history_api.get_history_data()` | Splits status filename into type and location; its `type` filter uses those parts | Read job ownership from payload. Preserve run descriptors and time ordering. Adapt actual job selectors to ID and name. |
| `reports_api._parse_job_key()`, `_parse_status_file_stem()`, `get_report_jobs()`, `get_report_data()` | Parse keys/filenames, reconstruct keys and filter timeseries by type/location | Group/select the same logical job by ID across renames and prefix edits. Preserve report calculations. |
| `BackupJob._send_notification_event()`, `_save_status()` | Build notification/reminder attribution from type/location; status save has a runtime-key fallback | Carry the ID from the admitted job run through status and notification writes. |
| `notification_reminder_api._latest_backup_status_by_key()` | Falls back to a constructed type/location key | Use persisted IDs for schedule/status/proof joins. |
| `archive_prefix.archive_prefix_from_job_key()` and `archive_prefix_from_backup_type()` | Turn mutable identity inputs into an archive prefix | Operational callers read the full prefix from job metadata. A migration-only derivation of the old actual prefix is allowed. |
| `restore_api._archive_filter_rows_for_restore_job()` | Combines type-derived, recorded and key-derived prefixes | Use the retained full current/previous prefixes of the ID-selected job. |
| `check_api.CheckManager._repository_command()` | Derives a prune prefix from the selected job key | Resolve the selected ID to its explicit current prefix and unchanged retention settings. Keep native Borg prune. |
| `wizard_runner._load_env_from_job()` | Uses type/location for cache directory, check flag, defaults, log name and lock name | Separate job/run ownership from operational data. Preserve existing cache/check references and effective settings across migration and prefix edits. |
| `BackupUIHandler._delete_job()` | Uses type/location file globs for optional status/log deletion and legacy secret guesses | Preserve confirmation and deletion scope; select owned job artifacts by ID/evidence. Do not broaden deletion or delete repositories. |
| `ui/js/pages/wizard.js: saveWizardJob()` | Reconstructs the key for a separate schedule request after saving the job | Use the ID returned by the save operation. |

## Other active consumers to update, not replace

- HTTP boundary in `borg_backup_ui.py`: job run/cancel/enabled/delete, schedules,
  wizard edit, report selection, repository maintenance, restore browse/precheck/
  execution, test policy/run selection, activity/live-log requests, and request
  context logging. Trace request JSON, query parameters and responses together.
- `JobManager.start()`, `get_state()`, `is_running()`, `stream_output()`;
  `active_resource_locks()`, `durable_running_states()`, `stream_job_output()`.
- `wizard_runner.main()`, `ResourceLockSet`, `job_control.JobControl` and
  `request_cancel()`: job ownership moves to IDs; resource IDs and independent
  run IDs retain their current roles.
- `activity_log.resolve_activity_run()` / `activity_log_path()`;
  `activity_log_capture.prepare_capture()`, `capture_record()`, `running_captures()`
  and `retain_capture()`. RAM state lives under `/run/borg-backup-ui/jobs/` and
  `/run/borg-backup-ui/activity-logs/`; retained logs use the configured log path.
  Do not rewrite live ownership files under running workers. Preserve readable
  retained logs and their recorded references.
- `repository_context.resolve_job_repository_context()`,
  `smb_mount._job_smb_meta()` / `ensure_smb_mount_for_job()`: resolve the same
  repository/storage by job ID without changing mount behavior.
- `runtime/scripts/borg_restore_test.py: discover_repos()`, `RestoreTest.test_repo()`
  and `_notify_event()`; API plan, verification, run and policy handlers. Preserve
  current test behavior; repairing the missing cron trigger belongs to #493.
- `status_api.get_status_data()`, `jobs_api.list_jobs()`,
  `report_mail_api._job_metadata_by_key()`, `_planned_job_keys_for_period()`,
  `_statuses_for_key_in_window()` and `_repo_growth_7d()`; reminder joins;
  `homepage_widget_api._read_jobs()` / `_read_latest_backup_rows()` and Unraid
  widget `_backup_rows_by_key()`, `_job_cache_items()`, `_read_static_jobs()`.
- Import/export: `export_jobs_bundle()`, `_job_preview_rows()`,
  `_resolve_import_key()`, `import_jobs_bundle()` and encrypted wrappers. Preserve
  existing export content and modes. Importing as a copy creates a new ID;
  updating an existing job keeps its ID. Old bundles without IDs need a bounded
  conversion at the existing import boundary, not a second permanent identity.
- `system_health_api._collect_job_health()`,
  `factory_reset_api._active_operation_blockers()`, and
  `support_bundle_api.create_support_bundle()`: adapt actual references/checks;
  retain existing reset semantics and full sanitized diagnostic content.
- UI consumers: `ui/js/core/app-core.js` and the `jobs`, `wizard`, `dashboard`,
  `history`, `reports`, `restore`, `restore-tests`, `storage` and `settings` pages.
  Inspect action attributes, selection values, lookup maps, import selections
  and name labels together. UUID values must not become visible sorting labels.

## Uses that must not be blindly replaced

- `backup_type` currently supplies fallback icons/colors, display descriptions,
  type-specific compression/retention defaults and some Docker/VM defaults.
  Preserve the effective values when removing it from identity. Do not put a
  UUID in these fields or infer their meaning from a UUID.
- Repository/storage/profile keys and Borg repository IDs identify different
  objects. Keep them and existing credential references unchanged.
- `runtime/lib/borg_runner.py: BorgRunner.create()` and `prune()` already accept
  an archive prefix. Change the value supplied by the job layer as needed; retain
  native `borg prune --verbose --list --show-rc` and current-prefix retention.
- `config_api._scan_per_repo_passphrases()` calls a descriptive filename fragment
  `type_id`; it is not an active job lookup. Preserve secret-file references.
- `storage_profiles_api.build_storage_repo_uri()` has no production-tree caller
  in the reviewed Main. Its argument name alone does not justify changing it.
- No source-manifest feature, replacement status/report schema, shortened support
  bundle, combined-prefix retention, migration assistant, or new page redesign
  is authorized by this analysis.

## Reuse Main's migration infrastructure

Use `api/migrations/registry.py: run_startup_migrations()` and the existing
`detect(config)` / `apply(config)` contract. Add one job-ID migration module to
that registry; do not import the migration subsystem from #447.

Reuse `api/migrations/audit.py` for state and JSONL audit, `inventory_store` for
existing atomic-write/lock primitives, and the snapshot pattern demonstrated by
`canonical_backup_conf_v1`. A multi-file migration still needs its own durable
old-key-to-ID assignment and progress information; a single atomic file write
does not make a set of writes atomic.

The existing startup sequence evaluates migrations before enabling normal
services. Reuse `_evaluate_startup_migrations()`, `startup_state`, and
`_activate_runtime_services()` for failure reporting and blocking. Ensure all
configured affected storage paths are ready before planning, and establish that
old backup/restore workers are no longer writing affected records. If existing
startup/process checks cannot provide this prerequisite, report that specific
gap before proposing any broader mechanism.

For the new migration:

1. Read source JSON directly, validate exact old keys and references, and resolve
   configured paths. Avoid normal readers that write, such as status snapshot
   generation, job-directory migration or repository reconciliation.
2. Preserve affected originals and persist the ID assignment before changing
   jobs or dependent records. An interrupted retry reuses the assigned IDs.
3. Enrich records and remap only necessary identity references. Preserve fields,
   existing prefix lists, evidence, timestamps and unknown historical data.
4. Verify active references. Preserve/report unresolved historical records without
   guessing or deleting them. Never declare success after a partial conversion.
5. Let normal startup regenerate cron and derived caches only after success.
   Existing orphan cleanup must not delete schedules mid-conversion.

## Focused checks to prepare

- Representative Main jobs: built-in/custom types, underscores in old keys,
  explicit and automatic icons/colors, multiple locations, multiple recorded
  prefixes, restore policies, enabled/disabled schedules and unknown fields.
- Linked `.status`, weekly observations, `.test`, restore index/detail records,
  repository references and notification state. Compare all original evidence.
- First migration, repeat invocation, interrupted write/retry, ambiguous history,
  duplicate active IDs and unavailable configured storage.
- Rename and prefix edit keep identity, schedules, history and test/check proof;
  future archive names use the full prefix. Exercise approved prefix conflicts.
- Use UUID/file order different from name order. Verify alphabetical job names
  within existing groups in every list/selector; preserve run chronology.
- Preserve native prune output, import/export behavior and support-bundle scope.
- Keep focus on #486: no implementation of #493 and no adoption of #447 extras.

The original analysis below establishes the baseline. Implementation and
copy-based migration validation are documented in the final section; the live
Unraid installation test remains the maintainer's next step.

## Supplied production copy: 2026.09.07.0935

On 2026-09-07 the maintainer supplied an unmodified production-data copy for
#486. The copied application's `APP_VERSION` confirms `2026.09.07.0935`.
Inspection used direct, read-only JSON parsing, not copied application code or
normal application readers that could write. No migration was executed during
this initial inventory; subsequent copy-only migration results are listed below.
Production payloads, configuration secrets and authentication data are not
included in this branch. A local ignored fingerprint manifest records the 671
JSON records read for the identity audit.

The actual job root in this copy is `/boot/config/borg-backup/config/jobs/`,
represented by `borg-backup/config/jobs/` in the supplied directory. Runtime
status, restore-test, log and cache paths are under `/mnt/user/borg_backup_ui`,
represented by `borg_backup_ui/`. Do not mistake `GLOBAL_DATA_DIR` for the
canonical job root. Main's `_apply_runtime_dirs_from_conf()` applies the paths
in canonical `config/backup.conf`; the older `STATUS_DIR` in the UI bootstrap
configuration is not the effective status path for these records.

| Store in the supplied copy | Observed baseline | Required preservation check |
| --- | --- | --- |
| Job metadata | 14 schema-v3 jobs, no `job_id`; unique keys; filenames, `job_key` and type/location pairs agree | Assign exactly 14 stable IDs; preserve all original settings and fields |
| Schedules | 11 backup schedules, 10 enabled; all keys resolve | Preserve expressions and enabled flags; the absent `restore_test` trigger belongs to #493 |
| Repositories | 13 repositories for 14 jobs; both reverse-reference lists match job assignments | Preserve the shared repository and all 14 assignments |
| Regular backup status/history | 568 `.status` files; all resolve to existing jobs and agree with their filenames | Preserve all results, check fields, timestamps, statistics and log references |
| Current weekly snapshots | 14 keys, 28 week/size observations; all resolve | Remap keys without changing the observations |
| Legacy weekly snapshots under `status/` | 17 keys, 107 observations; six keys with eight observations have no current job | Preserve unresolved history and both input files; do not silently merge or replace the current snapshot |
| Restore-test results | Six `.test` files; filenames and payload type/location agree with existing jobs; dates/results present | Preserve full reports and the existing proof, independent of whether the current policy is enabled |
| Notification delivery history | 200 records; 196 resolve, four refer to two absent jobs | Preserve all delivery records; do not guess the four historical owners |
| Reminder state | Three job-specific reminder keys | Preserve event names, due markers and sent timestamps |
| Cache/check markers | All 14 current jobs have their expected existing `.last_check_<type>` file | Continue to reference existing markers and caches after introducing IDs |

Important cases already represented by this copy:

- Eleven jobs have empty explicit icon and color fields. Their effective display
  depends on Main's type defaults; empty fields must not become a visual change
  when identity changes. Three jobs carry explicit icon/color selections.
- Ten jobs have no explicit prefix list, three have one entry, and one has two
  current/historical prefixes. Retain both entries of the latter. Two jobs share
  a repository; their current and recorded prefixes do not overlap. Identical
  prefixes across different repositories are present and remain permitted.
- The two weekly files have 11 shared job keys, with different arrays for all
  11. Main imports the legacy file only when the current file is absent; this
  migration must not introduce a new merge policy.
- The six unmatched legacy weekly keys and two unmatched notification keys do
  not exist in the current job inventory. Their eight weekly observations and
  four deliveries account for the previously reported unresolved-history
  diagnostics by store and count. That is historical missing ownership, not
  evidence that an active job is missing its new ID.
- Existing backup outcomes are 536 success, 19 skipped, nine error, three
  warning and one cancelled. Check status is already `unknown` in 19 records
  and `ok` in 549. Preservation tests must compare these original values rather
  than manufacture success or known check results.
- The status recycle directory also contains 69 `.status` files and four old
  restore-test files. Two status records and one test do not exactly match a
  current job key. Keep recycle contents separate from active history; do not
  revive them or infer ownership by case folding/name similarity.

Coverage gaps for synthetic fixtures, not missing production files:

- Restore runs, Restore History, the notification queue and runtime recovery
  are present but empty. Add synthetic nonempty examples from their existing
  Main schemas to test identity references without creating real operations.
- Add controlled prefix conflicts, ambiguous references, duplicate IDs,
  unknown fields and interrupted/repeated migration cases. The real copy does
  not demonstrate those failure/retry behaviors.
- Use deliberately different UUID and name orders for UI checks. Do not rely
  on the order of the current filenames as a sufficient sorting test.

This provided the input for representative migration fixtures. The implementation
validation below records the executable before/after checks; private source files
are not committed as test fixtures.

## Discarding the experiment and Unraid limitation

An unmerged feature PR can be closed without changing Main. This says nothing
about reverting an already installed test plugin or migrated persistent data.

Unraid does not provide the plugin downgrade assumed in the earlier planning
text. A migration snapshot protects data; it is not a plugin downgrade. Do not
promise reinstalling the older Main package as the normal return path, restore
old migration-state files as a substitute, or invent a rollback feature in #486.
Corrections to an installed test version use a corrected version and documented
data repair where necessary. Any separate installation recovery would require
its own concrete plan and authorization. Test data copies first.

## Implementation and test candidate (#486)

The implementation uses one new registered migration, `job_ids_v1`, after the
existing canonical inventory migrations. It assigns each job a UUID, stores
`job_id` and the existing API field `job_key` with that UUID, and renames job
metadata to `<UUID>.json`. Main's public API structures and page layouts are
retained. The full editable current prefix is `archive_prefix`; existing
`archive_prefixes` remains the prefix history used by Browse & Restore.
`backup_type` remains descriptive and preserves automatic icon/color and
runtime defaults, but is no longer used as the job's identity.

Migration preserves unknown job fields, existing status filenames, status and
check values, restore-test results/report IDs, weekly observations, timestamps,
and repository assignments. Restore-test files become `<UUID>.test`;
notification/restore stores and schedule keys are converted without discarding
unresolved historical entries. Conflicting historical evidence is retained and
recorded for review rather than claimed by an active job. Invalid active
references block startup before the first data change.

`cache_subdir` and `check_flag_name` preserve the exact previous cache/check
location for migrated jobs. New jobs receive an ID-specific cache location.
These references stay stable when names and prefixes change. Borg still handles
pruning once for the current prefix, with its existing verbose output; older
prefixes remain available for restore, as on Main.

### Data preservation and recovery

Before replacing any input, migration stages complete originals and proposed
files under `<data-root>/config/migration-backups/job_ids_v1-<run-id>/` and
persists `config/job-id-migration.json`. The journal records the UUID assignment,
source/target filenames, before/after SHA-256 checksums, timestamps and actions.
The existing migration JSONL log and central failure gate are reused.

If interrupted, startup resumes the same journal and IDs. A file modified since
the snapshot causes a failure rather than being overwritten. Do not delete or
edit the journal to force another migration. Preserve it, the matching snapshot
and the migration audit log when diagnosing a failure. Restore an individual
original only with the plugin stopped and after checking its journal entry and
checksum; record the exact files and reason. A partial/manual restore is not a
completed migration and must not be used to bypass the startup gate. Use a
corrected plugin version for code fixes. The snapshots do not downgrade Unraid
or the installed plugin.

### Validation performed during implementation

- Migration tests cover field preservation, repeat execution, interrupted
  replacement/rename, changed input on retry, unavailable storage, active
  workers, conflicting active references and ambiguous history.
- Integration tests exercise name/full-prefix editing, unchanged IDs/schedules,
  cache/check references, history/report/restore joins, alphabetical job lists,
  complete support-bundle job records, old/new exports and import conflicts.
- Prefix tests include historical prefixes and overlapping Borg selections in
  one repository, allowed reuse by the same job, and separate repositories.
- Runtime, native prune, notification, repository and UI tests retain their
  existing behavioral assertions with canonical UUID fixtures.
- Local browser review uses synthetic data and real API readers; it does not
  start backups or install anything on the maintainer's server.
- A private copy of 598 relevant supplied files was migrated: 14 jobs and 594
  converted files. Settings, status/check/restore payloads and weekly values
  were compared against the originals. A repeat invocation made no changes.
  The 598 input files on the supplied share were verified unchanged afterwards.
  Ten unresolved historical references remain: four notification deliveries
  and six weekly keys (containing eight measurements), as identified above.

The remaining maintainer acceptance checks on Unraid are still required. Keep PR #494
unmerged until that test is accepted. Stable release promotion remains separate.

### Maintainer findings on test version 2026.09.07.1400

On Unraid the job-ID migration completed successfully at 14:14:16, following
startup at 14:10:34. Repository assignments had no errors, schedules were applied,
and the web server started at 14:14:17. This confirms the live migration step;
the remaining acceptance checks below are still pending. The 3m42s startup wait
had no progress messages. A limited start-log progress proposal awaits approval.

The repository maintenance confirmation still derived its displayed archive
filter from the UUID. The backend already used the stored full archive prefix.
The correction reads `archive_prefix` in the dialog, prefers the selected job's
current name, sorts retention sources by name, and removes the former type/location
fallback for job ownership. Browser-logic tests cover German and English, selected
source changes and UUID submission. A local browser check confirmed the dialog
and filter changes without executing maintenance.

### Maintainer test on Unraid

1. Keep the supplied original data copy; install the verified test-channel
   package on the existing Main data with the array/pools available and no
   backup/restore worker running.
2. Confirm the existing migration status reports success and all 14 jobs remain
   present, with their icons, colors, schedules, histories and restore/check
   evidence. Check the complete job JSON in a new support bundle.
3. Restart the plugin once: the same IDs must remain, without a second conversion.
4. Rename a selected test job and change its full prefix. Its ID, old history,
   restore evidence, schedule and cache/check reference must remain attached.
5. Run that test job: inspect the new archive prefix and native verbose prune
   output. The new status/history entry must use the same job ID.
6. Check prefix conflicts in a shared repository and allowed equal prefixes in
   separate repositories. Verify alphabetical names in existing job groups,
   and the ID in Edit Job and expanded History details.
