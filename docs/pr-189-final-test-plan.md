# PR #189 final acceptance test plan

## Automated gate

Run from the repository root:

```bash
pytest -q
./plugin/mr-preflight.sh
```

The automated suite covers:

- direct stable-to-canonical migration for Local, USB, SMB and SSH targets;
- partial test installation and already canonical installation;
- ID preservation, idempotence, validation failure and rollback;
- schedule and restore-test-policy preservation;
- persistent passphrase/keyfile behavior;
- separate-process inventory writes;
- job create/edit/repository switch/delete and usage reconciliation;
- repository create/import/deletion guards;
- storage profile updates and validation rollback;
- sanitized canonical inventory and migration audit support data.

## Upgrade test on Unraid

1. Export a normal configuration backup and download a support bundle.
2. Record current job count, schedules, Restore Test policies, storage profiles
   and repository count.
3. Install the final test-channel candidate over the current stable version.
4. Open **Settings > Advanced > System health and migration**.
5. Confirm `canonical_data_model_v1` is `applied` or `not applicable` and has no
   failed phase.
6. Confirm `settings.json` no longer exists.
7. Confirm `storages.json`, `repositories.json` and all job JSON files are
   readable and owned with restrictive permissions.
8. Restart the plugin and confirm the migration is not applied a second time.
9. Confirm all previous job schedules and Restore Test policies are unchanged.

## Functional relationship checks

1. Open every storage/profile type in Settings: Local, USB, SMB and SSH.
2. Open Repositories and verify each repository appears below the correct exact
   storage target.
3. Edit one job without changing its repository and save it.
4. Switch one non-critical test job to another compatible repository and save.
5. Reopen the job and confirm the assignment remains correct.
6. Run one small backup and open its live log.
7. Open Reports for that job.
8. Run one Restore Test for that repository.
9. Browse one archive and complete a dry-run restore.
10. Verify repository deletion remains blocked while a job references it.

## Diagnostics and recovery checks

1. Download a support bundle.
2. Confirm it contains sanitized canonical inventories and central migration
   state/audit files.
3. Confirm it contains no passphrase, SMB password, token, SSH private key or
   Borg keyfile content.
4. Review System Health assignment diagnostics; all counts must be zero.
5. Keep the merged code under tester observation for two to three days before
   preparing a separate stable release PR.

