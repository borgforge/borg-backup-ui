"""
api/auth_store.py - Auth-, User- und Session-Store-Helfer.

Dieses Modul kapselt persistente Auth-Dateien, Passwort-Hashing und kleine
Normalisierungshelfer. HTTP-spezifisches Verhalten bleibt in borg_backup_ui.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path


def data_root(config: dict) -> Path:
    return Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")


def api_token_file(config: dict) -> Path:
    return data_root(config) / "config" / ".api-token"


def load_or_create_api_token(config: dict) -> str:
    token_file = api_token_file(config)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    if token_file.exists():
        try:
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                return token
        except OSError:
            pass
    token = secrets.token_hex(32)
    token_file.write_text(f"{token}\n", encoding="utf-8")
    try:
        os.chmod(token_file, 0o600)
    except OSError:
        pass
    return token


def parse_cookie_header(raw_cookie: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in str(raw_cookie or "").split(";"):
        chunk = part.strip()
        if not chunk or "=" not in chunk:
            continue
        key, val = chunk.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def users_file(config: dict) -> Path:
    return data_root(config) / "config" / "users.json"


def sessions_file(config: dict) -> Path:
    return data_root(config) / "config" / "sessions.json"


def default_users_store() -> dict:
    return {
        "schema_version": 1,
        "users": [],
        "security": {
            "session_timeout_minutes": 30,
            "password_policy": {"min_length": 12},
        },
    }


def default_sessions_store() -> dict:
    return {
        "schema_version": 1,
        "sessions": [],
    }


def read_users_store(config: dict) -> dict:
    fp = users_file(config)
    if not fp.exists():
        return default_users_store()
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default_users_store()
        raw.setdefault("schema_version", 1)
        raw.setdefault("users", [])
        raw.setdefault("security", {})
        return raw
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default_users_store()


def write_users_store(config: dict, data: dict) -> None:
    fp = users_file(config)
    fp.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, fp)
    try:
        os.chmod(fp, 0o600)
    except OSError:
        pass


def read_sessions_store(config: dict) -> dict:
    fp = sessions_file(config)
    if not fp.exists():
        return default_sessions_store()
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default_sessions_store()
        raw.setdefault("schema_version", 1)
        raw.setdefault("sessions", [])
        if not isinstance(raw["sessions"], list):
            raw["sessions"] = []
        return raw
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default_sessions_store()


def write_sessions_store(config: dict, data: dict) -> None:
    fp = sessions_file(config)
    fp.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, fp)
    try:
        os.chmod(fp, 0o600)
    except OSError:
        pass


def normalize_username(name: str) -> str:
    return str(name or "").strip().lower()


def has_active_admin(config: dict) -> bool:
    store = read_users_store(config)
    for u in store.get("users", []):
        if not isinstance(u, dict):
            continue
        if not bool(u.get("enabled", True)):
            continue
        if str(u.get("role", "")).strip().lower() == "admin":
            return True
    return False


def has_any_users(config: dict) -> bool:
    store = read_users_store(config)
    users = store.get("users", [])
    return isinstance(users, list) and len(users) > 0


def hash_password(password: str, *, salt: str | None = None, iterations: int = 200000) -> str:
    s = salt or secrets.token_hex(16)
    it = max(10000, int(iterations or 200000))
    dk = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), s.encode("utf-8"), it)
    return f"pbkdf2_sha256${it}${s}${dk.hex()}"


def verify_password_hash(password: str, encoded: str) -> bool:
    raw = str(encoded or "")
    parts = raw.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    _, it_str, salt, _hash_hex = parts
    try:
        it = max(10000, int(it_str))
    except ValueError:
        return False
    probe = hash_password(password, salt=salt, iterations=it)
    return secrets.compare_digest(probe, raw)


def safe_user_view(u: dict) -> dict:
    return {
        "id": str(u.get("id", "")).strip(),
        "username": str(u.get("username", "")).strip(),
        "role": str(u.get("role", "")).strip().lower(),
        "enabled": bool(u.get("enabled", True)),
        "created_at": str(u.get("created_at", "")).strip(),
        "updated_at": str(u.get("updated_at", "")).strip(),
        "last_login_at": str(u.get("last_login_at", "")).strip(),
    }


def load_ui_auth_config(config: dict) -> dict:
    timeout_default = 30
    try:
        from config_api import read_expanded_conf
        conf = read_expanded_conf(config)
        timeout_default = int(str(conf.get("UI_SESSION_TIMEOUT_MINUTES", "30")).strip() or "30")
    except (ImportError, OSError, ValueError, TypeError, AttributeError):
        timeout_default = int(str(config.get("UI_SESSION_TIMEOUT_MINUTES", "30")).strip() or "30")

    return {
        "enabled": True,
        "password_hash": "",
        "salt": "",
        "iterations": 200000,
        "session_timeout_minutes": max(5, timeout_default),
    }
