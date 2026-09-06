"""Bounded v2 import boundary; no live inventory matching or writes (#478).

Preview allocates temporary source selectors once. The client returns this map
for apply. Destination job IDs are independently allocated by the v3 importer.
The inactive migration's pure metadata projection is reused, never its planner,
snapshot, journal or installer. Source-host cache paths are not imported.
"""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from job_model import validate_job_id, validate_job
from job_transfer import FORMAT, indexed, reference_map, validate_bundle, fail


def convert_legacy_bundle(config, bundle, source_ids=None):
    if not isinstance(bundle, dict) or bundle.get('format') != 'bbui-job-bundle-v2':
        return bundle, {}
    from migrations.immutable_job_id_v1 import _validate_job, _operational_defaults, _prefixes
    from config_api import read_expanded_conf
    from repository_context import LEGACY_JOB_REPOSITORY_FIELDS
    source = indexed(bundle.get('jobs'), 'job_key')
    selectors = {key: str(uuid4()) for key in source} if source_ids is None else source_ids
    if not isinstance(selectors, dict) or set(selectors) != set(source):
        fail('invalid_legacy_transfer_selection', 'The legacy source selection map is incomplete')
    for value in selectors.values(): validate_job_id(value)
    if len(set(selectors.values())) != len(selectors):
        fail('invalid_legacy_transfer_selection', 'Legacy source selectors must be unique')
    converted = []
    defaults = read_expanded_conf(config)
    for key, raw in source.items():
        if raw.get('schema_version') not in {1, 2, 3}:
            fail('unsupported_legacy_bundle', 'Only known legacy job schemas can be converted')
        label = '/bundle/' + key + '.json'
        _validate_job(raw, label)
        job = _operational_defaults(raw, defaults, label)
        job['archive_prefixes'] = _prefixes(raw, True, label)
        for field in {'job_key', 'backup_type', 'type_id', 'location', 'cache_reference', *LEGACY_JOB_REPOSITORY_FIELDS}:
            job.pop(field, None)
        job.update(schema_version=4, job_id=selectors[key], legacy_job_keys=[])
        validate_job(job)
        converted.append(job)
    repositories = indexed(bundle.get('repositories'), 'repository_key')
    storages = indexed(bundle.get('storages'), 'storage_key')
    selected_repos = {row['repository_key'] for row in converted}
    if selected_repos - repositories.keys():
        fail('invalid_legacy_bundle', 'The legacy bundle lacks canonical repository objects')
    repos = []
    for key in sorted(selected_repos):
        row = repositories[key]
        expected = {old for old, job in source.items() if job['repository_key'] == key}
        for old, new in (('used_by', 'job_ids'), ('source_job_keys', 'source_job_ids')):
            if old in row:
                values = row.pop(old)
                if not isinstance(values, list) or any(not isinstance(value, str) for value in values) or len(set(values)) != len(values) or set(values) & source.keys() != expected:
                    fail('invalid_legacy_references', 'Legacy repository assignments are inconsistent')
            elif new in row:
                fail('invalid_legacy_references', 'A v2 bundle must not mix canonical and legacy assignments')
            row[new] = [selectors[value] for value in source if value in expected]
        repos.append(row)
    schedules = bundle.get('schedules', {})
    if not isinstance(schedules, dict) or set(schedules) - source.keys() - {'restore_test'}:
        fail('invalid_legacy_references', 'A legacy schedule has no source job in the bundle')
    storage_keys = {row['storage_key'] for row in repos}
    if storage_keys - storages.keys(): fail('invalid_legacy_bundle', 'A legacy storage dependency is missing')
    # Old v2 exports also contained unrelated profiles/service schedules. These
    # are outside the explicitly selected job scope and never replace settings.
    result = {'format': FORMAT, 'jobs': converted, 'repositories': repos,
              'storages': [row for key, row in storages.items() if key in storage_keys],
              'schedules': {selectors[key]: {**row, 'enabled': row.get('enabled', True)} for key, row in schedules.items() if key in source},
              'passphrase_meta': {key: {'exists': bool(row.get('exists'))} for key, row in bundle.get('passphrase_meta', {}).items() if key in selected_repos}}
    result['references'] = reference_map(result)
    validate_bundle(result)
    return result, deepcopy(selectors)
