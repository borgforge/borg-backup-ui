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

Verify a notification using the maintainer's selected test destination and
confirm delivery status; do not send messages to other recipients as part of
an unattended check. Keep successful delivery and failure/retry behavior in
the acceptance record.

Record the two capture summaries and any remaining unexpected writes before
stable approval. Local filesystem tests demonstrate application behavior;
they do not measure physical USB I/O or predict USB lifespan.
