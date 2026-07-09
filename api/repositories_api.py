"""Repository object inventory for Borg Backup UI.

Repository objects are UI metadata only. They do not create, modify, or delete
Borg repositories on disk or remote targets.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _data_root(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    return base.parent if base.name == "scripts" else base


def repositories_file(config: dict) -> Path:
    return _data_root(config) / "config" / "repositories.json"


def _slug(value: str, fallback: str = "repository") -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text or fallback


def _repo_identity(path_or_uri: str) -> str:
    text = str(path_or_uri or "").strip()
    if not text:
        return ""
    if "://" in text:
        return text.rstrip("/")
    return text.rstrip("/")


def _unique_repository_key(base_key: str, existing: dict[str, dict[str, Any]], identity: str) -> str:
    base = _slug(base_key, "repo")
    current = existing.get(base)
    if not current or _repo_identity(current.get("repo_uri") or current.get("repo_path") or current.get("path_raw")) == identity:
        return base
    idx = 2
    while True:
        candidate = f"{base}_{idx}"
        current = existing.get(candidate)
        if not current or _repo_identity(current.get("repo_uri") or current.get("repo_path") or current.get("path_raw")) == identity:
            return candidate
        idx += 1


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def read_repository_store(config: dict) -> dict[str, Any]:
    payload = _read_json_file(repositories_file(config))
    rows = payload.get("repositories") if isinstance(payload.get("repositories"), list) else []
    normalized = normalize_repositories(rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": str(payload.get("updated_at") or ""),
        "repositories": normalized,
    }


def write_repository_store(config: dict, store: dict[str, Any]) -> None:
    path = repositories_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now(),
        "repositories": normalize_repositories(store.get("repositories") if isinstance(store, dict) else []),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_repositories(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        key = _slug(str(row.get("repository_key") or row.get("key") or ""), "")
        path_raw = str(row.get("path_raw") or row.get("repo_uri") or row.get("repo_path") or "").strip()
        if not key or not path_raw or key in seen:
            continue
        seen.add(key)
        location = str(row.get("location") or row.get("storage_type") or "").strip().lower()
        source_job_keys = row.get("source_job_keys") if isinstance(row.get("source_job_keys"), list) else []
        source_job_keys = [str(item).strip() for item in source_job_keys if str(item).strip()]
        used_by = row.get("used_by") if isinstance(row.get("used_by"), list) else source_job_keys
        used_by = [str(item).strip() for item in used_by if str(item).strip()]
        repo_uri = str(row.get("repo_uri") or "").strip()
        repo_path = str(row.get("repo_path") or "").strip()
        if "://" in path_raw and not repo_uri:
            repo_uri = path_raw
        if "://" not in path_raw and not repo_path:
            repo_path = path_raw
        out.append({
            "repository_key": key,
            "display_name": str(row.get("display_name") or key).strip() or key,
            "backup_type": str(row.get("backup_type") or "").strip().lower(),
            "location": location,
            "storage_type": str(row.get("storage_type") or location).strip().lower(),
            "storage_key": str(row.get("storage_key") or location).strip(),
            "storage_profile_key": str(row.get("storage_profile_key") or "").strip(),
            "usb_profile_key": str(row.get("usb_profile_key") or "").strip(),
            "smb_profile_key": str(row.get("smb_profile_key") or "").strip(),
            "repo_conf_key": str(row.get("repo_conf_key") or row.get("conf_key") or "").strip(),
            "repo_path": repo_path,
            "repo_uri": repo_uri,
            "path_raw": path_raw,
            "path_display": str(row.get("path_display") or path_raw).strip(),
            "passphrase_ref": str(row.get("passphrase_ref") or "").strip(),
            "created_by": str(row.get("created_by") or "manual").strip(),
            "created_at": str(row.get("created_at") or "").strip(),
            "updated_at": str(row.get("updated_at") or "").strip(),
            "last_test_status": str(row.get("last_test_status") or "").strip(),
            "last_check_status": str(row.get("last_check_status") or "").strip(),
            "last_seen_at": str(row.get("last_seen_at") or "").strip(),
            "offsite_candidate": bool(row.get("offsite_candidate", location == "storagebox")),
            "separate_medium_candidate": bool(row.get("separate_medium_candidate", location in {"usb", "storagebox", "smb"})),
            "source_job_keys": source_job_keys,
            "used_by": used_by,
        })
    out.sort(key=lambda item: (str(item.get("location") or ""), str(item.get("display_name") or "")))
    return out


def repository_from_job(job: dict[str, Any], *, created_by: str = "migration") -> dict[str, Any] | None:
    if not isinstance(job, dict):
        return None
    job_key = str(job.get("job_key") or "").strip()
    backup_type = str(job.get("backup_type") or "").strip().lower()
    location = str(job.get("location") or "").strip().lower()
    repo_cfg = job.get("repo") if isinstance(job.get("repo"), dict) else {}
    repo_path = str(repo_cfg.get("default") or "").strip()
    if not job_key or not repo_path or location not in {"local", "usb", "smb", "storagebox"}:
        return None
    pass_cfg = job.get("passphrase") if isinstance(job.get("passphrase"), dict) else {}
    storage_profile_key = str(job.get("storage_profile_key") or "").strip()
    usb_profile_key = str(job.get("usb_profile_key") or "").strip()
    smb_profile_key = str(job.get("smb_profile_key") or "").strip()
    display_name = str(job.get("name") or job_key).strip()
    storage_key = location
    profile_key = storage_profile_key or usb_profile_key or smb_profile_key
    if profile_key:
        storage_key = f"{location}:{profile_key}"
    repo_uri = repo_path if "://" in repo_path else ""
    local_path = "" if repo_uri else repo_path
    ts = _now()
    return {
        "repository_key": f"repo_{job_key}",
        "display_name": display_name,
        "backup_type": backup_type,
        "location": location,
        "storage_type": "ssh" if location == "storagebox" else location,
        "storage_key": storage_key,
        "storage_profile_key": storage_profile_key,
        "usb_profile_key": usb_profile_key,
        "smb_profile_key": smb_profile_key,
        "repo_conf_key": str(repo_cfg.get("conf_key") or "").strip(),
        "repo_path": local_path,
        "repo_uri": repo_uri,
        "path_raw": repo_path,
        "path_display": repo_path,
        "passphrase_ref": str(pass_cfg.get("default") or "").strip(),
        "created_by": created_by,
        "created_at": ts,
        "updated_at": ts,
        "last_test_status": "",
        "last_check_status": "",
        "last_seen_at": "",
        "offsite_candidate": location == "storagebox",
        "separate_medium_candidate": location in {"usb", "storagebox", "smb"},
        "source_job_keys": [job_key],
        "used_by": [job_key],
    }


def upsert_repository_for_job(config: dict, job: dict[str, Any], *, created_by: str = "wizard") -> str:
    repo = repository_from_job(job, created_by=created_by)
    if not repo:
        return ""

    store = read_repository_store(config)
    rows = store["repositories"]
    by_key = {str(row.get("repository_key")): row for row in rows}
    identity = _repo_identity(repo["path_raw"])
    existing_for_identity = next(
        (row for row in rows if _repo_identity(row.get("path_raw") or row.get("repo_uri") or row.get("repo_path")) == identity),
        None,
    )
    if existing_for_identity:
        key = str(existing_for_identity.get("repository_key") or "")
    else:
        key = _unique_repository_key(str(repo.get("repository_key") or ""), by_key, identity)

    repo["repository_key"] = key
    previous = by_key.get(key, {})
    source_jobs = sorted(set((previous.get("source_job_keys") if isinstance(previous.get("source_job_keys"), list) else []) + repo["source_job_keys"]))
    used_by = sorted(set((previous.get("used_by") if isinstance(previous.get("used_by"), list) else []) + repo["used_by"]))
    merged = {
        **previous,
        **repo,
        "repository_key": key,
        "created_at": str(previous.get("created_at") or repo.get("created_at") or _now()),
        "created_by": str(previous.get("created_by") or repo.get("created_by") or created_by),
        "updated_at": _now(),
        "source_job_keys": source_jobs,
        "used_by": used_by,
    }

    next_rows = [row for row in rows if str(row.get("repository_key") or "") != key]
    next_rows.append(merged)
    write_repository_store(config, {"repositories": next_rows})
    return key


def build_repository_groups(config: dict) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {"local": [], "usb": [], "smb": [], "storagebox": []}
    for repo in read_repository_store(config)["repositories"]:
        location = str(repo.get("location") or "").strip().lower()
        if location not in groups:
            groups[location] = []
        groups[location].append({
            **repo,
            "conf_key": str(repo.get("repo_conf_key") or repo.get("repository_key") or ""),
        })
    for rows in groups.values():
        rows.sort(key=lambda row: (str(row.get("backup_type") or ""), str(row.get("display_name") or "")))
    return groups
