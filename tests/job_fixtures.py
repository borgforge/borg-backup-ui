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
    result.update(job_id=key, job_key=key, schema_version=4)
    result.setdefault("archive_prefix", result["backup_type"] + "-backup")
    result.setdefault("archive_prefixes", [result["archive_prefix"]])
    result.setdefault("cache_subdir", result["location"] + "_" + result["backup_type"].lower())
    result.setdefault("check_flag_name", ".last_check_" + result["backup_type"].lower())
    return result
