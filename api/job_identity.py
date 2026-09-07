"""Permanent job identity, independent of display and archive naming (#486)."""

from __future__ import annotations

import uuid

JOB_SCHEMA_VERSION = 4


def new_job_id() -> str:
    return str(uuid.uuid4())


def validate_job_id(value: object) -> str:
    value = str(value or "").strip()
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError("Job ID must be a UUID") from exc
    if str(parsed) != value or parsed.int == 0:
        raise ValueError("Job ID must be a canonical, nonempty UUID")
    return value


def metadata_job_id(meta: dict) -> str:
    job_id = validate_job_id(meta.get("job_id"))
    if meta.get("job_key") != job_id:
        raise ValueError("Job ID and job key disagree")
    return job_id
