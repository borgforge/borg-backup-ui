# GitHub CI and release workflow

This is the normal public workflow (#677). GitHub runs the authoritative full
checks, builds test candidates, publishes the testing feed, prepares stable
release PRs and publishes approved versions as GitHub Releases. Local development uses focused tests. Confidential advisories keep
[their separate private workflow](security-release-workflow.md), including local
private preflight, private candidates and explicit disclosure approval.

## Daily operation

| Action | Maintainer input | Automatic work |
| --- | --- | --- |
| Develop | Push an issue branch and open/update its PR | CI checks the PR integration commit against main: static checks, full tests, dependency audit. A branch push without a PR does not start a second full run. |
| Test on Unraid | Actions > **Publish testing candidate** > Run workflow; branch **main**, version `YYYY.MM.DD.HHMM`, optional PR number, target `unraid-legacy` | Resolve current main or the PR merge commit; wait for/reuse matching CI, request CI if absent; audit current dependencies; build once; verify; publish testing feed and pin candidate. |
| Merge code | Review and merge the source PR | Main CI reuses full checks only for the identical complete Git tree and CI policy. Otherwise full checks run for the changed integration. Dependency audit runs again. |
| Prepare stable | After successful Unraid testing and source merge: Actions > **Prepare stable release PR** > Run workflow; branch **main**, tested version, check confirmation; approve environment `stable` | Verify main CI, fresh dependency audit, candidate/source/notes/checksums; copy tested bytes into a separate release PR. No rebuild or repeated source suite. |
| Release | Review and merge the release PR | The stable feed on main updates when merged. After main artifact-only CI and audit succeed, publish the version tag and GitHub Release with the original tested artifacts. No automatic merge. |
| Retry or backfill GitHub Release | Actions > **Publish GitHub release** > Run workflow; branch **main**, already merged stable version | Verify the merged release PR and its main CI, then finish a matching draft or publish missing metadata/assets. No rebuild, source suite or Unraid-feed update. |

Testing from a PR always includes current main. Moving main/PR refs during the
run aborts publication; start a new workflow. CI-policy changes must first be
reviewed and merged, then tested through the trusted main workflow. The
`unraid-8` target remains explicitly blocked until SDK/system validation (#549).

A workflow summary reports the version, test URL, selected source, immutable
candidate and package SHA256. A green dispatch request alone is not completion:
wait for the **publish** job and its verification summary before installing.

## Names in the Actions overview

New runs describe their source and purpose before technical identifiers (#687):

| Run | Example title |
| --- | --- |
| Pull request CI | `CI \| PR #688 \| Checks and audit \| source=<full commit SHA>` |
| Main CI | `CI \| main update \| Checks and audit \| source=<full commit SHA>` |
| Explicitly requested CI | `CI \| Requested source \| Checks and audit \| source=<full commit SHA>` |
| Test candidate | `Testing 2026.11.02.1800 \| PR #688 \| unraid-legacy` (or `main`) |
| Stable preparation | `Prepare stable 2026.11.02.1800 \| unraid-legacy` |
| Dependency audit | `Dependency audit \| Weekly schedule` or `Dependency audit \| Manual on main` |
| GitHub Release | `Publish GitHub release 2026.11.02.1800` |

The trailing CI SHA is the selected source/integration commit, not a random UUID.
It remains complete because a manual source-check dispatch reports main as its
API head SHA even when testing a PR. The resolver uses the title identifier to
wait for running CI and reject failed checks for the exact source. Historical
`CI <sha>` titles remain recognized. Reuse still requires verified artifacts,
successful jobs and the identical tree/policy; a title alone is never proof.

Titles use bounded PR/main/manual labels rather than arbitrary commit messages,
keeping the source marker predictable. The PR link and branch in GitHub's run
row provide the full change context. These names apply to new runs; existing
history keeps its original titles. Workflow filenames and the required
`CI result` job stay unchanged, so no ruleset/environment setup is needed.
Protected dispatch workflows acquire the new titles after this change is merged.

## Exact-source checks and reuse

The reusable `checks.yml` owns static checks and the full suite. `ci.yml` runs
on PR updates, main pushes and explicit dispatch. It records a `ci-proof` artifact
only after the required jobs succeed. Verification checks GitHub's run/attempt
and job conclusions, the artifact digest, checked commit and **entire Git tree**,
CI policy fingerprint, environment identity and the original full-test run.
Tests, workflows, dependency locks and documentation all belong to that tree.
An identical tree under a different merge/squash commit can reuse the tests.
A changed tree, missing/expired proof or changed policy requires fresh CI.
A failed latest CI run blocks testing even if older evidence is available.

Evidence retention is 90 days; ordinary reports/build downloads are retained
14 days. Reuse chains always point directly to the original full verification.
Local JSON or an old `.git/borg-backup-ui/preflight.json` cannot authorize a
release; the old public attestation commands have been removed.

Dependency audits deliberately run on CI, before testing publication, before
stable preparation and weekly. This short check is repeated because advisory
information can change without a source change. Findings fail visibly; none are
suppressed. This is different from repeating the expensive source test suite.

The dependency audit covers the Python distributions in the Apprise lockfile,
not CPython or native libraries linked into the private runtime. Native advisory
triage and the [runtime release decision](python-runtime-security-audit.md) are
separate requirements. Passing pip-audit/CI does not clear an open native-library
release blocker.

The daily [Apprise release monitor](apprise-monitor.md) (#699) complements these
audits with deduplicated upstream-version and public-advisory issues. Its
`dependency-monitor` environment requires separate maintainer setup and a live
check after merge. It does not update dependencies or authorize releases; Python
runtime monitoring is documented in the [private runtime guide](python-runtime.md)
and remains a mandatory activation check for #548.

## Local development and convenience commands

1. Use an issue and a fresh feature/fix branch. Run focused checks while editing.
2. Commit user-visible release notes in `release-notes/pending/<issue>.md`.
   Internal CI/tooling changes marked `release-note::no` need no fragment.
3. Commit, push and create/update the PR. Monitor GitHub CI rather than running
   the full suite locally and then repeating it in Actions.
4. Request a test candidate for every testable user-visible change. Wait for
   publication and verify the reported candidate before the maintainer test.

The shell entrypoints are convenience clients for the hosted workflow:

```bash
./plugin/mr-preflight.sh
./plugin/deploy-test.sh YYYY.MM.DD.HHMM
./plugin/deploy-test.sh YYYY.MM.DD.HHMM --pr 123
# Only after explicit successful Unraid test/release approval:
./plugin/promote-release.sh YYYY.MM.DD.HHMM --confirm-tested
```

`mr-preflight.sh` reads hosted evidence (release PRs use artifact-only checks).
`deploy-test.sh` dispatches on main; without `--pr`, it resolves the clean,
exactly pushed local branch's open PR, or current main. It performs no local
build. `promote-release.sh` also dispatches only; it requires the confirmation
flag and the stable environment approval. GitHub mutations by agents use
`borg-codex-bot`; the controller verifies `gh api user` before every mutation
and verifies the created/updated PR author. Never switch the maintainer's login
or place tokens in arguments, commits or reports.

Do not call `build.sh`, `build-candidate.sh` or `publish-test-snapshot.sh` as
public release entrypoints. For deliberate build debugging only, a clean local
commit can create a non-publishing preview under `.release-tmp/`:

```bash
python3 plugin/ci_pipeline.py prepare --platform unraid-legacy \
  --version YYYY.MM.DD.HHMM --output .release-tmp/preview-unique
```

That preview grants no publication authority. Stable local previews require
current main and the fetched `test-candidates/<version>` tag. Private-advisory
guards still apply to every public entrypoint.

## Candidate identity and stable promotion

The published `test-channel` branch remains a root snapshot with exactly one
manifest and one package. Only its dedicated publisher may use an exact
`--force-with-lease`. Each new version also gets a lightweight immutable tag
`test-candidates/<version>` pointing to that same snapshot. Protect these tags
against updates/deletion. Older candidates remain available through their tags;
this intentionally retains candidate package objects beyond the rotating feed.
No automatic candidate-tag cleanup is performed.

A version cannot be overwritten with different source or bytes. An interrupted
publication can resume using the same pinned candidate. A retry never rebuilds
that existing version. A newer feed cannot be replaced with an older version.
The candidate tag is created first, so a failed channel push may leave a valid
pinned candidate; retry the same version/source to finish. Concurrent writes
fail the lease instead of overwriting another publisher.

Stable promotion uses the selected immutable tag, never whichever candidate is
currently in the rotating feed. It requires the deployable source digest to
match main, verifies the original source and rendered release notes, advances
the stable version, copies the exact package and consumes only proven note
fragments. The resulting PR changes only the stable manifest, version,
release package and consumed fragments. Keep the latest five stable packages
and the existing manifest changelog retention. Mixed source/release PRs fail.

Package checks cover manifest channel URLs, MD5 and SHA256, embedded source and
note provenance, required payload, vendor bundle and safe permissions. Shared
host directory entries are omitted; payload directories/executables are 0755,
other regular files 0644, with root ownership. Existing host permissions are
preserved; an already affected host still needs the documented manual recovery.

The release PR uses artifact-only CI. Optional local `release-preflight.sh`
checks the same immutable candidate and exact bytes without source tests.
A successful maintainer Unraid test is never inferred from CI or a source merge.
Migration snapshots protect data; they are not an automatic plugin downgrade.

## GitHub Releases

After a stable release PR is merged, the main `CI` workflow's **Publish GitHub
release** job waits for `CI result`, including artifact verification and the
dependency audit. Only a push to main with an artifact-only delta reaches the
`release-publish` environment; PR runs never receive its token. The protected
lightweight tag `v<version>` points to the release PR's exact merge commit.

The publisher explicitly requires successful `plan` and `CI result` jobs and a
non-cancelled run (#696). Its `!cancelled()` status condition overrides GitHub's
implicit `success()` gate, which otherwise propagates the intentionally skipped
source checks through the dependency chain and skips publication even after a
successful artifact-only CI. Artifact checks and the dependency audit remain
mandatory through `CI result`; PRs, manual CI dispatches and source-only pushes
cannot reach the publisher.

Changes to this gate are checked with focused condition regressions, workflow
validation and PR CI. Automatic publication can only be verified live after the
fix is merged to main, on the next approved stable release merge. A manual retry
verifies publication but does not exercise the automatic job's condition.

The release description is the tested current-version changelog, including its
contributor credits. Four assets are published:

- `borg-backup-ui-<version>.txz`: the byte-identical tested package.
- `borg-backup-ui.plg`: the original stable manifest from the release commit.
- `provenance.json`: the package's embedded source/build/note provenance.
- `SHA256SUMS`: checksums for those three assets.

The Unraid update and package URLs remain on main. The attached manifest keeps
those URLs; it is historical release metadata, not a separate pinned update
channel. GitHub assets retain old packages independently of the five-package
retention on main. GitHub also provides its usual source archives for the tag.

Publishing first creates the tag and a draft, uploads missing files, downloads
and verifies their bytes/ownership, then makes the completed draft public. Each
write verifies the actual `borg-codex-bot` identity. A retry with identical data
is safe, including after a successful publication; conflicting tags, metadata,
unexpected assets or different bytes fail without overwriting or deleting them.
An incomplete GitHub upload left in `starter` state also fails for maintainer
inspection rather than deleting files automatically.

Use **Publish GitHub release** on main to retry an interrupted publication or
backfill `2026.11.02.1337` after this workflow is merged. It resolves the already
merged bot-owned `codex/release-<version>` PR, verifies the artifact/audit jobs in
the latest main CI attempt for that exact commit, and revalidates the package,
immutable test candidate, source and tested notes. The full source suite is not
repeated. A failed publishing job can be retried when all prerequisite jobs
passed; failed prerequisite jobs or missing historical CI evidence block it.
Backfill relies on that release's original audit, not a new dependency scan.

Historical commits are read as data by the reviewed current main controller;
their scripts are never executed. Main may advance during this metadata-only
operation as long as both commits remain on main history. An older backfill does
not replace a newer published stable version as `Latest`. Automatic/manual
publishers share a concurrency group; active publication is not canceled by a
new main push. Pending requests can still be superseded; retry a missed version
manually. Ordinary source CI continues to reuse only matching full-tree proofs.

## One-time GitHub setup (maintainer)

Configure these settings yourself; the implementation does not change repository
settings or credentials. Set them before the first publication run.

1. **Settings > Environments:** create `testing` and `stable`. For both, choose
   **Selected branches and tags** and allow a **branch** named exactly `main`.
   Do not allow PR refs, other branches, or tags. Testing needs no required
   reviewer. For stable, add the maintainer as **Required reviewer**; leave
   **Prevent self-review** off if the same sole maintainer starts and approves
   runs. Disable administrator bypass of protection rules where available.
2. In **each environment**, add secret **`BBUI_BOT_TOKEN`** belonging to
   `borg-codex-bot`, restricted to `borgforge/borg-backup-ui`. Fine-grained
   permissions: **Contents: Read and write**, **Actions: Read and write**,
   **Pull requests: Read and write**, plus implicit **Metadata: Read**. The
   bot needs repository write access and organization approval if required.
   These workflows do not edit workflow files. **Workflows: Read and write**
   is needed by the development bot when pushing workflow changes, and by the
   `release-publish` token when GitHub requires it for a historical release
   target whose workflow files differ from current main. The same development
   bot token can be used in the environment; no new bot account is needed.
   Do not store this publishing token as a repository-wide Actions secret.
3. **Settings > Rules > Rulesets > Protect main:** retain PR/review,
   conversation resolution, no deletion and no force push. After this PR has
   produced the new check once, require **`CI result`** from GitHub Actions and
   enable **Require branches to be up to date before merging**. Do not require
   conditional `checks / tests` or `checks / quality`: reuse/artifact PRs
   intentionally skip them. `CI result` includes the mandatory audit.
4. Add an active **tag ruleset** matching **`test-candidates/*`** with
   **Restrict updates** and **Restrict deletions**. Allow initial tag creation;
   do not give the bot an update/delete bypass. Keep `test-channel` outside the
   main ruleset; its exact snapshot replacement must remain possible.
5. **Settings > Actions > General:** allow the pinned official `actions/*`
   actions. Keep the default workflow token **read-only**. The repository
   checkbox allowing `GITHUB_TOKEN` to create PRs is unnecessary: PR creation
   uses the separately verified bot token. Retain artifacts for at least 90 days
   if the organization permits it; shorter retention safely reduces reuse.
6. Create **`release-publish`** with only branch **`main`** allowed, no wait timer
   and no required reviewer. Add **`BBUI_BOT_TOKEN`** for `borg-codex-bot`, as in
   the other environments. Stable preparation already has its explicit test
   confirmation/environment approval, followed by the maintainer's release PR
   merge; metadata publication needs no second approval. No Secrets administration
   permission is needed for the bot to consume an environment secret.
7. Add active tag ruleset **Protect stable release tags**, matching **`v*`**.
   Enable **Restrict updates**, **Restrict deletions** and **Block force pushes**;
   leave **Restrict creations** off and the bypass list empty. New release tags
   remain creatable while published tags cannot be moved or deleted by the bot.

Environment protection must exist before adding the token. The publisher and
stable jobs check out only reviewed main code; candidate compilation runs in a
separate job without bot secrets. Do not replace this separation with
`pull_request_target`, `workflow_run` privileged execution, inherited secrets or
checking out candidate code in a job holding the bot token.

GitHub Releases are the additional publication step described above. The guarded
main-push job in `ci.yml` cannot run for a pull request, source-only push or failed
prerequisite job. The separate scheduled Apprise monitor also uses a main-only
protected bot credential, restricted to issue maintenance as documented above.

GitHub may retain only the latest pending run in a concurrency group; active
publishing runs are not canceled. Check the Actions page after several requests
and resubmit any superseded pending request. Main movement during environment
approval requires a new run, rather than approving a stale source accidentally.

## Initial activation and troubleshooting

The new manual workflows can publish only after this change is reviewed/merged
into main and the environments/secrets are configured. For this internal
pipeline change, focused tests, workflow validation and PR CI are the pre-merge
verification; a live channel test is an explicit post-merge activation check.
Do not bypass this boundary by publishing locally. Older candidates created
before immutable tags were introduced remain installed/available on the old
feed, but need a new hosted candidate before using the new stable workflow.

After setup, dispatch testing for current main with a fresh version; verify its
summary, install on the test Unraid system and exercise backup/restore, API/UI
and notifications. Only then use the stable workflow with explicit approval.
PR #676 updated Apprise and resolved the dependency findings tracked in #672.
Publication still requires a passing audit against current advisory data.

- **Missing/expired CI evidence:** request testing, or run CI on main with the
  selected exact SHA. The resolver starts at most one CI and waits up to 45 min.
- **Failed CI:** fix the change or use **Re-run all jobs**, then retry testing.
  Evidence belongs to a complete run attempt; mixing successful jobs across
  partial reruns is not a reusable proof.
- **PR mergeability pending:** GitHub is still calculating; retry resolution.
- **Version conflict/source moved/main changed:** use a new version/run from the
  current integration. Do not edit a candidate tag or rewrite a proof.
- **Stable source/notes mismatch:** merge the tested source or build/test a new
  candidate for the final source. Do not rebuild during promotion.
- **Wrong/missing bot identity:** correct the environment secret/permissions;
  no fallback to the maintainer account is permitted.
- **GitHub Release missing after merge:** inspect **Publish GitHub release** in
  the main CI run. Fix environment/token problems, then dispatch the dedicated
  workflow with the same version. Do not rebuild or advance the stable version
  to repair publication metadata. Conflicting tags/assets require investigation;
  no automatic clobber/delete or force-push is allowed.

Reference: [GitHub environment protection](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[artifact metadata](https://docs.github.com/en/rest/actions/artifacts).
GitHub Release APIs: [releases](https://docs.github.com/en/rest/releases/releases),
[release assets](https://docs.github.com/en/rest/releases/assets).
The [#671 audit](../development/ci-cd-audit.md) is historical evidence;
[this document](release-workflow.md) defines the current workflow.
