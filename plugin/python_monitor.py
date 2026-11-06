#!/usr/bin/env python3
"""Monitor the shipped Python build, native CVEs and support lifecycle (#548)."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
import re
import sys
import tarfile
import time
import urllib.parse
import urllib.request

from packaging.version import Version, InvalidVersion

import apprise_monitor as monitor
import release_workflow as release
import python_fix_monitor as fix_monitor

ROOT = monitor.ROOT
PEPS = 'https://peps.python.org/api/python-releases.json'
LATEST = 'https://raw.githubusercontent.com/astral-sh/python-build-standalone/latest-release/latest-release.json'
NVD = 'https://services.nvd.nist.gov/rest/json/cves/2.0'
# Product identities, not version pins. Version/build/native versions come only
# from the same provenance that the package builder verifies and ships.
PRODUCTS = {
    'cpython': 'python:python', 'openssl-3.5': 'openssl:openssl', 'bzip2': 'bzip:bzip2',
    'expat': 'libexpat:expat', 'libffi': 'libffi_project:libffi', 'libedit': 'libedit_project:libedit',
    'ncurses': 'gnu:ncurses', 'bdb': 'oracle:berkeley_db', 'mpdecimal': None,
    'sqlite': 'sqlite:sqlite', 'xz': 'tukaani:xz', 'zlib': 'zlib:zlib',
    'uuid': None, 'tcl': 'tcl:tcl', 'tk': 'tcl:tk',
    'libX11': 'x.org:libx11', 'libXau': 'x.org:libxau', 'libxcb': 'x.org:libxcb',
}
CHECKLIST = '''

## Maintainer review

- [ ] Triage release notes / CVE applicability and fixed versions, including native libraries.
- [ ] Update the pinned supplier archive and provenance with plugin/python_runtime.py; review licenses and glibc/CPU requirements.
- [ ] Test both external and private Python, notifications, admin recovery, backup and restore on Unraid 6.12.5 and supported 7.x.
- [ ] Complete PR CI, publish a test candidate and obtain explicit maintainer test/stable approval before a separate release PR.
- [ ] Record evidence and any deliberate deferral here. No automatic runtime update is authorized.

Notes outside the monitor block are preserved. Use `status::waiting` or close as
not planned to defer. NVD findings require applicability review and are not a
claim that every listed CVE is exploitable in Borg Backup UI.
'''


def read_json(url: str) -> dict:
    """Read bounded public metadata without credentials, redirects or silent fallback."""
    if not (url in (PEPS, LATEST) or url.startswith(NVD + '?')):
        raise ValueError('Unapproved Python monitor source')
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'borg-backup-ui-dependency-monitor'})
    with urllib.request.build_opener(monitor.NoRedirect).open(request, timeout=60) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError('Monitor response exceeds size bound')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('Monitor response must be an object')
    return result


def finding(key: str, title: str, text: str, *, security: bool = False) -> dict:
    """Render locally controlled issue fields and fixed repository labels."""
    result = {'key': key, 'title': title, 'text': text,
              'labels': ['type::security' if security else 'type::maintenance', 'impact::internal', 'release-note::no']}
    if security:
        result['identifiers'] = [key.split(':', 1)[1]]
    return result


def release_findings(lock: dict, pep: dict, supplier: dict, today: date) -> list[dict]:
    """Detect actual stable releases, same-version rebuilds and 180/90/0-day EOL gates."""
    current = Version(lock['version'])
    series = f'{current.major}.{current.minor}'
    releases = pep['releases']
    metadata = pep['metadata']
    if series not in releases or series not in metadata:
        raise ValueError('Shipped Python series is absent from lifecycle data')
    stable = []
    for entries in releases.values():
        for item in entries:
            if item['state'] != 'actual' or date.fromisoformat(item['date']) > today:
                continue
            stage = item['stage'].removesuffix(' final')
            if re.fullmatch(r'3\.\d+\.\d+', stage):
                stable.append(Version(stage))
    patches = [v for v in stable if v.release[:2] == current.release[:2]]
    if not patches:
        raise ValueError('No actual stable release in shipped series')
    output = []
    latest_patch = max(patches)
    if latest_patch > current:
        output.append(finding(f'release:patch-{latest_patch}', f'Update bundled Python to {latest_patch}',
                              f'Monitored Python: {current}. Available patch/security release: {latest_patch}.\n'
                              f'Urgency: review promptly, including the security changes. Source: {PEPS}\n'
                              'Obtain a verified supplier build; do not change the Python series automatically.'))
    latest_series = max(stable)
    if latest_series.release[:2] > current.release[:2]:
        new = f'{latest_series.major}.{latest_series.minor}'
        output.append(finding(f'release:series-{new}', f'Review Python {new} compatibility for the private runtime',
                              f'Monitored series: {series}. New stable series: {new}.\n'
                              f'Urgency: compatibility planning, no automatic series switch. Source: {PEPS}'))
    tag = supplier['tag_name']
    if supplier['draft'] or supplier['prerelease'] or not re.fullmatch(r'\d{8}', tag):
        raise ValueError('Invalid supplier release identity')
    available = []
    for asset in supplier['assets']:
        match = re.fullmatch(r'cpython-(3\.\d+\.\d+)\+' + tag + r'-x86_64-unknown-linux-gnu-pgo\+lto-full.tar.zst', asset['name'])
        if match and Version(match[1]).release[:2] == current.release[:2]:
            available.append(Version(match[1]))
    if not available:
        raise ValueError('Latest supplier release lacks the shipped platform/series')
    candidate = max(available)
    stripped = f'cpython-{candidate}+{tag}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz'
    if stripped not in {asset['name'] for asset in supplier['assets']}:
        raise ValueError('Latest supplier release lacks the stripped runtime artifact')
    if candidate > current or (candidate == current and tag > lock['build']):
        output.append(finding(f'release:build-{candidate}-{tag}', f'Review Python runtime build {candidate}+{tag}',
                              f'Monitored build: {current}+{lock["build"]}. Available: {candidate}+{tag}.\n'
                              f'Source: https://github.com/astral-sh/python-build-standalone/releases/tag/{tag}\n'
                              'Urgency: review native-library and security changes, including same-version rebuilds.'))
    eol = date.fromisoformat(metadata[series]['end_of_life'])
    days = (eol - today).days
    if days <= 180:
        threshold = 0 if days <= 0 else 90 if days <= 90 else 180
        output.append(finding(f'release:eol-{series}-{threshold}', f'Plan Python {series} support transition ({threshold}-day warning)',
                              f'Monitored series: {series}. Upstream support ends {eol.isoformat()}.\n'
                              f'Urgency: {"unsupported; prioritize replacement" if threshold == 0 else "complete migration before support ends"}.\n'
                              f'Source: {PEPS}\nWarning policy: 180 days, escalation at 90 days and at end of support.'))
    return output


def relevant_match(match: dict, product: str, version: str) -> bool:
    """Exclude non-vulnerable context products and ranges known not to match.

    Unknown native version syntax is conservatively flagged for human review.
    NVD's API first filters the versioned virtual CPE; this additional check
    prevents unrelated products/nodes from turning into security findings.
    """
    prefix = 'cpe:2.3:a:' + product + ':'
    if match['vulnerable'] is not True or not match['criteria'].startswith(prefix):
        return False
    exact = match['criteria'][len(prefix):].split(':')[0]
    try:
        current = Version(version)
        if exact not in ('*', '-') and current != Version(exact):
            return False
        for key, test in [('versionStartIncluding', lambda a, b: a >= b),
                          ('versionStartExcluding', lambda a, b: a > b),
                          ('versionEndIncluding', lambda a, b: a <= b),
                          ('versionEndExcluding', lambda a, b: a < b)]:
            if key in match and not test(current, Version(match[key])):
                return False
    except InvalidVersion:
        return True
    return True


def configuration_matches(node: dict, product: str, version: str) -> bool:
    """Return whether an NVD expression can apply to this Linux/x86_64 build.

    False requires a proven incompatible operand. Other products, negation and
    unknown platform syntax remain possible, requiring human triage. Preserve
    AND/OR grouping, including nested nodes; never flatten a mandatory context.
    """
    if node.get('negate'):
        return True
    values = []
    for match in node.get('cpeMatch', []):
        criteria = match['criteria']
        fields = criteria.split(':')
        if (len(fields) != 13 or fields[:2] != ['cpe', '2.3']
                or type(match['vulnerable']) is not bool):
            raise ValueError('Malformed NVD CPE')
        incompatible = (criteria.startswith(('cpe:2.3:o:microsoft:windows', 'cpe:2.3:o:apple:mac_os'))
                        or fields[10] in ('windows', 'mac_os', 'mac_os_x', 'android', 'ios')
                        or fields[11] in ('aarch64', 'arm64', 'arm', 'i686'))
        if incompatible:
            values.append(False)
        elif criteria.startswith('cpe:2.3:a:' + product + ':'):
            # Context entries constrain the version too, even if not vulnerable.
            values.append(relevant_match({**match, 'vulnerable': True}, product, version))
        else:
            values.append(True)
    values.extend(configuration_matches(child, product, version)
                  for child in node.get('nodes', []))
    operator = node.get('operator', 'OR')
    if operator not in ('AND', 'OR'):
        raise ValueError('Unknown NVD configuration operator')
    if not values:
        raise ValueError('Empty NVD configuration')
    return all(values) if operator == 'AND' else any(values)


def vulnerable_matches(node: dict, product: str, version: str) -> list[dict]:
    """Collect possible vulnerable operands only from compatible subexpressions."""
    if node.get('negate'):
        return [{'negated_configuration': product}]
    if not configuration_matches(node, product, version):
        return []
    result = [match for match in node.get('cpeMatch', [])
              if relevant_match(match, product, version)
              and configuration_matches({'cpeMatch': [match]}, product, version)]
    for child in node.get('nodes', []):
        result.extend(vulnerable_matches(child, product, version))
    return result


def keyword_mentions_component(cve: dict, name: str) -> bool:
    """Require a whole component name for unclassified keyword candidates.

    NVD substring search for libedit also returns libeditorconfig. Inspect prose
    only as data for disambiguation; never render upstream text in an issue.
    """
    aliases = {'libedit': ('libedit', 'editline'), 'uuid': ('libuuid',),
               'mpdecimal': ('mpdecimal', 'libmpdec')}[name]
    descriptions = cve['descriptions']
    if not isinstance(descriptions, list) or not descriptions:
        raise ValueError('Missing keyword candidate description')
    text = ' '.join(row['value'] for row in descriptions).lower()
    return any(re.search(r'(?<![a-z0-9])' + re.escape(alias) + r'(?![a-z0-9])', text) for alias in aliases)


def security_findings(lock: dict, request=read_json, pause=time.sleep) -> list[dict]:
    """Query all shipped components with NVD rate limiting and bounded pagination.

    Group CVEs across components. Missing/schema/HTTP failures abort the entire
    scan before any writes; no incomplete scan can report an all-clear result.
    """
    by_cve = {}
    for index, (name, component) in enumerate(sorted(lock['components'].items())):
        product = PRODUCTS[name]  # unknown inventory entries require explicit coverage
        version = component['version']
        if not re.fullmatch(r'[0-9A-Za-z.+_-]{1,80}', version):
            raise ValueError('Invalid component version')
        start = 0
        expected_total = None
        seen = set()
        while True:
            if index or start:
                pause(6.5)  # public NVD limit: five requests per rolling 30 seconds
            params = {'resultsPerPage': 2000, 'startIndex': start}
            if product is None or name == 'libedit':
                # These libraries have no dependable versioned CPE inventory.
                # Never invent an empty product match and report a false clean
                # scan; send keyword candidates for explicit human triage.
                params['keywordSearch'] = 'libuuid' if name == 'uuid' else name
            else:
                params['virtualMatchString'] = f'cpe:2.3:a:{product}:{version}:*:*:*:*:*:*:*'
            query = urllib.parse.urlencode(params)
            data = request(NVD + '?' + query)
            rows = data['vulnerabilities']
            total = data['totalResults']
            if (data['startIndex'] != start or type(total) is not int or total < 0 or total > 10000
                    or not isinstance(rows, list) or len(rows) > 2000 or (not rows and start < total)
                    or start + len(rows) > total
                    or (expected_total is not None and total != expected_total)):
                raise ValueError('Incomplete NVD result')
            expected_total = total
            for item in rows:
                cve = item['cve']
                identifier = cve['id']
                if not re.fullmatch(r'CVE-\d{4}-\d{4,}', identifier):
                    raise ValueError('Malformed CVE identifier')
                if identifier in seen:
                    raise ValueError('Duplicate NVD result; pagination is unstable')
                seen.add(identifier)
                if cve['vulnStatus'] == 'Rejected':
                    continue
                matches = [match for config in cve.get('configurations', [])
                           for match in (vulnerable_matches(config, product, version) if product else [])]
                if product and name != 'libedit' and not cve.get('configurations'):
                    # A versioned API hit without analysis is not an all-clear.
                    matches = [{'unclassified_candidate': name}]
                if (product is None or (name == 'libedit' and not cve.get('configurations'))) and keyword_mentions_component(cve, name):
                    matches = [{'keyword_candidate': name}]
                if matches:
                    record = by_cve.setdefault(identifier, {'components': set(), 'facts': []})
                    record['components'].add(f'{name} {version}')
                    record['facts'].append({'matches': matches, 'modified': cve['lastModified'],
                                            'metrics': cve.get('metrics', {}),
                                            'descriptions': cve.get('descriptions', []),
                                            'references': cve.get('references', [])})
            start += len(rows)
            if start >= total:
                break
    output = []
    for identifier, record in sorted(by_cve.items()):
        digest = facts_digest(record['facts'])
        output.append(finding(f'security:{identifier}', f'Review private Python runtime advisory {identifier}',
                              f'Monitored build: {lock["version"]}+{lock["build"]}.\n'
                              f'Potentially affected components: {", ".join(sorted(record["components"]))}.\n'
                              f'Source and affected/fixed version ranges: https://nvd.nist.gov/vuln/detail/{identifier}\n'
                              'Urgency: security triage now; confirm platform/feature applicability and supplier fixes.\n'
                              'Classification: potential; version/CPE matches do not prove reachability or a fix. '
                              'Review compile options and CLI presence separately.\n'
                              f'Advisory facts SHA256: {digest}', security=True))
    return output


def facts_digest(value) -> str:
    """Fingerprint advisory facts without treating API list order as a change."""
    def normalize(item):
        if isinstance(item, dict):
            return {key: normalize(val) for key, val in item.items()}
        if isinstance(item, list):
            return sorted((normalize(val) for val in item), key=lambda val: json.dumps(val, sort_keys=True))
        return item
    return hashlib.sha256(json.dumps(normalize(value), sort_keys=True).encode()).hexdigest()


def baselines(root=ROOT) -> list[tuple[str, dict]]:
    """Read planned source and actual stable payload, never infer shipped pins.

    A merged source update may precede stable publication. Keep scanning the
    released runtime during that interval. Historical releases without private
    Python are validated but contribute no invented runtime baseline.
    """
    source = json.loads((root / 'runtime/python/runtime.lock.json').read_text())
    version = release.manifest_version(root / 'borg-backup-ui.plg')
    if not re.fullmatch(r'[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]{4}', version):
        raise ValueError('Malformed stable plugin version')
    package = root / 'releases' / f'borg-backup-ui-{version}.txz'
    provenance = release.package_provenance(package)
    if 'python_runtime_lock_sha256' not in provenance:
        return [('planned source; stable has no private runtime yet', source)]
    with tarfile.open(package) as archive:
        member = archive.extractfile('boot/config/plugins/borg-backup-ui/runtime/python/python-runtime.json')
        shipped = json.loads(member.read())
    same = all(shipped.get(key) == source.get(key) for key in
               ('version', 'build', 'components', 'sha256', 'install_sha256'))
    if same:
        return [(f'published stable {version} and current source', shipped)]
    return [(f'published stable {version}', shipped), ('planned source update', source)]


def merge_findings(scoped: list[tuple[str, list[dict]]]) -> list[dict]:
    """Group a CVE/release across shipped and proposed builds into one issue."""
    grouped = {}
    for scope, detected in scoped:
        for item in detected:
            text = f'Scope: {scope}.\n' + item['text']
            if item['key'] in grouped:
                grouped[item['key']]['text'] += '\n\n' + text
            else:
                grouped[item['key']] = {**item, 'text': text}
    return list(grouped.values())


def run(apply: bool = False) -> dict:
    """Collect complete upstream evidence before reconciling bot-authored issues."""
    if apply:
        monitor.require_main_job('python-monitor.yml')
        monitor.hosted.bot()
    versions = baselines(ROOT)
    tag = read_json(LATEST)['tag']
    if not re.fullmatch(r'\d{8}', tag):
        raise ValueError('Invalid latest supplier tag')
    supplier = monitor.evidence.api(f'repos/astral-sh/python-build-standalone/releases/tags/{tag}')
    pep = read_json(PEPS)
    cache = {}
    def cached_request(url):
        """Reuse identical public queries within this complete multi-build scan."""
        if url not in cache:
            cache[url] = read_json(url)
        return cache[url]
    scoped = []
    for scope, lock in versions:
        found = release_findings(lock, pep, supplier, date.today())
        found += security_findings(lock, request=cached_request)
        scoped.append((scope, found))
    found = merge_findings(scoped)
    issues = monitor.existing_issues()
    actions, deferred = monitor.plan_updates(found, issues, namespace='python', checklist=CHECKLIST)

    def fix_request(url):
        """Rate-limit additional CVE lookups and reuse complete source responses."""
        if url not in cache:
            time.sleep(6.5)
        return cached_request(url)

    fixes = fix_monitor.discover(versions, supplier, pep, issues, fix_request, sys.modules[__name__])
    notice = fix_monitor.notification(fixes, issues)
    notified = 0
    if apply:
        for action in actions:
            monitor.write_issue(action, workflow='python-monitor.yml')
        if notice:
            notified = fix_monitor.publish(fixes)
    return {'mode': 'apply' if apply else 'preview',
            'scan_status': 'complete', 'release_authorized': False,
            'fix_candidates': len(fixes), 'new_fix_notifications': notice['count'] if notice else 0,
            'notified_fixes': notified,
            'security_candidates': sum(item['key'].startswith('security:') for item in found),
            'security_scope': 'CPython and inventoried native libraries; separate from pip-audit',
            'baselines': [{'scope': scope, 'build': item['version'] + '+' + item['build']} for scope, item in versions],
            'components_scanned': sum(len(item['components']) for _, item in versions), 'findings': len(found), 'deferred': deferred,
            'creates': sum(a['method'] == 'POST' for a in actions), 'updates': sum(a['method'] == 'PATCH' for a in actions)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = monitor.checked('Python upstream metadata, inventory or issue reconciliation', run, args.apply)
    except monitor.MonitorFailure as exc:
        print(f'Python monitor failed during {exc}; no all-clear result. See the Python runtime maintainer guide.', file=sys.stderr)
        sys.exit(1)
    summary = json.dumps(result, sort_keys=True)
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
            handle.write('Python runtime monitor completed: `' + summary + '`\n')
