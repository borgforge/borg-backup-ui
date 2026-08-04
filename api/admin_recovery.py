"""Local administrator access recovery helpers.

This module is used by the Unraid plugin control page. It intentionally avoids
HTTP session state so access can be restored even when Borg Backup UI itself is
not reachable.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from auth_store import (
        default_sessions_store,
        default_users_store,
        hash_password,
        normalize_username,
        read_users_store,
        sessions_file,
        users_file,
        write_sessions_store,
        write_users_store,
    )
except ImportError:  # pragma: no cover - package import path
    from .auth_store import (
        default_sessions_store,
        default_users_store,
        hash_password,
        normalize_username,
        read_users_store,
        sessions_file,
        users_file,
        write_sessions_store,
        write_users_store,
    )


USERNAME_RE = re.compile(r"[a-z0-9._-]{3,64}")
DEFAULT_PLUGIN_DIR = Path("/boot/config/plugins/borg-backup-ui")
DEFAULT_DATA_ROOT = Path("/boot/config/borg-backup")


def load_control_page_config(plugin_dir: Path = DEFAULT_PLUGIN_DIR) -> dict[str, str]:
    """Load the minimal UI config needed to locate the auth store."""
    config = {
        "BACKUP_SCRIPTS_DIR": str(DEFAULT_DATA_ROOT),
        "BORG_SCRIPTS_DIR": str(plugin_dir / "runtime" / "scripts"),
    }
    conf_file = plugin_dir / "borg_backup_ui.conf"
    if conf_file.exists():
        for raw in conf_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key in {"BACKUP_SCRIPTS_DIR", "BORG_SCRIPTS_DIR"}:
                config[key] = value.strip().strip('"').strip("'")
    for key in list(config):
        if key in os.environ:
            config[key] = os.environ[key]
    return config


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _backup_users_file(config: dict[str, Any], now: str) -> Path | None:
    src = users_file(config)
    if not src.exists():
        return None
    backup_dir = src.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    dst = backup_dir / f"users.json.admin-recovery-{stamp}.bak"
    shutil.copy2(src, dst)
    try:
        os.chmod(dst, 0o600)
    except OSError:
        pass
    return dst


def recover_admin_access(config: dict[str, Any], username: str, password: str) -> dict[str, Any]:
    """Reset or create an enabled admin account and invalidate all sessions."""
    normalized = normalize_username(username)
    if not normalized:
        normalized = "admin"
    if not USERNAME_RE.fullmatch(normalized):
        raise ValueError("Username is invalid (3-64 characters: a-z, 0-9, ., _, -)")
    if len(str(password or "")) < 12:
        raise ValueError("Password must contain at least 12 characters")

    now = _utc_now()
    backup_file = _backup_users_file(config, now)
    store = read_users_store(config)
    users = [u for u in store.get("users", []) if isinstance(u, dict)]

    action = "created"
    target = None
    for user in users:
        if normalize_username(user.get("username", "")) == normalized:
            target = user
            action = "reset"
            break

    if target is None:
        target = {
            "id": f"u_{os.urandom(8).hex()}",
            "username": normalized,
            "created_at": now,
            "last_login_at": "",
        }
        users.append(target)

    target["username"] = normalized
    target["password_hash"] = hash_password(password)
    target["role"] = "admin"
    target["enabled"] = True
    target["updated_at"] = now
    store.setdefault("schema_version", 1)
    store.setdefault("security", default_users_store()["security"])
    store["users"] = users

    write_users_store(config, store)
    write_sessions_store(config, default_sessions_store())

    return {
        "ok": True,
        "action": action,
        "username": normalized,
        "users_file": str(users_file(config)),
        "sessions_file": str(sessions_file(config)),
        "backup_file": str(backup_file) if backup_file else "",
    }


def _run_control_page() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        plugin_dir = Path(str(os.environ.get("BBUI_PLUGIN_DIR") or DEFAULT_PLUGIN_DIR))
        config = load_control_page_config(plugin_dir)
        result = recover_admin_access(
            config,
            str(payload.get("username") or "admin"),
            str(payload.get("password") or ""),
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recover Borg Backup UI admin access")
    parser.add_argument("--control-page", action="store_true", help="read recovery data as JSON from stdin")
    args = parser.parse_args(argv)
    if args.control_page:
        return _run_control_page()
    parser.error("--control-page is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
