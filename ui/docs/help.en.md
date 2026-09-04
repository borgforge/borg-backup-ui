# Borg Backup UI - User Guide

This guide supports beginners, advanced users, and administrators throughout the complete backup lifecycle. Select a chapter on the left or search for a task, status, or error message.

> [!IMPORTANT] Backups are only dependable after at least one restore test and one manual restore to a test target have succeeded.

## 1. Getting Started

### Before the First Backup

1. Open **Settings > General** and review system health.
2. Create a storage target under **Local Profiles**, **USB Profiles**, **SMB Profiles**, or **SSH Profiles**.
3. Create or import a Borg repository under **Repositories**.
4. Create a backup job under **Jobs** and select the existing repository.
5. Run the job manually first and review its live log and **History**.
6. Schedule a restore test afterwards.

### Key Terms

- **Storage target:** A physical or remote location such as an Unraid pool, USB disk, SMB share, or SSH server.
- **Repository:** The Borg data store on a storage target. It contains archives and owns encryption plus a passphrase or keyfile.
- **Job:** Defines sources, exclusions, compression, retention, Docker/VM control, and the schedule.
- **Archive:** One backup snapshot inside a repository.
- **Restore test:** An automated verification that data can be restored from an archive.

> [!TIP] Configure the storage target and repository first. The job wizard no longer creates repositories as a side effect.

## 2. Interface and Roles

### Navigation

The main menu follows the operating workflow: **Dashboard**, **Jobs**, **Repositories**, **History**, **Reports**, **Browse & Restore**, **Restore Tests**, **Settings**, and **Help**. System status, language, sign-in information, and version are shown at the lower left.

### Roles

- **viewer:** May read status and reports but cannot save changes.
- **operator:** May run operational actions but cannot manage administrative settings.
- **admin:** May manage users, settings, storage targets, repositories, and jobs.

### Status Colors

- **Green:** Successful, ready, or verified.
- **Orange:** Warning, overdue, or attention required.
- **Red:** Failed, unreachable, or blocked.
- **Gray:** Not scheduled, not run, or unknown.

## 3. Dashboard

The dashboard shows whether backups and restore evidence are currently healthy. The cards at the top summarize backup runs and restore tests. The location sidebar filters the job table by Local, USB, SMB, or Storagebox.

### Important Columns

- **Run status:** Result, time, duration of the latest backup run, and the next scheduled run.
- **Restore:** Latest restore test and its validity.
- **Storage data:** Source size, compressed and deduplicated data, and repository size.
- **Growth / Check:** Size change and the latest known repository check.

> [!NOTE] The dashboard displays the latest stored status data. Open **History**, **Reports**, or **Repositories** for technical details.

## 4. Storage Targets and Profiles

Storage targets are managed centrally under **Settings**. A profile can only be deleted when no repository or job references it.

### Local Profiles

Use a specific path below `/mnt`, for example `/mnt/backup`, `/mnt/cache/backups`, or an Unraid pool. Broad roots and system paths are rejected.

### USB Profiles

A USB profile points to an existing mount path. The disk must be mounted when a job runs; otherwise the run is safely skipped or stopped.

### SMB Profiles

The connection test checks port 445, sign-in, temporary mount, share access, write access, and unmount. Use SMB 2 or 3; SMB 1 is not supported.

### SSH Profiles

SSH profiles contain host, port, user, base path, and SSH key. Existing keys are never overwritten. Verify and deploy the public key before importing a repository.

## 5. Repositories

The **Repositories** page groups Borg repositories by storage target. A repository has a display name, a full repository path, encryption metadata, and optional job assignments.

### Create a Repository

1. Select **Add Repository**.
2. Choose an existing storage target.
3. Select **Create New Repository**.
4. Enter a display name, path within the storage target, and encryption mode.
5. Enter the passphrase or select a keyfile mode.
6. Review the summary and save the repository.

### Import a Repository

Select **Import Existing Repository** and then choose a directory within the storage target. Encrypted repositories require the matching passphrase or an existing or imported Borg key.

### Tabs

- **Overview:** Borg sizes, archive count, health, path, storage target, encryption, and job assignment.
- **Archives:** Archives, technical IDs, timestamps, and duration; newest archives are listed first.
- **Maintenance:** Check, full data verification, prune, and compact.
- **Administration:** Job links, non-destructive removal from the UI, and protected permanent deletion.

> [!WARNING] Permanent repository deletion removes Borg data. It is only available without job assignments and after multi-step confirmation.

## 6. Backup Jobs

A job connects sources to exactly one existing repository. Encryption belongs to the repository; compression and retention belong to the job.

### Job Wizard

1. **Basics:** Name, technical type, icon, and optional Docker/VM control.
2. **Sources & Target:** Folders or files to back up, exclusions, storage type, storage target, repository, and compression.
3. **Docker:** Stop all running containers, selected containers, or all containers except selected containers and restart them afterwards.
4. **VMs:** Shut down all running or selected VMs and restart them afterwards.
5. **Retention:** Daily, weekly, monthly, and yearly restore points.
6. **Description:** Clear description with optional Markdown.
7. **Schedule:** Simple schedule or cron expression.
8. **Flow Preview:** Final review of the planned workflow.

> [!IMPORTANT] Retention values count periods, not archives per period. **Daily: 20** means up to one daily state for 20 daily periods, not 20 archives per day. Borg Backup UI automatically runs prune after every successful backup. `0` disables only that tier; at least one retention value must be greater than `0`.

Example: If backups are created at 08:00 and 08:30 on the same day, the newer qualifying archive normally represents that day's daily restore point. See the full manual under **Backup Jobs > Retention, Compression, and Description** for details and additional examples.

### Sources and Exclusions

Sources are the folders or files that a backup job should back up. Typical examples are `/mnt/user/appdata/`, `/mnt/user/domains/`, or a custom share below `/mnt/user/...`.

At least one source is required because the job otherwise does not know which data should be backed up. Sources must exist and be readable by the backup process. Missing required sources stop the run so that an apparently successful but incomplete archive is not created.

Exclusions are optional child folders or files inside a source that should not be included in the backup. Exclusions must therefore be located below a selected source.

> [!TIP] Run every new or substantially changed job manually once before enabling its schedule.

### Cancel a Running Job Safely

For a running job, **Cancel job** requests a controlled cancellation. An active Borg step is interrupted. If Docker containers or VMs are currently being stopped, that operation is completed first and the systems that were running before the backup are restarted afterwards. No further cancellation is possible during recovery. If recovery fails, the run ends as an error and the runtime recovery notice remains visible.

A cancelled run is stored with the **Cancelled** status. The application does not automatically run a repository check or remove Borg locks afterwards. Review the live or stored log if Borg reports anything unusual.

## 7. Scheduling

Cron uses five fields: minute, hour, day, month, and weekday. `0 3 * * *` starts a job every day at 03:00. Leave enough time between large jobs and avoid concurrent access to the same repository.

### Overdue Runs

The application calculates the expected run from the schedule. After the configured tolerance expires, it can notify through Unraid, email, or Apprise profiles. The reminder interval prevents immediate repetitions.

## 8. Docker and VMs

Docker selection can be used as either an include or exclude list. **Selected containers only** stops exactly the checked containers. **All except selected containers** stops all running containers but keeps the checked containers running.

Before a backup, the application records which containers or VMs were actually running. Only those targets are restarted afterwards. After an interruption or server restart, **Runtime Recovery** in system health reports pending restarts.

### Appdata and Domains

- For a complete `/mnt/user/appdata` backup, all writing containers should be stopped.
- For a complete `/mnt/user/domains` backup, the affected VMs should be shut down.
- Selective control is suitable when sources and dependent services are clearly known.

## 9. History and Live Logs

**History** lists backup runs by location, type, and status. Expand a run for archive name, sizes, duration, exit code, repository check, and log file. Running jobs provide a live log; completed runs link to the stored log.

### Borg Results

- Exit code `0` means success.
- Warnings can produce a usable archive but must be reviewed.
- Errors mean the run is not a dependable backup.
- Skipped means that a protection condition such as a missing mount or active parity check applied.

## 10. Reports

Reports show metrics and trends for each job. They include run totals, success rate, duration, growth, repository size, Borg information, and restore evidence. Select a job on the left and refresh Borg information only when needed.

## 11. Browse & Restore

The restore wizard walks through job, archive, selection, target, and review. In the target step, **Archive path** identifies the selection inside the archive; repository and archive are shown separately below it. Restores may only write to approved target roots.

### Safe Workflow

1. Select a job and archive.
2. Mark files or directories.
3. Choose a separate target directory.
4. Use **Do Not Overwrite** when in doubt.
5. Review the summary and confirmation.
6. Monitor the live log and then **Restore History**.

> [!WARNING] Do not restore production data directly over existing files without review. Use a test target first.

## 12. Restore Tests

Restore tests automatically verify recoverability. **Planning & Policy** defines mode, interval, and level. **Reports** provides evidence, coverage, test steps, and clear error categories.

### Test Levels

- **L1:** Connectivity and basic repository verification.
- **L2:** Adds sample restore and technical checks.
- **L3:** Most extensive verification with a larger sample and integrity comparison.

> [!NOTE] Higher levels require more time and I/O. Schedule large offsite repositories outside production peak times.

## 13. Settings

### General

Manages data paths, theme, log retention, Borg cache, parity protection, SMTP, weekly report, Homepage widget, and application information. Notification channels live in the separate **Notifications** area.

### Users

Administrators manage users, roles, passwords, and sessions. Disable a user first before deleting it permanently.

### Backup and Restore

**Backup** contains global runtime, Docker, VM, and report defaults. **Restore** contains restore-test defaults and approved target roots for Browse & Restore.

### Import / Export

Exports protect jobs, profiles, and secrets. The current encrypted format detects wrong passwords and modified files before writing. The preview shows conflicts before import. Profile-secret imports are applied only after a successful preview.

### Advanced and Factory Reset

**Advanced** shows reminder diagnostics and per-repository passphrases. **Factory Reset** removes application configuration and operating data after multi-step confirmation, but does not delete external Borg repositories.

## 14. System Health, Migration, and Support

System health checks data paths, jobs, secrets, profiles, repository references, migrations, and runtime recovery. A failed mandatory migration places the application in restricted maintenance mode until the problem is resolved.

### Support Bundle

Support bundles are **sanitized, not anonymous**. Secrets are masked, but paths, job names, hostnames, or other metadata can still identify a system. Review the bundle before sharing it.

## 15. Troubleshooting and FAQ

### No Repository in the Job Wizard

Verify that a matching storage target and a managed repository on it exist. The wizard only lists repositories for the selected storage target.

### Repository Is Locked

A running Borg process or interrupted connection can hold a lock. Wait for active processes to finish. Remove locks only after careful verification according to the troubleshooting documentation.

### Network or SSH Disconnect

Check the WAN connection, server availability, and SSH keepalive. A failed check must be restarted; Borg does not resume partial check progress.

### Backup Contains No Data

Check spelling, letter case, content, and readability of the selected folders or files. An existing but empty directory is technically valid and creates an empty archive.

### What Backup Strategy Should I Use?

Use multiple copies on different media, at least one offsite copy, automatic failure monitoring, and regular restore tests. Passphrases and keyfiles must also be backed up outside the server.
