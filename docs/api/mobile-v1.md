# BorgForge Mobile API v1 (#738)

This additive API pairs a native client without copying internal API tokens,
widget tokens, browser cookies or Unraid credentials. It grants **monitor:read**
only. There are no mobile job controls, restore operations, logs or configuration
exports. Existing browser/internal automation routes keep their authorization.

## Pairing

1. The Android client uses a validated HTTPS base URL and reads
   `GET /api/mobile/v1/capabilities`: `api_version: 1`,
   `authentication: device_pairing`, `scope: monitor:read`,
   `session_expires_in: 43200`.
2. `POST /api/mobile/v1/pair` with JSON `device_name` (1-80 characters)
   returns `device_code` (32 random bytes, base64url), `user_code` (10 characters),
   `expires_in: 600`, `session_expires_in: 43200`, and `scope`.
3. On the **same HTTPS server**, sign into Borg Backup UI, then open
   `/ui/mobile-devices.html` (also linked from Settings > Users).
   Only enter a code displayed in your own app, never a code sent by someone else.
   `POST /api/auth/mobile/approve` with `user_code` needs a valid browser session
   for an enabled plugin user and a matching HTTPS Origin. Viewers may pair too.
4. `POST /api/mobile/v1/exchange` with `device_code` returns
   `status: pending`, or once only `status: authorized`, `access_token`,
   `session_id`, `expires_at` (Unix seconds), `scope: monitor:read`.
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

## Lifecycle and permissions

Device sessions expire **12 hours after pairing**, without sliding renewal or a
refresh token. Pair again after expiry. `GET /api/auth/mobile/sessions` lists the
current browser user's own sessions (`id`, `label`, `created_at`, `expires_at`).
`POST /api/auth/mobile/revoke` with `session_id` idempotently revokes an owned
session. Foreign IDs do not confer access. Existing logout-all operations also
revoke mobile sessions in their selected user/all scope.

Passwords, roles and enabled state are checked against current users. Account
security changes/deletion revoke persisted sessions and approved pending pairs
before saving the change. Disabling then re-enabling does not restore access.
The fixed expiry and password/role fingerprint also apply after restarts.

`config/mobile-sessions.json` is additive: atomic replacement, file mode 0600,
credential digests only, no raw access/device/user code. An invalid existing
store fails closed with 503, preserving the file. Back up authentication state
securely; restoring an older auth backup can restore still-unexpired sessions.
The store is owned by the existing single server process and serializes mutations
with a lock. Running multiple independent writers against one data directory is
not supported. Anonymous pairing is limited to 10 attempts/IP/hour, approval to
30/user/hour, with 100 pending requests and 500 sessions globally. Reverse proxies
share the connection IP bucket; arbitrary forwarded client IP headers are not
trusted. Expired entries are pruned during store operations.

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

## Monitoring projection

`snapshot` has `api_version: 1`, `sampled_at` (UTC ISO 8601), and arrays:

- `jobs`: opaque `id`, `name`, `status`, opaque `repository_id`, nullable
  `last_run`, `next_run`, `duration_seconds`.
- `history`: latest at most 100 valid timestamped entries, opaque `id`,
  `job_name`, `status`, `timestamp`, nullable `duration_seconds`, `bytes`
  (recorded original data size, not network transfer).
- `repositories`: opaque `id`, display `name`, nullable `bytes`, `checked_at`.
  Individual sizes/checks are currently unavailable, not inferred from jobs.
- `restore_tests`: `job_name`, `status`, `checked_at` from recorded job evidence.
- `storage_daily`: 30 daily `{date: YYYY-MM-DD, bytes: integer|null}` entries
  from the existing overview repository-size aggregation. These are recorded
  samples carried forward by that aggregation, not live disk readings.

Source: `mobile_api.snapshot` projects `_get_jobs` (`jobs_api.list_jobs`),
`_get_history` (`history_api.get_history_data`) and `_get_report_overview`
(`dashboard_overview.get_dashboard_overview`). It excludes paths, raw logs,
archive names, retention/source configuration, credentials and arbitrary fields.
Display names are intentionally included and may be sensitive. Job/status reads
retain existing backend behavior, including legacy status snapshot bookkeeping;
no backup/restore command is executed. Unknown states become `unknown`; no
schedule, progress percentage, VPN state or missing measurement is invented.
Naive recorded timestamps are interpreted in the server's local timezone and
converted to UTC. History entries with invalid timestamps are omitted.

Errors: 400 invalid input/code; 401 invalid/expired/revoked device or browser
session; 403 missing setup, invalid Origin or maintenance write restriction;
404 unsupported method/path/query; 429 pairing limits; 503 unavailable stores.
Clients should discard invalid sessions on 401 and require pairing again.
Never display raw server errors or fall back to the demo for a real server.

## Verification

`tests/test_mobile_auth.py` covers the full HTTP pairing/read/logout flow,
read-only authorization boundaries, CSRF, credential hashing, permissions,
revocation, account changes, expiry, rate limiting, corruption and projection.
Run it with `tests/test_auth.py` and `tests/test_dashboard_overview_api.py` for
focused regression coverage. Hosted CI remains the full-suite authority.

Maintainer test on the test candidate: pair a viewer, check actual job/history
labels and states, revoke it in the browser, refresh the app and expect sign-in;
pair two server profiles and verify isolation; verify a legacy backend stays
unsupported. Never start or cancel production backups as a test.
