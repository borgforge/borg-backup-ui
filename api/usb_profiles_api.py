"""
api/usb_profiles_api.py - USB-Profilverwaltung und Statuschecks.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List


def normalize_usb_profile_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Keep usable USB profiles, assigning unique keys where absent."""
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for idx, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        mount_path = str(row.get("mount_path", "")).strip()
        if not name or not mount_path:
            continue
        key = str(row.get("key", "")).strip().lower()
        if not key:
            key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or f"usb-{idx + 1}"
        while key in seen:
            key = f"{key}-{idx + 1}"
        seen.add(key)
        out.append({"key": key, "name": name, "mount_path": mount_path})
    return out


def get_usb_profile_job_refs(ui_config: dict) -> Dict[str, List[str]]:
    from repository_context import profile_job_references
    return profile_job_references(ui_config, "usb")


def validate_usb_profile_usage_before_save(ui_config: dict, next_rows: List[Dict[str, str]]) -> None:
    """Reject removal or incomplete edits of USB profiles still used by jobs.

    Raises ValueError naming the affected profile and missing fields.
    """
    refs = get_usb_profile_job_refs(ui_config)
    next_by_key = {
        str(r.get("key") or "").strip().lower(): r
        for r in next_rows
        if str(r.get("key") or "").strip()
    }
    for key, jobs in refs.items():
        if not jobs:
            continue
        row = next_by_key.get(key)
        if row is None:
            raise ValueError(
                f"USB profile '{key}' cannot be removed because it is still used by {len(jobs)} job(s)."
            )
        missing = [
            label for field, label in (
                ("name", "Name"),
                ("mount_path", "mount path"),
            )
            if not str(row.get(field) or "").strip()
        ]
        if missing:
            raise ValueError(
                f"USB profile '{key}' is still used by {len(jobs)} job(s) and cannot be saved incomplete. "
                f"Missing: {', '.join(missing)}."
            )


def test_usb_profiles_status(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Use the same read-only USB storage preflight as backup startup."""
    from dataclasses import asdict
    from lib.usb_storage import inspect_usb_storage

    messages = {
        "ok": "OK", "not_found": "Path not found", "not_directory": "Path is not a directory",
        "invalid_path": "Path must be absolute", "not_mounted": "USB drive is not mounted",
        "outside_mount": "Path resolves outside its storage mount", "not_writable": "USB storage is not writable",
    }
    results: List[Dict[str, Any]] = []
    for row in profiles or []:
        name = str((row or {}).get("name", "")).strip()
        mount_path = str((row or {}).get("mount_path", "")).strip()
        key = str((row or {}).get("key", "")).strip()
        item = {
            "key": key,
            "name": name,
            "mount_path": mount_path,
            "ok": False,
            "exists": False,
            "is_dir": False,
            "is_mounted": False,
            "writable": False,
            "detected_mount": "",
            "code": "invalid_path",
            "message": "",
        }
        if not mount_path:
            item["message"] = "Path is missing"
            results.append(item)
            continue
        try:
            status = inspect_usb_storage(Path(mount_path))
            item.update(asdict(status), ok=status.ok, message=messages[status.code])
        except OSError as exc:
            item.update(code="access_error", message=f"USB storage check failed: {exc}")
        results.append(item)
    return {"results": results}
