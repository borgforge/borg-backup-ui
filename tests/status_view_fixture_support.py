"""Synthetic canonical identities for legacy presentation regression fixtures."""
import hashlib
import json
from pathlib import Path
from uuid import UUID


def job_id_for(label):
    return str(UUID(bytes=hashlib.sha256(label.encode()).digest()[:16], version=4))


def write_job(root, label, *, name='', location='local'):
    from job_model import new_job_defaults
    root = Path(root)
    job_id = job_id_for(label)
    config_dir = root / 'config'
    (config_dir / 'jobs').mkdir(parents=True, exist_ok=True)
    repo_key = 'repo_' + label
    job = {**new_job_defaults(), 'job_id':job_id, 'name':name or label,
           'source_paths':[str(root)], 'repository_key':repo_key, 'archive_prefixes':[label]}
    (config_dir / 'jobs' / (job_id + '.json')).write_text(json.dumps(job))
    path = config_dir / 'repositories.json'
    store = json.loads(path.read_text()) if path.exists() else {'schema_version':1,'repositories':[]}
    store['repositories'] = [row for row in store['repositories'] if row['repository_key'] != repo_key]
    store['repositories'].append({'repository_key':repo_key,'storage_key':location,'relative_path':label,
                                 'encryption':'none','job_ids':[job_id],'source_job_ids':[job_id]})
    path.write_text(json.dumps(store))
    from storage_objects_api import write_storage_store
    storages=[]
    for loc in ('local','usb','smb','storagebox'):
        storages.append({'storage_key':loc,'storage_type':'ssh' if loc=='storagebox' else loc,
                         'location':loc,'base_path':str(root / 'repos' / loc),'mount_path':str(root / 'repos' / loc),
                         'host':'example.invalid','user':'synthetic','server':'example.invalid','share':'synthetic',
                         'username':'synthetic'})
    write_storage_store({'BACKUP_SCRIPTS_DIR':str(root)}, {'storages':storages})
    return job_id


def status_identity(root, label, name='', location='local'):
    return {'job_id':job_id_for(label),'job_name_snapshot':name or label,
            'archive_prefix_snapshot':label,'repository_key_snapshot':'repo_'+label,
            'repository_snapshot':str(Path(root) / 'repos' / location / label),
            'location_snapshot':location}
