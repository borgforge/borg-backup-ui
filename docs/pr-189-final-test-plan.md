# PR #189 final acceptance checklist

This checklist records the practical Unraid acceptance of the canonical storage
and repository model before PR #189 is merged.

## Test record

- Date: 12.07.2026
- Tester: tsteinbe
- Unraid version: 7.2.6
- Source plugin version: `2026.07.05.1531`
- Direct-migration candidate: `2026.07.12.0025`
- Current regression candidate: `2026.07.12.1027`
- Current package MD5: `362f9345047c0f7aff1cc77aa03f255c`
- Result: [ ] PASS  [ ] FAIL
- Notes / observed issues: ________________________________________________

## 1. Preparation

- [X] Create and download a normal configuration backup.
- [X] Download a support bundle before the update.
- [X] Record the current job count: 11
- [X] Record the current storage-target count: 3
- [X] Record the current repository count: 11
- [X] Record all job schedules.
- [X] Record all Restore Test policies, intervals and levels.
- [X] Record the repository assigned to every job.

## 2. Automated gate

- [x] `pytest -q`: 374 tests passed.
- [x] `./plugin/mr-preflight.sh`: passed.
- [x] Test manifest and package MD5 match.
- [x] Stable remains unchanged at `2026.07.05.1531`.
- [x] PR #189 contains no Stable release artifacts.

## 3. Direct upgrade and migration

Perform this section on at least one installation that still uses the current
Stable layout. A system that already ran an intermediate PR #189 migration is
not sufficient for this particular check.

- [X] Install Test Channel candidate `2026.07.12.0025` over Stable.
- [X] Confirm the application starts and shows the candidate version.
- [X] Open **Settings > Advanced > System health and migration**.
- [X] Confirm `canonical_data_model_v1` is `applied` or `not applicable`.
- [X] Confirm no migration phase is failed or pending.
- [X] Confirm no rollback error is shown.
- [X] Confirm `settings.json` was removed after successful validation.
- [X] Confirm `storages.json` is readable and contains all storage targets.
- [X] Confirm `repositories.json` is readable and contains all repositories.
- [X] Confirm all job JSON files use schema version 2 and a `repository_key`.
- [X] Confirm all previous jobs still exist.
- [X] Confirm schedules are unchanged.
- [X] Confirm Restore Test policies, intervals and levels are unchanged.
- [X] Restart the plugin or Unraid.
- [X] Confirm the migration is not applied a second time.
- [X] Confirm no duplicate storage targets or repositories were created.

## 4. Storage targets and profiles

- [X] Open **Local Profiles** and confirm names and paths.
- [X] Open **USB Profiles** and confirm names, paths and usage counts.
- [X] Open **SMB Profiles** and confirm connection fields and usage counts.
- [X] Open **SSH Profiles** and confirm endpoint, base path and SSH key path.
- [X] Confirm an in-use profile cannot be deleted.
- [X] Confirm the available profile status checks still work.

### Local path validation

Use a disposable local profile or restore the original value after this test.

- [X] `/mnt//backup` is rejected with an understandable error.
- [X] `/mnt/./backup` is rejected with an understandable error.
- [X] `/mnt/../etc` is rejected with an understandable error.
- [X] `/mnt/backup/` is accepted and stored as `/mnt/backup`.
- [X] A valid custom Unraid pool path below `/mnt/<pool>` is accepted.

## 5. Repositories

- [X] Every repository appears below the correct exact storage target.
- [X] Display name, repository path, encryption and job assignment are correct.
- [X] Borg information loads successfully for an existing repository.
- [X] The displayed archive count matches the archive list.
- [X] Archives are sorted newest first.
- [X] Cached repository information survives a page reload.
- [X] A Repokey repository remains accessible.
- [X] A Keyfile repository remains accessible after a plugin or Unraid restart.
- [X] Repository deletion is blocked while a job references it.

Optional disposable-repository test:

- [X] Create or import a disposable repository.
- [X] Open its information and archive list.
- [X] Run a repository Check.
- [X] Remove the repository after all job references have been removed.
- [X] Confirm its metadata, passphrase and dedicated keyfile are cleaned up as expected.

## 6. Job Wizard and relationships

- [X] Open an existing job and confirm storage target is selected before repository.
- [X] Confirm only repositories for the selected exact storage target are offered.
- [X] Confirm options use `Repository name (effective path)`.
- [X] Confirm no redundant storage or repository confirmation text appears.
- [X] Save one job without changing its repository.
- [X] Reopen it and confirm the same repository remains assigned.
- [X] Switch one disposable job to another compatible repository and save it.
- [X] Reopen it and confirm the new assignment remains correct.
- [X] Confirm System Health reports no assignment inconsistencies.
- [X] Confirm repository deletion is blocked for the newly assigned repository.

### Source-path autocomplete

- [X] Typing below `/mnt` shows matching directories.
- [X] Up/Down selects a suggestion.
- [X] Right Arrow opens the selected directory and loads its children.
- [X] Enter adds the final source path.

## 7. Backup runtime

- [X] Start one small local or USB backup.
- [X] Confirm the job is visibly running.
- [X] Open and follow its live log.
- [X] Confirm the expected repository is used.
- [X] Confirm the final status and exit code are correct.
- [X] Confirm History contains the completed run.
- [X] Confirm Reports open for the completed run.
- [X] Confirm Dashboard reflects the new run.

For a Docker/VM job where applicable:

- [X] Only configured containers or VMs are stopped.
- [X] Only instances that were running before the backup are restarted.
- [X] No open Runtime Recovery warning remains after successful recovery.

## 8. Restore Test

- [X] Confirm saved policy, interval and level before starting.
- [X] Start one Restore Test.
- [X] Confirm running state and live log are visible.
- [X] Open the completed verification report.
- [X] Confirm repository, archive, level and result are correct.
- [X] Confirm the run remains traceable after navigation or a new login.

## 9. Browse & Restore

- [X] Select a job and open an archive.
- [X] Browse and select one safe test item.
- [X] Select an allowed restore destination.
- [X] Complete the precheck.
- [X] Complete a dry-run restore.
- [X] Confirm the result and Restore History entry.
- [X] Optionally complete a real restore into a disposable destination.

## 10. Diagnostics and support bundle

- [X] Download a new support bundle after the test.
- [X] Confirm sanitized `storages.json` is included.
- [X] Confirm sanitized `repositories.json` is included.
- [ ] Confirm no synthesized `settings.sanitized.json` is included.
- [X] Confirm `migration-state.json` is included.
- [X] Confirm `migrations.log.jsonl` is included.
- [X] Confirm migration status, failed phase and rollback details are understandable.
- [X] Confirm the bundle contains no passphrases.
- [X] Confirm the bundle contains no SMB passwords or access tokens.
- [X] Confirm the bundle contains no private SSH key or Borg keyfile content.

## 11. Final acceptance

- [X] No job, profile, repository, schedule or Restore Test policy was lost.
- [X] No duplicate canonical objects were created.
- [X] No canonical assignment error remains in System Health.
- [X] Backup, Restore Test and Browse & Restore completed successfully.
- [X] Local path validation behaves as documented.
- [X] All discovered regressions are recorded in GitHub before merge.
- [ ] Maintainer explicitly accepts PR #189 for merge.
- [ ] After merge, observe the result for two to three days before preparing a
      separate Stable release PR.

## Sign-off

- Maintainer: ____________________
- Sign-off date: ____________________
- Final decision: [ ] MERGE PR #189  [ ] DO NOT MERGE
- Follow-up issues: ________________________________________________
