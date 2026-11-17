# BorgForge Mobile API v1 (#738)

This additive API pairs a native client without copying internal API tokens,
widget tokens, browser cookies or Unraid credentials. It grants **monitor:read**
by default. Optional device-specific job control is described below. There are
no restore operations or configuration exports; original log excerpts require explicit device log permission. Existing browser/internal automation routes keep their authorization.

## Pairing

1. The Android client uses a validated HTTPS base URL and reads
   `GET /api/mobile/v1/capabilities`: `api_version: 1`,
   `authentication: device_pairing`, `scope: monitor:read`,
   `session_expires_in: 43200`, `persistent_pairing: true`.
2. `POST /api/mobile/v1/pair` with JSON `device_name` (1-80 characters) and optional strict boolean
   `persistent: true` when advertised
   returns `device_code` (32 random bytes, base64url), `user_code` (10 characters),
   `expires_in: 600`, `session_expires_in: 43200`, and `scope`.
3. On the **same HTTPS server**, sign into Borg Backup UI, then open
   **Settings > Users > BorgForge Mobile**. The existing app address
   `/ui/mobile-devices.html` redirects into this integrated view; a fixed
   `#mobile-devices` target survives login. No arbitrary return URL is accepted.
   Only enter a code displayed in your own app, never a code sent by someone else.
   `POST /api/auth/mobile/approve` with `user_code` needs a valid browser session
   for an enabled plugin user and a matching HTTPS Origin. Viewers may pair too.
4. `POST /api/mobile/v1/exchange` with `device_code` returns
   `status: pending`, or once only `status: authorized`, `access_token`,
   `session_id`, `expires_at` (Unix seconds), `scope: monitor:read`.
   Persistent pairing additionally returns a `refresh_token` (`bfr_` plus 43
   base64url characters), once only. Both credentials require secure storage.
   The shipped app checks on explicit user action, without background polling.
   If the one-time response is lost, begin a new pairing.
5. Send `Authorization: Bearer <access_token>` only to this exact server and
   mobile API. `GET /api/mobile/v1/snapshot` reads monitoring data.
   `POST /api/mobile/v1/logout` with `{}` revokes the calling device session.

No mobile endpoint accepts browser cookies or internal tokens as device access.
Browser approval/list/revoke cannot be authorized by a mobile bearer. Anonymous
pair/exchange POSTs reject browser Origin headers. JSON POST bodies are limited
to 4096 bytes; unknown methods, routes and query parameters are rejected.
Responses use `Cache-Control: no-store`; no token is put in a URL or cookie.

## Integrated device management (#741)

Pairing, the owned session list and revocation share the normal settings cards,
theme, sidebar and navigation. Opening Users loads the list; refreshing, approving
or revoking updates it in place without discarding a typed code. After completing
pairing in the app, refresh to see the issued device session. Rows show the device
label, access rights, registration time, expiry and a revoke action. A valid
session is not a claim that the phone is currently online.

Admins retain user administration. Viewer/operator accounts see only their own
mobile-device section under Settings > Users and fetch no configuration/user-list
APIs. Server-side administrative guards and device ownership are unchanged.
Device approval still requires HTTPS, cookie authentication, matching Origin and
explicit optional job-control consent. No new app build or re-pairing is needed
just to use the integrated settings page.

## Lifecycle and permissions

Access tokens expire **12 hours after issuance**. New clients opt into persistent
pairing; legacy pairs keep fixed expiry and never silently gain persistence.
Persistent devices remain registered until explicitly revoked, logged out, or
invalidated by a user security change. Existing devices need one new pairing to
obtain a refresh credential. No data-store migration or expiry extension is
performed for old sessions.

`POST /api/mobile/v1/refresh` with `{refresh_token}` issues a new `access_token`,
`session_id`, `expires_at`, and `scope`. The session ID and approved rights remain
unchanged. The refresh credential is long-lived, hashed on disk and accepted only
on this endpoint; it cannot read data or control jobs. Browser Origins are rejected,
bodies are bounded, user security is rechecked and renewal is limited to 30/device/hour.
A renewed access token invalidates the old one. The refresh credential remains
stable so a lost response does not require re-pairing. A stolen refresh credential
can renew until revoked: HTTPS, Keystore storage and prompt device revocation are
required. Neither credential is an internal/plugin administrator token.

Clients serialize renewal per server, atomically replace storage only if the old
credential is still current, and never replay job writes after renewal. Commands
are scoped to an access-token epoch; old admitted requests are rejected after
rotation and a fresh epoch starts a fresh bounded ledger. Revocation removes the
entire grant, including refresh access, across server restarts.

`GET /api/auth/mobile/sessions` lists the current browser user's own sessions
(`id`, `label`, `created_at`, `expires_at`, `job_control`, optional `persistent: true`),
plus `can_approve_job_control`. For persistent devices `expires_at` is access-token
expiry; the UI displays "Until revoked" as the device lifetime.
`POST /api/auth/mobile/revoke` with `session_id` idempotently revokes an owned
session. Foreign IDs do not confer access. Existing logout-all operations also
revoke mobile sessions in their selected user/all scope.

Passwords, roles and enabled state are checked against current users. Account
security changes/deletion revoke persisted sessions and approved pending pairs
before saving the change. Disabling then re-enabling does not restore access.
Access expiry and the password/role fingerprint also apply after restarts.

`config/mobile-sessions.json` is additive: atomic replacement, file mode 0600,
credential digests only, no raw access/device/user code. An invalid existing
store fails closed with 503, preserving the file. Back up authentication state
securely; restoring an older auth backup can restore device grants, including persistent grants.
The store is owned by the existing single server process and serializes mutations
with a lock. Running multiple independent writers against one data directory is
not supported. Anonymous pairing is limited to 10 attempts/IP/hour, approval to
30/user/hour, with 100 pending requests and 500 sessions globally. Reverse proxies
share the connection IP bucket; arbitrary forwarded client IP headers are not
trusted. Expired pending and legacy session entries are pruned during store operations; persistent device grants are retained.

This is a per-device bearer session, not hardware attestation or proof of
possession. A stolen bearer works until revoked/expired; Android stores it with
Keystore-backed encryption. Device names and job labels are untrusted display
text. The web page inserts them as text, never HTML. The browser approval code
must remain on the user's own device to resist consent phishing.

## TLS and reverse proxies

The app requires HTTPS with normal certificate validation. It never follows
redirects or retries POSTs automatically. Nginx Proxy Manager must serve the full
valid certificate chain, preserve the public Host, and forward Authorization and
JSON bodies unchanged. Do not expose the plugin's plain HTTP port to untrusted
networks. TLS termination is at the proxy; the plugin cannot verify the external
TLS connection from arbitrary forwarded headers. Keep the proxy-to-plugin link
on a trusted network or protect it with TLS as well. Configure request limits and
timeouts at the proxy. No CORS access or TLS bypass is added.

## Monitoring projection (#740)

`snapshot` has `api_version: 1`, UTC `sampled_at`, boolean `job_control`, and:

- `jobs`: opaque `id`/`repository_id`, `name`, `status`, nullable `last_run`,
  `next_run`, `duration_seconds`, `bytes` (original size), `compressed_bytes`,
  `deduplicated_bytes`, `files_count`, `exit_code`, `reason_code`.
  `schedule_state` is `none`, `disabled`, `active`, or `unsupported`; nullable
  `cron` uses server-local time. The existing reminder calculator supplies next
  run for supported expressions; unsupported expressions are preserved, not guessed.
- Job runtime fields: nullable `run_id`, `phase`, `percent`, `processed_bytes`,
  boolean `cancel_requested`, `can_start`, `can_cancel`. A measured percentage is
  exposed only when the runtime records one; Borg create normally has none.
  `processed_bytes` is the recorded original size so far, not network traffic.
- `history`: latest at most 100 valid timestamped entries, opaque `id`/`job_id`,
  `job_name`, `status`, `timestamp`, nullable `duration_seconds`, `bytes`,
  `reason_code`, `exit_code`. Failure codes are also preserved by the existing
  history API as an additive field.
- `repositories`: opaque `id`, display `name`, nullable recorded `bytes`,
  `checked_at`, `measured_at` from status reports, deduplicated by current
  repository assignment. These are recorded samples, not a fresh repository scan.
- `restore_verifications`: `job_name`, last attempt `status`, nullable `checked_at`,
  `verification` (`verified`, `stale`, `failed`, `never`, `not_required`), nullable
  `valid_until`, `reason_code`. Missing evidence is included explicitly.
  Legacy `restore_tests` retains only timestamped attempts so initial v1 clients
  can still parse their required `checked_at` field.
- `storage_daily`: 30 daily `{date: YYYY-MM-DD, bytes: integer|null}` samples
  from the existing overview aggregation.

Backup outcomes retain `cancelled`, `skipped`, `unavailable`; `failed` maps to
`error`. Jobs without an attempt are `ready`; disabled jobs are `disabled`.
Unknown future states remain `unknown`. Fields added in #740 are optional to
clients. Older clients continue reading the initial v1 subset.

Sources: `jobs_api.list_jobs`, `status_api.get_status_data`,
`jobs_api.get_all_runtime_states`, read-only `schedule_api.get_schedules`,
`notification_reminder_api._next_expected_run`, `history_api.get_history`, and
`dashboard_overview`. Free-form error text, raw logs, source/repository paths,
configuration, passphrases and filename activity are never projected. Structured
reason identifiers permit localized client explanations without forwarding logs.

## Explicit job control (#740)

Capabilities advertises `job_control: true`. During browser approval,
`allow_job_control: true` (strict JSON boolean) requires an enabled operator/admin.
Default false and all existing sessions remain read-only. The bearer scope stays
`monitor:read` for compatibility; the stored additional device consent and current
role are authoritative, checked again for every command. Re-pair to change rights.

`POST /api/mobile/v1/jobs/start`: `{job_id, request_id}`.
`POST /api/mobile/v1/jobs/cancel`: `{job_id, run_id, request_id}`.
IDs are from the current snapshot; `request_id` is 32 random lowercase hex digits.
Both return `{accepted: true, run_id}`; cancellation also returns
`cancellation_deferred`. Accepted cancellation is a request, not proof of completion.
Only ordinary wizard backup jobs are eligible. No utility/restore/delete endpoint
is granted. Starts require enabled and idle; cancellation requires the exact
current run, an allowed phase and no already-pending cancellation. Existing
`job_launch.start_backup` and `jobs_api.cancel_job` retain runtime locks, hooks and
cleanup. The existing maintenance guard applies to these endpoints.

A per-session ledger reserves each request durably before execution. Same ID and
payload returns a stored success, never a second launch; changed payload or an
incomplete reservation returns 409. Crashes/timeouts require status reconciliation,
not automatic retries. At most 100 command reservations per access-token epoch are
retained. Revocation and account changes also prevent result replay. Concurrent
mobile admission is serialized in the single server process.

## Verification

`tests/test_mobile_auth.py` covers the full HTTP pairing/read/logout flow,
device authorization boundaries, CSRF, credential hashing, permissions,
revocation, account changes, expiry, rate limiting, corruption and projection.
Run it with `tests/test_auth.py` and `tests/test_dashboard_overview_api.py` for
focused regression coverage. `tests/test_mobile_controls.py` additionally mocks launch/cancel services to test
consent, roles, duplicate/crash protection, revoked sessions, run identity,
uncancellable phases and measured projections. Hosted CI remains the full-suite authority.

Maintainer test on the test candidate: pair a viewer, check actual job/history
labels and states, revoke it in the browser, refresh the app and expect sign-in;
pair two server profiles and verify isolation; verify a legacy backend stays
unsupported. Never start or cancel production backups as a test.

`tests/test_mobile_settings_ui.py` and `tests/mobile_devices_browser.cjs` cover
the integrated DE/EN UI for all roles, escaping, input preservation, duplicate
approval suppression, revocation, error states, shell navigation and fixed login
return routing. Browser fixtures contain synthetic device metadata only.

## Foreground status updates (#742)

The client polls snapshots sequentially while visible: every five seconds while
any job runs, otherwise every thirty seconds. Resuming refreshes immediately.
Background polling is suspended; failed reads are shown as failures rather than
retaining a running card as current. No write is replayed by this polling.
`tests/test_mobile_refresh.py` verifies renewal after long inactivity, expiry,
legacy behavior, Origin/token boundaries, hashed storage, revocation, account
changes and rejection of commands admitted under an obsolete access token.

## Opt-in original log tails and cached repository details (#743, #744)

Capabilities adds `logs: true` and `repository_details: true`. Snapshots add
`logs_supported: true` and the current device's boolean `logs` permission. Existing
devices default to no log access. Browser approval accepts optional strict boolean
`allow_logs`; viewers may opt in independently of job-control rights. Settings >
Users also permits granting/removing logs without re-pairing via
`POST /api/auth/mobile/log-permission` with `{session_id, allow_logs}`. It requires
an owned device, current enabled browser user, HTTPS matching Origin and the
maintenance guard. Foreign/missing IDs return 404; malformed values return 400.

`POST /api/mobile/v1/logs/read` is a read-only bounded request with bearer auth,
JSON Content-Type and one identity: `{event_id}` or `{job_id, run_id}`. History IDs
resolve within the snapshot's latest 100 known-job records and their retained log.
No client path/filename is accepted. Current consent and revocation are checked
again after reading. Cookie/internal tokens cannot authorize this route.

Complete log navigation (#746) adds optional `start` or `before` (mutually
exclusive nonnegative integers, maximum 2^53-1). Omit both for the current tail;
`start:0` opens the beginning. Subsequent reads include both `file_id` and
`known_size` from the previous response to pin the source and detect observed
truncation. These guards are navigation metadata, never credentials.

Response: `{text, running, redacted:false, start, end, size, file_id, unit}`.
`start` is inclusive and `end` exclusive. Cursor units are `bytes` for file logs,
`characters` (Unicode code points) for memory logs. Files copy at most 64 KiB;
memory reads copy at most 16000 code points without joining the entire buffer.
Adjacent windows preserve UTF-8 boundaries, original whitespace and long lines.
A growing incomplete UTF-8 character remains for the next read. Source IDs are
opaque hashes; active capture IDs remain stable across their verified retained
copy. Retained file reads reuse descriptor-pinned directory confinement.
No total file-size limit or silent truncation is introduced. Missing logs return
404; replaced sources/runs or observed shrink return 409; malformed cursors 400.
An in-place rewrite that preserves inode and size is not a supported log lifecycle.

Original content is explicitly authorized by device log consent (#744); existing
grants apply without re-pairing. Server-side writer masking cannot be reversed.
The pre-release app/backend update together; no old tail-schema fallback remains.
Text stays transient: clients must not persist it or write it to telemetry. The
app opens history at the beginning and live logs at the tail, provides first/
previous/next/end navigation, and polls only the visible foreground live end every
five seconds. Reading older pages pauses following; errors stop polling and clear
content. A replaced log must be reopened. No unbounded download or stream starts.

Repository entries now also include unassigned repositories from
`repositories_api.read_repository_store`, without running Borg or refreshing
storage. Optional fields: `archives_count`, `original_bytes` (total_size),
`compressed_bytes` (total_csize), `deduplicated_bytes` (unique_csize), `encryption`,
`info_at`, `info_status`, `check_status`. Unknown measurements stay null and cached
measurement timestamps remain separate from current snapshot time. Configuration
paths, credentials, raw refresh errors and archive filenames are not projected.
There are no repository write/maintenance/delete/restore grants.

Focused regressions: `tests/test_mobile_details.py`, history-log security tests,
mobile auth/refresh/control tests and DE/EN settings browser tests.

## Monitoring details (#745)

The coordinated pre-release client adds the following exact authenticated routes.
All use the existing monitor:read device bearer, current user and maintenance
checks; browser/internal/widget tokens cannot call them. Credentials are checked
again after detail reads, including revocation during slow archive listing.

- GET `/api/mobile/v1/monitoring`: `sampled_at`, nullable `resources`,
  `restore_tests`, `groups`. An unavailable section is null, never a fabricated
  zero. Resources expose host CPU percent, total/available RAM, measurement time,
  available/stale flags. Restore entries separate latest attempt, retained proof,
  validity, due/next run, scheduler/policy and structured step identifiers/status/
  duration/error codes. Groups expose names, member counts and latest run status,
  completed/total steps. Lists contain at most 100 entries and expose total count.
- POST `/api/mobile/v1/repositories/archives`, exactly `{repository_id}`: opaque
  managed repository ID, name, sampled_at, total and at most 100 newest `items`
  (name/start/end/duration_seconds). Explicit load only: the existing service can
  mount SMB and execute Borg list; no periodic refresh. Duration is measured or
  derived from valid recorded endpoints, otherwise null. No archive file browsing,
  deletion, extraction or restore. 400 invalid input, 404 unknown managed ID,
  503 unavailable repository; messages never reveal backend paths or secrets.
- POST `/api/mobile/v1/reports/read`, exactly `{days: 7|30|90}`: existing server-local
  daily outcomes, range, counts, success_rate and average_duration_seconds.
  Success denominator is success + warning + error; skipped/cancelled/unknown are
  separate. Empty denominator remains null. No Borg I/O.
- POST `/api/mobile/v1/groups/read`, exactly `{group_id}`: current run, member IDs/
  names and last five runs, each at most 100 ordered steps. Missing members have
  null names. Counts of completed attempts exclude pending/not_run; never infer
  a time percentage. Existing group service reconciles orphaned runs; no group
  start/stop/schedule mutation is authorized by mobile.

Snapshot jobs now include `location` and `sort_name`: same normalization and
location sequence as `ui/js/pages/jobs.js` (local/usb/smb/storagebox/utility),
then name ordering. Opaque IDs remain unchanged. All projections omit commands,
raw errors, process IDs, cgroups, paths, secret references and descriptions.
Names/archive names are authorized display metadata. No legacy fallback routes
were added; update the pre-release app and backend together.

## Independent host resources (#746)

`GET /api/mobile/v1/resources` returns the existing host projection directly:
`{available, stale, sampled_at, cpu_percent, memory_total_bytes,
memory_available_bytes}`. It uses the same scoped bearer/maintenance guard and
post-read session/user recheck as monitoring. It does not load restore plans or
group history. The shared resource sampler is unchanged: its first snapshot has
no CPU delta, its next sample is after one second, then cadence is one second
with tracked jobs and ten seconds otherwise. Missing counters remain null.

The Android app requests this small projection immediately on overview/system
views, after two seconds while warming up, then every five seconds after response
completion. Requests do not overlap or run in the background; transient errors
back off to thirty seconds and auth/unsupported errors stop polling. Composite
monitoring retains its thirty-second cadence and existing schema. Timestamp
seconds and the refresh explanation are visible in the app.
