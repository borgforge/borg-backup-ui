"""Shared SMB mount helper for non-runner workflows (restore/check/browse)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional


class SmbMountGuard:
    def __init__(self) -> None:
        self.enabled = False
        self.mount_path = ""
        self.mounted_by_guard = False
        self.unmount_after_run = True

    def cleanup(self) -> None:
        if not self.enabled or not self.mounted_by_guard or not self.mount_path or not self.unmount_after_run:
            return
        try:
            subprocess.run(["umount", self.mount_path], capture_output=True, text=True, timeout=15, check=False)
        except Exception:
            pass


def _parse_smb_profiles(config: dict) -> dict[str, dict]:
    from config_api import read_settings_payload

    payload = read_settings_payload(config)
    rows = payload.get("smb_profiles") if isinstance(payload.get("smb_profiles"), list) else []
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key", "")).strip()
        if key:
            out[key] = row
    return out


def _is_smb_mounted(mount_path: str) -> bool:
    if not mount_path:
        return False
    try:
        proc = subprocess.run(
            ["findmnt", "-T", mount_path, "-n", "-o", "FSTYPE"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        fs = (proc.stdout or "").strip().lower()
        return proc.returncode == 0 and fs in {"cifs", "smb3", "smbfs"}
    except Exception:
        return False


def _job_smb_meta(config: dict, job_key: str) -> Optional[dict]:
    from jobs_api import get_jobs_meta_dirs, resolve_data_root, resolve_scripts_dir

    scripts_dir = resolve_scripts_dir(config)
    data_root = resolve_data_root(config)
    for meta_dir in get_jobs_meta_dirs(scripts_dir, data_root):
        p = meta_dir / f"{job_key}.json"
        if not p.exists():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        if str(raw.get("location") or "").strip().lower() != "smb":
            return None
        smb_key = str(raw.get("smb_profile_key") or "").strip()
        if not smb_key:
            return None
        return {
            "smb_profile_key": smb_key,
            "mount_before_run": bool(raw.get("mount_before_run", True)),
            "unmount_after_run": bool(raw.get("unmount_after_run", True)),
        }
    return None


def _validate_mount_option_value(val: str) -> str:
    raw = str(val or "").strip()
    if not raw:
        raise ValueError("Leerer SMB-Optionswert ist nicht erlaubt")
    if "," in raw:
        raise ValueError(f"Ungültiger SMB-Optionswert (Komma nicht erlaubt): {raw}")
    if "=" in raw:
        raise ValueError(f"Ungültiger SMB-Optionswert (= nicht erlaubt): {raw}")
    if not re.fullmatch(r"[\w.:/+@-]+", raw):
        raise ValueError(f"Ungültiger SMB-Optionswert: {raw}")
    return raw


def ensure_smb_mount_for_job(config: dict, job_key: str) -> SmbMountGuard:
    guard = SmbMountGuard()
    meta = _job_smb_meta(config, job_key)
    if not meta:
        return guard

    if not bool(meta.get("mount_before_run", True)):
        return guard

    profiles = _parse_smb_profiles(config)
    profile_key = str(meta.get("smb_profile_key") or "").strip()
    profile = profiles.get(profile_key)
    if not isinstance(profile, dict):
        raise ValueError(f"SMB-Profil nicht gefunden: {profile_key}")

    server = str(profile.get("server", "")).strip()
    share = str(profile.get("share", "")).strip().lstrip("/")
    mount_path = str(profile.get("mount_path", "")).strip()
    username = str(profile.get("username", "")).strip()
    password_file = str(profile.get("password_file", "")).strip()
    if not server or not share or not mount_path or not username or not password_file:
        raise ValueError(f"SMB-Profil unvollständig: {profile_key}")

    mp = Path(mount_path)
    mp.mkdir(parents=True, exist_ok=True)
    guard.enabled = True
    guard.mount_path = mount_path
    guard.unmount_after_run = bool(meta.get("unmount_after_run", True))

    if _is_smb_mounted(mount_path):
        return guard

    src = f"//{server}/{share}"
    opts = [f"credentials={password_file}", "iocharset=utf8"]
    vers = _validate_mount_option_value(str(profile.get("vers", "")).strip() or "3.0")
    opts.append(f"vers={vers}")
    sec = str(profile.get("sec", "")).strip()
    if sec:
        sec = _validate_mount_option_value(sec)
        opts.append(f"sec={sec}")
    uid = str(profile.get("uid", "")).strip()
    if uid:
        uid = _validate_mount_option_value(uid)
        opts.append(f"uid={uid}")
    gid = str(profile.get("gid", "")).strip()
    if gid:
        gid = _validate_mount_option_value(gid)
        opts.append(f"gid={gid}")
    file_mode = str(profile.get("file_mode", "")).strip()
    if file_mode:
        file_mode = _validate_mount_option_value(file_mode)
        opts.append(f"file_mode={file_mode}")
    dir_mode = str(profile.get("dir_mode", "")).strip()
    if dir_mode:
        dir_mode = _validate_mount_option_value(dir_mode)
        opts.append(f"dir_mode={dir_mode}")

    cmd = ["mount", "-t", "cifs", src, mount_path, "-o", ",".join(opts)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if res.returncode != 0:
        msg = (res.stderr or res.stdout or "SMB-Mount fehlgeschlagen").strip()
        raise RuntimeError(f"SMB-Mount fehlgeschlagen ({src} -> {mount_path}): {msg}")

    guard.mounted_by_guard = True
    return guard
