"""Explicit UUID run fixtures for runtime tests; never convert production jobs."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import os
from uuid import uuid4

JOB_ID = '11111111-1111-4111-8111-111111111111'
RUN_ID = '22222222-2222-4222-8222-222222222222'
OTHER_JOB_ID = '33333333-3333-4333-8333-333333333333'


def write_run_fixture(directory, *, job_id=JOB_ID, run_id=None, file_activity=False):
    from job_model import new_job_defaults
    from job_runs import control_root, log_filename
    run_id = run_id or str(uuid4())
    job = {**new_job_defaults(), 'schema_version':4,'job_id':job_id,'name':'job','archive_prefixes':['files'],
           'legacy_job_keys':[], 'repository_key':'synthetic','source_paths':[str(directory)], 'file_activity':file_activity}
    snapshot = {'schema_version':1,'job_id':job_id,'run_id':run_id,'job_name_snapshot':'job',
                'archive_prefix_snapshot':'files','archive_prefixes_snapshot':['files'],
                'repository_key_snapshot':'synthetic','repository_snapshot':str(directory / 'repo'),
                'location_snapshot':'local','started_at':datetime.now(timezone.utc).isoformat(),
                'file_activity':file_activity,'log_file':str(directory / log_filename(job_id,run_id,'job')),
                'context':{'job':job,'repository_path':str(directory / 'repo'),'location':'local'},'settings':{}}
    path = control_root() / run_id / 'context.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot))
    return snapshot


def job_config_identity(prefix):
    return {'job_id':JOB_ID,'run_id':str(uuid4()),'archive_prefix':prefix,'repository_key':'synthetic'}


def identity_snapshot(name='Synthetic job', job_id=JOB_ID, run_id=RUN_ID):
    return {'job_id':job_id,'run_id':run_id,'job_name_snapshot':name,'archive_prefix_snapshot':'synthetic',
            'archive_prefixes_snapshot':['synthetic'],'repository_key_snapshot':'synthetic',
            'repository_snapshot':'/synthetic/repo','location_snapshot':'local'}
