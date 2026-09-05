"""Repository object inventory for Borg Backup UI.

Repository objects are the canonical metadata inventory for Borg repositories.
They can also be created or imported through the repository manager; backup jobs
only reference these objects.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shlex
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from inventory_store import atomic_write_bytes, atomic_write_inventory, atomic_write_json, inventory_lock, read_inventory
from storage_profiles_api import normalize_ssh_mode


SCHEMA_VERSION = 1
ALLOWED_ENCRYPTION_MODES = {
    "repokey-blake2",
    "repokey",
    "keyfile-blake2",
    "keyfile",
    "authenticated-blake2",
    "authenticated",
    "none",
}

REPOSITORY_INFO_REFRESH_STATE_VERSION = 1
REPOSITORY_INFO_REFRESH_DEFAULT_INTERVAL_HOURS = 24
REPOSITORY_INFO_REFRESH_DEFAULT_RETRY_HOURS = 1

_REFRESH_LOCK = threading.Lock()
_REFRESH_WAKE_EVENT = threading.Event()
_REFRESH_RUNTIME_STATE: dict[str, Any] = {
    "worker_started": False,
    "worker_started_at": "",
    "worker_state": "stopped",
    "current_run_started_at": "",
    "last_schedule_reason": "",
}


class RepositoryBusyError(RuntimeError):
    """The repository is healthy but currently used by another operation."""


class RepositoryLifecycleConflict(RuntimeError):
    """A repository cannot be removed while references or operations exist."""

    def __init__(self, message: str, code: str = "repository_lifecycle_conflict") -> None:
        super().__init__(message)
        self.code = code


class RepositoryTargetConflict(RuntimeError):
    """The requested target cannot safely be created or imported."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _data_root(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    return base.parent if base.name == "scripts" else base


def repositories_file(config: dict) -> Path:
    return _data_root(config) / "config" / "repositories.json"


def repository_info_refresh_state_file(config: dict) -> Path:
    return _data_root(config) / "config" / "repository-info-refresh-state.json"


def _slug(value: str, fallback: str = "repository") -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text or fallback


def _hash_suffix(value: str) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:8]


def _repo_identity(path_or_uri: str) -> str:
    text = str(path_or_uri or "").strip()
    if not text:
        return ""
    if "://" in text:
        return text.rstrip("/")
    return text.rstrip("/")


def repository_key_for(seed: str, identity: str) -> str:
    base = _slug(seed, "repository")
    if not base.startswith("repo_"):
        base = f"repo_{base}"
    suffix = _hash_suffix(_repo_identity(identity))
    if base.endswith(f"_{suffix}"):
        return base
    return f"{base}_{suffix}"


def repository_name_from_path(path_or_uri: str) -> str:
    text = str(path_or_uri or "").strip()
    if not text:
        return ""
    parsed_path = urlsplit(text).path if "://" in text else text
    name = unquote(parsed_path.rstrip("/").rsplit("/", 1)[-1]).strip()
    return name or text.rstrip("/").rsplit("/", 1)[-1].strip()


def _normalize_repo_segment(value: str) -> str:
    text = str(value or "").strip().strip("/")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._")
    if not text:
        raise ValueError("Repository name must not be empty")
    if text in {".", ".."} or "/" in text:
        raise ValueError("Repository name must be a single path segment")
    return text


def _safe_relative_path(value: str) -> str:
    text = str(value or "").strip().strip("/")
    if not text:
        raise ValueError("Repository path must not be empty")
    parts = []
    for raw in text.split("/"):
        part = raw.strip()
        if not part or part in {".", ".."}:
            raise ValueError("Repository path contains unsafe path segments")
        parts.append(_normalize_repo_segment(part))
    return "/".join(parts)


def _join_path(base: str, relative: str) -> str:
    b = str(base or "").strip().rstrip("/")
    r = _safe_relative_path(relative)
    if not b:
        raise ValueError("Storage base path is missing")
    if "://" in b:
        parsed = urlsplit(b)
        path = "/".join(part for part in (parsed.path.rstrip("/"), quote(r, safe="/._-")) if part)
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))
    return f"{b}/{r}" if b != "/" else f"/{r}"


def effective_repository_path(storage: dict[str, Any], relative_path: str) -> str:
    """Build the effective Borg repository path/URI for a storage object."""
    if not isinstance(storage, dict):
        raise ValueError("Storage target is missing")
    location = str(storage.get("location") or storage.get("storage_type") or "").strip().lower()
    relative = _safe_relative_path(relative_path)
    if location == "storagebox" or str(storage.get("storage_type") or "").strip().lower() == "ssh":
        user = str(storage.get("user") or "").strip()
        host = str(storage.get("host") or "").strip()
        port = str(storage.get("port") or "23").strip() or "23"
        base_path = str(storage.get("base_path") or "").strip() or "/./backup"
        if not user or not host:
            raise ValueError("SSH storage target is incomplete")
        if base_path.startswith("./"):
            base_path = f"/{base_path}"
        elif not base_path.startswith("/"):
            base_path = f"/{base_path}"
        base_path = base_path.rstrip("/") or "/"
        return f"ssh://{quote(user, safe='')}@{host}:{port}{base_path}/{quote(relative, safe='/._-')}"
    base_path = str(storage.get("base_path") or storage.get("mount_path") or "").strip()
    return _join_path(base_path, relative)


def _looks_like_borg_repository(path: Path) -> bool:
    config_file = path / "config"
    if not config_file.is_file():
        return False
    try:
        header = config_file.read_text(encoding="utf-8", errors="replace")[:8192]
    except OSError:
        return False
    return "[repository]" in header and re.search(r"(?m)^\s*id\s*=\s*[0-9a-fA-F]+\s*$", header) is not None


def validate_repository_target(config: dict, payload: dict[str, Any]) -> dict[str, Any]:
    """Classify a repository target without modifying it or writing secrets."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid repository payload")
    action = str(payload.get("action") or "import").strip().lower()
    if action not in {"create", "import"}:
        raise ValueError("Invalid repository action")
    storage_key = str(payload.get("storage_key") or "").strip()
    storage = _storage_by_key(config).get(storage_key)
    if not storage:
        raise ValueError("Storage target not found")
    relative_path = _safe_relative_path(str(payload.get("relative_path") or payload.get("repository_name") or ""))
    repo_path = effective_repository_path(storage, relative_path)

    existing = next((
        row for row in read_repository_store(config).get("repositories", [])
        if str(row.get("storage_key") or "") == storage_key
        and str(row.get("relative_path") or "").rstrip("/") == relative_path.rstrip("/")
    ), None)
    if existing:
        raise RepositoryTargetConflict(
            "This repository target is already managed by Borg Backup UI.",
            "repository_already_managed",
        )

    if "://" in repo_path:
        return {"ok": True, "state": "remote_unchecked", "repository_path": repo_path}

    target = Path(repo_path)
    try:
        exists = target.exists()
        if not exists:
            if action == "import":
                raise RepositoryTargetConflict(
                    "The repository target does not exist. Select Create repository or correct the path.",
                    "repository_target_missing",
                )
            return {"ok": True, "state": "absent", "repository_path": repo_path}
        if not target.is_dir():
            raise RepositoryTargetConflict(
                "The repository target exists but is not a directory.",
                "repository_target_not_directory",
            )
        is_empty = next(target.iterdir(), None) is None
    except RepositoryTargetConflict:
        raise
    except PermissionError as exc:
        raise RepositoryTargetConflict(
            "The repository target cannot be accessed. Check storage permissions.",
            "repository_target_inaccessible",
        ) from exc
    except OSError as exc:
        raise RepositoryTargetConflict(
            f"The repository target cannot be inspected: {exc}",
            "repository_target_inaccessible",
        ) from exc

    if is_empty:
        if action == "import":
            raise RepositoryTargetConflict(
                "The selected directory is empty and is not a Borg repository.",
                "repository_target_empty",
            )
        return {"ok": True, "state": "empty", "repository_path": repo_path}

    if _looks_like_borg_repository(target):
        if action == "create":
            raise RepositoryTargetConflict(
                "A Borg repository already exists at this target. Import it instead of creating it again.",
                "repository_target_borg_exists",
            )
        return {"ok": True, "state": "borg_repository", "repository_path": repo_path}

    raise RepositoryTargetConflict(
        "The repository target is not empty and does not look like a Borg repository. Choose an empty path.",
        "repository_target_not_empty",
    )


def _raise_borg_init_target_error(output: str, exit_code: int) -> None:
    text = str(output or "").strip()
    lowered = text.lower()
    if "already exists" in lowered or "repository exists" in lowered:
        raise RepositoryTargetConflict(
            "A Borg repository already exists at this target. Import it instead of creating it again.",
            "repository_target_borg_exists",
        )
    if "not empty" in lowered:
        raise RepositoryTargetConflict(
            "The repository target is not empty. Choose an empty path or import the existing Borg repository.",
            "repository_target_not_empty",
        )
    if "permission denied" in lowered or "operation not permitted" in lowered:
        raise RepositoryTargetConflict(
            "The repository target cannot be written. Check storage permissions.",
            "repository_target_inaccessible",
        )
    first_line = text.splitlines()[0] if text.splitlines() else f"borg init failed with exit {exit_code}"
    raise RuntimeError(first_line)


def _storage_name_from_location(location: str) -> str:
    return {
        "local": "Local",
        "usb": "USB",
        "smb": "SMB",
        "storagebox": "Storagebox",
    }.get(str(location or "").strip().lower(), str(location or "").strip())


def enrich_repository_display_fields(repo: dict[str, Any]) -> dict[str, Any]:
    row = dict(repo or {})
    path_raw = str(row.get("path_raw") or row.get("relative_path") or "").strip()
    display_name = str(row.get("display_name") or "").strip()
    job_name = str(row.get("job_name") or "").strip()
    if not job_name:
        job_name = str(row.get("display_name") or row.get("backup_type") or row.get("repository_key") or "").strip()

    repository_name = str(row.get("repository_name") or "").strip()
    if not repository_name:
        repository_name = repository_name_from_path(path_raw)
    if not repository_name:
        repository_name = str(row.get("repository_key") or "").strip()

    storage_name = str(row.get("storage_name") or "").strip()
    if not storage_name:
        storage_name = _storage_name_from_location(str(row.get("location") or row.get("storage_type") or ""))

    row["repository_name"] = repository_name
    row["job_name"] = job_name
    row["storage_name"] = storage_name
    row["display_name"] = display_name or repository_name or job_name or str(row.get("repository_key") or "").strip()
    return row


def read_repository_store(config: dict, *, preserve_legacy: bool = False) -> dict[str, Any]:
    path = repositories_file(config)
    from inventory_store import read_cached_inventory
    payload = read_cached_inventory(path)
    if payload is None:
        with inventory_lock(path.parent):
            payload = read_inventory(path, collection_key="repositories", schema_version=SCHEMA_VERSION)
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": str(payload.get("updated_at") or ""),
        "repositories": normalize_repositories(payload["repositories"], preserve_legacy=preserve_legacy),
    }


def read_repository_store_for_api(config: dict) -> dict[str, Any]:
    """Return repository metadata with all path fields derived from current storages."""
    store = read_repository_store(config)
    from storage_objects_api import read_storage_store
    storages = {
        str(row.get("storage_key") or ""): row
        for row in read_storage_store(config).get("storages", [])
    }
    derived = []
    for row in store["repositories"]:
        storage = storages.get(str(row.get("storage_key") or ""))
        relative = str(row.get("relative_path") or "").strip()
        if storage and relative:
            effective = effective_repository_path(storage, relative)
            row = {
                **row,
                "path_raw": effective,
                "path_display": effective,
                "storage_name": str(storage.get("display_name") or row.get("storage_name") or ""),
            }
        derived.append(row)
    return {**store, "repositories": derived}


def write_repository_store(config: dict, store: dict[str, Any], *, preserve_legacy: bool = False) -> None:
    path = repositories_file(config)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now(),
        "repositories": normalize_repositories(
            store.get("repositories") if isinstance(store, dict) else [],
            preserve_legacy=preserve_legacy,
        ),
    }
    with inventory_lock(path.parent):
        atomic_write_inventory(path, payload)


def update_repository_store(
    config: dict,
    updater: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> dict[str, Any]:
    """Run one repository read-modify-write operation under the shared lock."""
    path = repositories_file(config)
    with inventory_lock(path.parent):
        current = read_repository_store(config)
        updated = updater(current)
        result = updated if isinstance(updated, dict) else current
        write_repository_store(config, result)
        return read_repository_store(config)


def normalize_repositories(rows: Any, *, preserve_legacy: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        key = _slug(str(row.get("repository_key") or row.get("key") or ""), "")
        legacy_path = (
            str(row.get("path_raw") or row.get("repo_uri") or row.get("repo_path") or "").strip()
            if preserve_legacy
            else ""
        )
        relative_path = str(row.get("relative_path") or repository_name_from_path(legacy_path)).strip()
        storage_key = str(row.get("storage_key") or "").strip()
        if not key or not storage_key or not relative_path or key in seen:
            continue
        seen.add(key)
        location = str(row.get("location") or row.get("storage_type") or "").strip().lower()
        source_job_keys = row.get("source_job_keys") if isinstance(row.get("source_job_keys"), list) else []
        source_job_keys = [str(item).strip() for item in source_job_keys if str(item).strip()]
        used_by = row.get("used_by") if isinstance(row.get("used_by"), list) else source_job_keys
        used_by = [str(item).strip() for item in used_by if str(item).strip()]
        normalized = enrich_repository_display_fields({
            "repository_key": key,
            "display_name": str(row.get("display_name") or key).strip() or key,
            "backup_type": str(row.get("backup_type") or "").strip().lower(),
            "location": location,
            "storage_type": str(row.get("storage_type") or location).strip().lower(),
            "storage_key": storage_key,
            "storage_name": str(row.get("storage_name") or "").strip(),
            "relative_path": relative_path,
            "repository_name": str(row.get("repository_name") or "").strip(),
            "job_name": str(row.get("job_name") or "").strip(),
            "passphrase_ref": str(row.get("passphrase_ref") or "").strip(),
            "keyfile_ref": str(row.get("keyfile_ref") or "").strip(),
            "encryption": str(row.get("encryption") or "").strip(),
            "append_only": bool(row.get("append_only", False)),
            "storage_quota": str(row.get("storage_quota") or "").strip(),
            "initialized": bool(row.get("initialized", False)),
            "created_by": str(row.get("created_by") or "manual").strip(),
            "created_at": str(row.get("created_at") or "").strip(),
            "updated_at": str(row.get("updated_at") or "").strip(),
            "last_test_status": str(row.get("last_test_status") or "").strip(),
            "last_check_status": str(row.get("last_check_status") or "").strip(),
            "last_seen_at": str(row.get("last_seen_at") or "").strip(),
            "last_info_refresh_at": str(row.get("last_info_refresh_at") or "").strip(),
            "last_info_refresh_status": str(row.get("last_info_refresh_status") or "").strip(),
            "last_info_refresh_error": str(row.get("last_info_refresh_error") or "").strip(),
            "borg_repository_id": str(row.get("borg_repository_id") or "").strip(),
            "borg_last_modified": str(row.get("borg_last_modified") or "").strip(),
            "borg_key_exported_at": str(row.get("borg_key_exported_at") or "").strip(),
            "borg_key_imported_at": str(row.get("borg_key_imported_at") or "").strip(),
            "borg_key_repository_id": str(row.get("borg_key_repository_id") or "").strip(),
            "repository_stats": row.get("repository_stats") if isinstance(row.get("repository_stats"), dict) else {},
            "maintenance_results": row.get("maintenance_results") if isinstance(row.get("maintenance_results"), dict) else {},
            "offsite_candidate": bool(row.get("offsite_candidate", location == "storagebox")),
            "separate_medium_candidate": bool(row.get("separate_medium_candidate", location in {"usb", "storagebox", "smb"})),
            "source_job_keys": source_job_keys,
            "used_by": used_by,
        })
        if preserve_legacy:
            for legacy_field in (
                "repo_path",
                "repo_uri",
                "path_raw",
                "path_display",
                "storage_profile_key",
                "usb_profile_key",
                "smb_profile_key",
                "repo_conf_key",
            ):
                if legacy_field in row:
                    normalized[legacy_field] = str(row.get(legacy_field) or "").strip()
        out.append(normalized)
    out.sort(key=lambda item: (str(item.get("location") or ""), str(item.get("display_name") or "")))
    return out


def build_repository_groups(config: dict) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {"local": [], "usb": [], "smb": [], "storagebox": []}
    for repo in read_repository_store_for_api(config)["repositories"]:
        location = str(repo.get("location") or "").strip().lower()
        if location not in groups:
            groups[location] = []
        groups[location].append({
            **repo,
            "conf_key": str(repo.get("repository_key") or ""),
        })
    for rows in groups.values():
        rows.sort(key=lambda row: (str(row.get("backup_type") or ""), str(row.get("display_name") or "")))
    return groups


def repository_assignment_report(config: dict) -> dict[str, Any]:
    """Compare authoritative job assignments with canonical inventories."""
    from repository_context import jobs_dir
    from storage_objects_api import read_storage_store

    repositories = read_repository_store(config).get("repositories", [])
    repo_by_key = {str(row.get("repository_key") or "").strip(): row for row in repositories}
    storage_keys = {
        str(row.get("storage_key") or "").strip()
        for row in read_storage_store(config).get("storages", [])
        if str(row.get("storage_key") or "").strip()
    }
    actual: dict[str, list[str]] = {key: [] for key in repo_by_key}
    errors: list[dict[str, Any]] = []
    directory = jobs_dir(config)
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors.append({"code": "job_metadata_unreadable", "job_key": path.stem, "message": str(exc)})
            continue
        if not isinstance(job, dict):
            continue
        job_key = str(job.get("job_key") or path.stem).strip()
        repository_key = str(job.get("repository_key") or "").strip()
        if not repository_key:
            errors.append({
                "code": "job_repository_missing",
                "job_key": job_key,
                "message": "The job has no repository assignment. Open it in the Job Wizard and save a repository.",
            })
            continue
        repository = repo_by_key.get(repository_key)
        if not isinstance(repository, dict):
            errors.append({
                "code": "job_repository_not_found",
                "job_key": job_key,
                "repository_key": repository_key,
                "message": "The assigned repository does not exist. Open the job in the Job Wizard and select a valid repository.",
            })
            continue
        actual.setdefault(repository_key, []).append(job_key)

    mismatches: list[dict[str, Any]] = []
    for repository_key, repository in repo_by_key.items():
        storage_key = str(repository.get("storage_key") or "").strip()
        if not storage_key or storage_key not in storage_keys:
            errors.append({
                "code": "repository_storage_not_found",
                "repository_key": repository_key,
                "storage_key": storage_key,
                "message": "The repository references a missing storage target.",
            })
        expected = sorted(set(actual.get(repository_key, [])))
        stored_used_by = sorted({str(value).strip() for value in repository.get("used_by", []) if str(value).strip()})
        stored_source = sorted({str(value).strip() for value in repository.get("source_job_keys", []) if str(value).strip()})
        if stored_used_by != expected or stored_source != expected:
            mismatches.append({
                "repository_key": repository_key,
                "message": "Repository usage metadata differs from the authoritative job assignments.",
                "expected_job_keys": expected,
                "stored_used_by": stored_used_by,
                "stored_source_job_keys": stored_source,
            })
    return {
        "ok": not errors and not mismatches,
        "errors": errors,
        "usage_mismatches": mismatches,
        "assignments": actual,
    }


def reconcile_repository_usage(config: dict) -> dict[str, Any]:
    """Safely rebuild redundant repository usage lists from job metadata."""
    path = repositories_file(config)
    with inventory_lock(path.parent):
        report = repository_assignment_report(config)
        assignments = report.get("assignments") if isinstance(report.get("assignments"), dict) else {}
        current = read_repository_store(config)
        changed: list[str] = []
        rows = []
        for repository in current.get("repositories", []):
            key = str(repository.get("repository_key") or "").strip()
            expected = sorted({str(value).strip() for value in assignments.get(key, []) if str(value).strip()})
            used_by = sorted({str(value).strip() for value in repository.get("used_by", []) if str(value).strip()})
            source_jobs = sorted({str(value).strip() for value in repository.get("source_job_keys", []) if str(value).strip()})
            if used_by != expected or source_jobs != expected:
                repository = {**repository, "used_by": expected, "source_job_keys": expected, "updated_at": _now()}
                changed.append(key)
            rows.append(repository)
        if changed:
            write_repository_store(config, {"repositories": rows})
        final_report = repository_assignment_report(config)
        return {**final_report, "reconciled_repository_keys": changed}


def _secret_path_for_repository(config: dict, repository_key: str) -> Path:
    return _data_root(config) / "secrets" / f".borg-passphrase-{repository_key}"


def _storage_by_key(config: dict) -> dict[str, dict[str, Any]]:
    from storage_objects_api import read_storage_store
    return {
        str(row.get("storage_key") or ""): row
        for row in read_storage_store(config).get("storages", [])
        if str(row.get("storage_key") or "").strip()
    }


def _browse_relative_path(value: str) -> str:
    """Normalize an optional storage-relative path without allowing traversal."""
    text = str(value or "").strip()
    if text.startswith("/"):
        raise ValueError("Repository browse path must be relative to the storage target")
    text = text.strip("/")
    if not text:
        return ""
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ValueError("Repository browse path contains control characters")
    parts = text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Repository browse path contains unsafe path segments")
    return "/".join(parts)


def _browse_name_supported(name: str) -> bool:
    try:
        return _normalize_repo_segment(name) == name
    except ValueError:
        return False


def _managed_repository_paths(config: dict, storage_key: str) -> dict[str, dict[str, str]]:
    managed: dict[str, dict[str, str]] = {}
    for row in read_repository_store(config).get("repositories", []):
        if str(row.get("storage_key") or "").strip() != storage_key:
            continue
        relative = str(row.get("relative_path") or "").strip().strip("/")
        if not relative:
            continue
        managed[relative] = {
            "repository_key": str(row.get("repository_key") or "").strip(),
            "display_name": str(row.get("display_name") or row.get("repository_name") or "").strip(),
        }
    return managed


def _smb_storage_cleanup(config: dict, storage: dict[str, Any], mounted: dict[str, Any]):
    """Return cleanup for a temporary SMB mount unless the profile should stay mounted."""
    if mounted.get("message_code") != "smb_mount_success":
        return None
    if bool(storage.get("keep_mounted", False)):
        return None
    profile_key = str(storage.get("profile_key") or "")
    if not profile_key:
        return None
    from smb_profiles_api import run_smb_profile_action

    return lambda: run_smb_profile_action(config, profile_key, "unmount")


def _mount_smb_storage_if_needed(
    config: dict,
    storage: dict[str, Any],
    *,
    error_type: type[Exception] = RuntimeError,
):
    if str(storage.get("location") or storage.get("storage_type") or "").strip().lower() != "smb":
        return None
    from smb_profiles_api import run_smb_profile_action

    mounted = run_smb_profile_action(config, str(storage.get("profile_key") or ""), "mount")
    if not mounted.get("ok"):
        raise error_type(str(mounted.get("message") or "SMB mount failed"))
    return _smb_storage_cleanup(config, storage, mounted)


@contextmanager
def _local_storage_browse_path(config: dict, storage: dict[str, Any]):
    """Yield a mounted local base path and undo only mounts created here."""
    cleanup = _mount_smb_storage_if_needed(config, storage, error_type=ValueError)

    raw_base = str(storage.get("base_path") or storage.get("mount_path") or "").strip()
    if not raw_base:
        if cleanup:
            cleanup()
        raise ValueError("Storage base path is missing")
    try:
        yield Path(raw_base)
    finally:
        if cleanup:
            cleanup()


def _list_local_storage_directories(
    config: dict,
    storage: dict[str, Any],
    relative_path: str,
) -> list[dict[str, Any]]:
    with _local_storage_browse_path(config, storage) as raw_base:
        try:
            base = raw_base.resolve(strict=True)
            current = (base / relative_path).resolve(strict=True) if relative_path else base
            current.relative_to(base)
        except (OSError, ValueError) as exc:
            raise ValueError("Repository browse path does not exist inside the storage target") from exc
        if not current.is_dir():
            raise ValueError("Repository browse path is not a directory")
        if relative_path and _looks_like_borg_repository(current):
            return []
        try:
            directories = [
                {
                    "name": child.name,
                    "borg_repository": _looks_like_borg_repository(child),
                }
                for child in current.iterdir()
                if child.is_dir() and not child.is_symlink()
            ]
            return sorted(directories, key=lambda row: str(row["name"]).lower())
        except OSError as exc:
            raise ValueError(f"Repository directory cannot be listed: {exc}") from exc


def _ssh_storage_profile(storage: dict[str, Any]) -> dict[str, str]:
    return {
        "host": str(storage.get("host") or "").strip(),
        "port": str(storage.get("port") or "22").strip() or "22",
        "user": str(storage.get("user") or "").strip(),
        "base_path": str(storage.get("base_path") or "").strip(),
        "ssh_key": str(storage.get("ssh_key_path") or "").strip(),
    }


def _ssh_storage_browse_path(storage: dict[str, Any], relative_path: str) -> str:
    base = str(storage.get("base_path") or "").strip() or "."
    if base.startswith("/./"):
        base = f".{base[2:]}"
    base = base.rstrip("/") or "/"
    return posixpath.join(base, relative_path) if relative_path else base


def _list_ssh_storage_directories(storage: dict[str, Any], relative_path: str) -> list[str]:
    from storagebox_api import _storagebox_ssh_base_cmd

    profile = _ssh_storage_profile(storage)
    if not profile["host"] or not profile["user"]:
        raise ValueError("SSH storage target is incomplete")
    remote_path = _ssh_storage_browse_path(storage, relative_path)
    remote_command = f"ls -1Ap -- {shlex.quote(remote_path)}"
    try:
        proc = subprocess.run(
            _storagebox_ssh_base_cmd(profile) + [remote_command],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("ssh binary not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("SSH directory listing timed out") from exc
    output = _mask_repo_output(((proc.stdout or "") + "\n" + (proc.stderr or "")).strip())
    if proc.returncode != 0:
        first = next((line.strip() for line in output.splitlines() if line.strip()), "SSH directory listing failed")
        raise ValueError(first[:500])
    directories = []
    for line in (proc.stdout or "").splitlines():
        name = line.strip()
        if not name.endswith("/"):
            continue
        name = name.rstrip("/")
        if name and name not in {".", ".."} and "/" not in name:
            directories.append(name)
    return sorted(set(directories), key=str.lower)


def browse_repository_directories(config: dict, storage_key: str, relative_path: str = "") -> dict[str, Any]:
    """List one safe directory level inside a canonical storage target."""
    key = str(storage_key or "").strip()
    storage = _storage_by_key(config).get(key)
    if not storage:
        raise ValueError("Storage target not found")
    current = _browse_relative_path(relative_path)
    storage_type = str(storage.get("storage_type") or storage.get("location") or "").strip().lower()
    if storage_type == "ssh" or str(storage.get("location") or "").strip().lower() == "storagebox":
        if normalize_ssh_mode(str(storage.get("ssh_mode") or "shell")) == "borg_serve":
            raise ValueError("Directory browsing is not available for Borg serve only SSH profiles")
        entries = [
            {"name": name, "borg_repository": False}
            for name in _list_ssh_storage_directories(storage, current)
        ]
    else:
        entries = _list_local_storage_directories(config, storage, current)

    managed = _managed_repository_paths(config, key)
    directories = []
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        relative = f"{current}/{name}" if current else name
        existing = managed.get(relative, {})
        directories.append({
            "name": name,
            "relative_path": relative,
            "supported": all(_browse_name_supported(part) for part in relative.split("/")),
            "managed": bool(existing),
            "borg_repository": bool(entry.get("borg_repository")),
            "repository_key": str(existing.get("repository_key") or ""),
            "display_name": str(existing.get("display_name") or ""),
        })
    parent = current.rsplit("/", 1)[0] if "/" in current else ""
    return {
        "storage_key": key,
        "storage_name": str(storage.get("display_name") or key),
        "relative_path": current,
        "parent_path": parent,
        "directories": directories,
    }


def _repo_env(
    storage: dict[str, Any],
    passphrase_file: Path | None,
    config: dict | None = None,
    *,
    persistent_keys: bool = True,
    encryption: str = "",
) -> dict[str, str]:
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    # Never inherit this safety acknowledgement globally. Borg may access an
    # unknown unencrypted repository only when the canonical repository object
    # explicitly identifies it as unencrypted.
    env.pop("BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK", None)
    # Managed storage paths may legitimately change, for example when an SMB
    # profile receives a generated mount path. The repository identity still
    # has to match Borg's cache; this only acknowledges that changed location.
    env.pop("BORG_RELOCATED_REPO_ACCESS_IS_OK", None)
    env["BORG_RELOCATED_REPO_ACCESS_IS_OK"] = "yes"
    if str(encryption or "").strip().lower() == "none":
        env["BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK"] = "yes"
    if passphrase_file is not None:
        env["BORG_PASSCOMMAND"] = f"cat {shlex.quote(str(passphrase_file))}"
    from borg_ssh import configure_borg_ssh

    configure_borg_ssh(env, storage)
    if persistent_keys:
        from borg_key_store import apply_borg_key_environment

        env = apply_borg_key_environment(env, config or {})
    return env


def _mask_repo_output(text: str, passphrase: str = "") -> str:
    from security_utils import mask_secrets

    out = mask_secrets(str(text or ""))
    if passphrase:
        out = out.replace(passphrase, "***")
    return out


def _raise_borg_command_error(output: str, fallback: str) -> None:
    from borg_ssh import SSH_INTERRUPTION_MESSAGE, is_ssh_connection_interruption

    safe_output = _mask_repo_output(output)
    if is_ssh_connection_interruption(safe_output):
        raise RuntimeError(SSH_INTERRUPTION_MESSAGE)
    lowered = safe_output.lower()
    if "failed to create/acquire the lock" in lowered or "lock.exclusive" in lowered:
        raise RepositoryBusyError("Repository is currently in use by another Borg operation.")
    if "previously located at" in lowered or "relocated repository" in lowered:
        exc = ValueError(
            "Borg reports that this repository was previously accessed through another path. "
            "Mount the configured storage profile and retry the repository action."
        )
        exc.api_code = "repository_relocated"  # type: ignore[attr-defined]
        exc.api_status = 409  # type: ignore[attr-defined]
        raise exc
    if "no key file for repository" in lowered or "key file" in lowered and "not found" in lowered:
        raise RuntimeError(
            "The Borg keyfile is missing. Import a matching Borg key export for this repository."
        )
    first = next((line.strip() for line in safe_output.splitlines() if line.strip()), fallback)
    raise RuntimeError(first[:500])


@contextmanager
def _repository_access(config: dict, repository: dict[str, Any]):
    storage = _storage_by_key(config).get(str(repository.get("storage_key") or ""), {})
    if not storage:
        raise ValueError("Repository storage target was not found")
    repo_path = effective_repository_path(storage, str(repository.get("relative_path") or ""))
    cleanup = _mount_smb_storage_if_needed(config, storage)
    passphrase_ref = str(repository.get("passphrase_ref") or "").strip()
    passphrase_file = Path(passphrase_ref) if passphrase_ref else None
    if passphrase_file is not None and not passphrase_file.is_file():
        raise ValueError("Repository passphrase file is missing")
    try:
        yield storage, repo_path, passphrase_file
    finally:
        if cleanup:
            cleanup()


def _borg_info(
    config: dict,
    storage: dict[str, Any],
    repo_path: str,
    passphrase_file: Path | None,
    encryption: str = "",
) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["borg", "info", "--json", repo_path],
            capture_output=True,
            text=True,
            timeout=60,
            env=_repo_env(storage, passphrase_file, config, encryption=encryption),
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("borg binary not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("borg info timed out") from exc
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        _raise_borg_command_error(output, "borg info failed")
    try:
        payload = json.loads(proc.stdout or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("borg info returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("borg info returned an invalid response")
    return payload


def _borg_info_with_default_keys(
    storage: dict[str, Any],
    repo_path: str,
    passphrase_file: Path | None,
    encryption: str = "",
) -> dict[str, Any]:
    """Probe Borg's legacy default key directory during an explicit import."""
    proc = subprocess.run(
        ["borg", "info", "--json", repo_path],
        capture_output=True,
        text=True,
        timeout=60,
        env=_repo_env(
            storage,
            passphrase_file,
            persistent_keys=False,
            encryption=encryption,
        ),
        check=False,
    )
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        _raise_borg_command_error(output, "borg info failed")
    try:
        payload = json.loads(proc.stdout or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("borg info returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("borg info returned an invalid response")
    return payload


def _import_exported_repository_key(
    config: dict,
    storage: dict[str, Any],
    repo_path: str,
    passphrase_file: Path | None,
    key_data: str,
    encryption: str = "",
) -> None:
    from borg_key_store import ensure_borg_keys_dir, find_key_file

    encoded = str(key_data or "").strip().encode("utf-8")
    if not encoded or len(encoded) > 1024 * 1024:
        raise ValueError("Borg key export is empty or too large")
    first = encoded.splitlines()[0].decode("utf-8", "replace").strip()
    if not first.startswith("BORG_KEY "):
        raise ValueError("Borg key export has an invalid format")
    repository_id = first[len("BORG_KEY "):].strip().lower()
    if not repository_id or any(ch not in "0123456789abcdef" for ch in repository_id):
        raise ValueError("Borg key export has an invalid repository ID")
    key_dir = ensure_borg_keys_dir(config)
    existing = find_key_file(key_dir, repository_id)
    if existing is not None:
        if existing.read_bytes().strip() != encoded.strip():
            raise ValueError("A different key for this Borg repository already exists")
        return
    temp_path: Path | None = None
    try:
        import_dir = _data_root(config) / "config"
        import_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=import_dir, prefix=".key-import-", delete=False
        ) as handle:
            handle.write(encoded + b"\n")
            temp_path = Path(handle.name)
        os.chmod(temp_path, 0o600)
        proc = subprocess.run(
            ["borg", "key", "import", repo_path, str(temp_path)],
            capture_output=True,
            text=True,
            timeout=120,
            env=_repo_env(storage, passphrase_file, config, encryption=encryption),
            check=False,
        )
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            created = find_key_file(key_dir, repository_id)
            if created is not None:
                created.unlink(missing_ok=True)
            _raise_borg_command_error(output, "Borg key import failed")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _repository_by_key(config: dict, repository_key: str) -> dict[str, Any]:
    key = str(repository_key or "").strip()
    if not key:
        raise ValueError("repository_key is required")
    repository = next(
        (row for row in read_repository_store(config).get("repositories", []) if str(row.get("repository_key") or "") == key),
        None,
    )
    if not repository:
        raise ValueError("Repository not found")
    return repository


def _key_recovery_supported(encryption: str) -> bool:
    mode = str(encryption or "").strip().lower()
    return mode in ALLOWED_ENCRYPTION_MODES and mode != "none"


def _repository_key_error(message: str, code: str, status: int = 400) -> ValueError:
    exc = ValueError(message)
    exc.api_code = code  # type: ignore[attr-defined]
    exc.api_status = status  # type: ignore[attr-defined]
    return exc


def _parse_borg_key_export_repository_id(key_data: str) -> str:
    encoded = str(key_data or "").strip().encode("utf-8")
    if not encoded or len(encoded) > 1024 * 1024:
        raise _repository_key_error("Borg key export is empty or too large", "repository_key_invalid")
    first = encoded.splitlines()[0].decode("utf-8", "replace").strip()
    if not first.startswith("BORG_KEY "):
        raise _repository_key_error("Borg key export has an invalid format", "repository_key_invalid")
    repository_id = first[len("BORG_KEY "):].strip().lower()
    if not repository_id or any(ch not in "0123456789abcdef" for ch in repository_id):
        raise _repository_key_error("Borg key export has an invalid repository ID", "repository_key_invalid")
    return repository_id


def _write_temp_borg_key_export(config: dict, key_data: str) -> Path:
    encoded = str(key_data or "").strip().encode("utf-8")
    import_dir = _data_root(config) / "config"
    import_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="wb", dir=import_dir, prefix=".key-recovery-import-", delete=False) as handle:
        handle.write(encoded + b"\n")
        temp_path = Path(handle.name)
    os.chmod(temp_path, 0o600)
    return temp_path


def _export_borg_repository_key(
    config: dict,
    storage: dict[str, Any],
    repo_path: str,
    passphrase_file: Path | None,
    encryption: str,
) -> str:
    export_dir = _data_root(config) / "config"
    export_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=export_dir, prefix=".key-recovery-export-", delete=False) as handle:
            temp_path = Path(handle.name)
        os.chmod(temp_path, 0o600)
        proc = subprocess.run(
            ["borg", "key", "export", repo_path, str(temp_path)],
            capture_output=True,
            text=True,
            timeout=120,
            env=_repo_env(storage, passphrase_file, config, encryption=encryption),
            check=False,
        )
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            _raise_borg_command_error(output, "Borg key export failed")
        key_data = temp_path.read_text(encoding="utf-8")
        _parse_borg_key_export_repository_id(key_data)
        return key_data.strip() + "\n"
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _import_borg_repository_key(
    config: dict,
    storage: dict[str, Any],
    repo_path: str,
    passphrase_file: Path | None,
    key_data: str,
    encryption: str,
) -> None:
    temp_path: Path | None = None
    try:
        temp_path = _write_temp_borg_key_export(config, key_data)
        proc = subprocess.run(
            ["borg", "key", "import", repo_path, str(temp_path)],
            capture_output=True,
            text=True,
            timeout=120,
            env=_repo_env(storage, passphrase_file, config, encryption=encryption),
            check=False,
        )
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            _raise_borg_command_error(output, "Borg key import failed")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _safe_key_export_filename(repository: dict[str, Any], repository_id: str) -> str:
    name = _slug(str(repository.get("display_name") or repository.get("repository_name") or "repository"), "repository")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = str(repository_id or "").strip().lower()[:12] or "unknown"
    return f"borg-key-{name}-{suffix}-{stamp}.txt"


def _update_repository_key_recovery_fields(
    config: dict,
    repository_key: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    key = str(repository_key or "").strip()
    store = read_repository_store(config)
    rows: list[dict[str, Any]] = []
    updated: dict[str, Any] | None = None
    for row in store.get("repositories", []):
        if str(row.get("repository_key") or "") == key:
            updated = {**row, **fields, "updated_at": _now()}
            rows.append(updated)
        else:
            rows.append(row)
    if updated is None:
        raise ValueError("Repository not found")
    write_repository_store(config, {"repositories": rows})
    return updated


def export_repository_key(
    config: dict,
    repository_key: str,
    *,
    audit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repository = _repository_by_key(config, repository_key)
    encryption = str(repository.get("encryption") or "").strip().lower()
    if not _key_recovery_supported(encryption):
        raise _repository_key_error("This repository encryption mode does not use a Borg key export.", "repository_key_unsupported")
    with _repository_access(config, repository) as (storage, repo_path, passphrase_file):
        from jobs_api import is_resource_active

        if is_resource_active(config, f"repo:{repo_path}"):
            raise RepositoryBusyError("Repository is currently in use by another Borg operation.")
        try:
            key_data = _export_borg_repository_key(config, storage, repo_path, passphrase_file, encryption)
            exported_id = _parse_borg_key_export_repository_id(key_data)
            expected_id = str(repository.get("borg_repository_id") or "").strip().lower()
            if expected_id and exported_id != expected_id:
                raise _repository_key_error(
                    "The exported Borg key belongs to a different repository ID.",
                    "repository_key_mismatch",
                    409,
                )
            exported_at = _now()
            updated = _update_repository_key_recovery_fields(config, str(repository.get("repository_key") or ""), {
                "borg_key_exported_at": exported_at,
                "borg_key_repository_id": exported_id,
                "borg_repository_id": expected_id or exported_id,
            })
            _write_repository_lifecycle_audit(
                config,
                updated,
                action="key_export",
                status="success",
                details={"repository_id": exported_id},
                audit_context=audit_context,
            )
            return {
                "ok": True,
                "repository_key": str(repository.get("repository_key") or ""),
                "repository_id": exported_id,
                "filename": _safe_key_export_filename(repository, exported_id),
                "key_data": key_data,
                "exported_at": exported_at,
            }
        except Exception as exc:
            _write_repository_lifecycle_audit(
                config,
                repository,
                action="key_export",
                status="failed",
                details={"error": type(exc).__name__},
                audit_context=audit_context,
            )
            raise


def import_repository_key(
    config: dict,
    repository_key: str,
    key_data: str,
    *,
    audit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repository = _repository_by_key(config, repository_key)
    encryption = str(repository.get("encryption") or "").strip().lower()
    if not _key_recovery_supported(encryption):
        raise _repository_key_error("This repository encryption mode does not use a Borg key export.", "repository_key_unsupported")
    imported_id = _parse_borg_key_export_repository_id(key_data)
    expected_id = str(repository.get("borg_repository_id") or repository.get("borg_key_repository_id") or "").strip().lower()
    if not expected_id:
        raise _repository_key_error(
            "Repository ID is unknown. Refresh repository information before importing a Borg key.",
            "repository_id_missing",
            409,
        )
    if imported_id != expected_id:
        raise _repository_key_error(
            "The selected Borg key belongs to a different repository ID.",
            "repository_key_mismatch",
            409,
        )
    with _repository_access(config, repository) as (storage, repo_path, passphrase_file):
        from jobs_api import is_resource_active

        if is_resource_active(config, f"repo:{repo_path}"):
            raise RepositoryBusyError("Repository is currently in use by another Borg operation.")
        try:
            _import_borg_repository_key(config, storage, repo_path, passphrase_file, key_data, encryption)
            info_fields = _borg_info_fields(_borg_info(config, storage, repo_path, passphrase_file, encryption))
            live_id = str(info_fields.get("borg_repository_id") or "").strip().lower()
            if live_id and live_id != expected_id:
                raise _repository_key_error(
                    "Borg reported a different repository ID after key import.",
                    "repository_key_mismatch",
                    409,
                )
            imported_at = _now()
            fields: dict[str, Any] = {
                "borg_key_imported_at": imported_at,
                "borg_key_repository_id": expected_id,
                "borg_repository_id": live_id or expected_id,
                "borg_last_modified": str(info_fields.get("borg_last_modified") or repository.get("borg_last_modified") or ""),
            }
            if str(encryption).startswith("keyfile"):
                from borg_key_store import borg_keys_dir, find_key_file

                key_file = find_key_file(borg_keys_dir(config), expected_id)
                fields["keyfile_ref"] = str(key_file) if key_file is not None else str(repository.get("keyfile_ref") or "")
            updated = _update_repository_key_recovery_fields(config, str(repository.get("repository_key") or ""), fields)
            _write_repository_lifecycle_audit(
                config,
                updated,
                action="key_import",
                status="success",
                details={"repository_id": expected_id},
                audit_context=audit_context,
            )
            return {
                "ok": True,
                "repository_key": str(repository.get("repository_key") or ""),
                "repository_id": expected_id,
                "imported_at": imported_at,
            }
        except Exception as exc:
            _write_repository_lifecycle_audit(
                config,
                repository,
                action="key_import",
                status="failed",
                details={"error": type(exc).__name__},
                audit_context=audit_context,
            )
            raise


def _borg_list(
    config: dict,
    storage: dict[str, Any],
    repo_path: str,
    passphrase_file: Path | None,
    encryption: str = "",
) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["borg", "list", "--json", repo_path],
            capture_output=True,
            text=True,
            timeout=60,
            env=_repo_env(storage, passphrase_file, config, encryption=encryption),
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("borg binary not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("borg list timed out") from exc
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        _raise_borg_command_error(output, "borg list failed")
    try:
        payload = json.loads(proc.stdout or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("borg list returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("borg list returned an invalid response")
    return payload


def _borg_info_fields(payload: dict[str, Any], archive_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    repository = payload.get("repository") if isinstance(payload.get("repository"), dict) else {}
    encryption = payload.get("encryption") if isinstance(payload.get("encryption"), dict) else {}
    cache = payload.get("cache") if isinstance(payload.get("cache"), dict) else {}
    stats = cache.get("stats") if isinstance(cache.get("stats"), dict) else {}
    stats = dict(stats)
    if isinstance(archive_payload, dict):
        archives = archive_payload.get("archives") if isinstance(archive_payload.get("archives"), list) else []
        stats["archives_count"] = len(archives)
    return {
        "encryption": str(encryption.get("mode") or "").strip(),
        "borg_repository_id": str(repository.get("id") or "").strip(),
        "borg_last_modified": str(repository.get("last_modified") or "").strip(),
        "repository_stats": stats,
    }


def refresh_repository_info(config: dict, repository_key: str) -> dict[str, Any]:
    key = str(repository_key or "").strip()
    store = read_repository_store(config)
    rows = store["repositories"]
    repository = next((row for row in rows if str(row.get("repository_key") or "") == key), None)
    if not repository:
        raise ValueError("Repository not found")
    storage = _storage_by_key(config).get(str(repository.get("storage_key") or ""), {})
    repo_path = effective_repository_path(storage, str(repository.get("relative_path") or ""))
    from jobs_api import is_resource_active
    if is_resource_active(config, f"repo:{repo_path}"):
        _record_repository_info_busy(config, key, _now())
        raise RepositoryBusyError("Repository is currently in use by a backup job.")
    cleanup = _mount_smb_storage_if_needed(config, storage)
    passphrase_ref = str(repository.get("passphrase_ref") or "").strip()
    passphrase_file = Path(passphrase_ref) if passphrase_ref else None
    if passphrase_file is not None and not passphrase_file.is_file():
        raise ValueError("Repository passphrase file is missing")
    encryption = str(repository.get("encryption") or "").strip()
    try:
        info_payload = _borg_info(config, storage, repo_path, passphrase_file, encryption)
        archive_payload = _borg_list(config, storage, repo_path, passphrase_file, encryption)
    except RepositoryBusyError:
        _record_repository_info_busy(config, key, _now())
        raise
    finally:
        if cleanup:
            cleanup()
    fields = _borg_info_fields(info_payload, archive_payload)
    refreshed_at = _now()
    result_holder: dict[str, Any] = {}
    def apply_refresh(latest_store: dict[str, Any]) -> dict[str, Any]:
        latest_rows = latest_store["repositories"]
        latest_repository = next((row for row in latest_rows if str(row.get("repository_key") or "") == key), None)
        if not latest_repository:
            raise ValueError("Repository was removed while its information was refreshed")
        updated_row = {
            **latest_repository,
            **{field: value for field, value in fields.items() if value not in ("", None, {})},
            "last_test_status": "ok",
            "last_seen_at": refreshed_at,
            "last_info_refresh_at": refreshed_at,
            "last_info_refresh_status": "success",
            "last_info_refresh_error": "",
            "updated_at": refreshed_at,
        }
        result_holder["repository"] = updated_row
        return {"repositories": [updated_row if str(row.get("repository_key") or "") == key else row for row in latest_rows]}
    update_repository_store(config, apply_refresh)
    updated = result_holder["repository"]
    return {"ok": True, "repository": enrich_repository_display_fields(updated)}


def _parse_repository_timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _repository_info_is_due(
    repository: dict[str, Any],
    now: datetime,
    *,
    max_age_hours: int,
    retry_after_hours: int,
) -> bool:
    status = str(repository.get("last_info_refresh_status") or "").strip().lower()
    stats = repository.get("repository_stats") if isinstance(repository.get("repository_stats"), dict) else {}
    if status != "error" and not stats:
        return True
    timestamp = _parse_repository_timestamp(
        repository.get("last_info_refresh_at") or repository.get("last_seen_at")
    )
    if timestamp is None:
        return True
    hours = retry_after_hours if status in {"error", "busy"} else max_age_hours
    return timestamp <= now - timedelta(hours=max(1, int(hours)))


def _record_repository_info_error(config: dict, repository_key: str, message: str, checked_at: str) -> None:
    def apply_error(store: dict[str, Any]) -> dict[str, Any]:
        return {"repositories": [{
            **row,
            "last_info_refresh_at": checked_at,
            "last_info_refresh_status": "error",
            "last_info_refresh_error": _mask_repo_output(str(message or "Repository information refresh failed"))[:500],
            "updated_at": checked_at,
        } if str(row.get("repository_key") or "") == repository_key else row for row in store["repositories"]]}
    update_repository_store(config, apply_error)


def _record_repository_info_warning(config: dict, repository_key: str, message: str, checked_at: str) -> None:
    def apply_warning(store: dict[str, Any]) -> dict[str, Any]:
        return {"repositories": [{
            **row,
            "last_info_refresh_at": checked_at,
            "last_info_refresh_status": "warning",
            "last_info_refresh_error": _mask_repo_output(str(message or "Repository storage is currently unavailable"))[:500],
            "updated_at": checked_at,
        } if str(row.get("repository_key") or "") == repository_key else row for row in store["repositories"]]}
    update_repository_store(config, apply_warning)


def _record_repository_info_busy(config: dict, repository_key: str, checked_at: str) -> None:
    def apply_busy(store: dict[str, Any]) -> dict[str, Any]:
        return {"repositories": [{
            **row,
            "last_info_refresh_at": checked_at,
            "last_info_refresh_status": "busy",
            "last_info_refresh_error": "Repository information refresh was deferred because the repository is in use.",
            "updated_at": checked_at,
        } if str(row.get("repository_key") or "") == repository_key else row for row in store["repositories"]]}
    update_repository_store(config, apply_busy)


def refresh_due_repository_info(
    config: dict,
    *,
    max_age_hours: int = 24,
    retry_after_hours: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh cached Borg information that is missing, stale, or due for retry."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    repositories = read_repository_store(config)["repositories"]
    from storage_objects_api import read_storage_store
    storages = {
        str(row.get("storage_key") or ""): row
        for row in read_storage_store(config).get("storages", [])
    }
    from jobs_api import active_resource_locks
    active_resources = {
        str(row.get("resource") or "").strip()
        for row in active_resource_locks(config)
        if str(row.get("resource") or "").strip()
    }
    due_keys = [
        str(row.get("repository_key") or "").strip()
        for row in repositories
        if str(row.get("repository_key") or "").strip()
        and (
            (
                str(row.get("last_info_refresh_status") or "").strip().lower() == "error"
                and str(row.get("storage_key") or "") in storages
                and f"repo:{effective_repository_path(storages[str(row.get('storage_key') or '')], str(row.get('relative_path') or ''))}" in active_resources
            )
            or _repository_info_is_due(
                row,
                current,
                max_age_hours=max_age_hours,
                retry_after_hours=retry_after_hours,
            )
        )
    ]
    refreshed = 0
    failed = 0
    deferred = 0
    errors = []
    for repository_key in due_keys:
        try:
            refresh_repository_info(config, repository_key)
            refreshed += 1
        except RepositoryBusyError:
            deferred += 1
            _record_repository_info_busy(config, repository_key, _now())
        except Exception as exc:
            failed += 1
            safe_message = _mask_repo_output(str(exc or "Repository information refresh failed"))[:500]
            _record_repository_info_error(config, repository_key, safe_message, _now())
            errors.append({"repository_key": repository_key, "error": safe_message})
    return {
        "checked": len(repositories),
        "due": len(due_keys),
        "refreshed": refreshed,
        "failed": failed,
        "deferred": deferred,
        "errors": errors,
    }


def _truthy_config(value: Any, default: bool = True) -> bool:
    raw = str(value if value is not None else "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "enabled"}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def repository_info_refresh_settings(config: dict) -> dict[str, Any]:
    try:
        from config_api import read_expanded_conf, read_raw_conf

        conf = read_expanded_conf(config)
        conf.update(read_raw_conf(config))
    except Exception:
        conf = config
    return {
        "enabled": _truthy_config(conf.get("REPOSITORY_INFO_REFRESH_ENABLED"), False),
        "interval_hours": _bounded_int(
            conf.get("REPOSITORY_INFO_REFRESH_INTERVAL_HOURS"),
            REPOSITORY_INFO_REFRESH_DEFAULT_INTERVAL_HOURS,
            1,
            24 * 30,
        ),
        "retry_hours": _bounded_int(
            conf.get("REPOSITORY_INFO_REFRESH_RETRY_HOURS"),
            REPOSITORY_INFO_REFRESH_DEFAULT_RETRY_HOURS,
            1,
            24 * 7,
        ),
    }


def _repository_info_refresh_state_defaults() -> dict[str, Any]:
    return {
        "schema_version": REPOSITORY_INFO_REFRESH_STATE_VERSION,
        "updated_at": "",
        "last_run_at": "",
        "next_run_at": "",
        "last_result": {
            "checked": 0,
            "refreshed": 0,
            "failed": 0,
            "deferred": 0,
            "errors": [],
        },
    }


def _read_repository_info_refresh_state(config: dict) -> dict[str, Any]:
    path = repository_info_refresh_state_file(config)
    defaults = _repository_info_refresh_state_defaults()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return defaults
    if not isinstance(payload, dict):
        return defaults
    result = {**defaults, **payload}
    if not isinstance(result.get("last_result"), dict):
        result["last_result"] = defaults["last_result"]
    return result


def _write_repository_info_refresh_state(config: dict, payload: dict[str, Any]) -> None:
    path = repository_info_refresh_state_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with inventory_lock(path.parent):
        atomic_write_json(path, payload, mode=0o600)


def _format_repository_timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _latest_repository_info_timestamp(config: dict) -> datetime | None:
    latest: datetime | None = None
    for row in read_repository_store(config).get("repositories", []):
        for raw in (row.get("last_info_refresh_at"), row.get("last_seen_at")):
            parsed = _parse_repository_timestamp(raw)
            if parsed is not None and (latest is None or parsed > latest):
                latest = parsed
    return latest


def _repository_info_missing_stats(config: dict) -> bool:
    for row in read_repository_store(config).get("repositories", []):
        stats = row.get("repository_stats") if isinstance(row.get("repository_stats"), dict) else {}
        status = str(row.get("last_info_refresh_status") or "").strip().lower()
        if not stats and status not in {"error", "warning", "busy"}:
            return True
    return False


def _compute_repository_info_next_run(
    config: dict,
    settings: dict[str, Any],
    state: dict[str, Any],
    now: datetime,
    *,
    after_run: bool = False,
) -> datetime | None:
    if not settings.get("enabled"):
        return None
    last_result = state.get("last_result") if isinstance(state.get("last_result"), dict) else {}
    retry_due = _repository_info_result_requires_retry(config, last_result)
    interval_hours = (
        int(settings.get("retry_hours") or REPOSITORY_INFO_REFRESH_DEFAULT_RETRY_HOURS)
        if retry_due
        else int(settings.get("interval_hours") or REPOSITORY_INFO_REFRESH_DEFAULT_INTERVAL_HOURS)
    )
    interval = timedelta(hours=interval_hours)
    if after_run:
        return now + interval
    last_run = _parse_repository_timestamp(state.get("last_run_at"))
    if last_run is None:
        last_run = _latest_repository_info_timestamp(config)
    if last_run is None or _repository_info_missing_stats(config):
        return now
    return last_run + interval


def _repository_storage_location(repository: dict[str, Any], storage: dict[str, Any]) -> str:
    return str(
        storage.get("location")
        or storage.get("storage_type")
        or repository.get("location")
        or repository.get("storage_type")
        or repository.get("storage_name")
        or ""
    ).strip().lower()


def _is_removable_or_mount_storage_unavailable(
    repository: dict[str, Any],
    storage: dict[str, Any],
    exc: Exception,
) -> bool:
    location = _repository_storage_location(repository, storage)
    if location not in {"smb", "usb"}:
        return False
    message = str(exc or "").lower()
    unavailable_markers = (
        "not mounted",
        "could not be mounted",
        "couldn't be mounted",
        "failed to mount",
        "mount point",
        "mountpoint",
        "no such file or directory",
        "does not exist",
        "not found",
        "is not a directory",
        "stale file handle",
        "transport endpoint is not connected",
        "host is down",
        "network is unreachable",
    )
    return any(marker in message for marker in unavailable_markers)


def _repository_info_display_status(repository: dict[str, Any], storage: dict[str, Any]) -> str:
    status = str(repository.get("last_info_refresh_status") or "").strip().lower()
    error = str(repository.get("last_info_refresh_error") or "").strip()
    if status == "error" and error and _is_removable_or_mount_storage_unavailable(
        repository,
        storage,
        RuntimeError(error),
    ):
        return "warning"
    return status


def _repository_info_result_requires_retry(config: dict, result: dict[str, Any]) -> bool:
    if int(result.get("deferred") or 0) > 0:
        return True
    failed = int(result.get("failed") or 0)
    if failed <= 0:
        return False
    errors = result.get("errors") if isinstance(result.get("errors"), list) else []
    if not errors:
        return True
    repositories = {
        str(row.get("repository_key") or ""): row
        for row in read_repository_store(config).get("repositories", [])
    }
    storages = _storage_by_key(config)
    classified = 0
    for item in errors:
        if not isinstance(item, dict):
            return True
        key = str(item.get("repository_key") or "").strip()
        repository = repositories.get(key)
        if not repository:
            return True
        storage = storages.get(str(repository.get("storage_key") or ""), {})
        error = RuntimeError(str(item.get("error") or ""))
        if not _is_removable_or_mount_storage_unavailable(repository, storage, error):
            return True
        classified += 1
    return classified < failed


def refresh_all_repository_info(config: dict) -> dict[str, Any]:
    """Refresh cached Borg information for every managed repository once."""
    repositories = read_repository_store(config).get("repositories", [])
    storages = _storage_by_key(config)
    checked = len(repositories)
    refreshed = 0
    warning = 0
    failed = 0
    deferred = 0
    errors: list[dict[str, str]] = []
    for repository in repositories:
        key = str(repository.get("repository_key") or "").strip()
        if not key:
            continue
        storage = storages.get(str(repository.get("storage_key") or ""), {})
        try:
            refresh_repository_info(config, key)
            refreshed += 1
        except RepositoryBusyError:
            deferred += 1
            _record_repository_info_busy(config, key, _now())
        except Exception as exc:
            safe_message = _mask_repo_output(str(exc or "Repository information refresh failed"))[:500]
            if _is_removable_or_mount_storage_unavailable(repository, storage, exc):
                warning += 1
                _record_repository_info_warning(config, key, safe_message, _now())
            else:
                failed += 1
                _record_repository_info_error(config, key, safe_message, _now())
                errors.append({"repository_key": key, "error": safe_message})
    return {
        "checked": checked,
        "refreshed": refreshed,
        "warning": warning,
        "failed": failed,
        "deferred": deferred,
        "errors": errors,
    }


def signal_repository_info_refresh_config_changed() -> None:
    _REFRESH_WAKE_EVENT.set()


def run_repository_info_refresh_scheduler(
    config: dict,
    *,
    log_fn: Callable[[str], None] | None = None,
    startup_delay_seconds: int = 300,
) -> None:
    """Run the automatic repository info refresh without hourly polling."""
    with _REFRESH_LOCK:
        _REFRESH_RUNTIME_STATE.update({
            "worker_started": True,
            "worker_started_at": _now(),
            "worker_state": "startup_wait",
            "current_run_started_at": "",
            "last_schedule_reason": "startup",
        })
    if _REFRESH_WAKE_EVENT.wait(max(0, int(startup_delay_seconds))):
        _REFRESH_WAKE_EVENT.clear()
    while True:
        settings = repository_info_refresh_settings(config)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        state = _read_repository_info_refresh_state(config)
        if not settings["enabled"]:
            disabled_payload = {
                **state,
                "schema_version": REPOSITORY_INFO_REFRESH_STATE_VERSION,
                "updated_at": _now(),
                "next_run_at": "",
            }
            _write_repository_info_refresh_state(config, disabled_payload)
            with _REFRESH_LOCK:
                _REFRESH_RUNTIME_STATE.update({
                    "worker_state": "disabled",
                    "current_run_started_at": "",
                    "last_schedule_reason": "disabled",
                })
            _REFRESH_WAKE_EVENT.wait(24 * 60 * 60)
            _REFRESH_WAKE_EVENT.clear()
            continue

        next_run = _compute_repository_info_next_run(config, settings, state, now)
        if next_run is None:
            timeout = 24 * 60 * 60
        else:
            timeout = max(0.0, (next_run - now).total_seconds())
        scheduled_payload = {
            **state,
            "schema_version": REPOSITORY_INFO_REFRESH_STATE_VERSION,
            "updated_at": _now(),
            "next_run_at": _format_repository_timestamp(next_run),
        }
        _write_repository_info_refresh_state(config, scheduled_payload)
        with _REFRESH_LOCK:
            _REFRESH_RUNTIME_STATE.update({
                "worker_state": "sleeping" if timeout > 0 else "due",
                "current_run_started_at": "",
                "last_schedule_reason": "scheduled",
            })
        if timeout > 0 and _REFRESH_WAKE_EVENT.wait(timeout):
            _REFRESH_WAKE_EVENT.clear()
            continue

        _REFRESH_WAKE_EVENT.clear()
        started_at = _now()
        with _REFRESH_LOCK:
            _REFRESH_RUNTIME_STATE.update({
                "worker_state": "running",
                "current_run_started_at": started_at,
                "last_schedule_reason": "running",
            })
        try:
            result = refresh_all_repository_info(config)
        except Exception as exc:
            result = {
                "checked": 0,
                "refreshed": 0,
                "warning": 0,
                "failed": 1,
                "deferred": 0,
                "errors": [{"repository_key": "", "error": _mask_repo_output(str(exc))[:500]}],
            }
        finished = datetime.now(timezone.utc).replace(microsecond=0)
        next_after_run = _compute_repository_info_next_run(
            config,
            repository_info_refresh_settings(config),
            {"last_run_at": _format_repository_timestamp(finished), "last_result": result},
            finished,
            after_run=True,
        )
        persisted = {
            "schema_version": REPOSITORY_INFO_REFRESH_STATE_VERSION,
            "updated_at": _format_repository_timestamp(finished),
            "last_run_at": _format_repository_timestamp(finished),
            "next_run_at": _format_repository_timestamp(next_after_run),
            "last_result": result,
        }
        _write_repository_info_refresh_state(config, persisted)
        with _REFRESH_LOCK:
            _REFRESH_RUNTIME_STATE.update({
                "worker_state": "sleeping",
                "current_run_started_at": "",
                "last_schedule_reason": "completed",
            })
        if log_fn:
            log_fn(
                "Repository information refresh completed: "
                f"checked={result.get('checked')} refreshed={result.get('refreshed')} "
                f"warning={result.get('warning')} deferred={result.get('deferred')} "
                f"failed={result.get('failed')} "
                f"next_run_at={persisted.get('next_run_at') or 'disabled'}"
            )


def get_repository_info_refresh_status(config: dict) -> dict[str, Any]:
    settings = repository_info_refresh_settings(config)
    persisted = _read_repository_info_refresh_state(config)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if settings["enabled"] and not persisted.get("next_run_at"):
        next_run = _compute_repository_info_next_run(config, settings, persisted, now)
        persisted["next_run_at"] = _format_repository_timestamp(next_run)
    repositories = read_repository_store(config).get("repositories", [])
    storages = _storage_by_key(config)
    details = []
    counts = {"success": 0, "warning": 0, "error": 0, "busy": 0, "pending": 0}
    for row in repositories:
        storage = storages.get(str(row.get("storage_key") or ""), {})
        status = _repository_info_display_status(row, storage)
        stats = row.get("repository_stats") if isinstance(row.get("repository_stats"), dict) else {}
        if status == "success":
            counts["success"] += 1
        elif status == "warning":
            counts["warning"] += 1
        elif status == "error":
            counts["error"] += 1
        elif status == "busy":
            counts["busy"] += 1
        else:
            counts["pending"] += 1
        details.append({
            "repository_key": str(row.get("repository_key") or ""),
            "display_name": str(row.get("display_name") or row.get("repository_name") or row.get("repository_key") or ""),
            "storage_name": str(row.get("storage_name") or row.get("location") or ""),
            "location": _repository_storage_location(row, storage),
            "last_info_refresh_at": str(row.get("last_info_refresh_at") or row.get("last_seen_at") or ""),
            "last_info_refresh_status": status or ("pending" if not stats else "unknown"),
            "last_info_refresh_error": str(row.get("last_info_refresh_error") or ""),
        })
    with _REFRESH_LOCK:
        runtime = dict(_REFRESH_RUNTIME_STATE)
    return {
        "enabled": bool(settings["enabled"]),
        "interval_hours": int(settings["interval_hours"]),
        "retry_hours": int(settings["retry_hours"]),
        "plugin_pid": os.getpid(),
        "worker_started": bool(runtime.get("worker_started")),
        "worker_state": str(runtime.get("worker_state") or "stopped"),
        "worker_started_at": str(runtime.get("worker_started_at") or ""),
        "current_run_started_at": str(runtime.get("current_run_started_at") or ""),
        "last_run_at": str(persisted.get("last_run_at") or ""),
        "next_run_at": str(persisted.get("next_run_at") or ""),
        "last_result": persisted.get("last_result") if isinstance(persisted.get("last_result"), dict) else {},
        "repository_count": len(repositories),
        "counts": counts,
        "details": details,
    }


def get_repository_archives(config: dict, repository_key: str, limit: int = 100) -> dict[str, Any]:
    key = str(repository_key or "").strip()
    maximum = max(1, min(int(limit or 100), 500))
    store = read_repository_store(config)
    repository = next(
        (row for row in store.get("repositories", []) if str(row.get("repository_key") or "") == key),
        None,
    )
    if not repository:
        raise ValueError("Repository not found")
    storage = _storage_by_key(config).get(str(repository.get("storage_key") or ""), {})
    cleanup = _mount_smb_storage_if_needed(config, storage)
    repo_path = effective_repository_path(storage, str(repository.get("relative_path") or ""))
    passphrase_ref = str(repository.get("passphrase_ref") or "").strip()
    passphrase_file = Path(passphrase_ref) if passphrase_ref else None
    if passphrase_file is not None and not passphrase_file.is_file():
        raise ValueError("Repository passphrase file is missing")
    encryption = str(repository.get("encryption") or "").strip()
    try:
        payload = _borg_list(config, storage, repo_path, passphrase_file, encryption)
    finally:
        if cleanup:
            cleanup()
    rows = payload.get("archives") if isinstance(payload.get("archives"), list) else []
    rows = [row for row in rows if isinstance(row, dict)]
    rows.sort(
        key=lambda row: (
            _parse_repository_timestamp(row.get("start") or row.get("end"))
            or datetime.min.replace(tzinfo=timezone.utc),
            str(row.get("name") or ""),
        ),
        reverse=True,
    )
    archives = []
    for row in rows[:maximum]:
        archives.append({
            "name": str(row.get("name") or ""),
            "id": str(row.get("id") or ""),
            "start": str(row.get("start") or ""),
            "end": str(row.get("end") or ""),
            "duration": row.get("duration"),
        })
    return {"repository_key": key, "archive_count": len(rows), "archives": archives}


def _validate_repository_archive_name(value: Any) -> str:
    name = str(value or "")
    if not name.strip() or len(name) > 255:
        raise ValueError("Archive name is invalid")
    if "::" in name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("Archive name is invalid")
    return name


def _validate_repository_archive_path(value: Any) -> str:
    path = str(value or "").rstrip("/")
    if not path:
        return ""
    if len(path) > 4096 or path.startswith("/"):
        raise ValueError("Archive path is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise ValueError("Archive path is invalid")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts) or posixpath.normpath(path) != path:
        raise ValueError("Archive path is invalid")
    return path


def get_repository_archive_files(
    config: dict,
    repository_key: str,
    archive: str,
    path: str = "",
) -> dict[str, Any]:
    """Browse one repository archive without requiring a backup-job assignment."""
    repository = _repository_by_key(config, repository_key)
    archive_name = _validate_repository_archive_name(archive)
    archive_path = _validate_repository_archive_path(path)

    with _repository_access(config, repository) as (storage, repo_path, passphrase_file):
        from jobs_api import is_resource_active

        if is_resource_active(config, f"repo:{repo_path}"):
            raise RepositoryBusyError("Repository is currently in use by another Borg operation.")
        encryption = str(repository.get("encryption") or "").strip()
        env = _repo_env(storage, passphrase_file, config, encryption=encryption)
        from archive_browser import list_archive_directory

        try:
            files = list_archive_directory(repo_path, archive_name, archive_path, env)
        except RuntimeError as exc:
            _raise_borg_command_error(str(exc), "borg archive listing failed")

    return {
        "repository_key": str(repository.get("repository_key") or ""),
        "archive": archive_name,
        "path": archive_path,
        "files": files,
    }


def _repository_lifecycle_audit_file(config: dict) -> Path:
    return _data_root(config) / "config" / "repository-lifecycle.log.jsonl"


def _write_repository_lifecycle_audit(
    config: dict,
    repository: dict[str, Any],
    *,
    action: str,
    status: str,
    details: dict[str, Any] | None = None,
    audit_context: dict[str, Any] | None = None,
) -> None:
    path = _repository_lifecycle_audit_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    context = audit_context if isinstance(audit_context, dict) else {}
    payload = {
        "timestamp": _now(),
        "action": str(action or ""),
        "status": str(status or ""),
        "actor": str(context.get("actor") or "system"),
        "actor_role": str(context.get("actor_role") or "system"),
        "auth_method": str(context.get("auth_method") or "internal"),
        "request_id": str(context.get("request_id") or ""),
        "repository_key": str(repository.get("repository_key") or ""),
        "repository_id": str(repository.get("borg_repository_id") or ""),
        "display_name": str(repository.get("display_name") or ""),
        "storage_key": str(repository.get("storage_key") or ""),
        "details": details if isinstance(details, dict) else {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _repository_lifecycle_context(config: dict, repository_key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    from check_api import CheckManager
    from jobs_api import JobManager, is_resource_active
    from repository_context import jobs_using_repository
    from restore_api import list_restore_runs

    key = str(repository_key or "").strip()
    store = read_repository_store(config)
    repository = next(
        (row for row in store.get("repositories", []) if str(row.get("repository_key") or "") == key),
        None,
    )
    if not repository:
        raise ValueError("Repository not found")
    storage = _storage_by_key(config).get(str(repository.get("storage_key") or ""), {})
    if not storage:
        raise ValueError("Repository storage target was not found")
    repo_path = effective_repository_path(storage, str(repository.get("relative_path") or ""))
    jobs = jobs_using_repository(config, key)
    blockers: list[str] = []
    if jobs:
        blockers.append("jobs_linked")
    if is_resource_active(config, f"repo:{repo_path}"):
        blockers.append("repository_active")
    maintenance = CheckManager.get().get_state()
    if maintenance.get("running") and str(maintenance.get("target_key") or "") == key:
        blockers.append("maintenance_running")
    if JobManager.get().get_state("restore_test").get("running"):
        blockers.append("restore_test_running")
    if list_restore_runs(config, 50).get("active"):
        blockers.append("restore_running")
    blockers = list(dict.fromkeys(blockers))
    stats = repository.get("repository_stats") if isinstance(repository.get("repository_stats"), dict) else {}
    return repository, {
        "repository_key": key,
        "display_name": str(repository.get("display_name") or repository.get("repository_name") or key),
        "repository_name": str(repository.get("repository_name") or ""),
        "repository_path": repo_path,
        "storage_name": str(storage.get("display_name") or repository.get("storage_name") or ""),
        "repository_id": str(repository.get("borg_repository_id") or ""),
        "archive_count": _nonnegative_int(stats.get("archives_count")),
        "deduplicated_size": _nonnegative_int(stats.get("unique_csize")),
        "job_keys": jobs,
        "blockers": blockers,
        "allowed": not blockers,
    }


def prepare_repository_lifecycle(config: dict, repository_key: str, mode: str) -> dict[str, Any]:
    requested_mode = str(mode or "remove").strip().lower()
    if requested_mode not in {"remove", "delete"}:
        raise ValueError("Repository lifecycle mode is invalid")
    repository, context = _repository_lifecycle_context(config, repository_key)
    if not context["allowed"] or requested_mode == "remove":
        return {"ok": True, "mode": requested_mode, **context}

    with _repository_access(config, repository) as (storage, repo_path, passphrase_file):
        encryption = str(repository.get("encryption") or "").strip()
        info_payload = _borg_info(config, storage, repo_path, passphrase_file, encryption)
        archive_payload = _borg_list(config, storage, repo_path, passphrase_file, encryption)
    fields = _borg_info_fields(info_payload, archive_payload)
    live_stats = fields.get("repository_stats") if isinstance(fields.get("repository_stats"), dict) else {}
    context.update({
        "repository_id": str(fields.get("borg_repository_id") or ""),
        "archive_count": _nonnegative_int(live_stats.get("archives_count")),
        "deduplicated_size": _nonnegative_int(live_stats.get("unique_csize")),
    })
    if not context["repository_id"]:
        raise RuntimeError("Borg did not return a repository ID")
    return {"ok": True, "mode": requested_mode, **context}


def _remove_repository_metadata(config: dict, repository_key: str) -> dict[str, Any]:
    key = str(repository_key or "").strip()
    store = read_repository_store(config)
    repository = next(
        (row for row in store.get("repositories", []) if str(row.get("repository_key") or "") == key),
        None,
    )
    if not repository:
        raise ValueError("Repository not found")
    remaining = [row for row in store.get("repositories", []) if str(row.get("repository_key") or "") != key]
    write_repository_store(config, {"repositories": remaining})
    return repository


def _remove_repository_secret(config: dict, repository: dict[str, Any]) -> bool:
    raw = str(repository.get("passphrase_ref") or "").strip()
    if not raw:
        return False
    candidate = Path(raw)
    secrets_root = (_data_root(config) / "secrets").resolve()
    try:
        if candidate.parent.resolve() != secrets_root or not candidate.name.startswith(".borg-passphrase-"):
            return False
    except OSError:
        return False
    for row in read_repository_store(config).get("repositories", []):
        if str(row.get("passphrase_ref") or "").strip() == raw:
            return False
    try:
        if candidate.is_symlink() or candidate.exists():
            candidate.unlink()
            return True
    except OSError:
        return False
    return False


def apply_repository_lifecycle(
    config: dict,
    payload: dict[str, Any],
    *,
    audit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid repository lifecycle payload")
    key = str(payload.get("repository_key") or "").strip()
    mode = str(payload.get("mode") or "remove").strip().lower()
    if mode not in {"remove", "delete"}:
        raise ValueError("Repository lifecycle mode is invalid")
    repository, context = _repository_lifecycle_context(config, key)
    display_name = str(repository.get("display_name") or repository.get("repository_name") or key)
    if str(payload.get("confirmation_name") or "") != display_name:
        raise ValueError("Repository display name confirmation does not match")
    if not context["allowed"]:
        raise RepositoryLifecycleConflict(
            "Repository cannot be removed while jobs or operations are active",
            code="repository_lifecycle_blocked",
        )

    if mode == "remove":
        removed = _remove_repository_metadata(config, key)
        _write_repository_lifecycle_audit(
            config,
            removed,
            action="remove_from_inventory",
            status="success",
            details={"repository_data_deleted": False, "secret_deleted": False},
            audit_context=audit_context,
        )
        return {"ok": True, "mode": mode, "repository_key": key, "repository_deleted": False, "secret_deleted": False}

    if str(payload.get("confirmation_phrase") or "") != "DELETE":
        raise ValueError("Permanent repository deletion requires DELETE confirmation")
    expected_id = str(payload.get("expected_repository_id") or "").strip()
    expected_path = str(payload.get("expected_repository_path") or "").strip()
    try:
        expected_archives = int(payload.get("expected_archive_count"))
    except (TypeError, ValueError):
        raise ValueError("Expected archive count is required") from None
    if not expected_id or expected_path != context["repository_path"]:
        raise ValueError("Repository identity confirmation is incomplete")

    try:
        with _repository_access(config, repository) as (storage, repo_path, passphrase_file):
            encryption = str(repository.get("encryption") or "").strip()
            info_payload = _borg_info(config, storage, repo_path, passphrase_file, encryption)
            archive_payload = _borg_list(config, storage, repo_path, passphrase_file, encryption)
            live_fields = _borg_info_fields(info_payload, archive_payload)
            live_id = str(live_fields.get("borg_repository_id") or "").strip()
            live_stats = live_fields.get("repository_stats") if isinstance(live_fields.get("repository_stats"), dict) else {}
            live_archives = _nonnegative_int(live_stats.get("archives_count"))
            if live_id != expected_id or live_archives != expected_archives:
                raise RepositoryLifecycleConflict(
                    "Repository identity or archive count changed; repeat the deletion review",
                    code="repository_identity_changed",
                )
            env = _repo_env(storage, passphrase_file, config, encryption=encryption)
            env["BORG_DELETE_I_KNOW_WHAT_I_AM_DOING"] = "YES"
            timeout_raw = str(config.get("REPOSITORY_DELETE_TIMEOUT_SECONDS") or "3600").strip()
            try:
                timeout = max(60, min(int(timeout_raw), 86400))
            except ValueError:
                timeout = 3600
            proc = subprocess.run(
                ["borg", "delete", "--lock-wait", "30", repo_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )
            output = _mask_repo_output(((proc.stdout or "") + "\n" + (proc.stderr or "")).strip())
            if proc.returncode != 0:
                _raise_borg_command_error(output, f"borg delete failed with exit {proc.returncode}")
    except Exception as exc:
        _write_repository_lifecycle_audit(
            config,
            repository,
            action="delete_repository",
            status="failed",
            details={"error": _mask_repo_output(str(exc))[:500]},
            audit_context=audit_context,
        )
        raise

    removed = _remove_repository_metadata(config, key)
    secret_deleted = _remove_repository_secret(config, removed)
    from borg_key_store import remove_repository_key

    keyfile_deleted = remove_repository_key(
        config,
        str(removed.get("borg_repository_id") or ""),
        [
            str(row.get("borg_repository_id") or "")
            for row in read_repository_store(config).get("repositories", [])
        ],
    )
    _write_repository_lifecycle_audit(
        config,
        removed,
        action="delete_repository",
        status="success",
        details={
            "archive_count": expected_archives,
            "secret_deleted": secret_deleted,
            "keyfile_deleted": keyfile_deleted,
        },
        audit_context=audit_context,
    )
    return {
        "ok": True,
        "mode": mode,
        "repository_key": key,
        "repository_deleted": True,
        "secret_deleted": secret_deleted,
        "keyfile_deleted": keyfile_deleted,
    }


def create_or_import_repository(config: dict, payload: dict[str, Any]) -> dict[str, Any]:
    """Create/import a repository object, optionally running borg init.

    The command is intentionally scoped to repository management. Backup jobs
    should only select existing repository objects.
    """
    if not isinstance(payload, dict):
        raise ValueError("Invalid repository payload")
    action = str(payload.get("action") or "import").strip().lower()
    if action not in {"import", "create"}:
        raise ValueError("Invalid repository action")
    storage_key = str(payload.get("storage_key") or "").strip()
    storages = _storage_by_key(config)
    storage = storages.get(storage_key)
    if not storage:
        raise ValueError("Storage target not found")

    display_name = str(payload.get("display_name") or "").strip()
    repo_name = _normalize_repo_segment(str(payload.get("repository_name") or display_name or "repository"))
    relative_path = _safe_relative_path(str(payload.get("relative_path") or repo_name))
    repo_path = effective_repository_path(storage, relative_path)
    location = str(storage.get("location") or storage.get("storage_type") or "").strip().lower()
    encryption = str(payload.get("encryption") or ("repokey-blake2" if action == "create" else "auto")).strip()
    if action == "create" and encryption not in ALLOWED_ENCRYPTION_MODES:
        raise ValueError("Invalid Borg encryption mode")
    if action == "import" and encryption not in {*ALLOWED_ENCRYPTION_MODES, "auto"}:
        raise ValueError("Invalid Borg encryption mode")
    append_only = bool(payload.get("append_only", False))
    make_parent_dirs = bool(payload.get("make_parent_dirs", True))
    storage_quota = str(payload.get("storage_quota") or "").strip()
    if action != "create":
        append_only = False
        make_parent_dirs = False
        storage_quota = ""
    if storage_quota and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?[KMGTP]?", storage_quota, re.IGNORECASE):
        raise ValueError("Invalid storage quota")

    seed = f"repo_{repo_name}_{location}"
    repo_key = repository_key_for(seed, repo_path)
    store = read_repository_store(config)
    rows = store["repositories"]
    existing = next((
        row for row in rows
        if str(row.get("storage_key") or "") == storage_key
        and str(row.get("relative_path") or "").rstrip("/") == relative_path.rstrip("/")
    ), None)

    if action == "create":
        validate_repository_target(config, payload)

    passphrase_ref = str((existing or {}).get("passphrase_ref") or "").strip()
    passphrase_file: Path | None = None
    passphrase = str(payload.get("passphrase") or "").strip()
    key_data = str(payload.get("key_data") or "").strip()
    secret_previous: bytes | None = None
    secret_existed = False

    def restore_secret() -> None:
        if passphrase_file is None or not passphrase:
            return
        if secret_existed:
            passphrase_file.write_bytes(secret_previous or b"")
            passphrase_file.chmod(0o600)
        else:
            passphrase_file.unlink(missing_ok=True)

    if encryption != "none":
        passphrase_file = Path(passphrase_ref) if passphrase_ref else _secret_path_for_repository(config, repo_key)
        passphrase_ref = str(passphrase_file)
        if action == "create" and not passphrase:
            raise ValueError("Passphrase is required for encrypted repository creation")
        if action == "import" and not passphrase and not passphrase_file.is_file():
            passphrase_file = None
            passphrase_ref = ""
        if passphrase:
            assert passphrase_file is not None
            secret_existed = passphrase_file.exists()
            secret_previous = passphrase_file.read_bytes() if secret_existed else None
            passphrase_file.parent.mkdir(parents=True, exist_ok=True)
            passphrase_file.write_text(passphrase, encoding="utf-8")
            passphrase_file.chmod(0o600)

    output = ""
    exit_code = 0
    initialized = False
    info_fields: dict[str, Any] = {}
    if action == "create":
        cmd = ["borg", "init", f"--encryption={encryption}"]
        if append_only:
            cmd.append("--append-only")
        if storage_quota:
            cmd.extend(["--storage-quota", storage_quota])
        if make_parent_dirs:
            cmd.append("--make-parent-dirs")
        cmd.append(repo_path)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=_repo_env(storage, passphrase_file, config, encryption=encryption),
                check=False,
            )
            exit_code = proc.returncode
            output = _mask_repo_output(((proc.stdout or "") + "\n" + (proc.stderr or "")).strip(), passphrase)
        except FileNotFoundError:
            restore_secret()
            raise ValueError("borg binary not found")
        except subprocess.TimeoutExpired:
            restore_secret()
            raise TimeoutError("borg init timed out")
        if exit_code != 0:
            restore_secret()
            _raise_borg_init_target_error(output, exit_code)
        initialized = True
        try:
            info_fields = _borg_info_fields(
                _borg_info(config, storage, repo_path, passphrase_file, encryption)
            )
        except Exception:
            info_fields = {}
    else:
        try:
            if key_data:
                _import_exported_repository_key(
                    config, storage, repo_path, passphrase_file, key_data, encryption
                )
            try:
                info_payload = _borg_info(config, storage, repo_path, passphrase_file, encryption)
            except Exception as persistent_error:
                if key_data:
                    raise
                try:
                    legacy_payload = _borg_info_with_default_keys(
                        storage, repo_path, passphrase_file, encryption
                    )
                    legacy_fields = _borg_info_fields(legacy_payload)
                    from borg_key_store import import_default_key_if_present

                    copied = import_default_key_if_present(
                        config, str(legacy_fields.get("borg_repository_id") or "")
                    )
                    if copied is None:
                        raise persistent_error
                    info_payload = _borg_info(
                        config, storage, repo_path, passphrase_file, encryption
                    )
                except Exception:
                    raise persistent_error
            info_fields = _borg_info_fields(info_payload)
        except Exception:
            restore_secret()
            raise
        initialized = True
        detected_encryption = str(info_fields.get("encryption") or "").strip()
        if detected_encryption:
            encryption = detected_encryption
        elif encryption == "auto":
            encryption = "unknown"

    if existing:
        repo_key = str(existing.get("repository_key") or repo_key)
        passphrase_ref = str(existing.get("passphrase_ref") or passphrase_ref)

    now = _now()
    existing = existing if isinstance(existing, dict) else {}
    keyfile_ref = str(existing.get("keyfile_ref") or "").strip()
    if str(info_fields.get("borg_repository_id") or ""):
        from borg_key_store import borg_keys_dir, find_key_file, is_keyfile_encryption

        if is_keyfile_encryption(encryption):
            key_file = find_key_file(
                borg_keys_dir(config), str(info_fields.get("borg_repository_id") or "")
            )
            keyfile_ref = str(key_file) if key_file is not None else ""
        else:
            keyfile_ref = ""
    row = {
        **existing,
        "repository_key": repo_key,
        "display_name": display_name or repo_name,
        "repository_name": repo_name,
        "job_name": str((existing or {}).get("job_name") or "").strip(),
        "backup_type": str((existing or {}).get("backup_type") or "").strip(),
        "location": location,
        "storage_type": str(storage.get("storage_type") or location).strip().lower(),
        "storage_key": storage_key,
        "storage_name": str(storage.get("display_name") or "").strip(),
        "relative_path": relative_path,
        "passphrase_ref": passphrase_ref,
        "keyfile_ref": keyfile_ref,
        "encryption": encryption,
        "append_only": append_only,
        "storage_quota": storage_quota,
        "initialized": initialized,
        "created_by": str(existing.get("created_by") or action),
        "created_at": str(existing.get("created_at") or now),
        "updated_at": now,
        **{key: value for key, value in info_fields.items() if value not in ("", None, {})},
        "last_test_status": "ok",
        "last_seen_at": now,
        "last_info_refresh_at": now,
        "last_info_refresh_status": "success",
        "last_info_refresh_error": "",
        "source_job_keys": existing.get("source_job_keys", []),
        "used_by": existing.get("used_by", []),
    }
    for legacy_field in ("storage_profile_key", "usb_profile_key", "smb_profile_key", "repo_conf_key", "conf_key"):
        row.pop(legacy_field, None)
    next_rows = [item for item in rows if str(item.get("repository_key") or "") != repo_key]
    next_rows.append(row)
    write_repository_store(config, {"repositories": next_rows})
    stored = next(
        item for item in read_repository_store_for_api(config)["repositories"]
        if str(item.get("repository_key") or "") == repo_key
    )
    return {
        "ok": True,
        "action": action,
        "repository": stored,
        "exit_code": exit_code,
        "output": output,
    }


def _link_repository_to_job_locked(
    config: dict,
    repository_key: str,
    job_key: str,
    *,
    previous_repository_key: str = "",
    previous_job_key: str = "",
) -> None:
    selected = str(repository_key or "").strip()
    current_job = str(job_key or "").strip()
    if not selected or not current_job:
        raise ValueError("Repository and job keys are required")
    store = read_repository_store(config)
    rows = store["repositories"]
    if not any(str(row.get("repository_key") or "") == selected for row in rows):
        raise ValueError("Repository not found")
    old_repo = str(previous_repository_key or "").strip()
    old_job = str(previous_job_key or current_job).strip()
    next_rows = []
    for row in rows:
        key = str(row.get("repository_key") or "")
        used_by = [str(item).strip() for item in row.get("used_by", []) if str(item).strip()]
        source_jobs = [str(item).strip() for item in row.get("source_job_keys", []) if str(item).strip()]
        if key == old_repo or old_job != current_job:
            used_by = [item for item in used_by if item not in {old_job, current_job}]
            source_jobs = [item for item in source_jobs if item not in {old_job, current_job}]
        if key == selected:
            if current_job not in used_by:
                used_by.append(current_job)
            if current_job not in source_jobs:
                source_jobs.append(current_job)
        next_rows.append({**row, "used_by": used_by, "source_job_keys": source_jobs, "updated_at": _now()})
    write_repository_store(config, {"repositories": next_rows})


def link_repository_to_job(
    config: dict,
    repository_key: str,
    job_key: str,
    *,
    previous_repository_key: str = "",
    previous_job_key: str = "",
) -> None:
    path = repositories_file(config)
    with inventory_lock(path.parent):
        _link_repository_to_job_locked(
            config,
            repository_key,
            job_key,
            previous_repository_key=previous_repository_key,
            previous_job_key=previous_job_key,
        )


def _unlink_job_from_repositories_locked(config: dict, job_key: str) -> None:
    current_job = str(job_key or "").strip()
    if not current_job:
        return
    store = read_repository_store(config)
    changed = False
    next_rows = []
    for row in store.get("repositories", []):
        used_by = [str(item).strip() for item in row.get("used_by", []) if str(item).strip()]
        source_jobs = [str(item).strip() for item in row.get("source_job_keys", []) if str(item).strip()]
        next_used_by = [item for item in used_by if item != current_job]
        next_source_jobs = [item for item in source_jobs if item != current_job]
        if next_used_by != used_by or next_source_jobs != source_jobs:
            changed = True
            row = {
                **row,
                "used_by": next_used_by,
                "source_job_keys": next_source_jobs,
                "updated_at": _now(),
            }
        next_rows.append(row)
    if changed:
        write_repository_store(config, {"repositories": next_rows})


def unlink_job_from_repositories(config: dict, job_key: str) -> None:
    path = repositories_file(config)
    with inventory_lock(path.parent):
        _unlink_job_from_repositories_locked(config, job_key)


def save_job_repository_transaction(
    config: dict,
    metadata_path: Path,
    metadata: dict[str, Any],
    repository_key: str,
    job_key: str,
    *,
    previous_repository_key: str = "",
    previous_job_key: str = "",
    previous_metadata_path: Path | None = None,
) -> None:
    """Persist job metadata and both repository link lists as one recoverable unit."""
    repo_path = repositories_file(config)
    target = Path(metadata_path)
    previous = Path(previous_metadata_path) if previous_metadata_path else None
    try:
        with inventory_lock(repo_path.parent):
            old_target = target.read_bytes() if target.exists() else None
            old_previous = None
            if previous is not None and previous != target and previous.exists():
                old_previous = previous.read_bytes()
            old_repo = repo_path.read_bytes() if repo_path.exists() else None
            try:
                link_repository_to_job(
                    config,
                    repository_key,
                    job_key,
                    previous_repository_key=previous_repository_key,
                    previous_job_key=previous_job_key,
                )
                atomic_write_json(target, metadata)
                if previous is not None and previous != target and previous.exists():
                    previous.unlink()
            except Exception:
                if old_repo is None:
                    repo_path.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(repo_path, old_repo)
                if old_target is None:
                    target.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(target, old_target)
                if previous is not None and previous != target:
                    if old_previous is None:
                        previous.unlink(missing_ok=True)
                    else:
                        atomic_write_bytes(previous, old_previous)
                raise
    finally:
        from jobs_api import invalidate_job_discovery_cache
        invalidate_job_discovery_cache()


def delete_job_metadata_transaction(config: dict, metadata_paths: list[Path], job_key: str) -> int:
    """Delete job metadata and unlink its repository references with rollback."""
    repo_path = repositories_file(config)
    paths = [Path(path) for path in metadata_paths]
    try:
        with inventory_lock(repo_path.parent):
            snapshots = {path: path.read_bytes() for path in paths if path.exists()}
            old_repo = repo_path.read_bytes() if repo_path.exists() else None
            try:
                unlink_job_from_repositories(config, job_key)
                for path in snapshots:
                    path.unlink()
            except Exception:
                if old_repo is None:
                    repo_path.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(repo_path, old_repo)
                for path, content in snapshots.items():
                    atomic_write_bytes(path, content)
                raise
    finally:
        from jobs_api import invalidate_job_discovery_cache
        invalidate_job_discovery_cache()
    return len(snapshots)
