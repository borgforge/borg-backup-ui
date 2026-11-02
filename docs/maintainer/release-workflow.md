# GitHub CI and release workflow

This is the normal public workflow (#677). GitHub runs the authoritative full
checks, builds test candidates, publishes the testing feed and prepares stable
release PRs. Local development uses focused tests. Confidential advisories keep
[their separate private workflow](security-release-workflow.md), including local
private preflight, private candidates and explicit disclosure approval.

## Daily operation

| Action | Maintainer input | Automatic work |
| --- | --- | --- |
| Develop | Push an issue branch and open/update its PR | CI checks the PR integration commit against main: static checks, full tests, dependency audit. A branch push without a PR does not start a second full run. |
| Test on Unraid | Actions > **Publish testing candidate** > Run workflow; branch **main**, version `YYYY.MM.DD.HHMM`, optional PR number, target `unraid-legacy` | Resolve current main or the PR merge commit; wait for/reuse matching CI, request CI if absent; audit current dependencies; build once; verify; publish testing feed and pin candidate. |
| Merge code | Review and merge the source PR | Main CI reuses full checks only for the identical complete Git tree and CI policy. Otherwise full checks run for the changed integration. Dependency audit runs again. |
| Prepare stable | After successful Unraid testing and source merge: Actions > **Prepare stable release PR** > Run workflow; branch **main**, tested version, check confirmation; approve environment `stable` | Verify main CI, fresh dependency audit, candidate/source/notes/checksums; copy tested bytes into a separate release PR. No rebuild or repeated source suite. |
| Release | Review and merge the release PR | Artifact-only CI and audit verify the release; the existing stable feed on main updates when merged. No automatic merge or GitHub Release is created. |

Testing from a PR always includes current main. Moving main/PR refs during the
run aborts publication; start a new workflow. CI-policy changes must first be
reviewed and merged, then tested through the trusted main workflow. The
`unraid-8` target remains explicitly blocked until SDK/system validation (#549).

A workflow summary reports the version, test URL, selected source, immutable
candidate and package SHA256. A green dispatch request alone is not completion:
wait for the **publish** job and its verification summary before installing.

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
   These workflows do not edit workflow files; **Workflows: Read and write**
   is needed separately by the development bot when pushing workflow changes.
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

Environment protection must exist before adding the token. The publisher and
stable jobs check out only reviewed main code; candidate compilation runs in a
separate job without bot secrets. Do not replace this separation with
`pull_request_target`, `workflow_run` privileged execution, inherited secrets or
checking out candidate code in a job holding the bot token.

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

Reference: [GitHub environment protection](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[artifact metadata](https://docs.github.com/en/rest/actions/artifacts).
The [#671 audit](../development/ci-cd-audit.md) is historical evidence;
[this document](release-workflow.md) defines the current workflow.
