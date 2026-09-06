# Permanent job identities: migration guide

This update gives each backup job a permanent identity. Renaming a job will keep its schedules, reports, restore results and history connected. The migration converts the plugin's own installation data. Existing Borg repositories and archive names stay in place.

## Before testing the update

The first candidate is a test-channel version and needs volunteer testing on different supported installations before a stable release is approved. Use a test installation or a system for which you have a checked recovery copy. Keep a separate backup of your Unraid flash configuration as well as the plugin data. The migration backup covers the exact affected files; it does not replace a full Unraid flash backup or a backup of your Borg repositories.

Allow running backup, restore, test and notification work to finish safely. Ensure the storage used by the plugin and the intended migration backup location is mounted. The backup location needs persistent storage with private file permissions. The Unraid USB boot filesystem is not a suitable location for the confidential migration backup.

## Use the migration assistant

1. Open **Settings > System Health & Migration**. If migration is required or the existing data cannot be classified safely, the plugin stays in maintenance. Installation, startup and opening this page do not authorize a conversion. Unraid and its array and pool controls remain available.
2. Select a private backup location and choose **Prepare migration**. The application checks prerequisites, saves the original migration plan and creates an exact backup of affected data and managed cron settings. It checks completeness, sizes and checksums automatically. Waiting reasons remain visible; a running job is not killed to make migration proceed.
3. At **Backup verified**, review the displayed location, creation time, size and verification result. Choose **Download protected backup**, save a separate copy on independent storage and check that it is available there. The backup can contain credentials and other confidential information. Do not upload it to a public issue or forum post.
4. Select the acknowledgement that you saved and checked a separate copy, then choose **Confirm saved copy**. This records your acknowledgement; it cannot prove that a copy exists on another device. This step does not start conversion.
5. Choose **Run migration now** separately. The server rechecks the exact plan and backup, storage availability, unchanged source and cron data, and writer exclusion before applying the migration. Progress remains visible. Normal functions remain paused until the final integrity checks and startup gate succeed.

Changed source data or a changed backup invalidates previous approval. The assistant cannot silently replace the plan under an earlier confirmation. Preserve existing recovery data and follow the displayed diagnostic information.

## Closing the browser or restarting

You may close the browser and return to observe the saved stage. A previously authorized operation can continue on the server; reopening the page does not submit it again. A restart retains the original allocated identities, plan, backup and journal and does not automatically approve application.

After an interruption, only a verified, explicit continuation is permitted. **Continue migration now** is available only when the server considers the original attempt safe to resume. Unknown or inconsistent partial states stay blocked. After a migration failure, correct the reported cause and restart the plugin successfully before normal operation can return.

## Recovery and reporting a problem

Keep the original migration directory and the separate downloaded copy. Routine old-backup cleanup must not delete this recovery state. Do not rename files, hand-edit job identities, delete the journal or create another identity map as a recovery shortcut.

Record the displayed stage and diagnostic codes. A protected support bundle contains bounded, masked diagnostics; the migration snapshot is a separate confidential recovery artifact. Share the diagnostic codes and the affected workflow with the maintainer, and report whether a backup, restore or notification was active. Volunteer tests should include checking jobs, schedules, histories and restore results after migration.

The snapshot is a data recovery source, not an automatic plugin downgrade. Unraid controls the installed plugin package. Repairs use the installed version or a corrected package. If manual data restoration is required, keep the plugin stopped, preserve the interrupted state, and work from an explicitly reviewed restoration plan. Record the snapshot identity, each exact source and destination, checksums, permissions and the time of every action. Verify the restored data and managed cron state before a successful startup permits normal work. Do not copy a whole data share over a partly converted installation or restore only selected related records without a consistency check.
