"""Canonical source-path handling for wizard jobs."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


JOB_SCHEMA_VERSION = 3


class SourcePathValidationError(ValueError):
    """A job does not contain a valid canonical source-path list."""


def normalize_source_paths(value: Any, *, field: str = "Source paths") -> list[str]:
    """Validate and normalize the canonical JSON-array representation."""
    if not isinstance(value, list):
        raise SourcePathValidationError(f"{field} must be stored as a JSON array")

    normalized_paths: list[str] = []
    seen: set[str] = set()
    for index, raw_path in enumerate(value):
        if not isinstance(raw_path, str):
            raise SourcePathValidationError(f"{field} entry {index + 1} must be a string")
        path = raw_path.strip()
        if not path:
            raise SourcePathValidationError(f"{field} entry {index + 1} must not be empty")
        if any(character in path for character in ("\x00", "\n", "\r")):
            raise SourcePathValidationError(f"{field} entry {index + 1} contains control characters")
        if not Path(path).is_absolute():
            raise SourcePathValidationError(f"{field} entry {index + 1} must be an absolute path: {path}")
        normalized = os.path.normpath(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_paths.append(normalized)

    if not normalized_paths:
        raise SourcePathValidationError(f"{field} must contain at least one path")
    return normalized_paths


def legacy_source_paths_value(job: dict[str, Any]) -> Any:
    """Read the pre-v3 value at an explicit migration/import boundary."""
    if "source_paths" in job:
        return job.get("source_paths")
    paths = job.get("paths") if isinstance(job.get("paths"), dict) else {}
    return paths.get("default")


def convert_legacy_source_paths(value: Any, *, job_key: str) -> list[str]:
    """Convert one legacy value without guessing at ambiguous whitespace."""
    field = f"Job '{job_key}' source_paths"
    if isinstance(value, list):
        return normalize_source_paths(value, field=field)
    if not isinstance(value, str):
        raise SourcePathValidationError(
            f"Job '{job_key}' cannot be migrated: no legacy source path string or source_paths array exists"
        )

    raw = value.strip()
    if not raw:
        raise SourcePathValidationError(f"Job '{job_key}' cannot be migrated: the legacy source path value is empty")
    if "\x00" in raw:
        raise SourcePathValidationError(f"Job '{job_key}' cannot be migrated: the legacy source path contains NUL")

    # Newline-separated values are unambiguous and preserve ordinary spaces.
    if "\n" in raw or "\r" in raw:
        lines = [line.strip() for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
        return normalize_source_paths(lines, field=field)

    # The old UI joined absolute paths with spaces. A whitespace followed by a
    # slash may also occur in an unusual directory name, so missing candidates
    # make the value ambiguous and must not be guessed.
    candidates = [part.strip() for part in re.split(r"\s+(?=/)", raw) if part.strip()]
    if len(candidates) == 1:
        return normalize_source_paths(candidates, field=field)
    # Only access the filesystem for a genuinely ambiguous value. This avoids
    # touching offline USB or network source paths during ordinary migrations.
    if Path(raw).is_dir():
        return normalize_source_paths([raw], field=field)
    normalized = normalize_source_paths(candidates, field=field)
    if len(normalized) > 1:
        missing = [path for path in normalized if not Path(path).is_dir()]
        if missing:
            raise SourcePathValidationError(
                f"Job '{job_key}' cannot be migrated unambiguously: multiple absolute source paths were detected, "
                f"but these directories do not exist: {', '.join(missing)}. "
                "Restore the previous plugin version, correct and save this job, then retry the update."
            )
    return normalized


def upgrade_job_source_paths(job: dict[str, Any], *, job_key: str) -> dict[str, Any]:
    """Return canonical schema-v3 job data for startup migration or import."""
    if not isinstance(job, dict):
        raise SourcePathValidationError(f"Job '{job_key}' cannot be migrated: metadata root is not an object")
    upgraded = dict(job)
    upgraded["source_paths"] = convert_legacy_source_paths(
        legacy_source_paths_value(upgraded),
        job_key=job_key,
    )
    upgraded["schema_version"] = JOB_SCHEMA_VERSION
    upgraded.pop("paths", None)
    return upgraded
