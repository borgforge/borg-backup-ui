"""Allowlisted read-only mobile details from existing services (#745).

No paths, command strings, credentials or free-form diagnostic text leave these
projections. Archive listing is explicit and may mount storage through the
existing repository service; no mutation or execution endpoint is introduced.
"""
from datetime import datetime, timezone
import math
import re

import mobile_auth as auth
from mobile_api import _code, _id, _name, _number, _stamp

LOCATIONS = ('local', 'usb', 'smb', 'storagebox', 'utility')
OUTCOMES = ('success', 'warning', 'error', 'skipped', 'cancelled', 'unknown')


def location(job):
    """Mirror jobsLocationKey in ui/js/pages/jobs.js, including utility priority."""
    if job.get('is_utility'):
        return 'utility'
    value = str(job.get('location') or '').lower()
    return value if value in LOCATIONS[:-1] else 'local'


def _ratio(value):
    return value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100 else None


def _epoch(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def _opaque(body, key):
    value = body.get(key)
    if set(body) != {key} or not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise auth.MobileError('mobile_bad_request', 400)
    return value


def _current(handler):
    """Recheck in-flight revocation without requiring command or log permission."""
    session = handler._mobile_session
    with auth.LOCK:
        current = next((s for s in auth._load(handler.config)['sessions'] if s['id'] == session['id']), None)
        if (not current or current['token_hash'] != session['token_hash']
                or current['expires_at'] <= auth.time.time()
                or auth._fingerprint(auth._user(handler.config, current['username'])) != current['fingerprint']):
            raise auth.MobileError('mobile_unauthorized', 401)


def resources(config):
    """Return host-only counters; omit processes, cgroups, paths and run metadata."""
    from resource_metrics import get_resource_metrics
    data = get_resource_metrics(config)
    host = data.get('host') or {}
    return {'available': data.get('available') is True, 'stale': data.get('stale') is not False,
            'sampled_at': _epoch(data.get('timestamp')), 'cpu_percent': _ratio(host.get('cpu_percent')),
            'memory_total_bytes': _number(host.get('memory_total_bytes')),
            'memory_available_bytes': _number(host.get('memory_available_bytes'))}


def restore_tests(config):
    """Separate latest attempt, retained evidence and due state; omit raw reports."""
    from restore_tests_api import list_restore_tests, list_restore_test_plan
    reports = {r['job_key']: r for r in list_restore_tests(config)}
    plans = list_restore_test_plan(config)['jobs']
    rows = []
    for plan in plans[:100]:
        report = reports.get(plan['job_key'], {})
        policy = plan.get('policy') or {}
        rows.append({'job_id': _id(plan['job_key']), 'job_name': _name(plan.get('display_name')),
                     'location': location(plan), 'verification': _code(plan.get('verification_status')),
                     'evidence_at': _stamp(plan.get('verification_evidence_date')),
                     'valid_until': _stamp(plan.get('verification_valid_until')),
                     'checked_at': _stamp(plan.get('last_test_date')), 'status': _code(plan.get('last_test_result')),
                     'next_due_at': _stamp(plan.get('next_due_at')), 'next_run_at': _stamp(plan.get('next_run_at')),
                     'overdue': plan.get('is_overdue') is True, 'mode': _code(policy.get('mode')),
                     'interval_days': _number(policy.get('interval_days')), 'validity_days': _number(policy.get('validity_days')),
                     'scheduler_state': _code(plan.get('scheduler_state')),
                     'duration_seconds': _number(report.get('test_duration_seconds')),
                     'reason_code': _code(report.get('failure_code')),
                     'steps': [{'id': _code(s.get('step_id')) or 'unknown', 'status': _code(s.get('status')) or 'unknown',
                                'duration_ms': _number(s.get('duration_ms')), 'reason_code': _code(s.get('error_code'))}
                               for s in report.get('steps', [])[:30] if isinstance(s, dict)]})
    return {'items': rows, 'total': len(plans)}


def _run(run, names, *, details=False):
    if not isinstance(run, dict):
        return None
    steps = run.get('steps') or []
    completed = sum(s.get('status') in {'success', 'warning', 'failed', 'cancelled', 'skipped', 'interrupted'} for s in steps)
    result = {'status': _code(run.get('status')) or 'unknown', 'started_at': _stamp(run.get('started_at')),
              'finished_at': _stamp(run.get('finished_at')), 'completed': completed, 'total': len(steps)}
    if details:
        result['steps'] = [{'job_id': _id(s.get('job_key')), 'job_name': names.get(s.get('job_key')),
                            'status': _code(s.get('status')) or 'unknown', 'started_at': _stamp(s.get('started_at')),
                            'finished_at': _stamp(s.get('finished_at'))} for s in steps[:100]]
    return result


def groups(config):
    """Use existing group lifecycle reconciliation; no start, stop or scheduling."""
    from job_groups import list_groups
    rows = list_groups(config)['groups']
    return {'items': [{'id': _id(g['id']), 'name': _name(g['name']), 'job_count': len(g['jobs']),
                       'run': _run(g.get('run'), {}), 'missing_jobs': len(g.get('missing_jobs', []))}
                      for g in rows[:100]], 'total': len(rows)}


def group_detail(handler, body):
    """Resolve an opaque group ID and return current/last-five bounded runs.

    Raises MobileError for malformed or unknown identity. Uses the existing
    lifecycle reconciliation and never starts jobs or exposes raw runner errors.
    """
    from job_groups import list_groups, group_history
    group_id = _opaque(body, 'group_id')
    group = next((g for g in list_groups(handler.config)['groups'] if _id(g['id']) == group_id), None)
    if not group:
        raise auth.MobileError('mobile_not_found', 404)
    names = {j['key']: _name(j.get('display_name') or j.get('name')) for j in handler._get_jobs()['jobs']}
    return {'id': group_id, 'name': _name(group['name']), 'run': _run(group.get('run'), names, details=True),
            'jobs': [{'job_id': _id(key), 'job_name': names.get(key)} for key in group['jobs'][:100]],
            'history': [_run(r, names, details=True) for r in group_history(handler.config, group['id'], limit=5)['runs']]}


def archives(handler, body):
    """Resolve only managed opaque repository IDs; read at most 100 newest rows."""
    from repositories_api import read_repository_store, get_repository_archives
    repo_id = _opaque(body, 'repository_id')
    repo = next((r for r in read_repository_store(handler.config)['repositories'] if _id(r['repository_key']) == repo_id), None)
    if not repo:
        raise auth.MobileError('mobile_not_found', 404)
    try:
        data = get_repository_archives(handler.config, repo['repository_key'], limit=100)
    except (ValueError, OSError, RuntimeError) as exc:
        raise auth.MobileError('mobile_archive_unavailable', 503) from exc
    rows = []
    for row in data['archives'][:100]:
        start, end = _stamp(row.get('start')), _stamp(row.get('end'))
        duration = _number(row.get('duration'))
        if duration is None and start and end:
            duration = _number((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
        rows.append({'name': str(row.get('name') or '')[:255], 'start': start, 'end': end, 'duration_seconds': duration})
    return {'repository_id': repo_id, 'name': _name(repo.get('display_name')), 'total': data['archive_count'],
            'sampled_at': datetime.now(timezone.utc).isoformat(), 'items': rows}


def report(handler, body):
    """Project existing server-local day totals and its exact success denominator."""
    days = body.get('days')
    if set(body) != {'days'} or type(days) is not int or days not in (7, 30, 90):
        raise auth.MobileError('mobile_bad_request', 400)
    data = handler._get_report_overview(f'days={days}&location=all')
    return {'days': days, 'from': data['from'], 'to': data['to'],
            'counts': {k: _number(data['counts'].get(k)) for k in OUTCOMES},
            'success_rate': _ratio(data.get('success_rate')),
            'average_duration_seconds': _number(data.get('average_duration_seconds')),
            'daily': [{'date': p['date'], **{k: _number(p.get(k)) for k in OUTCOMES}} for p in data['daily'][:90]]}


def handle(handler, endpoint, body):
    """Dispatch authenticated reads and check revocation again before responding."""
    _current(handler)
    if endpoint == 'monitoring':
        result = {'sampled_at': datetime.now(timezone.utc).isoformat()}
        for key, reader in (('resources', resources), ('restore_tests', restore_tests), ('groups', groups)):
            try:
                result[key] = reader(handler.config)
            except (OSError, ValueError, RuntimeError):
                result[key] = None  # optional section unavailable, never a fabricated zero
    elif endpoint == 'repositories/archives':
        result = archives(handler, body)
    elif endpoint == 'reports/read':
        result = report(handler, body)
    elif endpoint == 'groups/read':
        result = group_detail(handler, body)
    else:
        raise auth.MobileError('mobile_not_found', 404)
    _current(handler)
    return result
