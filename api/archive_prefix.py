"""Helpers for Borg archive name prefixes used by wizard jobs."""

import re
from typing import Iterable


_ARCHIVE_PREFIX_RX = re.compile(r"^[A-Za-z0-9_.-]+$")


def validate_archive_prefix(value: object) -> str:
    prefix = str(value or "").strip()
    if not prefix or not _ARCHIVE_PREFIX_RX.fullmatch(prefix):
        raise ValueError("Archive prefix may contain only letters, digits, dots, underscores and hyphens")
    return prefix


def archive_prefix_from_metadata(meta: dict) -> str:
    return validate_archive_prefix(meta.get("archive_prefix"))


def job_archive_prefixes(meta: dict) -> list[str]:
    return list(dict.fromkeys([
        archive_prefix_from_metadata(meta),
        *(validate_archive_prefix(value) for value in meta.get("archive_prefixes", [])),
    ]))


def validate_prefix_ownership(candidate: dict, other_jobs: Iterable[dict]) -> None:
    """A Borg '<prefix>-*' selection belongs to one job per repository."""
    prefixes = job_archive_prefixes(candidate)
    for other in other_jobs:
        if other.get("job_id") == candidate.get("job_id"):
            continue
        if other.get("repository_key") != candidate.get("repository_key"):
            continue
        for prefix in prefixes:
            for owned in job_archive_prefixes(other):
                if prefix == owned or prefix.startswith(owned + "-") or owned.startswith(prefix + "-"):
                    raise ValueError(
                        f"Archive prefix '{prefix}' overlaps with '{owned}' of job "
                        f"'{other.get('name') or other.get('job_id')}' in the selected repository"
                    )


def archive_prefix_from_backup_type(backup_type: str) -> str:
    backup_type = str(backup_type or "").strip()
    return f"{backup_type}-backup" if backup_type else ""


def archive_prefix_from_job_key(job_key: str) -> str:
    """Return the archive prefix used by wizard jobs, e.g. appdata-backup."""
    key = str(job_key or "").strip()
    for location in ("storagebox", "local", "usb", "smb"):
        suffix = f"_{location}"
        if key.endswith(suffix):
            return archive_prefix_from_backup_type(key[: -len(suffix)])
    backup_type = key.rsplit("_", 1)[0] if "_" in key else key
    return archive_prefix_from_backup_type(backup_type)


def normalize_archive_prefixes(prefixes: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in prefixes:
        prefix = str(raw or "").strip()
        if not prefix or prefix in seen or not _ARCHIVE_PREFIX_RX.fullmatch(prefix):
            continue
        seen.add(prefix)
        out.append(prefix)
    return out
