"""Canonical repository context resolution for jobs and Borg operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RepositoryContextError(ValueError):
    """A job cannot be resolved to one complete repository/storage context."""


LEGACY_JOB_REPOSITORY_FIELDS = {
    "repo",
    "passphrase",
    "encryption",
    "storage_key",
    "usb_profile_key",
    "smb_profile_key",
    "storage_profile_key",
    "create_repo_if_missing",
    "remote_init_confirmed",
}


def _data_root(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    return base.parent if base.name == "scripts" else base


def jobs_dir(config: dict) -> Path:
    return _data_root(config) / "config" / "jobs"


def load_job_metadata(config: dict, job_key: str) -> dict[str, Any]:
    key = str(job_key or "").strip()
    if not key:
        raise RepositoryContextError("Job key is missing")
    path = jobs_dir(config) / f"{key}.json"
    if not path.is_file():
        raise RepositoryContextError(f"Job metadata was not found: {key}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RepositoryContextError(f"Job metadata is not readable: {key}") from exc
    if not isinstance(payload, dict):
        raise RepositoryContextError(f"Job metadata is invalid: {key}")
    return payload


def repository_by_key(config: dict, repository_key: str) -> dict[str, Any]:
    from repositories_api import read_repository_store

    key = str(repository_key or "").strip()
    if not key:
        raise RepositoryContextError("Job has no repository assignment")
    repository = next(
        (
            row
            for row in read_repository_store(config).get("repositories", [])
            if str(row.get("repository_key") or "").strip() == key
        ),
        None,
    )
    if not isinstance(repository, dict):
        raise RepositoryContextError(f"Assigned repository was not found: {key}")
    return repository


def storage_by_key(config: dict, storage_key: str) -> dict[str, Any]:
    from storage_objects_api import read_storage_store

    key = str(storage_key or "").strip()
    if not key:
        raise RepositoryContextError("Repository has no storage assignment")
    storage = next(
        (
            row
            for row in read_storage_store(config).get("storages", [])
            if str(row.get("storage_key") or "").strip() == key
        ),
        None,
    )
    if not isinstance(storage, dict):
        raise RepositoryContextError(f"Assigned storage target was not found: {key}")
    return storage


def repository_path(repository: dict[str, Any], storage: dict[str, Any]) -> str:
    from repositories_api import effective_repository_path

    relative_path = str(repository.get("relative_path") or "").strip()
    if not relative_path:
        raise RepositoryContextError("Repository has no relative path")
    try:
        return effective_repository_path(storage, relative_path)
    except (TypeError, ValueError) as exc:
        raise RepositoryContextError(f"Repository path cannot be resolved: {exc}") from exc


def resolve_job_repository_context(
    config: dict,
    job_key: str = "",
    *,
    job: dict[str, Any] | None = None,
    require_passphrase_file: bool = True,
    allow_legacy_job: bool = False,
) -> dict[str, Any]:
    metadata = dict(job) if isinstance(job, dict) else load_job_metadata(config, job_key)
    resolved_job_key = str(metadata.get("job_key") or job_key or "").strip()
    if not allow_legacy_job:
        legacy_fields = sorted(field for field in LEGACY_JOB_REPOSITORY_FIELDS if field in metadata)
        if int(metadata.get("schema_version") or 1) < 2 or legacy_fields:
            details = ", ".join(legacy_fields) if legacy_fields else "schema_version"
            raise RepositoryContextError(
                f"Job '{resolved_job_key}' awaits repository migration ({details})"
            )
    repository_key = str(metadata.get("repository_key") or "").strip()
    repository = repository_by_key(config, repository_key)
    storage_key = str(repository.get("storage_key") or "").strip()
    storage = storage_by_key(config, storage_key)
    path = repository_path(repository, storage)

    storage_location = str(storage.get("location") or storage.get("storage_type") or "").strip().lower()
    if storage_location == "ssh":
        storage_location = "storagebox"
    job_location = str(metadata.get("location") or "").strip().lower()
    if job_location and storage_location and job_location != storage_location:
        raise RepositoryContextError(
            f"Job location '{job_location}' does not match repository storage '{storage_location}'"
        )

    encryption = str(repository.get("encryption") or "").strip().lower()
    if not encryption:
        raise RepositoryContextError("Repository encryption metadata is missing")
    passphrase_ref = str(repository.get("passphrase_ref") or "").strip()
    if encryption != "none":
        if not passphrase_ref:
            raise RepositoryContextError("Repository passphrase reference is missing")
        if require_passphrase_file and not Path(passphrase_ref).is_file():
            raise RepositoryContextError("Repository passphrase file does not exist")

    return {
        "job_key": resolved_job_key,
        "job": metadata,
        "repository_key": repository_key,
        "repository": repository,
        "storage_key": storage_key,
        "storage": storage,
        "location": storage_location,
        "repository_path": path,
        "relative_path": str(repository.get("relative_path") or "").strip(),
        "passphrase_ref": passphrase_ref,
        "encryption": encryption,
        "profile_key": str(storage.get("profile_key") or "").strip(),
    }


def profile_job_references(config: dict, location: str) -> dict[str, list[str]]:
    wanted = str(location or "").strip().lower()
    references: dict[str, list[str]] = {}
    directory = jobs_dir(config)
    if not directory.is_dir():
        return references
    for path in sorted(directory.glob("*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(job, dict):
            continue
        job_key = str(job.get("job_key") or path.stem).strip()
        try:
            context = resolve_job_repository_context(
                config,
                job_key,
                job=job,
                require_passphrase_file=False,
            )
        except RepositoryContextError:
            continue
        if str(context.get("location") or "").strip().lower() != wanted:
            continue
        profile_key = str(context.get("profile_key") or "").strip().lower()
        if not profile_key:
            continue
        name = str(job.get("name") or "").strip()
        label = f"{job_key} ({name})" if name else job_key
        references.setdefault(profile_key, []).append(label)
    return references


def jobs_using_repository(config: dict, repository_key: str) -> list[str]:
    wanted = str(repository_key or "").strip()
    if not wanted:
        return []
    jobs: list[str] = []
    directory = jobs_dir(config)
    if not directory.is_dir():
        return jobs
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("repository_key") or "").strip() != wanted:
            continue
        key = str(payload.get("job_key") or path.stem).strip()
        if key:
            jobs.append(key)
    return jobs
