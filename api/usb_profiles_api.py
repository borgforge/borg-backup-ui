"""
api/usb_profiles_api.py - USB-Profilverwaltung und Statuschecks.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List


def normalize_usb_profile_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
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
    from jobs_api import get_jobs_meta_dirs, resolve_data_root, resolve_scripts_dir

    refs: Dict[str, List[str]] = {}
    scripts_dir = resolve_scripts_dir(ui_config)
    data_root = resolve_data_root(ui_config)
    for meta_dir in get_jobs_meta_dirs(scripts_dir, data_root):
        if not meta_dir.is_dir():
            continue
        for meta_file in sorted(meta_dir.glob("*.json")):
            try:
                raw = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(raw.get("location") or "").strip().lower() != "usb":
                continue
            key = str(raw.get("usb_profile_key") or "").strip().lower()
            if not key:
                continue
            job_key = str(raw.get("job_key") or meta_file.stem).strip()
            name = str(raw.get("name") or "").strip()
            label = f"{job_key} ({name})" if name else job_key
            refs.setdefault(key, []).append(label)
    return refs


def validate_usb_profile_usage_before_save(ui_config: dict, next_rows: List[Dict[str, str]]) -> None:
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
    """Prueft USB-Profilpfade auf Existenz, Verzeichnis und Mount-Zustand."""
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
            "message": "",
        }
        if not mount_path:
            item["message"] = "Path is missing"
            results.append(item)
            continue
        p = Path(mount_path)
        item["exists"] = p.exists()
        item["is_dir"] = p.is_dir()
        if not item["exists"]:
            item["message"] = "Path not found"
            results.append(item)
            continue
        if not item["is_dir"]:
            item["message"] = "Path is not a directory"
            results.append(item)
            continue
        mounted = False
        try:
            proc = subprocess.run(
                ["findmnt", "-T", mount_path, "-n", "-o", "TARGET"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            mounted = proc.returncode == 0 and bool((proc.stdout or "").strip())
        except Exception:
            mounted = False
        if not mounted:
            try:
                mounts = Path("/proc/mounts").read_text(encoding="utf-8", errors="ignore").splitlines()
                mp_norm = mount_path.rstrip("/")
                for line in mounts:
                    cols = line.split()
                    if len(cols) < 2:
                        continue
                    tgt = cols[1].rstrip("/")
                    if tgt == mp_norm:
                        mounted = True
                        break
            except Exception:
                mounted = False
        item["is_mounted"] = mounted
        if not mounted:
            item["message"] = "Path is not mounted"
            results.append(item)
            continue
        item["ok"] = True
        item["message"] = "OK"
        results.append(item)
    return {"results": results}
