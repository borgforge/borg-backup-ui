# Borg Backup UI - Quick Help

This help provides a quick orientation. It does not replace the complete handbook; it summarizes the most important workflows, checks, and common problems.

## What is the application for?

Borg Backup UI manages Borg backup jobs on Unraid. It helps configure jobs, storage targets, schedules, restore tests, and system health checks.

## Quick Start

### 1) Check system status

- **System status** in the sidebar shows whether everything is OK or whether items need attention.
- When a warning is displayed, click **System status** and review the pending items under **Settings > System Health & Migration**.
- The area separates system checks, job checks, the latest migration, and configuration or maintenance items.

### 2) Prepare the storage target and repository

- Under **Repositories**, select **Add repository**.
- Use an existing storage target or set up Local, USB, SMB, or SSH/Storage Box through the guided flow.
- For SMB, the application manages the technical mount path automatically.
- Then create a Borg repository or import an existing repository.

Tip: Import validates the repository with `borg info` without modifying or initializing it.

### 3) Create or edit a job

- Under **Jobs**, select **New Job** or edit an existing job.
- Select the job name and type.
- Enter the source paths.
- Select a storage type, storage target, and an existing repository on that target.
- Review compression and retention. Encryption and passphrase belong to the repository and are not changed by the job.
- Enable a schedule if the job should run automatically.

### 4) Review the preview and checks

- The wizard displays the selected managed repository and its path.
- The quick job check is a local plausibility check. It does not replace a complete Borg repository test.

### 5) Run the first backup manually

- After saving, run the job manually once.
- Watch the log output.
- Then review **History** and **Reports**.

Recommendation: Enable a permanent schedule for a new job only after a successful manual run.

### 6) Optionally configure notifications

- SMTP is configured under **Settings > General**.
- After saving, send a test email.
- ntfy is also configured under **Settings > General**.
- ntfy requires a server URL, a topic, and optional authentication. Password and token are stored as secret files.
- After entering the values, send a test ntfy notification.
- Email, Unraid system notifications, and ntfy have separate event selections. Reminders are centrally rate-limited so overdue checks do not notify on every poll.
- Scheduled backups can use an overdue tolerance in hours. A notification is sent when an expected run did not complete successfully within that tolerance.
- The weekly report is enabled and scheduled under **Settings > Backup**.
- The weekly report uses its own recipient or, when empty, the global email recipient.

## Understanding system status

### Sidebar

- **all OK**: The latest system check completed successfully.
- **item(s) open**: At least one system, job, or maintenance check needs attention.
- **unknown**: The status has not been loaded yet or the backend check failed.

### Settings > System Health & Migration

- **System** checks base directories, tools, CIFS support, and secret file permissions.
- **Migration** shows the latest run and whether actual changes were recorded.
- **Initial setup, configuration & maintenance** shows inventory, pending items, errors, and cleanup candidates.
- **Pending items** shows specific actions when user input is required.
- **Technical Details** contains paths, registry details, and diagnostic information.

## Jobs and storage targets

### Local and USB

- Repository paths are normal file-system paths.
- USB targets must be available before a run can complete successfully.

### SMB

- SMB jobs use a saved SMB profile.
- The job check validates the profile reference and path plausibility.
- Repository access can only be tested meaningfully after the SMB target is mounted.
- Under **Storage > SMB**, mount the target first and then run the repository test.

### SSH, Storage Box, and Synology

- SSH targets use an SSH profile containing the host, port, user, base path, and key.
- The profile test checks SSH, Borg, the base path, and write access.
- Test the specific repository under **Storage** or through the repository preview in the wizard.
- A correct relative base path can look like `./backup` and is represented as `/./backup/...` in the URI.

## Repositories

- **Repositories** is where Borg repositories are configured, imported, and maintained.
- Repository details provide information refresh, Check, Verify Data, Prune, and Compact actions.
- Prune uses the linked job's retention policy and is disabled without a linked job.
- Verify Data, Prune, and Compact require explicit confirmation.

## Restore and Restore Tests

- **Browse & Restore** is used to browse archives and restore individual data.
- Restore targets are restricted to safe paths below `/mnt/user/...`.
- **Restore Tests** regularly check whether a restore works technically.
- Restore tests are not a complete content audit, but they provide important evidence that repository, archive, and restore path work together.

## Notifications, email, and reports

- SMTP configuration and the test email are under **Settings > General**.
- The SMTP password is not shown in clear text after saving. A saved password is shown only as a status.
- Email notifications follow the selected notification events; regular summaries are handled by the weekly report.
- ntfy configuration and the test notification are also under **Settings > General**.
- ntfy can send push notifications for successful backups, failed or warning backups, skipped backups, and overdue scheduled checks.
- Overdue scheduled restore tests can send reminders when the event is enabled for the channel.
- The ntfy password and access token are not shown in clear text after saving.
- The weekly report is enabled under **Settings > Backup**. It uses the saved SMTP configuration.
- Test emails, weekly reports, and technical output emails are always sent in English.

## Import, export, and backups

- **Settings > Import / Export** provides encrypted exports for jobs, passphrases, profiles, and secrets.
- A preview is displayed before an import.
- Import modes such as `skip`, `overwrite`, or `rename` control how existing data is handled.
- Job imports can include matching USB/SMB profiles from the package.
- Profile-secret imports can create missing SMB/SSH profiles from the package when the settings import is not set to `ignore`.
- Configuration backups provide a rollback point before maintenance or cleanup actions.
- Support bundles should not contain secrets in plain text.

## Migration and maintenance

- Migrations are actual changes to existing files, directories, or settings.
- Setup checks describe existing structures and are not automatically migrations.
- Cleanup candidates indicate old or unused configuration entries.
- Cleanup actions create a backup first and must be started explicitly.

## Common problems

### System status shows a warning

- Click **System status** in the sidebar.
- Read the specific message under **Pending items**.
- If only cleanup candidates are shown, this is usually maintenance rather than an immediate backup failure.

### No repository is available in the job wizard

- Create or import a repository under **Repositories** first.
- Verify the selected storage type and exact storage target in the job wizard.
- Only repositories belonging to that exact storage target are shown.

### SMB repository test does not work

- Check the SMB profile under **Settings > SMB Profiles**.
- Check the mount status under **Storage > SMB**.
- If it is not mounted, mount it and run the test again.

### SSH URI looks incorrect

- Check the host, port, user, and base path in the SSH profile.
- A typical Storage Box base path is `./backup`.
- The resulting URI then contains a slash after the port, for example `:23/./backup/...`.

### Passphrase or secret is missing

- Edit the job and check its passphrase file.
- Use encrypted secret packages when importing or exporting passphrases and profile secrets.
- Secret files should have restrictive permissions.

### SMTP, ntfy, or weekly-report values are missing after reload

- Save values in the matching area first: SMTP and ntfy under **General**, weekly report under **Backup**.
- After saving, the state is reloaded from `backup.conf`.
- SMTP password, ntfy password, and ntfy token intentionally remain visually empty when they have already been saved.
