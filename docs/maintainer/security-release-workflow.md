# Confidential security fixes

Use this workflow for a draft GitHub Security Advisory and its temporary private
fork. The advisory replaces a public issue during confidential development.
Keep the code PR, tests, packages and discussion private. Do not create a public
test-channel build. This workflow does not publish an advisory or request a CVE.

## Identity and setup

Keep `origin` pointed at `borgforge/borg-backup-ui`. Add an explicit remote for
the advisory's temporary private fork. Use process-local bot credentials for
`gh` and the bot's dedicated SSH key for Git. Never change the maintainer's
interactive login or put credentials in remote URLs, manifests or packages.

Run from the repository root, substituting the advisory and remote names:

```bash
python3 plugin/security_workflow.py init --advisory GHSA-xxxx-xxxx-xxxx --remote security-advisory
```

Initialization reads the parent repository's advisory API. It verifies the bot
identity, draft status, private fork identity and both fetch/push URLs. A remote
name alone is not evidence that a repository is private. API failures stop the
operation. Repository/PR API access to the fork is not required for builds.
If `gh pr create` is unavailable, the maintainer creates the private PR in the
browser; the agent must not fall back to another GitHub account or a public PR.

The context is stored under the common Git directory and also guards linked
worktrees. Normal preflight, test-channel publishing, dev deploy and normal
stable promotion stop while this context is active. These are workflow guards,
not a replacement for reviewing manual Git commands.

## Private preflight

Commit and push the implementation branch to the private remote first. Then:

```bash
./plugin/mr-preflight.sh --security
```

The preflight verifies clean source, the exact private remote commit, private
base and implementation/release separation. It compiles Python sources and
runs the full pytest suite locally. Test output and temporary test data remain
below `.release-tmp/security/<advisory>/`. A successful, unchanged run writes a
separate private attestation, binding the advisory context, commit, branch,
base, source digest and test report hash. Failed or changed runs do not attest.
Do not manufacture an attestation from an earlier test report.

Provide Python/pytest and other test dependencies through the process
environment. Skipped tests remain visible in `tests.log`; in particular,
missing Borg integration tests do not imply a successful Unraid installation
test. GitHub integrations/status checks are unavailable in temporary private
forks, so local verification and maintainer review are essential.

## Build and verify a local candidate

```bash
python3 plugin/security_workflow.py build YYYY.MM.DD.HHMM
python3 plugin/security_workflow.py verify --candidate /absolute/path/to/candidate
```

The build rechecks the attested private source before and after packaging,
without rerunning pytest. Both public and private paths use
`plugin/build-candidate.sh` and the existing package builder. The shared helper
exports an exact commit, prepares provenance and release notes, builds and
checks the package. It never publishes. Dependency downloads still use the
existing hash-locked requirements; this is not an offline dependency cache.

Candidates remain in `.release-tmp/security/<advisory>/<version>/`. A version
cannot overwrite an existing candidate. The directory contains:

- the tested `.txz` and `borg-backup-ui.plg` for local installation;
- `SHA256SUMS`, provenance, release notes, and `tests.log`;
- `candidate.json` tying artifacts to the private preflight;
- `INSTALL.md` and a separate `release-template.plg` for future promotion.

The bundle hashes protect against accidental changes relative to trusted local
metadata; they are not a digital signature. Transfer the bundle privately over
an authenticated channel. No automatic upload is performed.

## Unraid test

Use `INSTALL.md` in the generated candidate. Check `SHA256SUMS` after transfer,
place the TXZ at the documented persistent plugin path, and install the local
manifest through Unraid's `plugin install`. Keep the normal plugin name and
manifest filename so reboot does not install two different variants.

The private manifest has no update URL. It requires the local package and
checks SHA-256, including repeat-install/boot paths. Missing or incorrect
packages fail instead of downloading from a public URL. Existing installation,
Apprise extraction, start/stop and removal hooks remain in use. Keep the TXZ on
flash for reboot recovery. Do not install `release-template.plg` during private
testing; it contains future public distribution metadata.

Manually test the fix, login, normal logs, installation/upgrade, restart and
Unraid reboot. Automated tests simulate package installation, repeat install
and volatile-file recovery; they cannot validate Unraid's plugin manager.
After stable publication, explicitly install the official stable manifest to
restore the normal update URL. This transition still needs a maintainer test.

## Prepare locally, publish only after approval

After explicit successful-test/release approval, prepare a local release tree:

```bash
./plugin/promote-release.sh YYYY.MM.DD.HHMM --security-candidate /absolute/path/to/candidate
```

Without a publication flag this only exports a local preview. It copies the
exact TXZ, applies tested notes/metadata, consumes only matching note fragments,
checks retention and verifies release artifacts against the tested source.
It does not push, create a public branch/PR, or change the current checkout.

Coordinate the public source merge and release with the maintainer/reporter.
A public code push already discloses the fix. GitHub's advisory merge process
is special: only one open PR may target the temporary fork's main branch for
the merge. Do not create a second private main-targeting release PR blindly.
Keep release artifacts separate from the implementation PR.

Once the approved fix is on public `origin/main`, start from clean, synchronized
local `main`. Explicit coordinated publication uses:

```bash
./plugin/promote-release.sh YYYY.MM.DD.HHMM \
  --security-candidate /absolute/path/to/candidate \
  --publish-security GHSA-xxxx-xxxx-xxxx
```

This command is a real publication action: it pushes a public release branch
and creates/updates a public release PR. It requires the active local context
and advisory to match the candidate, rechecks the draft/private fork, and
requires the public main source digest to equal the tested source. It never
reads an unrelated test-channel package. The TXZ remains byte-identical;
distribution metadata changes from the local manifest to the stable template.

The release PR is verified using:

```bash
./plugin/release-preflight.sh --security-candidate /absolute/path/to/candidate
```

This checks artifacts and package identity without repeating source tests.
If tested deployable source changes, build and test a new candidate instead.
Release merge, CVE/credit coordination and advisory publication remain explicit
maintainer actions, outside these scripts.

After the advisory is published, archive the local guard:

```bash
python3 plugin/security_workflow.py finish --advisory GHSA-xxxx-xxxx-xxxx
```

`finish` verifies published status before clearing the active context. The
archived context, test reports and candidate files remain local. Advisory-named
branches remain blocked by the public guard; use a normal branch for later work.

Reference: [GitHub temporary private forks](https://docs.github.com/en/code-security/tutorials/fix-reported-vulnerabilities/collaborate-in-a-fork).
