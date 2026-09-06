"""Canonical job navigation and historical payload projections (#476).

Configured inventory is authoritative for active summaries. Historical names
are display evidence only; no filename, alias or prefix inference occurs here.
"""
from dataclasses import asdict
from pathlib import Path

from job_model import validate_job_id


def valid_job_id(value):
    try:
        return validate_job_id(value)
    except ValueError:
        return ""


def configured_jobs(config):
    from inventory_store import inventory_lock
    from job_store import read_jobs
    from repository_context import jobs_dir, load_repository_inventory, resolve_job_repository_context
    with inventory_lock(jobs_dir(config).parent):
        inventory = load_repository_inventory(config)
        result = {}
        for job_id, raw in read_jobs(jobs_dir(config)).items():
            context = resolve_job_repository_context(config, job_id, job=raw,
                require_passphrase_file=False, inventory=inventory)
            result[job_id] = {
                **{key: raw.get(key) for key in ('name', 'description', 'icon', 'icon_color', 'enabled', 'restore_test_policy')},
                'job_id': job_id, 'display_name': raw['name'],
                'archive_prefix': raw['archive_prefixes'][0],
                'archive_prefixes': list(raw['archive_prefixes']),
                'location': context['location'], 'repository_key': raw['repository_key'],
                'repo_path': context['repository_path'],
            }
        return result


def load_statuses(config):
    from status import StatusStore
    return StatusStore(Path(config['STATUS_DIR'])).load()


def identity_scope(status, jobs):
    if status.job_id and status.identity_state != 'unassigned':
        return 'configured' if status.job_id in jobs else 'deleted'
    if status.job_id and status.identity_reason == 'deleted_job' and status.job_id not in jobs:
        return 'deleted'
    return 'unassigned'


def historical_row(status, jobs):
    from status import format_bytes, format_duration
    data = asdict(status)
    data.pop('source_path', None)
    scope = identity_scope(status, jobs)
    job = jobs.get(status.job_id, {}) if scope == 'configured' else {}
    name = status.job_name_snapshot or (status.backup_type if status.backup_type != 'unknown' else '')
    location = status.location_snapshot or (status.location if status.location != 'unknown' else '')
    return {
        **data, 'entry_kind': 'backup_run', 'identity_scope': scope,
        'legacy_status': not bool(valid_job_id(status.run_id)),
        'current_job_name': job.get('name', ''), 'display_name': job.get('name') or name,
        'historical_name': name, 'location': location,
        'filename': status.source_path.name if status.source_path else '',
        'date': status.timestamp[:10], 'time': status.timestamp[11:19],
        'duration_fmt': format_duration(status.duration_seconds),
        **{key + '_fmt': format_bytes(getattr(status, key)) for key in (
            'original_size', 'compressed_size', 'deduplicated_size', 'repository_size')},
    }


def history_rows(config, jobs=None):
    jobs = configured_jobs(config) if jobs is None else jobs
    return [historical_row(status, jobs) for status in load_statuses(config)]


def navigation_jobs(jobs, rows):
    result = {job_id: {**job, 'identity_scope': 'configured'} for job_id, job in jobs.items()}
    for row in sorted(rows, key=lambda r: (r['timestamp'], r['filename'])):
        job_id = row['job_id']
        if row['identity_scope'] == 'deleted':
            result[job_id] = {'job_id': job_id, 'identity_scope': 'deleted',
                'name': row['historical_name'], 'display_name': row['historical_name'],
                'location': row['location'], 'enabled': False}
    return sorted(result.values(), key=lambda row: (row['identity_scope'], str(row.get('name') or '').casefold(), row['job_id']))


def summarize(backups):
    """Exclusive enabled-job categories, shared by dashboard and widgets."""
    result = dict.fromkeys(('total', 'enabled', 'disabled', 'running', 'success', 'warning', 'skipped', 'error', 'never', 'unknown'), 0)
    for row in backups:
        result['total'] += 1
        if row.get('enabled') is False:
            result['disabled'] += 1
            continue
        result['enabled'] += 1
        if row.get('running'):
            category = 'running'
        elif row.get('status') in {'error', 'failed', 'failure'}:
            category = 'error'
        elif row.get('backup_overdue'):
            category = 'warning'
        elif row.get('never_run'):
            category = 'never'
        else:
            state = row.get('status')
            category = {'cancelled': 'warning', 'failed': 'error', 'failure': 'error'}.get(state, state)
            if category not in {'success', 'warning', 'skipped', 'error'}:
                category = 'unknown'
        result[category] += 1
    return result


def apply_restore_verification(config, backups):
    from restore_tests_api import build_restore_verification_map
    verification = build_restore_verification_map(config, backups)
    for row in backups:
        proof = verification.get(row['job_id'], {})
        for field in ('status', 'reason', 'last_test_date', 'valid_until', 'is_overdue', 'failure_code', 'failure_hint', 'failure_category'):
            row['restore_verification_' + field] = proof.get(field, False if field == 'is_overdue' else '')
