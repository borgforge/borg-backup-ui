"""Repair proven, untouched presentation after immutable-ID migration (#479).

The original approved plan and snapshot remain read-only. A cosmetic repair
never guesses from a current name/prefix or requires removed recovery material.
"""
from copy import deepcopy
import hashlib

from inventory_store import atomic_write_bytes, inventory_lock
from job_model import validate_job, validate_job_id
from job_presentation import legacy_presentation_defaults
from migration_barrier import quiescence_held

from . import identity_storage as storage, immutable_job_id_v1 as identity
from .audit import append_event, config_dir

MIGRATION_ID = 'job_presentation_v1'
INTRODUCED_IN = 'issue-447-479'


def _fingerprint(raw, mode):
    return {'exists': True, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'mode': mode}


def _evidence(config):
    from identity_migration_api import IdentityMigrationAssistant
    assistant = IdentityMigrationAssistant(config)
    state = assistant._state_dir()
    if state is None:
        return None
    assistant._validate_state_layout(state)
    meta = assistant._meta(state)
    if not meta or meta['stage'] != 'complete' or meta['status'] != 'applied' or not meta['acknowledged']:
        return None
    plan = storage.load_plan(state)
    journal = storage.read_journal(state)
    if (not journal or journal[-1]['phase'] != 'commit' or journal[-1]['status'] != 'applied'
            or meta.get('plan_id') != plan['plan_id']):
        return None
    handle, manifest = assistant._snapshot(state, plan)
    if handle['digest'] != meta.get('snapshot_digest'):
        return None
    recovery = assistant._validate_location(state.parent / ('.job-presentation-v1-' + plan['plan_id'][:16]))
    return state, plan, manifest, recovery


def _candidates(config, evidence):
    state, plan, manifest, recovery = evidence
    targets = {row['target']: row for row in plan['actions'] if row.get('kind') == 'write_json'}
    jobs_dir = config_dir(config) / 'jobs'
    candidates, skipped = [], []
    for job_id, planned in sorted(plan['jobs'].items()):
        validate_job_id(job_id)
        source = plan['job_sources'][job_id]
        original_entry = manifest['entries'][source]
        _, raw = storage._read_file(state / 'snapshot/files' / original_entry['blob'], private=True)
        if _fingerprint(raw, original_entry['original']['mode']) != original_entry['original']:
            storage._fail('snapshot_changed')
        original = identity._strict_json(raw, source)
        defaults = legacy_presentation_defaults(original) if original.get('schema_version') in {1, 2, 3} else {}
        updates = {key: value for key, value in defaults.items() if not str(planned.get(key) or '').strip()}
        path = jobs_dir / (job_id + '.json')
        reason = 'explicit_or_unchanged_presentation' if not defaults else 'already_preserved'
        if updates:
            action = targets.get(str(path))
            if not action or action.get('source') != source or action.get('data') != planned:
                storage._fail('invalid_plan')
            before = identity.encode_target_json(planned)
            if _fingerprint(before, action['after']['mode']) != action['after']:
                storage._fail('invalid_plan')
            corrected = {**deepcopy(planned), **updates}
            validate_job(corrected, filename=path.name)
            after = identity.encode_target_json(corrected)
            candidates.append({'job_id': job_id, 'path': path, 'updates': updates,
                'before': before, 'after': after, 'before_fp': action['after'],
                'after_fp': _fingerprint(after, action['after']['mode'])})
            continue
        skipped.append({'job_id': job_id, 'reason': reason})
    return candidates, skipped


def detect(config):
    # Only the registry writes audit/state. No recovery paths are created here.
    from identity_migration_api import IdentityMigrationAssistant
    exists = storage.fingerprint_file(IdentityMigrationAssistant(config).selector)['exists']
    return {'required': exists, 'reason': 'inspect_original_presentation' if exists else 'no_identity_migration'}


def _result(config, status, *, actions=None, skipped=None, **details):
    details = {'actions': actions or [], 'skipped': skipped or [], **details}
    append_event(config, {'event': 'migration_' + status, 'migration_id': MIGRATION_ID,
        'status': status, 'details': details})
    return {'migration_id': MIGRATION_ID, 'status': status, 'details': details}


def apply(config):
    if not quiescence_held(config):
        return {'migration_id': MIGRATION_ID, 'status': 'failed', 'details': {
            'error_type': 'PresentationRepairError', 'error': 'exclusive_migration_required', 'failed_phase': 'apply'}}
    with inventory_lock(config_dir(config)):
        # Recovery evidence is optional for cosmetic repair. Missing/corrupt
        # evidence must never block an otherwise healthy installation.
        try:
            evidence = _evidence(config)
            if evidence is None:
                return _result(config, 'skipped', reason='original_recovery_unavailable')
            candidates, skipped = _candidates(config, evidence)
        except Exception:
            return _result(config, 'skipped', reason='original_recovery_unavailable')
        recovery = evidence[3]
        actions, changed = [], []
        try:
            for item in candidates:
                current = storage.fingerprint_file(item['path'])
                backup = recovery / (item['job_id'] + '.json')
                if current == item['after_fp']:
                    # Only our exact verified before-copy establishes a prior
                    # interrupted repair; otherwise this is a user's change.
                    try:
                        _, saved = storage._read_file(backup, private=True)
                    except Exception:
                        saved = None
                    if saved == item['before']:
                        actions.append({'job_id': item['job_id'], 'action': 'already_applied'})
                        continue
                if current != item['before_fp']:
                    skipped.append({'job_id': item['job_id'], 'reason': 'changed_since_identity_migration'})
                    continue
                # Dedicated private persistent storage, never the Unraid FAT
                # config volume and never a new file in the approved snapshot.
                try:
                    storage._private_directory(recovery, create=True)
                    storage._publish_once(backup, item['before'])
                    _, saved = storage._read_file(backup, private=True)
                    if saved != item['before']:
                        storage._fail('snapshot_changed')
                except Exception:
                    skipped.append({'job_id': item['job_id'], 'reason': 'private_recovery_unavailable'})
                    continue
                event = {'job_id': item['job_id'], 'action': 'materialize_automatic_presentation',
                    'appearance': item['updates'], 'path': str(item['path']), 'backup': str(backup),
                    'before_sha256': item['before_fp']['sha256'], 'after_sha256': item['after_fp']['sha256']}
                append_event(config, {'event': 'migration_job_pending', 'migration_id': MIGRATION_ID,
                    'status': 'pending', 'details': event})
                if storage.fingerprint_file(item['path']) != item['before_fp']:
                    storage._fail('input_changed')
                changed.append(item)
                atomic_write_bytes(item['path'], item['after'], mode=item['after_fp']['mode'])
                if storage.fingerprint_file(item['path']) != item['after_fp']:
                    storage._fail('verification_failed')
                actions.append(event)
            return _result(config, 'applied' if actions else 'skipped', actions=actions, skipped=skipped)
        except Exception as exc:
            rollback = []
            for item in reversed(changed):
                try:
                    current = storage.fingerprint_file(item['path'])
                    if current == item['after_fp']:
                        _, saved = storage._read_file(recovery / (item['job_id'] + '.json'), private=True)
                        if saved != item['before']:
                            storage._fail('snapshot_changed')
                        atomic_write_bytes(item['path'], saved, mode=item['before_fp']['mode'])
                    if storage.fingerprint_file(item['path']) != item['before_fp']:
                        storage._fail('input_changed')
                    rollback.append({'job_id': item['job_id'], 'status': 'restored'})
                except Exception:
                    rollback.append({'job_id': item['job_id'], 'status': 'failed'})
            return _result(config, 'failed', actions=actions, skipped=skipped,
                error_type=type(exc).__name__, error='job_presentation_write_failed',
                failed_phase='apply', rollback=rollback)
