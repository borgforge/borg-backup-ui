"""
api/ntfy_api.py - ntfy notification settings and test delivery.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict


_RUNTIME_LIB = Path(__file__).resolve().parents[1] / "runtime" / "lib"
if str(_RUNTIME_LIB) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_LIB))

from notifications import NtfyConfig, send_ntfy_test  # type: ignore  # noqa: E402


def _secrets_dir() -> Path:
    p = Path("/boot/config/borg-backup/secrets")
    p.mkdir(parents=True, exist_ok=True)
    return p


def ntfy_secret_path(kind: str) -> Path:
    safe = "token" if str(kind or "").strip().lower() == "token" else "password"
    return _secrets_dir() / f".ntfy-{safe}"


def _write_secret(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(value or "").strip(), encoding="utf-8")
    path.chmod(0o600)


def prepare_ntfy_updates_for_save(updates: Dict[str, str], previous_conf: Dict[str, str]) -> Dict[str, str]:
    next_updates = dict(updates)

    if "NTFY_PASSWORD" in next_updates:
        incoming = str(next_updates.pop("NTFY_PASSWORD") or "").strip()
        if incoming:
            path = Path(str(previous_conf.get("NTFY_PASSWORD_FILE") or "").strip() or ntfy_secret_path("password"))
            _write_secret(path, incoming)
            next_updates["NTFY_PASSWORD_FILE"] = str(path)

    if "NTFY_ACCESS_TOKEN" in next_updates:
        incoming = str(next_updates.pop("NTFY_ACCESS_TOKEN") or "").strip()
        if incoming:
            path = Path(str(previous_conf.get("NTFY_ACCESS_TOKEN_FILE") or "").strip() or ntfy_secret_path("token"))
            _write_secret(path, incoming)
            next_updates["NTFY_ACCESS_TOKEN_FILE"] = str(path)

    return next_updates


def _config_from_payload(payload: dict, fallback: Dict[str, str]) -> NtfyConfig:
    data = dict(fallback)
    mapping = {
        "enabled": "NTFY_ENABLED",
        "profile_name": "NTFY_PROFILE_NAME",
        "server_url": "NTFY_SERVER_URL",
        "topic": "NTFY_TOPIC",
        "username": "NTFY_USERNAME",
        "priority": "NTFY_PRIORITY",
        "tags": "NTFY_TAGS",
        "click_url": "NTFY_CLICK_URL",
        "events": "NTFY_EVENTS",
    }
    for source, target in mapping.items():
        if source in payload:
            data[target] = str(payload.get(source) or "")
    if "password" in payload and str(payload.get("password") or "").strip():
        data["NTFY_PASSWORD_FILE"] = ""
        data["_NTFY_TEST_PASSWORD"] = str(payload.get("password") or "").strip()
    if "access_token" in payload and str(payload.get("access_token") or "").strip():
        data["NTFY_ACCESS_TOKEN_FILE"] = ""
        data["_NTFY_TEST_TOKEN"] = str(payload.get("access_token") or "").strip()

    cfg = NtfyConfig.from_config(data)
    if data.get("_NTFY_TEST_PASSWORD"):
        cfg.password = str(data["_NTFY_TEST_PASSWORD"])
    if data.get("_NTFY_TEST_TOKEN"):
        cfg.access_token = str(data["_NTFY_TEST_TOKEN"])
    cfg.enabled = True
    return cfg


def send_test_ntfy(ui_config: dict, payload: dict | None = None) -> dict:
    from config_api import read_expanded_conf

    body = payload if isinstance(payload, dict) else {}
    conf = read_expanded_conf(ui_config)
    ok, message = send_ntfy_test(_config_from_payload(body, conf))
    return {
        "success": bool(ok),
        "message": message,
        "message_code": "ntfy_test_sent" if ok else "ntfy_test_failed",
    }
