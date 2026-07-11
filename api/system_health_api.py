"""
api/system_health_api.py – kleiner Systemzustand fuer Migration/Verzeichnislayout.
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict


def _read_migration_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "success": False,
            "message": "No migration run has been recorded yet.",
            "timestamp": "",
            "reason_code": "none",
            "reason_text": "No run yet",
            "details": {},
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("last_run"), dict):
            return raw
        return {
            "success": bool(raw.get("success", False)),
            "message": str(raw.get("message", "") or ""),
            "timestamp": str(raw.get("timestamp", "") or ""),
            "reason_code": str(raw.get("reason_code", "") or ""),
            "reason_text": str(raw.get("reason_text", "") or ""),
            "details": raw.get("details") if isinstance(raw.get("details"), dict) else {},
        }
    except Exception:
        return {
            "success": False,
            "message": "Migration status is not readable.",
            "timestamp": "",
            "reason_code": "unreadable",
            "reason_text": "Migration status is not readable",
            "details": {},
        }


def _is_effective_migration(entry: Dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False
    if str(entry.get("reason_code", "")).strip() and str(entry.get("reason_code", "")).strip() != "no_changes":
        return True
    details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
    startup = details.get("startup_migrations") if isinstance(details.get("startup_migrations"), dict) else {}
    if startup.get("applied") or startup.get("failed"):
        return True
    return False


def _read_migration_log(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"last_event": {}, "last_effective_event": {}}
    last_event: Dict[str, Any] = {}
    last_effective_event: Dict[str, Any] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if not isinstance(entry, dict):
                    continue
                last_event = entry
                if _is_effective_migration(entry):
                    last_effective_event = entry
    except Exception:
        return {"last_event": {}, "last_effective_event": {}}
    return {"last_event": last_event, "last_effective_event": last_effective_event}


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _last_migration_successful(migration: Dict[str, Any]) -> bool:
    if not isinstance(migration, dict):
        return False
    last_run = migration.get("last_run")
    if isinstance(last_run, dict) and "success" in last_run:
        return bool(last_run.get("success", False))
    return bool(migration.get("success", False))


def _build_migration_summary(migration: Dict[str, Any], migration_log: Dict[str, Any]) -> Dict[str, Any]:
    last_event = migration_log.get("last_event") if isinstance(migration_log, dict) else {}
    if not isinstance(last_event, dict) or not last_event:
        if isinstance(migration, dict) and isinstance(migration.get("last_run"), dict):
            last_event = migration.get("last_run", {})
        else:
            last_event = migration if isinstance(migration, dict) else {}
    last_effective = migration_log.get("last_effective_event") if isinstance(migration_log, dict) else {}
    if not isinstance(last_effective, dict):
        last_effective = {}

    timestamp = str(last_event.get("timestamp", "") or "").strip()
    last_effective_ts = str(last_effective.get("timestamp", "") or "").strip()
    if not timestamp:
        return {
            "status": "none",
            "state": "No run yet",
            "last_run": "",
            "last_effective_run": last_effective_ts,
            "last_effective_exists": bool(last_effective_ts),
            "reason_code": "none",
            "reason": "No migration run has been recorded yet",
            "actions": [],
            "errors": [],
            "technical_message": "",
        }

    ok = bool(last_event.get("success", False))
    reason_code = str(last_event.get("reason_code", "") or "").strip()
    reason_text = str(last_event.get("reason_text", "") or "").strip()
    message = str(last_event.get("message", "") or "").strip()
    details = last_event.get("details") if isinstance(last_event.get("details"), dict) else {}
    actions = []
    errors = []
    startup = details.get("startup_migrations") if isinstance(details.get("startup_migrations"), dict) else {}
    startup_applied = startup.get("applied") if isinstance(startup.get("applied"), list) else []
    startup_failed = startup.get("failed") if isinstance(startup.get("failed"), list) else []
    startup_results = startup.get("results") if isinstance(startup.get("results"), dict) else {}
    for migration_id in startup_applied:
        migration_id_text = str(migration_id or "").strip()
        if not migration_id_text:
            continue
        actions.append(f"{migration_id_text} applied")
        result = startup_results.get(migration_id_text) if isinstance(startup_results.get(migration_id_text), dict) else {}
        result_details = result.get("details") if isinstance(result.get("details"), dict) else {}
        updated_keys = result_details.get("updated_keys") if isinstance(result_details.get("updated_keys"), list) else []
        if updated_keys:
            actions.append(f"Updated keys: {', '.join(str(key) for key in updated_keys)}")
        imported = _as_int(result_details.get("imported"))
        if imported > 0:
            actions.append(f"{imported} restore run(s) migrated")
        result_errors = result_details.get("errors") if isinstance(result_details.get("errors"), list) else []
        if result_errors:
            errors.append(f"{migration_id_text}: {len(result_errors)} error(s)")
    for migration_id in startup_failed:
        migration_id_text = str(migration_id or "").strip()
        if not migration_id_text:
            continue
        result = startup_results.get(migration_id_text) if isinstance(startup_results.get(migration_id_text), dict) else {}
        result_details = result.get("details") if isinstance(result.get("details"), dict) else {}
        result_errors = result_details.get("errors") if isinstance(result_details.get("errors"), list) else []
        if result_errors:
            errors.append(f"{migration_id_text}: {len(result_errors)} error(s)")
        else:
            error_text = str(result_details.get("error") or result.get("error") or "").strip()
            errors.append(f"{migration_id_text}: {error_text or 'failed'}")
    if not ok and not errors:
        errors.append("Migration failed")

    reason = reason_text or (
        "Cache/remotes changed, including backup.conf update"
        if reason_code == "storage_paths_changed"
        else (
            "Startup migrations applied"
            if reason_code == "startup_migrations_applied"
            else ("No changes required" if reason_code == "no_changes" else ("Migration completed" if ok else "Migration completed with errors"))
        )
    )
    return {
        "status": "success" if ok else "failed",
        "state": "Successful" if ok else "Failed",
        "last_run": timestamp,
        "last_effective_run": last_effective_ts,
        "last_effective_exists": bool(last_effective_ts),
        "reason_code": reason_code,
        "reason": reason,
        "actions": actions,
        "errors": errors,
        "technical_message": message,
    }


def _split_job_paths(value: Any) -> list[str]:
    return [p.strip() for p in str(value or "").replace("\n", " ").split(" ") if p.strip()]


def _collect_job_health(config: dict, jobs_dir: Path) -> Dict[str, Any]:
    items = []
    if jobs_dir.is_dir():
        job_files = sorted(jobs_dir.glob("*.json"))
    else:
        job_files = []

    repository_inventory = None
    repository_inventory_error = ""
    try:
        from repository_context import load_repository_inventory
        repository_inventory = load_repository_inventory(config)
    except Exception as exc:
        repository_inventory_error = str(exc)

    for meta_file in job_files:
        try:
            raw = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception as exc:
            items.append({
                "job_key": meta_file.stem,
                "name": meta_file.stem,
                "state": "bad",
                "errors": [f"Job metadata is not readable: {exc}"],
                "error_details": [{"code": "metadata_unreadable", "params": {"message": str(exc)}}],
                "warnings": [],
            })
            continue
        if not isinstance(raw, dict):
            continue
        job_key = str(raw.get("job_key") or meta_file.stem).strip()
        name = str(raw.get("name") or job_key).strip()
        location = str(raw.get("location") or "").strip().lower()
        errors: list[str] = []
        error_details: list[dict] = []
        warnings: list[str] = []

        def add_error(code: str, message: str, **params: Any) -> None:
            errors.append(message)
            error_details.append({"code": code, "params": params})

        repository_context = None
        if repository_inventory_error:
            add_error("repository_context_invalid", repository_inventory_error)
        else:
            try:
                from repository_context import resolve_job_repository_context
                repository_context = resolve_job_repository_context(
                    config,
                    job_key,
                    job=raw,
                    inventory=repository_inventory,
                )
                location = str(repository_context.get("location") or location)
            except Exception as exc:
                add_error("repository_context_invalid", str(exc))

        paths_cfg = raw.get("paths") if isinstance(raw.get("paths"), dict) else {}
        source_paths = _split_job_paths(paths_cfg.get("default"))
        if not source_paths:
            add_error("source_paths_missing", "Source paths are missing")
        else:
            missing = [p for p in source_paths if not Path(p).exists()]
            if missing:
                add_error("source_paths_not_found", f"{len(missing)} source path(s) do not exist", count=len(missing))

        if repository_context and location == "storagebox":
            storage = repository_context.get("storage") if isinstance(repository_context.get("storage"), dict) else {}
            ssh_key = str(storage.get("ssh_key_path") or "").strip()
            if ssh_key and not Path(ssh_key).is_file():
                add_error("ssh_key_file_missing", "SSH key file does not exist")
            if not str(storage.get("host") or "").strip() or not str(storage.get("user") or "").strip():
                add_error("storage_profile_incomplete", "Storage target is incomplete")

        state = "bad" if errors else ("warn" if warnings else "ok")
        items.append({
            "job_key": job_key,
            "name": name,
            "location": location,
            "state": state,
            "errors": errors,
            "error_details": error_details,
            "warnings": warnings,
        })

    failed = sum(1 for item in items if item.get("state") == "bad")
    warnings_count = sum(1 for item in items if item.get("state") == "warn")
    return {
        "summary": {
            "total": len(items),
            "ok": sum(1 for item in items if item.get("state") == "ok"),
            "failed": failed,
            "warnings": warnings_count,
        },
        "items": items,
    }


def _probe_cifs_support() -> tuple[bool, str]:
    """Inspect local CIFS capability without starting a blocking process."""
    try:
        filesystems = Path("/proc/filesystems").read_text(encoding="utf-8", errors="replace")
        if any("cifs" in line for line in filesystems.splitlines()):
            return True, "loaded"
    except Exception:
        pass
    try:
        modules = Path("/proc/modules").read_text(encoding="utf-8", errors="replace")
        if any(line.startswith("cifs ") for line in modules.splitlines()):
            return True, "loaded"
    except Exception:
        pass
    if Path("/sys/module/cifs").exists():
        return True, "loaded"
    if shutil.which("mount.cifs"):
        return True, "available"
    return False, "missing"


def get_system_health_data(config: dict) -> Dict[str, Any]:
    base = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    root = base.parent if base.name == "scripts" else base
    jobs_dir = root / "config" / "jobs"
    secrets_dir = root / "secrets"
    migration_file = root / "config" / "migration-state.json"
    migration_log_file = root / "config" / "migrations.log.jsonl"
    repositories_inventory_file = root / "config" / "repositories.json"
    storages_inventory_file = root / "config" / "storages.json"

    inventory_errors: list[dict[str, str]] = []
    try:
        from repositories_api import read_repository_store
        read_repository_store(config)
    except Exception as exc:
        inventory_errors.append({"inventory": "repositories", "path": str(repositories_inventory_file), "error": str(exc)})
    try:
        from storage_objects_api import read_storage_store
        read_storage_store(config)
    except Exception as exc:
        inventory_errors.append({"inventory": "storages", "path": str(storages_inventory_file), "error": str(exc)})
    inventories_ok = not inventory_errors

    migration = _read_migration_state(migration_file)
    migration_log = _read_migration_log(migration_log_file)
    migration_summary = _build_migration_summary(migration, migration_log)
    try:
        from migration_api import get_migration_registry_status
        migration_registry = get_migration_registry_status(config)
    except Exception as exc:
        migration_registry = {
            "schema_version": 1,
            "items": [],
            "summary": {"total": 0, "pending": 0, "failed": 0, "planned": 0},
            "error": str(exc),
        }
    last_effective = migration_log.get("last_effective_event") if isinstance(migration_log, dict) else {}
    if not isinstance(last_effective, dict):
        last_effective = {}
    last_effective_ts = str(last_effective.get("timestamp", "") or "").strip()
    mount_bin = shutil.which("mount")
    umount_bin = shutil.which("umount")
    cifs_supported, cifs_state = _probe_cifs_support()

    config_dir = root / "config"
    settings_json = config_dir / "settings.json"
    api_token_file = config_dir / ".api-token"
    ui_auth_file = config_dir / ".ui-auth.json"

    def _mode_octal(path: Path) -> str:
        try:
            return oct(path.stat().st_mode & 0o777)
        except Exception:
            return "n/a"

    def _secure_600(path: Path) -> bool:
        try:
            mode = path.stat().st_mode & 0o777
            return mode == 0o600
        except Exception:
            return False

    secret_candidates = []
    for p in secrets_dir.glob(".smb-*.cred"):
        if p.is_file():
            secret_candidates.append(p)
    for p in secrets_dir.glob(".borg-passphrase-*"):
        if p.is_file():
            secret_candidates.append(p)
    for p in secrets_dir.glob(".ntfy-*"):
        if p.is_file():
            secret_candidates.append(p)
    if api_token_file.exists():
        secret_candidates.append(api_token_file)
    if ui_auth_file.exists():
        secret_candidates.append(ui_auth_file)
    if settings_json.exists():
        secret_candidates.append(settings_json)

    bad_perm = []
    for p in secret_candidates:
        if not _secure_600(p):
            bad_perm.append({"path": str(p), "mode": _mode_octal(p)})

    secrets_permissions_ok = len(bad_perm) == 0
    perm_msg = "All checked secret files have mode 600."
    if not secret_candidates:
        perm_msg = "No secret files were found for permission checks."
    elif bad_perm:
        perm_msg = f"{len(bad_perm)} file(s) have unexpected permissions."
    job_health = _collect_job_health(config, jobs_dir)
    try:
        runtime_lib = Path(__file__).resolve().parents[1] / "runtime" / "lib"
        if str(runtime_lib) not in sys.path:
            sys.path.insert(0, str(runtime_lib))
        from runtime_recovery import runtime_recovery_file_from_env, summarize_runtime_recovery
        runtime_recovery = summarize_runtime_recovery(runtime_recovery_file_from_env(config))
    except Exception as exc:
        runtime_recovery = {
            "state_file": str(root / "config" / "runtime-recovery.json"),
            "pending_count": 0,
            "docker_pending_count": 0,
            "vm_pending_count": 0,
            "entries": [],
            "error": str(exc),
        }
    return {
        "checks": {
            "data_root_ok": root.is_dir(),
            "jobs_path_ok": jobs_dir.is_dir(),
            "secrets_path_ok": secrets_dir.is_dir(),
            "last_migration_successful": _last_migration_successful(migration),
            "last_effective_migration_exists": bool(last_effective_ts),
            "mount_bin_ok": bool(mount_bin and umount_bin),
            "cifs_supported": bool(cifs_supported),
            "cifs_state": cifs_state,
            "secrets_permissions_ok": secrets_permissions_ok,
            "canonical_inventories_ok": inventories_ok,
        },
        "paths": {
            "data_root": str(root),
            "jobs": str(jobs_dir),
            "secrets": str(secrets_dir),
            "migration_state_file": str(migration_file),
            "migration_log_file": str(migration_log_file),
            "repositories_inventory_file": str(repositories_inventory_file),
            "storages_inventory_file": str(storages_inventory_file),
            "mount_bin": str(mount_bin or ""),
            "umount_bin": str(umount_bin or ""),
        },
        "last_migration": migration,
        "migration_log": migration_log,
        "migration_summary": migration_summary,
        "migration_registry": migration_registry,
        "job_health": job_health,
        "runtime_recovery": runtime_recovery,
        "secrets_permissions": {
            "ok": secrets_permissions_ok,
            "message": perm_msg,
            "bad_files": bad_perm,
            "checked_files_count": len(secret_candidates),
        },
        "canonical_inventories": {
            "ok": inventories_ok,
            "errors": inventory_errors,
        },
    }
