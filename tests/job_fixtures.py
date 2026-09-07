"""Canonical test jobs with readable labels and deterministic UUIDs (#486).

Legacy migration inputs deliberately do not use this helper.
"""

import uuid


def job_id(label: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "https://example.invalid/test-jobs/" + label))


def identified_job(metadata: dict) -> dict:
    result = dict(metadata)
    key = str(result["job_key"])
    try:
        uuid.UUID(key)
    except ValueError:
        key = job_id(key)
    result.update(job_id=key, job_key=key, schema_version=5)
    result.setdefault("archive_prefix", result["backup_type"] + "-backup")
    result.setdefault("archive_prefixes", [result["archive_prefix"]])
    result.setdefault("cache_subdir", result["location"] + "_" + result["backup_type"].lower())
    result.setdefault("check_flag_name", ".last_check_" + result["backup_type"].lower())
    result.setdefault("compression", "lz4")
    result.setdefault("retention", {"daily": "7", "weekly": "4", "monthly": "6", "yearly": "3"})
    return result


def write_job(root, label, **values):
    """Give status/report fixtures an existing job rather than synthesizing one from history."""
    import json
    from pathlib import Path
    backup_type, location = label.rsplit("_", 1)
    meta = identified_job({"job_key": label, "backup_type": backup_type, "location": location,
                           "name": backup_type, "enabled": True, **values})
    target = Path(root) / "config" / "jobs" / f"{meta['job_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(json.dumps(meta), encoding="utf-8")
    return meta
