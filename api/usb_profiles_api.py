"""
api/usb_profiles_api.py - USB-Profilverwaltung und Statuschecks.
"""
from __future__ import annotations

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
            item["message"] = "Pfad fehlt"
            results.append(item)
            continue
        p = Path(mount_path)
        item["exists"] = p.exists()
        item["is_dir"] = p.is_dir()
        if not item["exists"]:
            item["message"] = "Pfad nicht gefunden"
            results.append(item)
            continue
        if not item["is_dir"]:
            item["message"] = "Pfad ist kein Verzeichnis"
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
            item["message"] = "Pfad ist nicht gemountet"
            results.append(item)
            continue
        item["ok"] = True
        item["message"] = "OK"
        results.append(item)
    return {"results": results}
