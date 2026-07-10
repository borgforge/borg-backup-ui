"""
api/wizard_api.py - Job wizard metadata validation and storage.

Backup jobs are stored as canonical JSON metadata and executed through the
scriptless wizard runner.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _type_upper(type_id: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", type_id.upper())


_RUNTIME_MODES = {"all", "selected", "none"}


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


def _runtime_control_from_params(params: dict, kind: str, existing: Optional[dict] = None) -> dict:
    existing = existing if isinstance(existing, dict) else {}
    legacy_key = "use_docker" if kind == "docker" else "use_vm"
    raw = params.get(f"{kind}_control")
    source = raw if isinstance(raw, dict) else {}
    if not source and isinstance(existing.get(f"{kind}_control"), dict):
        source = existing.get(f"{kind}_control") or {}

    mode = str(source.get("mode") or "").strip().lower()
    if mode not in _RUNTIME_MODES:
        mode = "all" if bool(params.get(legacy_key, False)) else "none"

    selected = _split_selected(
        params.get(f"{kind}_selected", source.get("selected", []))
    )
    ack_key = "ack_appdata_risk" if kind == "docker" else "ack_domains_risk"
    ack = bool(params.get(ack_key, source.get(ack_key, False)))
    return {
        "mode": mode,
        "selected": selected if mode == "selected" else [],
        ack_key: ack,
    }


def _runtime_control_from_meta(meta: dict, kind: str) -> dict:
    raw = meta.get(f"{kind}_control") if isinstance(meta.get(f"{kind}_control"), dict) else {}
    features = meta.get("features") if isinstance(meta.get("features"), dict) else {}
    legacy_enabled = bool(features.get(kind, False))
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in _RUNTIME_MODES:
        mode = "all" if legacy_enabled else "none"
    ack_key = "ack_appdata_risk" if kind == "docker" else "ack_domains_risk"
    return {
        "mode": mode,
        "selected": _split_selected(raw.get("selected", [])) if mode == "selected" else [],
        ack_key: bool(raw.get(ack_key, False)),
    }


def _source_matches(raw_sources: list[str], prefix: str) -> bool:
    prefix_norm = prefix.rstrip("/")
    for src in raw_sources:
        src_norm = str(src or "").rstrip("/")
        if src_norm == prefix_norm:
            return True
    return False


def validate_params(
    params: dict,
    scripts_dir: Path,
    data_root: Optional[Path] = None,
    *,
    allow_existing: bool = False,
    ui_config: Optional[dict] = None,
) -> None:
    """Wirft ValueError bei ungültigen Parametern."""
    type_id = params.get("type_id", "").strip()
    if not type_id:
        raise ValueError("Type ID must not be empty")
    if not re.fullmatch(r"[a-z0-9_]+", type_id):
        raise ValueError("Type ID may contain only lowercase letters, digits, and underscores")
    if not params.get("job_name", "").strip():
        raise ValueError("Job name must not be empty")
    if not params.get("source_paths", "").strip():
        raise ValueError("At least one source path is required")
    selected_repo = _repository_from_params(params, ui_config)
    if not selected_repo:
        raise ValueError("Repository selection is required")
    params["repo_path"] = _repository_path(selected_repo, ui_config)
    params["encryption"] = _repository_encryption(selected_repo, str(params.get("encryption", "repokey-blake2")))

    location = params.get("location", "local")
    if location not in ("local", "usb", "smb", "storagebox"):
        raise ValueError(f"Invalid location: {location!r}")
    from repository_context import storage_by_key
    selected_storage_key = str(selected_repo.get("storage_key") or "").strip()
    selected_storage = storage_by_key(ui_config or {}, selected_storage_key)
    repository_location = str(selected_storage.get("location") or selected_storage.get("storage_type") or "").strip().lower()
    if repository_location == "ssh":
        repository_location = "storagebox"
    if repository_location != location:
        raise ValueError("Selected repository does not match the selected storage location")
    requested_storage_key = str(params.get("storage_key") or "").strip()
    if requested_storage_key and requested_storage_key != selected_storage_key:
        raise ValueError("Selected repository does not belong to the selected storage target")
    params["storage_key"] = selected_storage_key
    profile_key = str(selected_storage.get("profile_key") or "").strip()
    params["usb_profile_key"] = profile_key if location == "usb" else ""
    params["smb_profile_key"] = profile_key if location == "smb" else ""
    params["storage_profile_key"] = profile_key if location == "storagebox" else ""
    if location == "smb" and not str(params.get("smb_profile_key", "")).strip():
        raise ValueError("SMB profile is missing")
    if location == "storagebox" and not str(params.get("storage_profile_key", "")).strip():
        raise ValueError("Storage profile is missing")

    raw_sources = [p.strip() for p in str(params.get("source_paths", "")).split() if p.strip()]
    for src in raw_sources:
        p = Path(src)
        if not p.exists():
            raise ValueError(f"Source path does not exist: {src}")
        if not p.is_dir():
            raise ValueError(f"Source path is not a directory: {src}")

    docker_control = _runtime_control_from_params(params, "docker")
    vm_control = _runtime_control_from_params(params, "vm")
    if docker_control["mode"] == "selected" and not docker_control["selected"]:
        raise ValueError("At least one Docker container must be selected")
    if vm_control["mode"] == "selected" and not vm_control["selected"]:
        raise ValueError("At least one VM must be selected")
    if _source_matches(raw_sources, "/mnt/user/appdata") and docker_control["mode"] != "all":
        if not bool(docker_control.get("ack_appdata_risk", False)):
            raise ValueError("Appdata backup risk must be acknowledged when not stopping all Docker containers")
    if _source_matches(raw_sources, "/mnt/user/domains") and vm_control["mode"] != "all":
        if not bool(vm_control.get("ack_domains_risk", False)):
            raise ValueError("VM domain backup risk must be acknowledged when not shutting down all VMs")

    from jobs_api import get_jobs_meta_dir
    job_key = f"{type_id}_{location}"
    meta_target = get_jobs_meta_dir(scripts_dir, data_root) / f"{job_key}.json"
    if meta_target.exists() and not allow_existing:
        raise FileExistsError(f"Job already exists: {type_id}_{location}")


def _paths_conf_key(type_id: str) -> str:
    return f"BACKUP_PATHS_{_type_upper(type_id)}"


def _repository_from_params(params: dict, ui_config: Optional[dict]) -> Optional[dict]:
    repository_key = str(params.get("repository_key") or "").strip()
    if not repository_key or not ui_config:
        return None
    try:
        from repositories_api import read_repository_store
        rows = read_repository_store(ui_config).get("repositories", [])
    except Exception:
        return None
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
    return str(repo.get("path_raw") or repo.get("repo_uri") or repo.get("repo_path") or repo.get("path_display") or "").strip()


def _repository_encryption(repo: Optional[dict], fallback: str = "repokey-blake2") -> str:
    if not isinstance(repo, dict):
        return fallback
    return str(repo.get("encryption") or fallback).strip() or fallback


def load_job_for_wizard(job_key: str, scripts_dir: Path, ui_config: dict) -> dict:
    from jobs_api import discover_jobs, get_jobs_meta_dirs, resolve_data_root
    from config_api import read_expanded_conf

    data_root = resolve_data_root(ui_config)
    jobs = {j.key: j for j in discover_jobs(scripts_dir, data_root)}
    if job_key not in jobs:
        raise ValueError(f"Unknown job: {job_key}")

    info = jobs[job_key]
    conf = read_expanded_conf(ui_config)
    type_id = str(info.backup_type or "").lower()
    location = str(info.location or "local").lower()

    paths_key = _paths_conf_key(type_id)

    # Prefer explicit wizard metadata values if available.
    meta_paths_default = ""
    meta_compression = ""
    meta_keep_daily = ""
    meta_keep_weekly = ""
    meta_keep_monthly = ""
    meta_keep_yearly = ""
    meta_repository_key = ""
    meta_mount_before_run = True
    meta_unmount_after_run = True
    meta: dict = {}
    meta_docker_control = {"mode": "all" if bool(info.has_docker) else "none", "selected": [], "ack_appdata_risk": False}
    meta_vm_control = {"mode": "all" if bool(info.has_vm) else "none", "selected": [], "ack_domains_risk": False}
    for meta_dir in get_jobs_meta_dirs(scripts_dir, data_root):
        meta_file = meta_dir / f"{job_key}.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if isinstance(meta.get("paths"), dict):
                meta_paths_default = str(meta["paths"].get("default") or "").strip()
            meta_compression = str(meta.get("compression") or "").strip()
            meta_ret = meta.get("retention") if isinstance(meta.get("retention"), dict) else {}
            meta_keep_daily = str(meta_ret.get("daily") or "").strip()
            meta_keep_weekly = str(meta_ret.get("weekly") or "").strip()
            meta_keep_monthly = str(meta_ret.get("monthly") or "").strip()
            meta_keep_yearly = str(meta_ret.get("yearly") or "").strip()
            meta_repository_key = str(meta.get("repository_key") or "").strip()
            meta_mount_before_run = bool(meta.get("mount_before_run", True))
            meta_unmount_after_run = bool(meta.get("unmount_after_run", True))
            meta_docker_control = _runtime_control_from_meta(meta, "docker")
            meta_vm_control = _runtime_control_from_meta(meta, "vm")
            break
        except (json.JSONDecodeError, OSError, UnicodeDecodeError, TypeError, ValueError):
            continue

    from repository_context import resolve_job_repository_context
    if not meta:
        raise ValueError(f"Wizard metadata is missing: {job_key}")
    repository_context = resolve_job_repository_context(
        ui_config,
        job_key,
        job=meta,
        require_passphrase_file=False,
    )
    storage = repository_context["storage"]
    profile_key = str(storage.get("profile_key") or "").strip()
    repo_path = str(repository_context["repository_path"])
    source_paths = meta_paths_default or conf.get(paths_key) or ""
    compression = meta_compression or conf.get(f"COMPRESSION_{_type_upper(type_id)}", "lz4")

    # Prefer explicit job metadata name (JSON) over display label with location suffix.
    # This keeps edited names stable (e.g. "Flash" stays "Flash", not "Flash - Lokal").
    params = {
        "job_key": job_key,
        "type_id": type_id,
        "job_name": (info.name or "").strip() or info.display_name or job_key,
        "description": info.description or "",
        "icon": str(getattr(info, "icon", "") or "").strip().lower(),
        "icon_color": str(getattr(info, "icon_color", "") or "").strip().lower(),
        "location": location,
        "use_docker": meta_docker_control["mode"] != "none",
        "use_vm": meta_vm_control["mode"] != "none",
        "docker_control": meta_docker_control,
        "vm_control": meta_vm_control,
        "source_paths": source_paths or "",
        "repo_path": repo_path or "",
        "repository_key": meta_repository_key,
        "usb_profile_key": profile_key if location == "usb" else "",
        "smb_profile_key": profile_key if location == "smb" else "",
        "storage_profile_key": profile_key if location == "storagebox" else "",
        "mount_before_run": meta_mount_before_run,
        "unmount_after_run": meta_unmount_after_run,
        "compression": compression,
        "encryption": str(repository_context["encryption"]),
        "passphrase": "",
        "keep_daily": meta_keep_daily or conf.get(f"RETENTION_{_type_upper(type_id)}_DAILY", "7"),
        "keep_weekly": meta_keep_weekly or conf.get(f"RETENTION_{_type_upper(type_id)}_WEEKLY", "4"),
        "keep_monthly": meta_keep_monthly or conf.get(f"RETENTION_{_type_upper(type_id)}_MONTHLY", "6"),
        "keep_yearly": meta_keep_yearly or conf.get(f"RETENTION_{_type_upper(type_id)}_YEARLY", "3"),
        "standard": info.standard,
    }
    return params


def generate_flow_preview(params: dict, ui_config: Optional[dict] = None, scripts_dir: Optional[Path] = None) -> dict:
    """Erzeugt eine textuelle Backup-Flow-Vorschau fuer den Wizard."""
    type_id = params["type_id"].strip()
    location = params.get("location", "local")
    source_paths = [p for p in params.get("source_paths", "").split() if p]
    selected_repo = _repository_from_params(params, ui_config)
    repo_path = _repository_path(selected_repo, ui_config) or params.get("repo_path", "").strip()
    encryption = _repository_encryption(selected_repo, params.get("encryption", "repokey-blake2"))
    docker_control = _runtime_control_from_params(params, "docker")
    vm_control = _runtime_control_from_params(params, "vm")
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
        else:
            add_step("dockerStop", "Stop all Docker containers")
    if use_vm:
        if vm_control["mode"] == "selected":
            add_step("vmStop", f"Shut down selected VMs ({len(vm_control['selected'])})")
        else:
            add_step("vmStop", "Shut down all VMs")
    add_step("borgCreate", f"Borg create ({len(source_paths)} source(s))", count=len(source_paths))
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
        "job_key": f"{type_id}_{location}",
        "summary": {
            "location": location,
            "repo": repo_path,
            "repository_key": str((selected_repo or {}).get("repository_key") or params.get("repository_key") or "").strip(),
            "repository_name": str((selected_repo or {}).get("repository_name") or "").strip(),
            "encryption": encryption,
            "sources_count": len(source_paths),
            "docker": use_docker,
            "vm": use_vm,
            "docker_mode": docker_control["mode"],
            "vm_mode": vm_control["mode"],
            "docker_selected": docker_control["selected"],
            "vm_selected": vm_control["selected"],
        },
        "steps": steps,
        "step_codes": step_codes,
        "remote_repo": remote_repo,
    }


def save_job(params: dict, scripts_dir: Path, data_root: Optional[Path] = None, ui_config: Optional[dict] = None) -> dict:
    """Speichert Job-eigene Wizard-Metadaten mit kanonischer Repository-Referenz."""
    from jobs_api import get_jobs_meta_dir
    type_id     = params["type_id"].strip()
    location    = params.get("location", "local")
    description = params.get("description", "").strip()
    icon = str(params.get("icon", "")).strip().lower()
    icon_color = str(params.get("icon_color", "")).strip().lower()
    selected_repo = _repository_from_params(params, ui_config)
    if not selected_repo:
        raise ValueError("Selected repository object was not found")
    selected_repository_key = str((selected_repo or {}).get("repository_key") or params.get("repository_key") or "").strip()

    scripts_dir.mkdir(parents=True, exist_ok=True)
    existing_job_key = str(params.get("existing_job_key", "")).strip()

    # ── Wizard-Metadaten schreiben (Phase 2) ─────────────────────────────────
    job_key = f"{type_id}_{location}"
    type_upper = _type_upper(type_id)

    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    jobs_meta_dir = get_jobs_meta_dir(scripts_dir, data_root)
    jobs_meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path = jobs_meta_dir / f"{job_key}.json"

    existing = {}
    if meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            existing = {}
    elif existing_job_key and existing_job_key != job_key:
        old_meta_path = jobs_meta_dir / f"{existing_job_key}.json"
        if old_meta_path.exists():
            try:
                existing = json.loads(old_meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                existing = {}

    mount_before_run = bool(params.get("mount_before_run", existing.get("mount_before_run", True)))
    unmount_after_run = bool(params.get("unmount_after_run", existing.get("unmount_after_run", True)))
    docker_control = _runtime_control_from_params(params, "docker", existing)
    vm_control = _runtime_control_from_params(params, "vm", existing)

    metadata = {
        "schema_version": 2,
        "job_key": job_key,
        "name": params.get("job_name", "").strip() or job_key,
        "description": description,
        "icon": icon,
        "icon_color": icon_color,
        "enabled": bool(existing.get("enabled", True)),
        "standard": "wizard",
        "backup_type": type_id,
        "location": location,
        "mount_before_run": mount_before_run if location == "smb" else True,
        "unmount_after_run": unmount_after_run if location == "smb" else True,
        "script": "",
        "runner": "scriptless-wizard-runner",
        "paths": {
            "conf_key": f"BACKUP_PATHS_{type_upper}",
            "default": params.get("source_paths", "").strip(),
        },
        "features": {
            "docker": docker_control["mode"] != "none",
            "vm": vm_control["mode"] != "none",
        },
        "docker_control": docker_control,
        "vm_control": vm_control,
        "compression": str(params.get("compression", "lz4")).strip() or "lz4",
        "retention": {
            "daily": str(params.get("keep_daily", "7")).strip() or "7",
            "weekly": str(params.get("keep_weekly", "4")).strip() or "4",
            "monthly": str(params.get("keep_monthly", "6")).strip() or "6",
            "yearly": str(params.get("keep_yearly", "3")).strip() or "3",
        },
        "created_at": existing.get("created_at", now_iso),
        "updated_at": now_iso,
    }
    metadata["repository_key"] = selected_repository_key
    if isinstance(existing.get("restore_test_policy"), dict):
        metadata["restore_test_policy"] = dict(existing["restore_test_policy"])

    repo_config = ui_config or {
        "BACKUP_SCRIPTS_DIR": str(data_root or (scripts_dir.parent if scripts_dir.name == "scripts" else scripts_dir)),
    }
    from repositories_api import link_repository_to_job
    link_repository_to_job(
        repo_config,
        selected_repository_key,
        job_key,
        previous_repository_key=str(existing.get("repository_key") or ""),
        previous_job_key=existing_job_key or job_key,
    )

    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if existing_job_key and existing_job_key != job_key:
        old_meta = jobs_meta_dir / f"{existing_job_key}.json"
        if old_meta.exists():
            try:
                old_meta.unlink()
            except OSError:
                pass

    return {
        "filename": "",
        "path": "",
        "script": "",
        "metadata_path": str(meta_path),
        "regenerated_script": False,
    }
