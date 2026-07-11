"""Migration: create repository object metadata from existing wizard jobs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repositories_api import (
    read_repository_store,
    repository_key_for,
    repository_name_from_path,
    write_repository_store,
)


MIGRATION_ID = "repository_objects_v1"
INTRODUCED_IN = "2026.07.09.0000"


def _data_root(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    return base.parent if base.name == "scripts" else base


def _jobs_dir(config: dict) -> Path:
    return _data_root(config) / "config" / "jobs"


def _job_files(config: dict) -> list[Path]:
    jobs_dir = _jobs_dir(config)
    if not jobs_dir.is_dir():
        return []
    return sorted(path for path in jobs_dir.glob("*.json") if path.is_file())


def _read_job(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _job_needs_link(job: dict[str, Any]) -> bool:
    return not str(job.get("repository_key") or "").strip()


def _has_repository_payload(job: dict[str, Any]) -> bool:
    repo_cfg = job.get("repo") if isinstance(job.get("repo"), dict) else {}
    return bool(str(job.get("job_key") or "").strip() and str(repo_cfg.get("default") or "").strip())


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _identity(path_or_uri: Any) -> str:
    return str(path_or_uri or "").strip().rstrip("/")


def _storage_name(job: dict[str, Any]) -> str:
    location = str(job.get("location") or "").strip().lower()
    for field in (
        "storage_profile_name",
        "usb_profile_name",
        "smb_profile_name",
        "profile_name",
        "storage_profile_key",
        "usb_profile_key",
        "smb_profile_key",
    ):
        value = str(job.get(field) or "").strip()
        if value:
            return value
    return {
        "local": "Local",
        "usb": "USB",
        "smb": "SMB",
        "storagebox": "Storagebox",
    }.get(location, location)


def _repository_from_legacy_job(job: dict[str, Any]) -> dict[str, Any] | None:
    job_key = str(job.get("job_key") or "").strip()
    location = str(job.get("location") or "").strip().lower()
    repo_cfg = job.get("repo") if isinstance(job.get("repo"), dict) else {}
    repo_path = str(repo_cfg.get("default") or "").strip()
    if not job_key or not repo_path or location not in {"local", "usb", "smb", "storagebox"}:
        return None
    passphrase = job.get("passphrase") if isinstance(job.get("passphrase"), dict) else {}
    profile_keys = {
        "storage_profile_key": str(job.get("storage_profile_key") or "").strip(),
        "usb_profile_key": str(job.get("usb_profile_key") or "").strip(),
        "smb_profile_key": str(job.get("smb_profile_key") or "").strip(),
    }
    profile_key = next((value for value in profile_keys.values() if value), "")
    display_name = str(job.get("name") or job_key).strip()
    timestamp = _now()
    return {
        "repository_key": repository_key_for(f"repo_{job_key}", repo_path),
        "display_name": display_name,
        "repository_name": repository_name_from_path(repo_path),
        "job_name": display_name,
        "backup_type": str(job.get("backup_type") or "").strip().lower(),
        "location": location,
        "storage_type": "ssh" if location == "storagebox" else location,
        "storage_key": f"{location}:{profile_key}" if profile_key else location,
        "storage_name": _storage_name(job),
        **profile_keys,
        "repo_conf_key": str(repo_cfg.get("conf_key") or "").strip(),
        "repo_path": "" if "://" in repo_path else repo_path,
        "repo_uri": repo_path if "://" in repo_path else "",
        "path_raw": repo_path,
        "path_display": repo_path,
        "passphrase_ref": str(passphrase.get("default") or "").strip(),
        "encryption": str(job.get("encryption") or "").strip(),
        "append_only": bool(job.get("append_only", False)),
        "storage_quota": str(job.get("storage_quota") or "").strip(),
        "initialized": bool(job.get("initialized", False)),
        "created_by": "migration",
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_test_status": "",
        "last_check_status": "",
        "last_seen_at": "",
        "offsite_candidate": location == "storagebox",
        "separate_medium_candidate": location in {"usb", "storagebox", "smb"},
        "source_job_keys": [job_key],
        "used_by": [job_key],
    }


def _upsert_repository_for_legacy_job(config: dict, job: dict[str, Any]) -> str:
    repository = _repository_from_legacy_job(job)
    if not repository:
        return ""
    store = read_repository_store(config)
    rows = store.get("repositories", [])
    identity = _identity(repository.get("path_raw"))
    existing = next(
        (
            row for row in rows
            if _identity(row.get("path_raw") or row.get("repo_uri") or row.get("repo_path")) == identity
        ),
        None,
    )
    key = str((existing or {}).get("repository_key") or repository.get("repository_key") or "")
    repository["repository_key"] = key

    from storage_objects_api import repository_relative_path, upsert_storage_for_repository
    try:
        from config_api import read_settings_payload
        settings = read_settings_payload(config)
    except Exception:
        settings = None
    storage = upsert_storage_for_repository(config, repository, settings=settings)
    if storage:
        repository["storage_key"] = str(storage.get("storage_key") or repository.get("storage_key") or "")
        repository["storage_name"] = str(storage.get("display_name") or repository.get("storage_name") or "")
        repository["relative_path"] = repository_relative_path(repository, storage)

    previous = existing or {}
    repository["created_at"] = str(previous.get("created_at") or repository.get("created_at") or _now())
    repository["created_by"] = str(previous.get("created_by") or "migration")
    repository["updated_at"] = _now()
    repository["source_job_keys"] = sorted(set(
        (previous.get("source_job_keys") if isinstance(previous.get("source_job_keys"), list) else [])
        + repository["source_job_keys"]
    ))
    repository["used_by"] = sorted(set(
        (previous.get("used_by") if isinstance(previous.get("used_by"), list) else [])
        + repository["used_by"]
    ))
    write_repository_store(config, {"repositories": [
        row for row in rows if str(row.get("repository_key") or "") != key
    ] + [repository]}, preserve_legacy=True)
    return key


def detect(config: dict) -> dict[str, Any]:
    files = _job_files(config)
    jobs = [job for path in files if (job := _read_job(path))]
    candidates = [job for job in jobs if _has_repository_payload(job)]
    missing_links = [str(job.get("job_key") or "") for job in candidates if _job_needs_link(job)]
    repo_count = len(read_repository_store(config).get("repositories") or [])
    required = bool(candidates and (repo_count == 0 or missing_links))
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": required,
        "jobs_dir": str(_jobs_dir(config)),
        "job_count": len(jobs),
        "candidate_count": len(candidates),
        "repository_count": repo_count,
        "jobs_missing_repository_key": missing_links,
    }


def apply(config: dict) -> dict[str, Any]:
    actions: list[str] = []
    migrated_jobs: list[str] = []
    repository_keys: list[str] = []

    for path in _job_files(config):
        job = _read_job(path)
        if not job or not _has_repository_payload(job):
            continue
        job_key = str(job.get("job_key") or "").strip()
        repository_key = _upsert_repository_for_legacy_job(config, job)
        if not repository_key:
            continue
        repository_keys.append(repository_key)
        if str(job.get("repository_key") or "").strip() != repository_key:
            job["repository_key"] = repository_key
            try:
                path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                migrated_jobs.append(job_key)
                actions.append(f"linked job {job_key} to {repository_key}")
            except OSError as exc:
                return {
                    "migration_id": MIGRATION_ID,
                    "introduced_in": INTRODUCED_IN,
                    "runner": "central_migration_registry",
                    "status": "failed",
                    "details": {
                        "error": str(exc),
                        "job_key": job_key,
                        "job_file": str(path),
                    },
                }
        else:
            actions.append(f"verified job {job_key} uses {repository_key}")

    unique_repositories = sorted(set(repository_keys))
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied" if migrated_jobs or unique_repositories else "not_required",
        "details": {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "jobs_dir": str(_jobs_dir(config)),
            "repository_file": str(_data_root(config) / "config" / "repositories.json"),
            "linked_jobs": migrated_jobs,
            "linked_job_count": len(migrated_jobs),
            "repository_keys": unique_repositories,
            "repository_count": len(unique_repositories),
            "actions": actions,
        },
    }
