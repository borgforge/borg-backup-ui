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
6. Restore a known file through **Browse & Restore** to a separate destination with **Dry run** off; compare its contents.
7. Only then enable schedules, restore tests and notifications.

[Complete tutorial](../../docs/user-manual/en/user-manual.md#tutorial-first-backup-and-verified-restore).

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

Three cards show **Latest backup runs**, **Restore coverage** and **Active runs**. The location filter applies to these metrics, attention items, historical statistics and location totals. The first card counts the last saved outcome per job. Restore coverage compares valid evidence with all jobs; the ratio within known test plans appears separately. Missing status data never counts as success.

**Needs attention** shows full failure messages, warnings, skipped or cancelled runs, overdue backups and restore evidence. **View job** opens the matching job and its status. Jobs without test plans are listed separately with a link to Restore Tests.

**Trends** evaluates saved backup runs over 7, 30 or 90 calendar days including today in the server timezone. Success rate is successful runs / (successful runs + warnings + failures). Skipped, cancelled and unknown runs are counted separately. This historical rate differs from the share of jobs whose current outcome is successful.

**Repository storage** uses actual sizes from saved reports, counting each shared repository once. The last sample is carried forward until the next measurement. Missing sizes are never replaced by deduplicated archive sizes; incomplete series remain gaps. Assignment follows the current job configuration because older reports contain no repository ID. After changing a repository assignment, older values therefore have limited comparability. The chart shows the latest sample time. Deleted jobs are excluded from this overview.

The **Locations** table summarizes job counts, latest successes, jobs needing attention and restore coverage. **Open jobs** in a location row shows only the jobs at that location, for example USB. Individual job details and actions belong on the Jobs page.

**Server resources** directly below the summary row containing **Latest backup runs** remain global. CPU, RAM and expandable history use the full width. Active protected restore tests also use the full width, even with history collapsed. Charts stack on narrow screens.

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

All repository tabs share a compact height based on the overview and the window size. Switching tabs or loading data keeps the card height unchanged. Archive pages fit this area; longer contents scroll inside the selected tab. On wide screens Management places key recovery, removal and deletion in columns separated by vertical dividers, with action buttons aligned along the bottom. The repository ID stays on one line; truncated IDs are available in full on hover. On narrow screens the management sections, archive list and file browser are stacked. Returning to Repositories automatically refreshes job links and the availability of management actions. Deleting a job does not require an additional Refresh click; any other blockers still apply.

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

- **Overview:** Compact sizes, archive count and files in the newest archive. **Refresh statistics** fetches these values from Borg; the adjacent timestamp identifies that fetch. Maintenance results retain their own timestamps. Expanding a card scrolls it into view when needed.
- **Archives:** Archive name and creation time; newest archives are listed first. Long names stay on one line; hover or open the archive to read the full name. The number of entries per page adapts to the window and row heights. The range and paging buttons appear directly above and below the left archive list, for example "1–5 of 14 loaded archives". Select an archive to browse its folders and files directly in a read-only view. This also works for imported archives without a job assignment. Reading the archive index for the first time can take longer for large or remote repositories. Restore, download, and file preview remain part of the separate **Browse & Restore** workflow.
- **Maintenance:** Check, full data verification, prune, and compact. On wide screens the four actions use two columns with aligned Start buttons. Long expanded execution details scroll within their result area while the buttons retain their position. Narrow screens stack the actions vertically.
- **Administration:** Job links, non-destructive removal from the UI, and protected permanent deletion.

> [!WARNING] Permanent repository deletion removes Borg data. It is only available without job assignments and after multi-step confirmation.

## 6. Backup Jobs

A job connects sources to exactly one existing repository. Encryption belongs to the repository; compression and retention belong to the job.

**Next run** shows the scheduled time. The last run time and duration remain separate values.

Jobs appear as separate compact cards with spacing. The **Single jobs/Job groups** tabs attach directly to the workspace. The **All locations** total and each individual location count use the same subtly outlined badge. A labelled location bar below them shares the surrounding panel, without pills or a dropdown. A dedicated date column shows schedules, the latest restore test and evidence validity. The arrow next to a job opens one detail area with **Workflow** and **Data & settings**. The latter combines storage facts, policy, archive prefix, description, Borg/repository checks and restore evidence. Both views reserve the height of the larger content, so switching does not shift the list. Open details and the selected view survive refreshes.

Subtle markers below the job name identify configured **VMs**, **Docker**, **Pre script** and **Post script** options. Script markers reflect current assignments, not historical run results; their tooltip names the script and the post-script execution condition.

Status and restore evidence use distinct symbols and subtle background fills with normal-weight text and no outline. Last test and validity dates have separate labels and vertically aligned values.

**Start**, **Log** and **Cancel** have matching icons and retain their positions and labels below the centered **Actions** heading. Unavailable actions remain disabled. **Log** opens the live log during a run (marked with a live dot) and the saved log afterwards; it is disabled when no log is available. During Docker/VM recovery, **Cancel** stays disabled, with the explanation in a tooltip instead of an extra text row. Requested cancellation appears in the status badge.

Collapsed cards identify failures, warnings, skipped or cancelled runs by status only. The full message appears exactly once under **Workflow**, labelled **Last saved outcome**, including during a new run. Dashboard problem links open this view directly. Long live-log lines scroll horizontally. Missing status files never imply success.

### Job Wizard

1. **Basics:** Job name, permanent Job ID, archive prefix, icon and optional Docker/VM control.
2. **Sources & Target:** Folders or files to back up, storage type, storage target, repository, and compression.
3. **Exclusions:** Paths, marker filenames and one uploaded exclusion file, shown together in a dedicated step.
4. **Docker:** Stop all running containers, selected containers, or all containers except selected containers and restart them afterwards; drag or use the arrows to set their order.
5. **VMs:** Shut down all running or selected VMs and restart them afterwards.
6. **Retention:** Tiered with an optional time window, last X archives, or keep all.
7. **Description:** Clear description with optional Markdown.
8. **Schedule:** Simple schedule or cron expression.
9. **Pre/Post scripts:** Assign optional centrally stored scripts.
10. **Flow Preview:** Final review of the planned workflow.

Docker and VM steps are skipped when control is off. Job name, permanent Job ID and archive prefix are separate; renaming preserves identity. Prune uses only the current prefix, while Browse & Restore also includes saved previous prefixes.

> [!IMPORTANT] Retention values count periods containing backups. Choose “Tiered”, “Last X archives” or “Keep all”. A time window such as “all archives from the last 7 days” supplements count rules and cannot be used alone. `0` disables a rule. Empty policies and “last 0” are blocked. A small count can permit deletion of many older archives. The info button explains each strategy and its deletion effect without expanding the wizard.

Example: If backups are created at 08:00 and 08:30 on the same day, the daily rule keeps only one restore point for that day—normally the newer 08:30 archive. See the full manual under **Backup Jobs > Retention, Compression, and Description** for details and additional examples.

### Sources and Exclusions

Sources are the folders or files that a backup job should back up. Typical examples are `/mnt/user/appdata/`, `/mnt/user/domains/`, or a custom share below `/mnt/user/...`.

At least one source is required because the job otherwise does not know which data should be backed up. Sources must exist and be readable by the backup process. Missing required sources stop the run so that an apparently successful but incomplete archive is not created.

Exclusions are optional child folders or files inside a source that should not be included in the backup. Exclusions must therefore be located below a selected source.

> [!TIP] Run every new or substantially changed job manually once before enabling its schedule.

### Cancel a Running Job Safely

For a running job, **Cancel** requests a controlled cancellation. An active Borg step is interrupted. If Docker containers or VMs are currently being stopped, that operation is completed first and the systems that were running before the backup are restarted afterwards. No further cancellation is possible during recovery. If recovery fails, the run ends as an error and the runtime recovery notice remains visible.

A cancelled run is stored with the **Cancelled** status. The application does not automatically run a repository check or remove Borg locks afterwards. Review the live or stored log if Borg reports anything unusual.

### Job Groups

Under **Jobs > Job groups**, administrators can arrange existing jobs into a sequence with its own schedule. Individual jobs retain their settings and show their group membership. The next job starts only after its predecessor fully exits, including maintenance and the Post script. Individual schedules are not changed automatically.

**Stop after current job** ends the sequence after the running job. Groups stop on errors by default; continuation is configurable. Other jobs can start independently. Shutdown in the last job only happens if that job runs. Review additional individual schedules and scripts before the first automatic run.

[Setup, log view, error handling and export](../../docs/user-manual/en/user-manual.md#38-job-groups).


## 7. Scheduling

Cron uses five fields: minute, hour, day, month, and weekday. `0 3 * * *` starts a job every day at 03:00. Leave enough time between large jobs and avoid concurrent access to the same repository.

### Overdue Runs

The application calculates the expected run from the schedule. After the configured tolerance expires, it can notify through Unraid, email, or Apprise profiles. The reminder interval prevents immediate repetitions.

## 8. Docker and VMs

Docker selection can be used as either an include or exclude list. **Selected containers only** stops exactly the checked containers. **All except selected containers** stops all running containers but keeps the checked containers running.

The **Order** list in the Docker step defines the order in which containers start from top to bottom after the backup; they are then stopped one by one in reverse order. Put databases at the top. A custom order replaces the priority groups and their pauses for the listed containers; neither Docker health checks nor application readiness are awaited. Without changes, the default order by the `backup.start.priority` label applies and the containers are stopped together.

Before a backup, the application records which containers or VMs were actually running. Only those targets are restarted afterwards. After an interruption or server restart, **Runtime Recovery** in system health reports pending restarts.

### Appdata and Domains

- For a complete `/mnt/user/appdata` backup, all writing containers should be stopped.
- For a complete `/mnt/user/domains` backup, the affected VMs should be shut down.
- Selective control is suitable when sources and dependent services are clearly known.

## 9. History and Live Logs

**History** lists backup runs by location, type, and status. Expand a run for archive name, sizes, duration, exit code, repository check, and log file. Running jobs provide a live log; completed runs link to the stored log.

The per-job **File activity in the live log** option can be enabled under **Basics** in the Job Wizard. Borg then shows added (`A`), modified (`M`), and errored (`E`) entries; unchanged entries are omitted. These values come from Borg's files cache and are neither a byte-transfer indicator nor a complete archive listing. File and directory names also appear in the stored run log and can be included in support bundles.

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

A cancelled restore test is an incomplete attempt, not failed verification evidence. Jobs and saved status details show the **latest test attempt as cancelled** with its date; the preceding completed test retains its outcome and original validity deadline. Cancellation neither renews evidence nor hides a preceding real failure. Without a usable preceding report, verification remains open. Existing cancellation reports are evaluated using retained report history in the same way; reports are preserved.

Under **Planning & Policy > ⋯ > Edit plan**, administrators set calendar execution,
test level and separate evidence validity. **Test now** starts manually.
Server timezone applies; missed/skipped slots are not caught up. Skipping does
not renew evidence. Legacy interval tests remain separate under **Settings >
Restore**. No corresponding overdue reminder is sent without a previous report.

Planning combines the information into four columns, grouped by location with job counts. Empty locations are hidden, and location is not repeated below each job. **Evidence & history** opens the job reports. Successful reports appear as **Restoration evidence**, identifying the archive and cumulative scope: L1, L1 + L2 or L1 + L2 + L3. Validity is separate from the attempt result. After cancellation, previous valid evidence is directly accessible. One **Technical evidence** section combines checks and log diagnostics; **Show check data** opens supporting values with their check; existing reports remain unchanged.

### Test Levels

- **L1:** Archive listing and metadata; no complete data check.
- **L2:** `borg extract --dry-run` reads data and checks it with Borg, but writes no restored user files.
- **L3:** Additionally stream selected files through `--stdout` and calculate SHA-256; no independent expected-hash comparison.

> [!WARNING] Selection uses the newest repository archive, not necessarily the
> job's archive. Check its name and individual steps. Metadata failures,
> timeout and memory interruptions produce a failed test.

Archive listings use bounded memory. Defaults are a 2048 MiB RAM limit and a
1024 MiB host reserve; limited tests run sequentially and require cgroup v2.
Tests do not start without working enforcement. Reports are retained per run;
their details identify the log file.

[Methods, writes, coverage and limits](../../docs/user-manual/en/user-manual.md#83-test-levels).
An actual restore to a separate destination, content comparison and application
test remain necessary.

## 13. Settings

### General

Manages data paths, theme, log retention, Borg cache, parity protection and the Homepage widget. SMTP, notification channels and custom notification texts are under **Notifications**, the weekly report under **Backup**, and version information under **About**. Notification texts provide a shared placeholder reference, an event selector and equally sized template/preview fields. Unconfigured events show editable examples in the interface language. Preview titles and messages match those templates; **Save** applies them to delivery. Custom texts, placeholder names and inserted values are not translated. Unraid shows the complete message with line breaks; forwarding to Unraid agents such as Discord preserves the same text lines.

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

## Emergency and Configuration Backup

Protect repository, passphrase, Borg key, profiles/secrets and plugin configuration separately from the server. Job exports contain neither archives nor central script definitions. Profile-secret imports and job imports use separate formats.

[Recovery guide and exact export limits](../../docs/user-manual/en/user-manual.md#16-disaster-recovery). Import existing repositories; never initialize them again.

Practical extensions: [Pre/Post scripts](../../docs/user-manual/en/user-manual.md#116-configure-and-verify-prepost-scripts) and [Grafana](../../docs/user-manual/en/user-manual.md#117-monitor-backup-health-in-grafana).

## Database backups

Configure MariaDB/MySQL/PostgreSQL profiles in Settings > Database backups and select them in job wizard step 2. Bundled scripts are plugin-managed; updates may replace direct edits. Store credentials in plugin Secrets, load databases and select them with checkboxes. Scripts separates editable own scripts, practical templates to copy, and read-only managed database helpers with syntax highlighting. Test restoration separately. See manual section 19.

New local database dumps are gzip-compressed. Folder names identify profile and time; the overview shows compressed and original sizes. Validate and decompress `.gz` files before restoration; existing dumps remain unchanged.
