# Private Python runtime (#548)

## Release status and ownership

The source implementation is not a stable-release announcement. The first
stable version without a Python 3 for Unraid requirement is **not assigned**:
Unraid tests and explicit test/stable approval are pending. Published stable
2026.11.03.1237 still needs external Python. When promoting the verified test
candidate, record the first stable version here and in the English/German
installation instructions, README and CA descriptions. The #548 release-note
fragment makes the change explicit in that release's manifest.

The Borg Backup UI maintainer owns Python/native-library updates, triage and
compatibility testing. The daily monitor does not update hosts or authorize
releases. Issue #548 stays open until the manual matrix, published test candidate,
monitor activation and version-specific documentation are verified.

## Provenance and package layout

`runtime/python/runtime.lock.json` is the single version/build/component inventory
used by the builder for the planned source version. The monitor also reads
actual runtime provenance from the current stable package. If a source update
is merged before its stable release, both builds remain monitored; duplicate
findings are grouped. Older releases without private Python do not create a
fictitious shipped-runtime baseline. The initial supplier is
[Astral python-build-standalone](https://docs.astral.sh/python-build-standalone/),
CPython 3.13.18, build 20261026, ordinary GIL, x86_64-unknown-linux-gnu (not v2/v3).
The 3.13 series is deliberately bounded; new stable series require compatibility
review. External Python 3.10 through 3.13 must pass the same import/operation probe.
Compatibility with an old external version is not an upstream support guarantee.

The full provenance archive, supplier-stripped install archive, downloads
inventory, supplier license and `PYTHON.json`
are SHA256-pinned. The builder compares Python version, target, glibc requirement,
linked libraries and native source versions to the committed inventory. It
rejects unknown linked libraries or inventory drift. Native versions come from
the pinned supplier source inventory; runtime checks also exercise SSL, SQLite,
compression, authentication and the exact packaged Apprise dependencies.

The full supplier archive is a build input only. Executable binaries come from
the separately pinned `install_only_stripped` archive from the same release.
This removes debug data while preserving supplier-produced relocation metadata.
Package build and validation reject payloads above GitHub's 100 MiB ordinary
Git-file limit before test/stable publication. The package contains a compressed
install tree, original component license texts, supplier license, original
`PYTHON.json`, supplier downloads inventory and normalized provenance. Compiler
objects, headers/static development archives, pip/ensurepip, stdlib tests,
Berkeley DB and Tk/GUI extensions and their libraries/resources are omitted.
Built-in readline/ncurses and their libraries remain inventoried. This is an
application runtime, not a general Python SDK. Original upstream metadata is
retained as evidence; `excluded_extensions` records the curated omissions.

The normalized outer metadata binds the compressed bundle SHA256 to the same
lockfile. Package validation verifies these against the embedded source
provenance. Historical packages without the new marker retain their existing
verification contract. No binaries are downloaded on Unraid: the archive is
included in the plugin package and extracted into
`/usr/local/lib/borg-backup-ui/python/<bundle-sha256>/` on demand.
Unraid mounts `/run` with `noexec` (and may impose a small size limit); only
selection/lock files and bytecode cache remain there. The private executable tree
lives in Unraid's writable `/usr` overlay. Before extraction, the launcher checks
direct execution in the staging directory and reports a specific error for
`noexec` or denied execution. Tests override `BBUI_RUNTIME_STATE` and
`BBUI_RUNTIME_ROOT` independently; production uses the paths above. Python libraries and
symlinks stay inside that private tree; system Python and global PATH/site-packages
are unchanged. RAM trees survive service restarts and disappear on reboot. Old
hash trees are retained until reboot so running workers are not broken by an
upgrade. Uninstall removes only `/run/borg-backup-ui` and
`/usr/local/lib/borg-backup-ui` in addition to the plugin payload, not another
Python provider. Previously extracted trees under the old `/run` location are
left until reboot/uninstall so already-running workers on other hosts are not
broken by an upgrade.

The supplier advertises glibc 2.17. `check_python_runtime.py` checks the actual
shipped ELF symbol requirements against this ceiling. This is necessary evidence,
not a claim of completed Unraid host testing. Memory use includes the extracted
runtime; insufficient RAM, missing/corrupt payload or failed probes fail with a
repair message. The control page can stage the runtime for recovery while the
service is stopped.

## Selection and isolation

The Bash launcher works without Python and serializes staging with flock. It
probes an absolute external python3 path with a timeout and `-E -s -S`, then uses
the bundled fallback when absent/incompatible. A running service pins helpers to
its selected path; a subsequently installed provider is reconsidered only after
service stop/restart. Removal of the active external binary produces an error
for new helpers rather than silently switching them; restart selects fallback.

Backup/scheduler, restore, resource workers, recovery and notifications use the
parent's absolute interpreter with host startup customizations and sites disabled.
Bytecode stays in the existing RAM cache for the daemon; isolated workers disable
bytecode writes. Hook examples use the new `BBUI_PYTHON` environment value.
Existing saved Bash hooks are preserved, not rewritten. Hooks explicitly calling
`python3` or importing extra third-party packages retain their own prerequisites;
review them before removing a provider used by custom scripts or other plugins.

Diagnostics show source, version and path under Settings > System Health &
Migration and on the Unraid control page. The same actual-process diagnostics
are recorded in backup and restore-test logs (including the protected worker).
`BorgBackup executable` identifies the backup program; `Borg Backup UI Python`
identifies the interpreter running the application/worker. During installation
and service start, the console reports private extraction or reuse followed by
the selected interpreter; interpreter details also enter the service log.
An unavailable runtime prevents account discovery and is shown as an unavailable
check, not as evidence that no administrator exists. Restart remains available
for a running service whose external interpreter has been removed.
Settings > About > Third-party separately shows the bundled CPython version/build
and the active interpreter. Each bundle owns its expandable full license notices;
the build generates runtime/licenses/bundles.json from the packaged Python archive,
Apprise wheel license/notice files, Borg and Prism notices. It does not read host
site-packages or fetch licenses at runtime. Original supplier notices are retained
unchanged; the component inventory identifies the libraries actually shipped. DE/EN user documentation explains the
transition. New manifests use Unraid's native `Min="6.12.5" Max="7.99.99"`
attributes and CA metadata uses MinVer/MaxVer. Stable promotion carries the tested
gate forward. Unraid 8 prereleases are above this maximum. The broad 7.x bound is
a generation boundary, not certification of every future 7.x release.

## Daily release/security monitor

`python-monitor.yml` runs daily at 07:17 UTC and supports manual dispatch on main.
It shares the already configured `dependency-monitor` environment: main only,
`BBUI_BOT_TOKEN` belonging to borg-codex-bot, repository Issues read/write. It needs
no extra secret or environment. PR code never receives that secret. Apply checks
workflow identity, current main and bot identity before each write and verifies
the persisted author. Read-only preview: `python plugin/python_monitor.py` with
the hash-pinned `.github/requirements-monitor.lock` dependencies available.

Sources:

- [Python PEP release/lifecycle API](https://peps.python.org/api/python-releases.json):
  actual stable patch/security releases, new stable series and support end dates.
  Ignore expected future releases and prereleases. Warn at 180 days, escalate at
  90 days and again when support ends; do not silently move the shipped series.
- [Supplier latest-release metadata](https://raw.githubusercontent.com/astral-sh/python-build-standalone/latest-release/latest-release.json)
  and its GitHub release assets: available patch builds and same-version rebuilds
  for the locked platform/series. Missing platform assets fail the run.
- [NVD CVE API](https://nvd.nist.gov/developers/vulnerabilities): query versioned
  virtual CPEs for CPython and every shipped native component, including OpenSSL.
  Apply the public rate limit, bounded pagination and explicit product mappings.
  Exclude non-vulnerable contextual products, explicit mandatory Windows/macOS
  contexts and ranges known not to match. libedit, mpdecimal and libuuid use
  keyword queries where versioned CPE coverage is unreliable; these candidates
  require manual applicability review.
  Unknown native version syntax is conservatively sent for triage. NVD can lag
  disclosure and omit/unanalysed records; no monitor proves absence of bugs.
  CVE issues link to affected/fixed ranges and require feature/platform review.

All sources must complete before writing any issues. Missing inventory coverage,
source/schema errors and access failures are visible failed runs, never a quiet
all-clear. No credentials go to upstream metadata endpoints. Only validated
identifiers/versions and locally constructed links enter issue bodies.

Issues use a separate `bbui-python-monitor` managed block, preserving maintainer
notes/checklists. CVEs affecting several components are grouped. Unchanged
findings cause no write. `status::waiting` and not-planned closures defer;
closed release/build issues remain closed. Changed security facts may reopen a
completed security issue while the shipped version remains affected. Review
initial preview findings before the first apply; the monitor does not suppress
pre-existing advisories or automatically close resolved issues.

After merge, dispatch the monitor twice on main. Verify successful source scans,
actual bot identity, issue authors/contents where findings exist and unchanged
second-run counts. Record run links in #548. A local preview is not activation.

## Update procedure

1. Use an issue; review the supplier release, CPython changes, CVEs and licenses.
2. Pin the new archive and hashes. Extract upstream PYTHON.json and downloads
   metadata; regenerate `components` using `python_runtime.inventory` and review
   exclusions/coverage. Never handwave new native libraries or glibc changes.
3. Run focused tests and `check_python_runtime.py` in repository-local scratch
   space. PR CI runs the real interpreter/ELF/vendor contracts and full source
   suite. No automatic dependency update or installation occurs.
4. Merge any CI-policy changes before privileged test publication. Publish and
   verify a test candidate through the trusted main workflow, then execute the
   manual matrix. Obtain explicit test/stable approval; use a separate stable PR.
5. Verify the release, update the first-version documentation if this is the
   transition release, and rerun the monitor against the shipped provenance.

The CI logs explicitly name the source, Python version and absolute interpreter
for host/private contract tests, private application tests and the full source
suite. A host interpreter cannot silently substitute for the private test run.

## Required manual compatibility matrix (pending)

Run the following on **Unraid 6.12.5** and the maintainer's supported **7.x**
installation(s); record exact OS, CPU, Python/build, candidate version and results.
No Unraid host is available in the development environment, so none is marked
passed here. Future 7.x versions require new validation.

- Fresh install without Python: offline boot, API/UI, admin recovery, notification,
  manual and scheduled backup, browse/restore and restore test.
- Suitable external Python: repeat those operations; verify external diagnostics.
- Missing, old, incomplete or unusable external Python: verify private fallback.
- Install a compatible provider while running: no switch; restart then selects
  external. Remove external between starts and reboot: private recovery.
- Missing/removed active interpreter: visible error; controlled restart recovers.
- Upgrade: configs, jobs, reports, secrets and repositories preserved; active
  workers not switched to another tree. Other plugins' Python remains intact.
- Uninstall/reinstall: private RAM files cleaned, external provider untouched.
- Simulate corrupt runtime bundle and low RAM: actionable failure, no half-staged
  runtime used. Verify no global Python links, site-packages or PATH were changed.
- Native plugin manager rejects 6.12.4 and 8.0 (including prerelease), accepts
  6.12.5 and the tested 7.x versions. CA metadata alone is not installer proof.

## Initial advisory review (2026-11-04; open)

The public metadata preview found 13 SQLite CVEs affecting supplier SQLite
3.53.1 (CVE-2026-11822, CVE-2026-11824, CVE-2026-119371 through
CVE-2026-119379, CVE-2026-119586 and CVE-2026-119591). NVD lists fixes in
3.53.2 / 3.54.0; the pinned supplier release still contains 3.53.1. SQLite is
built into libpython, so deleting sqlite3's Python package would not remove the
native library. Retain truthful inventory and monitor coverage.

The application uses JSON stores and does not open SQLite databases or accept
SQL; the runtime probe only executes a fixed `select 1` against a new in-memory
database. This limits current application exposure, but is not a blanket safety
claim for arbitrary custom Python hooks. Review supplier updates and record the
maintainer's applicability decision before stable approval; do not mark the
monitor or #548 complete based on the preview. CVE-2026-3087 has an explicit
mandatory Windows context and is excluded for this Linux target by tested logic.
