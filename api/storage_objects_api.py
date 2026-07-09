"""Storage target inventory for Borg Backup UI.

Storage objects describe where repositories live. They are UI metadata only and
do not mount, create, modify, or delete storage targets.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
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
            "host": str(row.get("host") or "").strip(),
            "port": str(row.get("port") or "").strip(),
            "user": str(row.get("user") or "").strip(),
            "server": str(row.get("server") or "").strip(),
            "share": str(row.get("share") or "").strip(),
            "target_type": str(row.get("target_type") or "").strip(),
            "ssh_key_path": str(row.get("ssh_key_path") or "").strip(),
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


def _profile_key(value: str, prefix: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-") or prefix
    if not base.startswith(f"{prefix}-"):
        base = f"{prefix}-{base}"
    candidate = base
    index = 2
    while candidate in existing:
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _safe_local_storage_path(value: str, *, field: str) -> str:
    raw = str(value or "").strip().rstrip("/") or "/"
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError(f"{field} must be an absolute path")
    blocked = {"/", "/mnt", "/boot", "/etc", "/usr", "/var"}
    if raw in blocked or not raw.startswith("/mnt/"):
        raise ValueError(f"{field} must be a dedicated directory below /mnt")
    if any(part in {".", ".."} for part in path.parts):
        raise ValueError(f"{field} contains unsafe path segments")
    return raw


def create_storage_target(config: dict, payload: dict[str, Any]) -> dict[str, Any]:
    """Create one storage target and persist profile-backed targets in settings.json."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid storage target payload")
    location = str(payload.get("storage_type") or payload.get("location") or "").strip().lower()
    if location == "ssh":
        location = "storagebox"
    if location not in {"local", "usb", "smb", "storagebox"}:
        raise ValueError("Invalid storage target type")
    display_name = str(payload.get("display_name") or "").strip()
    if not display_name:
        raise ValueError("Storage target display name is required")

    from config_api import read_settings_payload, write_settings_payload

    settings = read_settings_payload(config)
    store = read_storage_store(config)
    storages = store.get("storages", [])

    if location == "local":
        base_path = _safe_local_storage_path(payload.get("base_path", ""), field="Local storage path")
        identity = f"local:{base_path}"
        existing = next((row for row in storages if str(row.get("identity") or "") == identity), None)
        if existing:
            return {"ok": True, "created": False, "storage": existing}
        if bool(payload.get("create_base_path", True)):
            Path(base_path).mkdir(parents=True, exist_ok=True)
        now = _now()
        storage = {
            "storage_key": storage_key_for("local", identity),
            "display_name": display_name,
            "storage_type": "local",
            "location": "local",
            "identity": identity,
            "profile_key": "",
            "base_path": base_path,
            "mount_path": "",
            "created_by": "repository_wizard",
            "created_at": now,
            "updated_at": now,
            "source": "repository_wizard",
        }
        write_storage_store(config, {"storages": [*storages, storage]})
        return {"ok": True, "created": True, "storage": normalize_storages([storage])[0]}

    profile_field = {
        "usb": "usb_profiles",
        "smb": "smb_profiles",
        "storagebox": "storage_profiles",
    }[location]
    profiles = list(settings.get(profile_field) if isinstance(settings.get(profile_field), list) else [])
    existing_keys = {str(row.get("key") or "").strip().lower() for row in profiles if isinstance(row, dict)}
    prefix = {"usb": "usb", "smb": "smb", "storagebox": "storage"}[location]
    key = _profile_key(display_name, prefix, existing_keys)

    if location == "usb":
        mount_path = _safe_local_storage_path(payload.get("mount_path", ""), field="USB mount path")
        if not Path(mount_path).is_dir():
            raise ValueError("USB mount path does not exist or is not mounted")
        profile = {"key": key, "name": display_name, "mount_path": mount_path}
    elif location == "smb":
        server = str(payload.get("server") or "").strip()
        share = str(payload.get("share") or "").strip().lstrip("/")
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        if not server or not share or not username or not password:
            raise ValueError("SMB server, share, username and password are required")
        mount_path = f"/mnt/borg-backup-ui/smb/{key}"
        profile = {
            "key": key,
            "name": display_name,
            "server": server,
            "share": share,
            "mount_path": mount_path,
            "username": username,
            "smb_password": password,
            "vers": str(payload.get("vers") or "3.0").strip() or "3.0",
            "sec": str(payload.get("sec") or "").strip(),
        }
        from smb_profiles_api import prepare_smb_profiles_for_save
        profiles = prepare_smb_profiles_for_save(json.dumps([*profiles, profile], ensure_ascii=False))
        settings[profile_field] = profiles
        write_settings_payload(config, settings)
        storage_key = storage_key_for("smb", f"smb-profile:{key}")
        storage = next((row for row in read_storage_store(config)["storages"] if row["storage_key"] == storage_key), None)
        return {"ok": True, "created": True, "storage": storage, "managed_mount_path": mount_path}
    else:
        host = str(payload.get("host") or "").strip()
        user = str(payload.get("user") or "").strip()
        base_path = str(payload.get("base_path") or "").strip()
        port = str(payload.get("port") or "23").strip() or "23"
        ssh_key_path = str(payload.get("ssh_key_path") or "/root/.ssh/id_rsa").strip()
        if not host or not user or not base_path:
            raise ValueError("SSH host, user and base path are required")
        try:
            port_num = int(port)
        except ValueError as exc:
            raise ValueError("SSH port must be numeric") from exc
        if port_num < 1 or port_num > 65535:
            raise ValueError("SSH port is out of range")
        if ssh_key_path and not Path(ssh_key_path).is_absolute():
            raise ValueError("SSH key path must be absolute")
        profile = {
            "key": key,
            "name": display_name,
            "host": host,
            "port": str(port_num),
            "user": user,
            "base_path": base_path,
            "target_type": str(payload.get("target_type") or "storagebox").strip() or "storagebox",
            "ssh_key_path": ssh_key_path,
        }

    settings[profile_field] = [*profiles, profile]
    write_settings_payload(config, settings)
    storage_type = "storagebox" if location == "storagebox" else location
    storage_key = storage_key_for(storage_type, f"{storage_type}-profile:{key}")
    storage = next((row for row in read_storage_store(config)["storages"] if row["storage_key"] == storage_key), None)
    if not storage:
        raise RuntimeError("Storage target inventory was not updated")
    return {"ok": True, "created": True, "storage": storage}


def test_storage_target(config: dict, storage_key: str) -> dict[str, Any]:
    key = str(storage_key or "").strip()
    storage = next((row for row in read_storage_store(config)["storages"] if row["storage_key"] == key), None)
    if not storage:
        raise ValueError("Storage target not found")
    location = str(storage.get("location") or storage.get("storage_type") or "").strip().lower()
    if location == "smb":
        from smb_profiles_api import run_smb_profile_action
        result = run_smb_profile_action(config, str(storage.get("profile_key") or ""), "test")
        return {"ok": bool(result.get("ok", False)), "storage_key": key, "details": result}
    if location == "storagebox" or str(storage.get("storage_type") or "").lower() == "ssh":
        from storagebox_api import storagebox_connection_test
        result = storagebox_connection_test(config, str(storage.get("profile_key") or ""))
        return {"ok": bool(result.get("success", False)), "storage_key": key, "details": result}

    path = str(storage.get("base_path") or storage.get("mount_path") or "").strip()
    if not path or not Path(path).is_dir():
        return {"ok": False, "storage_key": key, "message": "Storage path does not exist or is not mounted"}
    probe = Path(path) / f".bbui-storage-test-{uuid.uuid4().hex[:10]}"
    fd: int | None = None
    try:
        fd = os.open(str(probe), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, b"ok\n")
        os.close(fd)
        fd = None
        probe.unlink(missing_ok=True)
    except Exception as exc:
        if fd is not None:
            os.close(fd)
        probe.unlink(missing_ok=True)
        return {"ok": False, "storage_key": key, "message": f"Storage path is not writable: {exc}"}
    return {"ok": True, "storage_key": key, "message": "Storage path is readable and writable"}


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
    host = ""
    port = ""
    user = ""
    server = ""
    share = ""
    target_type = ""
    ssh_key_path = ""
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
            server = str(profile.get("server") or "").strip()
            share = str(profile.get("share") or "").strip()
            endpoint = "/".join(part for part in (server, share) if part)
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
            host = str(profile.get("host") or "").strip()
            port = str(profile.get("port") or "").strip()
            user = str(profile.get("user") or "").strip()
            target_type = str(profile.get("target_type") or "").strip()
            ssh_key_path = str(profile.get("ssh_key_path") or "").strip()
            endpoint = ":".join(part for part in (host, port) if part)
            base_path = str(profile.get("base_path") or "").strip()
            identity = f"storagebox-profile:{profile_key}"
            source = "storage_profile"
        else:
            parsed = urlsplit(path_raw)
            endpoint = parsed.netloc
            host = parsed.hostname or ""
            port = str(parsed.port or "")
            user = parsed.username or ""
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
        "host": host,
        "port": port,
        "user": user,
        "server": server,
        "share": share,
        "target_type": target_type,
        "ssh_key_path": ssh_key_path,
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


def upsert_storages_from_settings(config: dict, settings: dict[str, Any] | None) -> list[str]:
    """Create/update storage objects from configured storage profiles.

    The Settings page is still the input surface for profiles during the
    #184/#187 transition. This function writes the future storage inventory
    without deleting existing storage objects or repositories.
    """
    payload = settings if isinstance(settings, dict) else {}
    store = read_storage_store(config)
    rows = store["storages"]
    by_key = {str(row.get("storage_key") or ""): row for row in rows if str(row.get("storage_key") or "").strip()}
    changed: list[str] = []

    def merge(storage: dict[str, Any]) -> None:
        key = str(storage.get("storage_key") or "").strip()
        if not key:
            return
        previous = by_key.get(key, {})
        merged = {
            **previous,
            **storage,
            "storage_key": key,
            "created_at": str(previous.get("created_at") or storage.get("created_at") or _now()),
            "created_by": str(previous.get("created_by") or storage.get("created_by") or "settings"),
            "updated_at": _now(),
        }
        before_norm = normalize_storages([previous])[0] if previous else {}
        after_norm = normalize_storages([merged])[0]
        if before_norm != after_norm:
            changed.append(key)
        by_key[key] = merged

    for profile in payload.get("usb_profiles") if isinstance(payload.get("usb_profiles"), list) else []:
        if not isinstance(profile, dict):
            continue
        profile_key = str(profile.get("key") or "").strip().lower()
        mount_path = str(profile.get("mount_path") or "").strip()
        if not profile_key or not mount_path:
            continue
        merge({
            "storage_key": storage_key_for("usb", f"usb-profile:{profile_key}"),
            "display_name": str(profile.get("name") or profile_key).strip(),
            "storage_type": "usb",
            "location": "usb",
            "identity": f"usb-profile:{profile_key}",
            "profile_key": profile_key,
            "base_path": mount_path,
            "mount_path": mount_path,
            "source": "usb_profile",
            "created_by": "settings",
        })

    for profile in payload.get("smb_profiles") if isinstance(payload.get("smb_profiles"), list) else []:
        if not isinstance(profile, dict):
            continue
        profile_key = str(profile.get("key") or "").strip().lower()
        mount_path = str(profile.get("mount_path") or "").strip()
        if not profile_key or not mount_path:
            continue
        server = str(profile.get("server") or "").strip()
        share = str(profile.get("share") or "").strip()
        merge({
            "storage_key": storage_key_for("smb", f"smb-profile:{profile_key}"),
            "display_name": str(profile.get("name") or profile_key).strip(),
            "storage_type": "smb",
            "location": "smb",
            "identity": f"smb-profile:{profile_key}",
            "profile_key": profile_key,
            "base_path": mount_path,
            "mount_path": mount_path,
            "endpoint": "/".join(part for part in (server, share) if part),
            "server": server,
            "share": share,
            "source": "smb_profile",
            "created_by": "settings",
        })

    for profile in payload.get("storage_profiles") if isinstance(payload.get("storage_profiles"), list) else []:
        if not isinstance(profile, dict):
            continue
        profile_key = str(profile.get("key") or "").strip().lower()
        host = str(profile.get("host") or "").strip()
        base_path = str(profile.get("base_path") or "").strip()
        if not profile_key or not host or not base_path:
            continue
        port = str(profile.get("port") or "").strip()
        merge({
            "storage_key": storage_key_for("storagebox", f"storagebox-profile:{profile_key}"),
            "display_name": str(profile.get("name") or profile_key).strip(),
            "storage_type": "ssh",
            "location": "storagebox",
            "identity": f"storagebox-profile:{profile_key}",
            "profile_key": profile_key,
            "base_path": base_path,
            "endpoint": ":".join(part for part in (host, port) if part),
            "host": host,
            "port": port,
            "user": str(profile.get("user") or "").strip(),
            "target_type": str(profile.get("target_type") or "storagebox").strip(),
            "ssh_key_path": str(profile.get("ssh_key_path") or "").strip(),
            "source": "storage_profile",
            "created_by": "settings",
        })

    if changed:
        write_storage_store(config, {"storages": list(by_key.values())})
    return sorted(set(changed))
