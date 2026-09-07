"""Permanent job identity, independent of display and archive naming (#486)."""

from __future__ import annotations

import uuid
import re
from pathlib import Path
from datetime import datetime, timezone

JOB_SCHEMA_VERSION = 4


class JobIdConflictError(ValueError):
    api_code = "job_id_exists"
    api_status = 409


def new_job_id(jobs_dir: Path | None = None) -> str:
    for _ in range(100):
        candidate = str(uuid.uuid4())
        if jobs_dir is None or not (jobs_dir / f"{candidate}.json").exists():
            return candidate
    raise JobIdConflictError("Could not generate an unused job ID. Please try again.")


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


def _filename_label(value: str, max_bytes: int, fallback: str) -> str:
    """Readable path component, bounded in UTF-8 without splitting a character."""
    value = re.sub(r"[^\w.-]+", "_", str(value or ""), flags=re.UNICODE)
    # Keep the '--' separator unambiguous even for user-provided job names.
    value = re.sub(r"[-_]{2,}", "_", value).strip("._-")
    return value.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore").rstrip("._-") or fallback


def job_file_component(job_name: str, location: str, job_id: str, *, name_bytes: int = 100) -> str:
    identity = validate_job_id(job_id)
    place = _filename_label(location, 10, "unknown")
    name = _filename_label(job_name, min(100, name_bytes), "Job")
    return f"{name}_{place}_{identity}"


def job_log_filename(job_name: str, location: str, job_id: str, run_label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", run_label):
        raise ValueError("Invalid log run label")
    # Longer activity run identifiers also fit the shared 255-byte limit.
    fixed = f"BBUI-_{_filename_label(location, 10, 'unknown')}_{validate_job_id(job_id)}--{run_label}.log"
    component = job_file_component(job_name, location, job_id, name_bytes=255 - len(fixed.encode("utf-8")))
    return f"BBUI-{component}--{run_label}.log"


def job_run_date_tag(run_id: str = "") -> str:
    """Use the managed run's start time for logs with or without a file list."""
    if re.fullmatch(r"\d{8}T\d{6}Z-[A-Za-z0-9]+", run_id):
        started = datetime.strptime(run_id.split("-", 1)[0], "%Y%m%dT%H%M%SZ")
        return started.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def job_log_paths(directory: Path, job_key: str):
    """Find this job's logs across name changes and previous filename formats."""
    for path in directory.glob("*.log"):
        name = path.name
        if name.startswith(f"Borg-Backup_{job_key}--"):
            yield path
        elif name.startswith("BBUI-"):
            component, separator, _run = name.partition("--")
            if separator and component.endswith(f"_{job_key}"):
                yield path
