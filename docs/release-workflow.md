# Release workflow

This document defines the only supported path from a source change to a test
package and, after explicit approval, to a stable release.

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

Do not run `plugin/build.sh` directly. It is an internal builder that accepts
only an exported and prepared source tree created by the deployment workflow.

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

Verify the published snapshot:

```bash
TEST_COMMIT="$(git ls-remote origin refs/heads/test-channel | awk '{print $1}')"
curl -fsSL "https://raw.githubusercontent.com/borgforge/borg-backup-ui/${TEST_COMMIT}/borg-backup-ui-test.plg"
```

Check version, package URL, MD5, plugin URL, and that the snapshot contains
exactly one package.

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
