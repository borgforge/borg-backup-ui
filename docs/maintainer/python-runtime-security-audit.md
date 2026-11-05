# CPython/native runtime security review (#705-#718)

Review date: 2026-11-06. Scope: current source and published testing candidate
2026.11.05.1312; stable 2026.11.03.1237 still uses external Python and contains no
private runtime. This is an applicability review, not a release attestation.

## Decision

**Blocked for a new security-fix testing candidate and for stable promotion.**
Eleven advisories concern code present in the bundled SQLite library. The normal
application does not expose their prerequisites, but the library is not patched.
Two findings are not applicable to this particular bundle because the required
component is absent. Neither passing tests nor pip-audit removes this blocker.
No stable approval, test installation, or risk acceptance is inferred.

The official supplier latest-release pointer and release API still identify
[20261026](https://github.com/astral-sh/python-build-standalone/releases/tag/20261026).
There is no newer verified supplier build to pin. Retain truthful pins: CPython
3.13.18, SQLite 3.53.1, OpenSSL 3.5.9, Linux x86_64, glibc ceiling 2.17. Do not
remove the Python sqlite3 package and call that a fix: SQLite is linked into
libpython. Do not substitute host libraries or edit supplier binaries.

A source rebuild could update SQLite to at least 3.54.0 (currently 3.54.1), but
would require maintaining the supplier's compiler/sysroot, static-library link,
CPython PGO/LTO build, source patches, licenses, checksums and resulting artifact
provenance. This repository currently verifies supplier artifacts; it has no
reproducible CPython supplier-build pipeline. A local replacement library would
not replace the static copy in libpython. Adopting an unverified binary or a new
runtime supplier is not a safe fix within this change. The supported next step is
a verified supplier update, or a separately designed reproducible source-build
path. No such alternative has been certified by this audit.

## Actual artifact and exposure

The immutable candidate `test-candidates/2026.11.05.1312` contains exactly the
manifest and one 96,002,908-byte package (below the 100 MiB limit). Existing
package validation verified embedded source and runtime lock provenance:

- Source: `f897f2a2f9d81b4472b29bf3d3b5d4ed76c7b815`.
- Package SHA256: `4a9b0bfed02f4914378fe280abeef9f845e08d819230ca9ef30214b46163343c`.
- Runtime lock SHA256: `849252dbfd9df032ba23272535a0e6d5c6909054ba0c3c98d10328777cfcfdd5`.
- Full supplier SHA256: `f003449a05408c2e4b184f2a7abd1ea277081ff1a9100289075243ab5ed81207`.
- Stripped supplier SHA256: `df15fe60d3ff55bf9dcf25824b5572756bb8816ff93865a273d3301d7066a8b7`.

Both supplier asset digests match the official GitHub release metadata and the
lock. Build verification checks downloaded bytes, original PYTHON.json,
downloads inventory, supplier license and all inventoried linked libraries.
The extracted published interpreter was executed with `-I -S`; it reports
SQLite 3.53.1 and OpenSSL 3.5.9. SQLite source ID is
`2026-05-05 10:34:17 c88b22011a54b4f6fbd149e9f8e4de77658ce58143a1af0e3785e4e6475127e9`.

`PRAGMA compile_options` confirms ENABLE_FTS3, ENABLE_FTS3_PARENTHESIS,
ENABLE_FTS4, ENABLE_FTS5 and ENABLE_RTREE. ENABLE_SESSION is absent; the process
also does not export sqlite3changeset_apply. No native sqlite3 CLI is shipped.
This agrees with the supplier's
[SQLite build recipe](https://github.com/astral-sh/python-build-standalone/blob/20261026/cpython-unix/build-sqlite.sh),
which builds/installs the static library, not the shell. Python's `-m sqlite3`
frontend is not SQLite's native shell and does not implement `.recover`.

Source review covers the HTTP/API code, workers, scheduler, recovery, backup,
restore, notifications and the packaged Apprise dependency tree. Application
persistence is JSON. The only application SQLite connection is
`runtime/python/probe.py`: a new `:memory:` database and fixed `select 1`.
Retired SQLite profile fields in `api/database_profiles.py` do not open SQLite.
Backing up or restoring an opaque database file does not parse it with SQLite.
There is no user SQL, uploaded SQLite database, FTS query, changeset or recovery
output input to this probe. Administrative custom hooks can run arbitrary code
and must not be interpreted as covered by this restricted exposure assessment.
Future database features or dependencies require renewed review.

## Individual decisions

All affected-version limits below are taken from the individual NVD records,
with their linked SQLite fixes/release notes; they are not a claim that this
bundle contains those fixes. See [SQLite release history](https://sqlite.org/changes.html).
For every library-present row, status is **open, affected library; unreachable
in the reviewed application flow**. Residual risk is use through custom Python
code or future application changes; keep the issue open until remediation.

| Issue / advisory | Required path and actual bundle | Upstream fixed version | Decision |
| --- | --- | --- | --- |
| #706 [CVE-2026-11822](https://nvd.nist.gov/vuln/detail/CVE-2026-11822) | FTS5 malformed leaf, MATCH; FTS5 enabled, no untrusted DB/query | 3.53.2 | Open; library present, application path unreachable |
| #707 [CVE-2026-11824](https://nvd.nist.gov/vuln/detail/CVE-2026-11824) | FTS5 continuation metadata underflow; FTS5 enabled, no untrusted DB/query | 3.53.2 | Open; library present, application path unreachable |
| #708 [CVE-2026-119371](https://nvd.nist.gov/vuln/detail/CVE-2026-119371) | CTE recursion through SQL/view; core present, no user SQL/view | 3.54.0 | Open; library present, application path unreachable |
| #709 [CVE-2026-119372](https://nvd.nist.gov/vuln/detail/CVE-2026-119372) | FTS3/4 snippet OR/NEAR; FTS3_PARENTHESIS enabled, no MATCH/snippet | 3.54.0 | Open; library present, application path unreachable |
| #710 [CVE-2026-119373](https://nvd.nist.gov/vuln/detail/CVE-2026-119373) | FTS5 detail=none, negative rowids, prefix MATCH; enabled, never used | 3.54.0 | Open; library present, application path unreachable |
| #711 [CVE-2026-119374](https://nvd.nist.gov/vuln/detail/CVE-2026-119374) | FTS5 corrupted index with secure-delete; enabled, no DB input/deletion | 3.54.0 | Open; library present, application path unreachable |
| #712 [CVE-2026-119375](https://nvd.nist.gov/vuln/detail/CVE-2026-119375) | Crafted DB/WAL page size; core present, probe has no file/WAL input | 3.54.0 | Open; library present, application path unreachable |
| #713 [CVE-2026-119376](https://nvd.nist.gov/vuln/detail/CVE-2026-119376) | Deep COLLATE SQL/view expression; core present, fixed select only | 3.54.0 | Open; library present, application path unreachable |
| #714 [CVE-2026-119377](https://nvd.nist.gov/vuln/detail/CVE-2026-119377) | RIGHT/FULL JOIN USING plus authorizer restrictions; core present, neither used | 3.54.0 | Open; library present, application path unreachable |
| #715 [CVE-2026-119378](https://nvd.nist.gov/vuln/detail/CVE-2026-119378) | Malformed R-Tree shadow tables; RTREE enabled, no R-Tree/database input | 3.54.0 | Open; library present, application path unreachable |
| #716 [CVE-2026-119379](https://nvd.nist.gov/vuln/detail/CVE-2026-119379) | Session changeset application; ENABLE_SESSION and native apply symbol absent | 3.54.0 | Not applicable to this build; not patched; reassess if session support is added |
| #717 [CVE-2026-119586](https://nvd.nist.gov/vuln/detail/CVE-2026-119586) | Native shell `.recover` output piped into shell; native shell absent | No verified fixed release; affected through 3.54.1 inclusive | Not applicable to this bundle; host-installed CLI remains outside this assessment |
| #718 [CVE-2026-119591](https://nvd.nist.gov/vuln/detail/CVE-2026-119591) | count(*) over large VALUES SQL/view; core present, no such SQL/view input | 3.54.0 | Open; library present, application path unreachable |

## Python series (#705)

Keep Python 3.13. The [official lifecycle API](https://peps.python.org/api/python-releases.json)
reports security maintenance until 2029-10-01, with 3.13.18 the current actual
release in this series. [PEP 719](https://peps.python.org/pep-0719/) documents its
security-only phase. A move to 3.15 would not itself prove that the supplier's
SQLite was fixed. #705 remains deferred compatibility work, not a security fix.

A future 3.15 review must adjust the explicit 3.10-3.13 provider gate, check stdlib
API removals/behavior, Apprise and native wheel compatibility, ordinary-GIL build
selection, libc/CPU constraints, subprocess isolation, every worker/recovery
entrypoint and the real Unraid matrix. This review did not certify 3.15.

## Monitor and verification changes

The monitor now preserves nested AND/OR platform constraints, checks application
CPE target OS/CPU qualifiers, and keeps unknown/negated conditions for triage.
Versioned NVD hits without configurations remain potential findings. Malformed empty configurations and unstable
pagination (changed totals, duplicates, overflow) fail instead of reporting an
incomplete success. Advisory descriptions/references are fingerprinted as data;
list ordering alone does not change the fingerprint. No upstream prose is run
or copied into issue instructions. Unknown components still fail coverage.

The report explicitly distinguishes completed collection from release authority;
all automatic CVE findings remain potential pending build/feature review. CLI
and optional-extension decisions above are manual, scoped to the exact bundle,
and are not global CVE suppressions. Changed facts/builds may reopen completed
issues; explicit maintainer deferrals and notes remain preserved. Findings that
disappear from a scan are never automatically closed or called fixed. Stable and
planned runtime baselines remain separate, with one grouped issue per CVE.

The builder now executes the real private interpreter and refuses Python,
SQLite or OpenSSL version drift from the lock. It records native source ID,
compile options, session symbol and CLI presence in inner/outer provenance.
`check_python_runtime.py` prints these facts and adds administrative recovery
regressions to the private-interpreter application tests. Existing isolation,
offline staging, notifications/Apprise, ELF, API/UI, worker and restore tests
remain enabled. No security check or protected workflow was disabled.

`pip-audit` checks the locked Python distributions in
`plugin/apprise-requirements.lock`. It does **not** scan the interpreter or its
statically linked SQLite/OpenSSL/native components. The native monitor is a
separate advisory/triage source, not a blocking CI vulnerability scanner today.
A green dependency audit or `CI result` cannot override this documented release
blocker. Automated native release enforcement would be a separately reviewed
CI-policy change, merged before privileged publication.

## Local verification

The real bundled-interpreter harness passed 321 tests (7 environment-dependent
skips), including the added administrative recovery coverage; both the external
3.12.3 and private 3.13.18 probes, packaged Apprise providers, host-path poisoning,
offline extraction and shipped ELF glibc ceiling checks passed. The focused
monitor/runtime/shared-issue suite passed 151 tests (3 skips); after adding the
missing stripped-asset regression, all 42 monitor tests passed. Local skips do
not replace the mandatory GitHub tool/browser checks or real Unraid acceptance.

A complete read-only live scan covered all 12 inventoried components: 14 findings
(one Python series task, 13 SQLite candidates), zero proposed new issues and 13
managed-block updates due to richer advisory fingerprints/classification. This
is not an applied monitor run. The new native-version evidence was produced
from both the extracted published candidate and a freshly verified local bundle.

## Outstanding acceptance

- Obtain a verified patched runtime and repeat per-CVE native/feature assessment.
- Complete GitHub CI for this change; record the PR/run evidence in the issues.
- After merge, run the protected Python monitor twice and verify idempotence;
  local previews do not activate main workflow changes.
- Publish a fresh unique testing version only after the security blocker is
  resolved; verify manifest, package, hashes, source, snapshot and immutable tag.
- Run real Unraid 6.12.5 and supported 7.x fresh install/upgrade, external/private
  provider, API/UI, admin recovery, notifications, scheduled/manual backup,
  restore/restore-test, reboot/offline and uninstall checks. None was performed
  on real Unraid hardware in this audit. Unraid 8 remains excluded.
- Obtain explicit maintainer test/stable approval before a separate release PR.
