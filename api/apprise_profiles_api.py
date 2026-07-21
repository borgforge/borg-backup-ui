"""Canonical Apprise notification profile persistence and API helpers."""

from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_RUNTIME_LIB = Path(__file__).resolve().parents[1] / "runtime" / "lib"
if str(_RUNTIME_LIB) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_LIB))

from apprise_adapter import (  # type: ignore  # noqa: E402
    AppriseAdapterError,
    send_test_notification,
    supported_providers,
    validate_url,
)
from inventory_store import (  # type: ignore  # noqa: E402
    InventoryAccessError,
    InventoryCorruptError,
    atomic_write_bytes,
    atomic_write_inventory,
    inventory_lock,
    read_inventory,
)


SCHEMA_VERSION = 1
COLLECTION_KEY = "profiles"
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_.:+-]{0,63}$")
EVENT_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{1,63}$")
DEFAULT_EVENTS = [
    "backup_success",
    "backup_warning",
    "backup_failed",
    "backup_skipped",
    "restore_test_failed",
]
ACTIVE_REFERENCE_KEYS = {
    "APPRISE_PROFILE_ID",
    "APPRISE_DEFAULT_PROFILE_ID",
    "NOTIFY_APPRISE_PROFILE_ID",
}
ACTIVE_REFERENCE_LIST_KEYS = {
    "APPRISE_PROFILE_IDS",
    "NOTIFY_APPRISE_PROFILE_IDS",
}


class AppriseProfileConflict(RuntimeError):
    """Raised when a profile cannot be changed due to an active reference."""

    code = "apprise_profile_in_use"


def _data_root(config: dict[str, Any]) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR") or "/boot/config/borg-backup").strip()
    return Path(raw or "/boot/config/borg-backup")


def _config_dir(config: dict[str, Any]) -> Path:
    return _data_root(config) / "config"


def profile_store_path(config: dict[str, Any]) -> Path:
    return _config_dir(config) / "apprise-profiles.json"


def _secrets_dir(config: dict[str, Any]) -> Path:
    return _data_root(config) / "secrets"


def profile_secret_path(config: dict[str, Any], profile_id: str) -> Path:
    return _secrets_dir(config) / f".apprise-profile-{profile_id}.url"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_string(value: Any, *, max_len: int = 256) -> str:
    text = str(value or "").strip()
    if "\n" in text or "\r" in text:
        raise ValueError("Profile values must not contain line breaks")
    return text[:max_len]


def _profile_id(value: Any | None = None) -> str:
    text = _clean_string(value, max_len=64).lower() if value else f"apprise-{uuid.uuid4().hex[:12]}"
    if not PROFILE_ID_RE.fullmatch(text):
        raise ValueError("profile id must be 2-64 lowercase characters: a-z, 0-9, ., _, -")
    return text


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int_range(value: Any, *, default: int, minimum: int, maximum: int, label: str) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return parsed


def _events(value: Any) -> list[str]:
    if value is None:
        raw = DEFAULT_EVENTS
    elif isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, list):
        raw = value
    else:
        raise ValueError("selected_events must be a list")

    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        event = _clean_string(item, max_len=64).lower()
        if not event:
            continue
        if not EVENT_RE.fullmatch(event):
            raise ValueError(f"Invalid notification event: {event}")
        if event not in seen:
            seen.add(event)
            result.append(event)
    if not result:
        raise ValueError("selected_events must contain at least one event")
    return result


def _retry_policy(value: Any) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    return {
        "attempts": _int_range(source.get("attempts"), default=1, minimum=1, maximum=5, label="retry attempts"),
        "backoff_seconds": _int_range(
            source.get("backoff_seconds"),
            default=0,
            minimum=0,
            maximum=3600,
            label="retry backoff_seconds",
        ),
    }


def _provider(value: Any) -> str:
    text = _clean_string(value or "apprise", max_len=64).lower()
    if not PROVIDER_RE.fullmatch(text):
        raise ValueError("provider must use a-z, 0-9, ., _, :, + or -")
    return text


def _read_store(config: dict[str, Any]) -> dict[str, Any]:
    return read_inventory(profile_store_path(config), collection_key=COLLECTION_KEY, schema_version=SCHEMA_VERSION)


def _write_store(config: dict[str, Any], payload: dict[str, Any]) -> None:
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = _utc_now()
    atomic_write_inventory(profile_store_path(config), payload)


def _sanitize_profile(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    profile_id = _profile_id(row.get("id"))
    return {
        "id": profile_id,
        "name": _clean_string(row.get("name") or profile_id, max_len=80),
        "enabled": _bool(row.get("enabled"), True),
        "provider": _provider(row.get("provider")),
        "selected_events": _events(row.get("selected_events")),
        "timeout_seconds": _int_range(
            row.get("timeout_seconds"),
            default=15,
            minimum=1,
            maximum=300,
            label="timeout_seconds",
        ),
        "retry_policy": _retry_policy(row.get("retry_policy")),
        "priority": _clean_string(row.get("priority") or "", max_len=40),
        "default": _bool(row.get("default"), False),
        "created_at": _clean_string(row.get("created_at") or _utc_now(), max_len=40),
        "updated_at": _clean_string(row.get("updated_at") or _utc_now(), max_len=40),
        "url_set": profile_secret_path(config, profile_id).is_file(),
    }


def _public_profile(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    clean = _sanitize_profile(row, config)
    clean["url_set"] = profile_secret_path(config, clean["id"]).is_file()
    return clean


def _find_index(rows: list[dict[str, Any]], profile_id: str) -> int:
    for idx, row in enumerate(rows):
        if str(row.get("id") or "") == profile_id:
            return idx
    return -1


def _write_secret(config: dict[str, Any], profile_id: str, url: str) -> None:
    text = _clean_string(url, max_len=4096)
    if not text:
        raise ValueError("apprise_url is required")
    atomic_write_bytes(profile_secret_path(config, profile_id), (text + "\n").encode("utf-8"), mode=0o600)


def _read_secret(config: dict[str, Any], profile_id: str) -> str:
    path = profile_secret_path(config, profile_id)
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        raise InventoryAccessError(f"Apprise profile secret is not readable: {path.name}") from exc
    return ""


def list_profiles(config: dict[str, Any]) -> dict[str, Any]:
    try:
        with inventory_lock(_config_dir(config)):
            payload = _read_store(config)
            profiles = [_public_profile(row, config) for row in payload.get(COLLECTION_KEY, [])]
    except (InventoryCorruptError, InventoryAccessError):
        raise
    return {"schema_version": SCHEMA_VERSION, "profiles": profiles}


def get_profile(config: dict[str, Any], profile_id: str) -> dict[str, Any]:
    pid = _profile_id(profile_id)
    with inventory_lock(_config_dir(config)):
        payload = _read_store(config)
        rows = payload.get(COLLECTION_KEY, [])
        idx = _find_index(rows, pid)
        if idx < 0:
            raise FileNotFoundError("Apprise profile not found")
        return {"profile": _public_profile(rows[idx], config)}


def create_profile(config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    pid = _profile_id(payload.get("id"))
    url = _clean_string(payload.get("apprise_url") or payload.get("url"), max_len=4096)
    validation = validate_profile_url(url)
    if not validation["success"]:
        raise ValueError(validation["message"])

    now = _utc_now()
    row = _sanitize_profile({**payload, "id": pid, "created_at": now, "updated_at": now}, config)
    row.pop("url_set", None)
    with inventory_lock(_config_dir(config)):
        store = _read_store(config)
        rows = list(store.get(COLLECTION_KEY, []))
        if _find_index(rows, pid) >= 0:
            raise ValueError("Apprise profile already exists")
        if row.get("default"):
            for existing in rows:
                existing["default"] = False
        _write_secret(config, pid, url)
        rows.append(row)
        store[COLLECTION_KEY] = rows
        _write_store(config, store)
    return {"created": True, "profile": _public_profile(row, config)}


def update_profile(config: dict[str, Any], profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    pid = _profile_id(profile_id or payload.get("id"))
    new_url = payload.get("apprise_url", payload.get("url", None))
    if new_url is not None:
        validation = validate_profile_url(str(new_url or ""))
        if not validation["success"]:
            raise ValueError(validation["message"])

    with inventory_lock(_config_dir(config)):
        store = _read_store(config)
        rows = list(store.get(COLLECTION_KEY, []))
        idx = _find_index(rows, pid)
        if idx < 0:
            raise FileNotFoundError("Apprise profile not found")
        merged = {**rows[idx], **payload, "id": pid, "updated_at": _utc_now()}
        row = _sanitize_profile(merged, config)
        row.pop("url_set", None)
        if row.get("default"):
            for pos, existing in enumerate(rows):
                if pos != idx:
                    existing["default"] = False
        rows[idx] = row
        if new_url is not None:
            _write_secret(config, pid, str(new_url or ""))
        store[COLLECTION_KEY] = rows
        _write_store(config, store)
    return {"updated": True, "profile": _public_profile(row, config)}


def _parse_reference_list(value: Any) -> set[str]:
    if isinstance(value, list):
        raw = value
    else:
        text = str(value or "").strip()
        if not text:
            return set()
        try:
            decoded = json.loads(text)
            raw = decoded if isinstance(decoded, list) else text.split(",")
        except json.JSONDecodeError:
            raw = text.split(",")
    return {str(item or "").strip() for item in raw if str(item or "").strip()}


def active_profile_references(config: dict[str, Any]) -> set[str]:
    try:
        from config_api import read_expanded_conf

        conf = read_expanded_conf(config)
    except Exception:
        conf = {}
    refs: set[str] = set()
    for key in ACTIVE_REFERENCE_KEYS:
        value = str(conf.get(key) or "").strip()
        if value:
            refs.add(value)
    for key in ACTIVE_REFERENCE_LIST_KEYS:
        refs.update(_parse_reference_list(conf.get(key)))
    return refs


def delete_profile(config: dict[str, Any], profile_id: str) -> dict[str, Any]:
    pid = _profile_id(profile_id)
    refs = active_profile_references(config)
    if pid in refs:
        raise AppriseProfileConflict("Apprise profile is referenced by active configuration")
    with inventory_lock(_config_dir(config)):
        store = _read_store(config)
        rows = list(store.get(COLLECTION_KEY, []))
        idx = _find_index(rows, pid)
        if idx < 0:
            raise FileNotFoundError("Apprise profile not found")
        rows.pop(idx)
        store[COLLECTION_KEY] = rows
        _write_store(config, store)
        secret_deleted = False
        try:
            path = profile_secret_path(config, pid)
            if path.exists():
                path.unlink()
                secret_deleted = True
        except OSError as exc:
            raise InventoryAccessError(f"Apprise profile secret could not be deleted: {pid}") from exc
    return {"deleted": True, "profile_id": pid, "secret_deleted": secret_deleted}


def validate_profile_url(apprise_url: str) -> dict[str, Any]:
    try:
        result = validate_url(str(apprise_url or ""))
    except AppriseAdapterError as exc:
        return {"success": False, "message": str(exc), "message_code": "apprise_runtime_unavailable"}
    return {
        "success": bool(result.ok),
        "message": result.message,
        "message_code": "apprise_url_valid" if result.ok else "apprise_url_invalid",
    }


def validate_profile_payload(config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    url = _clean_string(payload.get("apprise_url") or payload.get("url"), max_len=4096)
    result = validate_profile_url(url)
    return {**result, "url_set": bool(url)}


def test_profile(config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    pid = str(payload.get("id") or payload.get("profile_id") or "").strip()
    url = _clean_string(payload.get("apprise_url") or payload.get("url"), max_len=4096)
    profile_name = _clean_string(payload.get("name") or "Borg Backup UI", max_len=80)
    timeout = _int_range(payload.get("timeout_seconds"), default=15, minimum=1, maximum=300, label="timeout_seconds")
    if not url and pid:
        profile = get_profile(config, pid)["profile"]
        url = _read_secret(config, pid)
        profile_name = _clean_string(profile.get("name") or profile_name, max_len=80)
        timeout = int(profile.get("timeout_seconds") or timeout)
    if not url:
        raise ValueError("apprise_url or profile_id is required")
    try:
        result = send_test_notification(
            url,
            title=profile_name,
            body="This is a test notification from Borg Backup UI.",
        )
    except AppriseAdapterError as exc:
        return {"success": False, "message": str(exc), "message_code": "apprise_runtime_unavailable"}
    return {
        "success": bool(result.ok),
        "message": result.message,
        "message_code": "apprise_test_sent" if result.ok else "apprise_test_failed",
        "timeout_seconds": timeout,
    }


def get_supported_providers(_config: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return supported_providers(timeout_seconds=5)
    except AppriseAdapterError as exc:
        return {
            "version": "",
            "providers": [],
            "provider_count": 0,
            "success": False,
            "message": str(exc),
            "message_code": "apprise_provider_discovery_failed",
        }
