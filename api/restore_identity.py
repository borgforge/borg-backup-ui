"""Immutable restore ownership and captured repository descriptors (#477)."""
from copy import deepcopy

from job_model import validate_job_id

SNAPSHOT_FIELDS = (
    'job_id', 'run_id', 'job_name_snapshot', 'repository_key_snapshot',
    'repository_snapshot', 'archive_prefix_snapshot', 'archive_prefixes_snapshot',
    'location_snapshot', 'identity_state', 'identity_reason', 'legacy_job_key',
)


def capture_repository(config, job_id):
    from inventory_store import inventory_lock
    from repository_context import jobs_dir, resolve_job_repository_context
    job_id = validate_job_id(job_id)
    with inventory_lock(jobs_dir(config).parent):
        context = deepcopy(resolve_job_repository_context(config, job_id))
    return {
        **context,
        'repo': context['repository_path'],
        'passphrase_file': context['passphrase_ref'] or None,
    }


def archive_prefix(info, archive):
    """Match literal stored prefixes, choosing the most specific owned prefix."""
    prefixes = info['job']['archive_prefixes']
    matches = [p for p in prefixes if archive.startswith(p + '-')]
    if not matches:
        raise ValueError('Archive does not belong to this job in its current repository')
    return max(matches, key=len)


def snapshots(info, archive='', run_id=''):
    job = info['job']
    return {
        'job_id': validate_job_id(job['job_id']),
        'run_id': run_id,
        'job_name_snapshot': job['name'],
        'repository_key_snapshot': info['repository_key'],
        'repository_snapshot': info['repo'],
        'archive_prefix_snapshot': archive_prefix(info, archive) if archive else job['archive_prefixes'][0],
        'archive_prefixes_snapshot': list(job['archive_prefixes']),
        'location_snapshot': info['location'],
    }


def historical_identity(row, jobs):
    """Payload identity is authoritative; filenames and old labels never assign jobs."""
    from status_read_model import valid_job_id
    result = dict(row)
    job_id = valid_job_id(row.get('job_id'))
    if job_id and row.get('identity_reason') == 'deleted_job' and job_id not in jobs:
        result.update(job_id=job_id, identity_scope='deleted', current_job_name='')
    elif not job_id or row.get('identity_state') == 'unassigned':
        result.update(job_id='', identity_scope='unassigned', current_job_name='')
    else:
        job = jobs.get(job_id)
        result.update(job_id=job_id, identity_scope='configured' if job else 'deleted',
                      current_job_name=job['name'] if job else '')
    return result


def request_job_id(params, *, query=False):
    if any(key in params for key in ('job', 'job_key', 'job_keys')):
        raise ValueError('Restore operations require job_id')
    value = params.get('job_id')
    if query:
        if not isinstance(value, list) or len(value) != 1:
            raise ValueError('Exactly one job_id is required')
        value = value[0]
    return validate_job_id(value)
