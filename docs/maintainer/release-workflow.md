# Release workflow

This document defines the normal public path from a source change to a test
package and, after explicit approval, to a stable release. Confidential advisory
fixes use [the private security workflow](security-release-workflow.md) instead
of the public test-channel. Both paths share the package builder and artifact
verification, and require explicit approval before stable publication.

## Goals

- Every package is tied to an exact pushed commit.
- The full test suite runs exactly once for that final commit.
- Test-channel and stable use the exact same package bytes.
- Feature and fix PRs never contain stable release artifacts.
- Stable promotion happens only after explicit user approval and in a separate
  release PR.

## 1. Development

1. Work on an issue-specific feature or fix branch.
2. Run focused tests while developing.
3. Add a release-note fragment for a user-visible change under
   `release-notes/pending/<issue>.md`.
4. Commit all final changes and push the branch.

Internal changes with `release-note::no` do not need a fragment.

Use the categorized Markdown format documented in
`release-notes/pending/README.md` (#505). The build merges matching categories
and preserves headings, spacing and nested lists. The version block copied to
stable is identical to the tested changelog; there is no separate stable text.
Changing tested notes requires a new committed, verified test candidate.

Do not run `plugin/build.sh` or `plugin/build-candidate.sh` directly. These are
internal builders for exported, prepared source trees. Publishing public/private
entrypoints first verify the appropriate attestation and remote commit. The
non-publishing CI preview described below deliberately creates no attestation.

## 2. Final source preflight

Run the full preflight once, after the final commit has been pushed:

```bash
./plugin/mr-preflight.sh
```

The script fails before the expensive tests when:

- the branch is `main`;
- the worktree is dirty;
- the branch has no delta against `origin/main`;
- the branch contains stable manifest or package changes;
- `APP_VERSION` was changed in a feature/fix PR;
- the local commit is not identical to the pushed branch.

After the cheap checks it runs syntax checks and the complete pytest suite.
When successful, it writes a commit-bound attestation below `.git/`. This file
is local and is never committed.

The attestation becomes invalid when the commit, branch, merge base, deployable
source digest, or worktree changes. A changed commit therefore needs one new
final preflight after it has been pushed.

## 3. Pull request and test channel

Create or update the implementation PR after the final preflight. The PR must
not contain:

- `borg-backup-ui.plg` changes;
- stable `releases/borg-backup-ui-*.txz` files;
- a release-only `APP_VERSION` bump.

Build and publish the test package with:

```bash
./plugin/deploy-test.sh <version>
```

`deploy-test.sh`:

- verifies the local preflight attestation;
- verifies that local HEAD still equals the pushed branch;
- exports that exact commit into a repository-local staging directory;
- renders release notes from the committed pending fragments;
- records source commit, merge base, source digest, and release-note digest in
  `build-provenance.json` inside the package;
- builds the package only in the staging tree;
- publishes a minimal test-channel snapshot containing one manifest and one
  package.

It does not rerun pytest and does not modify stable release files in the
feature branch.

For #484/#671, both package builders apply the same permission rules. The
portable builder validates normalized entries while compressing once; native
makepkg retains its generated hooks and subsequent normalization pass. Only
plugin-owned directories and Slackware package metadata retain
directory entries; shared ancestors such as `/`, `/boot`, `/etc/rc.d` and `/usr`
are omitted. Payload directories/executables use `0755`, other regular files
use `0644`, and ownership is `root:root`. Artifact verification rejects shared
directory entries and unsafe payload modes before publication or promotion.
This preserves existing host permissions; it does not repair an already affected
host. Recovery instructions are in user-manual section 13.6 (German and English).

Verify the published snapshot:

```bash
TEST_COMMIT="$(git ls-remote origin refs/heads/test-channel | awk '{print $1}')"
curl -fsSL "https://raw.githubusercontent.com/borgforge/borg-backup-ui/${TEST_COMMIT}/borg-backup-ui-test.plg"
```

Check version, package URL, MD5, SHA256 (new candidates), plugin URL, and that
the snapshot contains exactly one package. New installers verify SHA256 on
download and reuse of a cached package, in addition to MD5. Old MD5-only
manifests remain readable; promotion preserves the tested installer block.

## 4. User test and merge

The test-channel version is the user test candidate. It is not a stable
release approval.

After successful testing, merge the implementation PR. Do not create a stable
release unless the user explicitly approves it, for example:

```text
Test erfolgreich, Release erstellen
```

## 5. Stable promotion

After explicit approval, promote the tested version:

```bash
git switch main
git pull --ff-only origin main
./plugin/promote-release.sh <version>
```

Promotion must be started from a clean local `main` that exactly matches
`origin/main`. The script stops before changing anything if the branch, working
tree, or commit does not match.

Promotion:

- starts from current `origin/main`;
- downloads the exact test-channel package;
- verifies package MD5 and embedded provenance;
- verifies that the tested source digest equals current `origin/main`;
- copies the package byte-for-byte without rebuilding it;
- copies the exact tested release-note block;
- consumes only the pending release-note fragments named and hashed by the
  package provenance;
- updates `APP_VERSION` and the stable manifest;
- keeps only the newest three release-note sections in the stable plugin
  manifest changelog;
- keeps at most five stable packages under `releases/`;
- creates or updates a separate `codex/release-<version>` PR.

If current `main` does not match the tested source digest, promotion stops. A
new test-channel package must then be built and tested from the new source.

## 6. Release PR preflight

Release branches use the artifact-only preflight:

```bash
./plugin/release-preflight.sh
```

`plugin/mr-preflight.sh` delegates to it automatically for
`codex/release-*` branches. It verifies the manifest, package, version,
retention, provenance, source digest, release-note consumption, pushed commit,
and byte identity with the test-channel package. It does not rerun the source
test suite.

Allowed release-PR changes are limited to:

- `borg-backup-ui.plg`;
- `borg_backup_ui.py` for the version bump only;
- `releases/borg-backup-ui-*.txz`;
- deletion of the consumed `release-notes/pending/*.md` fragments.

## 7. Rollback limitation

Migration backups protect configuration data, but they do not downgrade the
installed plugin code. Unraid does not provide an automatic application
rollback through this workflow. A code rollback therefore requires an
explicitly prepared and tested plugin version; never restore migration state
files manually as a substitute for a code downgrade.

## 8. Troubleshooting

### Preflight attestation missing or stale

Ensure the worktree is clean and the final commit is pushed, then run the full
preflight once again. Do not copy or edit the attestation manually.

### Stable promotion reports a source-digest mismatch

`main` changed after the test package was built. Create and test a new
test-channel version from current source.

### Direct build is rejected

This is intentional. Use `deploy-test.sh` for test packages and
`promote-release.sh` for stable promotion.

## 9. Read-only CI and local previews (#671)

`ci.yml` classifies the actual Git delta on pull requests and main pushes.
Source changes run shared syntax/static/binary-integrity checks and the full test
suite. Pure release changes run artifact-only checks, including source/notes,
retention, checksums and exact note-fragment consumption; PRs also compare the
tested package bytes. A release branch name alone never skips tests, and mixed
source/release changes fail. `security.yml` audits the locked runtime
dependencies on PRs, main, manual dispatch and a weekly schedule. Dependency
findings fail visibly; no advisories are suppressed. Both workflows use read-only
repository permissions and do not install a plugin or publish a release.

Manual `testing-release.yml` performs checks, then builds a local candidate.
Manual `stable-release.yml` is restricted to main and prepares a stable preview
from the current immutable test snapshot, without rebuilding. Both upload review
artifacts with 14-day retention and **cannot publish**: there are no channel
writes, tags, release API calls, bot secrets or write permissions. Their artifact
download links are not Unraid update feeds. `unraid-8` fails before packaging
until the official SDK and real target validation are available (#549).

For a local preview of a clean committed tree (all output stays in the repo):

```bash
python3 plugin/ci_pipeline.py prepare --platform unraid-legacy \
  --version YYYY.MM.DD.HHMM --output .release-tmp/preview-unique
```

Use a real timestamp version and a new output directory. Run the quality/tests
first. This command intentionally does not require a push or issue a release
attestation; a preview never authorizes the normal publishing entrypoints.
Private-advisory guards still apply. Stable previews additionally require clean
HEAD equal to fetched `origin/main` and a tested source/notes match:

```bash
python3 plugin/ci_pipeline.py stable-preview --platform unraid-legacy \
  --version YYYY.MM.DD.HHMM --output .release-tmp/stable-preview-unique
```

Build metrics record step, wall/CPU time, peak child RSS and exit code in
`metrics.jsonl`, without command arguments or environment. Cache only downloaded
pip content; wheels remain hash-verified. CI keys include OS/CPU/Python and the
runtime lock. Source export excludes retained releases/tests; archive timestamps
use the source commit epoch. Reproducibility is scoped to the same commit,
version, platform, lock and builder/toolchain, not arbitrary Python/xz versions.

Before activating publication, review a separate change covering bot identity,
stable environment approval, artifact provenance and immutable promotion, status
checks, tag/asset policy and real Unraid tests. The existing manual release
workflow and the explicit maintainer test-approval requirement remain in force.
See [the audit](../development/ci-cd-audit.md) and
[generation boundaries](../development/multi-generation-plugin-architecture.md).
