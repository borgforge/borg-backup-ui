"""
api/smb_profiles_api.py - SMB-Profilverwaltung, Status und Lifecycle-Helfer.
"""
from __future__ import annotations

import json
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from smb_protocol import (
    build_smb_mount_options,
    classify_smb_mount_error,
    normalize_smb_version,
    sanitize_smb_error,
)


SMB_MANAGED_MOUNT_BASE = Path("/mnt/borg-backup-ui/smb")


def _smb_secret_path(profile_key: str) -> Path:
    safe_key = re.sub(r"[^a-z0-9_-]+", "-", str(profile_key or "").strip().lower()).strip("-")
    if not safe_key:
        safe_key = "smb-profile"
    return Path("/boot/config/borg-backup/secrets") / f".smb-{safe_key}.cred"


def _truthy(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "on"}


def _profile_slug(value: str, *, fallback: str = "smb") -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").strip()).strip("-")
    return slug or fallback


def generate_smb_mount_path(profile_name: str, *, suffix: str = "") -> str:
    """Return a managed SMB mount path for a new profile."""
    SMB_MANAGED_MOUNT_BASE.mkdir(parents=True, exist_ok=True)
    clean_suffix = re.sub(r"[^a-z0-9]+", "", str(suffix or "").strip().lower())[:8]
    if not clean_suffix:
        clean_suffix = uuid.uuid4().hex[:6]
    slug = _profile_slug(profile_name, fallback="")
    leaf = f"{slug}-smb-{clean_suffix}" if slug else f"smb-{clean_suffix}"
    return str(SMB_MANAGED_MOUNT_BASE / leaf)


def normalize_smb_profile_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for idx, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        server = str(row.get("server", "")).strip()
        share = str(row.get("share", "")).strip().lstrip("/")
        mount_path = str(row.get("mount_path", "")).strip()
        username = str(row.get("username", "")).strip()
        smb_password = str(row.get("smb_password", row.get("password", ""))).strip()
        vers = normalize_smb_version(row.get("vers"))
        sec = str(row.get("sec", "")).strip()
        if not name or not server or not share or not username:
            continue
        key = str(row.get("key", "")).strip().lower()
        if not key:
            pf_hint = str(row.get("password_file", "")).strip()
            m = re.search(r"\.smb-([a-z0-9_-]+)\.cred$", pf_hint, re.IGNORECASE)
            if m:
                key = m.group(1).strip().lower()
        if not key:
            key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or f"smb-{idx + 1}"
        while key in seen:
            key = f"{key}-{idx + 1}"
        seen.add(key)
        if not mount_path:
            mount_path = generate_smb_mount_path(name)
        password_file = str(row.get("password_file", "")).strip() or str(_smb_secret_path(key))
        password_set = bool(row.get("password_set", False))
        if not password_set:
            try:
                password_set = Path(password_file).is_file()
            except Exception:
                password_set = False
        out.append({
            "key": key,
            "name": name,
            "server": server,
            "share": share,
            "mount_path": mount_path,
            "username": username,
            "vers": vers,
            "sec": sec,
            "password_file": password_file,
            "smb_password": smb_password,
            "password_set": "true" if password_set else "false",
            "mount_at_start": _truthy(row.get("mount_at_start"), default=False),
            "keep_mounted": _truthy(row.get("keep_mounted"), default=False),
        })
    return out


def validate_smb_profiles_json(raw_value: str) -> List[Dict[str, Any]]:
    try:
        decoded = json.loads(str(raw_value or "[]"))
    except (json.JSONDecodeError, TypeError, ValueError):
        raise ValueError("SMB profile data is not valid JSON.")
    if not isinstance(decoded, list):
        raise ValueError("SMB profile data must be a list.")
    normalized = normalize_smb_profile_rows(decoded)
    if len(normalized) != len([x for x in decoded if isinstance(x, dict)]):
        raise ValueError("SMB profiles are incomplete. Required: name, server, share and username.")
    for row in normalized:
        pf = str(row.get("password_file", "")).strip()
        if not pf.startswith("/"):
            raise ValueError(f"SMB profile '{row.get('name','')}' does not have an absolute password file path.")
    return normalized


def prepare_smb_profiles_for_save(raw_value: str) -> List[Dict[str, Any]]:
    normalized = validate_smb_profiles_json(raw_value)
    if not normalized:
        return []
    secrets_dir = Path("/boot/config/borg-backup/secrets")
    secrets_dir.mkdir(parents=True, exist_ok=True)

    final_rows: List[Dict[str, Any]] = []
    for row in normalized:
        key = str(row.get("key", "")).strip()
        username = str(row.get("username", "")).strip()
        smb_password = str(row.get("smb_password", "")).strip()
        secret_file = _smb_secret_path(key)
        mount_path = str(row.get("mount_path", "")).strip()

        if smb_password:
            secret_file.write_text(f"username={username}\npassword={smb_password}\n", encoding="utf-8")
            secret_file.chmod(0o600)
        elif not secret_file.is_file():
            raise ValueError(f"SMB profile '{row.get('name','')}' requires a password when first saved.")
        Path(mount_path).mkdir(parents=True, exist_ok=True)

        final_rows.append({
            "key": key,
            "name": str(row.get("name", "")).strip(),
            "server": str(row.get("server", "")).strip(),
            "share": str(row.get("share", "")).strip(),
            "mount_path": mount_path,
            "username": username,
            "vers": normalize_smb_version(row.get("vers")),
            "sec": str(row.get("sec", "")).strip(),
            "password_file": str(secret_file),
            "mount_at_start": bool(row.get("mount_at_start", False)),
            "keep_mounted": bool(row.get("keep_mounted", False)),
        })
    return final_rows


def get_smb_profile_job_refs(ui_config: dict) -> Dict[str, List[str]]:
    from repository_context import profile_job_references
    return profile_job_references(ui_config, "smb")


def get_smb_profiles_with_status(ui_config: dict) -> List[Dict[str, Any]]:
    from storage_objects_api import settings_profiles_from_storages
    rows = validate_smb_profiles_json(json.dumps(settings_profiles_from_storages(ui_config).get("smb_profiles", [])))
    refs = get_smb_profile_job_refs(ui_config)
    out: List[Dict[str, Any]] = []
    for row in rows:
        key = str(row.get("key", "")).strip().lower()
        mount_path = str(row.get("mount_path", "")).strip()
        mounted = False
        if mount_path:
            try:
                proc = subprocess.run(
                    ["findmnt", "-T", mount_path, "-n", "-o", "FSTYPE"],
                    capture_output=True,
                    text=True,
                    timeout=4,
                    check=False,
                )
                fs = (proc.stdout or "").strip().lower()
                mounted = proc.returncode == 0 and fs in {"cifs", "smb3", "smbfs"}
            except Exception:
                mounted = False
        out.append({
            "key": key,
            "name": str(row.get("name", "")).strip(),
            "server": str(row.get("server", "")).strip(),
            "share": str(row.get("share", "")).strip(),
            "mount_path": mount_path,
            "username": str(row.get("username", "")).strip(),
            "vers": normalize_smb_version(row.get("vers")),
            "sec": str(row.get("sec", "")).strip(),
            "is_mounted": mounted,
            "mount_at_start": bool(row.get("mount_at_start", False)),
            "keep_mounted": bool(row.get("keep_mounted", False)),
            "jobs_count": len(refs.get(key, [])),
            "job_refs": refs.get(key, [])[:10],
        })
    return out


def run_smb_profile_action(ui_config: dict, profile_key: str, action: str) -> Dict[str, Any]:
    key = str(profile_key or "").strip().lower()
    act = str(action or "").strip().lower()
    if not key:
        raise ValueError("profile_key is missing")
    if act not in {"mount", "unmount", "test", "status"}:
        raise ValueError("Invalid action")

    profiles = {str(p.get("key") or "").strip().lower(): p for p in get_smb_profiles_with_status(ui_config)}
    profile = profiles.get(key)
    if not profile:
        raise ValueError(f"SMB profile not found: {key}")

    if act == "test":
        result = test_smb_profiles_status([{
            "key": profile["key"],
            "name": profile["name"],
            "server": profile["server"],
            "share": profile["share"],
            "mount_path": profile["mount_path"],
            "username": profile["username"],
            "vers": profile["vers"],
            "sec": profile["sec"],
            "password_set": True,
            "password_file": str(_smb_secret_path(profile["key"])),
        }])
        rows = result.get("results") if isinstance(result.get("results"), list) else []
        r = rows[0] if rows else {}
        return {"ok": bool(r.get("ok", False)), "action": "test", "result": r}

    src = f"//{profile['server']}/{str(profile['share']).lstrip('/')}"
    cred = str(_smb_secret_path(profile["key"]))
    mount_path = str(profile["mount_path"])
    Path(mount_path).mkdir(parents=True, exist_ok=True)

    def _mounted() -> bool:
        try:
            proc = subprocess.run(
                ["findmnt", "-T", mount_path, "-n", "-o", "FSTYPE"],
                capture_output=True, text=True, timeout=4, check=False
            )
            fs = (proc.stdout or "").strip().lower()
            return proc.returncode == 0 and fs in {"cifs", "smb3", "smbfs"}
        except Exception:
            return False

    if act == "status":
        mounted = _mounted()
        return {
            "ok": True,
            "action": "status",
            "is_mounted": mounted,
            "message": "Mounted" if mounted else "Not mounted",
            "message_code": "smb_mounted" if mounted else "smb_unmounted",
        }

    if act == "mount":
        if _mounted():
            return {
                "ok": True,
                "action": "mount",
                "message": "Already mounted",
                "message_code": "smb_already_mounted",
                "mounted_by_action": False,
            }
        opts = build_smb_mount_options(profile, cred)
        res = subprocess.run(
            ["mount", "-t", "cifs", src, mount_path, "-o", ",".join(opts)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        ok = res.returncode == 0
        if ok:
            return {
                "ok": True,
                "action": "mount",
                "message": "Mount OK",
                "message_code": "smb_mount_success",
                "mounted_by_action": True,
            }
        technical = sanitize_smb_error(res.stderr or res.stdout or "Mount failed")
        failure_code, failure_hint = classify_smb_mount_error(technical)
        return {
            "ok": False,
            "action": "mount",
            "message": failure_hint,
            "message_code": "smb_mount_failed",
            "failure_code": failure_code,
            "failure_hint": failure_hint,
            "technical_details": technical,
        }

    if not _mounted():
        return {"ok": True, "action": "unmount", "message": "Already unmounted", "message_code": "smb_already_unmounted"}
    res = subprocess.run(["umount", mount_path], capture_output=True, text=True, timeout=20, check=False)
    ok = res.returncode == 0
    msg = "Unmount OK" if ok else (res.stderr or res.stdout or "Unmount failed").strip()
    return {"ok": ok, "action": "unmount", "message": msg, "message_code": "smb_unmount_success" if ok else "smb_unmount_failed"}


def mount_startup_smb_profiles(ui_config: dict) -> Dict[str, Any]:
    """Mount SMB profiles explicitly configured for plugin startup."""
    rows = get_smb_profiles_with_status(ui_config)
    selected = [
        str(row.get("key") or "").strip().lower()
        for row in rows
        if bool(row.get("mount_at_start", False)) and str(row.get("key") or "").strip()
    ]
    result: Dict[str, Any] = {"requested": selected, "mounted": [], "already_mounted": [], "failed": []}
    for key in selected:
        try:
            action = run_smb_profile_action(ui_config, key, "mount")
            if action.get("ok") and action.get("message_code") == "smb_already_mounted":
                result["already_mounted"].append(key)
            elif action.get("ok"):
                result["mounted"].append(key)
            else:
                result["failed"].append({
                    "key": key,
                    "message": str(action.get("message") or "SMB mount failed"),
                    "failure_code": str(action.get("failure_code") or ""),
                })
        except Exception as exc:
            result["failed"].append({"key": key, "message": str(exc), "failure_code": ""})
    return result


def validate_smb_profile_usage_before_save(ui_config: dict, new_rows: List[Dict[str, str]]) -> None:
    new_keys = {str(r.get("key") or "").strip() for r in (new_rows or []) if str(r.get("key") or "").strip()}
    refs = get_smb_profile_job_refs(ui_config)
    blocked = []
    for key, jobs in refs.items():
        if key not in new_keys and jobs:
            blocked.append((key, jobs))
    if blocked:
        details = "; ".join(f"{k}: {', '.join(v[:5])}" for k, v in blocked)
        raise ValueError(
            "SMB profile cannot be deleted because jobs still use it. "
            f"Update those jobs first: {details}"
        )


def cleanup_removed_smb_mountpoints(
    previous_rows: List[Dict[str, str]],
    cleanup_keys: List[str],
) -> Dict[str, Any]:
    requested = {str(k or "").strip().lower() for k in (cleanup_keys or []) if str(k or "").strip()}
    by_key = {
        str(r.get("key") or "").strip().lower(): str(r.get("mount_path") or "").strip()
        for r in (previous_rows or [])
        if str(r.get("key") or "").strip()
    }
    result: Dict[str, Any] = {
        "requested": sorted(requested),
        "removed": [],
        "skipped": [],
        "errors": [],
    }
    for key in sorted(requested):
        mount_path = by_key.get(key, "")
        if not mount_path:
            result["skipped"].append({"key": key, "reason": "mount_path_unbekannt"})
            continue
        p = Path(mount_path)
        if not p.exists():
            result["skipped"].append({"key": key, "path": mount_path, "reason": "pfad_existiert_nicht"})
            continue
        if not p.is_dir():
            result["skipped"].append({"key": key, "path": mount_path, "reason": "kein_verzeichnis"})
            continue
        try:
            proc = subprocess.run(
                ["findmnt", "-T", mount_path, "-n", "-o", "FSTYPE"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            fs = (proc.stdout or "").strip().lower()
            if proc.returncode == 0 and fs in {"cifs", "smb3", "smbfs"}:
                result["skipped"].append({"key": key, "path": mount_path, "reason": "noch_gemountet"})
                continue
        except Exception:
            pass
        try:
            p.rmdir()
            result["removed"].append({"key": key, "path": mount_path})
        except OSError as exc:
            result["skipped"].append({"key": key, "path": mount_path, "reason": f"nicht_leer_oder_blockiert: {exc}"})
        except Exception as exc:
            result["errors"].append({"key": key, "path": mount_path, "reason": str(exc)})
    return result


def cleanup_removed_smb_secrets(
    previous_rows: List[Dict[str, str]],
    cleanup_keys: List[str],
) -> Dict[str, Any]:
    requested = {str(k or "").strip().lower() for k in (cleanup_keys or []) if str(k or "").strip()}
    by_key: Dict[str, str] = {}
    for r in (previous_rows or []):
        key = str(r.get("key") or "").strip().lower()
        if not key:
            continue
        pf = str(r.get("password_file") or "").strip()
        by_key[key] = pf or str(_smb_secret_path(key))

    result: Dict[str, Any] = {
        "requested": sorted(requested),
        "removed": [],
        "skipped": [],
        "errors": [],
    }
    for key in sorted(requested):
        path = by_key.get(key, "")
        if not path:
            result["skipped"].append({"key": key, "reason": "secret_path_unbekannt"})
            continue
        p = Path(path)
        if not p.exists():
            result["skipped"].append({"key": key, "path": path, "reason": "datei_existiert_nicht"})
            continue
        if not p.is_file():
            result["skipped"].append({"key": key, "path": path, "reason": "kein_file"})
            continue
        try:
            p.unlink()
            result["removed"].append({"key": key, "path": path})
        except Exception as exc:
            result["errors"].append({"key": key, "path": path, "reason": str(exc)})
    return result


def test_smb_profiles_status(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for row in normalize_smb_profile_rows(profiles):
        name = row["name"]
        mount_path = row["mount_path"]
        server = row["server"]
        share = row["share"]
        username = row["username"]
        password_file = row["password_file"]
        smb_password = str(row.get("smb_password", "")).strip()
        key = row["key"]
        item = {
            "key": key,
            "name": name,
            "mount_path": mount_path,
            "username": username,
            "password_file": password_file,
            "ok": False,
            "credentials_ok": False,
            "exists": False,
            "is_dir": False,
            "is_mounted": False,
            "message": "",
            "failure_code": "",
            "failure_hint": "",
            "technical_details": "",
            "checks": {
                "port_ok": False,
                "port_msg": "",
                "auth_ok": False,
                "auth_msg": "",
                "share_ok": False,
                "share_msg": "",
                "mount_ok": False,
                "mount_msg": "",
                "write_ok": False,
                "write_msg": "",
                "unmount_ok": False,
                "unmount_msg": "",
            },
        }
        if smb_password:
            item["credentials_ok"] = True
            item["checks"]["auth_ok"] = True
            item["checks"]["auth_msg"] = "Password supplied through UI"
        else:
            pf = Path(password_file)
            if not pf.exists() or not pf.is_file():
                item["message"] = "Password file not found"
                item["checks"]["auth_msg"] = "Password file not found"
                results.append(item)
                continue
            try:
                content = pf.read_text(encoding="utf-8", errors="replace")
            except Exception:
                item["message"] = "Password file is not readable"
                item["checks"]["auth_msg"] = "Password file is not readable"
                results.append(item)
                continue
            low = content.lower()
            has_user = f"username={username}".lower() in low
            has_pass = "password=" in low
            if not (has_user and has_pass):
                item["message"] = "Password file is incomplete (username/password)"
                item["checks"]["auth_msg"] = "Credentials file is incomplete"
                results.append(item)
                continue
            item["credentials_ok"] = True
            item["checks"]["auth_ok"] = True
            item["checks"]["auth_msg"] = "Credentials file is complete"

        try:
            import socket
            with socket.create_connection((server, 445), timeout=3):
                pass
            item["checks"]["port_ok"] = True
            item["checks"]["port_msg"] = "TCP 445 reachable"
        except Exception as exc:
            item["checks"]["port_msg"] = f"TCP 445 unreachable: {exc}"

        p = Path(mount_path)
        if not p.exists():
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        item["exists"] = p.exists()
        item["is_dir"] = p.is_dir()
        if not item["exists"]:
            item["message"] = "Mount path not found"
            item["checks"]["share_msg"] = "cannot be checked"
            results.append(item)
            continue
        if not item["is_dir"]:
            item["message"] = "Mount path is not a directory"
            item["checks"]["share_msg"] = "cannot be checked"
            results.append(item)
            continue
        mounted = False
        try:
            proc = subprocess.run(
                ["findmnt", "-T", mount_path, "-n", "-o", "FSTYPE"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            fs_type = (proc.stdout or "").strip().lower()
            mounted = proc.returncode == 0 and fs_type in {"cifs", "smb3", "smbfs"}
        except Exception:
            mounted = False
        item["is_mounted"] = mounted

        temp_cred_file: Optional[Path] = None
        test_mounted = False
        if not mounted:
            cred_path = Path(password_file)
            if smb_password:
                temp_cred_file = Path(f"/tmp/.bbui-smb-test-{key}.cred")
                temp_cred_file.write_text(
                    f"username={username}\npassword={smb_password}\n",
                    encoding="utf-8",
                )
                temp_cred_file.chmod(0o600)
                cred_path = temp_cred_file

            opts = build_smb_mount_options(row, cred_path)
            cmd = ["mount", "-t", "cifs", f"//{server}/{share}", mount_path, "-o", ",".join(opts)]
            mnt = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
            if mnt.returncode != 0:
                technical = sanitize_smb_error(mnt.stderr or mnt.stdout or "mount failed")
                failure_code, failure_hint = classify_smb_mount_error(technical)
                item["failure_code"] = failure_code
                item["failure_hint"] = failure_hint
                item["technical_details"] = technical
                item["message"] = failure_hint
                item["checks"]["mount_msg"] = item["message"]
                if temp_cred_file and temp_cred_file.exists():
                    temp_cred_file.unlink(missing_ok=True)
                results.append(item)
                continue
            mounted = True
            test_mounted = True
            item["is_mounted"] = True
            item["checks"]["mount_ok"] = True
            protocol = normalize_smb_version(row.get("vers"))
            item["checks"]["mount_msg"] = f"Test mount succeeded (protocol: {protocol})"
        else:
            item["checks"]["mount_ok"] = True
            item["checks"]["mount_msg"] = "Already mounted"
        try:
            mount_lines = Path("/proc/mounts").read_text(encoding="utf-8", errors="ignore").splitlines()
            src_expected = f"//{server}/{share}".lower()
            hit = False
            for line in mount_lines:
                cols = line.split()
                if len(cols) < 3:
                    continue
                src = cols[0].lower()
                tgt = cols[1].rstrip("/")
                if tgt == mount_path.rstrip("/") and src == src_expected:
                    hit = True
                    break
            if not hit:
                item["message"] = "Mounted, but source does not match profile"
                item["checks"]["share_msg"] = "Source does not match profile"
                results.append(item)
                continue
            item["checks"]["share_ok"] = True
            item["checks"]["share_msg"] = "Share source matches"
        except Exception:
            pass
        probe = Path(mount_path) / ".bbui-smb-write-test"
        try:
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as exc:
            item["message"] = f"SMB mounted, but write test failed: {exc}"
            item["checks"]["write_msg"] = str(exc)
            if test_mounted:
                um = subprocess.run(["umount", mount_path], capture_output=True, text=True, timeout=12, check=False)
                item["checks"]["unmount_ok"] = um.returncode == 0
                item["checks"]["unmount_msg"] = "Unmount OK" if um.returncode == 0 else (um.stderr or um.stdout or "Unmount failed").strip()
            if temp_cred_file and temp_cred_file.exists():
                temp_cred_file.unlink(missing_ok=True)
            results.append(item)
            continue
        item["checks"]["write_ok"] = True
        item["checks"]["write_msg"] = "Write test succeeded"

        if test_mounted:
            um = subprocess.run(["umount", mount_path], capture_output=True, text=True, timeout=12, check=False)
            item["checks"]["unmount_ok"] = um.returncode == 0
            item["checks"]["unmount_msg"] = "Unmount OK" if um.returncode == 0 else (um.stderr or um.stdout or "Unmount failed").strip()
            item["is_mounted"] = False
            item["message"] = "OK (test mount succeeded and was unmounted)"
        else:
            item["checks"]["unmount_ok"] = True
            item["checks"]["unmount_msg"] = "Not required (already mounted)"
            item["message"] = "OK (already mounted)"

        if temp_cred_file and temp_cred_file.exists():
            temp_cred_file.unlink(missing_ok=True)
        item["ok"] = True
        results.append(item)
    return {"results": results}
