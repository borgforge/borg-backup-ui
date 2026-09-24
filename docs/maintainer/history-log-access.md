# History log access

`GET /api/history/log?file=...` remains available to authenticated viewers.
Its JSON response still contains `exists`, `content`, and `path`.

The reader in `api/history_api.py` permits regular `.log` and `.txt` files
inside the configured `GLOBAL_LOG_DIR` and the explicitly supported legacy
directory `/mnt/user/Logs`. Both the roots and candidate paths are resolved
before checking containment. The legacy directory remains readable even when
a different current log directory is configured.

- Absolute paths must resolve inside an allowed root before they can be read.
- Relative paths are interpreted under `GLOBAL_LOG_DIR`, not the process
  working directory. Parent traversal (`..`) is rejected.
- The query is URL-decoded once; percent sequences in filenames remain literal.
- A relocated history entry can still find its basename in the current or
  legacy log directory. This fallback never reads the original outside path,
  even if it still exists. When no safe fallback exists, an outside path
  returns HTTP 403.
- Symlinks are permitted only when the resolved target stays in allowed
  storage and has an allowed extension. A configured log-root symlink is
  resolved as part of the administrator's configuration.
- After resolution, directory components are opened relative to pinned file
  descriptors with `O_NOFOLLOW`. The final file also uses `O_NOFOLLOW` and
  `O_NONBLOCK`, and must be regular according to `fstat`. This rejects symlink
  substitutions during opening and avoids blocking on a FIFO.
- Missing allowed files retain the HTTP 200 / `exists: false` response.
  Malformed requests and non-regular files return HTTP 400; unauthorized paths
  return HTTP 403. Read errors do not return OS exception text to clients.

This boundary applies to the history log reader. The separate live-activity
log endpoints resolve their files by server-side job/run identity and are not
changed by this fix. Permissions and ownership on log directories remain the
administrator's responsibility; hard links and mounts are not separate trust
boundaries enforced by this endpoint.

## Local verification

`tests/test_history_log_security.py` uses synthetic files and authentication
stores. It covers viewer/admin access, absolute and parent-traversal attacks,
file/directory symlinks, the basename fallback, configured root aliases,
single URL decoding, non-regular files, and symlink swaps during opening.
One loopback HTTP test logs in as a real viewer and checks the log endpoint,
history listing, application page, and log-viewer asset.

The fix is tracked privately under GHSA-h4gr-4cm5-92gr. During confidential
development, run tests locally with temporary files below the repository.
Do not run the public test-channel deployment. The current `mr-preflight.sh`
requires a branch pushed to public `origin`, so it is not the private source
attestation workflow; private packaging and coordinated publication require
a separate follow-up.
