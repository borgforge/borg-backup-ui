"""Canonical restore fixtures with literal archive scope, no implicit migration."""
from uuid import uuid4

JOB_ID = '11111111-1111-4111-8111-111111111111'
OTHER_ID = '22222222-2222-4222-8222-222222222222'
RUN_ID = '33333333-3333-4333-8333-333333333333'


def info(repo='/repo', job_id=JOB_ID, prefix='archive'):
    return {'job_id': job_id, 'repo': repo, 'path': repo, 'location': 'local',
            'repository_key': 'repo-appdata', 'storage_key': 'local', 'storage': {},
            'passphrase_file': None, 'encryption': 'none', 'type': prefix,
            'job': {'job_id': job_id, 'name': 'Photos', 'archive_prefixes': [prefix]},
            'policy': {'mode': 'scheduled', 'level': 1, 'interval_days': 30}}
