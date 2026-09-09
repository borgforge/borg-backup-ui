# Issue #497: idle and navigation write verification

This fix is tested on top of the permanent-job-ID branch at the maintainer's
request. An already migrated test-channel installation can update directly;
restoring pre-migration data is not required. This test does not cover #496 or
#498, and does not change authentication or move configuration stores.

## Automated checks

Focused tests cover unchanged/missing queues, delayed and exhausted retries,
persisted claims and enqueueing during delivery, unchanged lock metadata,
permission correction, thread/process serialization, and read-only setup
status with unavailable, missing or unwritable data storage. Explicit setup
still creates directories and performs an actual write test.

The follow-up covers the actual restore GET handlers as well as setup status:
archive/file lists, repository statistics, target-directory browsing and restore
state. Missing/unmounted/unwritable storage still blocks these requests; they
do not repair missing directories. Actual backup, restore, check and download
actions retain their write probe. A read-only access check does not guarantee
that later writes succeed (for example when storage fills up).

Service-launcher tests use an isolated payload and cache path to verify real
Python imports in the service and a child process, cache reuse on the next
start, and successful execution without bytecode writes when the optional
cache directory cannot be prepared.

## Maintainer measurements on 2026-09-09

The first #497 candidate was `2026.09.08.2345`. Both new captures completed
without reported gaps and monitored 180 directories:

- `bbui-io-idle-497.jsonl`: 00:00:25 to 00:05:25, 300 seconds. No content writes,
  replacements, create/delete events or metadata changes; 20 writable-handle
  closes on `notification-delivery.lock` without content WRITE events.
- `bbui-io-ui-497.jsonl`: 00:06:12 to 00:16:13, 600 seconds. No queue saves and no
  inventory-lock permission updates. Ten remaining data-directory write probes
  and ten individual Python bytecode cache writes on the boot USB prompted the
  follow-up. Nine of the probes occurred during the final minute.
- `users.json` was saved once at 00:06:30; `sessions.json` twice at 00:06:24 and
  00:06:30, with no further session saves during navigation. The paired saves
  fit sign-in; the capture alone does not identify the earlier session action.

The maintainer accepted the queue, lock and setup-status changes. The restore
GET correction and RAM bytecode cache still need the updated candidate's
Unraid verification. Raw file captures are not published in the repository.

## Python bytecode cache

The service launcher sets `PYTHONPYCACHEPREFIX=/run/borg-backup-ui/pycache`
before starting Python, with a private `0700` cache directory. Python child
processes inherit it. Current cron entries call the API, so scheduled jobs use
the same cache as manually started jobs. Direct developer invocations outside
the service launcher do not receive this setting automatically.

On Unraid this path is in RAM and disappears at reboot. It is shared across
processes and retained across plugin-service restarts. It is unrelated to Borg
repository caches, job counts or backup sizes. There is no fixed allocation or
32 MiB cap. The initial 10-20 MiB estimate (32 MiB planning allowance) is not a
measured limit; Python versions and loaded modules affect the size.

If preparing this optional directory fails, the launcher sets
`PYTHONDONTWRITEBYTECODE=1` and logs the condition. The service continues without
bytecode writes; it does not fall back to writing caches alongside USB source
files. New imports may take longer without a usable bytecode cache.

## Unraid acceptance

Record the test-channel version, Unraid version and configured data directory.
Let startup/migration finish before starting the measurements. Use the same
inotify monitor and watched paths as the original #497 captures; keep its
output in RAM, outside the watched directories.

1. Close Borg Backup UI tabs and capture five minutes of idle activity.
2. Capture ten minutes of UI activity: sign in, visit each page without saving
   configuration, then navigate repeatedly during the final minute. Record
   the start of rapid navigation so unequal periods can be compared correctly.
3. Compare file-content writes, replacements, create/delete events and metadata
   changes. READ events and closing a writable handle alone do not prove a
   file-content write. Record any monitor overflows or gaps.

Expected results:

- `config/notification-queue.json`: no saves when missing, empty or unchanged,
  including retry entries whose next attempt is still in the future. Actual
  enqueueing, due claims, retries and delivery-status changes still write.
- `config/.inventory.lock`: no repeated permission updates while its existing
  permissions are `0600`. Creation or correction of permissions is expected
  when needed; keep locking enabled.
- `status/.borg-ui-write-test`: no create/write/delete events from ordinary
  page-status requests. The probe remains expected during explicit data-dir
  setup and runtime initialization, so measure after startup has finished.
- Normal sign-in can still save `users.json` and `sessions.json`. The fix makes
  no claim about session writes that were not reproduced in the original test.
- Setup readiness still reports missing or unavailable directories. It no
  longer silently creates or repairs directories during a GET request.
- Service and child-process `.pyc` files appear under
  `/run/borg-backup-ui/pycache`, with none created or replaced alongside the
  plugin's Python sources on `/boot`. Visit all pages once to populate lazy
  imports, then repeat navigation and compare warm-cache events.

Measure the actual cache allocation after navigation and a backup/restore-test
run (adjust the command only if the implementation path changes):

```bash
du -sh /run/borg-backup-ui/pycache
stat -c '%a %U:%G %n' /run/borg-backup-ui/pycache
```

After all active jobs have finished, verify that a plugin-service restart
reuses the cache. On a later normal Unraid reboot verify that the cache is
recreated in RAM and the application starts normally. The original inotify
monitor's boot/data roots do not include this RAM directory; use `--root`
explicitly when capturing its events.

Verify a notification using the maintainer's selected test destination and
confirm delivery status; do not send messages to other recipients as part of
an unattended check. Keep successful delivery and failure/retry behavior in
the acceptance record.

Record the two capture summaries and any remaining unexpected writes before
stable approval. Local filesystem tests demonstrate application behavior;
they do not measure physical USB I/O or predict USB lifespan.
