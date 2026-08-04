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


def list_admin_users(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return existing administrator accounts for the control page selector."""
    store = read_users_store(config)
    admins: list[dict[str, Any]] = []
    for user in store.get("users", []):
        if not isinstance(user, dict):
            continue
        if str(user.get("role", "")).strip().lower() != "admin":
            continue
        username = normalize_username(user.get("username", ""))
        if not username:
            continue
        admins.append({
            "username": username,
            "enabled": bool(user.get("enabled", True)),
        })
    admins.sort(key=lambda item: item["username"])
    return admins


def recover_admin_access(config: dict[str, Any], username: str, password: str) -> dict[str, Any]:
    """Reset an existing admin account and invalidate all sessions."""
    normalized = normalize_username(username)
    if not normalized:
        raise ValueError("Admin username is required")
    if not USERNAME_RE.fullmatch(normalized):
        raise ValueError("Username is invalid (3-64 characters: a-z, 0-9, ., _, -)")
    if len(str(password or "")) < 12:
        raise ValueError("Password must contain at least 12 characters")

    now = _utc_now()
    backup_file = _backup_users_file(config, now)
    store = read_users_store(config)
    users = [u for u in store.get("users", []) if isinstance(u, dict)]

    target = None
    for user in users:
        if (
            normalize_username(user.get("username", "")) == normalized
            and str(user.get("role", "")).strip().lower() == "admin"
        ):
            target = user
            break

    if target is None:
        raise ValueError("Admin user was not found")

    target["username"] = normalized
    target["password_hash"] = hash_password(password)
    target["role"] = "admin"
    target["enabled"] = True
    target["updated_at"] = now
    store.setdefault("schema_version", 1)
    store["users"] = users

    write_users_store(config, store)
    write_sessions_store(config, default_sessions_store())

    return {
        "ok": True,
        "action": "reset",
        "username": normalized,
        "users_file": str(users_file(config)),
        "sessions_file": str(sessions_file(config)),
        "backup_file": str(backup_file) if backup_file else "",
    }


def _load_control_config_from_env() -> dict[str, str]:
    plugin_dir = Path(str(os.environ.get("BBUI_PLUGIN_DIR") or DEFAULT_PLUGIN_DIR))
    return load_control_page_config(plugin_dir)


def _run_list_admins() -> int:
    try:
        result = {"ok": True, "admins": list_admin_users(_load_control_config_from_env())}
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1


def _run_control_page_reset() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        result = recover_admin_access(
            _load_control_config_from_env(),
            str(payload.get("username") or ""),
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
    parser.add_argument("--list-admins", action="store_true", help="list existing admin accounts as JSON")
    args = parser.parse_args(argv)
    if args.list_admins:
        return _run_list_admins()
    if args.control_page:
        return _run_control_page_reset()
    parser.error("--control-page or --list-admins is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
