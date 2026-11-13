"""Correlate supplier metadata with open runtime CVEs and notify once (#720).

Supplier archives are hashed and read as data, never installed or executed.
Notifications identify version-based fix candidates, not release approval.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from packaging.version import Version, InvalidVersion

import apprise_monitor as shared
import python_runtime as runtime

SUPPLIER = 'astral-sh/python-build-standalone'
RECIPIENT = 'TheTwist76'
ISSUE_MARKER = re.compile(r'<!-- bbui-python-monitor:security:(CVE-\d{4}-\d{4,}):start -->')
NOTICE_MARKER = re.compile(r'<!-- bbui-python-fix:v1:([0-9a-f]{64}) -->')
MAX_ARCHIVE = 512 * 1024 * 1024


class AssetRedirect(urllib.request.HTTPRedirectHandler):
    """Allow only HTTPS GitHub release-asset redirects, without credentials."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Reject non-asset destinations before urllib creates the next request."""
        parsed = urllib.parse.urlsplit(newurl)
        if (parsed.scheme != 'https' or parsed.hostname not in
                ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com')
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise ValueError('Unexpected supplier asset redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def asset_identity(asset: dict, name: str) -> str:
    """Require the exact published asset name, bounded size and GitHub digest."""
    digest = asset.get('digest', '')
    if (asset['name'] != name or asset.get('state') != 'uploaded'
            or type(asset['size']) is not int or not 0 < asset['size'] <= MAX_ARCHIVE
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest)):
        raise ValueError('Incomplete supplier asset evidence')
    return digest.removeprefix('sha256:')


def download_asset(tag: str, asset: dict, destination: Path) -> str:
    """Download an exact allowlisted asset, bounding bytes and verifying SHA256."""
    name = asset['name']
    expected = asset_identity(asset, name)
    if (not re.fullmatch(r'\d{8}', tag) or not re.fullmatch(
            r'cpython-3\.\d+\.\d+\+\d{8}-x86_64-unknown-linux-gnu-pgo\+lto-full.tar.zst', name)):
        raise ValueError('Unexpected supplier archive')
    url = f'https://github.com/{SUPPLIER}/releases/download/{tag}/' + urllib.parse.quote(name, safe='')
    digest = hashlib.sha256()
    size = 0
    request = urllib.request.Request(url, headers={'User-Agent': 'borg-backup-ui-python-monitor'})
    with urllib.request.build_opener(AssetRedirect).open(request, timeout=60) as response, destination.open('wb') as out:
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > asset['size']:
                raise ValueError('Supplier archive exceeds declared size')
            digest.update(block)
            out.write(block)
    if size != asset['size'] or digest.hexdigest() != expected:
        raise ValueError('Supplier archive checksum/size mismatch')
    return expected


class MetadataReader:
    """Bound decompressed bytes consumed while looking for PYTHON.json."""

    def __init__(self, stream):
        """Wrap the zstd pipe with a 64 MiB scan budget; never extract files."""
        self.stream = stream
        self.remaining = 64 * 1024 * 1024

    def read(self, size):
        """Read at most the remaining budget, failing on oversized metadata scans."""
        if size < 0 or size > self.remaining:
            raise ValueError('Supplier metadata scan exceeds limit')
        block = self.stream.read(size)
        self.remaining -= len(block)
        return block


def archive_metadata(path: Path) -> dict:
    """Read one bounded regular PYTHON.json from a verified zstd tar, without execution."""
    process = subprocess.Popen(['zstd', '--decompress', '--stdout', '--memory=128MB', str(path)],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        with tarfile.open(fileobj=MetadataReader(process.stdout), mode='r|') as archive:
            for member in archive:
                if member.name == 'python/PYTHON.json':
                    if not member.isfile() or not 0 < member.size <= 4 * 1024 * 1024:
                        raise ValueError('Invalid supplier Python metadata member')
                    return json.load(archive.extractfile(member))
        raise ValueError('Supplier archive lacks Python metadata')
    except tarfile.TarError:
        raise ValueError('Malformed supplier archive metadata') from None
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def supplier_commit(tag: str) -> str:
    """Resolve a release tag to an immutable source commit, including annotated tags."""
    if not re.fullmatch(r'\d{8}', tag):
        raise ValueError('Invalid supplier tag')
    obj = shared.evidence.api(f'repos/{SUPPLIER}/git/ref/tags/{tag}')['object']
    for _ in range(4):
        if not re.fullmatch(r'[0-9a-f]{40}', obj['sha']):
            raise ValueError('Invalid supplier source SHA')
        if obj['type'] == 'commit':
            return obj['sha']
        if obj['type'] != 'tag':
            break
        obj = shared.evidence.api(f'repos/{SUPPLIER}/git/tags/{obj["sha"]}')['object']
    raise ValueError('Unresolved supplier source tag')


def candidate_inventory(lock: dict, supplier: dict, version: str, root: Path) -> dict:
    """Read exact build links and commit-pinned source versions for a compatible candidate.

    Both full and stripped assets must exist with SHA256 identities. No candidate
    binary is run; installation and native execution remain update/build checks.
    """
    if (lock['supplier'] != SUPPLIER or lock['target'] != 'x86_64-unknown-linux-gnu'
            or not re.fullmatch(r'3\.\d+\.\d+', version)
            or Version(version).release[:2] != Version(lock['version']).release[:2]):
        raise ValueError('Unsupported candidate platform/series')
    tag = supplier['tag_name']
    if not re.fullmatch(r'\d{8}', tag) or supplier['draft'] or supplier['prerelease']:
        raise ValueError('Invalid supplier release')
    prefix = f'cpython-{version}+{tag}-{lock["target"]}'
    assets = {}
    for suffix in ('-pgo+lto-full.tar.zst', '-install_only_stripped.tar.gz'):
        name = prefix + suffix
        matches = [asset for asset in supplier['assets'] if asset['name'] == name]
        if len(matches) != 1:
            raise ValueError('Missing or duplicate candidate asset')
        asset_identity(matches[0], name)
        assets[suffix] = matches[0]
    commit = supplier_commit(tag)
    url = f'https://raw.githubusercontent.com/{SUPPLIER}/{commit}/pythonbuild/downloads.json'
    request = urllib.request.Request(url, headers={'User-Agent': 'borg-backup-ui-python-monitor'})
    with urllib.request.build_opener(shared.NoRedirect).open(request, timeout=60) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('Supplier source inventory exceeds limit')
    scratch = root / '.release-tmp'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='python-fix-', dir=scratch) as folder:
        archive = Path(folder) / 'supplier.tar.zst'
        digest = download_asset(tag, assets['-pgo+lto-full.tar.zst'], archive)
        metadata = archive_metadata(archive)
    if metadata.get('build_options') != 'pgo+lto':
        raise ValueError('Unexpected candidate build options')
    candidate = {key: lock[key] for key in ('supplier', 'target', 'glibc_minimum', 'excluded_extensions')}
    candidate.update(version=version, build=tag)
    candidate['components'] = runtime.inventory(metadata, json.loads(raw), candidate)
    for name, component in candidate['components'].items():
        if not re.fullmatch(r'[0-9A-Za-z.+_-]{1,80}', component['version']):
            raise ValueError('Invalid candidate component version')
        if name != 'cpython' and not re.fullmatch(r'[0-9a-f]{64}', component['source_sha256']):
            raise ValueError('Missing candidate source digest')
    candidate['evidence'] = {'source_commit': commit, 'archive_sha256': digest,
                             'downloads_sha256': hashlib.sha256(raw).hexdigest(),
                             'install_sha256': asset_identity(assets['-install_only_stripped.tar.gz'],
                                                              prefix + '-install_only_stripped.tar.gz')}
    return candidate


def security_issues(issues: list[dict]) -> list[tuple[str, dict]]:
    """Return validated bot CVE issues, including closed ones for notification history."""
    # Reuse the existing strict identity/marker/duplicate validation.
    shared.plan_updates([], issues, namespace='python')
    return [(match[1], issue) for issue in issues
            if (match := ISSUE_MARKER.search(issue.get('body') or ''))]


def eligible(issue: dict) -> bool:
    """Respect explicit closure and waiting deferrals when proposing a notification."""
    return (issue['state'] == 'open' and issue.get('state_reason') != 'not_planned'
            and 'status::waiting' not in {label['name'] for label in issue['labels']})


def fixed_components(cve: dict, lock: dict, candidate: dict, engine) -> list[dict]:
    """Require explicit affected upper bounds crossed by newer component versions.

    Absence from search results, exact-version-only CPEs, unanalysed records,
    negation, component removal and keyword hits never prove a fix. Return no
    candidate if any affected component remains vulnerable or ambiguous.
    """
    if cve.get('vulnStatus') not in ('Analyzed', 'Modified') or not cve.get('configurations'):
        return []
    # Newly introduced candidate components must not retain the same CVE.
    for name, component in candidate['components'].items():
        product = engine.PRODUCTS[name]
        if product is None or name == 'libedit':
            if engine.keyword_mentions_component(cve, name):
                return []
        if product and any(engine.vulnerable_matches(config, product, component['version'])
                           for config in cve['configurations']):
            return []
    fixes = []
    for name, component in sorted(lock['components'].items()):
        product = engine.PRODUCTS[name]
        if product is None:
            if engine.keyword_mentions_component(cve, name):
                return []
            continue
        before = component['version']
        matches = [match for config in cve['configurations']
                   for match in engine.vulnerable_matches(config, product, before)]
        if not matches:
            if name == 'libedit' and engine.keyword_mentions_component(cve, name):
                return []
            continue
        after = candidate['components'].get(name, {}).get('version')
        if not after:
            return []
        try:
            if Version(after) <= Version(before):
                return []
            if any(engine.vulnerable_matches(config, product, after) for config in cve['configurations']):
                return []
            bounds = []
            for match in matches:
                key = ('versionEndExcluding' if 'versionEndExcluding' in match else 'versionEndIncluding')
                bound = match.get(key)
                if not bound or not re.fullmatch(r'[0-9A-Za-z.+_-]{1,80}', bound):
                    return []
                if (Version(after) < Version(bound) if key == 'versionEndExcluding' else Version(after) <= Version(bound)):
                    return []
                bounds.append({'kind': key, 'version': bound})
        except InvalidVersion:
            return []
        fixes.append({'component': name, 'before': before, 'after': after,
                      'bounds': sorted({json.dumps(item, sort_keys=True) for item in bounds})})
    return fixes



def required_floors(versions: list) -> dict[str, str]:
    """Combine stable/planned security floors so an upstream replacement cannot regress either."""
    result = {}
    for _, lock in versions:
        for name, minimum in lock.get('minimum_component_versions', {}).items():
            if name not in result or Version(minimum) > Version(result[name]):
                result[name] = minimum
    return result


def replacement_regressions(candidate: dict, floors: dict[str, str]) -> list[str]:
    """Describe missing, unknown or too-old upstream native versions; never assume parity."""
    result = []
    for name, minimum in sorted(floors.items()):
        actual = candidate['components'].get(name, {}).get('version')
        try:
            valid = actual is not None and Version(actual) >= Version(minimum)
        except InvalidVersion:
            valid = False
        if not valid:
            result.append(f'{name}: candidate {actual or "missing"}, required >= {minimum}')
    return result


def review_replacements(versions: list, supplier: dict, pep: dict, engine, inventory=candidate_inventory) -> dict:
    """Attach a concrete regression check to new supplier-build issues for custom baselines."""
    floors = required_floors(versions)
    if not floors:
        return {}
    reviews = {}
    for _, lock in versions:
        for item in engine.release_findings(lock, pep, supplier, engine.date.today()):
            if not item['key'].startswith('release:build-') or item['key'] in reviews:
                continue
            version = item['key'].split('-')[1]
            candidate = inventory(lock, supplier, version, engine.ROOT)
            problems = replacement_regressions(candidate, floors)
            reviews[item['key']] = ('Replacement blocked by native security floors: ' + '; '.join(problems) + '.'
                                    if problems else 'Candidate meets the committed native security floors; compatibility and release review still required.')
    return reviews


def discover(versions: list, supplier: dict, pep: dict, issues: list, request, engine, inventory=candidate_inventory) -> list[dict]:
    """Compare open CVEs with compatible newer builds; complete all reads before writes."""
    opened = [(identifier, issue) for identifier, issue in security_issues(issues) if eligible(issue)]
    if not opened:
        return []
    candidates, records, fixes = {}, {}, {}
    for scope, lock in versions:
        releases = engine.release_findings(lock, pep, supplier, engine.date.today())
        builds = [item for item in releases if item['key'].startswith('release:build-')]
        if not builds:
            continue
        version = builds[0]['key'].split('-')[1]
        identity = (version, supplier['tag_name'], lock['target'], tuple(lock['excluded_extensions']), lock['glibc_minimum'])
        if identity not in candidates:
            candidates[identity] = inventory(lock, supplier, version, engine.ROOT)
        candidate = candidates[identity]
        if replacement_regressions(candidate, required_floors(versions)):
            continue
        if not set(candidate['components']) <= set(engine.PRODUCTS):
            raise ValueError('Candidate contains an unmonitored native component')
        for identifier, issue in opened:
            if identifier not in records:
                data = request(engine.NVD + '?' + urllib.parse.urlencode({'cveId': identifier}))
                if (data['totalResults'] != 1 or data['startIndex'] != 0
                        or len(data['vulnerabilities']) != 1 or data['vulnerabilities'][0]['cve']['id'] != identifier):
                    raise ValueError('Incomplete CVE fix evidence')
                records[identifier] = data['vulnerabilities'][0]['cve']
            parts = fixed_components(records[identifier], lock, candidate, engine)
            if not parts:
                continue
            # Deduplicate the actionable fix, not dates, text, scope or later builds
            # carrying the same fix. Newly affected baseline versions/bounds differ.
            key = engine.facts_digest({'cve': identifier, 'series': Version(lock['version']).release[:2],
                                      'fixes': [{k: v for k, v in part.items() if k != 'after'} for part in parts]})
            fixes[key] = {'key': key, 'cve': identifier, 'issue': issue['number'], 'parts': parts,
                          'candidate': candidate, 'scope': scope}
    return list(fixes.values())


def comments(number: int) -> list[dict]:
    """Read complete bounded comment history, failing instead of losing deduplication."""
    result = []
    for page in range(1, 21):
        batch = shared.evidence.api(f'repos/{shared.REPO}/issues/{number}/comments?per_page=100&page={page}')
        if not isinstance(batch, list):
            raise ValueError('Invalid notification history')
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise ValueError('Notification history exceeds 2000 comments')


def notification(fixes: list[dict], issues: list[dict], history=comments) -> dict | None:
    """Group unseen fixes into one mention, using bot comments as a durable ledger."""
    if not fixes:
        return None
    known, active = set(), set()
    for _, issue in security_issues(issues):
        if eligible(issue):
            active.add(issue['number'])
        for comment in history(issue['number']):
            if comment['user']['login'] == shared.hosted.BOT:
                known.update(NOTICE_MARKER.findall(comment.get('body') or ''))
    unseen = sorted((fix for fix in fixes if fix['key'] not in known and fix['issue'] in active),
                    key=lambda fix: (fix['issue'], fix['key']))
    if not unseen:
        return None
    lines = [f'@{RECIPIENT} A compatible Python runtime build contains version-based fix candidates '
             'for these open security issues:', '']
    for fix in unseen:
        candidate = fix['candidate']
        build = f'{candidate["version"]}+{candidate["build"]}'
        parts = ', '.join(f'{part["component"]} {part["before"]} -> {part["after"]}' for part in fix['parts'])
        lines += [f'- #{fix["issue"]}: [{fix["cve"]}](https://nvd.nist.gov/vuln/detail/{fix["cve"]}) '
                  f'- {parts}; build [{build}](https://github.com/{SUPPLIER}/releases/tag/{candidate["build"]}).',
                  f'  Full archive SHA256: `{candidate["evidence"]["archive_sha256"]}`; '
                  f'stripped archive SHA256: `{candidate["evidence"]["install_sha256"]}`.',
                  f'  Supplier source commit: `{candidate["evidence"]["source_commit"]}`; '
                  f'source inventory SHA256: `{candidate["evidence"]["downloads_sha256"]}`.',
                  f'<!-- bbui-python-fix:v1:{fix["key"]} -->']
    lines += ['', 'Evidence: the exact supplier archive metadata and source inventory identify newer library '
              'versions beyond explicit NVD affected-version upper bounds. No supplier binary was executed. '
              'Review upstream fixes and build options, pin the update, verify actual native versions and test '
              'on Unraid before closing issues. This is not an installed fix or stable-release approval. '
              'The same fix will not trigger another mention on daily runs or later rebuilds.']
    body = '\n'.join(lines)
    if len(body) > 60000:
        raise ValueError('Fix notification exceeds GitHub comment limit')
    return {'issue': unseen[0]['issue'], 'body': body, 'count': len(unseen)}


def publish(fixes: list[dict]) -> int:
    """Recheck live history/state, post one mention as bot, and verify persisted body.

    A timeout after creation is recovered by reading the comment marker on the
    next run. The workflow concurrency group serializes scheduled/manual runs.
    """
    shared.require_main_job('python-monitor.yml')
    planned = notification(fixes, shared.existing_issues())
    if planned is None:
        return 0
    shared.require_main_job('python-monitor.yml')
    shared.hosted.bot()
    response = subprocess.run(['gh', 'api', '--method', 'POST',
                               f'repos/{shared.REPO}/issues/{planned["issue"]}/comments', '--input', '-'],
                              input=json.dumps({'body': planned['body']}), capture_output=True, text=True)
    if response.returncode:
        raise RuntimeError('Fix notification failed; rerun to reconcile comment history')
    identifier = json.loads(response.stdout)['id']
    if type(identifier) is not int or identifier <= 0:
        raise ValueError('Invalid notification comment identity')
    saved = shared.evidence.api(f'repos/{shared.REPO}/issues/comments/{identifier}')
    if saved['user']['login'] != shared.hosted.BOT or saved['body'] != planned['body']:
        raise ValueError('Fix notification author/body verification failed')
    return planned['count']
