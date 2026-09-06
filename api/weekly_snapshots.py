"""UUID-owned weekly observations; conflicting migration evidence is retained."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path

from job_model import validate_job_id


def _empty():
    return {'schema_version': 1, 'identity_schema_version': 1, 'observations': []}


def read_observations(*paths):
    from status import status_storage_unavailable_reason
    rows = []
    for path in dict.fromkeys(paths):
        if status_storage_unavailable_reason(path) or not path.exists():
            continue
        from job_store import read_json
        data = read_json(path)
        if (not isinstance(data, dict) or data.get('identity_schema_version') != 1 or data.get('schema_version') != 1
                or not isinstance(data.get('observations'), list)):
            raise ValueError('Weekly snapshots require the approved identity migration')
        for index, original in enumerate(data['observations']):
            if not isinstance(original, dict):
                raise ValueError('Invalid weekly observation')
            row = deepcopy(original)
            if row.get('job_id') is not None:
                validate_job_id(row['job_id'])
            elif row.get('identity_state') != 'unassigned':
                raise ValueError('Weekly observation has no identity classification')
            week = date.fromisoformat(row.get('week', ''))
            if week.weekday() != 0 or type(row.get('size')) is not int or row['size'] < 0:
                raise ValueError('Invalid weekly observation period or size')
            evidence = row.get('source_records')
            if (not isinstance(evidence, list) or not evidence or any(
                    not isinstance(item, dict) or not isinstance(item.get('source'), str)
                    or not isinstance(item.get('locator'), str) for item in evidence)):
                raise ValueError('Weekly observation provenance is missing')
            rows.append(row)
    return merge_observations(rows)


def merge_observations(rows):
    groups = {}
    for original in rows:
        row = deepcopy(original)
        evidence = row.pop('source_records')
        row.pop('conflict', None)
        key = json.dumps(row, sort_keys=True, ensure_ascii=False)
        group = groups.setdefault(key, {**row, 'source_records': []})
        for item in evidence:
            if item not in group['source_records']:
                group['source_records'].append(item)
    result = list(groups.values())
    values = {}
    for row in result:
        owner = (row.get('job_id'), row.get('legacy_job_key') if not row.get('job_id') else '')
        values.setdefault((owner, row['week']), set()).add(row['size'])
    for row in result:
        owner = (row.get('job_id'), row.get('legacy_job_key') if not row.get('job_id') else '')
        if len(values[(owner, row['week'])]) > 1:
            row['conflict'] = True
    return sorted(result, key=lambda row: (str(row.get('job_id') or ''), str(row.get('legacy_job_key') or ''), row['week'], row['size']))


def write_current(snapshot_file, latest, *, legacy_file=None, force=False):
    from inventory_store import inventory_lock, atomic_write_json
    from status import status_storage_unavailable_reason, ensure_status_storage_directory
    if status_storage_unavailable_reason(snapshot_file):
        return
    ensure_status_storage_directory(snapshot_file.parent)
    today = date.today()
    week = (today - timedelta(days=today.weekday())).isoformat()
    with inventory_lock(snapshot_file.parent):
        paths = [snapshot_file] + ([legacy_file] if legacy_file else [])
        rows = read_observations(*paths)
        original_rows = deepcopy(rows)
        for job_id, status in latest.items():
            validate_job_id(job_id)
            if status.key != job_id or status.repository_size <= 0:
                continue
            previous = [row for row in rows if row.get('job_id') == job_id and row['week'] == week and row.get('observation_kind') == 'runtime']
            from status_read_model import valid_job_id
            current_order = (bool(valid_job_id(status.run_id)), status.timestamp)
            if previous and max((bool(valid_job_id(row.get('run_id'))), row.get('timestamp', '')) for row in previous) > current_order:
                continue
            # Only our live weekly sample can be updated. Migrated observations,
            # their conflicts and unassigned provenance are never overwritten.
            rows = [row for row in rows if row not in previous]
            rows.append({'job_id': job_id, 'week': week, 'size': status.repository_size,
                         'observation_kind': 'runtime', 'timestamp': status.timestamp,
                         'run_id': status.run_id, 'repository_key_snapshot': status.repository_key_snapshot,
                         'repository_snapshot': status.repository_snapshot,
                         'source_records': [{'source': str(status.source_path), 'locator': ''}]})
        rows = merge_observations(rows)
        if rows != original_rows or force:
            existing = _empty()
            if snapshot_file.exists():
                from job_store import read_json
                existing = read_json(snapshot_file)
            atomic_write_json(snapshot_file, {**existing, **_empty(), 'observations': rows})


def chart_series(rows, job_ids):
    groups = {}
    for row in rows:
        job_id = row.get('job_id')
        if job_id not in job_ids or row.get('identity_state') == 'unassigned':
            continue
        groups.setdefault((job_id, row['week']), []).append(row)
    result = {}
    for (job_id, week), observations in sorted(groups.items()):
        values = {row['size'] for row in observations}
        conflict = len(values) > 1 or any(row.get('conflict') for row in observations)
        repositories = {(row.get('repository_key_snapshot', ''), row.get('repository_snapshot', '')) for row in observations}
        result.setdefault(job_id, []).append({'week': week,
            'size': None if conflict else next(iter(values)), 'conflict': conflict,
            'repository_key_snapshot': next(iter(repositories))[0] if len(repositories) == 1 else '',
            'repository_snapshot': next(iter(repositories))[1] if len(repositories) == 1 else '',
        })
    return {job_id: entries[-8:] for job_id, entries in result.items()}
