"""Canonical repository context resolution for jobs and Borg operations."""

from __future__ import annotations

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


def load_job_metadata(config: dict, job_id: str) -> dict[str, Any]:
    from job_store import read_job
    return read_job(jobs_dir(config), job_id)


def load_repository_inventory(config: dict) -> dict[str, dict[str, dict[str, Any]]]:
    """Load canonical repository and storage objects once for one operation."""
    from inventory_store import inventory_lock
    with inventory_lock(jobs_dir(config).parent):
        from repositories_api import read_repository_store
        from storage_objects_api import read_storage_store

        from job_store import read_jobs, validate_assignments
        store = read_repository_store(config)
        validate_assignments(read_jobs(jobs_dir(config)), store)
        repositories = {
            str(row.get("repository_key") or "").strip(): row
            for row in store.get("repositories", [])
            if isinstance(row, dict) and str(row.get("repository_key") or "").strip()
        }
        storages = {
            str(row.get("storage_key") or "").strip(): row
            for row in read_storage_store(config).get("storages", [])
            if isinstance(row, dict) and str(row.get("storage_key") or "").strip()
        }
        return {"repositories": repositories, "storages": storages}


def repository_by_key(
    config: dict,
    repository_key: str,
    *,
    inventory: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    from repositories_api import read_repository_store

    key = str(repository_key or "").strip()
    if not key:
        raise RepositoryContextError("Job has no repository assignment")
    if isinstance(inventory, dict):
        repository = inventory.get("repositories", {}).get(key)
    else:
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


def storage_by_key(
    config: dict,
    storage_key: str,
    *,
    inventory: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    from storage_objects_api import read_storage_store

    key = str(storage_key or "").strip()
    if not key:
        raise RepositoryContextError("Repository has no storage assignment")
    if isinstance(inventory, dict):
        storage = inventory.get("storages", {}).get(key)
    else:
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
    job_id: str = "",
    *,
    job: dict[str, Any] | None = None,
    require_passphrase_file: bool = True,
    inventory: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    from job_model import JobValidationError, validate_job
    metadata = dict(job) if isinstance(job, dict) else load_job_metadata(config, job_id)
    validate_job(metadata)
    resolved_job_id = metadata["job_id"]
    if job_id and job_id != resolved_job_id:
        raise JobValidationError("conflicting_job_identity", "Requested job_id does not match metadata")
    if LEGACY_JOB_REPOSITORY_FIELDS.intersection(metadata):
        raise RepositoryContextError("Job still contains legacy repository fields")
    repository_key = str(metadata.get("repository_key") or "").strip()
    source = inventory if isinstance(inventory, dict) else load_repository_inventory(config)
    repository = repository_by_key(config, repository_key, inventory=source)
    storage_key = str(repository.get("storage_key") or "").strip()
    storage = storage_by_key(config, storage_key, inventory=source)
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
        "job_id": resolved_job_id,
        "name": metadata["name"],
        "archive_prefix": metadata["archive_prefixes"][0],
        "archive_prefixes": list(metadata["archive_prefixes"]),
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
    from job_store import read_jobs
    wanted = str(location or "").strip().lower()
    references: dict[str, list[str]] = {}
    inventory = load_repository_inventory(config)
    for job_id, job in read_jobs(jobs_dir(config)).items():
        context = resolve_job_repository_context(config, job_id, job=job,
            require_passphrase_file=False, inventory=inventory)
        if context["location"] == wanted and context["profile_key"]:
            references.setdefault(context["profile_key"], []).append(f"{job['name']} ({job_id})")
    return references


def jobs_using_repository(config: dict, repository_key: str) -> list[str]:
    from inventory_store import inventory_lock
    with inventory_lock(jobs_dir(config).parent):
        from job_store import read_jobs, validate_assignments
        from repositories_api import read_repository_store
        jobs = read_jobs(jobs_dir(config))
        validate_assignments(jobs, read_repository_store(config))
        return [job_id for job_id, job in jobs.items() if job["repository_key"] == repository_key]
