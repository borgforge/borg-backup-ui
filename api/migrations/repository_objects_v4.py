"""Migration: enrich repository encryption metadata from linked jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repositories_api import read_repository_store, repositories_file, write_repository_store


MIGRATION_ID = "repository_objects_v4"
INTRODUCED_IN = "2026.07.09.0004"


def _data_root(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    return base.parent if base.name == "scripts" else base


def _jobs_dir(config: dict) -> Path:
    return _data_root(config) / "config" / "jobs"


def _read_job(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _jobs_by_key(config: dict) -> dict[str, dict[str, Any]]:
    jobs_dir = _jobs_dir(config)
    if not jobs_dir.is_dir():
        return {}
    jobs: dict[str, dict[str, Any]] = {}
    for path in sorted(jobs_dir.glob("*.json")):
        if not path.is_file():
            continue
        job = _read_job(path)
        if not job:
            continue
        key = str(job.get("job_key") or path.stem).strip()
        if key:
            jobs[key] = job
    return jobs


def _linked_job_keys(repo: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for field in ("used_by", "source_job_keys"):
        values = repo.get(field) if isinstance(repo.get(field), list) else []
        for value in values:
            key = str(value or "").strip()
            if key and key not in keys:
                keys.append(key)
    return keys


def _job_encryption(repo: dict[str, Any], jobs: dict[str, dict[str, Any]]) -> str:
    for key in _linked_job_keys(repo):
        encryption = str(jobs.get(key, {}).get("encryption") or "").strip()
        if encryption:
            return encryption
    return ""


def _missing_encryption_repositories(config: dict) -> list[str]:
    jobs = _jobs_by_key(config)
    missing = []
    for repo in read_repository_store(config).get("repositories", []):
        if not isinstance(repo, dict):
            continue
        if str(repo.get("encryption") or "").strip():
            continue
        if _job_encryption(repo, jobs):
            missing.append(str(repo.get("repository_key") or ""))
    return missing


def detect(config: dict) -> dict[str, Any]:
    missing = _missing_encryption_repositories(config)
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(missing),
        "repository_file": str(repositories_file(config)),
        "repositories_missing_encryption": missing,
    }


def apply(config: dict) -> dict[str, Any]:
    store = read_repository_store(config)
    jobs = _jobs_by_key(config)
    updated_repositories: list[str] = []
    updated_rows: list[dict[str, Any]] = []

    for repo in store.get("repositories", []):
        if not isinstance(repo, dict):
            continue
        if not str(repo.get("encryption") or "").strip():
            encryption = _job_encryption(repo, jobs)
            if encryption:
                repo = {**repo, "encryption": encryption}
                updated_repositories.append(str(repo.get("repository_key") or ""))
        updated_rows.append(repo)

    if updated_repositories:
        write_repository_store(config, {"repositories": updated_rows})

    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied" if updated_repositories else "not_required",
        "details": {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "repository_file": str(repositories_file(config)),
            "updated_repositories": updated_repositories,
            "updated_repository_count": len(updated_repositories),
        },
    }
