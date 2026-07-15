"""
api/settings_transfer_api.py

Export/Import von Job-Konfigurationen sowie verschlüsseltes Backup von
Passphrase-Dateien.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from config_api import get_smb_profile_job_refs
from job_source_paths import SourcePathValidationError, upgrade_job_source_paths
from jobs_api import get_jobs_meta_dir, resolve_data_root, resolve_scripts_dir
from schedule_api import get_schedules, write_schedules


_AUTHENTICATED_EXPORT_MAGIC = b"BBUI-AUTH-ENC-V2\n"
_AUTHENTICATED_PLAINTEXT_MAGIC = b"BBUI-AUTH-PLAINTEXT-V2\n"
_AUTHENTICATED_EXPORT_FORMAT = "bbui-authenticated-export"
_AUTHENTICATED_EXPORT_VERSION = 2
_AUTHENTICATED_EXPORT_ITERATIONS = 200000
_AUTHENTICATED_EXPORT_SALT_BYTES = 16
_AUTHENTICATED_EXPORT_TAG_BYTES = 32
_LEGACY_OPENSSL_MAGIC = b"Salted__"
_ENCRYPTION_FORMAT_AUTHENTICATED = "authenticated-v2"
_ENCRYPTION_FORMAT_LEGACY = "legacy-openssl-aes-256-cbc"


def _canonical_profile_payload(config: dict) -> dict:
    from storage_objects_api import settings_profiles_from_storages
    profiles = settings_profiles_from_storages(config)
    return {
        "schema_version": 1,
        "local_profiles": profiles.get("local_profiles", []),
        "usb_profiles": profiles.get("usb_profiles", []),
        "smb_profiles": profiles.get("smb_profiles", []),
        "storage_profiles": profiles.get("storage_profiles", []),
    }


def _write_canonical_profile_payload(config: dict, payload: dict) -> None:
    from storage_objects_api import replace_all_profile_storages
    replace_all_profile_storages(config, payload)


def _jobs_dir(config: dict) -> Path:
    scripts_dir = resolve_scripts_dir(config)
    data_root = resolve_data_root(config)
    d = get_jobs_meta_dir(scripts_dir, data_root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _schedules_path(config: dict) -> Path:
    base = Path(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup"))
    return base / "config" / "schedules.json"


def export_jobs_bundle(config: dict, selected_keys: List[str] | None = None) -> dict:
    selected = set((selected_keys or []))
    jobs_dir = _jobs_dir(config)
    schedules = get_schedules(config)
    jobs: List[dict] = []
    repository_keys: set[str] = set()
    for p in sorted(jobs_dir.glob("*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        key = str(raw.get("job_key") or p.stem).strip()
        if selected and key not in selected:
            continue
        jobs.append(raw)
        repository_key = str(raw.get("repository_key") or "").strip()
        if repository_key:
            repository_keys.add(repository_key)

    from repositories_api import read_repository_store
    from storage_objects_api import read_storage_store
    repositories = [
        row for row in read_repository_store(config).get("repositories", [])
        if str(row.get("repository_key") or "").strip() in repository_keys
    ]
    storage_keys = {str(row.get("storage_key") or "").strip() for row in repositories}
    storages = [
        row for row in read_storage_store(config).get("storages", [])
        if str(row.get("storage_key") or "").strip() in storage_keys
    ]
    passphrase_meta: Dict[str, dict] = {}
    for repository in repositories:
        repository_key = str(repository.get("repository_key") or "").strip()
        pp_path = str(repository.get("passphrase_ref") or "").strip()
        if pp_path:
            f = Path(pp_path)
            if f.exists() and f.is_file():
                b = f.read_bytes()
                passphrase_meta[repository_key] = {
                    "path": str(f),
                    "exists": True,
                    "sha256": hashlib.sha256(b).hexdigest(),
                    "size": len(b),
                }
            else:
                passphrase_meta[repository_key] = {"path": pp_path, "exists": False}
    bundle = {
        "format": "bbui-job-bundle-v2",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "jobs": jobs,
        "repositories": repositories,
        "storages": storages,
        "schedules": {k: v for k, v in schedules.items() if not selected or k in selected},
        "passphrase_meta": passphrase_meta,
        "keyfile_meta": {},
        "settings_payload": _canonical_profile_payload(config),
    }
    bundle["keyfile_meta"] = _collect_job_key_files(config, bundle, include_content=False)
    text = json.dumps(bundle, indent=2, ensure_ascii=False) + "\n"
    return {
        "bundle": bundle,
        "bundle_text": text,
        "filename": f"bbui-jobs-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json",
        "job_count": len(jobs),
    }


def _collect_job_passphrase_files(bundle: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    repositories = bundle.get("repositories") if isinstance(bundle.get("repositories"), list) else []
    for repository in repositories:
        if not isinstance(repository, dict):
            continue
        repository_key = str(repository.get("repository_key") or "").strip()
        if not repository_key:
            continue
        pp_path = str(repository.get("passphrase_ref") or "").strip()
        if not pp_path:
            continue
        p = Path(pp_path)
        if not p.is_file():
            continue
        content = p.read_bytes()
        out[repository_key] = {
            "path": str(p),
            "sha256": hashlib.sha256(content).hexdigest(),
            "content_b64": base64.b64encode(content).decode("ascii"),
        }
    return out


def _collect_job_key_files(config: dict, bundle: dict, *, include_content: bool) -> dict[str, dict]:
    from borg_key_store import borg_keys_dir, find_key_file, is_keyfile_encryption

    out: dict[str, dict] = {}
    repositories = bundle.get("repositories") if isinstance(bundle.get("repositories"), list) else []
    for repository in repositories:
        if not isinstance(repository, dict) or not is_keyfile_encryption(repository.get("encryption")):
            continue
        repository_key = str(repository.get("repository_key") or "").strip()
        repository_id = str(repository.get("borg_repository_id") or "").strip().lower()
        if not repository_key or not repository_id:
            continue
        key_file = find_key_file(borg_keys_dir(config), repository_id)
        if key_file is None:
            out[repository_key] = {"repository_id": repository_id, "exists": False}
            continue
        content = key_file.read_bytes()
        row = {
            "repository_id": repository_id,
            "filename": key_file.name,
            "exists": True,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }
        if include_content:
            row["content_b64"] = base64.b64encode(content).decode("ascii")
        out[repository_key] = row
    return out


def _normalize_job_key(base: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(base or "").strip())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def _resolve_import_key(existing: set[str], desired: str, mode: str) -> Tuple[str | None, str]:
    key = _normalize_job_key(desired)
    if not key:
        return None, "invalid"
    if key not in existing:
        return key, "new"
    if mode == "skip":
        return None, "skipped_exists"
    if mode == "overwrite":
        return key, "overwrite"
    if mode == "rename":
        idx = 2
        while f"{key}_{idx}" in existing:
            idx += 1
        return f"{key}_{idx}", "renamed"
    return None, "skipped_exists"


def _canonical_import_jobs(jobs: list, selected: set[str] | None = None) -> list:
    """Upgrade old bundle jobs at the import boundary, never during runtime."""
    normalized: list = []
    for raw in jobs:
        if not isinstance(raw, dict):
            normalized.append(raw)
            continue
        source_key = str(raw.get("job_key") or "").strip()
        if selected and source_key not in selected:
            normalized.append(dict(raw))
            continue
        label = source_key or "<unknown>"
        try:
            normalized.append(upgrade_job_source_paths(raw, job_key=label))
        except SourcePathValidationError as exc:
            raise ValueError(
                f"Imported job '{label}' cannot be converted to structured source paths: {exc}"
            ) from exc
    return normalized


def _job_preview_rows(config: dict, bundle: dict) -> list[dict]:
    jobs = bundle.get("jobs") if isinstance(bundle.get("jobs"), list) else []
    schedules = bundle.get("schedules") if isinstance(bundle.get("schedules"), dict) else {}
    pp_meta = bundle.get("passphrase_meta") if isinstance(bundle.get("passphrase_meta"), dict) else {}
    jobs_dir = _jobs_dir(config)
    existing = {p.stem for p in jobs_dir.glob("*.json")}
    rows: list[dict] = []
    for raw in jobs:
        if not isinstance(raw, dict):
            continue
        src_key = str(raw.get("job_key") or "").strip()
        key_norm = _normalize_job_key(src_key)
        conflict = "new"
        if not key_norm:
            conflict = "invalid"
        elif key_norm in existing:
            conflict = "exists"
        schedule = schedules.get(src_key, {})
        feats = raw.get("features") if isinstance(raw.get("features"), dict) else {}
        repository_key = str(raw.get("repository_key") or "").strip()
        pp = pp_meta.get(repository_key) if isinstance(pp_meta.get(repository_key), dict) else {}
        pp_status = "unknown"
        pp_local = None
        if pp:
            pth = str(pp.get("path") or "").strip()
            if pth:
                lf = Path(pth)
                if lf.exists() and lf.is_file():
                    lb = lf.read_bytes()
                    lhash = hashlib.sha256(lb).hexdigest()
                    pp_local = {"path": str(lf), "sha256": lhash, "size": len(lb)}
                    if pp.get("sha256"):
                        pp_status = "present_match" if pp.get("sha256") == lhash else "present_mismatch"
                    else:
                        pp_status = "present"
                else:
                    pp_status = "missing"
        rows.append({
            "job_key": src_key,
            "name": str(raw.get("name") or src_key),
            "backup_type": str(raw.get("backup_type") or ""),
            "location": str(raw.get("location") or ""),
            "features": {"docker": bool(feats.get("docker")), "vm": bool(feats.get("vm"))},
            "schedule": schedule if isinstance(schedule, dict) else {},
            "conflict": conflict,
            "suggested_mode": "overwrite" if conflict == "exists" else "skip",
            "passphrase": {"status": pp_status, "bundle": pp, "local": pp_local},
        })
    return rows


def preview_jobs_bundle(config: dict, bundle: dict) -> dict:
    if not isinstance(bundle, dict):
        raise ValueError("Invalid bundle")
    if bundle.get("format") != "bbui-job-bundle-v2":
        raise ValueError("Unknown bundle format")
    normalized_bundle = dict(bundle)
    normalized_bundle["jobs"] = _canonical_import_jobs(
        bundle.get("jobs") if isinstance(bundle.get("jobs"), list) else []
    )
    rows = _job_preview_rows(config, normalized_bundle)
    settings_preview = _preview_settings_payload(config, bundle.get("settings_payload"))
    return {
        "format": bundle.get("format"),
        "job_count": len(rows),
        "jobs": rows,
        "settings_preview": settings_preview,
    }


def _backup_settings_snapshot(config: dict, reason: str = "Settings-Import") -> str | None:
    from storage_objects_api import storages_file
    source = storages_file(config)
    if not source.exists():
        return None
    bdir = source.parent / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = bdir / f"storages.json.{ts}.bak"
    dst.write_bytes(source.read_bytes())
    os.chmod(dst, 0o600)
    meta = {
        "reason": reason,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
    }
    (bdir / f"{dst.name}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(dst)


def _normalize_profiles_by_key(rows: list[dict], kind: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip().lower()
        if not key:
            continue
        out[key] = dict(row)
    return out


def _preview_settings_payload(config: dict, incoming_payload: dict | None) -> dict:
    current = _canonical_profile_payload(config)
    incoming = incoming_payload if isinstance(incoming_payload, dict) else {}
    cur_usb = _normalize_profiles_by_key(current.get("usb_profiles") if isinstance(current.get("usb_profiles"), list) else [], "usb")
    cur_smb = _normalize_profiles_by_key(current.get("smb_profiles") if isinstance(current.get("smb_profiles"), list) else [], "smb")
    cur_storage = _normalize_profiles_by_key(current.get("storage_profiles") if isinstance(current.get("storage_profiles"), list) else [], "storage")
    in_usb = _normalize_profiles_by_key(incoming.get("usb_profiles") if isinstance(incoming.get("usb_profiles"), list) else [], "usb")
    in_smb = _normalize_profiles_by_key(incoming.get("smb_profiles") if isinstance(incoming.get("smb_profiles"), list) else [], "smb")
    in_storage = _normalize_profiles_by_key(incoming.get("storage_profiles") if isinstance(incoming.get("storage_profiles"), list) else [], "storage")
    smb_refs = get_smb_profile_job_refs(config)

    def classify(current_rows: dict[str, dict], incoming_rows: dict[str, dict], with_refs: bool = False) -> list[dict]:
        rows: list[dict] = []
        for key in sorted(incoming_rows.keys()):
            inc = incoming_rows[key]
            cur = current_rows.get(key)
            if cur is None:
                status = "new"
            elif cur == inc:
                status = "unchanged"
            else:
                status = "conflict"
            item = {
                "key": key,
                "name": str(inc.get("name") or key),
                "status": status,
            }
            if with_refs:
                refs = smb_refs.get(key, [])
                item["jobs_count"] = len(refs)
                item["job_refs"] = refs[:10]
            rows.append(item)
        return rows

    usb_rows = classify(cur_usb, in_usb, with_refs=False)
    smb_rows = classify(cur_smb, in_smb, with_refs=True)
    storage_rows = classify(cur_storage, in_storage, with_refs=False)
    return {
        "present": bool(incoming_rows_count := (len(in_usb) + len(in_smb) + len(in_storage))),
        "profiles_total": incoming_rows_count,
        "usb": usb_rows,
        "smb": smb_rows,
        "storage": storage_rows,
    }


def _apply_settings_payload(
    config: dict,
    incoming_payload: dict | None,
    settings_mode: str,
    per_profile_mode: dict | None,
) -> tuple[bool, dict, str | None]:
    if settings_mode == "ignore":
        return False, {"mode": "ignore", "applied": 0, "conflicts": 0}, None
    if not isinstance(incoming_payload, dict):
        return False, {"mode": settings_mode, "applied": 0, "conflicts": 0}, None

    current = _canonical_profile_payload(config)
    per_mode = per_profile_mode if isinstance(per_profile_mode, dict) else {}
    in_usb = _normalize_profiles_by_key(incoming_payload.get("usb_profiles") if isinstance(incoming_payload.get("usb_profiles"), list) else [], "usb")
    in_smb = _normalize_profiles_by_key(incoming_payload.get("smb_profiles") if isinstance(incoming_payload.get("smb_profiles"), list) else [], "smb")
    in_storage = _normalize_profiles_by_key(incoming_payload.get("storage_profiles") if isinstance(incoming_payload.get("storage_profiles"), list) else [], "storage")
    cur_usb = _normalize_profiles_by_key(current.get("usb_profiles") if isinstance(current.get("usb_profiles"), list) else [], "usb")
    cur_smb = _normalize_profiles_by_key(current.get("smb_profiles") if isinstance(current.get("smb_profiles"), list) else [], "smb")
    cur_storage = _normalize_profiles_by_key(current.get("storage_profiles") if isinstance(current.get("storage_profiles"), list) else [], "storage")

    if settings_mode == "replace":
        backup_path = _backup_settings_snapshot(config, reason="Settings-Import replace")
        replace_payload = {
            **incoming_payload,
            "local_profiles": incoming_payload.get("local_profiles")
            if isinstance(incoming_payload.get("local_profiles"), list)
            else current.get("local_profiles", []),
        }
        _write_canonical_profile_payload(config, replace_payload)
        return True, {"mode": "replace", "applied": len(in_usb) + len(in_smb) + len(in_storage), "conflicts": 0}, backup_path

    # merge
    applied = 0
    conflicts = 0

    def merge_rows(current_rows: dict[str, dict], incoming_rows: dict[str, dict], scope: str) -> dict[str, dict]:
        nonlocal applied, conflicts
        out = dict(current_rows)
        for key, row in incoming_rows.items():
            cur = out.get(key)
            if cur is None:
                out[key] = row
                applied += 1
                continue
            if cur == row:
                continue
            conflicts += 1
            action = str(per_mode.get(f"{scope}:{key}", "skip")).strip().lower()
            if action not in {"skip", "overwrite", "rename"}:
                action = "skip"
            if action == "overwrite":
                out[key] = row
                applied += 1
                continue
            if action == "rename":
                idx = 2
                new_key = f"{key}_{idx}"
                while new_key in out:
                    idx += 1
                    new_key = f"{key}_{idx}"
                renamed = dict(row)
                renamed["key"] = new_key
                out[new_key] = renamed
                applied += 1
                continue
            # skip
        return out

    next_usb = merge_rows(cur_usb, in_usb, "usb")
    next_smb = merge_rows(cur_smb, in_smb, "smb")
    next_storage = merge_rows(cur_storage, in_storage, "storage")
    next_payload = {
        "schema_version": current.get("schema_version", incoming_payload.get("schema_version", 1)),
        "local_profiles": current.get("local_profiles", []),
        "usb_profiles": list(next_usb.values()),
        "smb_profiles": list(next_smb.values()),
        "storage_profiles": list(next_storage.values()),
    }
    if next_payload != current:
        backup_path = _backup_settings_snapshot(config, reason="Settings-Import merge")
        _write_canonical_profile_payload(config, next_payload)
        return True, {"mode": "merge", "applied": applied, "conflicts": conflicts}, backup_path
    return False, {"mode": "merge", "applied": applied, "conflicts": conflicts}, None


def _apply_repository_inventory(config: dict, bundle: dict, jobs: list[dict], dry_run: bool) -> dict:
    from repositories_api import read_repository_store, write_repository_store
    from storage_objects_api import read_storage_store, write_storage_store

    incoming_repositories = [row for row in (bundle.get("repositories") or []) if isinstance(row, dict)]
    incoming_storages = [row for row in (bundle.get("storages") or []) if isinstance(row, dict)]
    referenced_repository_keys = {
        str(job.get("repository_key") or "").strip() for job in jobs if isinstance(job, dict)
    }
    referenced_repository_keys.discard("")
    incoming_repositories = [
        row for row in incoming_repositories
        if str(row.get("repository_key") or "").strip() in referenced_repository_keys
    ]
    referenced_storage_keys = {
        str(row.get("storage_key") or "").strip() for row in incoming_repositories
    }
    incoming_storages = [
        row for row in incoming_storages
        if str(row.get("storage_key") or "").strip() in referenced_storage_keys
    ]

    current_repositories = read_repository_store(config).get("repositories", [])
    current_storages = read_storage_store(config).get("storages", [])
    repositories_by_key = {str(row.get("repository_key") or "").strip(): row for row in current_repositories}
    storages_by_key = {str(row.get("storage_key") or "").strip(): row for row in current_storages}

    for storage in incoming_storages:
        key = str(storage.get("storage_key") or "").strip()
        if not key:
            raise ValueError("Imported storage target has no key")
        existing = storages_by_key.get(key)
        if existing and str(existing.get("identity") or "") != str(storage.get("identity") or ""):
            raise ValueError(f"Storage key conflict: {key}")
        storages_by_key.setdefault(key, storage)

    for repository in incoming_repositories:
        repository = dict(repository)
        # A keyfile path belongs to the source host. Secure imports restore the
        # key into this host's canonical BORG_KEYS_DIR after inventory import.
        repository.pop("keyfile_ref", None)
        key = str(repository.get("repository_key") or "").strip()
        if not key:
            raise ValueError("Imported repository has no key")
        storage_key = str(repository.get("storage_key") or "").strip()
        if storage_key not in storages_by_key:
            raise ValueError(f"Imported repository references an unknown storage target: {storage_key}")
        existing = repositories_by_key.get(key)
        incoming_identity = (
            storage_key,
            str(repository.get("relative_path") or "").rstrip("/"),
        )
        existing_identity = (
            str((existing or {}).get("storage_key") or ""),
            str((existing or {}).get("relative_path") or "").rstrip("/"),
        )
        if existing and existing_identity != incoming_identity:
            raise ValueError(f"Repository key conflict: {key}")
        repositories_by_key.setdefault(key, repository)

    missing = sorted(key for key in referenced_repository_keys if key not in repositories_by_key)
    if missing:
        raise ValueError(f"Imported jobs reference missing repositories: {', '.join(missing)}")

    if not dry_run:
        write_storage_store(config, {"storages": list(storages_by_key.values())})
        write_repository_store(config, {"repositories": list(repositories_by_key.values())})
    return {
        "repositories": len(incoming_repositories),
        "storages": len(incoming_storages),
    }


def import_jobs_bundle(
    config: dict,
    bundle: dict,
    mode: str = "skip",
    dry_run: bool = True,
    selected_jobs: list[str] | None = None,
    per_job_mode: dict | None = None,
    settings_mode: str = "merge",
    per_profile_mode: dict | None = None,
) -> dict:
    if mode not in {"skip", "overwrite", "rename"}:
        raise ValueError("Invalid import mode")
    if not isinstance(bundle, dict):
        raise ValueError("Invalid bundle")
    if bundle.get("format") != "bbui-job-bundle-v2":
        raise ValueError("Unknown bundle format")
    if settings_mode not in {"ignore", "merge", "replace"}:
        raise ValueError("Invalid settings import mode")

    jobs = bundle.get("jobs")
    schedules = bundle.get("schedules") if isinstance(bundle.get("schedules"), dict) else {}
    if not isinstance(jobs, list):
        raise ValueError("Bundle does not contain a job list")

    selected_set = set(str(x).strip() for x in (selected_jobs or []) if str(x).strip())
    jobs = _canonical_import_jobs(jobs, selected_set or None)
    inventory_jobs = [
        row for row in jobs
        if isinstance(row, dict) and (not selected_set or str(row.get("job_key") or "").strip() in selected_set)
    ]
    inventory_report = _apply_repository_inventory(config, bundle, inventory_jobs, bool(dry_run))

    jobs_dir = _jobs_dir(config)
    existing_files = {p.stem for p in jobs_dir.glob("*.json")}
    existing = set(existing_files)
    report: List[dict] = []
    applied_jobs: List[Tuple[str, dict]] = []
    schedule_updates: Dict[str, dict] = {}

    selected = selected_set
    per_mode = per_job_mode if isinstance(per_job_mode, dict) else {}

    for raw in jobs:
        if not isinstance(raw, dict):
            continue
        src_key = str(raw.get("job_key") or "").strip()
        if selected and src_key not in selected:
            report.append({"job_key": src_key, "status": "skipped_unselected"})
            continue
        mode_job = str(per_mode.get(src_key, mode)).strip().lower()
        if mode_job not in {"skip", "overwrite", "rename"}:
            mode_job = mode
        final_key, action = _resolve_import_key(existing, src_key, mode_job)
        if not final_key:
            report.append({"job_key": src_key, "status": action})
            continue
        patched = dict(raw)
        patched["job_key"] = final_key
        if final_key != src_key:
            name = str(patched.get("name") or final_key)
            if f"({src_key})" not in name and src_key:
                patched["name"] = f"{name} ({final_key})"
        applied_jobs.append((final_key, patched))
        existing.add(final_key)
        if src_key in schedules:
            schedule_updates[final_key] = schedules[src_key]
        report.append({"job_key": src_key, "new_job_key": final_key, "status": action, "mode": mode_job})

    settings_applied = False
    settings_report = {"mode": settings_mode, "applied": 0, "conflicts": 0}
    settings_backup = None
    settings_payload = bundle.get("settings_payload")
    if not dry_run:
        settings_applied, settings_report, settings_backup = _apply_settings_payload(
            config,
            settings_payload,
            settings_mode=settings_mode,
            per_profile_mode=per_profile_mode,
        )

    if not dry_run:
        for key, raw in applied_jobs:
            target = jobs_dir / f"{key}.json"
            target.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # merge schedules
        merged = get_schedules(config)
        merged.update(schedule_updates)
        write_schedules(config, merged)

    return {
        "dry_run": bool(dry_run),
        "mode": mode,
        "report": report,
        "imported_count": len(applied_jobs),
        "scheduled_count": len(schedule_updates),
        "settings_applied": settings_applied,
        "settings_report": settings_report,
        "settings_backup": settings_backup,
        "repository_inventory": inventory_report,
    }


def _secrets_dir() -> Path:
    p = Path("/boot/config/borg-backup/secrets")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _valid_secret_backup_name(name: str) -> bool:
    value = str(name or "")
    if value.startswith((".borg-passphrase-", ".smb-", ".ntfy-")) and "/" not in value:
        return True
    if value.startswith("borg-keys/"):
        leaf = value.removeprefix("borg-keys/")
        return bool(leaf) and "/" not in leaf and leaf not in {".", ".."}
    return False


def _safe_key(value: str) -> str:
    raw = str(value or "").strip().lower()
    out = "".join(ch if (ch.isalnum() or ch in ("-", "_")) else "-" for ch in raw)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def _default_smb_secret_file(profile_key: str) -> Path:
    return _secrets_dir() / f".smb-{_safe_key(profile_key)}.cred"


def _collect_profile_secrets(settings_payload: dict) -> list[dict]:
    secrets: list[dict] = []
    smb_rows = settings_payload.get("smb_profiles") if isinstance(settings_payload.get("smb_profiles"), list) else []
    storage_rows = settings_payload.get("storage_profiles") if isinstance(settings_payload.get("storage_profiles"), list) else []

    for row in smb_rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip().lower()
        if not key:
            continue
        p = Path(str(row.get("password_file") or "").strip() or _default_smb_secret_file(key))
        if not p.is_file():
            continue
        raw = p.read_bytes()
        secrets.append({
            "profile_type": "smb",
            "profile_key": key,
            "secret_type": "smb_cred",
            "target_path": str(p),
            "filename": p.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "mode": int(p.stat().st_mode & 0o777),
            "content_b64": base64.b64encode(raw).decode("ascii"),
        })

    for row in storage_rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip().lower()
        if not key:
            continue
        priv = Path(str(row.get("ssh_key_path") or "").strip())
        if not priv.is_file():
            continue
        priv_raw = priv.read_bytes()
        secrets.append({
            "profile_type": "storage",
            "profile_key": key,
            "secret_type": "ssh_private_key",
            "target_path": str(priv),
            "filename": priv.name,
            "sha256": hashlib.sha256(priv_raw).hexdigest(),
            "mode": int(priv.stat().st_mode & 0o777),
            "content_b64": base64.b64encode(priv_raw).decode("ascii"),
        })
        pub = Path(str(priv) + ".pub")
        if pub.is_file():
            pub_raw = pub.read_bytes()
            secrets.append({
                "profile_type": "storage",
                "profile_key": key,
                "secret_type": "ssh_public_key",
                "target_path": str(pub),
                "filename": pub.name,
                "sha256": hashlib.sha256(pub_raw).hexdigest(),
                "mode": int(pub.stat().st_mode & 0o777),
                "content_b64": base64.b64encode(pub_raw).decode("ascii"),
            })
    return secrets


def _profile_maps(settings_payload: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    smb: dict[str, dict] = {}
    storage: dict[str, dict] = {}
    for row in (settings_payload.get("smb_profiles") or []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip().lower()
        if key:
            smb[key] = dict(row)
    for row in (settings_payload.get("storage_profiles") or []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip().lower()
        if key:
            storage[key] = dict(row)
    return smb, storage


def _target_path_for_profile_secret(
    profile_type: str,
    secret_type: str,
    profile_key: str,
    smb_map: dict[str, dict],
    storage_map: dict[str, dict],
) -> str:
    if profile_type == "smb" and secret_type == "smb_cred":
        row = smb_map.get(profile_key) or {}
        return str(row.get("password_file") or "").strip() or str(_default_smb_secret_file(profile_key))
    if profile_type == "storage" and secret_type in {"ssh_private_key", "ssh_public_key"}:
        row = storage_map.get(profile_key) or {}
        base = str(row.get("ssh_key_path") or "").strip()
        if not base:
            return ""
        return base if secret_type == "ssh_private_key" else f"{base}.pub"
    return ""


def _canonical_json_bytes(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _openssl_encrypt_cbc(plaintext: bytes, password: str) -> bytes:
    env = dict(os.environ)
    env["BBUI_SECRET_PASS"] = password
    proc = subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-salt",
            "-iter",
            str(_AUTHENTICATED_EXPORT_ITERATIONS),
            "-md",
            "sha256",
            "-pass",
            "env:BBUI_SECRET_PASS",
        ],
        input=plaintext,
        capture_output=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("Encrypted export could not be created")
    return proc.stdout


def _openssl_decrypt_cbc(ciphertext: bytes, password: str, *, legacy: bool = False) -> bytes:
    env = dict(os.environ)
    env["BBUI_SECRET_PASS"] = password
    command = [
        "openssl",
        "enc",
        "-d",
        "-aes-256-cbc",
        "-pbkdf2",
        "-iter",
        str(_AUTHENTICATED_EXPORT_ITERATIONS),
    ]
    if not legacy:
        command.extend(["-md", "sha256"])
    command.extend(["-pass", "env:BBUI_SECRET_PASS"])
    proc = subprocess.run(
        command,
        input=ciphertext,
        capture_output=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        if legacy:
            raise ValueError("Legacy encrypted export could not be decrypted (invalid password or file)")
        raise ValueError("Encrypted export could not be decrypted")
    return proc.stdout


def _authenticated_export_header(auth_salt: bytes) -> dict:
    return {
        "format": _AUTHENTICATED_EXPORT_FORMAT,
        "version": _AUTHENTICATED_EXPORT_VERSION,
        "cipher": {
            "name": "aes-256-cbc",
            "kdf": "pbkdf2-hmac-sha256",
            "iterations": _AUTHENTICATED_EXPORT_ITERATIONS,
            "salt": "openssl-embedded",
        },
        "authentication": {
            "name": "hmac-sha256",
            "kdf": "pbkdf2-hmac-sha256",
            "iterations": _AUTHENTICATED_EXPORT_ITERATIONS,
            "salt_b64": base64.b64encode(auth_salt).decode("ascii"),
        },
    }


def _derive_export_authentication_key(password: str, auth_salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        auth_salt,
        _AUTHENTICATED_EXPORT_ITERATIONS,
        dklen=_AUTHENTICATED_EXPORT_TAG_BYTES,
    )


def _authenticated_export_mac_input(header: dict, ciphertext: bytes) -> bytes:
    return _AUTHENTICATED_EXPORT_MAGIC + _canonical_json_bytes(header) + b"\0" + ciphertext


def _encrypt_authenticated_export(plaintext: bytes, password: str) -> bytes:
    auth_salt = os.urandom(_AUTHENTICATED_EXPORT_SALT_BYTES)
    header = _authenticated_export_header(auth_salt)
    ciphertext = _openssl_encrypt_cbc(_AUTHENTICATED_PLAINTEXT_MAGIC + plaintext, password)
    auth_key = _derive_export_authentication_key(password, auth_salt)
    tag = hmac.new(
        auth_key,
        _authenticated_export_mac_input(header, ciphertext),
        hashlib.sha256,
    ).digest()
    envelope = {
        "protected": header,
        "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
        "tag_b64": base64.b64encode(tag).decode("ascii"),
    }
    return _AUTHENTICATED_EXPORT_MAGIC + _canonical_json_bytes(envelope)


def _validate_authenticated_export_header(header: object) -> bytes:
    if not isinstance(header, dict):
        raise ValueError("Encrypted export is invalid or truncated")
    expected = _authenticated_export_header(b"placeholder")
    authentication = header.get("authentication")
    if not isinstance(authentication, dict):
        raise ValueError("Encrypted export is invalid or truncated")
    salt_b64 = authentication.get("salt_b64")
    comparable = dict(header)
    comparable["authentication"] = dict(authentication)
    comparable["authentication"]["salt_b64"] = expected["authentication"]["salt_b64"]
    if comparable != expected:
        raise ValueError("Unsupported encrypted export parameters")
    try:
        auth_salt = base64.b64decode(str(salt_b64 or "").encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise ValueError("Encrypted export is invalid or truncated") from exc
    if len(auth_salt) != _AUTHENTICATED_EXPORT_SALT_BYTES:
        raise ValueError("Encrypted export is invalid or truncated")
    return auth_salt


def _decrypt_encrypted_export(payload: bytes, password: str) -> tuple[bytes, str]:
    if payload.startswith(_AUTHENTICATED_EXPORT_MAGIC):
        try:
            envelope = json.loads(payload[len(_AUTHENTICATED_EXPORT_MAGIC):].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Encrypted export is invalid or truncated") from exc
        if not isinstance(envelope, dict):
            raise ValueError("Encrypted export is invalid or truncated")
        header = envelope.get("protected")
        auth_salt = _validate_authenticated_export_header(header)
        try:
            ciphertext = base64.b64decode(
                str(envelope.get("ciphertext_b64") or "").encode("ascii"),
                validate=True,
            )
            supplied_tag = base64.b64decode(
                str(envelope.get("tag_b64") or "").encode("ascii"),
                validate=True,
            )
        except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
            raise ValueError("Encrypted export is invalid or truncated") from exc
        if not ciphertext.startswith(_LEGACY_OPENSSL_MAGIC) or len(supplied_tag) != _AUTHENTICATED_EXPORT_TAG_BYTES:
            raise ValueError("Encrypted export is invalid or truncated")
        auth_key = _derive_export_authentication_key(password, auth_salt)
        expected_tag = hmac.new(
            auth_key,
            _authenticated_export_mac_input(header, ciphertext),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_tag, expected_tag):
            raise ValueError("Encrypted export authentication failed (invalid password or modified file)")
        plaintext = _openssl_decrypt_cbc(ciphertext, password)
        if not plaintext.startswith(_AUTHENTICATED_PLAINTEXT_MAGIC):
            raise ValueError("Encrypted export authentication failed (invalid password or modified file)")
        return plaintext[len(_AUTHENTICATED_PLAINTEXT_MAGIC):], _ENCRYPTION_FORMAT_AUTHENTICATED

    if payload.startswith(_LEGACY_OPENSSL_MAGIC):
        if len(payload) <= len(_LEGACY_OPENSSL_MAGIC):
            raise ValueError("Legacy encrypted export is invalid or truncated")
        return _openssl_decrypt_cbc(payload, password, legacy=True), _ENCRYPTION_FORMAT_LEGACY

    raise ValueError("Unsupported encrypted export format")


def _decode_encrypted_export_payload(payload_b64: str) -> bytes:
    try:
        payload = base64.b64decode(str(payload_b64 or "").encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise ValueError("Encrypted export is invalid or truncated") from exc
    if not payload:
        raise ValueError("Encrypted export is invalid or truncated")
    return payload


def _decode_encrypted_json_payload(plaintext: bytes) -> dict:
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Encrypted export payload is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("Encrypted export payload is invalid")
    return payload


def _encryption_preview_metadata(encryption_format: str) -> dict:
    return {
        "encryption_format": encryption_format,
        "legacy_encryption": encryption_format == _ENCRYPTION_FORMAT_LEGACY,
    }


def export_secrets_backup(password: str) -> dict:
    pw = str(password or "")
    if len(pw) < 8:
        raise ValueError("Password must contain at least 8 characters")
    files = []
    candidates = list(_secrets_dir().glob(".*"))
    candidates.extend(sorted((_secrets_dir() / "borg-keys").glob("*")))
    for p in sorted(candidates):
        if not p.is_file():
            continue
        name = f"borg-keys/{p.name}" if p.parent.name == "borg-keys" else p.name
        if not _valid_secret_backup_name(name):
            continue
        raw = p.read_bytes()
        files.append(
            {
                "name": name,
                "content_b64": base64.b64encode(raw).decode("ascii"),
                "mode": int(p.stat().st_mode & 0o777),
                "mtime": int(p.stat().st_mtime),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    payload = {
        "format": "bbui-secrets-backup-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    encrypted = _encrypt_authenticated_export(plaintext, pw)
    return {
        "filename": f"bbui-secrets-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.enc",
        "payload_b64": base64.b64encode(encrypted).decode("ascii"),
        "count": len(files),
    }


def preview_secrets_backup(password: str, payload_b64: str) -> dict:
    enc = _decode_encrypted_export_payload(payload_b64)
    plaintext, encryption_format = _decrypt_encrypted_export(enc, str(password or ""))
    payload = _decode_encrypted_json_payload(plaintext)
    if payload.get("format") != "bbui-secrets-backup-v1":
        raise ValueError("Invalid secrets backup format")
    files = payload.get("files") or []
    if not isinstance(files, list):
        raise ValueError("Invalid secrets file list")
    rows = []
    td = _secrets_dir()
    for item in files:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not _valid_secret_backup_name(name):
            continue
        target = td / name
        local_hash = None
        status = "missing"
        if target.exists() and target.is_file():
            lb = target.read_bytes()
            local_hash = hashlib.sha256(lb).hexdigest()
            src_hash = str(item.get("sha256") or "")
            if src_hash:
                status = "present_match" if src_hash == local_hash else "present_mismatch"
            else:
                status = "present"
        rows.append({"name": name, "status": status, "source_sha256": str(item.get("sha256") or ""), "local_sha256": local_hash})
    return {
        "format": payload.get("format"),
        "count": len(rows),
        "files": rows,
        **_encryption_preview_metadata(encryption_format),
    }


def import_secrets_backup(
    password: str,
    payload_b64: str,
    mode: str = "skip",
    selected_names: list[str] | None = None,
) -> dict:
    if mode not in {"skip", "overwrite", "rename"}:
        raise ValueError("Invalid import mode")
    enc = _decode_encrypted_export_payload(payload_b64)
    plaintext, encryption_format = _decrypt_encrypted_export(enc, str(password or ""))
    payload = _decode_encrypted_json_payload(plaintext)
    if payload.get("format") != "bbui-secrets-backup-v1":
        raise ValueError("Invalid secrets backup format")
    files = payload.get("files") or []
    if not isinstance(files, list):
        raise ValueError("Invalid secrets file list")

    target_dir = _secrets_dir()
    written = 0
    report = []
    selected = set(str(x).strip() for x in (selected_names or []) if str(x).strip())
    for item in files:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if selected and name not in selected:
            report.append({"name": name, "status": "skipped_unselected"})
            continue
        if not _valid_secret_backup_name(name):
            report.append({"name": name, "status": "invalid_name"})
            continue
        target = target_dir / name
        if target.exists():
            if mode == "skip":
                report.append({"name": name, "status": "skipped_exists"})
                continue
            if mode == "rename":
                idx = 2
                base = name
                while (target_dir / f"{base}.{idx}").exists():
                    idx += 1
                target = target_dir / f"{base}.{idx}"
        content = base64.b64decode(str(item.get("content_b64") or "").encode("ascii"), validate=False)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.parent.name == "borg-keys":
            os.chmod(target.parent, 0o700)
        target.write_bytes(content)
        os.chmod(target, 0o600)
        written += 1
        report.append({"name": name, "written_as": target.name, "status": "written"})
    return {
        "restored_count": written,
        "report": report,
        **_encryption_preview_metadata(encryption_format),
    }


def export_jobs_bundle_encrypted(config: dict, password: str, selected_keys: list[str] | None = None) -> dict:
    pw = str(password or "")
    if len(pw) < 8:
        raise ValueError("Password must contain at least 8 characters")
    plain = export_jobs_bundle(config, selected_keys=selected_keys)
    bundle = plain.get("bundle") if isinstance(plain.get("bundle"), dict) else {}
    # Secure jobs bundle intentionally excludes settings payload:
    # this artifact is for jobs + job passphrases only.
    bundle = dict(bundle)
    bundle.pop("settings_payload", None)
    passphrase_files = _collect_job_passphrase_files(bundle)
    key_files = _collect_job_key_files(config, bundle, include_content=True)
    payload = {
        "format": "bbui-job-bundle-secure-v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bundle": bundle,
        "passphrase_files": passphrase_files,
        "key_files": key_files,
    }
    encrypted = _encrypt_authenticated_export(json.dumps(payload, ensure_ascii=False).encode("utf-8"), pw)
    return {
        "filename": f"bbui-jobs-secure-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jobs.enc",
        "payload_b64": base64.b64encode(encrypted).decode("ascii"),
        "job_count": int(plain.get("job_count") or 0),
        "passphrase_count": len(passphrase_files),
        "keyfile_count": sum(1 for row in key_files.values() if row.get("exists")),
    }


def preview_jobs_bundle_encrypted(config: dict, password: str, payload_b64: str) -> dict:
    enc = _decode_encrypted_export_payload(payload_b64)
    plaintext, encryption_format = _decrypt_encrypted_export(enc, str(password or ""))
    payload = _decode_encrypted_json_payload(plaintext)
    if payload.get("format") != "bbui-job-bundle-secure-v2":
        raise ValueError("Unknown encrypted jobs format")
    bundle = payload.get("bundle")
    bundle = dict(bundle) if isinstance(bundle, dict) else {}
    bundle.pop("settings_payload", None)
    out = preview_jobs_bundle(config, bundle)
    out["secure_format"] = payload.get("format")
    out["passphrase_count"] = len(payload.get("passphrase_files") or {})
    out["keyfile_count"] = len(payload.get("key_files") or {})
    out.update(_encryption_preview_metadata(encryption_format))
    return out


def import_jobs_bundle_encrypted(
    config: dict,
    password: str,
    payload_b64: str,
    mode: str = "skip",
    dry_run: bool = True,
    selected_jobs: list[str] | None = None,
    per_job_mode: dict | None = None,
    settings_mode: str = "merge",
    per_profile_mode: dict | None = None,
    import_jobs: bool = True,
    import_passphrases: bool = True,
) -> dict:
    enc = _decode_encrypted_export_payload(payload_b64)
    plaintext, encryption_format = _decrypt_encrypted_export(enc, str(password or ""))
    payload = _decode_encrypted_json_payload(plaintext)
    if payload.get("format") != "bbui-job-bundle-secure-v2":
        raise ValueError("Unknown encrypted jobs format")
    bundle = payload.get("bundle")
    if not isinstance(bundle, dict):
        raise ValueError("Invalid bundle")
    passphrase_files = payload.get("passphrase_files") if isinstance(payload.get("passphrase_files"), dict) else {}
    key_files = payload.get("key_files") if isinstance(payload.get("key_files"), dict) else {}

    # Secure jobs import intentionally ignores settings payload.
    bundle = dict(bundle)
    bundle.pop("settings_payload", None)
    if import_jobs:
        result = import_jobs_bundle(
            config,
            bundle,
            mode=mode,
            dry_run=dry_run,
            selected_jobs=selected_jobs,
            per_job_mode=per_job_mode,
            settings_mode="ignore",
            per_profile_mode=per_profile_mode,
        )
    else:
        result = {
            "dry_run": bool(dry_run),
            "mode": mode,
            "report": [],
            "imported_count": 0,
            "scheduled_count": 0,
            "settings_applied": False,
            "settings_report": {"mode": "ignore", "applied": 0, "conflicts": 0},
            "settings_backup": None,
        }

    restored = 0
    if not dry_run and import_passphrases and passphrase_files:
        from repositories_api import read_repository_store
        repositories = {
            str(row.get("repository_key") or "").strip(): row
            for row in read_repository_store(config).get("repositories", [])
        }
        for repository_key, raw_file in passphrase_files.items():
            pf = raw_file if isinstance(raw_file, dict) else None
            if not pf:
                continue
            repository = repositories.get(str(repository_key or "").strip())
            if not repository:
                continue
            pp_path = str(repository.get("passphrase_ref") or "").strip()
            if not pp_path:
                continue
            try:
                content = base64.b64decode(str(pf.get("content_b64") or "").encode("ascii"), validate=False)
            except Exception:
                continue
            target = Path(pp_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            os.chmod(target, 0o600)
            restored += 1
    result["restored_passphrases"] = restored
    restored_keys = 0
    if not dry_run and import_passphrases and key_files:
        from borg_key_store import ensure_borg_keys_dir, find_key_file, repository_id_from_key_file
        from repositories_api import read_repository_store, write_repository_store

        store = read_repository_store(config)
        repositories = {
            str(row.get("repository_key") or "").strip(): row
            for row in store.get("repositories", [])
        }
        changed = False
        for repository_key, raw_file in key_files.items():
            key_row = raw_file if isinstance(raw_file, dict) else {}
            repository = repositories.get(str(repository_key or "").strip())
            if not repository or not key_row.get("exists"):
                continue
            expected_id = str(repository.get("borg_repository_id") or key_row.get("repository_id") or "").strip().lower()
            if not expected_id or expected_id != str(key_row.get("repository_id") or "").strip().lower():
                continue
            try:
                content = base64.b64decode(str(key_row.get("content_b64") or "").encode("ascii"), validate=False)
            except Exception:
                continue
            if len(content) > 1024 * 1024:
                continue
            key_dir = ensure_borg_keys_dir(config)
            current = find_key_file(key_dir, expected_id)
            if current is None:
                target = key_dir / f"bbui-{expected_id}"
                if target.exists():
                    continue
                target.write_bytes(content)
                os.chmod(target, 0o600)
                if repository_id_from_key_file(target) != expected_id:
                    target.unlink(missing_ok=True)
                    continue
                current = target
                restored_keys += 1
            elif current.read_bytes() != content:
                continue
            repository["keyfile_ref"] = str(current)
            changed = True
        if changed:
            write_repository_store(config, {"repositories": list(repositories.values())})
    result["restored_keyfiles"] = restored_keys
    result.update(_encryption_preview_metadata(encryption_format))
    return result


def export_profile_secrets_backup(config: dict, password: str) -> dict:
    pw = str(password or "")
    if len(pw) < 8:
        raise ValueError("Password must contain at least 8 characters")
    settings_payload = _canonical_profile_payload(config)
    entries = _collect_profile_secrets(settings_payload)
    payload = {
        "format": "bbui-profile-secrets-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "settings_payload": {
            "smb_profiles": settings_payload.get("smb_profiles") if isinstance(settings_payload.get("smb_profiles"), list) else [],
            "storage_profiles": settings_payload.get("storage_profiles") if isinstance(settings_payload.get("storage_profiles"), list) else [],
        },
        "manifest": [
            {
                "profile_type": e["profile_type"],
                "profile_key": e["profile_key"],
                "secret_type": e["secret_type"],
                "target_path": e["target_path"],
                "filename": e["filename"],
                "sha256": e["sha256"],
                "mode": e["mode"],
            }
            for e in entries
        ],
        "files": [
            {
                "profile_type": e["profile_type"],
                "profile_key": e["profile_key"],
                "secret_type": e["secret_type"],
                "content_b64": e["content_b64"],
            }
            for e in entries
        ],
    }
    plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    encrypted = _encrypt_authenticated_export(plaintext, pw)
    return {
        "filename": f"bbui-profile-secrets-{datetime.now().strftime('%Y%m%d-%H%M%S')}.profiles.enc",
        "payload_b64": base64.b64encode(encrypted).decode("ascii"),
        "count": len(entries),
    }


def preview_profile_secrets_backup(config: dict, password: str, payload_b64: str) -> dict:
    enc = _decode_encrypted_export_payload(payload_b64)
    plaintext, encryption_format = _decrypt_encrypted_export(enc, str(password or ""))
    payload = _decode_encrypted_json_payload(plaintext)
    if payload.get("format") != "bbui-profile-secrets-v1":
        raise ValueError("Invalid profile secrets format")
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), list) else []
    incoming_settings_payload = payload.get("settings_payload") if isinstance(payload.get("settings_payload"), dict) else None
    settings_payload = _canonical_profile_payload(config)
    smb_map, storage_map = _profile_maps(settings_payload)
    smb_keys = set(smb_map.keys())
    storage_keys = set(storage_map.keys())

    rows = []
    for m in manifest:
        if not isinstance(m, dict):
            continue
        ptype = str(m.get("profile_type") or "").strip().lower()
        pkey = str(m.get("profile_key") or "").strip().lower()
        stype = str(m.get("secret_type") or "").strip()
        target_path = str(m.get("target_path") or "").strip()
        source_sha = str(m.get("sha256") or "").strip()
        profile_exists = (pkey in smb_keys) if ptype == "smb" else (pkey in storage_keys if ptype == "storage" else False)
        resolved_target_path = _target_path_for_profile_secret(ptype, stype, pkey, smb_map, storage_map) or target_path

        status = "profile_missing" if not profile_exists else "missing"
        local_sha = ""
        tp = Path(resolved_target_path) if resolved_target_path else Path("")
        if profile_exists and tp.is_file():
            lb = tp.read_bytes()
            local_sha = hashlib.sha256(lb).hexdigest()
            status = "present_match" if (source_sha and source_sha == local_sha) else "present_mismatch"
        rows.append({
            "profile_type": ptype,
            "profile_key": pkey,
            "secret_type": stype,
            "target_path": resolved_target_path,
            "status": status,
            "source_sha256": source_sha,
            "local_sha256": local_sha,
        })
    return {
        "format": payload.get("format"),
        "count": len(rows),
        "entries": rows,
        "settings_preview": _preview_settings_payload(config, incoming_settings_payload),
        "profile_options": {
            "smb": sorted(smb_keys),
            "storage": sorted(storage_keys),
        },
        **_encryption_preview_metadata(encryption_format),
    }


def import_profile_secrets_backup(
    config: dict,
    password: str,
    payload_b64: str,
    mode: str = "skip",
    selected_entries: list[str] | None = None,
    profile_map: dict | None = None,
    settings_mode: str = "merge",
    per_profile_mode: dict | None = None,
) -> dict:
    if mode not in {"skip", "overwrite"}:
        raise ValueError("Invalid import mode (allowed: skip, overwrite)")
    if settings_mode not in {"ignore", "merge", "replace"}:
        raise ValueError("Invalid settings import mode")

    enc = _decode_encrypted_export_payload(payload_b64)
    plaintext, encryption_format = _decrypt_encrypted_export(enc, str(password or ""))
    payload = _decode_encrypted_json_payload(plaintext)
    if payload.get("format") != "bbui-profile-secrets-v1":
        raise ValueError("Invalid profile secrets format")

    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), list) else []
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    incoming_settings_payload = payload.get("settings_payload") if isinstance(payload.get("settings_payload"), dict) else None
    file_map = {}
    for f in files:
        if not isinstance(f, dict):
            continue
        fid = f"{str(f.get('profile_type') or '').lower()}:{str(f.get('profile_key') or '').lower()}:{str(f.get('secret_type') or '')}"
        file_map[fid] = f

    settings_applied, settings_report, settings_backup = _apply_settings_payload(
        config,
        incoming_settings_payload,
        settings_mode=settings_mode,
        per_profile_mode=per_profile_mode if isinstance(per_profile_mode, dict) else None,
    )

    settings_payload = _canonical_profile_payload(config)
    smb_map, storage_map = _profile_maps(settings_payload)
    smb_keys = set(smb_map.keys())
    storage_keys = set(storage_map.keys())
    map_override = profile_map if isinstance(profile_map, dict) else {}
    selected = set(str(x).strip() for x in (selected_entries or []) if str(x).strip())

    restored = 0
    report = []
    for m in manifest:
        if not isinstance(m, dict):
            continue
        ptype = str(m.get("profile_type") or "").strip().lower()
        pkey = str(m.get("profile_key") or "").strip().lower()
        stype = str(m.get("secret_type") or "").strip()
        entry_id = f"{ptype}:{pkey}:{stype}"
        if selected and entry_id not in selected:
            report.append({"entry_id": entry_id, "status": "skipped_unselected"})
            continue

        mapped_profile_key = str(map_override.get(entry_id) or pkey).strip().lower()
        profile_exists = (mapped_profile_key in smb_keys) if ptype == "smb" else (mapped_profile_key in storage_keys if ptype == "storage" else False)
        if not profile_exists:
            report.append({"entry_id": entry_id, "status": "skipped_profile_missing"})
            continue

        target_path = _target_path_for_profile_secret(ptype, stype, mapped_profile_key, smb_map, storage_map)
        if not target_path:
            report.append({"entry_id": entry_id, "status": "invalid_target"})
            continue
        target = Path(target_path)
        source_file = file_map.get(entry_id)
        if not source_file:
            report.append({"entry_id": entry_id, "status": "missing_content"})
            continue
        if target.exists() and mode == "skip":
            report.append({"entry_id": entry_id, "status": "skipped_exists"})
            continue

        try:
            content = base64.b64decode(str(source_file.get("content_b64") or "").encode("ascii"), validate=False)
        except Exception:
            report.append({"entry_id": entry_id, "status": "invalid_content"})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        os.chmod(target, 0o600)
        restored += 1
        report.append({"entry_id": entry_id, "status": "written", "target_path": str(target), "profile_key": mapped_profile_key})
    return {
        "restored_count": restored,
        "report": report,
        "settings_applied": settings_applied,
        "settings_report": settings_report,
        "settings_backup": settings_backup,
        **_encryption_preview_metadata(encryption_format),
    }
