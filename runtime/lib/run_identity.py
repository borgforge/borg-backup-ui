"""Stable run correlation shared by runtime records (#475)."""

import re
from uuid import UUID


SNAPSHOT_FIELDS = (
    "job_id", "run_id", "job_name_snapshot", "archive_prefix_snapshot",
    "archive_prefixes_snapshot", "repository_key_snapshot",
    "repository_snapshot", "location_snapshot",
)


def valid_uuid(value):
    try:
        parsed = UUID(value) if isinstance(value, str) else None
        return parsed is not None and parsed.version == 4 and str(parsed) == value
    except ValueError:
        return False


def require_identity(job_id, run_id):
    if not valid_uuid(job_id) or not valid_uuid(run_id):
        raise ValueError("Canonical UUIDv4 job_id and run_id are required")


def filename_stem(job_id, run_id, name):
    require_identity(job_id, run_id)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name)).strip(".-_")[:48] or "job"
    return f"{slug}_{job_id[:8]}--{run_id}"
