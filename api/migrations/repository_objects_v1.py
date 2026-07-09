"""Migration: create repository object metadata from existing wizard jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repositories_api import read_repository_store, upsert_repository_for_job


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
        repository_key = upsert_repository_for_job(config, job, created_by="migration")
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

