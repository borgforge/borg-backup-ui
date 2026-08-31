"""Helpers for Borg archive name prefixes used by wizard jobs."""

import re
from typing import Iterable


_ARCHIVE_PREFIX_RX = re.compile(r"^[A-Za-z0-9_.-]+-backup$")


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
