"""Local administrator access recovery helpers.

This module is used by the Unraid plugin control page. It intentionally avoids
HTTP session state so access can be restored even when Borg Backup UI itself is
not reachable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from auth_store import (
        data_root,
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
        data_root,
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
RECOVERY_TOKEN_TTL_SECONDS = 10 * 60


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


def recovery_tokens_file(config: dict[str, Any]) -> Path:
    return data_root(config) / "config" / "admin-recovery-tokens.json"


def _read_recovery_tokens(config: dict[str, Any]) -> dict[str, Any]:
    fp = recovery_tokens_file(config)
    if not fp.exists():
        return {"schema_version": 1, "tokens": []}
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"Admin recovery token store is unreadable or invalid: {fp}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Admin recovery token store has an invalid structure: {fp}")
    tokens = raw.get("tokens", [])
    if not isinstance(tokens, list):
        tokens = []
    raw.setdefault("schema_version", 1)
    raw["tokens"] = [t for t in tokens if isinstance(t, dict)]
    return raw


def _write_recovery_tokens(config: dict[str, Any], store: dict[str, Any]) -> None:
    fp = recovery_tokens_file(config)
    fp.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp = fp.with_name(f".{fp.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp, fp)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    try:
        os.chmod(fp, 0o600)
    except OSError:
        pass


def _hash_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _assert_existing_admin(config: dict[str, Any], username: str) -> str:
    normalized = normalize_username(username)
    if not normalized:
        raise ValueError("Admin username is required")
    if not USERNAME_RE.fullmatch(normalized):
        raise ValueError("Username is invalid (3-64 characters: a-z, 0-9, ., _, -)")
    for admin in list_admin_users(config):
        if normalize_username(admin.get("username", "")) == normalized:
            return normalized
    raise ValueError("Admin user was not found")


def create_admin_recovery_token(
    config: dict[str, Any],
    username: str,
    *,
    ttl_seconds: int = RECOVERY_TOKEN_TTL_SECONDS,
) -> dict[str, Any]:
    """Create a one-time recovery token for an existing admin account."""
    normalized = _assert_existing_admin(config, username)
    now = int(time.time())
    ttl = max(60, min(3600, int(ttl_seconds or RECOVERY_TOKEN_TTL_SECONDS)))
    expires_at = now + ttl
    token = secrets.token_urlsafe(32)
    store = _read_recovery_tokens(config)
    tokens = [
        t for t in store.get("tokens", [])
        if isinstance(t, dict) and int(t.get("expires_at", 0) or 0) > now and str(t.get("username", "")) != normalized
    ]
    tokens.append({
        "token_hash": _hash_token(token),
        "username": normalized,
        "created_at": now,
        "expires_at": expires_at,
    })
    store["schema_version"] = 1
    store["tokens"] = tokens[-10:]
    _write_recovery_tokens(config, store)
    return {
        "ok": True,
        "token": token,
        "username": normalized,
        "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ttl_seconds": ttl,
    }


def describe_admin_recovery_token(config: dict[str, Any], token: str) -> dict[str, Any]:
    """Return non-secret display information for a valid recovery token."""
    clean_token = str(token or "").strip()
    if len(clean_token) < 24:
        return {"valid": False, "username": "", "expires_at": ""}
    store = _read_recovery_tokens(config)
    now = int(time.time())
    token_hash = _hash_token(clean_token)
    for item in store.get("tokens", []):
        if not isinstance(item, dict):
            continue
        expires_at = int(item.get("expires_at", 0) or 0)
        if expires_at <= now:
            continue
        if not secrets.compare_digest(str(item.get("token_hash", "")), token_hash):
            continue
        return {
            "valid": True,
            "username": normalize_username(item.get("username", "")),
            "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    return {"valid": False, "username": "", "expires_at": ""}


def recover_admin_access_with_token(config: dict[str, Any], token: str, password: str) -> dict[str, Any]:
    """Consume a one-time token and reset the linked admin password."""
    clean_token = str(token or "").strip()
    if len(clean_token) < 24:
        raise ValueError("Admin recovery link is invalid or expired")
    if len(str(password or "")) < 12:
        raise ValueError("Password must contain at least 12 characters")

    store = _read_recovery_tokens(config)
    now = int(time.time())
    token_hash = _hash_token(clean_token)
    match: dict[str, Any] | None = None
    remaining: list[dict[str, Any]] = []
    for item in store.get("tokens", []):
        if not isinstance(item, dict):
            continue
        expires_at = int(item.get("expires_at", 0) or 0)
        if expires_at <= now:
            continue
        if secrets.compare_digest(str(item.get("token_hash", "")), token_hash):
            match = item
            continue
        remaining.append(item)
    if match is None:
        store["tokens"] = remaining
        _write_recovery_tokens(config, store)
        raise ValueError("Admin recovery link is invalid or expired")

    username = normalize_username(match.get("username", ""))
    store["tokens"] = remaining
    _write_recovery_tokens(config, store)
    result = recover_admin_access(config, username, password)
    result["token_consumed"] = True
    return result


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
    if len(str(password or "")) < 12:
        raise ValueError("Password must contain at least 12 characters")
    normalized = _assert_existing_admin(config, username)

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


def _run_create_token() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        result = create_admin_recovery_token(
            _load_control_config_from_env(),
            str(payload.get("username") or ""),
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recover Borg Backup UI admin access")
    parser.add_argument("--control-page", action="store_true", help="read recovery data as JSON from stdin")
    parser.add_argument("--create-token", action="store_true", help="create a one-time recovery token from JSON stdin")
    parser.add_argument("--list-admins", action="store_true", help="list existing admin accounts as JSON")
    args = parser.parse_args(argv)
    if args.list_admins:
        return _run_list_admins()
    if args.create_token:
        return _run_create_token()
    if args.control_page:
        return _run_control_page_reset()
    parser.error("--control-page, --create-token, or --list-admins is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
