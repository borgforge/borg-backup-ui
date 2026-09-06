"""Owned identity stores, bounded diagnostics and precise deletion (#447, #478).

Logical names are a closed ownership registry, never paths supplied by a client.
Historical evidence is retained until its exact digest is explicitly confirmed.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from job_model import validate_job, validate_job_inventory, validate_job_id
from job_store import read_json
from repository_context import jobs_dir
from migrations.identity_records import verify_records
from migrations.identity_storage import inventory_group, inventory_directories

SINGLETONS = {
    'repositories.json': 'repositories', 'storages.json': 'storages', 'schedules.json': 'schedules',
    'restore-runs.json': 'restore_runs', 'restore-history/index.json': 'restore_index',
    'notification-queue.json': 'notification_queue', 'notification-deliveries.json': 'notification_deliveries',
    'notification-state.json': 'notification_state',
}
HISTORY = {'status', 'restore_test', 'restore_detail', 'restore_index', 'notification_deliveries', 'notification_state', 'weekly'}


def store_layout(config):
    root = jobs_dir(config).parent
    status = Path(config.get('STATUS_DIR') or '/mnt/user/backup-status')
    return {'config': root, 'status': status,
            'proof': Path(config.get('RESTORE_TEST_STATUS_DIR') or status.parent / 'restore-status'),
            'weekly': Path(config.get('SNAPSHOT_FILE') or status.parent / 'weekly-snapshots.json'),
            'recovery': Path(config.get('RUNTIME_RECOVERY_FILE') or root / 'runtime-recovery.json')}


def owned_paths(config, *, runtime=False):
    layout = store_layout(config); root = layout['config']
    result = {'config/' + name: (root / name, kind) for name, kind in SINGLETONS.items()}
    result.update({'weekly': (layout['weekly'], 'weekly'), 'recovery': (layout['recovery'], 'runtime_recovery')})
    groups = [('config/jobs', root / 'jobs', '.json', 'job'),
              ('config/restore-history/runs', root / 'restore-history/runs', '.json', 'restore_detail'),
              ('status', layout['status'], '.status', 'status'), ('proof', layout['proof'], '.test', 'restore_test')]
    if runtime:
        from jobs_api import resolve_resource_lock_dir
        from job_runs import control_root
        groups.append(('locks', resolve_resource_lock_dir(config), '.json', 'resource_lock'))
        controls = control_root()
        for run_id in inventory_directories(controls)['entries']:
            for name in inventory_group(controls / run_id, ['.json'])['entries']:
                kind = {'state.json': 'control', 'context.json': 'run_context', 'cancel.request.json': 'cancel_request'}.get(name, 'unknown')
                result['controls/' + run_id + '/' + name] = (controls / run_id / name, kind)
    for namespace, directory, suffix, kind in groups:
        for name in inventory_group(directory, [suffix])['entries']:
            result[namespace + '/' + name] = (directory / name, kind)
    values = [str(path.absolute()) for path, _ in result.values()]
    if len(values) != len(set(values)):
        raise ValueError('Identity store locations overlap')
    return result


def read_owned(config, *, runtime=False):
    return {name: {'kind': kind, 'data': data} for name, (path, kind) in owned_paths(config, runtime=runtime).items()
            if (data := read_json(path)) is not None}


def record_digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def record_references(records):
    """Typed reference map, including map keys; snapshots retain descriptors."""
    references = []
    def walk(value, name, pointer):
        if isinstance(value, dict):
            for key, item in value.items():
                at = pointer + '/' + key.replace('~', '~0').replace('/', '~1')
                if key == 'job_id' and item is not None:
                    references.append({'file': name, 'pointer': at, 'job_id': item, 'encoding': 'value'})
                elif key in {'job_ids', 'source_job_ids'} and isinstance(item, list):
                    references.extend({'file': name, 'pointer': at + '/' + str(i), 'job_id': job_id, 'encoding': 'value'} for i, job_id in enumerate(item))
                else:
                    walk(item, name, at)
        elif isinstance(value, list):
            for i, item in enumerate(value): walk(item, name, pointer + '/' + str(i))
    for name, record in sorted(records.items()):
        data, kind = record['data'], record['kind']
        if kind == 'schedules':
            for key in data:
                if key != 'restore_test': references.append({'file': name, 'pointer': '/' + key, 'job_id': key, 'encoding': 'key'})
        elif kind == 'notification_state':
            for key in data.get('last_sent', {}):
                parts = key.split(':', 2)
                if len(parts) != 3: raise ValueError('Invalid reminder identity key')
                references.append({'file': name, 'pointer': '/last_sent/' + key.replace('~', '~0').replace('/', '~1'), 'job_id': parts[1], 'encoding': 'reminder'})
        walk(data, name, '')
    for ref in references: validate_job_id(ref['job_id'])
    return references


def remap_records(records, mapping):
    output = deepcopy(records)
    for ref in record_references(records):
        job_id = mapping.get(ref['job_id'], ref['job_id'])
        validate_job_id(job_id)
        parts = [part.replace('~1', '/').replace('~0', '~') for part in ref['pointer'].split('/')[1:]]
        parent = output[ref['file']]['data']
        for part in parts[:-1]: parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = parts[-1]
        if ref['encoding'] == 'value': parent[int(key) if isinstance(parent, list) else key] = job_id
        else:
            new_key = job_id if ref['encoding'] == 'key' else ':'.join([key.split(':', 2)[0], job_id, key.split(':', 2)[2]])
            if new_key != key:
                if new_key in parent: raise ValueError('Remapped identity keys collide')
                parent[new_key] = parent.pop(key)
    renamed = {}
    for name, record in output.items():
        if record['kind'] in {'job', 'restore_test'} and record['data'].get('job_id') in mapping.values():
            name = name.rsplit('/', 1)[0] + '/' + record['data']['job_id'] + ('.json' if record['kind'] == 'job' else '.test')
        if name in renamed: raise ValueError('Remapped owned files collide')
        renamed[name] = record
    return renamed


def validate_records(records):
    jobs = {}
    for name, record in records.items():
        if record['kind'] == 'job':
            validate_job(record['data'], filename=name.rsplit('/', 1)[-1])
            job_id = record['data']['job_id']
            if job_id in jobs: raise ValueError('Duplicate job ID')
            jobs[job_id] = record['data']
    validate_job_inventory(jobs)
    from job_store import validate_assignments
    from schedule_api import validate_schedules
    repos = records.get('config/repositories.json', {}).get('data', {'repositories': []})
    validate_assignments(jobs, repos)
    from job_transfer import indexed
    from repository_context import resolve_job_repository_context
    storages = indexed(records.get('config/storages.json', {}).get('data', {}).get('storages', []), 'storage_key')
    repositories = indexed(repos['repositories'], 'repository_key')
    if any(row.get('storage_key') not in storages for row in repositories.values()):
        raise ValueError('A repository references a missing storage')
    inventory = {'repositories': repositories, 'storages': storages}
    for job_id, job in jobs.items():
        resolve_job_repository_context({}, job_id, job=job, inventory=inventory, require_passphrase_file=False)
    validate_schedules(records.get('config/schedules.json', {}).get('data', {}), jobs)
    reasons = verify_records({'/' + name: record for name, record in records.items() if record['kind'] != 'job'}, jobs)
    errors = [reason['code'] for reason in reasons if reason.get('severity') == 'error']
    if errors: raise ValueError('Identity integrity check failed: ' + ', '.join(sorted(set(errors))[:8]))
    record_references(records)
    return jobs


def identity_health(config, *, limit=200):
    from status_read_model import valid_job_id
    findings, records, jobs = [], {}, {}
    def add(code, name='', job_id='', category='error'):
        findings.append({'code': code, 'file': str(name)[:240], 'job_id': valid_job_id(job_id), 'category': category})
    try:
        paths = owned_paths(config, runtime=True)
    except Exception:
        return {'ok': False, 'findings': [{'code': 'owned_store_scan_failed', 'category': 'error'}], 'total': 1, 'truncated': False}
    for name, (path, kind) in paths.items():
        try:
            data = read_json(path)
            if data is None: continue
            records['/' + name] = {'kind': kind, 'data': data}
            if kind == 'job':
                job_id = data.get('job_id')
                if job_id in jobs: add('duplicate_job_id', name, job_id)
                if not job_id: add('missing_job_id', name)
                validate_job(data, filename=path.name)
                jobs[job_id] = data
        except Exception as exc:
            add(getattr(exc, 'api_code', 'owned_record_unreadable'), name)
    try: validate_job_inventory(jobs)
    except Exception as exc: add(getattr(exc, 'api_code', 'invalid_job_inventory'))
    reasons = verify_records({name: row for name, row in records.items() if row['kind'] != 'job'}, jobs)
    for reason in reasons:
        add(reason['code'], reason['source'].lstrip('/'), category='warning' if reason.get('severity') == 'warning' else 'error')
    for name, record in records.items():
        data, kind = record['data'], record['kind']
        # A deleted historical owner is evidence, never an active join or an
        # automatic cleanup request. Legacy records remain visibly unassigned.
        rows = [data]
        for field in ('runs', 'deliveries', 'observations'):
            value = data.get(field)
            if isinstance(value, list): rows.extend(row for row in value if isinstance(row, dict))
        for row in rows:
            if kind in HISTORY and row.get('job_id') and row['job_id'] not in jobs:
                add('deleted_job_history_preserved', name.lstrip('/'), row['job_id'], 'history')
            elif kind in HISTORY and (row.get('identity_state') == 'unassigned' or row.get('legacy_job_key') or row.get('job_key') or row.get('backup_type')) and not row.get('job_id'):
                add('unresolved_legacy_history', name.lstrip('/'), category='history')
            if kind == 'control' and row.get('finished') is True and row.get('job_id') not in jobs:
                add('orphan_terminal_control', name.lstrip('/'), row.get('job_id'), 'cleanup_candidate')
    return {'ok': not any(row['category'] == 'error' for row in findings), 'findings': findings[:limit],
            'total': len(findings), 'truncated': len(findings) > limit,
            'jobs': [{'job_id': j, 'name': row['name'][:160], 'repository_key': row['repository_key']} for j, row in list(jobs.items())[:limit]]}


def deletion_plan(config, job_id, confirmed_artifacts=None):
    """Plan exact history removals, requiring matching content digests."""
    validate_job_id(job_id)
    records = read_owned(config)
    validate_records(records)
    artifacts, changes, selected_rows = [], {}, {}
    selected = confirmed_artifacts or []
    if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
        raise ValueError('Artifact confirmations must be a list of preview IDs')
    paths = owned_paths(config)
    for name, record in records.items():
        kind, data = record['kind'], record['data']
        if kind not in HISTORY: continue
        if kind in {'status', 'restore_test', 'restore_detail'}:
            rows = [('', data)]
        elif kind == 'notification_state':
            rows = [(key, {'job_id': key.split(':', 2)[1], 'value': val}) for key, val in data.get('last_sent', {}).items() if len(key.split(':', 2)) == 3]
        else:
            field = {'weekly': 'observations', 'restore_index': 'runs', 'notification_deliveries': 'deliveries'}[kind]
            rows = [(str(i), row) for i, row in enumerate(data.get(field, []))]
        for locator, row in rows:
            if row.get('job_id') != job_id: continue
            token = record_digest({'file': name, 'locator': locator, 'record': row})
            artifacts.append({'id': token, 'file': name, 'kind': kind, 'job_id': job_id,
                              'run_id': str(row.get('run_id') or row.get('restore_id') or '')[:64]})
            if token not in selected: continue
            target = paths[name][0]
            if not locator and kind in {'status', 'restore_test', 'restore_detail'}:
                changes[target] = None
            elif kind == 'notification_state':
                changes.setdefault(target, deepcopy(data))['last_sent'].pop(locator)
            else:
                after = changes.setdefault(target, deepcopy(data))
                selected_rows.setdefault(target, set()).add(int(locator))
                after[field] = [item for i, item in enumerate(data[field]) if i not in selected_rows[target]]
    if set(selected) - {row['id'] for row in artifacts}:
        raise ValueError('Artifact preview changed; reload before deleting')
    # Restore index/detail are one record pair: require both explicitly.
    next_records = deepcopy(records)
    for name, (path, _) in paths.items():
        if path in changes:
            if changes[path] is None: next_records.pop(name, None)
            else: next_records[name]['data'] = changes[path]
    validate_records(next_records)
    for record in records.values():
        data, kind = record['data'], record['kind']
        if kind in {'notification_queue', 'runtime_recovery', 'restore_runs'}:
            field = {'notification_queue': 'queue', 'runtime_recovery': 'entries', 'restore_runs': 'runs'}[kind]
            rows = data.get(field, [])
            rows = rows.values() if isinstance(rows, dict) else rows
            if any(row.get('job_id') == job_id for row in rows):
                raise ValueError('The job still has pending notifications, runtime recovery or restores; resolve them before deletion')
    return {'artifacts': artifacts, 'changes': changes, 'deleted_count': len(selected)}
