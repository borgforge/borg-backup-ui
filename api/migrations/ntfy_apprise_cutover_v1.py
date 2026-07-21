"""Migration: move native ntfy configuration into an Apprise profile."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from inventory_store import atomic_write_bytes, atomic_write_inventory, inventory_lock, read_inventory

MIGRATION_ID = "ntfy_apprise_cutover_v1"
INTRODUCED_IN = "2026.07.21.1347"
DESCRIPTION = "Migrate native ntfy settings into Apprise profiles and remove native ntfy config keys."

PROFILE_COLLECTION_KEY = "profiles"
PROFILE_SCHEMA_VERSION = 1
NTFY_KEYS = {
    "NTFY_ENABLED",
    "NTFY_PROFILE_NAME",
    "NTFY_SERVER_URL",
    "NTFY_TOPIC",
    "NTFY_USERNAME",
    "NTFY_PASSWORD_FILE",
    "NTFY_ACCESS_TOKEN_FILE",
    "NTFY_PRIORITY",
    "NTFY_TAGS",
    "NTFY_CLICK_URL",
    "NTFY_EVENTS",
    "NTFY_TIMEOUT_SECONDS",
}


def detect(config: dict) -> dict[str, Any]:
    from config_api import read_raw_conf

    conf = read_raw_conf(config)
    native_keys = sorted(key for key in NTFY_KEYS if key in conf)
    profile_exists = _migrated_profile_exists(config)
    configured = _native_ntfy_configured(conf)
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(native_keys),
        "native_keys": native_keys,
        "native_ntfy_configured": configured,
        "migrated_profile_exists": profile_exists,
        "reason": (
            "Native ntfy keys are present and must be migrated or removed"
            if native_keys
            else "Native ntfy cutover is current"
        ),
    }


def apply(config: dict) -> dict[str, Any]:
    from config_api import read_raw_conf, write_conf

    conf = read_raw_conf(config)
    native_keys = sorted(key for key in NTFY_KEYS if key in conf)
    if not native_keys:
        return _result("not_required", native_keys=native_keys, profile_id="", profile_created=False)

    profile_id = ""
    profile_created = False
    url_written = False
    if _native_ntfy_configured(conf) and not _migrated_profile_exists(config):
        profile, url = _profile_from_native_ntfy(config, conf)
        profile_id = str(profile.get("id") or "")
        _store_profile(config, profile)
        profile_created = True
        if url:
            atomic_write_bytes(
                _profile_secret_path(config, profile_id),
                (url + "\n").encode("utf-8"),
                mode=0o600,
            )
            url_written = True

    changed = write_conf(config, {}, snapshot_reason="Native ntfy Apprise cutover")
    return _result(
        "applied" if (changed or profile_created) else "not_required",
        native_keys=native_keys,
        profile_id=profile_id,
        profile_created=profile_created,
        url_written=url_written,
    )


def _result(
    status: str,
    *,
    native_keys: list[str],
    profile_id: str,
    profile_created: bool,
    url_written: bool = False,
) -> dict[str, Any]:
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": status,
        "details": {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "removed_keys": native_keys,
            "profile_id": profile_id,
            "profile_created": profile_created,
            "secret_written": url_written,
            "legacy_secret_files_preserved": True,
        },
    }


def _native_ntfy_configured(conf: dict[str, str]) -> bool:
    enabled = str(conf.get("NTFY_ENABLED", "false") or "").strip().lower() in {"1", "true", "yes", "on"}
    return enabled or bool(str(conf.get("NTFY_SERVER_URL", "") or "").strip() or str(conf.get("NTFY_TOPIC", "") or "").strip())


def _profile_from_native_ntfy(config: dict, conf: dict[str, str]) -> tuple[dict[str, Any], str]:
    profile_id = _next_profile_id(config, "ntfy-migrated")
    now = _utc_now()
    events = _events(str(conf.get("NTFY_EVENTS", "") or "backup_success,backup_failed,backup_skipped,restore_test_failed"))
    if "backup_failed" in events and "backup_warning" not in events:
        events.append("backup_warning")
    url, template, fields = _native_ntfy_url(conf)
    enabled = str(conf.get("NTFY_ENABLED", "false") or "").strip().lower() in {"1", "true", "yes", "on"}
    profile = {
        "id": profile_id,
        "name": str(conf.get("NTFY_PROFILE_NAME", "") or "ntfy").strip() or "ntfy",
        "enabled": bool(enabled and url),
        "provider": "ntfy",
        "selected_events": events,
        "timeout_seconds": _int_range(conf.get("NTFY_TIMEOUT_SECONDS"), default=15, minimum=1, maximum=300),
        "retry_policy": {"attempts": 1, "backoff_seconds": 0},
        "priority": _priority(conf.get("NTFY_PRIORITY")),
        "default": not _has_default_profile(config),
        "url_template": template,
        "url_fields": fields,
        "created_at": now,
        "updated_at": now,
        "url_set": bool(url),
        "migration": {
            "source": "native_ntfy",
            "migration_id": MIGRATION_ID,
            "migrated_at": now,
        },
    }
    return profile, url


def _native_ntfy_url(conf: dict[str, str]) -> tuple[str, str, dict[str, str]]:
    server_url = str(conf.get("NTFY_SERVER_URL", "") or "").strip()
    topic = str(conf.get("NTFY_TOPIC", "") or "").strip().strip("/")
    if not server_url or not topic:
        return "", "", _fields_from_native(conf)

    parsed = urlsplit(server_url if "://" in server_url else f"https://{server_url}")
    scheme = "ntfys" if parsed.scheme == "https" else "ntfy"
    host = parsed.hostname or parsed.netloc or parsed.path.strip("/")
    if not host:
        return "", "", _fields_from_native(conf)
    if parsed.port:
        host = f"{host}:{parsed.port}"

    username = str(conf.get("NTFY_USERNAME", "") or "").strip()
    password = _read_secret(conf.get("NTFY_PASSWORD_FILE", ""))
    token = _read_secret(conf.get("NTFY_ACCESS_TOKEN_FILE", ""))
    query = _ntfy_query(conf, auth="token" if token else ("basic" if username else ""))
    target = quote(topic, safe="")

    if token:
        template = "{schema}://{token}@{host}/{targets}"
        auth = f"{quote(token, safe='')}@"
    elif username and password:
        template = "{schema}://{user}:{password}@{host}/{targets}"
        auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    elif username:
        template = "{schema}://{user}@{host}/{targets}"
        auth = f"{quote(username, safe='')}@"
    else:
        template = "{schema}://{host}/{targets}"
        auth = ""

    url = f"{scheme}://{auth}{host}/{target}"
    if query:
        url = f"{url}?{query}"
    return url, template, _fields_from_native(conf)


def _ntfy_query(conf: dict[str, str], *, auth: str) -> str:
    params: dict[str, str] = {}
    priority = _priority(conf.get("NTFY_PRIORITY"))
    if priority and priority != "default":
        params["priority"] = "max" if priority == "urgent" else priority
    tags = str(conf.get("NTFY_TAGS", "") or "").strip()
    if tags:
        params["xtags"] = tags
    click = str(conf.get("NTFY_CLICK_URL", "") or "").strip()
    if click:
        params["click"] = click
    if auth:
        params["auth"] = auth
    return urlencode(params)


def _fields_from_native(conf: dict[str, str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    server_url = str(conf.get("NTFY_SERVER_URL", "") or "").strip()
    topic = str(conf.get("NTFY_TOPIC", "") or "").strip().strip("/")
    username = str(conf.get("NTFY_USERNAME", "") or "").strip()
    if server_url:
        parsed = urlsplit(server_url if "://" in server_url else f"https://{server_url}")
        host = parsed.hostname or parsed.netloc or parsed.path.strip("/")
        if host and parsed.port:
            host = f"{host}:{parsed.port}"
        if host:
            fields["host"] = host
    if topic:
        fields["targets"] = topic
    if username:
        fields["user"] = username
    return fields


def _events(raw: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in str(raw or "").split(","):
        event = item.strip()
        if event and event not in seen:
            seen.add(event)
            result.append(event)
    return result or ["backup_failed"]


def _priority(value: Any) -> str:
    text = str(value or "default").strip().lower() or "default"
    return text if text in {"default", "min", "low", "high", "urgent"} else "default"


def _int_range(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value or default).strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _read_secret(path_value: Any) -> str:
    path = Path(str(path_value or "").strip())
    if not str(path):
        return ""
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return ""


def _migrated_profile_exists(config: dict) -> bool:
    for row in _read_profiles(config):
        migration = row.get("migration") if isinstance(row.get("migration"), dict) else {}
        if str(migration.get("source") or "") == "native_ntfy":
            return True
        if str(row.get("id") or "") == "ntfy-migrated":
            return True
    return False


def _has_default_profile(config: dict) -> bool:
    return any(bool(row.get("default")) for row in _read_profiles(config))


def _next_profile_id(config: dict, base: str) -> str:
    existing = {str(row.get("id") or "") for row in _read_profiles(config)}
    if base not in existing:
        return base
    for idx in range(2, 100):
        candidate = f"{base}-{idx}"
        if candidate not in existing:
            return candidate
    raise RuntimeError("Could not allocate migrated ntfy Apprise profile id.")


def _store_profile(config: dict, profile: dict[str, Any]) -> None:
    with inventory_lock(_config_dir(config)):
        payload = read_inventory(_profile_store_path(config), collection_key=PROFILE_COLLECTION_KEY, schema_version=PROFILE_SCHEMA_VERSION)
        rows = payload.get(PROFILE_COLLECTION_KEY) if isinstance(payload.get(PROFILE_COLLECTION_KEY), list) else []
        rows.append(profile)
        payload[PROFILE_COLLECTION_KEY] = rows
        payload["schema_version"] = PROFILE_SCHEMA_VERSION
        payload["updated_at"] = _utc_now()
        atomic_write_inventory(_profile_store_path(config), payload)


def _read_profiles(config: dict) -> list[dict[str, Any]]:
    try:
        payload = read_inventory(_profile_store_path(config), collection_key=PROFILE_COLLECTION_KEY, schema_version=PROFILE_SCHEMA_VERSION)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []
    rows = payload.get(PROFILE_COLLECTION_KEY) if isinstance(payload.get(PROFILE_COLLECTION_KEY), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _data_root(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    return base.parent if base.name == "scripts" else base


def _config_dir(config: dict) -> Path:
    return _data_root(config) / "config"


def _profile_store_path(config: dict) -> Path:
    return _config_dir(config) / "apprise-profiles.json"


def _profile_secret_path(config: dict, profile_id: str) -> Path:
    return _data_root(config) / "secrets" / f".apprise-profile-{profile_id}.url"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
