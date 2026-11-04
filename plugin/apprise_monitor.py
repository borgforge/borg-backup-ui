#!/usr/bin/env python3
"""Monitor bundled Apprise using public metadata; never install or update it (#699).

Preview is read-only. Issue writes require the protected main workflow, current
main checkout and verified bot identity. All upstream prose/URLs are untrusted:
only validated versions/identifiers and locally constructed links are rendered.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

from packaging.utils import parse_sdist_filename, parse_wheel_filename
from packaging.version import Version

import ci_evidence as evidence
import ci_release as hosted
import security_workflow as security

ROOT = Path(__file__).resolve().parents[1]
REPO = evidence.REPOSITORY
INDEX = 'https://pypi.org/simple/apprise/'
END = '<!-- bbui-apprise-monitor:end -->'
START = re.compile(r'<!-- bbui-apprise-monitor:((?:release|security):[\w.!+-]+):start -->')
ADVISORY_ID = re.compile(r'(?:PYSEC-\d{4}-\d+|CVE-\d{4}-\d{4,}|GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})')
MAX_RESPONSE = 8 * 1024 * 1024
CHECKLIST = '''

## Maintainer review

- [ ] Review upstream release notes, security impact and Python/Unraid compatibility.
- [ ] Decide whether an update or migration is needed; no automatic update is authorized.
- [ ] Refresh the Apprise lockfile and hashes and verify the bundled providers.
- [ ] Run focused tests and PR CI, then publish and verify a test-channel candidate.
- [ ] Complete maintainer testing and explicit stable approval before a release PR.

Maintainer notes and checked boxes outside the monitor block are preserved.
Use `status::waiting` or close as not planned to defer this finding.
'''


class MonitorFailure(RuntimeError):
    """Report a fixed workflow phase without exposing untrusted exception text."""


def checked(phase, operation, *args):
    """Run one monitor phase; replace failure details with its trusted phase name."""
    try:
        return operation(*args)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, AttributeError):
        raise MonitorFailure(phase) from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Reject metadata redirects instead of following an unreviewed source."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Return no redirect request; urllib reports the HTTP failure."""
        return None


def pypi_json(url: str) -> dict:
    """Read bounded JSON from an allowed PyPI endpoint, without credentials.

    Timeouts, redirects, HTTP errors and malformed responses fail visibly; no
    fallback treats missing metadata as an empty successful result.
    """
    if url != INDEX and not re.fullmatch(r'https://pypi.org/pypi/apprise/[\w.!+%\-]+/json', url):
        raise ValueError('Unexpected PyPI endpoint')
    accept = 'application/vnd.pypi.simple.v1+json' if url == INDEX else 'application/json'
    request = urllib.request.Request(url, headers={'Accept': accept, 'User-Agent': 'borg-backup-ui-apprise-monitor'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('PyPI response exceeds the size limit')
        data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'PyPI request failed with HTTP {exc.code}; check availability/rate limits') from None
    except (OSError, urllib.error.URLError):
        raise RuntimeError('PyPI request failed; check connectivity and TLS') from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError('PyPI returned invalid JSON') from None
    if not isinstance(data, dict):
        raise ValueError('PyPI response must be an object')
    return data


def version(value: str) -> Version:
    """Parse a bounded public PEP 440 version or reject malformed/local versions."""
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError('Invalid version metadata')
    try:
        parsed = Version(value)
    except ValueError:
        raise ValueError('Invalid version metadata') from None
    if parsed.local is not None:
        raise ValueError('Local versions are not upstream releases')
    return parsed


def bundled_version(lockfile: Path) -> Version:
    """Read exactly one stable Apprise pin from the existing build lockfile."""
    pins = re.findall(r'^apprise==([^\s\\]+)\s*(?:\\|$)', lockfile.read_text(), re.MULTILINE)
    if len(pins) != 1:
        raise ValueError('Expected exactly one Apprise pin in the build lockfile')
    parsed = version(pins[0])
    if parsed.is_prerelease or parsed.is_devrelease:
        raise ValueError('Bundled Apprise must be a stable version')
    return parsed


def latest_stable(index: dict) -> Version:
    """Select the newest stable release with at least one non-yanked distribution.

    Uses the Simple JSON index, not the deprecated project-JSON releases field.
    Distribution files are inspected as metadata only and never downloaded.
    """
    if (index.get('name', '').lower() != 'apprise'
            or not re.fullmatch(r'1\.\d+', index.get('meta', {}).get('api-version', ''))
            or not isinstance(index.get('files'), list)):
        raise ValueError('Invalid Apprise index metadata')
    candidates = []
    for item in index['files']:
        if not isinstance(item, dict) or not isinstance(item.get('filename'), str):
            raise ValueError('Invalid distribution metadata')
        filename = item['filename']
        if len(filename) > 250 or '/' in filename or '\\' in filename:
            raise ValueError('Invalid distribution filename')
        try:
            name, parsed, *_ = (parse_wheel_filename(filename) if filename.endswith('.whl')
                                else parse_sdist_filename(filename))
        except ValueError:
            raise ValueError('Unrecognized Apprise distribution filename') from None
        yanked = item.get('yanked', False)
        if name != 'apprise' or type(yanked) not in (bool, str) or parsed.local is not None:
            raise ValueError('Invalid Apprise distribution identity or yanked state')
        # An empty reason string still means the file was yanked.
        if yanked is False and not parsed.is_prerelease and not parsed.is_devrelease:
            candidates.append(parsed)
    if not candidates:
        raise ValueError('No non-yanked stable Apprise release found')
    return max(candidates)


def advisories(metadata: dict, current: Version) -> list[dict]:
    """Validate installed-version advisories and return stable, sorted facts.

    Withdrawn entries are omitted. Prose and supplied links are never rendered;
    a digest detects meaningful changes to the public description without
    copying potentially hostile Markdown into a repository issue.
    """
    info = metadata.get('info', {})
    if (info.get('name', '').lower() != 'apprise' or version(info.get('version')) != current
            or not isinstance(metadata.get('vulnerabilities'), list)):
        raise ValueError('Invalid installed-version security metadata')
    result = {}
    for item in metadata['vulnerabilities']:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not ADVISORY_ID.fullmatch(item['id']):
            raise ValueError('Invalid advisory identity')
        withdrawn = item.get('withdrawn')
        if withdrawn is not None:
            if not isinstance(withdrawn, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT[\d:.+Z-]+', withdrawn):
                raise ValueError('Invalid advisory withdrawal metadata')
            continue
        aliases = item.get('aliases')
        fixed = item.get('fixed_in')
        if (not isinstance(aliases, list) or not isinstance(fixed, list)
                or any(not isinstance(alias, str) or not ADVISORY_ID.fullmatch(alias) for alias in aliases)):
            raise ValueError('Invalid advisory aliases or fixed versions')
        descriptions = [item.get(field, '') for field in ('summary', 'details')]
        descriptions = ['' if text is None else text for text in descriptions]
        if any(not isinstance(text, str) for text in descriptions):
            raise ValueError('Invalid advisory description')
        descriptions = [' '.join(text.split()) for text in descriptions]
        digest = hashlib.sha256(json.dumps(descriptions, ensure_ascii=True).encode()).hexdigest()
        advisory = {'id': item['id'], 'aliases': sorted(set(aliases)),
                    'fixed_in': [str(v) for v in sorted({version(v) for v in fixed})], 'digest': digest}
        if item['id'] in result and result[item['id']] != advisory:
            raise ValueError('Conflicting duplicate advisory')
        result[item['id']] = advisory
    # PYSEC/GHSA records can describe the same vulnerability. Merge connected
    # alias sets so one disclosure does not create several independent tasks.
    groups = []
    for entry in result.values():
        identifiers = {entry['id'], *entry['aliases']}
        related = [group for group in groups if group[0] & identifiers]
        entries = [entry]
        for group in related:
            identifiers |= group[0]
            entries.extend(group[1])
            groups.remove(group)
        groups.append((identifiers, entries))
    merged = []
    for identifiers, entries in groups:
        primary = min(entry['id'] for entry in entries)
        digests = sorted({entry['digest'] for entry in entries})
        merged.append({'id': primary, 'aliases': sorted(identifiers - {primary}),
                       'fixed_in': [str(v) for v in sorted({Version(v) for entry in entries for v in entry['fixed_in']})],
                       'digest': hashlib.sha256(json.dumps(digests).encode()).hexdigest()})
    return sorted(merged, key=lambda item: item['id'])


def findings(current: Version, latest: Version, security_findings: list[dict]) -> list[dict]:
    """Render deterministic release/security findings from validated facts only."""
    common = (f'Bundled Apprise: **{current}** (`plugin/apprise-requirements.lock`).\n\n'
              f'[Bundled version metadata](https://pypi.org/project/apprise/{current}/) | '
              '[Upstream release notes](https://github.com/caronc/apprise/releases)\n\n')
    labels = ['impact::internal', 'release-note::no', 'area::workflow']
    result = []
    if latest > current:
        result.append({'key': f'release:{latest}', 'title': f'Review Apprise {latest} update',
                       'labels': ['type::maintenance', *labels],
                       'text': common + f'New stable version: **{latest}**.\n\n'
                       f'[Available release](https://pypi.org/project/apprise/{latest}/)\n\n'
                       'Priority: routine compatibility/update review. A release is not proof that a migration is required.\n'
                       'Security findings for the bundled version are tracked separately by advisory identity.'})
    for item in security_findings:
        identifier = item['id']
        result.append({'key': f'security:{identifier}', 'title': f'Review Apprise security advisory {identifier}',
                       'identifiers': [identifier, *item['aliases']],
                       'labels': ['type::security', *labels],
                       'text': common + 'Priority: security triage required; assess severity and exposure from the advisory.\n\n'
                       f'[Public advisory {identifier}](https://osv.dev/vulnerability/{identifier})\n\n'
                       f'Aliases: {", ".join(item["aliases"]) or "none reported"}.\n\n'
                       f'Reported fixed versions: {", ".join(item["fixed_in"]) or "none reported"}.\n\n'
                       'Fixed versions require independent availability and compatibility review.\n'
                       f'<!-- public-description-sha256:{item["digest"]} -->'})
    return result


def existing_issues() -> list[dict]:
    """Read all bot-authored issues, including closed/unlabelled ones; cap at 2,000."""
    result = []
    for page in range(1, 21):
        batch = evidence.api(f'repos/{REPO}/issues?state=all&creator={hosted.BOT}&per_page=100&page={page}')
        if not isinstance(batch, list):
            raise ValueError('Invalid GitHub issue collection')
        result.extend(item for item in batch if 'pull_request' not in item)
        if len(batch) < 100:
            return result
    raise RuntimeError('Issue history exceeds 2,000 entries; extend the bounded monitor scan')


def plan_updates(detected: list[dict], issues: list[dict]) -> tuple[list[dict], int]:
    """Plan idempotent writes, preserving maintainer text and deliberate deferral.

    Closed release issues, status::waiting and not-planned issues are left alone.
    Changed security facts may reopen a completed security issue while the
    bundled version is still affected. Invalid/duplicate markers fail closed.
    """
    known = {}
    for issue in issues:
        body = issue.get('body') or ''
        matches = list(START.finditer(body))
        if not matches:
            if '<!-- bbui-apprise-monitor:' in body:
                raise ValueError('Damaged monitor issue marker requires maintainer reconciliation')
            continue
        if (len(matches) != 1 or body.count(END) != 1 or body.index(END) < matches[0].end()
                or issue['user']['login'] != hosted.BOT or issue['state'] not in ('open', 'closed')
                or type(issue['number']) is not int or issue['number'] <= 0):
            raise ValueError('Invalid monitor issue identity or managed block')
        key = matches[0][1]
        if key in known:
            raise ValueError('Duplicate monitor issues require maintainer reconciliation')
        known[key] = issue
    actions, deferred = [], 0
    for finding in detected:
        key = finding['key']
        if key.startswith('security:'):
            matches = [f'security:{identifier}' for identifier in finding['identifiers']
                       if f'security:{identifier}' in known]
            if len(matches) > 1:
                raise ValueError('Overlapping advisory issues require maintainer reconciliation')
            if matches:
                key = matches[0]
        block = f'<!-- bbui-apprise-monitor:{key}:start -->\n{finding["text"]}\n{END}'
        issue = known.get(key)
        if issue is None:
            actions.append({'method': 'POST', 'endpoint': f'repos/{REPO}/issues',
                            'payload': {'title': finding['title'], 'body': block + CHECKLIST,
                                        'labels': finding['labels']}})
            continue
        if ('status::waiting' in {label['name'] for label in issue['labels']}
                or issue.get('state_reason') == 'not_planned'
                or (issue['state'] == 'closed' and key.startswith('release:'))):
            deferred += 1
            continue
        body = issue['body']
        start = START.search(body).start()
        end = body.index(END) + len(END)
        updated = body[:start] + block + body[end:]
        if updated != body:
            payload = {'body': updated}
            if issue['state'] == 'closed':
                payload['state'] = 'open'
            actions.append({'method': 'PATCH', 'endpoint': f'repos/{REPO}/issues/{issue["number"]}',
                            'payload': payload,
                            'expected': {field: issue.get(field) for field in ('body', 'state', 'state_reason', 'labels')}})
    return actions, deferred


def require_main_job() -> None:
    """Reject local, stale, PR and other-repository jobs before any issue write."""
    security.guard_public(ROOT)
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_REPOSITORY') != REPO
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') not in ('schedule', 'workflow_dispatch')
            or os.environ.get('GITHUB_WORKFLOW_REF') != f'{REPO}/.github/workflows/apprise-monitor.yml@refs/heads/main'
            or os.environ.get('BBUI_ENVIRONMENT') != 'dependency-monitor'):
        raise RuntimeError('Issue writes require the protected main dependency-monitor workflow')
    sha = evidence.exact_sha(os.environ.get('GITHUB_SHA', ''))
    if (hosted.git(ROOT, 'rev-parse', 'HEAD') != sha
            or evidence.api(f'repos/{REPO}/git/ref/heads/main')['object']['sha'] != sha):
        raise RuntimeError('Main changed or checkout is stale; rerun the monitor on current main')


def write_issue(action: dict) -> None:
    """Write one planned issue as the verified bot, then verify its persisted author.

    Payloads go through stdin, not shell arguments. Failures never print tokens,
    upstream bodies or raw API errors; an interrupted creation is found on retry.
    """
    require_main_job()
    if action['method'] == 'PATCH':
        current = evidence.api(action['endpoint'])
        if (current['user']['login'] != hosted.BOT
                or any(current.get(field) != value for field, value in action['expected'].items())):
            raise RuntimeError('Issue changed since planning; rerun without overwriting maintainer edits')
    hosted.bot()
    response = subprocess.run(['gh', 'api', '--method', action['method'], action['endpoint'], '--input', '-'],
                              input=json.dumps(action['payload']), capture_output=True, text=True)
    if response.returncode:
        raise RuntimeError('Issue write failed; check bot Issues permission, rate limits and connectivity')
    try:
        number = json.loads(response.stdout)['number']
        if type(number) is not int or number <= 0:
            raise ValueError('Invalid issue number')
        saved = evidence.api(f'repos/{REPO}/issues/{number}')
        if saved['user']['login'] != hosted.BOT:
            raise ValueError('Unexpected issue author')
    except (ValueError, KeyError, TypeError):
        raise RuntimeError('Issue author verification failed') from None


def run(apply: bool = False) -> dict:
    """Collect all metadata and history before planning/writing; return safe counts.

    Preview performs no writes. Apply requires a current protected main job even
    when no updates exist, so missing/wrong bot credentials cannot look healthy.
    """
    if apply:
        checked('protected main job', require_main_job)
        checked('bot identity', hosted.bot)
    current = checked('bundled version pin', bundled_version, ROOT / 'plugin/apprise-requirements.lock')
    latest = checked('PyPI release index validation', latest_stable, checked('PyPI release index request', pypi_json, INDEX))
    url = f'https://pypi.org/pypi/apprise/{urllib.parse.quote(str(current), safe="")}/json'
    entries = checked('PyPI security metadata validation', advisories,
                      checked('PyPI security metadata request', pypi_json, url), current)
    detected = findings(current, latest, entries)
    actions, deferred = checked('issue reconciliation', plan_updates, detected,
                                checked('GitHub issue history', existing_issues))
    if apply:
        for action in actions:
            checked('protected issue write and author verification', write_issue, action)
    return {'mode': 'apply' if apply else 'preview', 'bundled': str(current), 'latest_stable': str(latest),
            'findings': len(detected), 'deferred_or_closed': deferred,
            'creates': sum(action['method'] == 'POST' for action in actions),
            'updates': sum(action['method'] == 'PATCH' for action in actions)}


def main() -> int:
    """Run preview or protected apply, reporting failures without upstream text."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Write issues only in the protected main workflow')
    args = parser.parse_args()
    try:
        result = run(args.apply)
    except MonitorFailure as exc:
        print(f'Apprise monitor failed during {exc}; no all-clear result. '
              'Check source availability/schema, bot access and current main; see maintainer documentation.', file=sys.stderr)
        return 1
    text = json.dumps(result, sort_keys=True)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
            handle.write('Apprise monitor completed: `' + text + '`\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
