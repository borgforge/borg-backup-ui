"""Migration: move repository IDs to deterministic hash-suffixed keys."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repositories_api import (
    read_repository_store,
    repositories_file,
    repository_key_for,
    write_repository_store,
)


MIGRATION_ID = "repository_objects_v3"
INTRODUCED_IN = "2026.07.09.0003"


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


def _repo_seed(repo: dict[str, Any]) -> str:
    used_by = repo.get("used_by") if isinstance(repo.get("used_by"), list) else []
    source_job_keys = repo.get("source_job_keys") if isinstance(repo.get("source_job_keys"), list) else []
    for value in [*used_by, *source_job_keys]:
        text = str(value or "").strip()
        if text:
            return f"repo_{text}"
    backup_type = str(repo.get("backup_type") or "repository").strip()
    location = str(repo.get("location") or repo.get("storage_type") or "").strip()
    return "_".join(part for part in ("repo", backup_type, location) if part)


def _expected_key(repo: dict[str, Any]) -> str:
    identity = str(repo.get("path_raw") or repo.get("repo_uri") or repo.get("repo_path") or "").strip()
    if not identity:
        return str(repo.get("repository_key") or "").strip()
    return repository_key_for(_repo_seed(repo), identity)


def detect(config: dict) -> dict[str, Any]:
    repositories = read_repository_store(config).get("repositories") or []
    changes = []
    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        old_key = str(repo.get("repository_key") or "").strip()
        new_key = _expected_key(repo)
        if old_key and new_key and old_key != new_key:
            changes.append({"from": old_key, "to": new_key})
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(changes),
        "repository_file": str(repositories_file(config)),
        "repository_count": len(repositories),
        "repository_key_changes": changes,
    }


def apply(config: dict) -> dict[str, Any]:
    store = read_repository_store(config)
    repositories = store.get("repositories") if isinstance(store.get("repositories"), list) else []
    key_map: dict[str, str] = {}
    updated_repos: list[dict[str, Any]] = []

    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        old_key = str(repo.get("repository_key") or "").strip()
        new_key = _expected_key(repo)
        if old_key and new_key and old_key != new_key:
            key_map[old_key] = new_key
            repo = {**repo, "repository_key": new_key}
        updated_repos.append(repo)

    updated_jobs: list[str] = []
    if key_map:
        write_repository_store(config, {"repositories": updated_repos}, preserve_legacy=True)
        for path in _job_files(config):
            job = _read_job(path)
            if not job:
                continue
            current = str(job.get("repository_key") or "").strip()
            replacement = key_map.get(current)
            if not replacement:
                continue
            job["repository_key"] = replacement
            try:
                path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                updated_jobs.append(str(job.get("job_key") or path.stem))
            except OSError as exc:
                return {
                    "migration_id": MIGRATION_ID,
                    "introduced_in": INTRODUCED_IN,
                    "runner": "central_migration_registry",
                    "status": "failed",
                    "details": {
                        "error": str(exc),
                        "job_file": str(path),
                        "repository_key": replacement,
                    },
                }

    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied" if key_map else "not_required",
        "details": {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "repository_file": str(repositories_file(config)),
            "repository_key_map": key_map,
            "updated_repository_count": len(key_map),
            "updated_jobs": sorted(updated_jobs),
        },
    }
