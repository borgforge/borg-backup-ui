"""
api/storage_profiles_api.py - Storagebox/SSH-Profilverwaltung.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


def normalize_storage_base_path(raw: str) -> str:
    base = str(raw or "").strip()
    if not base:
        return "/./backup"
    if base.startswith("./"):
        return base
    if base.startswith("/./"):
        return base
    if "://" in base:
        return base
    if not base.startswith("/"):
        base = "/" + base
    if base != "/":
        base = base.rstrip("/")
    return base or "/./backup"


def storage_repo_base_path_for_uri(raw: str) -> str:
    base = str(raw or "").strip() or "/./backup"
    if base.startswith("./"):
        base = f"/{base}"
    elif not base.startswith("/"):
        base = f"/{base}"
    if base != "/":
        base = base.rstrip("/")
    return base or "/./backup"


def build_storage_repo_uri(profile: Dict[str, Any], type_id: str) -> str:
    user = str(profile.get("user") or "").strip()
    host = str(profile.get("host") or "").strip()
    port = str(profile.get("port") or "23").strip() or "23"
    base_path = storage_repo_base_path_for_uri(str(profile.get("base_path") or "/./backup"))
    type_part = re.sub(r"[^a-z0-9_]+", "-", str(type_id or "").strip().lower()).strip("-_")
    if not type_part:
        type_part = "job"
    if not user or not host:
        return ""
    return f"ssh://{user}@{host}:{port}{base_path}/borg-backup-{type_part}"


def normalize_storage_profile_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for idx, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key", "")).strip().lower()
        name = str(row.get("name", "")).strip()
        host = str(row.get("host", "")).strip()
        user = str(row.get("user", "")).strip()
        if not name and not key:
            continue
        if not key:
            key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or f"storage-{idx + 1}"
        if not name:
            name = key
        while key in seen:
            key = f"{key}-{idx + 1}"
        seen.add(key)
        port = str(row.get("port", "23")).strip() or "23"
        base_path = normalize_storage_base_path(str(row.get("base_path", "/./backup")))
        target_type = str(row.get("target_type", "storagebox")).strip().lower() or "storagebox"
        ssh_key_path = str(row.get("ssh_key_path", "")).strip()
        out.append({
            "key": key,
            "name": name,
            "host": host,
            "port": port,
            "user": user,
            "base_path": base_path,
            "target_type": target_type,
            "ssh_key_path": ssh_key_path,
        })
    return out


def get_storage_profile_job_refs(ui_config: dict) -> Dict[str, List[str]]:
    from jobs_api import get_jobs_meta_dirs, resolve_data_root, resolve_scripts_dir

    scripts_dir = resolve_scripts_dir(ui_config)
    data_root = resolve_data_root(ui_config)
    refs: Dict[str, List[str]] = {}
    for meta_dir in get_jobs_meta_dirs(scripts_dir, data_root):
        if not meta_dir.is_dir():
            continue
        for meta_file in sorted(meta_dir.glob("*.json")):
            try:
                raw = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(raw.get("location") or "").strip().lower() != "storagebox":
                continue
            key = str(raw.get("storage_profile_key") or "").strip().lower()
            if not key:
                continue
            job_key = str(raw.get("job_key") or meta_file.stem).strip()
            name = str(raw.get("name") or "").strip()
            label = f"{job_key} ({name})" if name else job_key
            refs.setdefault(key, []).append(label)
    return refs


def validate_storage_profile_usage_before_save(ui_config: dict, next_rows: List[Dict[str, str]]) -> None:
    refs = get_storage_profile_job_refs(ui_config)
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
                f"Storage profile '{key}' cannot be removed because it is still used by {len(jobs)} job(s)."
            )
        missing = [
            label for field, label in (
                ("host", "Host"),
                ("user", "user"),
                ("base_path", "base path"),
            )
            if not str(row.get(field) or "").strip()
        ]
        if missing:
            raise ValueError(
                f"Storage profile '{key}' is still used by {len(jobs)} job(s) and cannot be saved incomplete. "
                f"Missing: {', '.join(missing)}."
            )


def validate_storage_profiles_complete_before_save(next_rows: List[Dict[str, str]]) -> None:
    for row in next_rows or []:
        key = str(row.get("key") or "").strip() or str(row.get("name") or "").strip() or "unknown"
        missing = [
            label for field, label in (
                ("name", "Name"),
                ("host", "Host"),
                ("user", "user"),
                ("base_path", "base path"),
            )
            if not str(row.get(field) or "").strip()
        ]
        if missing:
            raise ValueError(
                f"Storage profile '{key}' is incomplete. Missing: {', '.join(missing)}."
            )


def resolve_storage_profile(ui_config: dict, profile_key: str = "") -> dict:
    from config_api import ensure_settings_migrated

    settings_payload = ensure_settings_migrated(ui_config)
    rows = normalize_storage_profile_rows(
        settings_payload.get("storage_profiles") if isinstance(settings_payload.get("storage_profiles"), list) else []
    )
    if not rows:
        return {}
    wanted = str(profile_key or "").strip().lower()
    if wanted:
        for row in rows:
            if str(row.get("key", "")).strip().lower() == wanted:
                return row
    return rows[0]
