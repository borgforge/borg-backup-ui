# Database backup validation (#591)

Automated coverage uses the real managed helper, Docker process-group supervisor,
Borg archive/readback and restore into fresh network-isolated containers. Start
with pre-pulled `mariadb:11.4` and `postgres:16` and the bundled Borg executable
on PATH. Keep TMPDIR and pytest's base directory inside this repository.

```
BBUI_DATABASE_DOCKER_TESTS=1 pytest -q -s tests/test_database_docker_integration.py --basetemp=.release-tmp/database-docker-tests
pytest -q tests/test_database_backups.py tests/test_database_profiles_ui.py tests/test_script_catalog.py tests/test_script_library_ui.py
```

The Docker test substitutes only the host mount detection and filesystem-type probe because the
repository test filesystem is not an Unraid pool. Production mount, permissions,
space and overlap rules have isolated tests, including writable pools, symlink
rejection, directory replacement during export, real Borg readback through held
directory handles, and cleanup without touching a replacement directory. Clients and database processes are
real. Test images expose no ports; generated data is disposable. Failed fixture
startup is not an application export failure. Successful cancellation excludes
zombies (which cannot run) and checks that no active client child remains.

Validated on Linux/Docker with Borg 1.4.5:

| Image | Server/client | Image digest |
| --- | --- | --- |
| `mariadb:11.4` | 11.4.13 | `sha256:250e1609e93c0e6aecf64bfbab2d84d5e89d2481540fe77447ff6c855c3b1873` |
| `postgres:16` | 16.15 | `sha256:1a6ab3f5345eb6dbe04a1349529caabdb0ab09293a09590fad07b2246bfa4b54` |

Real exports also verify native password authentication with special characters,
database discovery, and removal of temporary in-container credentials. Managed
secrets remain separate from public configuration and preserve running snapshots.

Browser interaction tests use Node.js, Playwright and Chromium; set
`BBUI_CHROMIUM` to an installed executable if it is outside Playwright's default
cache. Without those optional dependencies the browser test is skipped.
Fresh Unraid installation and upgrade acceptance remain maintainer tests.

Manual test-channel acceptance on Unraid:

- Fresh install: open both translated settings pages, confirm all three helpers ship
  executable with the bilingual ownership warning and appear read-only with syntax
  highlighting under Scripts > Managed by Borg Backup UI. Only managed database
  helpers appear there, with no unrelated Python modules. No export runs at install.
- Open all four Templates, create an own draft, edit/save/assign the copy and verify
  the original is unchanged. Switching categories retains unsaved own edits.
  Check the script dropdown, Description/Source code tabs (including keyboard navigation),
  neutral gray card headings matching Prometheus and all seven specific descriptions.
  Intro/selection cards and detail tabs must match the Own scripts content surface
  in both themes.
  In Sources & destination, test many folders/profiles, wrapped long names, selection
  counts, retained unavailable profiles and reachable footer actions. Check
  light/dark themes, German/English, mobile layout and the container dropdown.
- Check new run names contain profile and server-local timestamp/offset without a
  UUID; database-job archives use the original prefix/date/time format. Existing
  UUID-only and profile/time/UUID directories remain listable/removable. Duplicate
  names must fail without modifying prior dumps/archives. Verify
  gzip files restore correctly, both sizes display correctly and existing
  uncompressed UUID runs remain listable/removable. Test disk-full/timeout/abort
  without publishing incomplete exports. Optional large-stream regression:
  `BBUI_COMPRESSION_TEST_MIB=5500 pytest -q tests/test_database_compression.py -k bounded_chunks`.
- Upgrade UUID credentials: confirm migration database_secret_names_v1, profile
  snapshots/audit entries without passwords, readable versioned files with profile,
  container and user metadata, and retained old secrets. Recheck after interruption.
  Verify encrypted Secrets export/import and old configuration reference recovery;
  rotate credentials and rename profiles while preserving old snapshots.
- Enter database users/passwords in Settings, load database lists, select scope
  and save. No manual container files/mounts are needed. Test Secrets export/import
  and credential rotation during a run. Check unavailable/wrong staging mounts.
- Keep normal pool permissions (`0777 nobody:users`); only the dump directory
  needs `0700 root:root`. Verify a missing direct child is created only by an
  explicit dump, and mount/path/mode/filesystem errors are distinguished.
- Save a profile, check its connection, export a test dump, cancel an active dump
  and reconcile an interrupted operation. Check per-run status/space and cleanup.
- Check shared application confirmations for local cleanup, profile deletion and
  discarding edits. Cancel must leave files/profiles/drafts unchanged; confirmed
  cleanup must target the displayed directory. Local run help explains its
  cross-profile job/test-dump scope and the absence of Borg archives.
- Run a mixed file/database job and a database-only job. Verify current dumps and
  manifest in Borg, missing/excluded artifacts cause failure, warnings retain
  local dumps, and no previous/partial dump appears in the current archive.
- On a Btrfs pool, run PostgreSQL and MariaDB profiles with `after_archive` retention
  (#694). Both current run directories must disappear after successful readback;
  older/manual dumps must remain. Check per-profile cleanup start/completion logs.
  Directory enumeration must use a fresh view of the pinned run, including files
  created after export opened it. Automated storage tests simulate this Btrfs
  boundary and a consumed directory cursor, including unknown-file protection.
  If cleanup fails, all verified profiles must retain their persisted archived
  status and the log must identify local cleanup as the failing phase. The job
  still fails and skips maintenance; successful readback is not a restore test.
- While a database export runs, check the active Database backups step and elapsed
  time before Docker shutdown. Verify persisted success/failure/cancellation and
  file details, and visibility of assigned Pre/Post scripts. Check seven steps in
  one desktop row and a full eleven-step workflow on narrow cards: only the strip
  scrolls horizontally, keyboard scrolling works, and refresh retains focus/scroll.
- Restore into separate database containers and verify data, views, routines,
  triggers/events and PostgreSQL extensions/roles. Reprovision omitted passwords
  and MariaDB global grants; do not claim a common snapshot with application files.
- Upgrade from the current stable plugin: save profiles and an unrelated custom
  script, then install the candidate. Confirm bundled helpers are refreshed and
  profiles, job references, credential files and custom scripts are unchanged.
- Exercise existing jobs without database profiles and concurrent Docker jobs.
- Export/import job configuration, confirm profile preservation and collision
  rejection, then recheck container credentials on the destination.

Record Unraid version, image digests, client/server versions and outcomes in the
implementation PR before stable promotion. These host-specific checks are not
replaced by the Linux Docker suite.


MySQL and retention (#593):

- Run `tests/test_database_housekeeping.py` and `tests/test_database_engines.py`:
  exact 30-day boundary, terminal states, unresolved/running protection, busy lock,
  symlink/invalid records, linked discovery cleanup and retired-profile preservation.
- With prepared images, run the opt-in MySQL Docker/Borg restore and cancellation
  tests (`BBUI_DATABASE_DOCKER_TESTS=1`, `-k mysql`). Use repository-local TMPDIR/basetemp.
- On Unraid, check each image for required supervisor/client tools. In particular,
  the minimal official MySQL 8.4 Oracle image lacks setsid and must fail clearly.
- Verify that only MariaDB, MySQL and PostgreSQL are selectable and exactly three
  managed helpers appear. No exporter stops the database container.
- Seed an old MongoDB/Redis/SQLite test profile beside a supported profile. Verify
  the warning, supported-profile CRUD, configuration export/import and rejection
  of jobs referencing retired engines. Preserve the old profile, Secrets and dumps.
- Leave unsaved database settings via the Settings menu: test application-dialog
  Cancel/close and Discard, repeated clicks, both languages/themes, and no native
  browser confirm. Reload/close-tab protection remains browser-managed.
- Confirm hourly housekeeping removes only expired proven-terminal metadata and
  linked discovery files. Unresolved crash remnants remain on disk beyond 30 days;
  no dumps, Secrets, archives or configuration are deleted.

Recorded local native verification for #593 (2026-10-24):

- MySQL 8.0.46 (`mysql:8.0-debian`): native dump, Borg readback, restore of data,
  view, routine, trigger/event, MyISAM rejection and owned cancellation passed.
- The previously tested MongoDB, Redis and SQLite exporters were withdrawn at the
  maintainer's request. They are not shipped or offered by the current candidate.
- Unraid fresh-install/upgrade and real container restore acceptance remain required
  before stable promotion.
