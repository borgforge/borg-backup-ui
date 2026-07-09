"""Storage target inventory for Borg Backup UI.

Storage objects describe where repositories live. They are UI metadata only and
do not mount, create, modify, or delete storage targets.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _data_root(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    return base.parent if base.name == "scripts" else base


def storages_file(config: dict) -> Path:
    return _data_root(config) / "config" / "storages.json"


def _hash_suffix(value: str) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:8]


def storage_key_for(storage_type: str, identity: str) -> str:
    clean_type = "".join(ch if ch.isalnum() else "_" for ch in str(storage_type or "").strip().lower()).strip("_")
    clean_type = clean_type or "storage"
    return f"storage_{clean_type}_{_hash_suffix(identity)}"


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _normalize_path(path: str) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    if "://" in text:
        return text.rstrip("/")
    return text.rstrip("/") or "/"


def _parent_path(path_or_uri: str) -> str:
    text = _normalize_path(path_or_uri)
    if not text:
        return ""
    if "://" in text:
        parsed = urlsplit(text)
        parent = parsed.path.rstrip("/").rsplit("/", 1)[0] or "/"
        return f"{parsed.scheme}://{parsed.netloc}{parent}".rstrip("/")
    return str(Path(text).parent)


def _leaf_path(path_or_uri: str) -> str:
    text = _normalize_path(path_or_uri)
    if not text:
        return ""
    parsed_path = urlsplit(text).path if "://" in text else text
    return parsed_path.rstrip("/").rsplit("/", 1)[-1].strip()


def _relative_path(path_or_uri: str, base_path: str) -> str:
    path = _normalize_path(path_or_uri)
    base = _normalize_path(base_path)
    if not path or not base:
        return _leaf_path(path)
    if path == base:
        return ""
    prefix = base.rstrip("/") + "/"
    if path.startswith(prefix):
        return path[len(prefix):].strip("/")
    if "://" in path and "://" in base:
        path_parts = urlsplit(path)
        base_parts = urlsplit(base)
        if path_parts.scheme == base_parts.scheme and path_parts.netloc == base_parts.netloc:
            path_path = path_parts.path.rstrip("/")
            base_path_only = base_parts.path.rstrip("/")
            prefix_path = base_path_only.rstrip("/") + "/"
            if path_path.startswith(prefix_path):
                return path_path[len(prefix_path):].strip("/")
    return _leaf_path(path)


def _profiles_by_key(rows: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip().lower()
        if key:
            out[key] = row
    return out


def _settings_profiles(settings: dict[str, Any] | None) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    payload = settings if isinstance(settings, dict) else {}
    return (
        _profiles_by_key(payload.get("usb_profiles")),
        _profiles_by_key(payload.get("smb_profiles")),
        _profiles_by_key(payload.get("storage_profiles")),
    )


def normalize_storages(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("storage_key") or row.get("key") or "").strip()
        storage_type = str(row.get("storage_type") or row.get("location") or "").strip().lower()
        identity = str(row.get("identity") or row.get("base_path") or row.get("mount_path") or key).strip()
        if not key and storage_type and identity:
            key = storage_key_for(storage_type, identity)
        if not key or key in seen:
            continue
        seen.add(key)
        display_name = str(row.get("display_name") or row.get("name") or "").strip()
        if not display_name:
            display_name = {
                "local": "Local",
                "usb": "USB",
                "smb": "SMB",
                "storagebox": "Storagebox",
            }.get(storage_type, key)
        out.append({
            "storage_key": key,
            "display_name": display_name,
            "storage_type": storage_type,
            "location": str(row.get("location") or storage_type).strip().lower(),
            "identity": identity,
            "profile_key": str(row.get("profile_key") or "").strip(),
            "base_path": str(row.get("base_path") or "").strip(),
            "mount_path": str(row.get("mount_path") or "").strip(),
            "endpoint": str(row.get("endpoint") or "").strip(),
            "created_by": str(row.get("created_by") or "migration").strip(),
            "created_at": str(row.get("created_at") or "").strip(),
            "updated_at": str(row.get("updated_at") or "").strip(),
            "source": str(row.get("source") or "").strip(),
        })
    out.sort(key=lambda item: (str(item.get("storage_type") or ""), str(item.get("display_name") or "")))
    return out


def read_storage_store(config: dict) -> dict[str, Any]:
    payload = _read_json_file(storages_file(config))
    rows = payload.get("storages") if isinstance(payload.get("storages"), list) else []
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": str(payload.get("updated_at") or ""),
        "storages": normalize_storages(rows),
    }


def write_storage_store(config: dict, store: dict[str, Any]) -> None:
    path = storages_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now(),
        "storages": normalize_storages(store.get("storages") if isinstance(store, dict) else []),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def storage_from_repository(repo: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not isinstance(repo, dict):
        return None
    location = str(repo.get("location") or repo.get("storage_type") or "").strip().lower()
    path_raw = str(repo.get("path_raw") or repo.get("repo_uri") or repo.get("repo_path") or "").strip()
    if not location or not path_raw:
        return None

    usb_profiles, smb_profiles, storage_profiles = _settings_profiles(settings)
    profile_key = ""
    display_name = ""
    base_path = ""
    mount_path = ""
    endpoint = ""
    source = "repository"
    identity = ""

    if location == "usb":
        profile_key = str(repo.get("usb_profile_key") or "").strip().lower()
        profile = usb_profiles.get(profile_key) if profile_key else None
        if profile:
            display_name = str(profile.get("name") or profile_key).strip()
            mount_path = str(profile.get("mount_path") or "").strip()
            base_path = mount_path
            identity = f"usb-profile:{profile_key}"
            source = "usb_profile"
        else:
            base_path = _parent_path(path_raw)
            display_name = str(repo.get("storage_name") or "USB").strip()
            identity = f"usb:{base_path}"
    elif location == "smb":
        profile_key = str(repo.get("smb_profile_key") or "").strip().lower()
        profile = smb_profiles.get(profile_key) if profile_key else None
        if profile:
            display_name = str(profile.get("name") or profile_key).strip()
            mount_path = str(profile.get("mount_path") or "").strip()
            base_path = mount_path
            endpoint = "/".join(part for part in (str(profile.get("server") or "").strip(), str(profile.get("share") or "").strip()) if part)
            identity = f"smb-profile:{profile_key}"
            source = "smb_profile"
        else:
            base_path = _parent_path(path_raw)
            display_name = str(repo.get("storage_name") or "SMB").strip()
            identity = f"smb:{base_path}"
    elif location == "storagebox":
        profile_key = str(repo.get("storage_profile_key") or "").strip().lower()
        profile = storage_profiles.get(profile_key) if profile_key else None
        if profile:
            display_name = str(profile.get("name") or profile_key).strip()
            endpoint = ":".join(part for part in (str(profile.get("host") or "").strip(), str(profile.get("port") or "").strip()) if part)
            base_path = str(profile.get("base_path") or "").strip()
            identity = f"storagebox-profile:{profile_key}"
            source = "storage_profile"
        else:
            parsed = urlsplit(path_raw)
            endpoint = parsed.netloc
            base_path = _parent_path(path_raw)
            display_name = str(repo.get("storage_name") or "Storagebox").strip()
            identity = f"storagebox:{endpoint}:{base_path}"
    else:
        location = "local"
        base_path = _parent_path(path_raw)
        display_name = str(repo.get("storage_name") or "Local").strip()
        identity = f"local:{base_path}"

    storage_type = "ssh" if location == "storagebox" else location
    storage_key = storage_key_for(location, identity)
    ts = _now()
    return {
        "storage_key": storage_key,
        "display_name": display_name or storage_key,
        "storage_type": storage_type,
        "location": location,
        "identity": identity,
        "profile_key": profile_key,
        "base_path": base_path,
        "mount_path": mount_path,
        "endpoint": endpoint,
        "created_by": "migration",
        "created_at": ts,
        "updated_at": ts,
        "source": source,
    }


def repository_relative_path(repo: dict[str, Any], storage: dict[str, Any] | None) -> str:
    if not isinstance(repo, dict):
        return ""
    base = str((storage or {}).get("base_path") or (storage or {}).get("mount_path") or "").strip()
    path_raw = str(repo.get("path_raw") or repo.get("repo_uri") or repo.get("repo_path") or "").strip()
    return _relative_path(path_raw, base)


def upsert_storage_for_repository(config: dict, repo: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    storage = storage_from_repository(repo, settings=settings)
    if not storage:
        return None
    store = read_storage_store(config)
    rows = store["storages"]
    key = str(storage.get("storage_key") or "")
    previous = next((row for row in rows if str(row.get("storage_key") or "") == key), {})
    merged = {
        **previous,
        **storage,
        "storage_key": key,
        "created_at": str(previous.get("created_at") or storage.get("created_at") or _now()),
        "created_by": str(previous.get("created_by") or storage.get("created_by") or "migration"),
        "updated_at": _now(),
    }
    next_rows = [row for row in rows if str(row.get("storage_key") or "") != key]
    next_rows.append(merged)
    write_storage_store(config, {"storages": next_rows})
    return merged
