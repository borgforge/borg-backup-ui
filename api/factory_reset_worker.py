#!/usr/bin/env python3
"""Detached one-shot worker for the guarded factory reset."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


_CRON_BLOCKS = {
    "# --- BORG-BACKUP-UI BEGIN ---": "# --- BORG-BACKUP-UI END ---",
    "# --- BORG-BACKUP-UI WEEKLY-REPORT BEGIN ---": "# --- BORG-BACKUP-UI WEEKLY-REPORT END ---",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _audit(path: Path, event: str, status: str, marker: dict, detail: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": _now(),
        "event": event,
        "status": status,
        "actor": str(marker.get("actor") or "admin"),
        "request_id": str(marker.get("request_id") or ""),
        "detail": str(detail or "")[:1000],
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)


def _safe_remove(path: Path, *, expected_config_root: bool = False, production: bool = True) -> None:
    resolved = path.resolve(strict=False)
    if expected_config_root:
        if production and resolved != Path("/boot/config/borg-backup"):
            raise ValueError("Unexpected Borg Backup configuration root")
    elif production and (
        not str(resolved).startswith("/mnt/") or len(resolved.parts) < 4
    ):
        raise ValueError("Operational data root must be a dedicated directory below /mnt/<storage>")
    if resolved in {
        Path("/"), Path("/mnt"), Path("/mnt/user"), Path("/mnt/cache"),
        Path("/mnt/disks"), Path("/mnt/remotes"), Path("/boot"), Path("/boot/config"),
    }:
        raise ValueError("Unsafe factory reset root")
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _default_data_root(example: Path, *, production: bool = True) -> Path:
    text = example.read_text(encoding="utf-8")
    match = re.search(r'^GLOBAL_DATA_DIR="([^"]+)"', text, re.MULTILINE)
    raw = match.group(1).strip() if match else "/mnt/user/borg-backup-ui"
    if production and not raw.startswith("/mnt/"):
        raise ValueError("Default operational data root is unsafe")
    return Path(raw)


def remove_plugin_cron_blocks() -> None:
    current = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True, timeout=10, check=False
    )
    if current.returncode not in (0, 1):
        detail = (current.stderr or current.stdout or "").strip() or f"exit {current.returncode}"
        raise RuntimeError(f"Could not read crontab: {detail}")
    lines = (current.stdout if current.returncode == 0 else "").splitlines()
    filtered: list[str] = []
    active_end = ""
    for line in lines:
        stripped = line.strip()
        if not active_end and stripped in _CRON_BLOCKS:
            active_end = _CRON_BLOCKS[stripped]
            continue
        if active_end:
            if stripped == active_end:
                active_end = ""
            continue
        filtered.append(line)
    if active_end:
        raise RuntimeError("Borg Backup UI crontab block is incomplete")
    payload = "\n".join(filtered).rstrip("\n")
    if payload:
        payload += "\n"
    updated = subprocess.run(
        ["crontab", "-"], input=payload, capture_output=True, text=True, timeout=10, check=False
    )
    if updated.returncode != 0:
        detail = (updated.stderr or updated.stdout or "").strip() or f"exit {updated.returncode}"
        raise RuntimeError(f"Could not update crontab: {detail}")


def perform_reset(marker: dict, *, production: bool = True) -> dict:
    root = Path(str(marker.get("configuration_root") or ""))
    old_data_raw = str(marker.get("operational_data_root") or "").strip()
    old_data = Path(old_data_raw) if old_data_raw else None
    plugin_dir = Path(str(marker.get("plugin_dir") or ""))
    example = plugin_dir / "runtime" / "config" / "backup.conf.example"
    if not example.is_file():
        raise FileNotFoundError("backup.conf.example is missing")

    controls = Path(str(marker.get("controls_root") or "/run/borg-backup-ui/jobs"))
    if production and controls != Path('/run/borg-backup-ui/jobs'):
        raise ValueError('Unexpected runtime control root')
    if controls in {Path('/'), Path('/run'), Path('/run/borg-backup-ui')}:
        raise ValueError('Unsafe runtime control root')
    _safe_remove(root, expected_config_root=True, production=production)
    if old_data is not None and old_data.resolve(strict=False) != root.resolve(strict=False):
        _safe_remove(old_data, production=production)

    if controls.is_symlink():
        controls.unlink()
    elif controls.exists():
        shutil.rmtree(controls)

    for directory in (root / "config" / "jobs", root / "secrets", root / "locks", root / "scripts"):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(example, root / "config" / "backup.conf")
    os.chmod(root / "config" / "backup.conf", 0o600)

    default_data = _default_data_root(example, production=production)
    for name in ("logs", "status", "restore-status", "cache", "remotes"):
        (default_data / name).mkdir(parents=True, exist_ok=True)
    return {
        "configuration_root": str(root),
        "deleted_operational_data_root": str(old_data or ""),
        "initialized_operational_data_root": str(default_data),
    }


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    marker_path = Path(sys.argv[1])
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    audit = Path(str(marker.get("audit_file") or ""))
    rc = str(marker.get("rc_script") or "/etc/rc.d/rc.borg_backup_ui")
    time.sleep(2)
    _audit(audit, "factory_reset_started", "started", marker)
    try:
        subprocess.run([rc, "stop"], timeout=30, check=False)
        remove_plugin_cron_blocks()
        result = perform_reset(marker)
        _audit(audit, "factory_reset_completed", "success", marker, json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        _audit(audit, "factory_reset_failed", "failed", marker, str(exc))
        subprocess.run([rc, "start"], timeout=30, check=False)
        return 1
    finally:
        marker_path.unlink(missing_ok=True)
    subprocess.run([rc, "start"], timeout=30, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
