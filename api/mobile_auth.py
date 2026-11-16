"""Bounded, browser-approved device sessions (#738).

Only SHA-256 credential digests are persisted. A fixed twelve-hour lifetime
requires explicit re-pairing; there is no refresh credential or password login.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

from auth_store import data_root, normalize_username, read_users_store

LOCK = threading.RLock()
PAIR_TTL = 600
SESSION_TTL = 12 * 60 * 60
SCOPE = "monitor:read"


class MobileError(ValueError):
    """Safe API error with an explicit HTTP status; never includes credentials."""

    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.api_code = code
        self.api_status = status


def digest(value: str) -> str:
    """Hash an opaque high-entropy credential or a bounded verification code."""
    return hashlib.sha256(value.encode()).hexdigest()


def _user(config: dict, name: str) -> dict:
    for user in read_users_store(config)["users"]:
        if (normalize_username(user.get("username")) == name
                and user.get("enabled", True)
                and user.get("role") in {"viewer", "operator", "admin"}):
            return user
    raise MobileError("mobile_unauthorized", 401)


def _fingerprint(user: dict) -> str:
    return digest(str(user.get("password_hash")) + ":" + str(user.get("role")))


def _path(config: dict) -> Path:
    return data_root(config) / "config" / "mobile-sessions.json"


def _load(config: dict) -> dict:
    fp = _path(config)
    if not fp.exists():
        return {"schema_version": 1, "pending": [], "sessions": [], "limits": {}}
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if (data["schema_version"] != 1 or not isinstance(data["limits"], dict)
                or any(not isinstance(data[k], list) for k in ("pending", "sessions"))):
            raise ValueError()
        now = time.time()
        for key in ("pending", "sessions"):
            data[key] = [row for row in data[key] if row["expires_at"] > now]
        data["limits"] = {k: [v for v in values if v > now - 3600]
                          for k, values in data["limits"].items() if values and max(values) > now - 3600}
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MobileError("mobile_store_unavailable", 503) from exc


def _save(config: dict, data: dict) -> None:
    fp = _path(config)
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_name(".mobile-" + secrets.token_hex(12) + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, fp)
    except OSError as exc:
        raise MobileError("mobile_store_unavailable", 503) from exc
    finally:
        tmp.unlink(missing_ok=True)


def _limit(config: dict, data: dict, key: str, maximum: int) -> None:
    key = digest(key)
    attempts = data["limits"].setdefault(key, [])
    if len(attempts) >= maximum or len(data["limits"]) > 1024:
        raise MobileError("mobile_rate_limited", 429)
    attempts.append(time.time())
    _save(config, data)


def begin(config: dict, label: object, client_ip: str) -> dict:
    """Create a ten-minute pairing; rate/bounds limit anonymous resource use."""
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80 or any(ord(c) < 32 for c in label):
        raise MobileError("mobile_bad_request", 400)
    with LOCK:
        data = _load(config)
        _limit(config, data, "begin:" + client_ip, 10)
        if len(data["pending"]) >= 100 or len(data["sessions"]) >= 500:
            raise MobileError("mobile_rate_limited", 429)
        device_code = secrets.token_urlsafe(32)
        user_code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
        data["pending"].append({"device_hash": digest(device_code), "code_hash": digest(user_code),
                                "label": label.strip(), "expires_at": time.time() + PAIR_TTL})
        _save(config, data)
        return {"device_code": device_code, "user_code": user_code, "expires_in": PAIR_TTL,
                "scope": SCOPE, "session_expires_in": SESSION_TTL}


def approve(config: dict, username: str, code: object, allow_job_control: bool = False) -> dict:
    """Bind a code to the current enabled browser user; approval is one-use."""
    with LOCK:
        data = _load(config)
        _limit(config, data, "approve:" + username, 30)
        user = _user(config, username)
        if type(allow_job_control) is not bool:
            raise MobileError("mobile_bad_request", 400)
        if allow_job_control and user.get("role") not in {"operator", "admin"}:
            raise MobileError("mobile_forbidden", 403)
        if not isinstance(code, str) or len(code) > 32:
            raise MobileError("mobile_bad_request", 400)
        hashed = digest(code.upper().replace("-", "").replace(" ", ""))
        pending = next((p for p in data["pending"] if secrets.compare_digest(p["code_hash"], hashed)), None)
        if not pending or pending.get("username"):
            raise MobileError("mobile_invalid_code", 400)
        pending.update(username=username, fingerprint=_fingerprint(user), job_control=allow_job_control)
        _save(config, data)
        return {"approved": True, "device_name": pending["label"], "scope": SCOPE}


def exchange(config: dict, device_code: object) -> dict:
    """Consume an approved pairing and return its bearer once; retries re-pair."""
    if not isinstance(device_code, str) or not 32 <= len(device_code) <= 128:
        raise MobileError("mobile_unauthorized", 401)
    with LOCK:
        data = _load(config)
        hashed = digest(device_code)
        pending = next((p for p in data["pending"] if secrets.compare_digest(p["device_hash"], hashed)), None)
        if not pending:
            raise MobileError("mobile_unauthorized", 401)
        if not pending.get("username"):
            return {"status": "pending"}
        user = _user(config, pending["username"])
        if _fingerprint(user) != pending["fingerprint"]:
            raise MobileError("mobile_unauthorized", 401)
        token = "bfm_" + secrets.token_urlsafe(32)
        session = {"id": secrets.token_hex(16), "token_hash": digest(token),
                   "username": pending["username"], "fingerprint": pending["fingerprint"],
                   "label": pending["label"], "job_control": pending.get("job_control", False), "created_at": time.time(),
                   "expires_at": time.time() + SESSION_TTL}
        data["pending"].remove(pending)
        data["sessions"].append(session)
        _save(config, data)
        return {"status": "authorized", "access_token": token, "session_id": session["id"],
                "expires_at": session["expires_at"], "scope": SCOPE}


def authenticate(config: dict, token: str) -> dict:
    """Validate bearer and current user on every request, without extending TTL."""
    if not token.startswith("bfm_") or len(token) > 128:
        raise MobileError("mobile_unauthorized", 401)
    with LOCK:
        data = _load(config)
        hashed = digest(token)
        session = next((s for s in data["sessions"] if secrets.compare_digest(s["token_hash"], hashed)), None)
        if not session or _fingerprint(_user(config, session["username"])) != session["fingerprint"]:
            raise MobileError("mobile_unauthorized", 401)
        return dict(session)


def sessions(config: dict, username: str) -> dict:
    """List only the caller's device metadata, never credential digests."""
    with LOCK:
        data = _load(config)
        return {"can_approve_job_control": _user(config, username).get("role") in {"operator", "admin"},
                "sessions": [dict({k: s[k] for k in ("id", "label", "created_at", "expires_at")},
                                  job_control=s.get("job_control", False))
                             for s in data["sessions"] if s["username"] == username]}


def revoke(config: dict, username: str, session_id: object) -> dict:
    """Idempotently revoke an owned session; foreign IDs confer no authority."""
    with LOCK:
        data = _load(config)
        data["sessions"] = [s for s in data["sessions"]
                            if not (s["username"] == username and s["id"] == session_id)]
        _save(config, data)
        return {"revoked": True}


def revoke_users(config: dict, usernames: set[str] | None = None) -> None:
    """Revoke device sessions and approvals for changed users (None means all).

    Existing corrupt device stores fail closed. An absent store is not created.
    """
    if not _path(config).exists():
        return
    with LOCK:
        data = _load(config)
        for key in ("pending", "sessions"):
            data[key] = [row for row in data[key]
                         if usernames is not None and row.get("username") not in usernames]
        _save(config, data)


def revoke_changed_users(config: dict, before: dict, after: dict) -> None:
    """Invalidate devices before an account deletion/security change is saved."""
    def security_fields(user):
        return (user.get("password_hash"), user.get("role"), user.get("enabled", True))
    current = {normalize_username(u.get("username")): security_fields(u) for u in after.get("users", [])}
    changed = {normalize_username(u.get("username")) for u in before.get("users", [])
               if current.get(normalize_username(u.get("username"))) != security_fields(u)}
    if changed:
        revoke_users(config, changed)


def can_control(config: dict, session: dict) -> bool:
    """Require explicit device consent and a currently enabled operator/admin."""
    return (session.get("job_control") is True
            and _user(config, session["username"]).get("role") in {"operator", "admin"})


def command(config: dict, session: dict, request_id: str, payload: dict, execute) -> dict:
    """Reserve a bounded operation ID durably before invoking a job action once.

    Replays return the recorded result; a crash/exception leaves an uncertain
    reservation (409), never an automatic second launch. Entries expire with
    the session. Revoked or changed users cannot replay successful commands.
    """
    import re
    if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise MobileError("mobile_bad_request", 400)
    with LOCK:
        data = _load(config)
        current = next((s for s in data["sessions"] if s["id"] == session["id"]), None)
        if not current or _fingerprint(_user(config, current["username"])) != current["fingerprint"]:
            raise MobileError("mobile_unauthorized", 401)
        if not can_control(config, current):
            raise MobileError("mobile_forbidden", 403)
        commands = current.setdefault("commands", {})
        previous = commands.get(request_id)
        if previous:
            if previous["payload"] != payload or "result" not in previous:
                raise MobileError("mobile_command_uncertain", 409)
            return previous["result"]
        if len(commands) >= 100:
            raise MobileError("mobile_rate_limited", 429)
        commands[request_id] = {"payload": payload}
        _save(config, data)
        # Serializing launch admission prevents two concurrent mobile requests
        # passing the existing runtime check before either process is recorded.
        result = execute()
        commands[request_id]["result"] = result
        _save(config, data)
        return result
