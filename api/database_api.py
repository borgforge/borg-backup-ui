"""Asynchronous administrator actions for managed database backups (#591)."""
from __future__ import annotations
import json
import os
import stat
import threading
import uuid
from pathlib import Path

from database_profiles import DatabaseError, data_root, snapshot_profiles, list_profiles
from database_backup import export_profiles, reconcile_operations, open_staging, _descriptor_path, open_dump_directory, open_dump_file, cleanup_run, is_run_directory_name, utc_now, discover_databases, close_results
from inventory_store import atomic_write_json

_active = {}
_live_progress = {}
_guard = threading.Lock()


def _state_path(config, identifier):
    import re
    if not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise DatabaseError('invalid_operation')
    return data_root(config) / 'database-tests' / (identifier + '.json')


def operation_status(config, identifier):
    """Return durable status plus in-memory telemetry; detect workers lost on restart."""
    result = json.loads(_state_path(config, identifier).read_text())
    with _guard:
        active = identifier in _active
        progress = dict(_live_progress.get(identifier, {}))
    if progress:
        result['progress'] = progress
    if result['status'] == 'running' and not active:
        result.update(status='interrupted', error_code='database_unresolved_export')
    return result


def cancel_operation(config, identifier):
    """Request cancellation; the worker confirms container termination before completion."""
    _state_path(config, identifier)
    with _guard:
        event = _active.get(identifier)
        if event:
            event.set()
    return operation_status(config, identifier)


def start_operation(config, payload):
    """Start a bounded check/export/cleanup worker using the existing Docker resource lock."""
    from wizard_runner import ResourceLockSet
    from jobs_api import resolve_resource_lock_dir
    action = payload.get('action')
    if action not in ('discover', 'check', 'dump', 'cleanup', 'reconcile'):
        raise DatabaseError('invalid_operation')
    profiles = snapshot_profiles(config, [payload.get('profile_id')], allow_disabled=action != 'dump', require_databases=action == 'dump')
    profile = profiles[0]
    identifier = uuid.uuid4().hex
    event = threading.Event()
    state = {'id': identifier, 'profile_id': profile['id'], 'action': action, 'profile_name': profile['name'], 'status': 'running', 'started_at': utc_now()}
    path = _state_path(config, identifier)
    locks = ResourceLockSet(resolve_resource_lock_dir(config),
                            job_key='database-test-' + identifier, operation='database-test', run_id=identifier)
    ok, _ = locks.acquire(['docker-control'])
    if not ok:
        raise DatabaseError('busy')
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        atomic_write_json(path, state)
        with _guard:
            _active[identifier] = event
            _live_progress[identifier] = {'phase':'preparing', 'processed_bytes':0, 'written_bytes':0}
    except BaseException:
        locks.release()
        raise

    def publish_progress(value):
        """Publish content-free measurements in memory; never rewrite boot status per chunk."""
        with _guard:
            _live_progress[identifier] = dict(value)

    def worker():
        """Own locks through termination/reconciliation and persist only safe diagnostics."""
        try:
            reconcile_operations(config)
            if action in ('discover', 'check'):
                state['databases'] = discover_databases(config, profile, event.is_set)
            elif action == 'dump':
                state['results'] = []
                export_profiles(config, profiles, 'test', identifier, event.is_set, results=state['results'], live_progress=publish_progress)
            elif action == 'cleanup':
                # Successful reconciliation under docker-control proves no exporter remains.
                cleanup_run(Path(str(payload.get('directory', ''))), profile, interrupted=True)
            state['status'] = 'completed'
        except DatabaseError as exc:
            state.update(status='cancelled' if exc.reason == 'cancelled' else 'failed', error_code=exc.api_code)
        except Exception:
            state.update(status='failed', error_code='database_operation_failed')
        finally:
            with _guard:
                state['progress'] = dict(_live_progress.get(identifier, {}))
            close_results(state.get('results', []))
            state['finished_at'] = utc_now()
            try:
                locks.release()
            finally:
                try:
                    atomic_write_json(path, state)
                finally:
                    with _guard:
                        _active.pop(identifier, None)
                        _live_progress.pop(identifier, None)
    try:
        threading.Thread(target=worker, name='database-' + identifier, daemon=True).start()
    except BaseException:
        locks.release()
        with _guard:
            _active.pop(identifier, None)
            _live_progress.pop(identifier, None)
        raise
    return state.copy()


def _run_origin(manifest):
    """Classify existing dump provenance without inferring it from archive success.

    Manual exports use the explicit test sentinel; canonical job UUIDs remain
    attributable even after job deletion. Missing/invalid legacy identities are
    reported as unknown. No manifests are changed.
    """
    from job_identity import validate_job_id
    identifier = manifest.get('job_id')
    if identifier == 'test':
        return {'origin': 'manual', 'job_id': ''}
    try:
        return {'origin': 'job', 'job_id': validate_job_id(identifier)}
    except (ValueError, TypeError, AttributeError):
        return {'origin': 'unknown', 'job_id': ''}


def retained_runs(config):
    """List dumps with normal Unraid permissions through held directory handles.

    Listing never creates paths or changes owners/modes. Unavailable locations
    include their profile name and configured path for actionable UI diagnostics.
    Each row includes origin (job/manual/unknown) and a validated job_id, or an
    empty string. Old manifests remain readable and are never rewritten.
    """
    rows, errors = [], []
    for profile in list_profiles(config)['profiles']:
        try:
            with open_staging(profile, require_space=False) as fd:
                for name in sorted(name for name in os.listdir(fd) if is_run_directory_name(name))[-500:]:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if not stat.S_ISDIR(info.st_mode):
                        continue
                    with open_dump_directory(fd, name) as run_fd:
                        directory = _descriptor_path(run_fd)
                        try:
                            with open_dump_file(directory / 'manifest.json') as handle:
                                row = json.load(handle)
                        except FileNotFoundError:
                            continue
                        if row.get('profile_id') != profile['id']:
                            continue
                        size = 0
                        for child in os.listdir(run_fd):
                            entry = os.stat(child, dir_fd=run_fd, follow_symlinks=False)
                            if stat.S_ISREG(entry.st_mode):
                                size += entry.st_size
                        rows.append({**_run_origin(row), 'profile_id': profile['id'], 'profile_name': row.get('profile_name') or profile['name'],
                                     'compression': row.get('compression', 'none'),
                                     'uncompressed_bytes': sum(f.get('uncompressed_bytes', f.get('bytes', 0)) for f in row.get('files', [])),
                                     'directory': str(Path(profile['staging_dir']) / name), 'status': row.get('status'),
                                     'started_at': row.get('started_at'), 'archived': row.get('archived', False), 'bytes': size})
        except DatabaseError as exc:
            errors.append({'profile_id': profile['id'], 'profile_name': profile['name'],
                           'staging_dir': profile['staging_dir'], 'error_code': exc.api_code})
        except Exception:
            errors.append({'profile_id': profile['id'], 'profile_name': profile['name'],
                           'staging_dir': profile['staging_dir'], 'error_code': 'database_invalid_storage'})
    return {'runs': rows, 'errors': errors}
