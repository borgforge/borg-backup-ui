"""
api/system_health_api.py – kleiner Systemzustand fuer Migration/Verzeichnislayout.
"""

import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any, Dict


def _read_migration_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "success": False,
            "message": "Noch kein Migrationslauf protokolliert.",
            "timestamp": "",
            "reason_code": "none",
            "reason_text": "Noch kein Lauf",
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
            "message": "Migrationsstatus nicht lesbar.",
            "timestamp": "",
            "reason_code": "unreadable",
            "reason_text": "Migrationsstatus nicht lesbar",
            "details": {},
        }


def _is_effective_migration(entry: Dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False
    if str(entry.get("reason_code", "")).strip() and str(entry.get("reason_code", "")).strip() != "no_changes":
        return True
    details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
    storage = details.get("storage_paths") if isinstance(details.get("storage_paths"), dict) else {}
    jobs = details.get("jobs_layout") if isinstance(details.get("jobs_layout"), dict) else {}
    if bool(storage.get("changed")) or bool(storage.get("settings_changed")) or bool(storage.get("forced_conf_write")):
        return True
    if int(storage.get("moved") or 0) > 0:
        return True
    if int(storage.get("move_errors") or 0) > 0:
        return True
    if str(jobs.get("status", "")).strip().lower() not in {"", "ok"}:
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
            "state": "Noch kein Lauf",
            "last_run": "",
            "last_effective_run": last_effective_ts,
            "last_effective_exists": bool(last_effective_ts),
            "reason_code": "none",
            "reason": "Noch kein Migrationslauf protokolliert",
            "actions": [],
            "errors": [],
            "technical_message": "",
        }

    ok = bool(last_event.get("success", False))
    reason_code = str(last_event.get("reason_code", "") or "").strip()
    reason_text = str(last_event.get("reason_text", "") or "").strip()
    message = str(last_event.get("message", "") or "").strip()
    details = last_event.get("details") if isinstance(last_event.get("details"), dict) else {}
    storage = details.get("storage_paths") if isinstance(details.get("storage_paths"), dict) else {}
    jobs = details.get("jobs_layout") if isinstance(details.get("jobs_layout"), dict) else {}

    actions = []
    errors = []
    moved = _as_int(storage.get("moved"))
    move_errors = _as_int(storage.get("move_errors"))
    if moved > 0:
        actions.append(f"{moved} Elemente verschoben")
    if bool(storage.get("changed")):
        actions.append("Storage-Pfade aktualisiert")
    if bool(storage.get("settings_changed")):
        actions.append("Profileinstellungen angepasst")
    if bool(storage.get("forced_conf_write")):
        actions.append("backup.conf korrigiert")
    if str(jobs.get("status", "")).strip().lower() not in {"", "ok"}:
        errors.append(f"Job-Layout: {jobs.get('error') or jobs.get('status')}")
    if move_errors > 0:
        errors.append(f"{move_errors} Verschiebe-Fehler")
    if not ok and not errors:
        errors.append("Migration fehlgeschlagen")

    reason = reason_text or (
        "Änderung des Cache/Remotes inkl. backup.conf-Anpassung"
        if reason_code == "storage_paths_changed"
        else ("Keine Änderungen nötig" if reason_code == "no_changes" else ("Migration ausgeführt" if ok else "Migration mit Fehlern"))
    )
    return {
        "status": "success" if ok else "failed",
        "state": "Erfolgreich" if ok else "Fehlgeschlagen",
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
    try:
        from storage_profiles_api import normalize_storage_profile_rows
        from config_api import read_settings_payload
        settings = read_settings_payload(config)
        storage_profiles = normalize_storage_profile_rows(
            settings.get("storage_profiles") if isinstance(settings.get("storage_profiles"), list) else []
        )
    except Exception:
        storage_profiles = []
    storage_by_key = {
        str(row.get("key") or "").strip().lower(): row
        for row in storage_profiles
        if str(row.get("key") or "").strip()
    }

    items = []
    if jobs_dir.is_dir():
        job_files = sorted(jobs_dir.glob("*.json"))
    else:
        job_files = []

    for meta_file in job_files:
        try:
            raw = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception as exc:
            items.append({
                "job_key": meta_file.stem,
                "name": meta_file.stem,
                "state": "bad",
                "errors": [f"Job-Metadaten nicht lesbar: {exc}"],
                "warnings": [],
            })
            continue
        if not isinstance(raw, dict):
            continue
        job_key = str(raw.get("job_key") or meta_file.stem).strip()
        name = str(raw.get("name") or job_key).strip()
        location = str(raw.get("location") or "").strip().lower()
        errors: list[str] = []
        warnings: list[str] = []

        repo_cfg = raw.get("repo") if isinstance(raw.get("repo"), dict) else {}
        repo = str(repo_cfg.get("default") or "").strip()
        if not repo:
            errors.append("Repository fehlt")
        elif location == "storagebox":
            if not repo.startswith("ssh://"):
                errors.append("Storagebox-Repository ist keine ssh:// URI")
            else:
                parts = urlsplit(repo)
                if not parts.netloc or not parts.path.startswith("/"):
                    errors.append("Storagebox-Repository-URI ist unvollständig")
                if ":23." in repo:
                    errors.append("Storagebox-Repository-URI enthält fehlenden Slash nach Port")

        paths_cfg = raw.get("paths") if isinstance(raw.get("paths"), dict) else {}
        source_paths = _split_job_paths(paths_cfg.get("default"))
        if not source_paths:
            errors.append("Quellpfade fehlen")
        else:
            missing = [p for p in source_paths if not Path(p).exists()]
            if missing:
                errors.append(f"{len(missing)} Quellpfad(e) nicht vorhanden")

        encryption = str(raw.get("encryption") or "").strip().lower()
        pass_cfg = raw.get("passphrase") if isinstance(raw.get("passphrase"), dict) else {}
        pass_mode = str(pass_cfg.get("mode") or "").strip().lower()
        pass_path = str(pass_cfg.get("default") or "").strip()
        if encryption != "none" and pass_mode != "none":
            if not pass_path:
                errors.append("Passphrase-Datei fehlt in Metadaten")
            elif not Path(pass_path).is_file():
                errors.append("Passphrase-Datei nicht vorhanden")

        if location == "storagebox":
            profile_key = str(raw.get("storage_profile_key") or "").strip().lower()
            profile = storage_by_key.get(profile_key)
            if not profile_key:
                errors.append("Storage-Profil fehlt")
            elif profile is None:
                errors.append(f"Storage-Profil '{profile_key}' nicht gefunden")
            else:
                ssh_key = str(profile.get("ssh_key_path") or "").strip()
                if ssh_key and not Path(ssh_key).is_file():
                    errors.append("SSH-Key-Datei nicht vorhanden")
                if not str(profile.get("host") or "").strip() or not str(profile.get("user") or "").strip():
                    errors.append("Storage-Profil ist unvollständig")

        state = "bad" if errors else ("warn" if warnings else "ok")
        items.append({
            "job_key": job_key,
            "name": name,
            "location": location,
            "state": state,
            "errors": errors,
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


def get_system_health_data(config: dict) -> Dict[str, Any]:
    base = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    root = base.parent if base.name == "scripts" else base
    jobs_dir = root / "config" / "jobs"
    secrets_dir = root / "secrets"
    migration_file = root / "config" / "migration-state.json"
    migration_log_file = root / "config" / "migrations.log.jsonl"

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
    cifs_supported = False
    cifs_state = "missing"
    try:
        filesystems = Path("/proc/filesystems").read_text(encoding="utf-8", errors="replace")
        if any("cifs" in line for line in filesystems.splitlines()):
            cifs_supported = True
            cifs_state = "loaded"
    except Exception:
        pass
    if not cifs_supported:
        try:
            modules = Path("/proc/modules").read_text(encoding="utf-8", errors="replace")
            if any(line.startswith("cifs ") for line in modules.splitlines()):
                cifs_supported = True
                cifs_state = "loaded"
        except Exception:
            pass
    if not cifs_supported:
        try:
            probe = subprocess.run(
                ["modinfo", "cifs"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if probe.returncode == 0:
                cifs_supported = True
                cifs_state = "available"
        except Exception:
            pass

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
    perm_msg = "Alle geprüften Secret-Dateien haben 600."
    if not secret_candidates:
        perm_msg = "Keine Secret-Dateien für Rechteprüfung gefunden."
    elif bad_perm:
        perm_msg = f"{len(bad_perm)} Datei(en) mit abweichenden Rechten."
    job_health = _collect_job_health(config, jobs_dir)

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
        },
        "paths": {
            "data_root": str(root),
            "jobs": str(jobs_dir),
            "secrets": str(secrets_dir),
            "migration_state_file": str(migration_file),
            "migration_log_file": str(migration_log_file),
            "mount_bin": str(mount_bin or ""),
            "umount_bin": str(umount_bin or ""),
        },
        "last_migration": migration,
        "migration_log": migration_log,
        "migration_summary": migration_summary,
        "migration_registry": migration_registry,
        "job_health": job_health,
        "secrets_permissions": {
            "ok": secrets_permissions_ok,
            "message": perm_msg,
            "bad_files": bad_perm,
            "checked_files_count": len(secret_candidates),
        },
    }
