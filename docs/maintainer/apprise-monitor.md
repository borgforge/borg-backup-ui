# Apprise release monitor

Issue #699 adds the **Monitor Apprise releases** workflow. It checks the Apprise
version pinned in `plugin/apprise-requirements.lock` daily at **06:41 UTC**, or
when manually dispatched on main. GitHub schedules can be delayed; this is not
a real-time security alert service. The private Python runtime is outside this
monitor's scope and remains part of #548.

## Sources and scope

- The [PyPI Simple JSON index](https://docs.pypi.org/api/index-api/) supplies
  distribution filenames and withdrawal flags. The monitor uses PEP 440 version
  ordering and selects the newest stable version with at least one non-yanked
  file. Prereleases, development releases and fully yanked releases are excluded;
  an empty withdrawal reason still means the file is yanked. It uses no deprecated
  project-JSON release list and does not download or execute distributions.
- The [installed-version PyPI JSON endpoint](https://docs.pypi.org/api/json/)
  supplies public advisories for the exact bundled Apprise version, including
  aliases, reported fixed versions and withdrawals. Withdrawn advisories are
  omitted. Missing/malformed data fails the run instead of meaning no findings.
- Findings link to PyPI, the official Apprise release notes and OSV advisories.
  Upstream descriptions and arbitrary URLs are not copied into issue Markdown.
  A normalized-description digest detects changes to advisory prose safely.
- This does not claim complete vulnerability coverage. The existing
  `Dependency security` workflow remains unchanged and continues auditing
  Apprise and its locked transitive dependencies during CI/releases and weekly.
  This monitor does not scan native libraries or a Python interpreter.

Only metadata and issues are read or written. The monitor never updates the
lockfile, builds a package, changes installed plugins, creates release PRs or
grants release approval. A new upstream version is a review task, not proof that
a migration is required.

## Maintainer setup and activation

The implementation must first be reviewed and merged to main. Maintainers
configure GitHub settings themselves; the controller does not modify them.

1. Create environment **`dependency-monitor`**. Under deployment branch/tag
   rules allow only the **branch** named exactly **`main`**, not tags or PR refs.
   Do this before adding the credential. Daily monitoring needs no reviewer or
   wait timer; requiring one will make each run wait for manual approval.
2. Add environment secret **`BBUI_BOT_TOKEN`** for **`borg-codex-bot`**, scoped to
   `borgforge/borg-backup-ui`. Required fine-grained permissions are **Contents:
   Read** and **Issues: Read and write**, plus implicit Metadata read. The bot
   must have repository access and any required organization approval. No
   Contents write, Actions write, PR write or repository administration is needed.
   Do not add this credential as an unprotected repository-wide secret.
3. Keep the workflow's default `GITHUB_TOKEN` read-only. Only the monitor step
   receives the bot token. The workflow permits schedule/manual events on main;
   the controller also checks repository, workflow, environment, checkout SHA
   and current main before writes. Each mutation verifies `gh api user` and the
   saved issue author. Local `--apply` and PR execution are rejected.
4. Manually run **Monitor Apprise releases** on **main** after setup. Inspect the
   successful job and its summary; dispatch success alone is not verification.
5. Run it again against unchanged inputs. Expect zero creates/updates. Record
   both run URLs and summaries in #699, and link any created findings. If there
   is no newer version or public advisory, record the no-change result; synthetic
   issue-creation cases remain covered by automated tests. Keep #699 open until
   activation and this live check are recorded.

No plugin test-channel/stable version is required for this internal monitor.
PR CI validates code, tests and workflow policy before merge; the main-only
issue writer can only be verified live after merge and maintainer setup.

## Issue lifecycle

- The newest eligible upstream version gets one release finding identified by
  `release:<version>`. Older intermediate versions are not opened in bulk.
- Each public advisory affecting the bundled version gets a separate security
  finding identified by the upstream PyPI advisory ID (`security:<id>`). Records
  connected by shared aliases are grouped; an existing matching ID is retained
  when upstream adds or changes its primary identifier. Aliases do not create
  additional issues. This prevents a closed release
  task from hiding a newly disclosed advisory. Release findings request routine
  review; security findings request security triage without guessing severity.
- The scan includes open and closed bot-authored issues, including ones whose
  labels were removed. Hidden `bbui-apprise-monitor` markers identify findings.
  Do not remove or copy these markers. Duplicate or damaged markers fail the run
  for maintainer reconciliation rather than silently creating more issues.
- Only the marked block is refreshed when facts change. Checked tasks, custom
  titles, labels and notes outside the block are preserved. No timestamps or
  daily comments are added, so unchanged runs produce no writes.
  Before updating, the monitor rereads the issue and aborts if its body, state
  or labels changed since planning. This narrows the concurrent-edit window;
  GitHub's issue API does not provide an atomic compare-and-swap for this edit.
- Add **`status::waiting`**, or close with reason **not planned**, to defer a
  finding. The monitor leaves it alone, even when security facts change; the
  maintainer owns reassessment while it is deferred. Remove the label and reopen
  it to resume updates. The independent vulnerability audit is not suppressed.
- Completed release issues are never recreated/reopened for the same version.
  A completed security issue is reopened only if it still affects the bundled
  version and its public facts change (fixed versions, aliases, description or
  affected bundled version). An unchanged completed advisory remains closed.
- A later version/advisory is a separate finding. Findings are not automatically
  closed when the lockfile advances, a release is yanked or an advisory is
  withdrawn; the maintainer checks resolution and closes them.

## Preview and troubleshooting

With the hash-pinned parser from `.github/requirements-monitor.lock` installed
in a repository-local environment, run:

```bash
python plugin/apprise_monitor.py
```

This reads live metadata and GitHub issue history and reports planned counts
without writing issues. GitHub CLI read authentication is required. It is not a
substitute for the protected live apply check.

The summary records bundled/latest versions, finding count, deferred/closed
count and creates/updates. Errors report the failed phase and return nonzero:

- PyPI requests: check service availability, rate limits, TLS and redirects.
  Reads time out after 30 seconds and are limited to 8 MiB; redirects are refused.
- Metadata validation: inspect source schema/version changes. Do not replace
  failures with an empty result or automatically trust new upstream formats.
- Bot identity/protected job: check environment setup, token validity, main-only
  routing and current main. A main change requires a new run.
- Issue history/reconciliation: check API access/rate limits and marker conflicts.
  The scan fails beyond 2,000 bot-authored issue/PR records rather than ignoring
  old closed findings. Extend the bounded scan through a reviewed change if needed.
- Issue write/author verification: check Issues write permission and connectivity.
  A prior write may have succeeded before a later error; retrying finds persisted
  issues and applies only missing changes. Never retry using a maintainer account.

Workflow failures must be monitored in Actions; enable GitHub's workflow-failure
notifications for the maintainer account as appropriate. Do not interpret a
missing/failed scheduled run as confirmation that dependencies are current.
