"""Shared SMB mount helper for non-runner workflows (restore/check/browse)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from smb_protocol import build_smb_mount_options, classify_smb_mount_error, sanitize_smb_error


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


def _job_smb_meta(config: dict, job_id: str) -> Optional[dict]:
    from repository_context import RepositoryContextError, resolve_job_repository_context

    try:
        context = resolve_job_repository_context(config, job_id, require_passphrase_file=False)
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


def ensure_smb_mount_for_job(config: dict, job_id: str) -> SmbMountGuard:
    guard = SmbMountGuard()
    meta = _job_smb_meta(config, job_id)
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
    opts = build_smb_mount_options(profile, password_file)

    cmd = ["mount", "-t", "cifs", src, mount_path, "-o", ",".join(opts)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if res.returncode != 0:
        technical = sanitize_smb_error(res.stderr or res.stdout or "SMB mount failed")
        _code, hint = classify_smb_mount_error(technical)
        raise RuntimeError(f"{hint} Technical details: {technical}")

    guard.mounted_by_guard = True
    return guard
