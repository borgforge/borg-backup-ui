"""
api/wizard_api.py - Job wizard metadata validation and storage.

Backup jobs are stored as canonical JSON metadata and executed through the
scriptless wizard runner.
"""

from copy import deepcopy
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from job_source_paths import normalize_source_paths
from job_model import (JobValidationError, apply_wizard_changes, archive_name_preview,
                       job_to_params, new_job_defaults, validate_archive_prefix, validate_job_id)


_RUNTIME_MODES = {"all", "selected", "none"}
_DOCKER_RUNTIME_MODES = _RUNTIME_MODES | {"except_selected"}


def _bool_value(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    return default


def _runtime_modes(kind: str) -> set[str]:
    return _DOCKER_RUNTIME_MODES if kind == "docker" else _RUNTIME_MODES


def list_source_directories(prefix: str = "", limit: int = 40, base_path: Path | None = None) -> list[dict]:
    """Return safe directory suggestions below /mnt for backup sources."""
    base = (base_path or Path("/mnt")).resolve()
    if not base.is_dir():
        return []
    raw = str(prefix or "").strip()
    display_base = "/mnt" if base_path is None else base.as_posix().rstrip("/")
    if not raw:
        return [{"path": f"{display_base}/"}]
    candidate = Path(raw)
    try:
        if base_path is None:
            if raw != "/mnt" and not raw.startswith("/mnt/"):
                return []
        elif candidate != base and base not in candidate.parents:
            return []
        has_trailing = raw.endswith("/")
        if has_trailing or candidate.is_dir():
            search_parent = candidate.resolve()
            display_parent = candidate
            name_prefix = ""
        else:
            search_parent = candidate.parent.resolve()
            display_parent = candidate.parent
            name_prefix = candidate.name
        search_parent.relative_to(base)
    except (OSError, ValueError):
        return []
    if not search_parent.is_dir():
        return []
    result: list[dict] = []
    safe_limit = max(1, min(int(limit or 40), 100))
    if not name_prefix and candidate != base and search_parent.is_dir():
        result.append({"path": f"{display_parent.as_posix().rstrip('/')}/"})
        if len(result) >= safe_limit:
            return result
    try:
        for child in sorted(search_parent.iterdir(), key=lambda path: path.name.lower()):
            if not child.is_dir():
                continue
            if name_prefix and not child.name.lower().startswith(name_prefix.lower()):
                continue
            try:
                child.resolve().relative_to(base)
            except (OSError, ValueError):
                continue
            result.append({"path": f"{display_parent.as_posix().rstrip('/')}/{child.name}/"})
            if len(result) >= safe_limit:
                break
    except OSError:
        return []
    return result


def _split_selected(raw) -> list[str]:
    if isinstance(raw, list):
        vals = raw
    elif isinstance(raw, str):
        vals = raw.splitlines() if "\n" in raw else raw.split(",")
    else:
        vals = []
    out: list[str] = []
    seen = set()
    for val in vals:
        name = str(val or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _exclude_paths(raw) -> list[str]:
    """Normalize concrete exclusion paths without accepting Borg patterns."""
    values = raw if isinstance(raw, list) else (raw.splitlines() if isinstance(raw, str) else [])
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if "\x00" in text or "\n" in text or "\r" in text:
            raise ValueError("Exclusion paths must not contain control characters")
        if not text.startswith("/"):
            raise ValueError(f"Exclusion path must be absolute: {text}")
        normalized = os.path.normpath(text)
        if normalized == "/" or normalized in seen:
            if normalized == "/":
                raise ValueError("The filesystem root cannot be excluded")
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _validate_exclude_paths(raw, source_paths: list[str]) -> list[str]:
    excludes = _exclude_paths(raw)
    normalized_sources = [os.path.normpath(str(path)) for path in source_paths]
    for exclude in excludes:
        if not Path(exclude).exists():
            raise ValueError(f"Exclusion path does not exist: {exclude}")
        if not any(exclude.startswith(source.rstrip("/") + "/") for source in normalized_sources):
            raise ValueError(f"Exclusion path must be below a selected source path: {exclude}")
    return excludes


def _runtime_control_from_params(params: dict, kind: str, existing: Optional[dict] = None) -> dict:
    existing = existing if isinstance(existing, dict) else {}
    legacy_key = "use_docker" if kind == "docker" else "use_vm"
    raw = params.get(f"{kind}_control")
    if f"{kind}_control" in params and not isinstance(raw, dict):
        raise JobValidationError("invalid_runtime_control", "Runtime control must be an object")
    source = raw if isinstance(raw, dict) else {}
    if not source and isinstance(existing.get(f"{kind}_control"), dict):
        source = existing.get(f"{kind}_control") or {}

    mode = str(source.get("mode") or "").strip().lower()
    if source and mode not in _runtime_modes(kind):
        raise JobValidationError("invalid_runtime_control", "Unsupported runtime control mode")
    if mode not in _runtime_modes(kind):
        mode = "all" if bool(params.get(legacy_key, False)) else "none"

    selected = _split_selected(
        params.get(f"{kind}_selected", source.get("selected", []))
    )
    ack_key = "ack_appdata_risk" if kind == "docker" else "ack_domains_risk"
    ack = bool(params.get(ack_key, source.get(ack_key, False)))
    return {
        "mode": mode,
        "selected": selected if mode in {"selected", "except_selected"} else [],
        ack_key: ack,
    }


def _runtime_control_from_meta(meta: dict, kind: str) -> dict:
    raw = meta.get(f"{kind}_control") if isinstance(meta.get(f"{kind}_control"), dict) else {}
    features = meta.get("features") if isinstance(meta.get("features"), dict) else {}
    legacy_enabled = bool(features.get(kind, False))
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in _runtime_modes(kind):
        mode = "all" if legacy_enabled else "none"
    ack_key = "ack_appdata_risk" if kind == "docker" else "ack_domains_risk"
    return {
        "mode": mode,
        "selected": _split_selected(raw.get("selected", [])) if mode in {"selected", "except_selected"} else [],
        ack_key: bool(raw.get(ack_key, False)),
    }


def _source_contains_path_component(raw_sources: list[str], component: str) -> bool:
    wanted = str(component or "").strip().lower()
    if not wanted:
        return False
    for src in raw_sources:
        parts = [part.strip().lower() for part in str(src or "").split("/") if part.strip()]
        if wanted in parts:
            return True
    return False


_RETENTION_DEFAULTS = {
    "daily": "7",
    "weekly": "4",
    "monthly": "6",
    "yearly": "3",
}


class RetentionValidationError(ValueError):
    """Expose a stable API code for localized wizard retention errors."""

    def __init__(self, api_code: str, message: str) -> None:
        super().__init__(message)
        self.api_code = api_code


def _retention_from_params(params: dict) -> dict[str, str]:
    """Return normalized Borg retention counts and reject unsafe policies."""
    retention: dict[str, str] = {}
    for period, default in _RETENTION_DEFAULTS.items():
        raw = str(params.get(f"keep_{period}", default)).strip() or default
        if not re.fullmatch(r"\d+", raw):
            raise RetentionValidationError(
                "retention_invalid",
                "Retention values must be non-negative whole numbers",
            )
        retention[period] = str(int(raw))
    if not any(int(value) > 0 for value in retention.values()):
        raise RetentionValidationError(
            "retention_all_zero",
            "At least one retention rule must be greater than zero; otherwise prune would delete every archive belonging to this job",
        )
    return retention


def validate_params(
    params: dict,
    scripts_dir: Path,
    data_root: Optional[Path] = None,
    *,
    allow_existing: bool = False,
    ui_config: Optional[dict] = None,
    require_runtime_ack: bool = True,
) -> None:
    """Validate effective wizard fields; never convert legacy metadata."""
    from jobs_api import get_jobs_meta_dir
    from job_store import read_jobs
    mode, source_id = _request_identity(params)
    if mode == "edit" and not allow_existing:
        raise JobValidationError("invalid_wizard_mode", "Editing requires edit mode")
    jobs = read_jobs(get_jobs_meta_dir(scripts_dir, data_root))
    existing = jobs.get(source_id) if source_id else None
    if source_id and existing is None:
        raise JobValidationError("unknown_job_id", "Unknown job_id; editing cannot create a job")
    effective = job_to_params(existing if existing is not None else new_job_defaults())
    effective.update(deepcopy(params))
    params.update(effective)
    validate_archive_prefix(params.get("archive_prefix"))
    if not isinstance(params.get("job_name"), str) or not params["job_name"].strip():
        raise JobValidationError("invalid_job_name", "Job name must not be empty")
    retention = _retention_from_params(params)
    params["file_activity"] = _bool_value(params.get("file_activity"), default=False)
    for period, value in retention.items():
        params[f"keep_{period}"] = value
    raw_sources = normalize_source_paths(params.get("source_paths"))
    params["source_paths"] = raw_sources
    selected_repo = _repository_from_params(params, ui_config)
    if not selected_repo:
        raise ValueError("Repository selection is required")
    params["repo_path"] = _repository_path(selected_repo, ui_config)
    params["encryption"] = _repository_encryption(selected_repo, str(params.get("encryption", "repokey-blake2")))

    from repository_context import storage_by_key
    selected_storage_key = str(selected_repo.get("storage_key") or "").strip()
    selected_storage = storage_by_key(ui_config or {}, selected_storage_key)
    repository_location = str(selected_storage.get("location") or selected_storage.get("storage_type") or "").strip().lower()
    if repository_location == "ssh":
        repository_location = "storagebox"
    location = repository_location
    if location not in {"local", "usb", "smb", "storagebox"}:
        raise ValueError("Selected repository has an unsupported storage location")
    params["location"] = location
    requested_storage_key = str(params.get("storage_key") or "").strip()
    if requested_storage_key and requested_storage_key != selected_storage_key:
        raise ValueError("Selected repository does not belong to the selected storage target")
    params["storage_key"] = selected_storage_key
    profile_key = str(selected_storage.get("profile_key") or "").strip()
    if location == "smb" and not profile_key:
        raise ValueError("SMB profile is missing")
    if location == "storagebox" and not profile_key:
        raise ValueError("Storage profile is missing")

    for src in raw_sources:
        p = Path(src)
        if not p.exists():
            raise ValueError(f"Source path does not exist: {src}")
        if not p.is_dir():
            raise ValueError(f"Source path is not a directory: {src}")
    params["exclude_paths"] = _validate_exclude_paths(params.get("exclude_paths", []), raw_sources)

    docker_control = _runtime_control_from_params(params, "docker")
    vm_control = _runtime_control_from_params(params, "vm")
    if docker_control["mode"] in {"selected", "except_selected"} and not docker_control["selected"]:
        raise ValueError("At least one Docker container must be selected")
    if vm_control["mode"] == "selected" and not vm_control["selected"]:
        raise ValueError("At least one VM must be selected")
    if require_runtime_ack and _source_contains_path_component(raw_sources, "appdata") and docker_control["mode"] != "all":
        if not bool(docker_control.get("ack_appdata_risk", False)):
            raise ValueError("Appdata backup risk must be acknowledged when not stopping all Docker containers")
    if require_runtime_ack and _source_contains_path_component(raw_sources, "domains") and vm_control["mode"] != "all":
        if not bool(vm_control.get("ack_domains_risk", False)):
            raise ValueError("VM domain backup risk must be acknowledged when not shutting down all VMs")

    params["docker_control"] = docker_control
    params["vm_control"] = vm_control


def _repository_from_params(params: dict, ui_config: Optional[dict]) -> Optional[dict]:
    repository_key = str(params.get("repository_key") or "").strip()
    if not repository_key or not ui_config:
        return None
    try:
        from repositories_api import repositories_file
        from job_store import read_repositories
        rows = read_repositories(repositories_file(ui_config))["repositories"]
    except OSError:
        raise ValueError("Repository inventory is not readable") from None
    for row in rows if isinstance(rows, list) else []:
        if str(row.get("repository_key") or "").strip() == repository_key:
            return row
    return None


def _repository_path(repo: Optional[dict], ui_config: Optional[dict] = None) -> str:
    if not isinstance(repo, dict):
        return ""
    if ui_config:
        try:
            from repository_context import repository_path, storage_by_key
            storage = storage_by_key(ui_config, str(repo.get("storage_key") or ""))
            return repository_path(repo, storage)
        except Exception:
            return ""
    return str(repo.get("path_raw") or "").strip()


def _repository_encryption(repo: Optional[dict], fallback: str = "repokey-blake2") -> str:
    if not isinstance(repo, dict):
        return fallback
    return str(repo.get("encryption") or fallback).strip() or fallback


def _request_identity(params):
    if not isinstance(params, dict):
        raise ValueError("Wizard payload must be an object")
    if {"type_id", "backup_type", "job_key", "existing_job_key", "legacy_job_keys", "archive_prefixes"}.intersection(params):
        raise JobValidationError("legacy_wizard_request", "Wizard requests must use job_id and archive_prefix")
    mode = params.get("_wizard_mode", "create")
    if not isinstance(mode, str) or mode not in {"create", "edit", "duplicate"}:
        raise JobValidationError("invalid_wizard_mode", "Unknown wizard operation")
    source_id = params.get("job_id")
    if mode == "create" and source_id is not None:
        raise JobValidationError("immutable_job_id", "New job IDs are assigned by the server")
    if mode != "create":
        validate_job_id(source_id)
    return mode, source_id


def load_job_for_wizard(job_id: str, scripts_dir: Path, ui_config: dict) -> dict:
    from jobs_api import get_jobs_meta_dir, resolve_data_root
    from job_store import read_job, read_json, job_revision
    from repository_context import storage_by_key

    meta = read_job(get_jobs_meta_dir(scripts_dir, resolve_data_root(ui_config)), job_id)
    params = job_to_params(meta)
    params.setdefault("file_activity", False)
    repo = _repository_from_params(params, ui_config)
    if repo is None:
        raise JobValidationError("invalid_job_repository", "The assigned repository is missing")
    storage = storage_by_key(ui_config, repo.get("storage_key", ""))
    location = str(storage.get("location") or storage.get("storage_type") or "")
    if location == "ssh":
        location = "storagebox"
    from schedule_api import get_schedules
    schedules = get_schedules(ui_config)
    schedule = schedules.get(job_id)
    if schedule is not None and not isinstance(schedule, dict):
        raise JobValidationError("invalid_job_schedule", "The job schedule is malformed")
    params.update(
        job_id=job_id, revision=job_revision(meta), location=location,
        storage_key=repo.get("storage_key", ""), repo_path=_repository_path(repo, ui_config),
        encryption=_repository_encryption(repo), passphrase="",
        archive_prefixes=list(meta["archive_prefixes"]),
        archive_name_preview=archive_name_preview(meta["archive_prefixes"][0]),
        schedule=deepcopy(schedule),
    )
    return params


def generate_flow_preview(params: dict, ui_config: Optional[dict] = None, scripts_dir: Optional[Path] = None) -> dict:
    """Erzeugt eine textuelle Backup-Flow-Vorschau fuer den Wizard."""
    prefix = validate_archive_prefix(params.get("archive_prefix"))
    location = params.get("location", "local")
    source_paths = normalize_source_paths(params.get("source_paths"))
    exclude_paths = _exclude_paths(params.get("exclude_paths", []))
    selected_repo = _repository_from_params(params, ui_config)
    repo_path = _repository_path(selected_repo, ui_config)
    encryption = _repository_encryption(selected_repo, params.get("encryption", "repokey-blake2"))
    docker_control = _runtime_control_from_params(params, "docker")
    vm_control = _runtime_control_from_params(params, "vm")
    retention = _retention_from_params(params)
    file_activity = _bool_value(params.get("file_activity"), default=False)
    use_docker = docker_control["mode"] != "none"
    use_vm = vm_control["mode"] != "none"

    steps = []
    step_codes = []

    def add_step(code: str, message: str, **params) -> None:
        steps.append(message)
        step_codes.append({"code": code, "params": params})

    add_step("prechecks", "Prechecks (prerequisites, parity, paths)")
    add_step("resourceLocksAcquire", "Acquire resource locks (repo, optional docker-control/vm-control)")
    if use_docker:
        if docker_control["mode"] == "selected":
            add_step("dockerStop", f"Stop selected Docker containers ({len(docker_control['selected'])})")
        elif docker_control["mode"] == "except_selected":
            add_step(
                "dockerStop",
                f"Stop all Docker containers except selected containers ({len(docker_control['selected'])} kept running)",
            )
        else:
            add_step("dockerStop", "Stop all Docker containers")
    if use_vm:
        if vm_control["mode"] == "selected":
            add_step("vmStop", f"Shut down selected VMs ({len(vm_control['selected'])})")
        else:
            add_step("vmStop", "Shut down all VMs")
    add_step(
        "borgCreate",
        f"Borg create ({len(source_paths)} source(s), {len(exclude_paths)} exclusion(s))",
        count=len(source_paths),
        exclusions=len(exclude_paths),
    )
    add_step("borgMaintenance", "Borg maintenance (prune -> compact -> check)")
    add_step("statusNotification", "Write status and notification")
    if use_vm:
        add_step("vmStart", "Start VMs stopped by this job")
    if use_docker:
        add_step("dockerStart", "Start Docker containers stopped by this job")
    add_step("resourceLocksRelease", "Release resource locks")

    remote_repo = {
        "checked": bool(selected_repo),
        "exists": bool(selected_repo),
        "needs_init_confirm": False,
        "message": "Managed repository selected" if selected_repo else "Repository object is missing",
    } if location == "storagebox" else {"checked": False, "exists": False, "needs_init_confirm": False, "message": ""}
    return {
        "runner": "scriptless-wizard-runner",
        "job_id": params.get("job_id"),
        "job_name": params.get("job_name", ""),
        "archive_name_preview": archive_name_preview(prefix),
        "summary": {
            "location": location,
            "repo": repo_path,
            "repository_key": str((selected_repo or {}).get("repository_key") or params.get("repository_key") or "").strip(),
            "repository_name": str((selected_repo or {}).get("repository_name") or "").strip(),
            "encryption": encryption,
            "sources_count": len(source_paths),
            "exclusions_count": len(exclude_paths),
            "exclude_paths": exclude_paths,
            "docker": use_docker,
            "vm": use_vm,
            "docker_mode": docker_control["mode"],
            "vm_mode": vm_control["mode"],
            "docker_selected": docker_control["selected"],
            "vm_selected": vm_control["selected"],
            "retention": retention,
            "file_activity": file_activity,
        },
        "steps": steps,
        "step_codes": step_codes,
        "remote_repo": remote_repo,
    }


def save_job(params: dict, scripts_dir: Path, data_root: Optional[Path] = None, ui_config: Optional[dict] = None) -> dict:
    """Save one ID-based job and its assignments; never rename an identity."""
    from uuid import uuid4
    from jobs_api import get_jobs_meta_dir
    from job_store import job_revision, save_job_transaction
    from repositories_api import repositories_file

    mode, source_id = _request_identity(params)
    config = ui_config or {
        "BACKUP_SCRIPTS_DIR": str(data_root or (scripts_dir.parent if scripts_dir.name == "scripts" else scripts_dir)),
    }
    original_params = deepcopy(params)

    def build(existing):
        effective = job_to_params(existing if existing is not None else new_job_defaults())
        effective.update(deepcopy(original_params))
        validate_params(effective, scripts_dir, data_root, allow_existing=mode == "edit", ui_config=config)
        # Allocate only on the write path, after validation, never on preview/read.
        job_id = source_id if mode == "edit" else str(uuid4())
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return apply_wizard_changes(effective, existing=existing, job_id=job_id, now=now, duplicate=mode == "duplicate")

    metadata, target = save_job_transaction(
        get_jobs_meta_dir(scripts_dir, data_root), repositories_file(config), build,
        source_id=source_id, expected_revision=params.get("expected_revision"), duplicate=mode == "duplicate",
    )
    return {
        "job_id": metadata["job_id"], "revision": job_revision(metadata),
        "job_name": metadata["name"], "archive_name_preview": archive_name_preview(metadata["archive_prefixes"][0]),
        "filename": "", "path": "", "script": "", "metadata_path": str(target), "regenerated_script": False,
    }
