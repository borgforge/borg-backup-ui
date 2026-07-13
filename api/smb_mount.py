"""Shared SMB mount helper for non-runner workflows (restore/check/browse)."""

from __future__ import annotations

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
    from repository_context import RepositoryContextError, resolve_job_repository_context

    try:
        context = resolve_job_repository_context(config, job_key, require_passphrase_file=False)
    except RepositoryContextError:
        return None
    if str(context.get("location") or "").strip().lower() != "smb":
        return None
    raw = context.get("job") if isinstance(context.get("job"), dict) else {}
    smb_key = str(context.get("profile_key") or "").strip()
    if not smb_key:
        return None
    return {
        "profile_key": smb_key,
        "storage": context.get("storage") if isinstance(context.get("storage"), dict) else {},
        "mount_before_run": bool(raw.get("mount_before_run", True)),
        "unmount_after_run": bool(raw.get("unmount_after_run", True)),
    }


def _validate_mount_option_value(val: str) -> str:
    raw = str(val or "").strip()
    if not raw:
        raise ValueError("Empty SMB option values are not allowed")
    if "," in raw:
        raise ValueError(f"Invalid SMB option value (commas are not allowed): {raw}")
    if "=" in raw:
        raise ValueError(f"Invalid SMB option value (= is not allowed): {raw}")
    if not re.fullmatch(r"[\w.:/+@-]+", raw):
        raise ValueError(f"Invalid SMB option value: {raw}")
    return raw


def ensure_smb_mount_for_job(config: dict, job_key: str) -> SmbMountGuard:
    guard = SmbMountGuard()
    meta = _job_smb_meta(config, job_key)
    if not meta:
        return guard

    if not bool(meta.get("mount_before_run", True)):
        return guard

    profile_key = str(meta.get("profile_key") or "").strip()
    profile = meta.get("storage") if isinstance(meta.get("storage"), dict) else {}

    server = str(profile.get("server", "")).strip()
    share = str(profile.get("share", "")).strip().lstrip("/")
    mount_path = str(profile.get("mount_path", "")).strip()
    username = str(profile.get("username", "")).strip()
    password_file = str(profile.get("password_file", "")).strip()
    if not server or not share or not mount_path or not username or not password_file:
        raise ValueError(f"SMB profile is incomplete: {profile_key}")

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
        msg = (res.stderr or res.stdout or "SMB mount failed").strip()
        raise RuntimeError(f"SMB mount failed ({src} -> {mount_path}): {msg}")

    guard.mounted_by_guard = True
    return guard
