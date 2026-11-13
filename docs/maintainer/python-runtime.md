# Private Python runtime (#548)

## Release status and ownership

Published stable **2026.11.11.1135** contains the private CPython 3.13.18
runtime based on supplier build 20261026, including SQLite 3.53.1. The source
update in #732 builds the same Python series with SQLite 3.54.1; it is not a
stable-release announcement. Its test candidate requires real Unraid acceptance
and separate explicit stable approval. Keep the stable and planned inventories
separate until the tested artifact is actually promoted.

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
CPython 3.13.18, ordinary GIL, x86_64-unknown-linux-gnu (not v2/v3).
The 3.13 series is deliberately bounded; new stable series require compatibility
review. External Python 3.10 through 3.13 must pass the same import/operation probe.
Compatibility with an old external version is not an upstream support guarantee.

For unmodified upstream builds, the full provenance archive, supplier-stripped
install archive, downloads inventory, supplier license and `PYTHON.json`
are SHA256-pinned. The builder compares Python version, target, glibc requirement,
linked libraries and native source versions to the committed inventory. It
rejects unknown linked libraries or inventory drift. Native versions come from
the pinned supplier source inventory; the builder executes the isolated binary and verifies Python, SQLite and OpenSSL
versions against the lock. Inner/outer provenance records native versions, SQLite
source ID, compile options, session symbol and CLI presence;
runtime checks also exercise SSL, SQLite,
compression, authentication and the exact packaged Apprise dependencies.

For unmodified upstream builds the full supplier archive is a build input only.
Executable binaries come from
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

## Source-built SQLite remediation (#732)

The planned runtime uses supplier source commit
`9244801782b78e4c4afc5c82a4524aa2101d3298` (20261110), with SQLite **3.54.1**.
`runtime/python/source-build.lock.json` pins the source archive, SQLite archive
and amalgamation hash, original/patched dependency inventory, the SQLite test
expectation, uv driver and build options. Supplier source changes are limited to
the SQLite dependency pin, its distribution-test version expectation and disabling
optional BOLT for this x86_64 target. PGO and LTO remain enabled. The original
BOLT-instrumented profiling run crashed in `test_functools.test_recursive_pickle`;
the final non-BOLT binary passes the unfiltered SQLite, functools and pickle
suites with an explicitly recorded 16 MiB **test-process** stack. The recursive
pickle case also crashes at 8 MiB in the unchanged supplier binary and the
non-BOLT build. This is not a BOLT-only or SQLite regression. Runtime stack
defaults remain unchanged; deep recursive pickling at 8 MiB remains an open
limitation tracked in [#733](https://github.com/borgforge/borg-backup-ui/issues/733).
BBUI application persistence does not use pickle; user-supplied hooks are outside
that assessment. Similar upstream reports provide context, not an exact root-cause
claim: [CPython #157062](https://github.com/python/cpython/issues/157062) and
[LLVM #225479](https://github.com/llvm/llvm-project/issues/225479).
Dependencies/toolchain/sysroot follow that immutable supplier source. Python
remains 3.13.18, ordinary GIL, x86_64 GNU with a glibc 2.17 ceiling.

`plugin/python_source_build.py` builds all dependencies and CPython in Docker
using the supplier's PGO/LTO recipe. Docker/Buildx, the hash-pinned uv driver,
an explicit bootstrap Python and substantial free disk space are prerequisites.
Scratch and caches stay under `.release-tmp/`; no credentials are needed to
compile. For example, with the driver/bootstrap paths chosen explicitly:

```bash
python3 plugin/python_source_build.py build --work .release-tmp/python-source \
  --uv /absolute/path/to/verified/uv --python /absolute/path/to/bootstrap/python
python3 plugin/python_source_build.py package --work .release-tmp/python-source \
  --destination .release-tmp/python-source/output
```

Packaging checks source integrity again, strips ELF debug sections, runs the
supplier distribution tests and CPython SQLite/functools/pickle tests, verifies
actual Python/SQLite/OpenSSL/native features and every ELF's glibc symbols, then
writes an input archive and proposed lockfile. It does not overwrite committed
pins. Preserve the full build/log for review; copy the reviewed archive into
`runtime/python/inputs/` and the generated lock into `runtime/python/runtime.lock.json`.
The input archive includes the install tree, original licenses, Python metadata,
modified supplier dependency inventory and a source-build receipt. Its SHA256,
recipe and receipt hashes are committed. Rebuilding is input-pinned; byte-for-byte
compiler reproducibility is not claimed. This receipt is not CI authorization.

Normal GitHub CI and the existing protected testing pipeline consume this pinned
input without compiling CPython in a credential-bearing publishing job. The
builder checks recipe/archive/receipt/inventory/native-version agreement. The
pipeline still runs the complete application checks and private-runtime checks.
The source input archive is excluded from the installed plugin payload; users
receive only the final private runtime bundle. There is no runtime download on
Unraid and no host-library replacement. Legacy upstream inputs remain readable
for already published stable provenance.

The lock records a distinct `custom_build.id` and a SQLite security floor of
3.54.1. The monitor scans actual component versions, independently for current
source and the published stable payload. While stable is still affected, its
CVE issues remain open and the managed block states when the planned build has
crossed explicit advisory fix bounds. Missing search results alone never prove a
fix. New supplier builds are checked against the combined stable/planned security
floors; a newer build date with older SQLite is labelled an unsuitable replacement
and cannot trigger a misleading fix notification. Returning to an upstream build
requires reviewed metadata, meeting these floors and the normal tests.

CVE-2026-119379 (session) and CVE-2026-119586 (native CLI) remain visible findings,
with scoped non-applicability only when verified native facts prove the required
feature absent. Updating those facts keeps a manually closed issue closed if all
matching baselines still lack the prerequisite. Missing facts or a newly enabled
feature restore ordinary potential/reopen behavior. No CVE is globally ignored.

## Build-time download retries (#728)

Supplier archives, source inventory and license downloads share the same pinned
cache downloader. A valid cached SHA256 is reused without a request. Otherwise,
transient HTTP 408/429/500/502/503/504 responses, temporary DNS failures, connection
failures/timeouts and interrupted transfers are retried at most four times after
5, 10, 20 and 40 seconds (five attempts total). Each request keeps its 60-second
socket timeout; this is not a total wall-clock deadline for a large download.
Truncated responses with a declared Content-Length are treated as interrupted
transfers. Retry diagnostics report the attempt, error category and delay to
stderr without URLs, server bodies or exception details.

Each retry starts a fresh temporary file. Failed/partial downloads are removed;
the destination is replaced only after its exact SHA256 matches the committed
pin. Checksum mismatches, certificate errors, permanent HTTP errors and local
filesystem failures are not retried. Exhausting retries still fails CI/build;
this does not change URLs, provenance, pins or publication approval. There are
no runtime downloads on Unraid.

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

NVD transport recovery (#720) retries timeouts, connection/read failures and
HTTP 408/429/500/502/503/504 at most three times per request. Each attempt has
a maximum 60-second socket timeout. Retries wait 15 then 30 seconds, or the
server's longer `Retry-After` (seconds or HTTP date). A requested wait over
120 seconds or beyond the remaining scan budget fails instead of retrying early.
The existing 6.5-second spacing between ordinary NVD requests remains in place.
NVD requests share a 720-second budget measured from scan start; time spent on
earlier inventory and metadata reads also consumes it. The workflow allows
15 minutes, leaving time for checkout and GitHub reconciliation after bounded
retries. This handles transient failures, not a persistent
NVD outage; no API key, stale cache or empty-success fallback is introduced.

Logs identify the approved source, NVD component/version or CVE, pagination
offset, attempt and sanitized error category (timeout, connection, HTTP status,
JSON/size failure). Other failures identify the inventory, assessment, GitHub
history or write phase. Upstream response bodies, arbitrary exception messages,
URLs and headers are not logged. Permanent HTTP errors and malformed responses
fail without retries. For a failed run, inspect the final phase and preceding
request attempts; retry the protected main workflow after upstream recovery.
Only a complete scan may proceed to issue reconciliation and fix notifications.

Issues use a separate `bbui-python-monitor` managed block, preserving maintainer
notes/checklists. CVEs affecting several components are grouped. Unchanged
findings cause no write. `status::waiting` and not-planned closures defer;
closed release/build issues remain closed. Changed security facts may reopen a
completed security issue while the shipped version remains affected. Review
initial preview findings before the first apply; the monitor does not suppress
pre-existing advisories or automatically close resolved issues.

### Targeted fix notifications (#720)

The same daily workflow compares newer supplier builds with open bot-managed
runtime CVE issues. It stays within each monitored Python series, the ordinary
GIL x86_64 GNU `pgo+lto` build and the locked glibc ceiling. Both the full and
stripped release assets need published SHA256 identities. The monitor downloads
and hashes the full archive, reads only its bounded `PYTHON.json` as data, and
resolves linked library versions from the release tag's immutable source commit.
No supplier binary or source code is installed or executed. The runner needs
`zstd`; missing tools, incomplete metadata or failed scans fail the workflow.

A notification requires positive NVD evidence: an analysed/modified CVE affects
a monitored component version, the candidate contains a newer version beyond an
explicit affected-range upper bound, and no affected component remains unresolved.
An empty search result, missing CPE analysis, exact-version-only match, negation,
keyword candidate or removed component is not proof of a fix. These cases remain
manual triage. The result is a **version-based fix candidate**, not verification
of the new executable, application reachability or a release approval. NVD delays
or missing version bounds can delay notifications even when an upstream fix exists.

When new fix candidates exist, the bot posts **one consolidated comment mentioning
`@TheTwist76`** on the lowest-numbered eligible security issue, linking all affected
issues and the supplier builds and recording component versions and provenance
hashes. GitHub delivers the mention according to the maintainer's notification
settings; the monitor does not change those personal settings or send email itself.
Closed issues and `status::waiting`/not-planned deferrals receive no new fix alerts.
The monitor never automatically closes issues or updates runtime pins.

Bot-authored comments contain durable per-fix markers. All managed security issue
histories, including closed issues, are checked before posting. The identity
includes the CVE, Python series, affected baseline component versions and fixed
range boundaries; it excludes timestamps, wording, scope labels and later builds
carrying the same fix. Thus unchanged daily runs, retried posts after a lost API
response and later rebuilds do not repeat the mention. New affected baselines or
changed fixed boundaries can create a new actionable notification. Do not delete
or edit these marker comments: they are the notification ledger. History lookup
failures abort instead of risking duplicate alerts. Scheduled/manual runs share
the existing workflow concurrency group, and posting rechecks current issue state,
history, protected-main identity and bot identity before verifying the saved author
and body. Preview mode reports counts without posting comments.

This enhancement becomes active only after PR #719 is merged to `main`. Verify two
protected runs, including unchanged second-run notification counts, in #720. Before
merge, focused fixtures cover positive/negative fix correlation and interrupted
notification retries; the current supplier metadata can be verified read-only.
No new plugin test package or stable release is needed for this internal monitor
extension; the existing Unraid candidate remains separate from monitor activation.

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

## Security review and testing authorization (2026-11-06)

See the [per-CVE audit for #705-#718](python-runtime-security-audit.md), including
actual published-package evidence, native build options, supplier availability,
residual risks and the explicit release decision. Eleven SQLite advisories
remain open for the contained library; the normal application does not expose
their required inputs. The session-extension and native-CLI findings are not
applicable to this exact build. None is represented as patched.

The maintainer authorized a new Python-3.13 test candidate based on the reviewed
application paths and continued tracking of the unpatched library. This replaces
the initial blanket release block; it does not mark the library fixed or apply
to arbitrary custom hooks/future SQLite usage. Reassess changes to code, build
options, runtime or advisory facts. Stable promotion remains unauthorized and
requires explicit successful Unraid testing and separate stable approval.

CPython 3.13 remains supported; #705 is future-series compatibility planning.
The inspected supplier Python 3.15.2 build also contains SQLite 3.53.1.
pip-audit covers Python distributions only, not native libraries. Monitor
completion and passing CI do not replace the product-specific assessment.
