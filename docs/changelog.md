# Changelog

Historische Release- und Entwicklungsnotizen fuer borg-backup-ui.

Das Plugin-Manifest `borg-backup-ui.plg` enthaelt nur noch eine kurze nutzerrelevante Zusammenfassung des aktuellen Stands.

## Unreleased

### Issue #479 (final integration for #447; awaiting test-channel qualification)
- Added read-only startup detection, cross-process writer admission and a German/
  English administrator assistant with separate preparation and conversion actions.
- Included configuration normalization in the same immutable UUID plan, verified
  exact-file snapshot and protected download; acknowledgement never starts apply.
- Added crash-consistent per-file publication, original-plan continuation,
  authenticated state gates and final reference/cron verification before startup.
- Covered detached backups, capture, restore/check/key deployment, notifications,
  maintenance workers, background refresh and safe maintenance diagnostics.
- Added complete synthetic migration qualification, actual Borg backup/restore,
  interrupted-run/restart tests and protected HTTP export/approval tests.
- Removed active HTTP job-key adapters. Historical aliases remain preserved in
  migration and bounded legacy import; normal operations require immutable IDs.
- Corrected settings profile usage to count distinct UUID jobs and show current
  names, and qualified existing wizard, keyfile, logging and storage regressions
  with canonical job inventories and explicit validated-startup fixtures.
- Give migration maintenance priority over first-run setup, close an already-open
  setup dialog and prevent delayed responses from reopening it. Fresh installs
  retain the normal required setup flow (#479).
- Stable promotion remains a separate decision after volunteer/maintainer testing.
- Accept the shipped restore-test type/location descriptors during identity
  migration and retain canonical report snapshots after subsequent tests/restarts.
  Show immediate preparation feedback, retain safe failure details through
  readiness polling, and group/explain diagnostics in German and English (#447).

- Read migrated restore proof from its recorded repository and tested archive,
  keeping native snapshots authoritative and rejecting mismatched ownership.
  Share this evaluation with scheduled restore tests without rewriting reports.
  Use only recorded test dates so migration file timestamps cannot renew proof.
- Preserve recorded legacy check values with explicit historical target scope.
  Distinguish missing or changed restore targets from expired proof in dashboard
  summaries and show readable explanations alongside retained dates.
- Keep migrated-run provenance only in expanded history details, and lay out
  available identity fields without empty cells. Explain separate status/report
  files in both migration guides (#447).
- Restore complete sanitized job/configuration diagnostics in support bundles,
  including source paths, exclusions, prefix history and policies. Export full
  structured run/restore JSON instead of unreadable text tails; document oversized
  or unreadable files explicitly and keep credentials/recovery data excluded.

- Preserve automatically selected job icons before removing legacy type fields.
  Materialize the previous list color using the existing palette when a different
  explicit icon otherwise loses its automatic color.
  Repair unchanged migrated jobs only from verified original migration evidence,
  retaining explicit appearance choices and later edits with an auditable result.
- Derive icon styling from the configured icon throughout dashboard, restore,
  restore-test, report and repository views. Sort job selectors by location and
  localized natural name order; show readable prefixes instead of UUID subtitles.
  Restore-test plans now include current prefix and description (#447).
- Restore detailed combined-retention logs: prefix scope and policy, repository
  and matching archive/checkpoint counts, each winning keep rule, explicitly
  planned removal candidates and success/warning/failure completion. Keep archive
  names, local timestamps and full IDs available for diagnosis (#447).
- Read Borg's naive JSON inventory timestamps in UTC and select calendar buckets
  in the local timezone. Match Borg's ascending-sort-then-reverse tie ordering;
  qualify local midnight and DST transitions against the shipped Borg binary.
- Recognize successful Borg-delete output in manual prune results without
  treating planned or unsuccessful deletions as completed removals (#447).

### Issue #478 (integration work for #447; not released)
- Added versioned ID-based job transfer with explicit new/merge/skip choices,
  complete selected reference maps, bounded v2 conversion and protected-file
  transactions with metadata/schedule/cron rollback.
- Added content-bound history deletion previews, retained repository-owned
  secrets and blocked deletion while pending work still references the job.
- Centralized owned-store/reference diagnostics, reduced support configuration
  exposure and covered ID stores/runtime controls in guarded factory reset.
- Kept settings recovery scoped to backup.conf as required by the approved C6
  contract. Complete installation recovery remains a future conditional feature.
- Added canonical/legacy transfer, lifecycle, privacy, reset and DE/EN UI tests.
  The migration and first installable test candidate remain gated on #479.

### Issue #477 (integration work for #447; not released)
- Converted Browse & Restore, prechecks/downloads and restore-test invocation to
  full job IDs and literal current/historical prefixes in the current repository.
- Captured restore start contexts and persisted readable run snapshots; retained
  terminal state for history-write retry without losing active runs to trimming.
- Converted restore-test plans, policies, results, proof and notification/reminder
  ownership; scheduled tests honor each job's captured level and interval.
- Limited the tested archive to the job's prefix union and retained proof across
  name/current-prefix changes; other repositories require a new proof.
- Added canonical API, DE/EN UI, real Borg restore/proof and migration regressions.
  Transfer and guarded activation remain #478/#479; no test package yet.

### Issue #476 (integration work for #447; not released)
- Made configured UUIDs authoritative for dashboard, widget, history and report
  navigation; disabled and deleted/unassigned history do not inflate active counts.
- Preserved historical payload descriptors and legacy continuity until the first
  native run. Runtime ownership takes precedence over completed-run outcomes.
- Added canonical weekly observations with provenance, preserved conflicts and
  repository-scoped growth; normal reads never perform a legacy conversion.
- Scoped restore proof to UUID and the recorded target, retained reminder keys
  across renames, and invalidated legacy widget aggregates.
- Added DE/EN navigation/counter tests and canonical status, weekly, mail and
  HTTP regressions. Restore, transfer and guarded activation remain #477-#479.

### Issue #475 (integration work for #447; not released)
- Added immutable UUID run contexts for manual/scheduled backup execution, exact
  prefix creation, status/log lookup, cancellation, recovery and notifications.
- Preserved start-time configuration, RAM activity-log capture and existing
  cache directories; repository changes do not reuse another target's check flag.
- Added one shared prefix-union retention engine, verified against the bundled
  Borg 1.4.5, and replaced the manual multi-prefix guard from #474.
- Serialized concurrent starts/stale resource recovery; payload IDs and process
  start tokens identify owners, and cancellation stays independent of retention.
- Added canonical runtime/real Borg regression coverage. Reporting, restore,
  transfer and final startup/migration activation remain #476-#479 work.

### Issue #474 (integration work for #447; not released)
- Converted job discovery, configuration actions, repository assignments and
  schedules to UUID job IDs; editable descriptors no longer rename identity.
- Validate all active references before writes; preserve schedule bytes on
  job edits and roll back ordinary metadata/repository/cron failures.
- Reconciliation and schedule reads report invalid references without repair
  or automatic deletion. Cron sends job_id and preserves disabled settings.
- Added a bounded deprecated HTTP alias adapter, current UI labels and tests
  for configuration rename, storage changes, rollback and concurrent updates.
- Runtime execution, combined-prefix retention, historical artifact cleanup
  and full startup activation remain guarded follow-up phases (#475-#479).

### Issue #473 (integration work for #447; not released)
- Added strict schema-v4 job validation, UUID-named metadata and canonical
  create/edit/duplicate operations, retaining unexposed operational settings.
- Replaced Type ID in the wizard with the complete archive prefix, an exact
  timestamp-pattern preview and retained prefix history in German and English.
- Wizard requests use job_id; schedule save retries reuse the returned ID.
  Added stale-editor detection and strict repository ownership checks.
- Legacy/corrupt inputs are rejected without implicit conversion. UUID runtime,
  scheduling, general inventory APIs and the startup migration gate remain
  subsequent phases; no independently installable package is produced.

### Issue #472 (integration work for #447; not released)
- Added an inactive, read-only migration inventory and UUID planner with exact
  legacy-reference mapping, archive ownership checks and preserved history.
- Added private persisted plans, checksummed snapshots, a chained audit journal
  and fail-closed preconditions. Retries retain the original UUID allocation.
- Added real-file fixture, failure and integrity tests. Startup registration,
  installation-data conversion and test-channel publication remain deferred.

### Issue #471 (integration work for #447; not released)
- Defined the immutable job identity, migration safety and legacy-data contract.
- Added a source dependency inventory and synthetic migration fixtures with
  reusable integrity assertions. No runtime migration is enabled in this phase.

### Issue #463 - file activity log performance
- Capture stdout and stderr directly in a RAM-backed runtime file only for jobs with file activity enabled, avoiding an unbounded API-process line buffer and writes into backed-up log directories during the run.
- Retain the complete log only after the runner exits, using an independent supervisor that survives a WebUI restart. Preserve cursor identity across the copy, release RAM after successful persistence, and keep a downloadable RAM copy with a visible error if saving fails. History/status references point at the final path.
- Preserve the existing API line counter with one independent blockwise reader, including a final line without a newline.
- Preserve the effective option for manual and scheduled runs and in resource locks used after an API restart.
- Load bounded UTF-8 file windows on demand, retaining at most three windows in the live view. Serialized requests provide backpressure; earlier output stays accessible in the complete file.
- Add bounded streaming downloads and stale-response cancellation. Existing compact logs continue to use the original SSE viewer.
- Coalesce small live updates into bounded blocks before evicting older output, keeping the viewport filled after burst output slows down. Remove the in-panel search and use theme colors for the navigation toolbar.
- Preserve live following across delayed programmatic scroll events, cursor catch-up, background tabs, and job-grid refreshes. Track the actual restored scroll position instead of suppressing all scroll events for one animation frame, and label previous/next section navigation explicitly.
- Show a warning badge for activity runs that the runner completed with Borg exit code 1; preserve failure, skip, and cancellation states.
- Cover a million-line round trip, Unicode boundaries, search boundaries, run recovery, direct process capture, access control, and UI navigation races.

### Issue #458
- Clarified in the Job Wizard and both manuals that Borg retention values count time periods rather than archives per period.
- Added the effective retention policy to the flow preview and made Repository Maintenance describe the maximum restore points per period.
- Rejected retention policies where daily, weekly, monthly and yearly values are all zero, while keeping zero valid for individual tiers.

### Issue #389
- Renamed the read-only restore source field to Archive path, removed its required-field marker and added the selected repository and archive as separate context in the target step.

### Issue #370
- Added first-use browser language detection for German and English, with English as the default for unsupported or unknown browser languages.
- Changed user-visible plugin install and service startup messages to English for international Unraid users.

### Issue #368
- Stopped adding a persistent Borg Backup UI autostart block to `/boot/config/go`; updates now remove the old block while keeping service startup in the plugin flow.

### Issue #365
- Updated the bundled BorgBackup 1.x stable binary from 1.4.4 to 1.4.5.

### Issue #292
- Normalized nested Settings cards so the Restore settings tab uses the same redesigned card surface as the other settings areas in light and dark themes.

### Issue #291
- Fixed Config Backups & Rollback so backup.conf snapshots are sorted and displayed by snapshot creation time instead of the copied source file modification time.
- Added metadata and filename fallback handling for older backup.conf snapshots, renamed the visible timestamp column to Created and clarified the German reason column as the snapshot trigger.
- Added a visible Config Backups & Rollback snapshot when `canonical_backup_conf_v1` rewrites backup.conf, using `canonical_backup_conf_v1 applied` as the trigger.

### Issue #289
- Added Repository settings for automatic repository info refresh, including enable/disable, interval and retry controls, worker status, next-run visibility and cached per-repository details.
- Replaced the hourly repository-info polling loop with a scheduled next-run worker so Borg info/list are not triggered merely to check whether work is due.
- Kept manual Repository Manager info refresh unchanged while the Settings status view reads only cached metadata and does not execute Borg commands.
- Moved the settings area to Operations > Repositories, grouped cached repository details by location and toned down the summary layout.
- Classified temporarily unavailable USB/SMB mount targets as warnings so they do not trigger the short failed-refresh retry interval.
- Refined the Repositories settings placement, worker status labels and grouped table layout, including display normalization for existing SMB/USB mount errors.
- Replaced the repository refresh enablement checkbox with an immediate-save switch.

### Issue #284
- Added consistent required-field markers to the Job Wizard, Restore Wizard, Repository Manager, profile settings, Apprise profile editor, user creation and confirmation dialogs.
- Kept optional fields unmarked and wired conditional repository passphrase state so encryption `none` does not show a required passphrase marker.

### Issue #283
- Removed direct SMB mount controls from the Job Wizard so job creation only selects storage targets and repositories already present in the canonical inventory.
- Kept manual SMB mount and unmount actions in Settings > SMB Profiles, and left repository creation/import responsible for direct storage access when needed.
- Added a visible compatibility note to repository imports, explaining that Borg Backup UI uses the bundled Borg 1.4.x runtime and that existing repositories must be verified after import.
- Preserved backend SMB job mount metadata defaults for existing jobs and runtime execution while no longer exposing those controls during job creation.

### Issue #282
- Improved the weekly HTML report layout before beta by grouping jobs by location, preferring user-facing job names and keeping archive names as secondary context.
- Added a weekly activity view that renders scheduled jobs as a seven-day status matrix and separates manual or unsupported custom-cron jobs from schedule-based missed-run evaluation.
- Limited the report header period and stale-run issues to the displayed seven-day report window, and kept manual jobs out of the issue summary.
- Replaced the duplicate seven-day run and success-rate columns in job details with a seven-day repository growth column while keeping file counts visible.

### Issue #264
- Removed the native ntfy API module, direct ntfy delivery client and native ntfy dispatch plumbing before the beta baseline.
- Renamed reusable notification message builders away from ntfy-specific names while keeping Apprise, mail, restore-test and reminder message formatting intact.
- Removed pre-beta native ntfy cutover and NTFY event migration modules and their native-only tests from the active codebase.
- Removed internal pre-beta data-model, repository, storage, restore-history, source-path and SMB-protocol migration modules from the beta startup baseline.
- Removed successful historical entries for retired pre-beta migrations from System Health & Migration while still showing failed, blocked or pending entries.
- Limited ordinary completed migration history for active/future migrations to the latest five entries while always keeping failed, blocked or pending entries visible.
- Documented the beta as the new initial supported state for notification and migration behavior.

### Issue #255
- Added a durable background queue for Apprise event delivery so provider network calls no longer block backup, restore-test or reminder processing.
- Queued Apprise notifications keep per-profile retry/backoff settings, survive application restarts and write sanitized delivery status to `config/notification-deliveries.json`.
- System Health and support bundles now include sanitized Apprise delivery status without exporting queued notification bodies or provider secret URLs.

### Issue #263
- Fixed the canonical storage profile migration so legacy SMB profiles with invalid old mount paths are normalized to the managed `/mnt/borg-backup-ui/smb/<profile-key>` path instead of failing startup migration.

### Issue #262
- Test and stable manifests now render a checksum-aware package installer that reuses a valid local package, skips reinstalling an already registered identical version and prints explicit progress messages before download or `upgradepkg`.
- Apprise is now packaged as a deterministic, SHA256-verified vendor bundle. The expanded `runtime/vendor` tree is no longer owned by the plugin package and is only refreshed on install when the Apprise version or bundle hash changes.

### Issue #256
- Added a dedicated Settings > Notifications area with Apprise profile overview, editor, duplication, enable/default state, event selection, validation, test delivery and deletion.
- Added searchable Apprise provider selection from the bundled runtime metadata while preserving the generic Apprise URL fallback.
- Compacted saved Apprise profile details outside edit mode and added dynamic provider URL templates and token hints from Apprise metadata for all providers.
- Added provider-specific URL field generation from Apprise templates. Non-secret URL fields and the selected template are stored with the profile, while password/token fields stay write-only and can be replaced during edits.
- Exposed all provider URL formats in the Apprise URL-format selector so ntfy password/token templates are selectable even when they appear after the compact help examples.
- Simplified saved Apprise profile summaries and suppressed duplicate provider labels when Apprise reports the same service name and schema.
- Enabled Apprise profiles to receive their selected backup, restore-test and overdue reminder events, using the profile display name as the notification title prefix.
- Added a startup cutover migration from native ntfy settings to an Apprise `ntfy` profile, removed native ntfy from the Settings UI and dropped native `NTFY_*` keys from the canonical backup configuration schema.
- Fixed migrated Apprise ntfy profiles so the editor reopens the matching URL format and provider fields instead of falling back to the first ntfy template.
- Removed the persistent ntfy migration hint from the Notifications settings area now that the cutover is handled automatically.
- Cleaned up notification event logging so delivered Apprise profile names are listed and the inactive native ntfy channel no longer appears in normal Apprise-only summaries.
- Updated German and English help/manual sections for the separate notification area and write-only Apprise URL secrets.

### Issue #258
- Added the canonical Apprise notification profile store with protected write-only URL secrets, atomic writes and cross-process locking.
- Added profile CRUD, validation, test delivery and provider discovery API helpers.
- Extended diagnostics to include sanitized Apprise profile metadata and permission checks for `.apprise-profile-*` secret files.

### Issue #257
- Added a hash-pinned Apprise dependency lock and package-build vendor step for `runtime/vendor` without runtime `pip` usage on Unraid.
- Introduced a provider-neutral Apprise adapter that loads only the bundled runtime, discovers supported providers and supports controlled validation/test delivery.
- Guarded provider discovery with a bounded timeout so Apprise provider metadata cannot block diagnostic or future UI flows indefinitely.

### Issue #248
- Restore tests now preserve repository encryption metadata and run repositories configured with `none` without a passphrase file.
- Encrypted repositories continue to require their configured passphrase file.

### Issue #246
- Bound the full preflight result to the exact pushed source commit.
- Build test packages from an exported staging tree with embedded provenance.
- Promote the exact tested package to stable without rebuilding it.
- Replaced mutable pending manifest notes with committed release-note fragments.
- Added a dedicated artifact-only preflight for stable release PRs.

### Issue #216
- Required startup migration failures now place the application in an explicit restricted maintenance mode instead of continuing normal processing.
- Repository reconciliation, schedule application, notification reminders and repository information refresh remain disabled until a later clean restart completes all migrations successfully.
- Operational and configuration-changing API requests return a clear maintenance response after normal authentication and role checks, while login, version, system health, migration diagnostics and support bundle creation remain available.
- A global bilingual UI notice identifies the failed migration and directs administrators to System Health & Migration; migration detection, application and runner failures are recorded without exposing secrets.
- Restricted navigation now keeps only Settings and Help available, replaces raw HTTP 503 states and endless loading indicators with a maintenance explanation, and marks the sidebar state as critical.
- System Health & Migration now shows the failed migration, failure phase, masked technical cause and prioritized recovery guidance while support bundle creation remains available.
- The startup registry now validates every migration detection and apply result, attributes contract violations to the exact migration phase, and blocks all later migrations after the first failure.
- Migration recovery documentation now distinguishes protected configuration snapshots from unsupported automatic plugin downgrades.

### Issue #242
- Replaced the German and English user-manual screenshots with current light-theme captures from the present UI and restored the numbered guide callouts.
- Updated the manual to show the current Repositories workspace and removed the obsolete standalone Storage screenshot.
- Sanitized environment-specific SSH profile values in the packaged documentation assets.

### Issue #238
- Running backup jobs can be cancelled cooperatively from the Jobs page. Active Borg processes receive SIGINT, Docker/VM stop phases finish before automatic recovery, and recovery failures remain visible as errors.
- The Jobs page keeps cancellation controls synchronized with the active backup phase and aligns running-job actions consistently without wrapping controls into unrelated columns.

### Issue #239
- Restore Tests now opens and reconnects the live log when a running test is detected during page load or refresh, not only after a conflicting start request.

### Issue #236
- Rebuilt the in-app help as a searchable bilingual operational guide with a generated table of contents, structured callouts and direct topic navigation.
- Expanded the German and English user manuals to cover the current menu order, roles, repositories, jobs, restore workflows, settings, troubleshooting, FAQ and operational best practices.
- Made the complete language-specific user manuals available offline inside the application alongside the concise quick help, with shared search and chapter navigation.
- Fixed help search chapter grouping so matching chapters and their navigation entries are visibly filtered instead of only updating the result count.
- Fixed a browser document-name collision that left the rendered help content empty after its table of contents had loaded.
- Added annotated guide images with numbered callouts plus a prioritized review of contextual-help and UI wording improvements.

### Issue #231
- New jobs, passphrase and profile-secret exports use a versioned authenticated encrypt-then-MAC envelope instead of unauthenticated AES-CBC alone.
- Wrong passwords, tampering and truncation are rejected before import data is written, without exposing cryptographic details or secrets.
- Failed preview attempts now show actionable password, integrity or format errors and invalidate any previously loaded preview and import payload.
- Existing AES-CBC exports remain explicitly importable as a visibly marked legacy format; every new export uses the authenticated format.

### Issue #230
- Backup finalization now attempts Docker recovery, VM recovery, status persistence and lock release independently, so one cleanup failure cannot skip the remaining safeguards.
- Runtime recovery failures force a failed backup result while preserving an original backup exception as the primary error.
- Cleanup diagnostics identify the failed phase without copying exception details that could contain credentials into the log.
### Issue #228
- Added a dedicated read-only summary endpoint for Homepage dashboards with backup, restore-verification, overdue and active-run status.
- Homepage uses a separately managed widget token that cannot access the general Borg Backup UI API and is stored with restricted file permissions.
- Settings can create, rotate or revoke the widget token and provide a ready-to-copy Homepage Custom API configuration.
- Widget responses use local cached state only and omit repository paths, logs, raw errors, user data and secrets.

### Issue #223
- New and migrated SMB profiles use automatic modern SMB 2/3 protocol negotiation instead of forcing SMB 3.0.
- Administrators can still select SMB 3.1.1, 3.0, 2.1 or 2.0 explicitly; SMB1 is rejected and never used as an automatic fallback.
- SMB profile tests, backups, restores and restore tests now share the same protocol policy and provide actionable network, share, authentication, permission and protocol diagnostics without exposing credentials.

### Issue #185
- New users now follow the browser or operating-system theme instead of defaulting to dark mode.
- Existing explicit light, dark or system preferences remain unchanged.
- Secondary dark-theme text uses a WCAG-readable contrast token across shared UI components.

### Issue #214
- Backup runs now fail before Docker or VM shutdown and before Borg maintenance when any configured source path is missing.
- Failure status records include the stable `required_source_paths_missing` code and list every missing path with a corrective action.
- Existing USB, SMB and parity skip behavior remains unchanged.

### Issue #218
- Repository check, data verification, prune and compact now wait up to 30 seconds for transient Borg lock contention.
- Added a privacy-safe troubleshooting procedure for persistent repository locks without automatic lock removal.

### Issue #215
- VM restart recovery now validates only the VMs stopped by the current backup job.
- Failed VM restarts remain visible as open runtime-recovery entries and identify the affected VMs.

### Issue #196
- Static UI assets are now restricted to the resolved UI directory, including symlink and traversal containment checks.
- Job logs, restore-test logs, restore downloads and repository-check streams now use the central API authentication and role policy.
- Existing unreadable or malformed user stores fail closed with a service-unavailable response instead of reopening administrator bootstrap or disabling authentication.
- Added focused security regressions and a local user-store recovery procedure.

### Issue #206
- Job source paths are now persisted and transported as JSON arrays, so spaces remain part of a path instead of being interpreted as separators.
- Added an audited, idempotent schema migration with a rollback backup for existing jobs and a clear failure state when a legacy value cannot be converted unambiguously.
- Job imports upgrade old source-path metadata only at the import boundary; normal Wizard, health and backup runtime paths no longer contain a legacy string fallback.

### Issue #205
- Repository creation and import now classify local target paths before submission and return actionable conflict messages for existing Borg repositories, non-empty foreign directories, missing import targets and inaccessible paths.
- Failed repository creation restores or removes newly written passphrase material, and known `borg init` target conflicts no longer surface as generic internal server errors.
- Editing a backup job now preloads its enabled state and daily, weekly, monthly or custom schedule instead of showing misleading defaults; schedule persistence failures remain visible in the open Wizard.
- Previously validated Job Wizard steps are keyboard-accessible and can be selected directly without allowing required or conditional steps to be bypassed. The Repository Wizard remains sequential.

### Issue #208
- Borg operations now use one shared SSH transport configuration across backups, repository maintenance, restores and restore tests.
- SSH keys no longer replace the configured keepalive options; interrupted WAN or SSH connections are classified consistently.
- Repository checks and restore tests now explain that a connection interruption leaves the operation incomplete without automatically implying repository damage.

### Issue #186
- Existing repository imports can browse directories inside the selected Local, USB, SMB or SSH/Storagebox target.
- The browser stays anchored to the canonical storage target, supports nested folders and preserves manual relative-path entry.
- Already managed repositories and unsupported repository path names are visible but cannot be selected for another import.
- Absolute paths, traversal segments and symlink escapes are rejected server-side; temporary SMB mounts are cleaned up after browsing.

### Issue #187
- The Repository Manager now only selects storage targets that were configured and tested centrally under Settings.
- Duplicate Local, USB, SMB and SSH storage-target creation fields and logic were removed from the repository wizard.

### Issue #203
- Dashboard backup rows are grouped by storage location in the established Local, USB, SMB and Storagebox order, matching the Jobs workspace.
- The redundant per-row location column was removed to provide more room for run, restore and storage details.

### Issue #202
- Job Wizard Docker and VM selection lists keep wheel, touchpad and touch scrolling inside the modal instead of moving the application page when a list boundary is reached.
- Appdata and VM safety acknowledgements now use a compact inline layout, and the duplicated runtime heading was removed to leave more room for long container and VM lists.
- The application page is locked while the Job Wizard is open; only the Wizard body or its nested selection list can scroll.

### Issue #143
- Canonical global configuration ownership:
  - `backup.conf` now contains exactly the active global keys declared by the installed runtime schema.
  - Obsolete storage and repository settings are removed by the audited `canonical_backup_conf_v1` startup migration instead of remaining as inactive compatibility data.
  - `storages.json` and `repositories.json` are the sole runtime authorities for storage targets and Borg repositories; `settings.json` and persistent schema copies are no longer runtime inputs.
  - Settings writes, restore-test configuration and SMTP defaults now use the same version-owned schema and reject unsupported keys.
  - Migration snapshots, atomic writes, verification, rollback and maintenance-mode handling protect existing installations during the cutover.
  - Repository archive lists, background information refreshes, tests and maintenance now explicitly confirm access only for repository objects marked as unencrypted, while Borg's safety prompt remains active for unknown repositories.

### Issue #199
- Backup jobs can define multiple concrete file or directory exclusion paths in the Job Wizard.
- Exclusions must exist below a selected source root and are passed to Borg as safe path-prefix patterns.
- Existing jobs remain unchanged with an empty exclusion list; edit, preview and runtime logs show the configured exclusions.
- Job Wizard step 2 now presents sources/exclusions and backup target side by side without reserving space for hidden autocomplete results.

### Issue #198
- Added a guarded factory reset as the final entry under Settings > Maintenance.
- Reset requires four risk acknowledgements, the exact server name, the current administrator password and the phrase `FACTORY RESET`.
- Running jobs, restores, restore tests and repository maintenance block reset; managed repositories inside a deletion root also block reset.
- Active-operation blockers are deduplicated and shown with one localized, user-readable reason instead of repeated internal operation identifiers.
- Application configuration and operational data are removed, schedules are cleared and the initial directory layout is recreated without deleting Borg repositories or plugin installation files.
- Reset execution is recorded in a protected JSONL audit log without secrets.

### Issue #197
- Test-channel manifests now open the existing Borg Backup UI control panel below Unraid Settings when the plugin icon is selected.
- Stable promotion copies the tested Settings launch target into the separate release PR.

### Issue #195
- Job Wizard repository selection:
  - Repository options now show the human-readable repository name with its effective repository path instead of three unlabeled values.
  - Redundant confirmation lines below valid storage and repository selections were removed; both areas remain available for missing-selection warnings.
- Canonical storage validation and migration diagnostics:
  - Local storage profiles reject broad, unsafe or malformed paths such as `/mnt//backup` before saving instead of silently dropping or normalizing the entry.
  - The canonical baseline migration validates Local, USB and SMB paths and rolls back with an audited error when malformed legacy input is encountered.
  - German and English System Health terminology and operator documentation describe the canonical inventories and recovery path consistently.
  - Repository workspace responses now derive the complete Local, USB, SMB or SSH path from the canonical storage target and relative repository path, so headers and details no longer show an empty repository path.
  - Support bundles no longer synthesize a misleading `settings.sanitized.json`; canonical storage and repository inventories are included directly.
  - Removed unused `settings.json` compatibility facades and the obsolete unregistered storage-path migration from normal runtime code.
  - Transitional repository path and profile fields are readable only by the baseline migration phases; normal runtime inventory reads enforce the canonical repository contract.
  - Job Wizard, Restore Test and SMB mount requests no longer transport location-specific profile keys; the selected canonical storage target supplies its profile identity.

### Issue #194
- Canonical data-model migration and diagnostics:
  - Replaced the PR #189 repository/storage migration chain with one baseline migration, `canonical_data_model_v1`.
  - The baseline accepts the published legacy layout, partially migrated test installations and already canonical installations while preserving existing canonical IDs.
  - Migration phases now create one rollback snapshot, validate all storage/repository/job links and remove `settings.json` only after the final model passes validation.
  - Migration progress, phase results, affected files, object-ID changes, validation and rollback outcomes are written to the central state and JSONL audit files without secrets.
  - System Health hides superseded intermediate migration entries and reports the canonical storage inventory instead of requiring `settings.json`.
  - Support bundles now include sanitized storage/repository inventories plus central migration state and audit details.
  - Added direct legacy-to-canonical, partial-upgrade, idempotence, rollback and separate-process locking regression coverage.

### Issue #193
- Canonical storage runtime cutover:
  - SMB backup, restore, restore-test and mount operations now consume the resolved storage object from `storages.json` instead of `SMB_PROFILES_JSON` or profile arrays in `settings.json`.
  - Settings profile changes use a structured API payload and persist directly to the canonical storage inventory.
  - The legacy-shaped settings reader is now only a derived compatibility view over `storages.json`; legacy input remains confined to audited startup migrations.
  - Repository usage lists are reconciled from authoritative job `repository_key` assignments after startup migrations.
  - System Health reports missing repositories, missing storage targets and inconsistent usage metadata with a repair path through the Job Wizard.
  - Jobs with a broken repository assignment can still be opened in the Wizard, corrected and saved without manual JSON editing.

### Issue #192
- Repository model cleanup:
  - Repository tests now accept only the canonical `repository_key`; direct repository paths and config keys are no longer public request parameters.
  - Persisted repository objects now contain only `storage_key` plus `relative_path`; effective local paths and SSH URIs are derived for API responses at runtime.
  - Added an audited, idempotent cleanup migration for repository inventories that already completed the earlier model migrations.
  - Removed stale help and manual instructions that described jobs as owners of repository paths, encryption or passphrases.
  - Added regression checks for canonical persistence, runtime job metadata access, translation parity and responsive Repository/Wizard layouts.

### Issue #191
- Performance:
  - Removed the blocking `modinfo cifs` subprocess from every System Health API request.
  - CIFS support is now detected through local kernel and `mount.cifs` capability checks without a three-second request timeout.
  - System Health now loads the canonical repository/storage inventory once per request instead of once per job.
  - Dashboard, sidebar and Settings now share one in-flight System Health request instead of downloading the same diagnostics repeatedly.
  - Split the large notification-reminder diagnostics from the general System Health response and load it through a dedicated Settings endpoint.
  - Normal Settings reads no longer run remote SSH authentication or target-detection probes; connection checks remain explicit user actions.
  - Repository and storage inventories reuse immutable in-process snapshots while their on-disk signatures remain unchanged.
  - Settings derives profile job counts from the canonical repository snapshot instead of rescanning every job for each profile type.
  - Static job metadata is cached with filesystem-signature invalidation while live run state and latest backup status remain uncached.
  - Settings menu switches reuse the existing page DOM instead of rebuilding all hidden panels and reloading backup history on every click.
  - The asynchronously loaded user list now updates its own panel without depending on a full Settings rerender.
  - Added regression coverage for the non-blocking capability probe.

### Issue #190
- Security:
  - Borg keyfile encryption now uses a persistent, plugin-owned `BORG_KEYS_DIR` with restrictive directory and file permissions across backup, restore, restore tests and repository maintenance.
  - Keyfile encryption was introduced with the canonical model and therefore writes directly to persistent storage; no unnecessary legacy-key migration is registered.
  - Existing keyfile repositories can import a `borg key export`; unrelated or conflicting keyfiles are never overwritten.
  - Encrypted job and secrets backups now include Borg keyfiles, while normal job exports and support bundles never contain key material.
  - Permanent repository deletion removes an exact unreferenced persistent keyfile and records the result in the lifecycle audit log.

### Issue #184
- Storage:
  - Added repository objects as a dedicated metadata inventory in `config/repositories.json`.
  - Existing wizard jobs are migrated to repository objects and receive a stable `repository_key`.
  - New or edited wizard jobs update the repository inventory automatically.
  - The Storage page now prefers managed repository objects and shows which jobs use each repository.
  - Repository objects now separate human-readable job, storage and repository names from technical IDs.
  - The Storage table shows display names by default and moves technical repository/job/storage IDs into the Details view.
  - Added `config/storages.json` as storage target inventory with stable `storage_*` IDs.
  - Existing repositories are migrated to reference storage objects and keep relative repository paths for the later repository wizard.
  - Repository objects now use deterministic hash-suffixed technical IDs such as `repo_flash_local_7f3c45ab`.
  - Storage objects now include the configured profile details needed by the later Storage/Repository wizard.
  - Missing repository encryption metadata is enriched once from linked job metadata instead of guessing a default value.
  - Jobs now keep only `repository_key`; repository paths, passphrase references, encryption and storage/profile links are resolved exclusively through the repository and storage inventories.
  - Added an audited, idempotent migration that validates effective legacy paths and secrets, creates a rollback backup, removes duplicate job fields and cleans deprecated repository/passphrase keys from `backup.conf`.
  - Backup, restore, restore-test, health, profile-usage and transfer paths now share the same canonical repository resolver and refuse unmigrated job metadata instead of silently falling back.

### Issue #187
- Storage:
  - Source-path suggestions support keyboard drill-down: Up/Down selects, Right opens the selected directory, and Enter adds the final source path.
  - Job source-path autocomplete now browses safely below `/mnt`, debounces input and prevents stale requests from clearing newer suggestions.

  - Repository paths can be typed naturally with internal hyphens; live input no longer removes a trailing hyphen before the next character is entered.
  - Added a three-step repository manager that selects or creates and tests Local, USB, SMB, and SSH/Storagebox targets before repository setup.
  - SMB targets receive a managed mount path; users no longer have to invent a technical temporary mount path.
  - Existing repository imports are validated with `borg info` and do not run `borg init`.
  - Job wizard repository handling now selects existing repository objects filtered by the exact storage target instead of accepting free-form repository paths.
  - Repository encryption metadata is owned by the repository object; jobs keep compression settings but no longer choose repository encryption.
  - Replaced the expandable repository table with a responsive master-detail workspace based on design variant A.
  - The repository sidebar groups repositories by exact storage target and keeps search, selection and status visible.
  - Repository details are split into Overview, Archives, Maintenance and Activities instead of exposing a technical live log.
  - Repository maintenance now stores structured, secret-masked results for Check, Verify Data, Prune and Compact.
  - Prune results list deleted archives, Compact reports reclaimed space when Borg provides it, and failed actions expose concise technical details.
  - The Archives tab loads the live archive inventory for the selected repository and shows names, IDs, timestamps and duration.
  - Borg repository information is refreshed in the background every 24 hours and cached; failed refreshes are retried after one hour.
  - Repository headers now use the configured repository display name instead of combining job and location names.
  - Display name, repository directory, absolute repository path and path inside the storage target are labeled separately.
  - Corrected repository header icon alignment.
  - Archive lists are sorted newest first and no longer show an unexplained empty duration column.
  - Verify Data, Prune and Compact confirmations now use an application-styled modal instead of the browser's native confirm dialog.
  - Removed the old job-based manual Borg Check card and the obsolete Job Wizard passphrase/repository-init path.
  - Repository info refresh now counts archives with `borg list --json` instead of assuming that `borg info --json` contains an archive list.
  - Repository Manager steps keep their numbered status circles, and the review distinguishes the display name from the path inside the storage target.
  - Running backup jobs are recovered from persistent resource locks when the UI process has lost its in-memory state, including live-log continuation from the active log file.
  - Automatic repository information refreshes are deferred while a backup uses the same repository and are shown as in use instead of as a repository failure.
  - Repository maintenance durations now use timezone-aware start times instead of collapsing valid runtimes to zero seconds.
  - The repository overview removes the redundant storage-relative path field, gives the absolute path the remaining row width, and drops the duplicate Activities tab until a real multi-run audit history exists.
  - Restore-test policies now survive Job Wizard edits instead of falling back to manual/L2 for local jobs.
  - Restore Tests now builds its sidebar from the already loaded plan and resolves all repository/storage assignments from one inventory snapshot per request.
  - Added a separate Repository Management tab with a non-destructive inventory removal and a guarded permanent Borg repository deletion.
  - Permanent deletion requires no linked jobs or running operations, revalidates repository ID/path/archive count, requires display-name plus `DELETE` confirmation, and records an audit entry.
  - Repository lifecycle audit entries now record the authenticated actor, role, authentication method and request ID; the general API log also identifies the repository action and outcome without exposing secrets.

### Issue #191
- Canonical inventory consistency:
  - Repository and storage inventories now use a shared cross-process lock, restrictive permissions, and durable atomic writes with `fsync` and `os.replace`.
  - Existing malformed inventories stop safely and are reported through API errors and System Health instead of being interpreted as empty data.
  - Job metadata and repository link changes are persisted as a recoverable transaction with rollback on write failures.
  - `storages.json` is the canonical source for Local, USB, SMB, and SSH profiles; the baseline migration creates a rollback backup and removes the obsolete `settings.json` after validation.
  - Settings now provides managed Local Profiles for arbitrary Unraid pools below `/mnt`, while broad collection roots and unsafe paths remain blocked.
  - Effective repository paths are derived from the current storage target and relative repository path.

### Issue #180
- Dashboard:
  - Growth now falls back to the previous backup status for the same job when no weekly snapshot baseline exists, avoiding unnecessary dash-only growth values.
### Issue #178
- Settings:
  - SSH key generation for storage profiles now shows an existing key as a warning instead of a success, making clear that no new key was created and nothing was overwritten.

### Issue #144
- Maintenance:
  - Removed the obsolete dedicated Restore migration status endpoint/UI banner.
  - Kept the internal `restore_history_v1` startup migration so completed legacy restore runs are still imported safely on systems that have not run it yet.
  - Restore active-run tracking remains in `restore-runs.json`; completed restore history remains in canonical per-run files under `restore-history/runs`.
  - Weekly snapshot handling now imports the old status-directory snapshot file once if needed and then writes only the canonical snapshot file.
  - Removed runtime `STORAGEBOX_BASE` alias expansion from the backup status config parser; deprecated keys remain visible through the cleanup audit.

### Issue #174
- Notifications:
  - Reminder diagnostics now distinguish the monitored/missed backup run from the next scheduled cron run, making rows such as an overdue weekly USB backup easier to understand.
  - The reminder diagnostics table now uses a compact fixed layout with wrapped labels so the Settings page no longer needs page-level horizontal scrolling.

### Issue #171
- Reports:
  - Failed restore verification banners now include the translated restore-test failure reason when the `.test` report contains a failure code such as `RT_NETWORK_ERROR`.
  - Restore verification metadata now forwards failure code, hint and category to job and dashboard/report API consumers without exposing raw command output.

### Issue #166
- Restore Tests:
  - Starting a second restore test while one is already running now returns a clear conflict instead of a generic internal server error.
  - The Restore Tests UI opens the live log and explains that a restore test is already running.
- Support bundle:
  - Restore-test `.test` status files are now included in support bundles.
  - Support bundle sanitizing now masks additional privacy-sensitive values such as e-mail addresses, SMTP/ntfy endpoints and storage profile host/user fields.

### Issue #163
- Notifications:
  - Backup and restore-test event e-mails now use STARTTLS on port 587, matching the SMTP test mail and weekly report behavior.

### Issue #158
- UI:
  - Dashboard run-status details now wrap cleanly instead of overlapping the Restore column for longer duration text.

### Issue #160
- Notifications:
  - Backup and restore-test event e-mails now fall back to the weekly-report recipient when the global e-mail recipient is empty.
  - Backup logs now show the configured e-mail notification events instead of the old failure-only wording.
  - SMTP test e-mails now require saving changed SMTP or e-mail settings first, so a successful test reflects the persisted runtime configuration.

### Issue #155
- Notifications:
  - Backup event e-mails now use the same message format and include the backup log output below the summary when a log file is available.

### Issue #153
- Notifications:
  - Backup jobs now pass the loaded job notification configuration into the central notification router, so selected e-mail events such as backup success are honored.
  - Added regression coverage for backup success and restore-test success e-mail event routing.

### Issue #150
- UI:
  - The sidebar footer and Settings About card now show the maintainer contact e-mail address.
  - The Settings About card now uses the current GitHub repository link.
  - Version and Borg version metadata are kept in UI state so the About card remains populated after tab and language changes.

### Issue #148
- Notifications:
  - Backup overdue reminders no longer send when the latest backup status for a scheduled job is missing or temporarily unreadable.
  - The scheduled reminder loop now waits for a boot grace period before its first check, avoiding false overdue notifications while Unraid mounts and status directories are still coming online.
  - Notification reminder diagnostics now show a dedicated missing-status state for these jobs.
  - Added regression coverage for the reported false-positive backup overdue reminder scenario.

### Issue #142
- Maintenance:
  - Startup now executes migrations only through the central migration registry.
  - Removed legacy migration-state assembly from `borg_backup_ui.py`.
  - The central registry now owns `migration-state.json` and `migrations.log.jsonl`.
  - Removed the old Storage path migration status entry from the migration registry UI.
  - Registry migration tests now cover applied, idempotent and failed startup migration runs.

### Issue #141
- Maintenance:
  - Removed the remaining legacy backup-script migration, detection and parser paths.
  - Normal job discovery now reads canonical job metadata only.
  - Backup execution and Browse & Restore repository resolution now require wizard/scriptless job metadata.
  - Removed the legacy job import action from the Jobs UI and Wizard flow.
  - Wizard job save responses no longer carry legacy backup script filenames.
  - The integrated Restore Test runner remains as utility code and is not treated as a legacy backup job.

### Issue #53
- Documentation:
  - Added a complete German user manual under `docs/user-manual/de/user-manual.md`.
  - Added an equivalent English user manual under `docs/user-manual/en/user-manual.md`.
  - Added current live-UI screenshots for both languages under `docs/user-manual/assets/`.
  - The manuals follow the application menu order and cover dashboard, jobs, storage, history, reports, browse/restore, restore tests, settings, help, notifications, users, system health, and migrations.

### Issue #124
- Tests:
  - Added pre-beta regression coverage for resource locks, selected Docker stop/start behavior, corrupt config/status recovery, and expanded secret masking.
  - Added `docs/maintainer/pre-beta-regression-tests.md` with a topic-based coverage map and manual Unraid follow-up checks.
  - Added a versioned pre-beta regression test report for `2026.07.03.0021`.

### Issue #137
- Notifications:
  - Backup overdue reminder sending now shares the same expected-run calculation as reminder diagnostics.
  - Stale `backup_overdue` reminder keys are cleared per job once a newer backup status satisfies the scheduled run.
  - Added a regression test for mixed current and overdue backup jobs so only truly sendable overdue reminders are delivered.

### Issue #123
- Runtime:
  - Backup runs now write `config/runtime-recovery.json` after Docker containers or VMs are stopped and before Borg work continues.
  - Normal cleanup marks the matching Docker/VM recovery entry as restarted; hard crashes or restarts leave pending entries for audit.
  - System health exposes pending runtime recovery entries with job name, runtime type, stopped timestamp, log file and affected targets.
  - Settings > System health & migration now shows a Runtime Recovery section and the sidebar health badge counts pending recovery entries.
  - Backup execution now prefers the packaged plugin runtime over older persistent data-root libraries, so Docker/VM recovery state is written reliably during running jobs.
  - Runtime recovery diagnostics now distinguish active backup runs from stale or failed recovery entries; active runs no longer turn system health into a warning.
  - Runtime recovery state is now a snapshot of open recovery problems; successfully restarted Docker/VM entries are removed instead of retained as history.
  - Runtime recovery warnings can now be marked as resolved after Docker containers or VMs have been checked or started manually.
- Schedules:
  - Crontab read/install failures now raise visible errors when schedules are saved or deleted.
  - Schedule API responses include crontab apply diagnostics for successful saves/deletes.

### Issue #125
- Security:
  - Restore target handling now revalidates destination paths immediately before unlink, recursive removal, rename and cleanup operations.
  - Restore overwrite and rename staging directories are created exclusively inside the validated target directory instead of using predictable names.
  - Restore ownership normalization uses `lchown` and avoids following symlinked directories.
  - Restore downloads now collect Borg stderr concurrently while streaming stdout to the browser, preventing stderr pipe backpressure from stalling the process.
  - Restore downloads now use a watchdog timeout and clean up killed or disconnected Borg subprocesses.

### Issue #133
- Notifications:
  - System health now includes read-only diagnostics for active backup and restore-test overdue reminders.
  - Diagnostics show expected/due times, overdue thresholds, latest status/test data, reminder keys and next allowed reminder time without sending notifications or updating reminder state.
  - Diagnostics ignore stale backup overdue reminder state when a later successful backup status already satisfies the expected scheduled run.
  - Reminder diagnostics are shown under Settings > Advanced in a dedicated table layout instead of inside system health details.
  - Advanced settings now separate notification reminder diagnostics and per-repository passphrases into subtabs.
  - Reminder diagnostics use two-digit day and month formatting for more stable table alignment.
  - Reminder diagnostics use a lighter table surface and avoid unnecessary line breaks in job, status and timestamp columns.
  - Backup overdue diagnostics advance to the next scheduled run once the latest expected run has completed successfully.
  - Per-repository passphrase settings use the same lighter table surface as notification reminder diagnostics.

### Issue #132
- UI:
  - The main app now applies the stored UI theme before loading stylesheets, avoiding a visible dark-theme flash when light mode is selected.

### Issue #130
- Notifications:
  - Restore-test overdue reminders now require a concrete due timestamp and no longer create `restore_test_overdue:*:never` reminder entries.
  - Scheduled restore-test runs now use the same restore-status directory resolution as the UI/API and evaluate `test_date` instead of file modification time.
  - The scheduled restore-test runner no longer sends a restore-test overdue notification immediately before running a due test.
  - Backup overdue reminders can match latest status entries by `backup_type` and `location` when a status row does not expose a `key`.
  - Notification reminder state is cleaned up during reminder checks; stale entries older than 90 days and legacy `restore_test_overdue:*:never` entries are removed.
  - Backup overdue reminder state is cleared when a later successful backup status satisfies the missed scheduled run.

### Issue #128
- Wizard:
  - Job wizard API failures now prefer backend validation details for wizard error messages, so preview and save failures can show the affected field or path instead of only a generic bad-request text.

### Issue #122
- Security:
  - Schedule writes now validate job keys before persisting schedules and before regenerating crontab entries.
  - Generated cron commands wrap untrusted values with shell-safe quoting and structured JSON payloads.
  - The UI login flow no longer sets the global API token as a browser cookie; automation access remains available through explicit API token headers or bearer auth.
  - Shared secret masking now covers common key/value secrets, bearer tokens, URL userinfo, secret query parameters, Borg passcommand paths and Borg Backup UI secret file paths.
  - Repository test output is sanitized before it is returned to the UI.

### Issue #102
- Browse & Restore:
  - Restore target roots are configurable under Settings > Restore > Browse & Restore.
  - `/mnt/user` remains the only default target root; additional roots such as `/mnt/data`, `/mnt/disk1`, `/mnt/disks/<name>` and `/mnt/remotes/<name>` must be added deliberately.
  - Broad or system-level roots such as `/`, `/mnt`, `/mnt/disks`, `/mnt/remotes`, `/boot`, `/etc`, `/usr` and `/var` are rejected by both UI validation and backend filtering.
  - Step 4 validates the target path against the configured roots before the precheck/start flow and displays the allowed roots dynamically.
  - Restore target root inputs validate while typing but normalize only on blur/save, so users can enter paths such as `/mnt/data` normally.

### Issue #101
- Notifications:
  - Backup overdue reminders now use the latest expected cron run plus configurable tolerance instead of only a broad schedule interval.
  - Settings expose `NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS` for the backup overdue tolerance.
  - Reminder interval and backup overdue tolerance are shown in a central reminder settings card because they apply to all notification channels.
  - Reminder keys now use the expected run timestamp so each missed scheduled window is notified at most once.

### Issue #92
- Settings:
  - System health now lists recorded startup migrations such as `notification_events_v1` in an executed migrations section.
  - Migration entries show status, changed keys, execution timestamp and introduced version so central notification migrations are auditable from the UI.
  - Applied startup migrations now write to `migrations.log.jsonl`, so the latest migration summary uses the actual latest migration run.
  - Backup overdue reminders now support weekday cron ranges and lists such as `0 9 * * 1-5` instead of treating every day-of-week restriction as a weekly schedule.

### Issue #93
- Browse & Restore:
  - Active restore runs remain in the wizard status banner and can still resume the live log.
  - Completed restore runs are stored in a dedicated Restore History with index and per-run detail files.
  - The Restore History UI shows status, timing, target, conflict mode, owner handling and the retained restore log in a separate view instead of above the wizard.
- Migration:
  - Legacy terminal entries from `config/restore-runs.json` are imported into `config/restore-history/index.json` and `config/restore-history/runs/<restore-id>.json`.
  - The migration writes `config/restore-history/migration-state.json` and `config/restore-history/migrations.log.jsonl` with migration id, status, timestamp, affected counts and errors.
  - The same migration is also reported through the central startup migration state so it is visible under Settings > System health & migration.
  - `restore-runs.json` is kept as active-run state only; stale running entries found after restart are marked aborted and moved to history.
  - Restore History keeps completed runs as individual detail files and allows users to delete history entries manually.

### Issue #82
- Wizard:
  - Docker- und VM-Steuerung kann pro Job auf alle laufenden Eintraege oder eine gespeicherte Auswahl eingeschraenkt werden.
  - Wizard listet lokale Docker-Container und VMs ueber interne API-Endpunkte.
  - Bei Appdata- und VM-Domain-Quellpfaden wird eine explizite Risiko-Bestaetigung verlangt, wenn nicht alle zugehoerigen Dienste gestoppt werden.
  - Die Runtime-Auswahl wurde in einen eigenen Wizard-Schritt verschoben, damit Grunddaten und Docker-/VM-Auswahl nicht in einer gedrängten Ansicht vermischt werden.
  - Risiko-Bestaetigungen fuer Appdata und VM-Domains werden nur beim vollstaendigen Standardpfad verlangt, nicht bei einzelnen Unterordnern.
  - Die Runtime-Auswahl nutzt mehr Wizard-Breite, zeigt Statuswerte als kontrastreiche Badges und fuehrt selektierte Docker-/VM-Ziele in der Flow-Vorschau auf.
  - Docker- und VM-Auswahl sind eigene optionale Wizard-Schritte, damit lange Container- und VM-Listen nicht auf derselben Seite stehen.
- Runtime:
  - Docker- und VM-Manager koennen selektiv stoppen und starten nur Eintraege neu, die der jeweilige Backup-Lauf selbst gestoppt hat.
  - Docker-Container werden fuer die Wizard-Auswahl kompatibler ueber ein einfaches `docker ps -a`-Format ermittelt.
  - Selektive Docker-Laeufe protokollieren in der Containerliste nur noch die tatsaechlich ausgewaehlten Container.
  - Bestehende Jobs ohne neue Runtime-Metadaten bleiben kompatibel und werden wie bisher als vollstaendige Docker-/VM-Steuerung behandelt.

## Unreleased unified UI redesign

### Issue #28
- UI (#28):
  - Gemeinsame Design-Tokens und wiederverwendbare Komponenten fuer Seitenkopf, Kontextnavigation, Workspace, Tabellen, Formulare, Statusfelder, Zusammenfassungen, Logs und Aktionen eingefuehrt.
  - Responsive Regeln fuer Desktop, Tablet und Mobile sowie sichtbare Fokus-, Lade-, Leer-, Warn-, Fehler-, Lauf- und Erfolgszustaende definiert.
  - Statusfelder im hellen Design verwenden explizite kontrastreiche Vorder- und Hintergrundfarben.

### Issue #29
- UI (#29):
  - Dashboard und Jobs verwenden einen gemeinsamen standortbasierten Arbeitsablauf mit Filterleiste und Auswahlzusammenfassung.
  - Das Dashboard zeigt Lauf-, Restore-, Speicher-, Wachstums- und Repository-Pruefdaten in einer kompakten Tabelle.
  - Jobs bleiben nach Standort gruppiert und behalten Start-, Log-, Zeitplan-, Legacy- und weitere Aktionsfunktionen.
  - Desktop-, Tablet- sowie helle und dunkle Darstellung wurden fuer die neuen Ansichten abgestimmt.

### Issue #30
- UI (#30):
  - History verwendet eine Standortnavigation mit kompakten Typ-/Statusfiltern, paginierter Tabelle und flexiblem Detailband.
  - History zaehlt Lokationen ueber den vollstaendigen gefilterten Bestand statt nur ueber die aktuelle Seite und verwendet die Storage-Location-Icons.
  - Berichte folgen der freigegebenen Variante C mit durchsuchbarer Job-Sidebar, Kennzahlen-Ledger, Trendtabelle mit Sparklines und monatlicher Statustabelle.
  - Bestehende Lauf-, Restore-, Repository-, Log- und Borg-Detaildaten bleiben erhalten.

### Issue #31
- UI (#31):
  - Restore Tests verwendet eine nach Location gruppierte Job-Sidebar mit Suche und den konfigurierten Job-Icons.
  - Planung, Laufzeithinweise, Policy-Tabelle, Live-Log und Prüfberichte sind in einem gemeinsamen responsiven Workspace zusammengeführt.
  - Plan- und Berichtszusammenfassungen erhalten höhere visuelle Priorität; technische Nachweise und Detaildaten bleiben verfügbar.
  - Prüfberichte folgen der freigegebenen Nachweisstruktur mit Ergebnis, Gesamturteil, Ausführung, Prüfumfang, kompakter Schrittfolge und einklappbaren technischen Nachweisen.

### Issue #32
- UI (#32):
  - Browse & Restore verwendet eine nach Standort gruppierte Job-Sidebar mit den konfigurierten Job-Icons und einen klaren Fünf-Schritt-Workflow.
  - Archivwahl, Dateibrowser, Einzelauswahl, Zieloptionen, Sicherheitsprüfung und technische Precheck-Ausgabe sind in einem gemeinsamen responsiven Workspace zusammengeführt.
  - Downloadgrößenprüfung, Zielbeschränkung unter `/mnt/user`, Konflikt- und Owner-Verhalten sowie Restore-Polling bleiben unverändert.

### Issue #34
- UI (#34):
  - Storage folgt der freigegebenen Variante A mit Standort-Sidebar, Repository-Tabelle und den bisherigen Standort-Icons.
  - Repository-Tests, SMB-Mount-Aktionen und der manuelle Borg Check bleiben im neuen responsiven Workspace erhalten.
  - Hilfe verwendet das gemeinsame Grunddesign mit einem automatisch aus den Dokumentüberschriften erzeugten Inhaltsverzeichnis.
  - Dialoge, Wizard, Zeitplan und technische Ausgaben verwenden einheitliche begrenzte und auf kleinen Bildschirmen scrollbar bleibende Oberflächen.
  - Standortbasierte Seiten verwenden in der deutschen Oberfläche einheitlich die Begriffe `Standorte` und `Alle Standorte`.

### Issue #33
- UI (#33):
  - Einstellungen verwenden ein gruppiertes Seitenmenü für System, Betrieb, Speicherziele und Wartung.
  - Konfigurationspfad, Speicheraktion und Bereichsstatus bleiben beim Scrollen sichtbar.
  - USB-, SMB- und SSH-Profile verwenden eine Master-Detail-Ansicht mit schreibgeschützten Feldern und explizitem Bearbeitungsmodus.
  - Profilprüfungen, SSH-Schlüsselaktionen, Löschschutz und bestehende Speicherverträge bleiben erhalten.
  - Reguläre Einstellungsbereiche verwenden ruhige horizontale Feldzeilen und responsive Tablet-/Mobilregeln.
  - Menü- und Speicherstatus-Texte werden korrekt aus dem Settings-Namensraum übersetzt.
  - Systemzustand und Migration folgen der kompakten Übersicht der Designstudie; technische Prüfungen bleiben aufklappbar verfügbar.
  - USB-Profile zeigen die tatsächlich zugeordneten Jobs aus den Job-Metadaten.
  - SSH-Status- und Verbindungstests aktualisieren nur den Ergebnisbereich und laden die Settings-Seite nicht mehr neu.
  - Bereits geladene Einstellungen bleiben bei Aktualisierungen sichtbar; Benutzerkonten werden nachgelagert geladen.
  - Die Unraid-Kontrollseite erkennt die Versionsnummer aus Test- und Stable-Manifesten.
  - Das Settings-Menü verwendet einheitliche SVG-Icons; Speicherziele übernehmen die Icons der Storage-Seite.
  - Die redundante Systemstatus-Zeile unterhalb des Settings-Menüs wurde entfernt.
  - `UI_SESSION_TIMEOUT_MINUTES` ist wieder Teil des aktiven `backup.conf`-Schemas und wird nicht mehr fälschlich als deprecated gemeldet.
  - Profil-Listen verwenden dieselben Standort-Icons wie Storage und die Settings-Navigation.
  - Der redundante absolute `backup.conf`-Pfad im Settings-Header wurde entfernt.
  - Der Dashboard-Laufstatus trennt und beschriftet den letzten Lauf und die Laufdauer; relative Zeiten und Einheiten folgen der gewählten UI-Sprache.
  - Dashboard-Spalten und Detailzeilen wurden neu ausbalanciert; Restore-Daten und Speichergrößen stehen geordnet untereinander, Standort-Badges brechen nicht mehr um.
  - Restore- und Speicherwerte verwenden ausgerichtete Label-Wert-Zeilen; die deduplizierte Größe des letzten Laufs ist eindeutig beschriftet.
  - Profilseiten zeigen den lokalen Speichern-Dialog auch nach dem Entfernen des letzten Profils im Bearbeitungsmodus.
  - USB-, SMB- und SSH-Profile können nicht entfernt werden, solange Jobs sie noch verwenden; die Prüfung erfolgt in UI und API.
  - Profilseiten serialisieren beim Speichern direkt die aktuellen DOM-Zeilen, laden nach Profil-Saves den Backend-Zustand nach und aktualisieren Leerhinweise dynamisch.
  - Das Plugin-Installationsskript prüft nach `upgradepkg`, ob die App-Dateien wirklich entpackt wurden, und entpackt das Paket andernfalls defensiv selbst.
  - Test-Channel-Deploys brechen vor dem Push ab, wenn das generierte Manifest kein gültiges XML ist oder das Paket zentrale App-Dateien nicht enthält.
  - Fällige Restore-Tests laufen für automatisch ausgewählte USB-, SMB- und Storagebox-Jobs nicht mehr gegen den alten globalen Location-Default.
  - Restore-Test-Discovery erkennt Profil-basierte USB- und SMB-Repositorys auch dann, wenn sie nicht mehr als `REPO_*`-Wert in `backup.conf` stehen.
  - Settings-Saves schreiben nur noch die Werte des aktiven Bereichs, damit SMTP- und Wochenbericht-Konfigurationen nicht durch versteckte leere Felder überschrieben werden.
  - Profil-Secret-Import erlaubt fehlende Zielprofile, wenn diese aus der im Paket enthaltenen Settings-Payload angelegt werden können.
  - In-App-Hilfe beschreibt nun SMTP, Wochenbericht sowie profilbasierte Import-/Secret-Import-Abläufe.

## Test-channel follow-up for 2026.06.25.1831

- Storage (#72):
  - Repositorys werden in der Gesamtansicht nach Standort gruppiert; SMB-Profile erscheinen nur noch im SMB-Kontext.
  - Ergebnisse von Repository-Tests bieten nach Erfolg und Fehler einen sichtbaren Detailzugang.
  - Repositorys verwenden die in den zugehörigen Job-Dateien konfigurierten Icons; leere Ergebnisplätze werden vor einem Test nicht angezeigt.
- Restore Tests (#76):
  - Überfälligkeit wird in der Planübersicht nur noch über den Zahlenwert hervorgehoben.
  - Sidebar-Zustände und technische Nachweise verwenden konsistente Farben und füllen keine leeren Rasterzellen.
- Dashboard (#77):
  - Spaltenbreiten sowie Backup-, Speicher- und Check-Daten wurden in klar getrennte, lesbare Zeilen gegliedert.
  - Archivnamen bleiben in der Backup-Spalte einzeilig und zeigen den vollständigen Wert weiterhin im Tooltip.
- Jobs (#78):
  - Vollständige Job-Beschreibungen bleiben sichtbar; Richtlinie und Restore-Test-Zeitpunkte sind übersichtlich angeordnet.
- History (#73):
  - Erfolgsstatus, Fehlerhinweise sowie Archiv- und Check-Details wurden sprachlich und visuell überarbeitet.
  - Der Check-Status belegt die vollständige letzte Detailzeile, sodass keine unbelegte Restfläche entsteht.
  - Das Archivfeld bleibt auch bei Fehlerläufen als Platzhalter erhalten, damit die Detailstruktur stabil bleibt.
- Berichte (#74):
  - Borg-Repository-Informationen verteilen nur vorhandene Kennzahlen ohne leere Füllspalte.
- Sprachauswahl (#75):
  - Deutsch und Englisch werden zusätzlich mit sichtbaren Flaggensymbolen gekennzeichnet; die Sprachnamen und barrierearmen Beschriftungen bleiben erhalten.

### Issue #70
- UI (#70):
  - Standort-Sidebars verwenden einheitlich die feste Reihenfolge Lokal, USB, SMB und Storagebox.
  - Nicht vorhandene Standortgruppen werden ausgelassen; Auswahl, Zählung und Filter bleiben unverändert.

## Archivierte Manifest-Historie

###2026.06.15.1213###
- Reports:
  - Wochenbericht zeigt die Erfolgsquote der letzten 7 Tage statt der historischen Gesamtquote.

###2026.06.12.0027###
- Reports:
  - Wochenbericht zeigt das Borg-Backup-UI-Icon im Mailkopf.
  - Job-Uebersicht und Log-Hinweise werden nach Location sortiert.
  - Exit-Spalte entfernt und Zeilenumbrueche in der Job-Tabelle reduziert.
  - Log-Hinweise werden nur noch fuer Fehler-Jobs angezeigt und ignorieren normale INFO-Mailzeilen.

###2026.06.12.0013###
- Reports:
  - Wochenbericht per Mail professioneller gestaltet mit Kopfbereich, Kennzahlen, Auffaelligkeiten, erweiterter Job-Uebersicht und Log-Hinweisen.
  - Relative Laufzeiten im Wochenbericht werden deutsch ausgegeben.

###2026.06.11.1013###
- UI:
  - Login- und Erstkonfigurationsseite verwenden das aktuelle Borg-Backup-UI-App-Icon.

###2026.06.09.2219###
- UI:
  - PDF-Export fuer Restore-Test-Pruefberichte entfernt.
  - Unbenutzten PDF-/QR-Rendercode entfernt; die Pruefbericht-UI bleibt erhalten.

###2026.06.09.2206###
- UI:
  - Restore-Test-PDF-Kopf zeigt Job, Archiv und Report-ID als eigene Zeilen.
  - PDF-Pruefschritte blenden weitere redundante Basisdaten aus.

###2026.06.09.2150###
- Fix:
  - Restore-Test-UI zeigt wieder die vollstaendigen Pruefschritt-Detailfelder.
  - PDF-Deduplizierung fuer Pruefschritt-Details erfolgt nur noch im PDF-Renderer.

###2026.06.09.2137###
- UI:
  - Restore-Test-Pruefbericht entfernt redundante Zeit-/Schema-Felder aus den Pruefschritt-Details.
  - PDF-Drucklayout fordert Farbdruck/Hintergruende per Print-CSS ausdruecklich an.

###2026.06.09.2121###
- UI:
  - Restore-Test-PDF-Bericht zeigt eine eigene Seitenzaehlung im Drucklayout.
  - QR-Code im PDF groesser dargestellt und mit Report-ID, Job, Archiv, Testdatum und Ergebnis befuellt.
  - QR-Beschriftung unter dem Code zentriert.

###2026.06.09.2107###
- UI:
  - Restore-Test-PDF-Bericht mit kompakterem Drucklayout fuer Browser-PDFs nachgeschaerft.
  - Berichtsdaten im PDF breiter gruppiert, damit Report-ID, Job und Archiv nicht in schmale Spalten umbrechen.
  - QR-Nachweis-ID im PDF-Bericht ergaenzt.

###2026.06.09.2051###
- UI:
  - Restore-Test-PDF-Bericht als hochwertigeres Pruefprotokoll mit Kopf, Zusammenfassung und Berichtsdaten gestaltet.
  - Level-3-Aktiv-Wert aus Schritt 5 entfernt, damit die Stichprobenwerte ohne graue Leerflaeche dargestellt werden.

###2026.06.09.2035###
- UI:
  - Restore-Test-Zusatzinformationen direkt den jeweiligen Pruefschritten zugeordnet.
  - PDF-/Druckexport als eigenstaendige, professionelle Berichtsvorlage neu aufgebaut.

###2026.06.09.2022###
- UI:
  - Restore-Test-Pruefberichte zeigen zusaetzliche Detailinformationen zu Archiv, Pruefumfang, Level-3-Stichprobe und getesteten Eintraegen.
  - Schrittlabels fuer Restore-Probe und Integritaetspruefung korrigiert.
  - Browserbasierter PDF-/Druckexport fuer einzelne Pruefberichte ergaenzt.

###2026.06.09.1947###
- UI:
  - Restore-Test-Pruefbericht-Kennzahlen fuellen die Report-Karte ohne graue Leerflaeche.

###2026.06.09.1936###
- UI:
  - Restore-Test-Pruefberichte professioneller als Report-Karte mit Kennzahlen und strukturierter Pruefschritt-Liste dargestellt.

###2026.06.09.1623###
- UI:
  - Browser-Favicon fuer kleine Tab-Darstellung neu erstellt und 16px/32px Varianten im HTML verlinkt.

###2026.06.09.1520###
- UI:
  - Sidebar-Logo vertikal zentriert dargestellt und UI-Icon mit transparenten Ecken ausgeliefert.

###2026.06.09.1442###
- UI:
  - Helle Icon-Variante als einheitliches Plugin-, Sidebar- und Favicon-Icon uebernommen.
  - Sidebar-Logo groesser dargestellt und Logo-Text zweizeilig gesetzt.

###2026.06.09.1421###
- UI:
  - Plugin-Icon deutlicher gestaltet und in den Plugin-Metadaten statt des Datenbank-Symbols referenziert.
  - Separate Hell-/Dunkel-Iconvarianten fuer die Sidebar ergaenzt.

###2026.06.09.1407###
- UI:
  - Neues Borg Backup UI Icon fuer Unraid-Plugin-Seite, Sidebar und Browser-Favicon ergaenzt.

###2026.06.09.0827###
- Wartung:
  - Unraid-Control-Page zeigt Python-Runtime-Pfad und Version an.
  - Start/Restart prueft Python 3.10+ und verweist klar auf `Python 3 for Unraid`.

###2026.06.09.0714###
- Fix:
  - Linux-VM-Desktopwarnungen werden wieder im Kontext des angemeldeten Benutzers ausgefuehrt.
  - VM-Benachrichtigungen bleiben best-effort und protokollieren Fehlschlaege nur als Hinweis.

###2026.06.08.1252###
- Doku:
  - In-App-Hilfe auf den aktuellen Stand gebracht und als kompakte Kurzhilfe neu strukturiert.
  - Struktur fuer ein ausfuehrliches Anwenderhandbuch ergaenzt.

###2026.06.08.0856###
- UI:
  - Sidebar-Systemstatus ist deutlicher gestaltet.
  - Einstellungen zeigen beim Aktualisieren einen Ladezustand statt kurz einen alten Systemzustand.

###2026.06.08.0832###
- UI:
  - Sidebar zeigt fuer Admins einen kompakten Systemstatus-Indikator mit direktem Sprung zu Einstellungen.

###2026.06.08.0806###
- UI:
  - Job-Wizard zeigt den SSH-/Storagebox-Repository-Status als eigene Statuszeile in der Vorschau.
  - Systemzustand trennt System, Jobs, letzten Migrationslauf sowie Initiales Setup/Konfiguration/Wartung klarer.
- Jobs:
  - Schnelle Job-Gesundheitspruefung fuer Repo-URI, Quellpfade, Passphrase-Datei und Storage-Profilreferenzen.
- Fix:
  - Storagebox-Repo-URIs werden backendseitig zentral aus Storage-Profilen aufgebaut.

###2026.06.08.0014###
- Fix:
  - Job-Wizard prueft bei SSH-/Storagebox-Jobs in der Vorschau, ob das Remote-Repository bereits existiert, und verlangt die Init-Bestaetigung nur noch wenn noetig.

###2026.06.08.0004###
- Fix:
  - Job-Wizard baut SSH-Repo-URLs aus Storage-Profilen mit relativem Basispfad korrekt als URI-Pfad, z.B. `:23/./backup/...`.

###2026.06.07.2351###
- Fix:
  - Dashboard-Systemzustand erkennt `migration-state.json` v2 korrekt und zeigt keinen falschen Warnhinweis mehr bei erfolgreichem letzten Lauf.

###2026.06.07.1414###
- UI:
  - Cleanup-Aktion wird direkt im sichtbaren Bereich `Offene Punkte` angeboten.
  - Technische Details enthalten keinen zweiten Cleanup-Button mehr.
  - Sichtbare Cleanup-Texte verwenden UTF-8-Umlaute und kuerzere Beschreibung.

###2026.06.07.1058###
- UI:
  - Cleanup-Kandidaten werden in der Aktionsuebersicht nicht mehr zusaetzlich als `offen` und `geplant` gezaehlt.
  - Wartungsbedarf wird als eigene Cleanup-Kennzahl dargestellt.

###2026.06.07.1046###
- UI:
  - `Systemzustand & Migration` zeigt Setup-/Konfigurationsstatus als sichtbare Kennzahlen und Aktionsliste.
  - Offene Wartungs- oder Cleanup-Punkte sind nicht mehr nur in der Bestandsaufnahme-Zeile versteckt.

###2026.06.07.1030###
- UI:
  - Leere Legacy-Cleanup-Planung wird nicht mehr als `geplant` gezaehlt.
  - Dry-Run-Hinweis fuer Cleanup wird nur noch angezeigt, wenn tatsaechlich Kandidaten vorhanden sind.

###2026.06.07.1019###
- Wartung:
  - `migration-state.json` befuellt den Bereich `config.backup_conf_schema` mit semantischem `backup.conf`-Status.
  - Aktive Legacy-Keys, bereits deaktivierte Legacy-Archivzeilen und geschuetzte interne Marker werden getrennt ausgewiesen.

###2026.06.07.0949###
- Wartung:
  - `migration-state.json` auf klares v2-Modell mit `last_run`, `migrations`, `checks` und `config` umgestellt.
  - Storage-Pfad-Migration schreibt keinen `MIGRATION_STORAGE_PATHS_VERSION`-Marker mehr in `backup.conf`.
  - Startup-Migration protokolliert `no_changes` nicht mehr als neuen Audit-Log-Eintrag.
  - Systemzustand liest den neuen Migrationsstatus und zeigt geplante, aber nicht noetige Cleanup-Aktionen klarer an.

###2026.06.07.0849###
- Fix:
  - Legacy-Cleanup schuetzt den internen Marker `MIGRATION_STORAGE_PATHS_VERSION` vor dem Auskommentieren.
  - Setup-Status erkennt einen zuvor auskommentierten Storage-Pfad-Marker weiterhin.
  - Anzeige `nicht nötig · geplant` fuer abgeschlossene Cleanup-Planung bereinigt.

###2026.06.07.0834###
- Wartung:
  - Apply-Mechanismus fuer Legacy-/Deprecated-`backup.conf`-Cleanup ergaenzt.
  - Cleanup kommentiert betroffene Keys nach expliziter Bestaetigung aus und erstellt vorher ein Config-Backup.

###2026.06.07.0045###
- Wartung:
  - Dry-Run-Plan fuer die spaetere `backup.conf` Legacy-/Deprecated-Cleanup-Migration ergaenzt.
  - Geplanter Cleanup zeigt Modus, Kandidatenzahl sowie Backup-/Rollback-Hinweis, fuehrt aber noch keine Aenderung aus.

###2026.06.07.0035###
- UI:
  - Registry-Bestandsaufnahme als `Setup & Konfiguration` getrennt von echten Migrationen dargestellt.
  - Legacy-/Deprecated-Keys aus `backup.conf` werden vollstaendig als Cleanup-Kandidaten gezaehlt.

###2026.06.07.0018###
- UI:
  - Migration-Registry-Texte in `Einstellungen > Systemzustand & Migration` auf deutsche Anzeige umgestellt.

###2026.06.07.0007###
- Wartung:
  - Read-only Migration-Registry ergaenzt: bekannte Migrationen, Schema-Sync-Status und deprecated `backup.conf`-Cleanup-Kandidaten werden inventarisiert.
  - Systemzustand zeigt Registry-Zusammenfassung und technische Registry-Details an.

###2026.06.06.2346###
- Wartung:
  - Systemzustand-API liefert eine strukturierte `migration_summary`; die Settings-UI nutzt diese bevorzugt fuer die Migrationsanzeige.

###2026.06.06.2335###
- UI:
  - Bereich `Einstellungen > Systemzustand & Migration` in Uebersicht, Systempruefungen, Migration und technische Details gegliedert.

###2026.06.06.2312###
- Security:
  - Support-/Diagnosepaket maskiert `ssh://`-Repository-URIs jetzt vollstaendig, damit User, Host und Repo-Pfad nicht im Export landen.

###2026.06.06.2010###
- Feature:
  - Support-/Diagnosepaket erweitert: `.status`, `.state`, `.pid`, `.txt` und `.log` aus Status-Verzeichnissen werden aufgenommen.
  - Plugin-Logs wie `/var/log/borg_backup_ui.log` und konfigurierte Log-Kandidaten werden begrenzt und sanitisiert exportiert.
  - Sanitizing-Report mit aufgenommenen und uebersprungenen Dateien ergaenzt.

###2026.06.06.1945###
- Feature:
  - Support-/Diagnosepaket als ZIP-Export in den Einstellungen ergaenzt.
  - Paket enthaelt sanitizierte Config, Settings, Job-Metadaten, Systemstatus und begrenzte Logs.
  - Bekannte Secrets werden maskiert; Secret-Dateien werden nicht exportiert.

###2026.06.06.1919###
- Wartung:
  - USB-Profilnormalisierung und USB-Profilstatus aus `api/config_api.py` in `api/usb_profiles_api.py` ausgelagert.
  - Bestehende `config_api`-Einstiege bleiben kompatibel.
  - Direkte Tests fuer USB-Profilnormalisierung und Statusmeldungen ergaenzt.

###2026.06.06.1843###
- Fix:
  - Unvollstaendige SSH-/Storage-Profile werden beim Speichern blockiert statt still aus der Profil-Liste entfernt.
  - Fehlermeldung nennt die fehlenden Pflichtfelder.

###2026.06.06.1807###
- Wartung:
  - Storagebox-/SSH-Profilnormalisierung, Job-Referenzen, Save-Validierung und Profil-Resolver aus `api/config_api.py` in `api/storage_profiles_api.py` ausgelagert.
  - Bestehende `config_api`-Einstiege bleiben kompatibel.
  - Direkte Tests fuer Storage-Profilnormalisierung, Save-Validierung und Profil-Resolver ergaenzt.

###2026.06.06.1715###
- Wartung:
  - SMB-Profilverwaltung, Status, Cleanup und Verbindungstest aus `api/config_api.py` in `api/smb_profiles_api.py` ausgelagert.
  - Bestehende `config_api`-Einstiege bleiben kompatibel.
  - Direkte Tests fuer SMB-Profilnormalisierung und Job-Loeschschutz ergaenzt.

###2026.06.06.1344###
- Fix:
  - Von Jobs genutzte Storage-Profile duerfen nicht mehr unvollstaendig gespeichert werden.
  - Draft-/ungenutzte Storage-Profile duerfen weiterhin unvollstaendig gespeichert werden.
  - Fehlermeldung nennt jetzt konkret fehlende Pflichtfelder statt eine Profil-Entfernung zu melden.

###2026.06.06.1335###
- Fix:
  - Legacy-Settings-Updates fuer `STORAGEBOX_HOST` speichern unvollstaendige Storage-Profile jetzt ebenfalls in `settings.json`.
  - Behebt weiterhin auftretende falsche Profil-Entfernungspruefung beim Leeren des SSH-Hosts.

###2026.06.06.1322###
- Fix:
  - Storage-Profile mit leerem Host/User werden beim Speichern nicht mehr als geloescht interpretiert, solange Key/Name vorhanden ist.
  - Behebt falsche Sperre `Storage-Profil ... kann nicht entfernt werden`, wenn ein referenziertes Profil nur unvollstaendig gespeichert wird.

###2026.06.06.1310###
- Wartung:
  - Storagebox-/SSH-Key-Setup und Verbindungstest aus `api/config_api.py` in `api/storagebox_api.py` ausgelagert.
  - Bestehende `config_api.storagebox_*`-Einstiege bleiben kompatibel.
  - Tests fuer Storagebox-Profilnormalisierung, SSH-Command-Aufbau und Zieltyp-Erkennung ergaenzt.

###2026.06.06.1256###
- Wartung:
  - SMTP-Testmail-Logik aus `api/config_api.py` in `api/smtp_api.py` ausgelagert.
  - Bestehender API-Einstieg `send_test_email()` bleibt kompatibel.
  - Tests fuer SMTP-Konfigurationsvalidierung ergaenzt.

###2026.06.06.1238###
- Wartung:
  - Auth-/User-/Session-Store-Helfer in `api/auth_store.py` ausgelagert.
  - Bestehendes HTTP-/API-Verhalten bleibt unverändert.
  - Auth-Tests um Store- und Cookie-Parsing-Abdeckung erweitert.

###2026.05.27.1133###
- Systemzustand > Migration:
  - `keine Änderungen protokolliert` wird nicht mehr als Fehler (`✗`) dargestellt.
  - Detailblock wird korrekt an `Letzte echte Migration` gebunden.

###2026.05.27.1122###
- Systemzustand > Migration überarbeitet:
  - Details beziehen sich jetzt aus `config/migrations.log.jsonl` (nicht mehr aus starren Texten).
  - Zeile `Letzte echte Migration` zeigt nur Läufe mit tatsächlichen Änderungen/Fehlern.
  - Detailblock zeigt dynamische `Grund`- und `Details/Aktionen`-Informationen aus dem Log-Event.
  - Doppelte Erfolgssignale reduziert (kein redundantes `Migration: Erfolgreich` mehr).

###2026.05.27.1108###
- Einstellungen > Systemzustand & Migration:
  - Migrationsdetails sind jetzt direkt bei `Letzte Migration` als aufklappbarer `Details`-Block eingebettet.
  - Enthält: `Status`, `Letzter Lauf`, `Grund`, `Übernommene Datenpfade`, `Verschobene Elemente`, `Fehler`, `Details/Aktionen`.
  - `Technische Details` bleiben separat aufklappbar.

###2026.05.27.1105###
- Einstellungen > Systemzustand & Migration:
  - Migrationsstatus jetzt strukturiert statt Freitext-Parsing:
    - `Status`, `Letzter Lauf`, `Grund`, `Übernommene Datenpfade`, `Verschobene Elemente`, `Fehler`, `Details/Aktionen`
  - Technische Rohdetails bleiben im aufklappbaren Bereich.
- Backend:
  - `migration-state.json` um strukturierte Felder erweitert (`reason_code`, `reason_text`, `details`).
  - Neues Audit-Log `config/migrations.log.jsonl` (ein Event pro Startup-Migrationslauf).

###2026.05.27.1041###
- Einstellungen > Systemzustand & Migration:
  - Letzte Migration jetzt benutzerverständlich zusammengefasst:
    - Migration (Erfolgreich/Fehlgeschlagen)
    - Letzter Lauf
    - Übernommene Datenpfade
    - Verschobene Elemente
    - Fehler
  - Technische Rohdetails bleiben über aufklappbaren Bereich `Technische Details` verfügbar.

###2026.05.27.1004###
- Scheduler-Fix:
  - Cron-Aufrufe für `/api/jobs/run` und `/api/restore-tests/run` senden jetzt den API-Token-Header mit.
  - Behebt nicht ausgelöste geplante Jobs bei aktivierter API-Authentifizierung.
- Storage UI-Fix:
  - Mouseover-Details auf Test-Status (`✓ OK` / Fehler) wiederhergestellt (`title` mit Output/Fehlermeldung).

###2026.05.27.0946###
- Restore/Browse UX + Auth-Fix:
  - Restore-Ziel wird standardmäßig mit `/mnt/user/` vorbelegt.
  - Zielpfad-Placeholder auf `/mnt/user/` angepasst.
  - Zielverzeichnis-Autocomplete auf `/mnt/user/...` beschränkt.
- 401-Fix bei Seitenwechsel nach Restore:
  - fehlende `credentials: include` bei Restore-/History-/Setup-Status-Requests ergänzt.

###2026.05.27.0930###
- Fix Root-Cause für P0-Migration:
  - `GLOBAL_DATA_DIR` wird für die Storage-Migration jetzt primär aus `read_raw_conf()` gelesen
    (statt nur aus `read_expanded_conf()`), mit Fallback.
  - Damit läuft die Migration auch dann korrekt, wenn `read_expanded_conf()` den Wert leer liefert.
  - Legacy-Quellpfade für Logs/Status/Restore-Status/Cache werden ebenfalls robust aus raw+expanded ermittelt.

###2026.05.27.0917###
- Fix echte Storage-Migration:
  - Cache-Migration nutzt jetzt cross-device-sichere Verschiebung (`shutil.move`) statt `rename`.
  - Dadurch werden Inhalte aus `/mnt/cache/...` nach `<GLOBAL_DATA_DIR>/cache` korrekt migriert.
  - Migrationsreport enthält jetzt zusätzlich `move_errors`.
  - `MIGRATION_STORAGE_PATHS_VERSION` wird nur auf `1` gesetzt, wenn keine Move-Fehler aufgetreten sind.

###2026.05.27.0906###
- Fix Startup-Robustheit für P0-Migration:
  - Harte Startup-Fallback-Prüfung ergänzt: wenn `GLOBAL_DATA_DIR` gesetzt ist, werden
    `GLOBAL_BORG_CACHE_BASE=<GLOBAL_DATA_DIR>/cache` und `MIGRATION_STORAGE_PATHS_VERSION=1`
    notfalls direkt in `backup.conf` gesetzt.
  - Zusätzliches Log: `Startup-Fallback: ...`.
- Fix rc-Startskript:
  - Start verwendet jetzt `python3` mit Fallback auf `python`.
  - Meldung `python3: command not found` wird damit vermieden.

###2026.05.27.0859###
- Fix für Storage-Pfadmigration (Persistenz):
  - Nach Migration werden die Zielwerte in `backup.conf` verifiziert.
  - Bei Abweichung werden die betroffenen Keys (`GLOBAL_LOG_DIR`, `STATUS_DIR`, `RESTORE_TEST_STATUS_DIR`, `GLOBAL_BORG_CACHE_BASE`, `MIGRATION_STORAGE_PATHS_VERSION`) hart nachgeschrieben.
  - Logging erweitert um `forced_conf_write`.

###2026.05.27.0849###
- Fix Migration-Startablauf:
  - Storage-Pfadmigration (`GLOBAL_DATA_DIR` -> cache/remotes usw.) läuft jetzt unabhängig von der Job-Layout-Migration.
  - Fehler in einer Teilmigration blockieren die andere Migration nicht mehr.
  - Explizites Logging ergänzt: Ergebnis der Storage-Pfadmigration (`changed/moved/settings_changed`).
  - Migrationsstatus wird immer geschrieben.

###2026.05.27.0824###
- P0 Storage-/Pfadmigration auf Basis von `GLOBAL_DATA_DIR`:
  - Laufzeitpfade werden aus dem Basisverzeichnis abgeleitet (`logs`, `status`, `restore-status`, `cache`, `remotes`).
  - Bei gesetztem `GLOBAL_DATA_DIR` werden `GLOBAL_LOG_DIR`, `STATUS_DIR`, `RESTORE_TEST_STATUS_DIR` und `GLOBAL_BORG_CACHE_BASE` automatisch migriert/gesetzt.
  - Migrationsstand in `backup.conf` über `MIGRATION_STORAGE_PATHS_VERSION=1` statt Marker-Datei.
  - Legacy-Datenpfade werden vorsichtig in die neuen Zielordner übernommen (nur wenn Zielobjekt noch nicht existiert).
  - SMB-Mountpfade unter `/mnt/remotes/...` werden auf `<GLOBAL_DATA_DIR>/remotes/...` normalisiert.
- Restore-Härtung:
  - Restore-Zielpfad ist backend- und frontend-seitig auf `/mnt/user/...` begrenzt.
  - Zielverzeichnis-Vorschläge in Browse & Restore nur noch unter `/mnt/user`.
  - Verzeichnis-Restore verbessert: wenn Zielordnername == Quellordnername, wird direkt in den Zielordner restored (kein doppelter Unterordner).
- Hilfe aktualisiert (`ui/docs/help.md`) mit neuer Basisverzeichnis-/Restore-Logik.

###2026.05.26.1719###
- Restore Test UI-Feinschliff:
  - Button umbenannt auf `Fällige Tests jetzt ausführen` (fachlich präziser).
  - Tooltip präzisiert: startet nur fällige geplante Tests.
  - Hinweistext bei keinen fälligen Tests erweitert (Intervall/Plan + manueller Start-Hinweis).
  - Prüfberichte-Tabelle leicht nachgeschärft (Zeilenabstand/Lesbarkeit Header).

###2026.05.26.1705###
- Restore Test -> Prüfberichte Tabelle verbessert:
  - neue Spalte `Job` in der Übersicht ergänzt.
  - Spalte `Dedupliziert` in `Abdeckung` umbenannt.
  - Status-Label bei Erfolg auf `Erfolgreich` geändert.
  - Spaltenbreiten/Zeilenumbruch für bessere Lesbarkeit (insb. Status einzeilig).

###2026.05.26.1656###
- Restore Test -> Prüfberichte:
  - Darstellung auf das bekannte, aufklappbare Prüfbericht-Layout umgestellt (wie im Screenshot).
  - Detailblock je Bericht mit Report-ID, Job, Archiv, Standort, Level, Start/Ende, Abdeckung, Fehlercode.
  - Prüfschritte-Tabelle mit `Schritt`, `Status`, `Dauer`, `Hinweis`, `Befehl`.

###2026.05.26.1645###
- Restore Tests UI überarbeitet:
  - Reiter-Layout für `Planung & Policy` und `Prüfberichte` vereinheitlicht.
  - `Prüfberichte` als eigene Ansicht mit Filterleiste (Job, Standort, Status, Zeitraum, nur problematische).
- Neue Prüfberichte-Übersicht:
  - Liste mit Job, Standort, Level, Ergebnis, Datum, Dauer, Report-ID, Gültig-bis, Abdeckung.
  - Klick auf Bericht öffnet vollständige Detailansicht direkt darunter.

###2026.05.26.1633###
- Restore Tests als Untermenü strukturiert:
  - Subtab `Planung & Policy`
  - Subtab `Prüfberichte`
- Dadurch klare Trennung zwischen Steuerung und Berichtsansicht.
- Prüfberichte bleiben im Restore-Tests-Bereich und sind nicht mehr in der allgemeinen History.

###2026.05.26.1621###
- Fix: Prüfberichte im Bereich „Restore Tests“ wieder sichtbar.
  - eigener Block „Prüfberichte“ unterhalb von „Planung & Policy pro Job“
  - lädt wieder `GET /api/restore-tests` und zeigt die Testbericht-Liste inklusive Details
  - allgemeine History bleibt weiterhin ohne Restore-Testberichte

###2026.05.26.1614###
- Restore-Plan Tabelle besser lesbar:
  - Sortierung jetzt nach Location und innerhalb der Location alphabetisch nach Jobname.
- History bereinigt:
  - Restore-Testberichte aus der allgemeinen History entfernt.
  - Restore-Testberichte bleiben zentral im Bereich „Restore Tests“.
  - Filteroption „Restore-Testbericht“ in History entfernt.

###2026.05.26.1603###
- Restore-Tests UI weiter bereinigt:
  - Zeitplan-Icon aus dem Header entfernt
  - alter Status-/Summary-Block entfernt
  - keine Doppelsteuerung mehr: Fokus auf „Planung & Policy pro Job“
- JS-Bindings entsprechend auf den konsolidierten UI-Pfad reduziert.

###2026.05.26.1550###
- Issue `#32` Phase 2a/2b:
  - Scheduler-Lauf (`scheduled=true`) wählt jetzt automatisch nur fällige Jobs mit Policy `scheduled`.
  - Wenn nichts fällig ist, wird kein Lauf gestartet (`started=false`, `reason=no_due_jobs`).
  - Restore-Tests UI konsolidiert: doppelte globale Run-Konfiguration entfernt.
  - Neuer zentraler Trigger: `Geplante jetzt ausführen`.
  - Plan-Tabelle erweitert um Scheduler-Status (`Ja (fällig)`, `Ja (wartet)`, `Nein`).

###2026.05.26.1537###
- Fix: `POST /api/restore-tests/run-job` nutzt jetzt standardmäßig das Job-Policy-Level
  (`restore_test_policy.level`) statt des globalen Default-Levels.
- Damit stimmen Plan-Anzeige und erzeugter Restore-Testbericht (`test_level`) bei
  „Jetzt testen“ wieder überein.

###2026.05.26.1525###
- Issue `#32` Phase-1 Härtung:
  - Plan-Tabelle: pro Job Loading/Status-Hinweis für `Speichern` und `Jetzt testen`
  - gezieltes Refresh nach Aktionen (`/api/restore-tests/plan` + `/api/restore-tests/running`)
  - Guardrails für Policy-Felder in UI+API (`interval_days >= 1`, `level in {1,2,3}`)
  - `run-job` API validiert Job-Key gegen bekannte/aktive Jobs (`unknown`/`disabled` => 400)
- Mini-Contract-Tests ergänzt: `tests/test_restore_tests_policy_contract.py`

###2026.05.26.1517###
- Fix für `POST /api/restore-tests/run-job`:
  - Einzeljob-Start verarbeitet den Request-Body jetzt korrekt in einem Durchlauf
  - kein zweites Einlesen des Body-Streams mehr
  - behebt Fälle, in denen „Jetzt testen“ in der Plan-Tabelle keinen Lauf ausgelöst hat

###2026.05.26.1510###
- Restore-Tests Plan-Buttons „Speichern“/„Jetzt testen“ robuster gemacht:
  - explizit `type="button"` gesetzt
  - Klickhandler mit `preventDefault()` + `stopPropagation()`
- behebt Fälle, in denen Klicks im Plan-Bereich ohne sichtbare Aktion blieben.

###2026.05.26.1505###
- Restore-Tests Plan-Aktionen senden jetzt Session-Cookies explizit mit (`credentials: include`):
  - `Jetzt testen` (pro Job)
  - Policy `Speichern`
  - manueller Restore-Test-Start
- behebt in Umgebungen mit strikter Cookie-Behandlung den Fehler:
  `API-Token fehlt oder ist ungültig`

###2026.05.26.1459###
- Fix für `GET /api/restore-tests/plan`:
  - entfernt fehlerhaften Import `get_latest_statuses` aus `status_api`
  - Plan-Aufbau nutzt jetzt direkt `list_jobs(config, {})`
  - behebt `internal_error` beim Laden von Restore-Planung/Policy in der UI

###2026.05.26.1418###
- Restore-Tests Phase 1 (Issue `#32`) umgesetzt:
  - neuer Plan-Endpunkt `GET /api/restore-tests/plan` mit Job-Policies, Fälligkeit und Zusammenfassung
  - neue API `PUT /api/restore-tests/policy` für Job-spezifische Restore-Test-Policy
  - neue API `POST /api/restore-tests/run-job` für Einzeltest pro Job
- UI „Restore Tests“ erweitert:
  - neuer Bereich „Planung & Policy pro Job“
  - pro Job: Policy/Intervall/Level editierbar + Speichern
  - pro Job: „Jetzt testen“-Aktion

###2026.05.26.1254###
- History: Restore-Testberichte zeigen jetzt je Prüfschritt den ausgeführten `Befehl` (z. B. `borg list`, `borg info`, `borg extract --dry-run`).
- Restore-Testberichte sind in der Standard-History ausgeblendet und erscheinen nur bei explizitem Filter `Typ = Restore-Testbericht`.
- Restore-Test-Reportschema erweitert: neue `steps[].command`-Felder für bessere Nachvollziehbarkeit im Prüfbericht.

###2026.05.26.1229###
- Release-Bump für Unraid-Update-Erkennung (History: Restore-Test Prüfberichte).
- History um echte Restore-Testberichte erweitert:
  - eigener Typ `Restore-Testbericht` inkl. Filter
  - strukturierte Detailansicht mit Report-ID, Level, Start/Ende, Gesamtstatus, Abdeckung
  - Prüfschritte mit Status/Dauer/Hinweis in der Detailansicht

###2026.05.26.1215###
- Release-Bump für Unraid-Update-Erkennung (Jobs-Card-Layout vereinheitlicht).
- Jobs-Cards im Stil der Dashboard-Cards nachgezogen:
  - konsistentere Kartenhöhe
  - stabilere Header-/Badge-Ausrichtung
  - Beschreibung auf 3 Zeilen begrenzt für einheitliches Raster
  - kompakter Restore-Status (`Restore: ...`)

###2026.05.26.1208###
- Release-Bump für Unraid-Update-Erkennung (Fix für Dashboard-Tabwechsel).
- Behebt doppelte Restore-Summary-Kacheln beim Wechsel auf Dashboard:
  - `restore-summary-bar` wird pro Render vollständig ersetzt (kein Anfügen)
  - leere Datenlage räumt den Bereich korrekt auf

###2026.05.26.1154###
- Release-Bump für Unraid-Update-Erkennung (Dashboard-Card-Polish).
- Dashboard-Cards vereinheitlicht und Lesbarkeit verbessert:
  - konsistentere Kartenhöhe
  - stabilere Header-/Badge-Ausrichtung
  - bessere Textumbrüche bei längeren Labels
  - Restore-Badges kompakter (`Restore: …`)

###2026.05.26.1139###
- Release-Bump für Unraid-Update-Erkennung nach Nachfix für Dashboard-Ausrichtung.
- Enthält den tatsächlich fehlenden UI-Fix:
  - getrennte Summary-Blöcke (Backup-Läufe / Restore-Nachweis)
  - korrigierte Badge-Ausrichtung in Dashboard-/Job-Karten
  - Text: `Restore nicht geplant`

###2026.05.26.1132###
- Release-Bump für Unraid-Update-Erkennung nach Merge von MR `!407` (Dashboard/Restore-Nachweis UI-Feinschliff).
- UI-Polish:
  - getrennte Dashboard-Abschnitte für Backup-Läufe und Restore-Nachweis
  - verbesserte Ausrichtung der Badges in Dashboard-/Job-Karten
  - Label angepasst: `Restore nicht geplant`

###2026.05.26.1112###
- UI-Integration für Restore-Nachweis umgesetzt (Issue `#31`):
  - Dashboard: aggregierte Nachweis-Kennzahlen (in-scope verifiziert/überfällig/fehlgeschlagen/offen + nicht erforderlich)
  - Dashboard/Jobs: Nachweis-Badges pro Backup/Job
  - Berichte: Nachweisstatus-Hinweis für gewählten Job
  - einheitliche Badge-Darstellung in Hell/Dunkel

###2026.05.26.1029###
- Release-Bump für Unraid-Update-Erkennung nach Merge von Issue `#29`.
- Restore-Test Nachweisstatus (P0) ergänzt:
  - Statusmodell `verified/stale/failed/never/not_required`
  - Job-Policy-Auswertung `off/scheduled/manual_only`
  - API-Felder in `/api/jobs` und `/api/status` für Nachweis/Policy erweitert.

###2026.05.26.0834###
- Login-UI zurück auf Variante 1 (kompakt) gesetzt.
- Split-Info-Spalte aus Variante 2 entfernt; Fokus wieder auf schlankem, klarem Login-Flow.

###2026.05.26.0830###
- Login-Seite als Split-Layout (Variante 2) umgesetzt:
  - links kompakter Login-Block
  - rechts schlanke System-/Betriebsinfos
  - responsive Fallback auf Single-Column für kleinere Viewports

###2026.05.26.0826###
- Login-Seite auf kompakte Utility-Variante umgestellt (Variante 1):
  - kleinere, ruhigere Card mit konsistenten Abständen
  - klarere Feld-/Label-Hierarchie und kompakter Primär-Button
  - besserer visueller Fit zur bestehenden Borg-UI in Hell/Dunkel

###2026.05.26.0818###
- P2 Benutzerverwaltung:
  - Session-Transparenz ergänzt: Anzeige aktiver Sessions im Benutzer-Tab (`eigene` und für Admin auch `gesamt`).
  - Hard-Delete-Flow gehärtet: klarer Warntext + explizite Bestätigung per Eingabe des Usernamens.
  - Deaktivieren bleibt als empfohlener Standardpfad für Offboarding.

###2026.05.26.0813###
- Security-Audit-Log ergänzt (schlank, ohne Secrets) für Benutzerverwaltung/Auth:
  - Login Erfolg/Fehlschlag
  - Logout
  - Passwort ändern / Passwort-Reset
  - User anlegen/ändern/löschen
  - Setup-Admin
  - Logout-All-Sessions
- Audit-Events enthalten `request_id` zur Korrelation mit API-Logs.

###2026.05.26.0808###
- P0-Härtung Benutzerverwaltung:
  - Benutzer-Mutationen jetzt atomar per zentralem Users-Lock (`create/update/reset/delete/change-password/setup-admin`).
  - Schutz „letzter aktiver Admin“ gegen Race-Conditions bei parallelen Änderungen verbessert.
  - First-Run-Admin-Setup zusätzlich gegen parallele Doppelanlage abgesichert.

###2026.05.25.1559###
- User-Management erweitert:
  - Eigenes Passwort ändern (`/api/auth/change-password`)
  - Sessions abmelden: eigene Sessions oder (als Admin) alle Sessions (`/api/auth/logout-all-sessions`)
  - Pro Benutzer neuer Schnellweg `Deaktivieren` als bevorzugte Alternative zum Löschen
- UI ergänzt:
  - Benutzer-Tab zeigt aktuellen Benutzer/Rolle und Aktionen für Passwortwechsel + Session-Logout
  - Löschdialog weist bei aktiven Benutzern auf „Deaktivieren“ als bevorzugten Weg hin

###2026.05.25.1552###
- Legacy-Auth über `UI_LOGIN_PASSWORD` entfernt; Authentifizierung erfolgt jetzt ausschließlich über Benutzerkonten (`users.json`).
- Login-Flow vereinfacht: Login immer mit Benutzername + Passwort (kein Legacy-Passwortpfad mehr).
- Einstellungen bereinigt: Karte `UI-Login & Session` entfernt; Session-Timeout ist jetzt in `Einstellungen -> Benutzer` konfigurierbar.
- Server ignoriert verbliebene `UI_LOGIN_PASSWORD`/`UI_LOGIN_PASSWORD_CLEAR` Updates explizit.

###2026.05.25.1542###
- Benutzerverwaltung erweitert: Benutzer kann jetzt im Tab `Einstellungen -> Benutzer` direkt gelöscht werden.
- Neue API ergänzt: `DELETE /api/auth/users`.
- Schutzregeln beim Löschen: aktuell angemeldeter Benutzer kann nicht gelöscht werden; letzter aktiver Admin kann nicht gelöscht werden.
- Sessions des gelöschten Benutzers werden sofort invalidiert.

###2026.05.25.1531###
- Release-Bump für Unraid-Update-Erkennung (reines Packaging-Release).
- Keine funktionalen Codeänderungen gegenüber `2026.05.25.1522`.

###2026.05.25.1522###
- Rollen-UI-Gating erweitert: `viewer` sieht keine aktiven Bedienaktionen mehr (Jobs starten/ändern, Storage-Tests/Mount, Restore-Start, Restore-Test-Start/Planung).
- Navigation gehärtet: `Einstellungen` wird für Nicht-Admins ausgeblendet; direkter Aufruf wird auf Dashboard umgeleitet.
- Dynamische UI-Elemente (nachgeladen gerenderte Karten/Buttons) werden per Observer konsistent mit Rollenrechten nachgezogen.
- Zusätzlicher Click-Guard blockiert verbotene Viewer-Aktionen defensiv auch bei dynamisch eingeblendeten Controls.

###2026.05.25.1505###
- Issue `#24` umgesetzt: Admin-Benutzerverwaltung im UI ergänzt (Benutzer anlegen, Rolle/Status ändern, Passwort zurücksetzen).
- Neue Auth-API-Endpunkte: `GET /api/auth/users`, `POST /api/auth/users`, `PUT /api/auth/users`, `POST /api/auth/users/password-reset`.
- Schutzregel umgesetzt: letzter aktiver Admin kann nicht deaktiviert oder auf nicht-admin gesetzt werden.
- UI erweitert: aktuell angemeldeter Benutzer inkl. Rolle wird im Sidebar-Footer angezeigt.

###2026.05.25.1452###
- Issue `#23` umgesetzt: serverseitige Rollen-Autorisierung pro API-Route (`viewer`, `operator`, `admin`) mit zentralem Guard in `_handle_api`.
- Default-Härtung: unbekannte/nicht gemappte API-Routen erfordern `admin`.
- Kompatibilität für Automationen: gültiger API-Token via Header/Bearer wird weiterhin als `admin` behandelt.

###2026.05.25.1447###
- UI ergänzt: neuer Sidebar-Button `Abmelden`.
- Logout-Flow angebunden: Button ruft `POST /api/auth/logout` auf und leitet anschließend auf `/login` um.

###2026.05.25.1417###
- Fix Session-Persistenz: Session-State wird jetzt konsistent im gemeinsamen Serverzustand geführt (klassenweit), statt request-lokal.
- Behebt leere `sessions.json` trotz erfolgreichem Login und daraus folgende `HTTP 401` bei Folge-Requests.

###2026.05.25.1411###
- Fix für sporadische `HTTP 401` bei Seitenwechseln: Session-Store schreibt jetzt atomisch (`sessions.json.tmp` -> `rename`) statt direkt in die Zieldatei.
- Session-Zugriffe thread-safe gemacht (Locking) und Session-Refresh ohne Datei-Write bei jedem Request, um Race-Conditions unter Parallel-Requests zu vermeiden.

###2026.05.25.1354###
- Fix Login/Asset-MIME: `/ui/*` Dateien werden im Logout/Setup-Fall nicht mehr auf HTML-Seiten umgeleitet.
- Verhindert Browserfehler wie `Uncaught SyntaxError: expected expression, got '<'` und falschen MIME-Typ bei JS-Dateien auf `/login`.

###2026.05.25.1352###
- Fix Auth-Flow nach Login: Bei aktivem UI-Login gilt eine gültige UI-Session jetzt direkt als API-Autorisierung für Browser-Requests.
- Dadurch wird der Fehler `Fehler beim Laden: HTTP 401 Unauthorized` nach erfolgreichem Login vermieden, wenn der API-Token-Cookie im Browser nicht rechtzeitig verfügbar ist.

###2026.05.25.1347###
- Issue `#22` umgesetzt: Session-Handling gehärtet mit persistentem Session-Store `config/sessions.json` (inkl. Schreiben mit Dateirechten `600`).
- Session-Logik erweitert: Idle-Timeout (konfiguriert) plus absolute Session-Laufzeit (12h hard limit), inkl. Pruning abgelaufener Sessions.
- Login/Logout verbessert: Session-Cookie erhält `Max-Age`, Logout invalidiert Session im persistenten Store.
- `/api/auth/status` erweitert um `session_absolute_timeout_minutes`.

###2026.05.25.1339###
- P0 `#21` umgesetzt: Benutzer-Store `config/users.json` eingeführt (Schema v1, Dateirechte `600` beim Schreiben).
- First-Run Admin-Setup ergänzt: neue Route `/setup-admin` mit Erstellung des ersten Admin-Benutzers.
- Auth-Flow erweitert: Login unterstützt jetzt Benutzername+Passwort aus `users.json`; Legacy-Modus mit `UI_LOGIN_PASSWORD` bleibt kompatibel.
- Bootstrap-Schutz: ohne vorhandene Benutzer und ohne Legacy-Login wird UI auf `/setup-admin` geführt, danach automatischer Login.

###2026.05.23.0854###
- Login-Seite visuell an Borg-UI angepasst (Card-Layout, Logo, Typografie, Farben).
- Theme-Unterstützung auf Login aktiv: Hell/Dunkel/System wird aus derselben UI-Theme-Preference (`bbui_theme_preference`) übernommen.

###2026.05.23.0043###
- Fix UI-Login-Aktivierung: Login-Checks lesen `UI_LOGIN_PASSWORD` und `UI_SESSION_TIMEOUT_MINUTES` jetzt aus der aktiven `backup.conf` (nicht nur aus Server-Startkonfiguration), damit Änderungen aus den Einstellungen sofort greifen.

###2026.05.23.0038###
- Einstellungen erweitert: neuer Bereich `UI-Login & Session` mit konfigurierbaren Feldern für `UI_LOGIN_PASSWORD` und `UI_SESSION_TIMEOUT_MINUTES`.
- Sicherheits-UX verbessert: UI zeigt nur den Zustand `Passwort gesetzt` (kein Klartext), leeres Passwortfeld überschreibt bestehendes UI-Login-Passwort nicht.
- UI-Login kann jetzt explizit über Checkbox `UI-Login deaktivieren (Passwort löschen)` entfernt werden.

###2026.05.23.0033###
- Sicherheits-Härtung: Optionaler UI-Login mit Session-Timeout eingeführt (`UI_LOGIN_PASSWORD`, `UI_SESSION_TIMEOUT_MINUTES`). Bei aktivem Login ist vor UI/API-Zugriff eine Anmeldung erforderlich.
- Systemzustand erweitert: Prüfung sensibler Dateirechte auf `600` für Secret-relevante Dateien (`.smb-*.cred`, `.borg-passphrase-*`, `.api-token`, optional `.ui-auth.json`, `config/settings.json`) inkl. Anzeige von Abweichungen.

###2026.05.23.0015###
- API-Härtung: Alle `/api/*`-Endpunkte sind jetzt per API-Token geschützt (Header `X-API-Token` / `Authorization: Bearer` oder HttpOnly-Cookie aus der UI-Session).
- Security-Fix: `/api/settings` liefert `GLOBAL_SMTP_PASSWORD` nicht mehr im Klartext; stattdessen wird `GLOBAL_SMTP_PASSWORD_SET` bereitgestellt.
- Settings-Save gehärtet: Leeres SMTP-Passwort überschreibt bestehende Zugangsdaten nicht mehr unbeabsichtigt.
- SMTP-UI angepasst: Feld bleibt leer, zeigt aber bei vorhandenem Secret den Zustand `SMTP-Passwort (gesetzt)`.

###2026.05.22.1040###
- Restore-Meldungen vereinheitlicht: normale Hinweise/Status (z. B. `Lade Archive...`, `Prüfe Downloadgröße...`, `Direkt-Download zu groß ...`) nutzen jetzt denselben orangefarbenen Hinweisstil.
- Download-Bestätigung bei großen Downloads nutzt jetzt den nativen In-App-Dialog (kein Browser-Standarddialog mehr im regulären Flow).

###2026.05.22.1023###
- Release-Bump nach Merge von MR !375, damit Unraid ein neues Update erkennt.

###2026.05.22.0948###
- Browse & Restore: Bestätigung für große Downloads (`>5 GB`) nutzt jetzt einen nativen In-App-Dialog statt Browser-/Windows-`confirm`.
- Dialog-Flow integriert in bestehendes Modal-Design inkl. Abbrechen/Start und Klick auf Backdrop zum Schließen.

###2026.05.22.0923###
- Browse & Restore UX verbessert: beim Download-Precheck wird jetzt ein sichtbarer Ladezustand (`Prüfe Downloadgröße...`) angezeigt.
- Bei blockiertem oder fehlgeschlagenem Download-Precheck wird die Meldung direkt im Browse-Bereich sichtbar ausgegeben.

###2026.05.22.0911###
- Browse & Restore Download abgesichert: serverseitige Größenprüfung vor Direktdownload mit Schwellwerten `>5 GB` (Bestätigung erforderlich) und `>20 GB` (hart blockiert, Hinweis auf Restore in Zielordner).
- Neue API `GET /api/restore/download-check` für Download-Vorprüfung; UI-Flow erweitert um Bestätigungsdialog bei großen Downloads.

###2026.05.22.0848###
- Browse & Restore Download korrigiert: `borg export-tar` für Verzeichnis-Downloads nutzt jetzt den stdout-Modus (`-`) mit Pfadfilter, damit TAR-Dateien nicht leer sind.

###2026.05.22.0844###
- Browse & Restore Download: Borg-Pfadtyp-Erkennung erweitert; unterstützt jetzt auch Kurztypen `d` (Verzeichnis) und `-` (Datei), damit Downloads auf älteren/abweichenden Borg-Versionen funktionieren.

###2026.05.22.0837###
- Browse & Restore Download-Fix: Verzeichnis-Download nutzt jetzt `borg export-tar` statt `borg extract --stdout`, dadurch sind Ordner-Downloads wieder gültige TAR-Archive.
- Pfadtyp-Erkennung ergänzt (`file`/`dir`) und Download-Header angepasst (`application/x-tar` für Verzeichnisse).

###2026.05.22.0016###
- Berichte-Kacheln Layout angepasst: `seit X Tagen` wird bei `Zuwachs 30 Tage` und `Ø Zuwachs/Tag` konsistent in einer zweiten Zeile dargestellt.

###2026.05.22.0003###
- Berichte-Tooltips erweitert: jetzt auch in `Neue Daten`, `Dauer` und `Status-Verlauf` mit kontextbezogenen Detailwerten.
- Wachstumskacheln robuster: `Zuwachs 30 Tage` und `Ø Zuwachs/Tag` nutzen bei kurzer Historie einen Fallback und zeigen `seit X Tagen` statt `0/—`.

###2026.05.21.2351###
- Berichte erweitert: Tooltips in `Repository-Größe über Zeit` zeigen jetzt Datum, Größe, Delta zum Vortag und Delta zur Vorwoche.
- Berichte erweitert um Wachstums-Kacheln: `Zuwachs 7 Tage`, `Zuwachs 30 Tage`, `Ø Zuwachs/Tag`, `Letzter Zuwachs`.

###2026.05.21.1645###
- Restore-Auswahl-Button Styling gehärtet: aktiver Zustand jetzt robust sichtbar (inkl. Hover/Focus und SVG-Stroke-Vererbung).
- Restore-Schritt-Hinweise (`Bitte zuerst ...`) farblich als Warnhinweis statt neutralem Text dargestellt.

###2026.05.21.1626###
- Restore-Auswahl UX verbessert: aktives Auswahl-Symbol (`✓`) wird deutlich farbig hervorgehoben.
- `Auswahl entfernen` setzt jetzt den Restore-Kontext vollständig zurück (Auswahl, Zielpfad, Modus, Vorprüfung, Bestätigung, Markierung).
- Auswahl-Button unterstützt Toggle: Klick auf bereits ausgewähltes Element hebt die Auswahl direkt wieder auf.

###2026.05.21.1619###
- Restore-Assistent Flow korrigiert: Auswahl eines Jobs lädt Archive im Hintergrund, bleibt aber in Schritt 1; Wechsel zu Schritt 2 erfolgt nur noch über `Weiter`.
- Schritt-3 Hinweis ergänzt: es ist immer nur eine Auswahl (Datei oder Verzeichnis) gleichzeitig möglich.

###2026.05.21.1613###
- Restore-Hinweise pro Schritt präzisiert: globale Fehlhinweise werden beim Schrittwechsel zurückgesetzt und nicht dauerhaft über alle Schritte angezeigt.
- Schritt 3 (`Auswahl`) um klaren Symbol-Hinweis erweitert (`⬇` Download, `✓` Auswahl für Restore; Datei oder Verzeichnis).
- Schritt 5 Abschluss-UX verbessert: nach erfolgreichem Restore wird `Zurück` zu `Schließen` und lädt `Browse & Restore` neu.

###2026.05.21.1555###
- Restore-Flow vereinfacht: manuelles `Vorprüfung ausführen` entfällt.
- Vorprüfung läuft jetzt automatisch beim Wechsel in Schritt 5 (`Prüfen & Start`).
- Start bleibt geschützt: `Wiederherstellen starten` erst bei erfolgreicher Vorprüfung + Bestätigung.
- Auto-Recheck ergänzt: Änderungen an Zielordner, Konfliktmodus oder Testlauf triggern bei Schritt 5 automatisch eine neue Vorprüfung.

###2026.05.21.1547###
- Restore-Auswahl korrigiert: zweiter Button im Dateibrowser ist jetzt `Auswählen` (bleibt in Schritt 3), Wechsel nach `Ziel & Modus` erfolgt erst über `Weiter`.
- Restore-Schrittleiste visuell überarbeitet: umrahmte, abgerundete Schritt-Badges mit klarer aktiver Hervorhebung.

###2026.05.21.1538###
- Browse-&-Restore Bezeichnungen wiederhergestellt (Seite + Navigation auf `Browse & Restore`).
- Auswahl-Darstellung im Restore-Assistenten erweitert: Typ (`Datei`/`Verzeichnis`), Pfad und kurzer Wirkhinweis werden explizit angezeigt.
- Aktion `Auswahl entfernen` ergänzt: setzt die Auswahl zurück und führt kontrolliert in den Auswahl-Schritt zurück.

###2026.05.21.1529###
- Restore-Bereich als geführter Assistent umgebaut: feste Schrittfolge `Job → Archiv → Auswahl → Ziel & Modus → Prüfen & Start`.
- Neue Schrittleiste mit Vor/Zurück-Navigation statt verteiltem Einzel-Flow.
- Auswahl wird im Schritt `Auswahl` getroffen und als `Ausgewählt` sichtbar gehalten.
- Start-Validierung bleibt strikt: vollständige Auswahl + erfolgreiche Vorprüfung + Bestätigung erforderlich.

###2026.05.21.1521###
- Restore-Seite UX überarbeitet: klarer 2-Schritt-Ablauf (`1. Backup durchsuchen`, `2. Wiederherstellen`) mit rein deutschen Bezeichnungen.
- Neuer Block `Aktuelle Auswahl` zeigt Job, Archiv, Auswahlanzahl und Zielordner direkt im Wiederherstellungsbereich.
- Startlogik gehärtet: `Wiederherstellen starten` nur bei vollständiger Auswahl + erfolgreicher Vorprüfung + Bestätigung.
- Texte im Restore-Flow vereinheitlicht (`Vorprüfung`, `Testlauf`, `Wiederherstellen`).

###2026.05.21.1358###
- Wizard-Runner USB-Fix: bei `location=usb` wird vor `borg create` jetzt explizit der USB-Mount über das USB-Profil geprüft.
- Fehlender USB-Mount führt damit zu sauberem Skip (statt `Repository ... does not exist` mit Exit 2).

###2026.05.21.1351###
- USB/Parity-Skip robust gemacht: Skip-Status wird jetzt auch dann als `.status` gespeichert, wenn der Skip außerhalb des `with BackupJob(...)`-Kontexts ausgelöst wird.
- Doppelte Skip-Status-Dateien verhindert: Skip-Status wird pro Lauf nur einmal geschrieben.

###2026.05.21.1345###
- Dashboard-Summary korrigiert: `Warnungen` zählt nicht mehr zusätzlich `Übersprungen`; `skipped` bleibt separat.

###2026.05.21.1325###
- Skip-Läufe als eigener Status `skipped` umgesetzt (inkl. `skip_reason_code`/`skip_reason_text` in Status-Dateien).
- Parity/USB-Skips schreiben jetzt reguläre `.status`-Einträge und erscheinen damit in History/Dashboard statt nur als Mini-Log.
- History erweitert: neuer Statusfilter `Übersprungen`, Badge-Label angepasst und Skip-Grund im Detail sichtbar.
- Dashboard/Jobs erweitert: `Übersprungen` als eigener Status inkl. Anzeige des Skip-Grundes.
- Reports/Mail-Statusmapping ergänzt: `skipped` wird konsistent dargestellt.

###2026.05.21.1306###
- Parity-Skip im Live-Log präzisiert: bei aktiver Parity wird jetzt explizit `Backup wird übersprungen` inkl. Aktion/Fortschritt geloggt.

###2026.05.21.1302###
- Wizard-Runner Parity-Handling gefixt: `ABORT_ON_PARITY_CHECK` wird jetzt ausgewertet statt Parity immer zu prüfen.
- Bei deaktiviertem Parity-Abbruch läuft der Job nach SMB-Mount/Repo-Init wieder in die eigentliche Backup-Phase (`Validierung`/`borg create`) weiter.
- Runner-Logging ergänzt: klare Statuszeile, ob der Parity-Check aktiv oder deaktiviert ist.

###2026.05.21.1016###
- Import/Export UI vereinfacht: reduziert auf 6 Aktionen (Jobs Export/Vorschau/Import, SMB Export/Vorschau/Import).
- Vorschau-Zustände entkoppelt: Laden einer Jobs-Vorschau leert SMB-Vorschau und umgekehrt (keine gemischte Anzeige mehr).
- Dateiauswahl gehärtet: Typ-Präfix-Prüfung für verschlüsselte Dateien (`bbui-jobs-secure-*`, `bbui-profile-secrets-*`) mit klarer Fehlermeldung bei falscher Datei.

###2026.05.21.0941###
- Jobs-Import/Export erweitert: neuer verschlüsselter Jobs-Bundle-Flow (`bbui-job-bundle-secure-v1`) inkl. Job-Passphrase-Dateien.
- Neue API-Endpunkte für verschlüsselte Job-Bundles: `/api/settings/jobs-export-secure`, `/api/settings/jobs-import-secure-preview`, `/api/settings/jobs-import-secure`.
- Secure-Import stellt Job-Passphrases nach dem Import automatisch mit Dateirechten `0600` wieder her.
- SMB/SSH-Secrets-Import erweitert: manuelle Profil-Zuordnung pro Secret-Eintrag (`map-to-profile`) im Vorschau-Dialog.

###2026.05.21.0906###
- Import/Export erweitert: neuer zweistufiger SMB/SSH-Secrets-Flow mit separatem, verschlüsseltem Paket (`bbui-profile-secrets-v1`).
- Neues `manifest`-basiertes Mapping über `profile_type + profile_key + secret_type` (kein Dateinamen-Match).
- Neue API-Endpunkte: `/api/settings/profile-secrets-export`, `/api/settings/profile-secrets-preview`, `/api/settings/profile-secrets-import`.
- Settings-UI erweitert: Vorschau- und Selektionsdialog für SMB/SSH-Secrets mit Status (`vorhanden`, `abweichend`, `fehlt`, `Profil fehlt`) und Importmodus `skip|overwrite`.

###2026.05.21.0839###
- Issue #6 Testabdeckung ergänzt: neue `unittest`-Contract-Tests für API-Fehler/Logging (`tests/test_issue6_api_contract.py`).
- Abgedeckt sind u. a. Secret-Maskierung, Kontext-Auflösung (Body/Query), Exception→HTTP-Mapping und `X-Request-Id`-Header im Erfolgsfall.

###2026.05.21.0028###
- Logging-Kontext erweitert: `job_key`, `profile_key`, `location` werden jetzt zusätzlich aus Query-Parametern gelesen.
- `GET /api/jobs/running` ergänzt im Erfolgslog automatisch laufende `job_key`-Werte (falls vorhanden).

###2026.05.21.0021###
- Issue #6 Logging erweitert: strukturierte Erfolgslogs (`API ok`) mit `request_id`, HTTP-Methode/Pfad, Laufzeit (`duration_ms`), Response-Größe und Kontext (`job_key`, `profile_key`, `location`).

###2026.05.21.0016###
- Issue #6 Logging-Hardening: Secret-Maskierung jetzt auch auf Error-Log-Kontextfelder angewendet (`job_key`, `profile_key`, `location`).

###2026.05.21.0000###
- API-Fehlerformat vereinheitlicht (P0): Responses liefern jetzt `code`, `message`, `details`, `request_id` (zusätzlich weiterhin `error` für Kompatibilität).
- API-Fehlerbehandlung erweitert: `ValueError→400`, `FileNotFoundError→404`, `PermissionError→403`, sonst `500`.
- Fehler-Logging verbessert: `request_id` + Kontext (`job_key`, `profile_key`, `location`) und einfache Secret-Maskierung für Fehlermeldungen.

###2026.05.20.2324###
- SMB-Profile Check: Schrittreihenfolge angepasst auf `Port → Auth → Temporärer Mount → Share → Schreibtest → Unmount`.
- SMB-Profile Check: Nach erstem Fehler werden nachfolgende Schritte als `Nicht getestet` angezeigt statt als `Fehler`.

###2026.05.20.2316###
- SMB-Profile UI: Statusindikator neben `Entfernen` entfernt (keine doppelte OK/Fehler-Anzeige mehr).
- SMB-Profile Check: `Temporärer Mount möglich` zeigt im Fehlerfall nur noch `Fehler - SMB Test-Mount fehlgeschlagen`; technische Details bleiben unter `Details anzeigen`.
- SMB-Profile Check: Zeilenabstände und Umbruch bei Fehlermeldungen verbessert.

###2026.05.20.2307###
- SSH-Profile UI: Erfolgstextbox unter den Check-Aktionen entfernt (keine Doppelinfos mehr); nur der SMB-Stil-Prüfblock bleibt als Statusanzeige.
- SSH-Profile UI: Card-Titel auf `SSH Setup & Check` angepasst.

###2026.05.20.2305###
- SSH-Profile UI: Erfolgstextbox unter den Check-Aktionen entfernt (keine Doppelinfos mehr); nur der SMB-Stil-Prüfblock bleibt als Statusanzeige.
- SSH-Profile UI: Card-Titel auf `SSH Setup & Check` angepasst.

###2026.05.20.2257###
- SSH-Profile UI: widersprüchliche Doppel-Statusanzeige entfernt; es bleibt nur noch der echte Prüfblock (SMB-Stil) als Statusquelle.

###2026.05.20.2251###
- SSH-Storage-Test: störende OpenSSH-Noise-Zeilen zu `known_hosts ... Operation not permitted` werden aus den Detailmeldungen gefiltert; angezeigt werden nur relevante Fehlerursachen.

###2026.05.20.2244###
- SSH-Profile Statusdarstellung an SMB-Design angeglichen: strukturierte Check-Zeilen mit `OK/Fehler` und Kurztext je Prüfschritt.
- SSH-Profile: `Details anzeigen` für Test-/Diagnoseausgaben ergänzt.

###2026.05.20.1628###
- Storagebox-Wizard Persistenz verbessert: Bei `ssh://`-Repo-URIs ohne User wird beim Speichern jetzt der User aus dem gewählten Storage-Profil in die URI geschrieben (`user@host`).

###2026.05.20.1621###
- SSH-Setup UI: `Status prüfen` führt keinen Verbindungstest mehr aus, sondern prüft nur Key/Public-Key (manueller Test bleibt über `Verbindung testen`).
- SSH-Setup UI: Zieltyp-Hinweise/Override entfernt, Oberfläche vereinfacht.
- SSH-Setup UI: Klarere Statusbezeichnung (`SSH-Setup Status`).

###2026.05.20.1609###
- UI Einstellungen/SSH-Profile: Tab von `Storagebox` auf `SSH-Profile` umbenannt.
- UI Einstellungen/SSH-Profile: `Zugangsdaten`-Card entfernt (Datenpflege erfolgt über Storage-Profile).
- UI Einstellungen/SSH-Profile: Setup-Bereich verschlankt (kompakter Status + `Verbindung testen` direkt bei den Aktionen).

###2026.05.20.1552###
- Storage-Profile erweitert: pro Profil kann jetzt ein eigener SSH-Key-Pfad (`ssh_key_path`) gepflegt werden.
- Storagebox-Setup-Aktionen (Key-Status/Erzeugen/Public/Deploy/Test) arbeiten jetzt profilbezogen statt nur mit globalem `BORG_SSH_KEY`.
- Einstellungen/Storagebox UI ergänzt: Profilauswahl im Setup sowie SSH-Key-Feld direkt im Storage-Profil.

###2026.05.20.1211###
- Jobs-Import erweitert: Settings-Payload (USB/SMB-Profile) mit Vorschau und Modusauswahl (`ignore`/`merge`/`replace`).
- Standardverhalten ist jetzt `merge` mit `skip` bei Konflikten; Konflikte können pro Profil auf `overwrite` oder `rename` gestellt werden.
- Vor dem Anwenden von Settings aus dem Import wird automatisch ein `settings.json`-Backup erzeugt; Import-Ergebnis zeigt Applied/Conflict-Zähler.

###2026.05.20.1154###
- Profile-Storage migriert: USB/SMB-Profile werden jetzt in `config/settings.json` gespeichert; Legacy-Keys `USB_PROFILES_JSON`/`SMB_PROFILES_JSON` werden aus `backup.conf` entfernt.
- Settings-API/Runtime vereinheitlicht: Lesen/Schreiben der Profile läuft zentral über `settings.json` (inkl. SMB-Mount-Workflows).
- Jobs Export/Import erweitert: Bundle enthält jetzt zusätzlich `settings_payload` (SMB/USB-Profile), Import kann diese wiederherstellen.
- Config-Backups bleiben change-basiert: Snapshot nur bei tatsächlicher Dateiänderung (kein Backup bei No-Op-Migrationen).

####2026.05.20.1018####
- SMB-Profil-Löschdialog an Job-Löschstil angenähert: Warnhinweis + Optionen + Bestätigungseingabe in einem Dialog, roter `Löschen`-Button.

####2026.05.20.1004####
- SMB-Profil-Entfernen UX überarbeitet: ein kombinierter Dialog (Unmount, Mountpunkt-Cleanup, Credentials-Cleanup) statt mehrerer Abfragen; Entfernen speichert danach direkt, damit Profile nach Refresh nicht wieder erscheinen.

####2026.05.20.0957####
- SMB-Profil-Entfernen erweitert: optionales Löschen der Credential-Datei (`.smb-<key>.cred`) ergänzt, separat auswählbar und explizit bestätigungspflichtig.

####2026.05.20.0950####
- SMB-Profil-Entfernen in den Einstellungen nutzt jetzt den bestehenden UI-Dialog statt Browser-`alert`/`confirm` (konsistenter Dialog-Flow inkl. optionalem Mountpunkt-Cleanup).

####2026.05.20.0900####
- SMB-Profil-Lifecycle: Beim Entfernen eines ungenutzten SMB-Profils kann optional der Mountpunkt mit aufgeräumt werden (nur wenn nicht gemountet und leer).
- Release/MR-Workflow ergänzt: neues Preflight-Skript `plugin/mr-preflight.sh` prüft Delta gegen `origin/main` und Push-Sync, um „MR enthält keine Änderungen“ zu vermeiden.
- Hilfe/Doku ergänzt: SMB-Mountpunkt-Verhalten nach Unmount und empfohlener Cleanup dokumentiert.

####2026.05.20.0822####
- Systemzustand/CIFS-Check verbessert: gilt als OK, wenn CIFS bereits geladen oder als Kernel-Modul verfügbar ist.
- UI-Detailtext für CIFS präzisiert (`geladen` / `verfügbar (lädt beim ersten Mount)` / `fehlt`).

####2026.05.19.2352####
- Hilfe/Doku um SMB erweitert: Quickstart, Wizard-Optionen (`smb`, Mount/Unmount), Storage-Verhalten (Mount als Voraussetzung für Repo-Test) und SMB-Troubleshooting ergänzt.

####2026.05.19.2339####
- Storage/SMB Feintuning: Mount-Status (`Gemountet`/`Nicht gemountet`) steht jetzt in der Profilzeile direkt neben der Share-URL statt darunter.
- Storage/SMB Feintuning: SMB-Repository-Sub-Liste nutzt jetzt denselben grauen Kartenhintergrund wie die übrigen Storage-Listen (kein weißer Block mehr).

####2026.05.19.2332####
- Storage/SMB Layout überarbeitet: SMB-Profilkopf (Share + Mount-Status + Aktionen) und Repository-Liste sind jetzt visuell getrennt, mit klaren Zeilen/Abständen für bessere Lesbarkeit.
- SMB-Repositories werden innerhalb eines eingerückten Sub-Blocks je Profil dargestellt; mobile Darstellung für SMB-Kopfzeile verbessert (Wrap statt Überlauf).

####2026.05.19.2327####
- Storage/SMB neu strukturiert: SMB-Repositories werden jetzt pro SMB-Profil im Storage-Block angezeigt (analog zu Local/USB/Storagebox).
- Repository-Test für SMB erfolgt jetzt auf Repo-Ebene je Eintrag; bei nicht gemountetem Share ist der Test-Button deaktiviert (`Erst SMB mounten`).
- SMB-Mount-Status dient in Storage nur noch als Ausführbarkeits-Voraussetzung (Mount/Unmount separat pro Profil).

####2026.05.19.2316####
- Wizard erweitert: SMB-Mount-Optionen sind jetzt in Schritt 2 sichtbar (`mount_before_run`, `unmount_after_run`) und pro Job speicherbar.
- Wizard-Edit ergänzt: bestehende SMB-Mount-Optionen werden beim Bearbeiten eines Jobs korrekt aus den Metadaten geladen.

####2026.05.19.2311####
- UI-Kosmetik Dashboard/Jobs: Location-Badge für `SMB` ergänzt (`.loc-badge.smb`) und damit optisch an Local/USB/Storagebox angeglichen.

####2026.05.19.2304####
- SMB-Profile UI-Fix: `jobs_count`/`job_refs` bleiben beim Normalisieren der Profil-Daten erhalten; Anzeige `Jobs: X` zeigt jetzt den Backend-Wert korrekt statt immer `0`.

####2026.05.19.2254####
- SMB-Profil-Jobzähler weiter gefixt: berücksichtigt jetzt zusätzlich Legacy-Jobordner `.../jobs` (nicht nur `.../config/jobs`) und zählt dadurch SMB-Jobs auch in älteren/abweichenden Layouts korrekt.
- SMB-Profil-Zuordnung vereinheitlicht: Key-Lookup für `jobs_count` ist jetzt überall case-insensitive.

####2026.05.19.2245####
- SMB-Profil-Counter weiter gehärtet: zusätzliche rekursive Suche nach `config/jobs` unter den üblichen `/boot/config/...`-Roots, um auch abweichende Runtime-Layouts sicher zu erfassen.

####2026.05.19.2242####
- SMB-Profil-Counter gefixt: `Jobs: X` berücksichtigt jetzt zusätzliche Job-Metadatenpfade (canonical, conf-basiert, GLOBAL_DATA_DIR-basiert) für robuste Erkennung in unterschiedlichen Runtime-Layouts.

####2026.05.19.2233####
- SMB-Profil-Jobcounter korrigiert: SMB-Jobs werden jetzt auch dann korrekt zugeordnet, wenn der Repo-Pfad über `repo.conf_key` aus `backup.conf` aufgelöst wird.

####2026.05.19.2222####
- Storage/SMB UI-Kosmetik: Mount-Status als kompaktes Badge statt breitem Balken.
- Storage/SMB: Test-/Action-Status bleibt pro Profil nach Refresh sichtbar.
- Storage/SMB: eigene Farbgebung analog zu Lokal/USB/Storagebox ergänzt.

####2026.05.19.2215####
- SMB-Profil-Zuordnung gehärtet: Job-Nutzung wird robuster erkannt (inkl. Repo-/Mount-Pfad-Matching), damit `Jobs: X` korrekt angezeigt wird.
- History-Filter erweitert: Location unterstützt jetzt `SMB` und `Custom`; Typ-Filter ergänzt um `Custom`.
- Storage erweitert um eigene SMB-Rubrik mit Profilstatus (gemountet/nicht gemountet) und Aktionen `Mount`, `Unmount`, `Test`.
- Neuer API-Endpoint für SMB-Storage-Aktionen: `POST /api/storage/smb-action`.
- Restore-Tests erweitert: Location `SMB` verfügbar und optionale Auto-Mount/Unmount-Logik pro SMB-Joblauf ergänzt.

####2026.05.19.2151####
- SMB integriert in Restore/Browse/Manual-Check: SMB-Jobs stellen den Mount jetzt auch außerhalb des Runners sicher.
- SMB-Job-Optionen `mount_before_run` und `unmount_after_run` ergänzt (Wizard-Metadaten + Runner-Verhalten).
- Systemzustand erweitert: Prüft Verfügbarkeit von `mount/umount` und CIFS-Unterstützung.
- Secrets-Transfer erweitert: Export/Import umfasst jetzt auch SMB-Credential-Dateien (`.smb-*`).
- Jobs/Dashboard: eigener Location-Abschnitt für SMB-Jobs.
- SMB-Profil-Löschschutz: Entfernen blockiert, wenn Profile noch von Jobs referenziert werden (inkl. UI-Hinweis).

###2026.05.19.2151###
- Release mit SMB-Integrations- und Konsistenzfixes (Restore/Check, Profile-Lifecycle, Systemchecks, UI-Gruppierung).

###2026.05.19.2016###
- SMB-Portcheck ohne `nc` umgesetzt (native Python-Socket-Pruefung auf TCP 445), damit auf Unraid ohne Netcat keine Fehlermeldung mehr entsteht.

###2026.05.19.2011###
- SMB-Statuspruefung gefixt: `checks`-Feld wird wieder korrekt im SMB-Resultat geliefert (Fehler `checks` behoben).
- SMB-Profil-Zeile kompakter gestaltet (kleinere Feld-/Button-Hoehen, engere Abstaende, bessere Breitenverteilung).

###2026.05.19.2003###
- SMB-Profile in Einstellungen kompakter gestaltet: Pflichtfelder jetzt in einer Zeile.
- Optionale SMB-Felder (`vers`, `sec`) als einklappbarer Bereich pro Profil umgesetzt.
- SMB-Statuspruefung erweitert: pro Profil klare Pruefmatrix (Port/Auth/Share/Mount/Write/Unmount) mit Details-Ansicht.

###2026.05.19.1920###
- SMB-Mount-Optionen erweitert: Profilfelder `vers` (Default `3.0`) und `sec` (optional) hinzugefuegt.
- SMB-Test-Mount nutzt jetzt `vers/sec`; bei Fehlern wird die Rueckmeldung pro getesteter SMB-Version klar angezeigt.
- Share-Normalisierung gehaertet (`share` ohne fuehrenden Slash), um `Invalid argument` bei `mount.cifs` zu vermeiden.

###2026.05.19.1915###
- SMB-Statuscheck erweitert: wenn der Pfad nicht gemountet ist, wird jetzt ein aktiver Test-Mount (inkl. Schreibtest) ausgefuehrt und anschliessend wieder unmountet.
- Damit kann SMB-Verbindung vor dem Runner-Ende-zu-Ende verifiziert werden.

###2026.05.19.1905###
- Phase C2 SMB-Runner: `location=smb` mountet SMB vor dem Backup automatisch und unmountet nach dem Lauf (inkl. Cleanup bei Fehlern).
- Locking erweitert: SMB-Profile werden als eigene Resource (`smb-mount:<profile>`) gelockt, um parallele Mount-Races zu vermeiden.
- SMB-Statuscheck legt fehlende Mount-Pfade unter `/mnt/remotes/...` automatisch an (statt hartem Existenzfehler).

###2026.05.19.1840###
- SMB-Profile UX vereinfacht: kein manuelles `password_file`-Feld mehr in der UI.
- Neues SMB-Passwortfeld (maskiert): beim Speichern wird automatisch `/boot/config/borg-backup/secrets/.smb-<key>.cred` erstellt/aktualisiert.
- Bestehende Passwoerter bleiben erhalten, wenn beim Bearbeiten kein neues Passwort eingegeben wird.

###2026.05.19.1827###
- Phase C1 SMB-Profile erweitert: `username` und `password_file` als Pflichtfelder im Settings-Tab.
- SMB-Statuscheck prueft jetzt zusaetzlich Credentials-Datei (existiert/lesbar, `username=` + `password=` vorhanden).
- SMB-Validierung gehaertet: unvollstaendige Profile und nicht-absolute Passwort-Datei werden klar abgefangen.

###2026.05.19.1814###
- Phase B Wizard: neue Location `SMB` mit Profil-Auswahl im Wizard (analog USB).
- Wizard erzeugt Repo-Pfad fuer SMB aus Profil-Mount (`<mount_path>/borg-backup-<type>`), inkl. Validierung bei fehlendem Profil.
- Job-Metadaten erweitert um `smb_profile_key`; Load/Edit setzt SMB-Profil wieder korrekt vor.
- Job/Check-Basiskompatibilitaet: `smb` als gueltige Location in Job-Discovery/Runner zugelassen.

###2026.05.19.1800###
- Phase A SMB-Grundstruktur: neues Settings-Tab `SMB-Profile` mit CRUD, Speicherung in `SMB_PROFILES_JSON` und Basis-Validierung.
- Neuer API-Endpoint `/api/settings/smb-profiles-status` fuer SMB-Profil-Checks (Pfad vorhanden, Verzeichnis, als SMB gemountet).
- `backup.conf`-Defaults und Settings-Output um `SMB_PROFILES_JSON`/`smb_profiles` erweitert.

###2026.05.19.1509###
- Storage-Verbindungstest erweitert: prueft fuer Synology/Generic jetzt zusaetzlich `borg --version` auf dem Zielsystem.
- Bei fehlendem Remote-Borg klare Fehlermeldung: `Remote-Borg fehlt ... borg installiert`.
- UI-Status zeigt neuen Schritt `Borg: OK/FEHLER` in `Status pruefen` und `Verbindung testen`.

###2026.05.19.1445###
- Hotfix Wizard-Vorschau: doppelte `params`-Deklaration in `_wizardPreview()` entfernt (behebt `can't access lexical declaration 'params' before initialization`).

###2026.05.19.1440###
- Wizard: `create_repo_if_missing` ist fuer `storagebox` jetzt standardmaessig aktiv (wie lokal/USB), damit neue Remote-Repositories automatisch initialisiert werden koennen.
- Schutz fuer Remote-Init: Storagebox-Repo-Anlage ist nur mit expliziter Bestaetigung im Wizard erlaubt und wird serverseitig auf gueltige `ssh://`-URI + Basispfad geprueft.

###2026.05.19.1407###
- Deploy-Dialog: `Abbrechen`/`Schließen` erhalten direkten `onclick`-Fallback, damit der Dialog immer reagiert.

###2026.05.19.1401###
- Hotfix Deploy-PTY: interaktiver Key-Deploy nutzt jetzt `pty.fork()` statt `Popen(openpty)`, damit SSH ein echtes controlling TTY erhält.
- Erwartete Wirkung: Passwort-Prompt bleibt interaktiv verfügbar, statt sofortigem `Permission denied`-Abbruch.

###2026.05.19.1354###
- Rebuild-Release nach Merge von MR !275, ohne zusätzliche Codeänderungen.
- Dient als saubere, neu versionierte Testbasis für Deployment-Validierung.

###2026.05.19.1337###
- Hotfix Deploy-Auth: interaktiver SSH-Deploy erzwingt Passwort/Keyboard-Interactive (Pubkey für Deploy-Session deaktiviert), um sofortige `Permission denied`-Abbrüche zu vermeiden.
- Hotfix Deploy-TTY: Deploy-Prozess läuft in eigener Session (`start_new_session`) für stabilere Prompt-Verarbeitung.
- Hotfix Cancel: `Abbrechen` schließt den Dialog sofort lokal und beendet Session asynchron.

###2026.05.19.1331###
- Hotfix interaktiver Key-Deploy: SSH-Start jetzt mit TTY (`-tt`) und Passwort-Authentifizierungsreihenfolge für stabile Prompt-Eingabe.
- Deploy-Dialog: `Senden` meldet jetzt klar, wenn Session bereits beendet ist.
- Deploy-Dialog: `Abbrechen` beendet Session und schließt den Dialog sofort.

###2026.05.19.1319###
- Interaktiver Key-Deploy ohne `sshpass` umgesetzt (TTY-basiert, nur Standardmittel).
- Neuer Deploy-Console-Dialog mit Live-Output, Eingabe, Abbrechen und Abschlussstatus.
- Passwörter werden nur im RAM verarbeitet (kein Speichern/Logging), inkl. Session-Timeout.
- Zieltyp-Override für Deploy ergänzt (Auto/Storagebox/Synology/Generic).

###2026.05.19.1313###
- Storage-Zielerkennung ergänzt: automatische Einordnung in `storagebox`, `synology` oder `generic` (Heuristik + optionaler Probe-Hinweis).
- Storagebox-Setup zeigt den erkannten Zieltyp inkl. Erkennungshinweis im UI.
- Status/Verbindungstest-Ausgabe enthält jetzt zusätzlich den erkannten Zieltyp.

###2026.05.19.1203###
- Hotfix Wizard USB-Hinweis: korrekte Warnklasse (`warning-state`) gesetzt, damit die farbliche Hervorhebung sichtbar ist.

###2026.05.19.1158###
- Wizard USB-Hinweis: „Kein USB-Profil vorhanden …“ wird jetzt als auffällige Warnbox dargestellt.
- Bei vorhandenem Profil bleibt der Hinweis kompakt als normaler Info-Text.

###2026.05.19.1151###
- Wizard: Validierungs-Hinweise (z. B. leere Pflichtfelder) deutlich hervorgehoben.
- Fehlertexte im Wizard jetzt kompakt mit farbigem Hintergrund/Border statt unauffälligem Standardtext.

###2026.05.19.1136###
- USB-Profile: Warnhinweis nur noch bei wirklich leerer Profil-Liste; Tab-Reihenfolge angepasst (nahe Storagebox).
- USB-Profile: Neuer **Status prüfen**-Check (Pfad vorhanden, Verzeichnis, gemountet) mit Ergebnis pro Profil.
- Wizard/Job-Metadaten: `usb_profile_key` wird gespeichert und beim Bearbeiten für die Vorauswahl genutzt.
- Konfig-Schreiben gehärtet: Werte werden robust gequotet (fix für JSON-Strings wie `USB_PROFILES_JSON`).

###2026.05.19.1116###
- Settings: Neuer Reiter **USB-Profile** (mehrere Profile mit Name + Mount-Pfad).
- Wizard: Bei `Location=USB` Profil-Auswahl per Dropdown; Repository-Pfad wird automatisch aus Profil + Typ gebaut.
- Wizard-Validierung: USB-Jobs werden blockiert, solange kein USB-Profil angelegt ist.

###2026.05.19.1013###
- Hilfe/Doku: Quickstart deutlich erweitert (Einstellungen, Job-Anlage, Zeitplan, Erstlauf, History/Berichte).
- Hinweise im Doku-Teil präzisiert (u. a. Python-Hinweis für Unraid CA).

###2026.05.19.0916###
- Neue Seite **Hilfe & Dokumentation** in der UI ergänzt.
- Doku wird aus `ui/docs/help.md` geladen und im UI gerendert.
- Unterstützt visuelle Inhalte: Bilder per Markdown `![Alt](/ui/docs/images/...png)`.

###2026.05.19.0901###
- Control Page: Direkten Installations-Link für Python entfernt.
- Hinweis bleibt erhalten: `Python 3 for Unraid` bitte über Unraid-Apps installieren.

###2026.05.19.0851###
- Control Page: Prüft nun, ob `python3` vorhanden ist.
- Zeigt bei fehlendem Python eine klare Warnung inkl. Hinweis auf Plugin `Python 3 for Unraid`.
- Start/Restart sind auf der Control Page deaktiviert, solange Python 3 fehlt (zusätzlich serverseitig abgefangen).

###2026.05.15.2207###
- Storagebox-Setup-Flow nachgeschärft: weniger Doppelinfos und klarere Aktionsergebnisse.
- `Status prüfen` führt Gesamtcheck aus (Key/Public + Verbindung) mit eindeutiger OK/FEHLER-Zusammenfassung.
- `Key erzeugen` zeigt stabile Rückmeldung; `Public Key` ist jetzt ein Toggle (anzeigen/ausblenden).
- `Verbindung testen` liefert klar getrennte, eindeutige Ausgabe.

###2026.05.15.2215###
- Phase 4 Import/Export 2.0:
  - Jobs-Import Vorschau mit Jobliste (Name, Typ, Location, Schedule, Features).
  - Konfliktstrategie pro Job (skip/overwrite/rename) + selektiver Job-Import.
  - Passphrase-Konflikte sichtbar (vorhanden/fehlt/abweichend) via SHA256-Metadaten.
  - Secrets-Backup Vorschau + selektiver Import (pro Datei).
  - Neue Endpoints: `/api/settings/jobs-import-preview`, `/api/settings/secrets-backup-preview`.

###2026.05.15.2222###
- Phase 5 Wizard UX:
  - Beschreibungshinweis verkürzt auf „Das Feld Beschreibung erlaubt Markdown.“
  - Info-Button am Beschreibungsfeld ergänzt.
  - Hilfe-Dialog mit Markdown-Basics und Beispieltext.

###2026.05.15.2236###
- Wizard Quellpfade: Autocomplete für Verzeichnisse unter `/mnt` ergänzt.
- Enter übernimmt den aktuellen Vorschlag als Pfad; Einträge erscheinen als entfernbarer Chip.
- Serverseitige Validierung ergänzt: Quellpfad muss existieren und ein Verzeichnis sein.

###2026.05.15.2244###
- Release fuer gemergten Fix: stabile Hoehe im Quellpfad-Autocomplete des Wizards (kein springendes Vorschlagsfenster).

###2026.05.15.2249###
- Wizard Quellpfad-Autocomplete: Vorschlagsfenster reserviert nun immer denselben Platz (kein Layout-Sprung beim Tippen).

###2026.05.15.2254###
- Wizard-Dialog: einheitliche Schrittgroesse eingefuehrt (orientiert an Schritt 2), kein Groessenwechsel zwischen Schritt 1–7.
- Ueberlauf wird innerhalb des Schrittbereichs gescrollt statt die Modalhoehe zu veraendern.

###2026.05.15.2258###
- Wizard Schritt 2: deutlicher Scroll-Hinweis ergänzt, damit weitere Einstellungen sofort erkennbar sind.

###2026.05.15.2311###
- Wizard Quellpfad-Autocomplete:
  - sichtbare Vorschau auf 4 Eintraege begrenzt
  - Pfeiltasten-Navigation scrollt den aktiven Eintrag automatisch ins Sichtfeld

###2026.05.15.2324###
- Wizard Quellpfad-Autocomplete: Vorschlagslimit von 25 auf 100 erhoeht, damit alle Verzeichnisse unter /mnt/user sichtbar sind.

###2026.05.15.2330###
- <Kurzänderung 1>
- <Kurzänderung 2>

###2026.05.15.2156###
- Settings-Design-Polish für Phase 3: Tabs visuell überarbeitet (Hover/Active/Focus, Dark/Light konsistent).
- Storagebox-Setup als klarere Step-Karten mit Status-Badges (OK/Offen) und strukturierterer Aktionsleiste.

###2026.05.15.2145###
- Release für gemergte Phase-3-Änderungen bereitgestellt (Settings-Tabs, Storagebox-Setup-UX, UI-Dialoge statt prompt/confirm).

###2026.05.15.2135###
- Phase 2 gestartet:
  - History-Pagination (20 Einträge/Seite) mit Zurück/Weiter.
  - Jobs: `enabled` vollständig nutzbar (Aktivieren/Deaktivieren im Menü, deaktivierte Jobs nicht startbar, Schedule wird beim Deaktivieren abgeschaltet).
  - Job-Löschdialog erweitert: optional nur Job löschen oder zusätzlich Artefakte (Status/Logs/Restore-Test) entfernen.

###2026.05.15.2128###
- Nachschärfung Weekly-Snapshot: Wochenbericht erzwingt Snapshot-Write (`force_snapshot_write`) vor dem Mailversand, auch wenn sich Größenwerte nicht geändert haben.

###2026.05.15.2121###
- Fix Nachschärfung: Wochenbericht erzwingt jetzt Snapshot-Write auch ohne Größenänderung (`force_snapshot_write`), damit sich `weekly-snapshots.json` beim Versand sicher aktualisiert.

###2026.05.15.2118###
- Weekly-Report Endpoint aktualisiert vor dem Versand jetzt aktiv die Statusdaten.
- Dadurch wird `weekly-snapshots.json` beim manuellen/cron-basierten Wochenbericht zuverlässig mitgeschrieben.

###2026.05.15.2111###
- Fix `weekly-snapshots.json`: Snapshot-Datei wird wieder zuverlässig geschrieben.
- Snapshot-Pfad standardisiert auf `${STATUS_DIR}/../weekly-snapshots.json` und parallel kompatibel im Legacy-Pfad `${STATUS_DIR}/weekly-snapshots.json` gepflegt.
- Lesen nutzt primär neuen Pfad und fällt auf Legacy-Datei zurück.

###2026.05.15.2104###
- Performance: neuer schlanker Endpoint `/api/setup-status`; Dashboard/Jobs nutzen keinen teuren `/api/settings`-Call mehr für Setup-Gates.
- Restore-Tests Phase 1:
  - Manueller Start läuft jetzt immer sofort (`--force`), Intervall-Check wird nur für geplante Läufe genutzt.
  - Restore-Test-Einträge können pro Job in der UI gelöscht werden.
  - Beim Job-Löschen wird die zugehörige `*.test` Datei mit entfernt.
  - Start-Dialog zeigt bei Einzelauswahl konkrete Jobnamen statt nur „X ausgewählte Jobs“.

###2026.05.13.2255###
- Fix Storagebox-Verbindungstest: Shell-Schreibtest normalisiert `STORAGEBOX_BASE_PATH` für Restricted-Shell korrekt.
- Borg-URI mit `/./...` bleibt unverändert; Test-Kommandos nutzen kompatiblen relativen Pfad.

###2026.05.13.2247###
- Fix Storagebox-Verbindungstest: Ergebnis-/Fehlermeldung bleibt sichtbar und wird nicht mehr durch automatisches Settings-Refresh sofort ausgeblendet.

###2026.05.13.2243###
- Hotfix: Unaufgelöste Merge-Konfliktmarker in der Plugin-XML (`.plg`) entfernt.
- Behebt Update-Erkennung/Parsing in Unraid.

###2026.05.13.2236###
- Storagebox-SSH-Auth-Status robuster gemacht: Login gilt als OK, solange keine expliziten Auth-/Netzwerkfehler erkannt werden.
- OpenSSH-PQ-Warnung wird als Hinweis behandelt und blockiert den Setup-Status nicht mehr.

###2026.05.13.2228###
- Storagebox-Verbindungstest auf bestätigte Kommandoliste gehärtet: `mkdir`, `touch`, `stat`, `rm`, `rmdir`.
- Verbessert die Zuverlässigkeit des Schreibtests auf der eingeschränkten Storagebox-Shell.

###2026.05.13.2218###
- Fix Storagebox-Assistent: SSH-Auth-Test nutzt jetzt Storagebox-kompatiblen Befehl (`help`) statt `true`.
- Verbindungstest auf kompatiblen Schreibtest umgestellt (`mkdir` + `rmdir` Probeverzeichnis).
- Behebt Statusfehler „Command not found“ bei Hetzner Storagebox.

###2026.05.13.2213###
- Phase B Storagebox-Assistent ergänzt:
  - SSH-Key prüfen/erzeugen, Public Key anzeigen, optional Key-Deploy via Passwort, Verbindungstest.
- Neue API-Endpoints: `/api/storagebox/key-status`, `/api/storagebox/key-generate`, `/api/storagebox/key-public`, `/api/storagebox/key-deploy`, `/api/storagebox/test`.
- Setup-Statusanzeige in Einstellungen + Wizard-Hinweis um SSH-Status erweitert.

###2026.05.13.2204###
- Phase A Storagebox UX: Profilfelder ergänzt (`STORAGEBOX_HOST`, `STORAGEBOX_PORT`, `STORAGEBOX_USER`, `STORAGEBOX_BASE_PATH`).
- Wizard baut bei `location=storagebox` die Repository-URI automatisch aus dem Profil.
- Technisches Repo-Feld für Storagebox auf readonly, inkl. klarer Hinweis bei unvollständigem Profil.
- Step-2-Validierung blockiert mit verständlicher Fehlermeldung, wenn Storagebox-Profil unvollständig ist.

###2026.05.13.2200###
- Hotfix Jobs-Laden: `iconKey` wieder korrekt lokal in `renderJobCard()` initialisiert.
- Versehentliche globale `iconKey`-Deklaration entfernt (behebt `can't access lexical declaration ... before initialization`).
###2026.05.13.2141###
- Hotfix Jobs-Seite: JS-Fehler `can't access lexical declaration 'iconKey' before initialization` behoben.
- `iconKey` wird wieder korrekt in `renderJobCard()` initialisiert; fehlerhafte globale Deklaration entfernt.

###2026.05.13.2137###
- Fix Jobs-Icon Regression: bei ungültigem `job.icon` wird wieder korrekt auf Typ-Icon (`backup_type`) zurückgefallen.
- Wizard speichert bei „Automatisch“ kein erzwungenes Icon mehr und lädt fehlende Icons als leer (Auto-Modus).

###2026.05.13.1811###
- Wizard: Live-Icon-Vorschau ergänzt (sofortige Anzeige der gewählten/automatischen Icon-Auswahl).
- Icon-Liste erweitert (u. a. Datenbank, Server, Home, Musik, Video, Dokumente, Code, Kamera, USB, Sicherheit).
- Jobs behalten bestehendes Verhalten mit Fallback auf Typ-Icon, wenn kein eigenes Icon gesetzt ist.

###2026.05.13.1806###
- Fix: `/api/jobs` HTTP 500 nach Icon-Feature behoben.
- Ursache: interner Job-Factory-Aufruf mit `icon=...`, aber Funktionssignatur ohne `icon`-Parameter.
- Job-Laden funktioniert wieder, Icon-Metadaten werden korrekt übernommen.

###2026.05.13.1804###
- Jobs/Wizard: Icon-Auswahl ohne Zusatzabhängigkeiten ergänzt.
- Gewähltes Icon wird im Job-Metadatenfile gespeichert (`icon`) und in der Jobs-Ansicht verwendet.
- Fallback bleibt der Typ-basierte Standard (wenn kein Icon gewählt ist).

###2026.05.13.1757###
- Storage-Ampel vollständig zurückgebaut (API/Backend/UI), da Laufzeiten in der Praxis zu hoch waren.
- Storage nutzt wieder den bisherigen schnellen, manuellen Repository-Test über den Test-Button.

###2026.05.13.1711###
- Theme Slice 2: Light-Theme-Kontrast verbessert (Status-/Location-Badges, Running-Outline, Status-Box-Border, Job-Description-Farbe, Dropdown-Schatten).
- Mehr harte Farbwerte auf Theme-Variablen umgestellt für konsistentes Dark/Light-Verhalten.

###2026.05.13.1703###
- Theme Slice 1: Umschaltbares UI-Theme (Dunkel/Hell/System) ergänzt.
- Theme-Präferenz wird lokal gespeichert (`localStorage`) und beim Start angewendet.
- Grundlegende Light-Theme-Tokens in `ui/style.css` ergänzt.

###2026.05.13.1655###
- Fix Jobs-Empty-State: Button `Ersten Job erstellen` erhält zusätzlich eine direkte Click-Bindung als Fallback.
- Damit öffnet der Wizard auch dann zuverlässig, wenn die delegierte Event-Bindung in Ausnahmefällen nicht greift.

###2026.05.12.2037###
- Phase 4 Slice 11: Restore-Tests-Details und Core-Settings-Link auf Event-Delegation umgestellt.
- Inline-`onclick` in Restore-Tests-Zeilen/Eintragsheadern entfernt (`data-rt-action` + `onRestoreTestsContentClick()`).
- Setup-Warnhinweis-Link nutzt jetzt `data-core-action="goto-settings"` statt Inline-JavaScript.

###2026.05.12.2027###
- Phase 4 Slice 10: Storage- und Settings-Aktionsbuttons auf Event-Delegation umgestellt.
- Inline-`onclick` in `storage.js`/`settings.js` entfernt (Repo-Test, Import/Export, Config-Backups, SMTP-Test, Weekly-Report-Senden).
- Aktionen laufen über `data-storage-action`/`data-settings-action` und zentrale Click-Handler.

###2026.05.12.2020###
- Phase 4 Slice 9: History-Tabelle auf Event-Delegation umgestellt.
- Inline-`onclick` für Zeilen-Expand und Log-Öffnen entfernt.
- Aktionen laufen über `data-history-action` + `onHistoryContentClick()`.

###2026.05.12.2014###
- Phase 4 Slice 8: Browse-&-Restore-Breadcrumb und Dateiliste auf Event-Delegation umgestellt.
- Inline-`onclick` entfernt; Aktionen laufen über `data-restore-action` + `onRestoreBrowserClick()`.
- Verhalten unverändert (Browse/Download/Restore), aber stabilere Entkopplung bei dynamischem Rendern.

###2026.05.12.1938###
- Phase 4 Slice 7: Job-Karten-Aktionen auf Event-Delegation umgestellt (`data-jobs-action` + `onJobsGridClick()`).
- Inline-`onclick` in der generierten Jobs-HTML entfernt (Start/Log/Menu/Edit/Adopt/Schedule/Delete).
- Verhalten unverändert, aber sauberere Trennung zwischen Markup und Event-Logik.

###2026.05.12.1925###
- Phase 4 Slice 6: Confirm-Modal im Jobs-Bereich auf zentralen Action-State (`start`/`delete`) umgestellt.
- Kein dynamisches Umschalten von `modal-confirm-btn.onclick` mehr; Primäraktion läuft über `confirmModalPrimaryAction()`.
- Enter-Handling im Confirm-Input nutzt denselben Dispatch-Pfad.

###2026.05.12.1911###
- Wizard-Fix: Passphrase-Button `Kopieren` mit robustem Fallback (auch ohne `navigator.clipboard`/Secure Context).
- Restore-Tests: `Jetzt testen` nutzt nun ein UI-Confirm-Modal statt Browser-Standarddialog.

###2026.05.12.1857###
- Phase 4 Slice 5: Verbleibende Inline-Event-Handler aus `ui/index.html` entfernt.
- Zentrale Event-Bindings in `_initApp()` für Wizard-, Schedule-, Restore-Tests-, Jobs-Log- und Settings-Aktionen ergänzt.
- Verhalten unverändert, aber sauberere Event-Struktur und weniger Global-HTML-Kopplung.

###2026.05.12.1847###
- Fix Wizard-Speicherpfad: Job-Metadaten werden beim Editieren/Speichern jetzt immer in den kanonischen Jobs-Pfad unter `/boot/config/borg-backup/config/jobs` geschrieben.
- Damit werden Description-Aenderungen zuverlaessig im richtigen Job-JSON persistiert (auch bei Runtime-Script-Pfaden).

###2026.05.12.1838###
- Wizard-Fix: Beschreibung wird beim Bearbeiten jetzt zuverlässig gespeichert, auch wenn der Job initial ohne Beschreibung angelegt wurde.
- Ursache war ein Race beim asynchronen Vorbefüllen; das Formular ist während des Ladens jetzt kurz deaktiviert.

###2026.05.12.1818###
- Phase 4 Slice 4: Inline-Handler für Wizard-/Schedule-Modal-Buttons entfernt.
- Frequency-/Wochentag-Buttons (Wizard + Schedule Modal) zentral per `data-*` und Event-Binding verdrahtet.
- Verhalten unverändert, nur Entkopplung von Inline-JavaScript.

###2026.05.12.1809###
- Phase 4 Slice 3: Inline-Handler im Restore-/Confirm-Modal-Bereich entfernt.
- Event-Binding für Restore-Selektoren, Precheck/Start, Confirm-Checkbox und Modal-Aktionen zentral in `_initApp()`.
- Verhalten unverändert, inkl. Enter-Handling im Delete-Confirm-Input.

###2026.05.12.1802###
- Phase 4 Slice 2: weitere Inline-Handler entfernt (Storage-Check, History-Filter, Berichte-Selektor/Borg-Info-Button).
- Event-Binding dafür zentral in `_initApp()` ergänzt.
- Verhalten unverändert, nur Entkopplung von Inline-JavaScript.

###2026.05.12.1744###
- Phase 4 Slice 1: erste Inline-Handler aus `ui/index.html` entfernt (Navigation, Mobile-Header/-Backdrop, Refresh-Buttons auf Dashboard/Jobs/History).
- Event-Binding dafür zentral in `_initApp()` hinterlegt.
- Verhalten unverändert, nur Entkopplung von Inline-JavaScript.

###2026.05.12.1736###
- Phase D3 Abschluss: Refactor-Status und Restpunkte in `docs/refactor-phase-d.md` dokumentiert.
- Enthält Zielbild, bereits umgesetzte D1/D2-Slices, Global-Kompatibilitätsinventar und nächste Schritte.

###2026.05.12.1729###
- Phase D2 (Slice 4): `wizard.js` schreibt Schedule-Daten bevorzugt über `BBUI.core.*`.
- Globale Fallbacks bleiben aktiv (kompatibler Übergang).
- Keine Funktionsänderung, nur weiterer Entkopplungsschritt.

###2026.05.12.1723###
- Phase D2 (Slice 3): `restore-tests.js` nutzt Schedule-Daten bevorzugt über `BBUI.core.*`.
- Globale Fallbacks bleiben aktiv (kompatibler Übergang).
- Keine Funktionsänderung, nur weiterer Entkopplungsschritt.

###2026.05.12.1716###
- Phase D2 (Slice 2): `dashboard.js` und `jobs.js` nutzen Core-Daten bevorzugt über `BBUI.core.*`.
- Globale Fallbacks bleiben erhalten (kompatibler Übergang).
- Keine Funktionsänderung, nur Entkopplungsschritt.

###2026.05.12.1708###
- Phase D2 (Slice 1): Core-Funktionen zusätzlich unter `BBUI.core.*` registriert.
- Rückwärtskompatibel: bestehende globale Aufrufe bleiben unverändert nutzbar.
- Vorbereitung für weitere Entkopplung ohne Funktionsänderung.

###2026.05.12.1649###
- Phase D1: Core-Navigation/Setup-Gates nach `ui/js/core/app-core.js` ausgelagert.
- Bootstrap lädt jetzt zusätzlich das Core-Modul `ui/js/core/app-core.js`.
- `ui/app.js` ist weiter verschlankt (Shell + Init + Log-Viewer).

###2026.05.12.1633###
- Phase C Core-Cleanup: gemeinsame Format-/DOM-Helper aus `ui/app.js` nach `ui/js/utils/format.js` und `ui/js/utils/dom.js` verschoben.
- Unbenutzten Legacy-Code (`highlightPython`) aus `ui/app.js` entfernt.
- Keine Funktionsänderung, nur strukturelle Bereinigung.

###2026.05.12.1617###
- app.js Refactor Phase B: Dashboard-Logik nach `ui/js/pages/dashboard.js` ausgelagert.
- Bootstrap lädt jetzt zusätzlich das Seitenmodul `ui/js/pages/dashboard.js`.
- Funktionales Verhalten bleibt unverändert (strukturierende Extraktion).

###2026.05.12.1604###
- app.js Refactor Phase B: Jobs-Logik nach `ui/js/pages/jobs.js` ausgelagert.
- Bootstrap lädt jetzt zusätzlich das Seitenmodul `ui/js/pages/jobs.js`.
- Funktionales Verhalten bleibt unverändert (strukturierende Extraktion).

###2026.05.12.1423###
- Fix Job-Erkennung: benutzerdefinierte/neu angelegte Backup-Jobs werden nicht mehr als Utility gefiltert.
- Browse & Restore sowie Manueller Borg Check zeigen diese Jobs wieder korrekt an.

###2026.05.12.1410###
- app.js Refactor Phase B: Wizard-Logik nach `ui/js/pages/wizard.js` ausgelagert.
- Bootstrap lädt jetzt zusätzlich das Seitenmodul `ui/js/pages/wizard.js`.
- Funktionales Verhalten bleibt unverändert (strukturierende Extraktion).

###2026.05.12.1357###
- app.js Refactor Phase B: History-Logik nach `ui/js/pages/history.js` ausgelagert.
- Bootstrap lädt jetzt zusätzlich das Seitenmodul `ui/js/pages/history.js`.
- Funktionales Verhalten bleibt unverändert (strukturierende Extraktion).

###2026.05.12.1353###
- Settings: Nach dem Speichern wird die Liste unter „Config-Backups & Rollback“ sofort neu geladen.
- Neue Backup-Snapshots sind damit direkt ohne Seitenwechsel sichtbar.

###2026.05.12.1343###
- app.js Refactor Phase B: Settings-Logik nach `ui/js/pages/settings.js` ausgelagert.
- Bootstrap lädt jetzt zusätzlich das Seitenmodul `ui/js/pages/settings.js`.
- Funktionales Verhalten bleibt unverändert (strukturierende Extraktion).

###2026.05.12.1323###
- Fix Storage-Test: Passphrase wird jetzt über das passende Job-Metadata aufgelöst (repo-basiert), inkl. `_local`, `_usb`, `_storagebox`.
- Fallback auf globale Legacy-Keys nur, wenn kein passender Job gefunden wird.

###2026.05.12.1310###
- app.js Refactor Phase B: Storage- und Manueller-Borg-Check-Logik nach `ui/js/pages/storage.js` ausgelagert.
- Bootstrap lädt jetzt zusätzlich das Seitenmodul `ui/js/pages/storage.js`.
- Funktionales Verhalten bleibt unverändert (strukturierende Extraktion).

###2026.05.12.1302###
- app.js Refactor Phase B: Berichte-Logik nach `ui/js/pages/reports.js` ausgelagert.
- Bootstrap lädt jetzt zusätzlich das Seitenmodul `ui/js/pages/reports.js`.
- Funktionales Verhalten bleibt unverändert (strukturierende Extraktion).

###2026.05.12.1249###
- app.js Refactor Phase B: Restore-Tests-Logik nach `ui/js/pages/restore-tests.js` ausgelagert.
- Bootstrap lädt jetzt zusätzlich das Seitenmodul `ui/js/pages/restore-tests.js`.
- Funktionales Verhalten bleibt unverändert (strukturierende Extraktion).

###2026.05.12.1225###
- Refactor-Fix: App-Initialisierung läuft jetzt auch, wenn `app.js` nach bereits feuertem `DOMContentLoaded` geladen wird.
- Behebt leeres Dashboard nach UI-Start/F5 im Bootstrap-Loader-Modus.

###2026.05.12.1216###
- app.js Refactor Phase B: Browse & Restore-Logik aus `ui/app.js` nach `ui/js/pages/restore.js` ausgelagert.
- Bootstrap lädt jetzt zusätzlich das Seitenmodul `ui/js/pages/restore.js`.
- Funktionales Verhalten bleibt unverändert (strukturierende Extraktion).

###2026.05.12.1154###
- app.js Refactor Phase A: neues Entry-Script `ui/js/app-main.js` eingeführt.
- Grundstruktur für künftige Module angelegt (`ui/js/api`, `ui/js/utils`).
- `ui/index.html` lädt jetzt den neuen Bootstrap-Entrypoint; Laufzeitverhalten bleibt unverändert.

###2026.05.12.1128###
- Browse & Restore: doppelte Ladeanzeige entfernt (Spinner bleibt, zusätzlicher Text oberhalb entfällt).

###2026.05.12.1112###
- Browse & Restore: beim Laden großer Archive wird jetzt ein sichtbarer Spinner im Dateibereich angezeigt.

###2026.05.12.1108###
- Browse & Restore: neue Option `Original Owner/Group beibehalten` im Restore-Assistent.
- Restore API: `preserve_owner` steuert Metadatenmodus (Backup-Metadaten behalten vs. Zielverzeichnis-Owner/Group).

###2026.05.12.1103###
- Browse & Restore: wiederhergestellte Dateien/Ordner erhalten jetzt rekursiv Owner/Group des Zielverzeichnisses.
- Verhindert `root:root`-Besitz nach Restore bei regulären Share-Zielpfaden.

###2026.05.12.1056###
- Browse & Restore: Dry-Run Ausgabe im Precheck jetzt zusammengefuehrt (stdout+stderr) als ein Block.
- Browse & Restore: Assist-Button-Reihenfolge und Hinweise im Dialog klarer angeordnet.
- Browse & Restore: native Browser-Confirm beim Restore durch UI-eigenes Bestätigungs-Modal ersetzt.

###2026.05.11.1956###
- Einstellungen: Job-Konfigurationen als Bundle exportieren/importieren (Dry-Run + Import-Modi skip/overwrite/rename).
- Einstellungen: verschluesseltes Backup/Wiederherstellung fuer per-Repo Passphrase-Dateien (passwortgeschuetzt).
- Doku: Refactor-Konzept fuer die Aufteilung von `ui/app.js` unter `docs/app-js-refactor-konzept.md`.

###2026.05.11.1939###
- Restore Tests: Detailkarten (Archivinformationen/Testausfuehrung) sprachlich auf Deutsch vereinheitlicht.
- Restore Tests: Tabellenbegriffe vereinheitlicht (`Ort`, `Abdeckung`) fuer konsistentes Wording.
- Restore Tests: Level-3 Bereich umbenannt in `Stichproben-Restore-Ergebnis`.

###2026.05.11.1935###
- Restore Tests: Dauer-Spalte zeigt Laufzeitwert und Kategorie jetzt sauber untereinander.
- Bessere Lesbarkeit der Laufzeit-Kategorie in der Tabelle.

###2026.05.11.1929###
- Restore Tests: Coverage-Spalte mit klaren Sampling-Hinweisen (inkl. Tooltip) verbessert.
- Restore Tests: Dauer-Spalte zeigt zusaetzlich Laufzeit-Kategorie (`kurz`/`mittel`/`lang`) und Tooltip.
- Restore Tests: Spalten-Tooltips fuer Coverage und Dauer ergaenzt.

###2026.05.11.1923###
- Restore Zielpfad-Autocomplete: robuster gegen schnelle Eingaben (Request-Guard + kleiner Prefix-Cache).
- Restore Zielpfad-Autocomplete: Enter auf exaktem Treffer normalisiert Pfad mit `/` und laedt passende Unterordner nach.
- Restore API: Suggest-Limit parametrisierbar (`limit`), serverseitig begrenzt.

###2026.05.11.1735###
- Restore Tests: Hinweisbereich ist jetzt als klarer, immer sichtbarer Info-Block dargestellt.
- Bessere Lesbarkeit der Laufzeit-Hinweise (statt unauffaelligem einklappbaren Bereich).

###2026.05.11.1555###
- Browse & Restore: Zielpfad-Feld mit Unraid-Style Autocomplete fuer Verzeichnisse unter `/mnt`.
- Restore API: neuer Endpoint `/api/restore/target-dirs` (Whitelist auf `/mnt`, Freitext bleibt erlaubt).

###2026.05.11.1532###
- Browse & Restore: moderne Icon-Buttons (Download/Restore) statt Pfeil-Symbole.
- Browse & Restore: bessere Lesbarkeit und einheitlicher Stil der Aktionen in der Dateiliste.

###2026.05.11.1508###
- Browse & Restore: Restore-Assistent mit Dry-Run-Precheck, Zielpfad-Validierung und Konfliktstrategie (skip/overwrite/rename).
- Browse & Restore: explizite Zusammenfassung + Bestätigung vor Restore-Start.

###2026.05.11.1442###
- Browse & Restore: Restore-Assistent mit Dry-Run-Precheck, Zielpfad-Validierung und Konfliktstrategie (skip/overwrite/rename).
- Browse & Restore: explizite Zusammenfassung + Bestätigung vor Restore-Start.

###2026.05.11.1427###
- Einstellungen: Config-Backups koennen jetzt einzeln geloescht werden.
- Einstellungen: Aktion "Alle außer neuestes löschen" fuer Config-Backups ergaenzt.

###2026.05.11.1422###
- Einstellungen: neue Karte "Config-Backups & Rollback" mit Liste und Restore-Aktion fuer backup.conf.
- API: /api/settings/backup-history und /api/settings/backup-restore.
- Settings-Save erstellt nun automatisch rotierende backup.conf-Snapshots.

###2026.05.11.1342###
- UI: Erstkonfiguration wird erzwungen, solange `GLOBAL_DATA_DIR` fehlt.
- UX: Beim Start automatische Weiterleitung auf Einstellungen; Navigation außerhalb Einstellungen bis zur Konfiguration gesperrt.

###2026.05.11.1316###
- UI: Systemzustand-Karte von Dashboard nach Einstellungen verschoben.
- Dashboard: zeigt nur noch einen kompakten Warnhinweis, wenn der Systemzustand nicht OK ist.

###2026.05.11.1312###
- Fix: Systemzustand/Migration zeigt keinen Importfehler mehr (jobs_api), Status korrekt beim Start.

###2026.05.11.1308###
- Dashboard: neue Systemzustand-Karte mit Data-Root/Jobs/Secrets und letztem Migrationsstatus.
- API: neuer Endpoint `GET /api/system-health` fuer schnelle Update-Diagnose.

###2026.05.11.1301###
- First-Install: Bootstrap legt Datenverzeichnisse (`config/jobs`, `secrets`, `locks`, `scripts`) unter `/boot/config/borg-backup` automatisch an.
- First-Install: `config/backup.conf` wird bei fehlender Datei automatisch aus `runtime/config/backup.conf.example` erstellt.

###2026.05.11.1235###
- Migration: Job-Metadaten liegen kanonisch unter `/boot/config/borg-backup/config/jobs` (kein runtime/config/jobs mehr als Ziel).
- Migration: Secrets-Konsolidierung nach `/boot/config/borg-backup/secrets` inkl. automatischem Umzug alter Dateien.
- Runtime: Root-Symlink-Abhängigkeit für Passphrases entfernt; Passphrase-Dateien werden direkt aus dem Secrets-Ordner genutzt.
- Startup: idempotente Datenmigration (Jobs/Secrets/Passphrase-Pfade in Metadaten und backup.conf).

###2026.05.11.1047###
- UI: Drittanbieter-Lizenzen im About-Bereich als lesbarer Eintrag mit Link zur offiziellen Borg-Lizenz.

###2026.05.11.1042###
- Fix: Beim Start wird ein kaputter `/usr/bin/borg` Link automatisch repariert.
- Fix: Fallback für Shell-CLI: falls Symlink nicht greift, wird `/usr/local/bin/borg` nach `/usr/bin/borg` kopiert.

###2026.05.11.1034###
- Fix: Wenn Borg unter `/boot/...` nicht ausführbar ist, wird die gebündelte Binary nach `/usr/local/bin/borg` gestaged und von dort genutzt.
- Startup/Python: PATH enthält `/usr/local/bin` vor Plugin-Pfaden, damit der staged Borg-Binary bevorzugt wird.

###2026.05.11.1026###
- Fix: Gebündeltes Borg funktioniert auf Unraid-Flash ohne Symlink-Unterstützung.
- Startup: bevorzugt `runtime/bin/borg/borg`, fallback auf versionierte Borg-Datei.
- Runtime: Python-Start nutzt denselben Borg-Fallback statt `current`-Symlink.

###2026.05.11.1001###
- Fix: Browse & Restore lädt Jobliste robust über API-Fallback (inkl. Fallback auf Check-Jobliste bei leerer Antwort).
- Fix: `/api/jobs` bleibt verfügbar, auch wenn Statusdaten temporär nicht geladen werden können.

###2026.05.11.0958###
- Fix: Einheitliche Scripts-Pfad-Auflösung (Basisordner vs. scripts-Unterordner) für Job-Erkennung.
- Fix: Browse & Restore zeigt Jobs auch dann, wenn `BORG_SCRIPTS_DIR` auf den Borg-Basisordner zeigt.
- Fix: Manueller Borg Check und Browse/Restore nutzen denselben normalisierten Job-Quellpfad.

###2026.05.11.0950###
- Fix: Browse & Restore lädt Jobliste wieder zuverlässig (Job-Discovery mit Script-Pfad-Fallback wie im Check-Flow).
- Fix: Manueller Borg Check zeigt Jobnamen mit Location-Suffix (z. B. Appdata (local/usb/storagebox)).

###2026.05.11.0939###
- Storage UI bereinigt: statischer config/backup.conf-Hinweis im Header entfernt.
- Storage UI bereinigt: Aktualisieren-Button im Header entfernt.
- Storage UI bereinigt: Editierfunktion pro Repository entfernt (Repositories sind job-gesteuert).

###2026.05.11.0919###
- Fix: Storage liest Repositories dynamisch aus Wizard-Jobs (Fallback), wenn keine statischen REPO_* Variablen gepflegt sind.
- Fix: fehlender `json`-Import in config_api behoben, dadurch wird die Storage-Liste nicht mehr stillschweigend leer.

###2026.05.11.0915###
- Release-Refresh: dynamische Storage-Repositories und Check-Jobliste nach Merge auf main veröffentlicht.

###2026.05.11.0859###
- Fix: Storage zeigt Wizard-Repositories aus Job-Metadaten (nicht nur REPO_* aus backup.conf).
- Fix: Manueller Borg Check findet Jobs robust mit Fallback auf <BACKUP_SCRIPTS_DIR>/scripts.

###2026.05.11.0830###
- Fix: Job-Ausführung setzt `PYTHONPATH` auf Plugin-Runtime, damit `import lib...` in Wizard/Legacy-Jobs zuverlässig funktioniert.

###2026.05.11.0823###
- Fix: API 500 nach Runtime-Lib-Migration behoben (status/jobs Importpfade)
- Build/Installer: runtime/* wird korrekt paketiert, Release-Cleanup Pfad korrigiert

###2026.05.11.0801###
- Runtime-Struktur auf `runtime/` umgestellt:
  - `runtime/lib`, `runtime/scripts`, `runtime/config`
- UI/Runner nutzen Libs jetzt ausschließlich aus Plugin-Runtime (`/boot/config/plugins/borg-backup-ui/runtime/lib`)
- Legacy-Fallback auf `/boot/config/borg-backup/lib` entfernt
- Installer bereinigt alte Legacy-Lib unter `/boot/config/borg-backup/lib`
- Installer räumt Release-Artefakte auf und behält nur aktuelle + vorherige Version

###2026.05.10.2350###
- Restore-Tests erweitert: Level/Location/Einzeljob-Auswahl im UI
- Restore-Test-Defaults auf produktiv validierte Werte angepasst
- UI-Verbesserungen/texte:
  - Scope -> Umfang
  - Hinweisblock mit Laufzeit-Erwartungen und Testfrequenz
  - Leere-Meldung: „Restore-Test wurde noch nicht ausgeführt.“
- Settings-Meldung „Verzeichnisse aktiv …“ erscheint nur beim erstmaligen Setzen von `GLOBAL_DATA_DIR`

###2026.05.09.1100###
- Layout: overflow-x: clip on main-content prevents implicit scroll-container (fixes bottom clipping on all pages)
- Layout: page bottom padding increased to 56px as additional safety margin

###2026.05.09.1000###
- Reports: Borg Repository Info section gets padding-bottom so cards are no longer clipped at the bottom edge

###2026.05.09.0900###
- Reports: empty state with icon, title and step cards shown when no job is selected
- Browse & Restore: empty state with icon, title and step cards shown when no job is selected

###2026.05.09.0800###
- Storage: fixed Manual Borg Check – showEl was undefined, causing a silent ReferenceError on button click

###2026.05.09.0700###
- Settings: new "Weekly Status Report" card – enable/disable, day of week, time, optional custom recipient
- Settings: "Send now" button to dispatch the weekly report on demand
- Settings: report cron job applied automatically when settings are saved
- Reports: weekly report sends an HTML email with status, last run time, repo size and duration per job
- Storage: new "Manual Borg Check" card with job selector and live log output (SSE stream)
- About: Borg version displayed in sidebar footer and Settings About card

###2026.05.08.1050###
- Dashboard: weekly growth snapshot now written automatically on every dashboard refresh
- Dashboard: no longer depends on external borg_summary_mail.py for "growth since last week"
- Dashboard: .status files are no longer moved or archived, so Reports page always has full history

###2026.05.08.1040###
- General: version number and author displayed in the sidebar footer
- Settings: new "About" section showing version, author, license and repository link
- Build: APP_VERSION is automatically injected into borg_backup_ui.py on every build

###2026.05.08.1030###
- Reports: replaced unreliable "Savings" card with "New Data (last run)" showing deduplicated_size
- Reports: new "New Unique Data per Run" chart (green bars, shows incremental backup growth)
- Reports: added "Borg Repository Info" section at the bottom of the page
- Reports: clicking "Load" runs borg info and shows accurate deduplication statistics on demand

###2026.05.08.1020###
- Reports: savings calculation fixed – now compares repository size against total original size across all runs

###2026.05.08.1010###
- Reports: savings calculation fixed – now uses repository_size vs original_size (not deduplicated_size)

###2026.05.08.1000###
- Reports: new "Reports" navigation item (between History and Browse & Restore)
- Reports: job selector reads available jobs directly from .status files – no borg call needed
- Reports: summary cards showing run count, success rate, average duration, repo size, original size, new data
- Reports: SVG chart – repository size over time (bars colored by run status)
- Reports: SVG chart – backup duration per run
- Reports: SVG chart – stacked status bars per month (green/yellow/red)
- Storage: removed borg-based repository stats section (replaced by Reports page)

###2026.05.08.0900###
- Browse & Restore: archive index now caches full listing for instant directory navigation
- Browse & Restore: shell variable expansion (${VAR}) in BORG_REPO resolved from backup.conf
- Browse & Restore: six regex patterns to extract BORG_REPO from wizard and hand-written scripts
- Browse & Restore: storagebox scripts using _DEFAULT_REPO variable now work correctly
- Browse & Restore: passphrase file path parsed from script instead of derived from type ID

###2026.05.07.1600###
- Settings: SMTP test login logic revised – works with external mail servers (GMX, Gmail) and internal servers without auth

###2026.05.07.1545###
- Settings: SMTP test skips login when server does not offer AUTH extension (fix for local/internal mail servers)

###2026.05.07.1530###
- Settings: "Send test email" button in the SMTP section
- Settings: sends a test mail using current SMTP settings, result shown immediately
- Settings: authentication and connection errors displayed in plain text

###2026.05.07.1500###
- Wizard: new step 6 "Schedule" – optional cron schedule directly when creating a job
- Wizard: schedule step supports daily, weekly, monthly and custom frequencies
- Wizard: if no schedule is enabled the step is skipped silently (not required)
- Wizard: schedule is written to schedules.json and crontab automatically on save

###2026.05.07.1207###
- Plugin settings page: service status (RUNNING/STOPPED), version number, open UI button
- Plugin settings page: Start / Stop / Restart buttons
- Plugin settings page: Port and Bind Address configuration with Apply / Default

###2026.05.07.1156###
- Navigation: all pages refresh automatically on every menu switch (no stale data)
- Wizard: "Keep existing" button shows active state and green confirmation line when selected
- Wizard: switching between keep/replace correctly resets state and visual indicators

###2026.05.07.1133###
- Wizard: Python syntax highlighting in script preview (keywords, strings, comments, numbers, decorators)
- Wizard: highlighting is built-in, no external CDN or library required

###2026.05.07.1127###
- Jobs: delete modal shows "delete passphrase file" checkbox when a key exists for the job type
- Jobs: passphrase file and /root/ symlink are deleted when checkbox is checked
- Jobs: success message lists deleted passphrase file if applicable

###2026.05.07.1105###
- Wizard: passphrase conflict detection when re-creating a job with an existing type_id
- Wizard: step 4 shows "keep existing" / "set new passphrase" choice when conflict detected
- Wizard: "set new passphrase" shows a prominent warning about the repository becoming unreadable
- Wizard: keeping the existing passphrase sends an empty passphrase field (no overwrite on save)

###2026.05.07.1054###
- Settings: new "Per-Repo Passphrases" card showing all keys in /boot/config/borg-secrets/ dynamically
- Settings: table with type ID, flash path and last-modified date per key

###2026.05.07.1034###
- Wizard: passphrase file stored on flash at /boot/config/borg-secrets/ (survives reboots)
- Wizard: /root/.borg-passphrase-<type_id> created as a symlink to the flash file
- Startup: rc.borg_backup_ui restores all /root/ passphrase symlinks from flash on every boot

###2026.05.07.0810###
- Wizard: new Passphrase step (step 4) for encrypted repositories
- Wizard: passphrase generator using crypto.getRandomValues(), copy-to-clipboard, show/hide toggle
- Wizard: passphrase step is skipped automatically when encryption is set to "none"
- Wizard: passphrase written to /boot/config/borg-secrets/ with chmod 600 on save
- Wizard: generated scripts omit BORG_PASSCOMMAND entirely when encryption is "none"

###2026.05.07###
- Jobs/Dashboard: color-coded type icons per backup type (flash, appdata, photos, VMs, other)
- Dashboard: fixed badge and icon alignment in "never run" cards

###2026.05.06.2211###
- Jobs: wizard to create new backup jobs (name, sources & target, retention, description, preview)
- Jobs: delete job button with typed confirmation to prevent accidents
- Restore Tests: run test immediately with live log output
- Restore Tests: schedule automated restore tests via cron

###2026.05.06.1908###
- Jobs: per-job cron schedule (daily, weekly, monthly, custom) with next-run preview on job cards
- Jobs: page auto-refreshes when a scheduled job starts

###2026.05.06.1828###
- Mobile UI: hamburger menu, slide-in sidebar, responsive grids and tables
- Dashboard: now also shows jobs that have never been run
- Dashboard: check status and restore tests marked as outdated when older than the check interval
- Restore Tests: new page with detailed view (archive info, level-3 restore, file list with SHA256)
- Storage: repository test button no longer jumps when displaying results
- History: log viewer now opens at the beginning of the file
- General: check interval from settings consistently used for all status indicators

###2026.05.06###
- Initial release
- Dashboard: backup status of all repositories at a glance
- Jobs: manually start backup scripts with live log
- Storage: manage and test Borg repositories
- History: search all backup runs, open log files
- Settings: edit backup.conf directly in the browser
