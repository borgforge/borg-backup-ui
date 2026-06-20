"""
api/settings_transfer_api.py

Export/Import von Job-Konfigurationen sowie verschlüsseltes Backup von
Passphrase-Dateien.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from config_api import get_smb_profile_job_refs, read_settings_payload, write_settings_payload
from jobs_api import get_jobs_meta_dir, resolve_data_root, resolve_scripts_dir
from schedule_api import get_schedules


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
    passphrase_meta: Dict[str, dict] = {}
    for p in sorted(jobs_dir.glob("*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        key = str(raw.get("job_key") or p.stem).strip()
        if selected and key not in selected:
            continue
        jobs.append(raw)
        pp = raw.get("passphrase") if isinstance(raw.get("passphrase"), dict) else {}
        pp_path = str(pp.get("default") or "").strip()
        if pp_path:
            f = Path(pp_path)
            if f.exists() and f.is_file():
                b = f.read_bytes()
                passphrase_meta[key] = {
                    "path": str(f),
                    "exists": True,
                    "sha256": hashlib.sha256(b).hexdigest(),
                    "size": len(b),
                }
            else:
                passphrase_meta[key] = {"path": pp_path, "exists": False}
    bundle = {
        "format": "bbui-job-bundle-v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "jobs": jobs,
        "schedules": {k: v for k, v in schedules.items() if not selected or k in selected},
        "passphrase_meta": passphrase_meta,
        "settings_payload": read_settings_payload(config),
    }
    text = json.dumps(bundle, indent=2, ensure_ascii=False) + "\n"
    return {
        "bundle": bundle,
        "bundle_text": text,
        "filename": f"bbui-jobs-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json",
        "job_count": len(jobs),
    }


def _collect_job_passphrase_files(bundle: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    jobs = bundle.get("jobs") if isinstance(bundle.get("jobs"), list) else []
    for raw in jobs:
        if not isinstance(raw, dict):
            continue
        job_key = str(raw.get("job_key") or "").strip()
        if not job_key:
            continue
        pp = raw.get("passphrase") if isinstance(raw.get("passphrase"), dict) else {}
        pp_path = str(pp.get("default") or "").strip()
        if not pp_path:
            continue
        p = Path(pp_path)
        if not p.is_file():
            continue
        content = p.read_bytes()
        out[job_key] = {
            "path": str(p),
            "sha256": hashlib.sha256(content).hexdigest(),
            "content_b64": base64.b64encode(content).decode("ascii"),
        }
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
        pp = pp_meta.get(src_key) if isinstance(pp_meta.get(src_key), dict) else {}
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
    if bundle.get("format") != "bbui-job-bundle-v1":
        raise ValueError("Unknown bundle format")
    rows = _job_preview_rows(config, bundle)
    settings_preview = _preview_settings_payload(config, bundle.get("settings_payload"))
    return {
        "format": bundle.get("format"),
        "job_count": len(rows),
        "jobs": rows,
        "settings_preview": settings_preview,
    }


def _settings_file(config: dict) -> Path:
    base = Path(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup"))
    return base / "config" / "settings.json"


def _backup_settings_snapshot(config: dict, reason: str = "Settings-Import") -> str | None:
    sf = _settings_file(config)
    if not sf.exists():
        return None
    bdir = sf.parent / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = bdir / f"settings.json.{ts}.bak"
    dst.write_text(sf.read_text(encoding="utf-8"), encoding="utf-8")
    meta = {
        "reason": reason,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(sf),
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
    current = read_settings_payload(config)
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

    current = read_settings_payload(config)
    per_mode = per_profile_mode if isinstance(per_profile_mode, dict) else {}
    in_usb = _normalize_profiles_by_key(incoming_payload.get("usb_profiles") if isinstance(incoming_payload.get("usb_profiles"), list) else [], "usb")
    in_smb = _normalize_profiles_by_key(incoming_payload.get("smb_profiles") if isinstance(incoming_payload.get("smb_profiles"), list) else [], "smb")
    in_storage = _normalize_profiles_by_key(incoming_payload.get("storage_profiles") if isinstance(incoming_payload.get("storage_profiles"), list) else [], "storage")
    cur_usb = _normalize_profiles_by_key(current.get("usb_profiles") if isinstance(current.get("usb_profiles"), list) else [], "usb")
    cur_smb = _normalize_profiles_by_key(current.get("smb_profiles") if isinstance(current.get("smb_profiles"), list) else [], "smb")
    cur_storage = _normalize_profiles_by_key(current.get("storage_profiles") if isinstance(current.get("storage_profiles"), list) else [], "storage")

    if settings_mode == "replace":
        backup_path = _backup_settings_snapshot(config, reason="Settings-Import replace")
        write_settings_payload(config, incoming_payload)
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
        "usb_profiles": list(next_usb.values()),
        "smb_profiles": list(next_smb.values()),
        "storage_profiles": list(next_storage.values()),
    }
    if next_payload != current:
        backup_path = _backup_settings_snapshot(config, reason="Settings-Import merge")
        write_settings_payload(config, next_payload)
        return True, {"mode": "merge", "applied": applied, "conflicts": conflicts}, backup_path
    return False, {"mode": "merge", "applied": applied, "conflicts": conflicts}, None


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
    if bundle.get("format") != "bbui-job-bundle-v1":
        raise ValueError("Unknown bundle format")
    if settings_mode not in {"ignore", "merge", "replace"}:
        raise ValueError("Invalid settings import mode")

    jobs = bundle.get("jobs")
    schedules = bundle.get("schedules") if isinstance(bundle.get("schedules"), dict) else {}
    if not isinstance(jobs, list):
        raise ValueError("Bundle does not contain a job list")

    jobs_dir = _jobs_dir(config)
    existing_files = {p.stem for p in jobs_dir.glob("*.json")}
    existing = set(existing_files)
    report: List[dict] = []
    applied_jobs: List[Tuple[str, dict]] = []
    schedule_updates: Dict[str, dict] = {}

    selected = set(str(x).strip() for x in (selected_jobs or []) if str(x).strip())
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
        sp = _schedules_path(config)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "dry_run": bool(dry_run),
        "mode": mode,
        "report": report,
        "imported_count": len(applied_jobs),
        "scheduled_count": len(schedule_updates),
        "settings_applied": settings_applied,
        "settings_report": settings_report,
        "settings_backup": settings_backup,
    }


def _secrets_dir() -> Path:
    p = Path("/boot/config/borg-backup/secrets")
    p.mkdir(parents=True, exist_ok=True)
    return p


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


def _openssl_encrypt(plaintext: bytes, password: str) -> bytes:
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
            "200000",
            "-pass",
            "env:BBUI_SECRET_PASS",
        ],
        input=plaintext,
        capture_output=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or b"").decode("utf-8", "ignore").strip() or "OpenSSL encryption failed")
    return proc.stdout


def _openssl_decrypt(ciphertext: bytes, password: str) -> bytes:
    env = dict(os.environ)
    env["BBUI_SECRET_PASS"] = password
    proc = subprocess.run(
        [
            "openssl",
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-iter",
            "200000",
            "-pass",
            "env:BBUI_SECRET_PASS",
        ],
        input=ciphertext,
        capture_output=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("Decryption failed (invalid password or file)")
    return proc.stdout


def export_secrets_backup(password: str) -> dict:
    pw = str(password or "")
    if len(pw) < 8:
        raise ValueError("Password must contain at least 8 characters")
    files = []
    for p in sorted(_secrets_dir().glob(".*")):
        if not p.is_file():
            continue
        if not (p.name.startswith(".borg-passphrase-") or p.name.startswith(".smb-")):
            continue
        raw = p.read_bytes()
        files.append(
            {
                "name": p.name,
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
    encrypted = _openssl_encrypt(plaintext, pw)
    return {
        "filename": f"bbui-secrets-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.enc",
        "payload_b64": base64.b64encode(encrypted).decode("ascii"),
        "count": len(files),
    }


def preview_secrets_backup(password: str, payload_b64: str) -> dict:
    enc = base64.b64decode(str(payload_b64 or "").encode("ascii"), validate=False)
    plaintext = _openssl_decrypt(enc, str(password or ""))
    payload = json.loads(plaintext.decode("utf-8"))
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
        if not (name.startswith(".borg-passphrase-") or name.startswith(".smb-")):
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
    return {"format": payload.get("format"), "count": len(rows), "files": rows}


def import_secrets_backup(
    password: str,
    payload_b64: str,
    mode: str = "skip",
    selected_names: list[str] | None = None,
) -> dict:
    if mode not in {"skip", "overwrite", "rename"}:
        raise ValueError("Invalid import mode")
    enc = base64.b64decode(str(payload_b64 or "").encode("ascii"), validate=False)
    plaintext = _openssl_decrypt(enc, str(password or ""))
    payload = json.loads(plaintext.decode("utf-8"))
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
        if not (name.startswith(".borg-passphrase-") or name.startswith(".smb-")):
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
        target.write_bytes(content)
        os.chmod(target, 0o600)
        written += 1
        report.append({"name": name, "written_as": target.name, "status": "written"})
    return {"restored_count": written, "report": report}


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
    payload = {
        "format": "bbui-job-bundle-secure-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bundle": bundle,
        "passphrase_files": passphrase_files,
    }
    encrypted = _openssl_encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"), pw)
    return {
        "filename": f"bbui-jobs-secure-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jobs.enc",
        "payload_b64": base64.b64encode(encrypted).decode("ascii"),
        "job_count": int(plain.get("job_count") or 0),
        "passphrase_count": len(passphrase_files),
    }


def preview_jobs_bundle_encrypted(config: dict, password: str, payload_b64: str) -> dict:
    enc = base64.b64decode(str(payload_b64 or "").encode("ascii"), validate=False)
    plaintext = _openssl_decrypt(enc, str(password or ""))
    payload = json.loads(plaintext.decode("utf-8"))
    if payload.get("format") != "bbui-job-bundle-secure-v1":
        raise ValueError("Unknown encrypted jobs format")
    bundle = payload.get("bundle")
    bundle = dict(bundle) if isinstance(bundle, dict) else {}
    bundle.pop("settings_payload", None)
    out = preview_jobs_bundle(config, bundle)
    out["secure_format"] = payload.get("format")
    out["passphrase_count"] = len(payload.get("passphrase_files") or {})
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
    enc = base64.b64decode(str(payload_b64 or "").encode("ascii"), validate=False)
    plaintext = _openssl_decrypt(enc, str(password or ""))
    payload = json.loads(plaintext.decode("utf-8"))
    if payload.get("format") != "bbui-job-bundle-secure-v1":
        raise ValueError("Unknown encrypted jobs format")
    bundle = payload.get("bundle")
    if not isinstance(bundle, dict):
        raise ValueError("Invalid bundle")
    passphrase_files = payload.get("passphrase_files") if isinstance(payload.get("passphrase_files"), dict) else {}

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
        jobs_dir = _jobs_dir(config)
        keys_map: dict[str, str] = {}
        if import_jobs:
            for row in (result.get("report") or []):
                if not isinstance(row, dict):
                    continue
                src_key = str(row.get("job_key") or "").strip()
                new_key = str(row.get("new_job_key") or "").strip()
                status = str(row.get("status") or "")
                if status in {"new", "overwrite", "renamed"} and src_key and new_key:
                    keys_map[src_key] = new_key
        else:
            for src_key in passphrase_files.keys():
                if (jobs_dir / f"{src_key}.json").is_file():
                    keys_map[src_key] = src_key

        for src_key, new_key in keys_map.items():
            pf = passphrase_files.get(src_key) if isinstance(passphrase_files.get(src_key), dict) else None
            if not pf:
                continue
            target_job_file = jobs_dir / f"{new_key}.json"
            if not target_job_file.is_file():
                continue
            try:
                job_raw = json.loads(target_job_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            pp = job_raw.get("passphrase") if isinstance(job_raw.get("passphrase"), dict) else {}
            pp_path = str(pp.get("default") or "").strip()
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
    return result


def export_profile_secrets_backup(config: dict, password: str) -> dict:
    pw = str(password or "")
    if len(pw) < 8:
        raise ValueError("Password must contain at least 8 characters")
    settings_payload = read_settings_payload(config)
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
    encrypted = _openssl_encrypt(plaintext, pw)
    return {
        "filename": f"bbui-profile-secrets-{datetime.now().strftime('%Y%m%d-%H%M%S')}.profiles.enc",
        "payload_b64": base64.b64encode(encrypted).decode("ascii"),
        "count": len(entries),
    }


def preview_profile_secrets_backup(config: dict, password: str, payload_b64: str) -> dict:
    enc = base64.b64decode(str(payload_b64 or "").encode("ascii"), validate=False)
    plaintext = _openssl_decrypt(enc, str(password or ""))
    payload = json.loads(plaintext.decode("utf-8"))
    if payload.get("format") != "bbui-profile-secrets-v1":
        raise ValueError("Invalid profile secrets format")
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), list) else []
    incoming_settings_payload = payload.get("settings_payload") if isinstance(payload.get("settings_payload"), dict) else None
    settings_payload = read_settings_payload(config)
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

    enc = base64.b64decode(str(payload_b64 or "").encode("ascii"), validate=False)
    plaintext = _openssl_decrypt(enc, str(password or ""))
    payload = json.loads(plaintext.decode("utf-8"))
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

    settings_payload = read_settings_payload(config)
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
    }
