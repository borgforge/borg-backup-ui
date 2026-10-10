# Practical Pre/Post scripts (#557)

[Deutsch](README.de.md)

Six standalone Bash templates for **Settings > Scripts > Import (.sh)**. These
are opt-in examples in the repository, not installed or enabled by the plugin.
Each file contains its own implementation; no shared helper has to be installed.
They are intended for review and host-specific testing, not unattended deployment.

| File | Purpose | Suggested hook timeout |
| --- | --- | --- |
| [pre-check-source.sh](pre-check-source.sh) | Verify an existing mount, source containment and identity marker | 30 s |
| [pre-check-free-space.sh](pre-check-free-space.sh) | Require a free-space threshold on an existing staging mount | 30 s |
| [pre-wake-server.sh](pre-wake-server.sh) | Send Wake-on-LAN if needed, wait for a TCP port | 150 s |
| [pre-dump-mariadb.sh](pre-dump-mariadb.sh) | Export one MariaDB database in a Docker container | 1800 s |
| [pre-dump-postgresql.sh](pre-dump-postgresql.sh) | Export one PostgreSQL database in a Docker container | 1800 s |
| [post-json-webhook.sh](post-json-webhook.sh) | Send job ID and pre-Post result to your HTTPS receiver | 30 s |

## Import and configuration

1. Read the selected file and this guide. Save the raw `.sh` file as UTF-8, not
   the HTML repository page. Retain the Bash shebang on its first line.
2. Import the file, then change the constants at the top for your own host.
   Do not put passwords/tokens into the editor: scripts can be exported.
3. Set `CONFIGURED="yes"` only after configuring prerequisites. Unchanged
   examples exit with code 2 without running their payload.
4. Set a descriptive name and a timeout. Import does not carry timeout/description;
   the table above is a starting point. Save and assign in wizard step 9.
5. Test with a disposable backup job, inspect the log and archive, and test a
   restore of any database export before enabling scheduling.

The plugin offers one Pre and one Post selection per job. These are alternatives,
not a script chain. For a combined workflow, create and review one combined
script with explicit failure handling; importing several files does not run them
in sequence. In particular a dump job can include the free-space check before
exporting. Do not concatenate whole files with their independent traps/guards.

## Existing hook contract

- Pre runs after the initial job lock but before network mounts, container/VM
  stops, repository preparation and backup. Its nonzero exit or timeout prevents
  backup. Mount checks therefore only work on sources already mounted by Unraid
  or the administrator; they must not expect the plugin's later mounts.
- Post runs after service recovery, repository maintenance/statistics and share
  cleanup. The plugin still holds job locks; final status/notifications follow.
- For the webhook choose **Also on failure, skip or cancellation**. Post can run
  after failed Pre; an initial lock conflict runs neither hook.
- `BBUI_JOB_ID`, `BBUI_HOOK_PHASE` and (Post only) `BBUI_JOB_RESULT` are supplied.
  No Borg credentials are inherited. Run privileges are normally root on Unraid.
- "On success" also includes Borg warnings. Post failure fails the overall job
  even when an archive exists. The webhook describes the result *before* Post,
  not a finalized overall outcome or proof of successful restore.
- Post has a timeout but cannot be cancelled through the UI. Do not leave work
  running in background. Killing a local `docker exec` does not guarantee that
  its container-side process has stopped; check for leftover dumps after an
  interrupted export before retrying.

## Source identity and free space

Use the actual mount root for `MOUNT_PATH`, not merely a folder below it.
`SOURCE_PATH` may be that mount or a subdirectory. Create a small, regular
`.backup-source-id` file there with a unique text identifier and set `EXPECTED_ID`
to the same text. The script never creates the marker or mounts a disk. A final
newline in the marker is allowed. The marker is an accidental-target check, not
a cryptographic identity guarantee. A mount disappearing after the check remains
possible; this check does not lock the filesystem.

The free-space example checks the available KiB reported by `df` against
`MIN_FREE_GIB`. Use the actual local filesystem used for dumps/staging. It is
neither a reservation nor a backup size estimate, does not check remote repository
quota and cannot replace Unraid share/pool allocation checks. A combined user
share can report space differently from the pool/disk that will receive a file.

## Wake-on-LAN

Requires `python3` with its standard library, a WOL-enabled host and a network
that permits the chosen broadcast. Set a colon-separated MAC, numeric IPv4
broadcast/host, TCP port and wait duration. There is no package installation or
interface reconfiguration. No packet is sent when the TCP port is already open;
otherwise one UDP magic packet is sent to port 9. Set the hook timeout above
`WAIT_SECONDS` plus a few seconds. TCP readiness is not authentication, an SMB
mount test or a guarantee that a remote share is ready.

There is deliberately no generic Post shutdown script. An independent script
cannot safely infer whether other jobs, users or hosts still need the server,
nor whether this job originally woke it. Shared-use coordination belongs in a
separately designed feature (see repository issue #89).

## Database dumps

Both examples require Bash, Docker CLI, `mountpoint`, `realpath`, `stat`, `mktemp`
and core Unix commands on the host, plus the matching dump client inside the
running container. These dependencies are checked/used, never installed.

Prepare an existing private output directory with mode `0700`, owned by the
hook user (normally root), **below the configured mounted filesystem**. Ancestors
must also be trusted and not writable by untrusted users. Use persistent storage
with enough space, not the Unraid boot flash. Configure that directory explicitly
as a backup source, and confirm no exclusion hides it. Merely generating a dump
does not make it part of an archive.

Each invocation creates a unique private directory and writes `dump.partial`.
Only a successful, nonempty export is renamed to `database.sql` or `database.dump`.
On normal failure/handled signals, only that invocation's partial file and empty
run directory are removed. Older completed dumps are retained, never overwritten
or automatically pruned. Plan separate retention for these local copies: Borg
prune does not remove them. A hard kill or host crash can leave partial data;
inspect it manually. Do not point other simultaneous backup jobs at this staging
area while a dump is being written. Dumps contain sensitive application data.

Database-client stderr is suppressed to avoid putting connection details into
job logs; failures report the operation without credentials. Diagnose failed
client commands separately in a protected administrator session.

### MariaDB

Set container, database and `CLIENT_CONFIG`, an absolute option-file path **inside
the container**. Provision that file separately, readable only by the intended
container user, with a `[client]` section and your backup connection credentials.
The container must provide `mariadb-dump`; this template does not automatically
substitute MySQL clients or discover passwords from container environment.

The command uses `--single-transaction --quick --skip-lock-tables --databases`.
Its consistency model requires transactional tables (such as InnoDB) and no
concurrent schema changes. It does not promise a consistent export of MyISAM or
other nontransactional tables. Stored routines/events, database accounts/grants
and cross-application file consistency are outside this template. Validate the
required objects and restore process for your own application.

### PostgreSQL

Set container, database, database user and `PGPASS_FILE`, a protected password
file **inside the container**, readable by the container's execution user and
with PostgreSQL's required restrictive permissions (normally `0600`). The client
uses TCP `127.0.0.1`, the container's libpq port settings/default and `--no-password`;
provision a matching password-file entry. The template accepts a plain database
name, not a connection URI. It calls `pg_dump --format=custom` for one database;
use the matching PostgreSQL restore tooling (`pg_restore`) to test recovery.
Cluster roles/tablespaces and consistency with external application files are
outside this export. Container-side libpq configuration remains applicable.

## Generic Post webhook

Requires `curl` and `python3`. Configure a trusted regular curl configuration
file, mode `0600`, owned by the hook user and stored below trusted directories.
It must contain **only one HTTPS `url` and optional authentication `header`
entries**. Provision actual secrets separately; do not import them into the
script. Example shape with nonfunctional placeholders:

```text
url = "https://monitor.example.invalid/backup-result"
header = "Authorization: Bearer REPLACE_LOCALLY"
```

No provider-specific URL suffixes are added. The receiver must accept an HTTP
POST with `Content-Type: application/json` and this contract:

```json
{"job_id": "example-job", "result": "warning"}
```

Possible results: `success`, `warning`, `failed`, `cancelled`, `skipped`.
The receiver should preserve warnings separately from clean success. Only HTTP
2xx counts as delivery. Redirects are not followed, retries are disabled, the
request has a 5-second connection timeout and 20-second total timeout, and
response bodies/errors are not logged. A timeout may occur after the receiver
accepted the message; account for this in receiver design. The generic webhook
is not directly compatible with every monitoring provider. Detecting missing
runs requires a deadline/expected schedule configured at the receiver.

## Distribution proposal and validation

Start with these versioned, individually importable files plus this bilingual
guide. A later plugin template gallery could open a copy as an unsaved draft,
keeping administrator edits and job assignments separate from bundled examples.
Neither automatic inventory seeding nor hosted downloads are part of #557.

Automated tests validate the real import path and run guarded examples with fake
Docker, filesystem-query and curl commands, plus an isolated fake socket for WOL.
They cover failed/empty exports, retention, invalid results, missing mounts,
identity mismatch and delivery failures without external side effects. Run:

```bash
mkdir -p .release-tmp/hook-tests
TMPDIR="$PWD/.release-tmp/hook-tests" pytest -q tests/test_practical_job_hooks.py --basetemp="$PWD/.release-tmp/hook-tests/pytest"
```

Real Unraid mounts, hardware WOL, database contents/restores and a real receiver
still require a maintainer test. This repository-only set is not copied by the
plugin package builder; a test-channel package would not distribute these files.
Test them through manual import instead. No stable release is prepared here.
