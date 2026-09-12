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

## First maintainer measurements on 2026-09-09

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
GET correction and RAM bytecode cache were subsequently tested in the second
round below. Raw file captures are not published in the repository.

## Follow-up maintainer measurements on 2026-09-09

Candidate: `2026.09.09.0916`, built from
`9be8b322b269cc0f73b95279e9012c04525b0887` on `codex/issue-486-job-ids`.
The maintainer previously reported Unraid `7.4.0 beta 2`; the monitor does not
record the OS or plugin version itself. Configured data root:
`/mnt/user/borg_backup_ui`. All times below are CEST (`UTC+02:00`).

| Capture | Start | End | Duration | Watched directories | Reported gaps |
| --- | --- | --- | ---: | ---: | --- |
| `bbui-io-idle-497.jsonl` | 09:23:04.770 | 09:28:04.776 | 300 s | 180 | None |
| `bbui-io-ui-497.jsonl` | 09:30:37.854 | 09:40:37.864 | 600 s | 180 | None |

The individual event records agree with the per-path summaries and final event
totals in both files. Both report `incomplete: false`, with no warning/error
records. The filenames were reused for this round; use timestamps and hashes
to distinguish them from the earlier captures.

| Observed operation | Idle, 5 min | UI, 10 min |
| --- | ---: | ---: |
| Replace `notification-queue.json` | 0 | 0 |
| Change `.inventory.lock` permissions/metadata | 0 | 0 |
| Create/write/delete `.borg-ui-write-test` | 0 | 0 |
| Write Python `.pyc` files on the boot USB | 0 | 0 |
| Save `users.json` or `sessions.json` | 0 | 0 |
| Save `repository-info-refresh-state.json` | 1 | 0 |

During UI navigation, no content writes, replacements, creations/deletions or
metadata changes were recorded anywhere in the watched trees. The 67,760 total
events consist of 67,684 READ events and 76 WRITE_CLOSE events on existing lock
files: 7 on `.inventory.lock` and 69 on `notification-delivery.lock`. No content
WRITE events accompanied those lock closes. The zero session saves do not
prove that sign-in persistence changed; authentication was not modified.

The idle capture contains 758 events: 730 READ, 22 WRITE_CLOSE, one CREATE,
one WRITE, one MOVE_FROM, one MOVE_TO and two METADATA events. The only save
occurred at 09:25:23: a temporary file was written and renamed over
`config/repository-info-refresh-state.json`. One of the WRITE_CLOSE events
belongs to that save; the other 21 belong to the two lock files.

The repository-info scheduler waits 300 seconds after service startup and
persists its planning state. This single save is consistent with that behavior,
but neither exact startup timing nor changes beyond timestamps can be proven
from the file-event capture. It is separate from the removed recurring queue
saves, restore probes and Python USB cache writes.

The maintainer additionally reported:

```text
root@TheTwist:~# du -sh /run/borg-backup-ui/pycache
13M     /run/borg-backup-ui/pycache
```

The measured cache allocation is approximately 13 MiB, within the initial
10-20 MiB estimate. The RAM directory is outside the original monitor roots.
The cache-size measurement and absence of USB `.pyc` writes support the
intended placement; these captures do not measure total process RAM or device
write commands.

Result: the targeted #497 write sources did not recur in the observed idle/UI
windows. The ten remaining restore probes and ten distinct USB Python-cache
writes from the first candidate were absent. Service-restart reuse, rebuilding
after an Unraid reboot, and real notification delivery are not demonstrated by
these captures and remain separate manual checks. No stable release approval
or permission to merge is implied by this record.

SHA-256 of the supplied follow-up evidence files:

```text
0c9a11a28549b3c91f4abb88ea81c29f1fa81e5ed182292a340b991341dc1d0b  bbui-io-idle-497.jsonl
e19aa35fb666bbdb7a391f6b01c30a670927af04cbbfc4e6b276ad6bd744bc26  bbui-io-ui-497.jsonl
```

## Attached diagnostic script and invocation

Attachment: [bbui-io-watch.py](attachments/bbui-io-watch.py).
This is the unchanged script used for the captures, retained as a versioned
attachment. Its SHA-256 is
`a01135a0d51873770f3046854f46d073ba8dd4e28b5c01d7ec0a48ac986ee34c`.
It is a standalone Linux/Python 3 diagnostic using only the standard library;
it is not installed or started by the plugin.

Save the attached file as `/tmp/bbui-io-watch.py` on Unraid. Record the installed
plugin version and `cat /etc/unraid-version` separately. Wait until startup and
migration have finished. Keep outputs in RAM, outside the watched paths.
`/tmp` contents disappear at reboot, so copy the results out before rebooting.

Idle capture: close the plugin UI and observe five minutes.

```bash
python3 /tmp/bbui-io-watch.py \
  --phase idle --seconds 300 \
  --data-root /mnt/user/borg_backup_ui \
  | tee /tmp/bbui-io-idle-497.jsonl
```

UI capture: observe ten minutes, visit each page without changing settings,
include Browse & Restore, and use repeated rapid navigation in the last minute.
Record whether sign-in/out or another deliberate action occurred.

```bash
python3 /tmp/bbui-io-watch.py \
  --phase ui --seconds 600 \
  --data-root /mnt/user/borg_backup_ui \
  | tee /tmp/bbui-io-ui-497.jsonl
```

Use the installation's actual data root. The monitor automatically watches
`/boot/config/borg-backup` and `/boot/config/plugins/borg-backup-ui` recursively.
`--data-root` adds the root itself and recursively watches its `logs`, `status`
and `restore-status` directories. It deliberately excludes Borg cache and
remote-mount trees. It does not follow directory symlinks or read file contents.
Filenames and paths can nevertheless contain private information.

Optional capture including the RAM cache: `--root` replaces the default boot
roots, so list them explicitly when adding the RAM path.

```bash
python3 /tmp/bbui-io-watch.py \
  --phase ui-ram --seconds 600 \
  --root /boot/config/borg-backup \
  --root /boot/config/plugins/borg-backup-ui \
  --root /run/borg-backup-ui/pycache \
  --data-root /mnt/user/borg_backup_ui \
  | tee /tmp/bbui-io-ui-497-ram.jsonl
```

Read events are grouped every ten seconds; other events are emitted immediately.
The final per-path summaries repeat the already reported counts: do not add
summaries and individual/batched records together. Check `ready`, any warnings,
and `finished.elapsed_seconds` plus `finished.incomplete`. An early manual stop
can have `incomplete: false` but a shorter duration. `WRITE_CLOSE` alone is not
a content write, and event counts are not byte counts, process attribution,
physical device I/O or a USB-lifespan measurement. The script is an event
recorder; interpretation and comparison are documented above.

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
