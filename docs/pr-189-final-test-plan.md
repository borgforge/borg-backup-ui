# PR #189 final acceptance checklist

This checklist records the practical Unraid acceptance of the canonical storage
and repository model before PR #189 is merged.

## Test record

- Date: ____________________
- Tester: ____________________
- Unraid version: ____________________
- Source plugin version: `2026.07.05.1531` / ____________________
- Direct-migration candidate: `2026.07.12.0025`
- Current regression candidate: `2026.07.12.0100`
- Current package MD5: `10207653e927d7aa5610a6846f586656`
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

- [ ] Open **Local Profiles** and confirm names and paths.
- [ ] Open **USB Profiles** and confirm names, paths and usage counts.
- [ ] Open **SMB Profiles** and confirm connection fields and usage counts.
- [ ] Open **SSH Profiles** and confirm endpoint, base path and SSH key path.
- [ ] Confirm an in-use profile cannot be deleted.
- [ ] Confirm the available profile status checks still work.

### Local path validation

Use a disposable local profile or restore the original value after this test.

- [ ] `/mnt//backup` is rejected with an understandable error.
- [ ] `/mnt/./backup` is rejected with an understandable error.
- [ ] `/mnt/../etc` is rejected with an understandable error.
- [ ] `/mnt/backup/` is accepted and stored as `/mnt/backup`.
- [ ] A valid custom Unraid pool path below `/mnt/<pool>` is accepted.

## 5. Repositories

- [ ] Every repository appears below the correct exact storage target.
- [ ] Display name, repository path, encryption and job assignment are correct.
- [ ] Borg information loads successfully for an existing repository.
- [ ] The displayed archive count matches the archive list.
- [ ] Archives are sorted newest first.
- [ ] Cached repository information survives a page reload.
- [ ] A Repokey repository remains accessible.
- [ ] A Keyfile repository remains accessible after a plugin or Unraid restart.
- [ ] Repository deletion is blocked while a job references it.

Optional disposable-repository test:

- [ ] Create or import a disposable repository.
- [ ] Open its information and archive list.
- [ ] Run a repository Check.
- [ ] Remove the repository after all job references have been removed.
- [ ] Confirm its metadata, passphrase and dedicated keyfile are cleaned up as expected.

## 6. Job Wizard and relationships

- [ ] Open an existing job and confirm storage target is selected before repository.
- [ ] Confirm only repositories for the selected exact storage target are offered.
- [ ] Confirm options use `Repository name (effective path)`.
- [ ] Confirm no redundant storage or repository confirmation text appears.
- [ ] Save one job without changing its repository.
- [ ] Reopen it and confirm the same repository remains assigned.
- [ ] Switch one disposable job to another compatible repository and save it.
- [ ] Reopen it and confirm the new assignment remains correct.
- [ ] Confirm System Health reports no assignment inconsistencies.
- [ ] Confirm repository deletion is blocked for the newly assigned repository.

### Source-path autocomplete

- [ ] Typing below `/mnt` shows matching directories.
- [ ] Up/Down selects a suggestion.
- [ ] Right Arrow opens the selected directory and loads its children.
- [ ] Enter adds the final source path.

## 7. Backup runtime

- [ ] Start one small local or USB backup.
- [ ] Confirm the job is visibly running.
- [ ] Open and follow its live log.
- [ ] Confirm the expected repository is used.
- [ ] Confirm the final status and exit code are correct.
- [ ] Confirm History contains the completed run.
- [ ] Confirm Reports open for the completed run.
- [ ] Confirm Dashboard reflects the new run.

For a Docker/VM job where applicable:

- [ ] Only configured containers or VMs are stopped.
- [ ] Only instances that were running before the backup are restarted.
- [ ] No open Runtime Recovery warning remains after successful recovery.

## 8. Restore Test

- [ ] Confirm saved policy, interval and level before starting.
- [ ] Start one Restore Test.
- [ ] Confirm running state and live log are visible.
- [ ] Open the completed verification report.
- [ ] Confirm repository, archive, level and result are correct.
- [ ] Confirm the run remains traceable after navigation or a new login.

## 9. Browse & Restore

- [ ] Select a job and open an archive.
- [ ] Browse and select one safe test item.
- [ ] Select an allowed restore destination.
- [ ] Complete the precheck.
- [ ] Complete a dry-run restore.
- [ ] Confirm the result and Restore History entry.
- [ ] Optionally complete a real restore into a disposable destination.

## 10. Diagnostics and support bundle

- [ ] Download a new support bundle after the test.
- [ ] Confirm sanitized `storages.json` is included.
- [ ] Confirm sanitized `repositories.json` is included.
- [ ] Confirm `migration-state.json` is included.
- [ ] Confirm `migrations.log.jsonl` is included.
- [ ] Confirm migration status, failed phase and rollback details are understandable.
- [ ] Confirm the bundle contains no passphrases.
- [ ] Confirm the bundle contains no SMB passwords or access tokens.
- [ ] Confirm the bundle contains no private SSH key or Borg keyfile content.

## 11. Final acceptance

- [ ] No job, profile, repository, schedule or Restore Test policy was lost.
- [ ] No duplicate canonical objects were created.
- [ ] No canonical assignment error remains in System Health.
- [ ] Backup, Restore Test and Browse & Restore completed successfully.
- [ ] Local path validation behaves as documented.
- [ ] All discovered regressions are recorded in GitHub before merge.
- [ ] Maintainer explicitly accepts PR #189 for merge.
- [ ] After merge, observe the result for two to three days before preparing a
      separate Stable release PR.

## Sign-off

- Maintainer: ____________________
- Sign-off date: ____________________
- Final decision: [ ] MERGE PR #189  [ ] DO NOT MERGE
- Follow-up issues: ________________________________________________
