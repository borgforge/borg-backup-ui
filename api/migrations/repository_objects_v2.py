"""Migration: add human-readable repository, job, and storage names."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repositories_api import enrich_repository_display_fields, write_repository_store


MIGRATION_ID = "repository_objects_v2"
INTRODUCED_IN = "2026.07.09.0001"


def _data_root(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    return base.parent if base.name == "scripts" else base


def _jobs_dir(config: dict) -> Path:
    return _data_root(config) / "config" / "jobs"


def _repository_file(config: dict) -> Path:
    return _data_root(config) / "config" / "repositories.json"


def _read_repository_rows(config: dict) -> list[dict[str, Any]]:
    path = _repository_file(config)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    rows = raw.get("repositories") if isinstance(raw, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


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


def _primary_job_for_repo(repo: dict[str, Any], jobs: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for field in ("used_by", "source_job_keys"):
        values = repo.get(field) if isinstance(repo.get(field), list) else []
        for key in values:
            job = jobs.get(str(key or "").strip())
            if job:
                return job
    return None


def _needs_enrichment(repo: dict[str, Any]) -> bool:
    for field in ("repository_name", "job_name", "storage_name"):
        if not str(repo.get(field) or "").strip():
            return True
    display_name = str(repo.get("display_name") or "").strip()
    return bool(display_name and display_name.lower().endswith((" - local", " - usb", " - smb", " - storagebox")))


def detect(config: dict) -> dict[str, Any]:
    repositories = _read_repository_rows(config)
    missing = [str(repo.get("repository_key") or "") for repo in repositories if _needs_enrichment(repo)]
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(missing),
        "repository_file": str(_repository_file(config)),
        "repository_count": len(repositories),
        "repositories_missing_display_names": missing,
    }


def apply(config: dict) -> dict[str, Any]:
    repositories = _read_repository_rows(config)
    jobs = _jobs_by_key(config)
    changed: list[str] = []
    updated: list[dict[str, Any]] = []

    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        before = json.dumps(repo, sort_keys=True, ensure_ascii=False)
        job = _primary_job_for_repo(repo, jobs)
        enriched = enrich_repository_display_fields(repo, job)
        after = json.dumps(enriched, sort_keys=True, ensure_ascii=False)
        if before != after:
            changed.append(str(enriched.get("repository_key") or ""))
        updated.append(enriched)

    if changed:
        write_repository_store(config, {"repositories": updated})

    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied" if changed else "not_required",
        "details": {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "repository_file": str(_repository_file(config)),
            "updated_repositories": changed,
            "updated_repository_count": len(changed),
        },
    }
