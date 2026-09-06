"""Explicit target-model fixture setup, never a production migration (#473)."""

import json
from pathlib import Path
from uuid import uuid4


def canonical_fixture(config):
    """Convert only the synthetic jobs/reverse links/schedules a test supplied.

    This helper is not a migration test or evidence that real data is eligible.
    The dedicated identity planner tests cover actual detection/projection.
    """
    from job_model import new_job_defaults

    root = Path(config["BACKUP_SCRIPTS_DIR"])
    jobs_dir = root / "config" / "jobs"
    ids, jobs = {}, []
    for path in sorted(jobs_dir.glob("*.json")):
        old = json.loads(path.read_text())
        if old.get("schema_version") == 4:
            jobs.append(old)
            continue
        key, typ = old["job_key"], old["backup_type"]
        job_id = str(uuid4())
        meta = new_job_defaults()
        meta.update(old)
        meta.update(schema_version=4, job_id=job_id, legacy_job_keys=[key],
                    archive_prefixes=list(dict.fromkeys([typ + "-backup", *old.get("archive_prefixes", [])])))
        for field in ("job_key", "backup_type", "type_id", "location"):
            meta.pop(field, None)
        (jobs_dir / (job_id + ".json")).write_text(json.dumps(meta))
        path.unlink()
        ids[key] = job_id
        jobs.append(meta)
    repos = root / "config" / "repositories.json"
    if repos.exists():
        data = json.loads(repos.read_text())
        for repo in data["repositories"]:
            repo.pop("used_by", None)
            repo.pop("source_job_keys", None)
            assigned = [j["job_id"] for j in jobs if j["repository_key"] == repo["repository_key"]]
            repo.update(job_ids=assigned, source_job_ids=list(assigned))
        repos.write_text(json.dumps(data))
    schedules = root / "config" / "schedules.json"
    if schedules.exists():
        data = json.loads(schedules.read_text())
        schedules.write_text(json.dumps({ids.get(key, key): value for key, value in data.items()}))
    return ids
