"""
api/config_api.py – backup.conf lesen, schreiben und Repositories verwalten

Zwei Lesemodi:
  read_expanded_conf() → via lib/status.py load_config() (Variablen expandiert)
  read_raw_conf()      → ohne Expansion (für Edit-Felder, erhält ${VAR})
"""

import os
import re
import json
import logging
import subprocess
import shutil
import shlex
import difflib
import threading
import time
import uuid
import pty
import select
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from api.security_utils import mask_secrets
except ImportError:  # pragma: no cover - direct api module imports in tests
    from security_utils import mask_secrets

try:
    from api.inventory_store import atomic_write_bytes, inventory_lock
except ImportError:  # pragma: no cover - direct api module imports in tests
    from inventory_store import atomic_write_bytes, inventory_lock

from smb_profiles_api import (
    cleanup_removed_smb_mountpoints,
    cleanup_removed_smb_secrets,
    get_smb_profile_job_refs,
    get_smb_profiles_with_status,
    normalize_smb_profile_rows,
    prepare_smb_profiles_for_save,
    run_smb_profile_action,
    test_smb_profiles_status,
    validate_smb_profile_usage_before_save,
    validate_smb_profiles_json,
)
from storage_profiles_api import (
    get_storage_profile_job_refs,
    normalize_storage_base_path as _normalize_storage_base_path,
    normalize_storage_profile_rows as _normalize_storage_profile_rows,
    resolve_storage_profile,
    validate_storage_profiles_complete_before_save,
    validate_storage_profile_usage_before_save,
)
from usb_profiles_api import (
    get_usb_profile_job_refs,
    normalize_usb_profile_rows as _normalize_usb_profile_rows,
    test_usb_profiles_status,
    validate_usb_profile_usage_before_save,
)

logger = logging.getLogger(__name__)

BACKUP_TYPES = ["flash", "appdata", "photos", "VMs", "sonstiges"]

# Mapping: Konfig-Suffix → Backup-Typ-Anzeigename
_CONF_TYPE_MAP = {
    "FLASH": "flash",
    "APPDATA": "appdata",
    "PHOTOS": "photos",
    "VMS": "VMs",
    "SONSTIGES": "sonstiges",
}

# ── Pfad-Hilfsfunktionen ─────────────────────────────────────────────────────

def _is_unraid_array_started() -> bool:
    """
    Best effort check for Unraid array state.
    Returns True when the array is operational for our use-case.
    Primary signal is mdcmd; fallback is a real /mnt/user mount.
    """
    mounted_user = False
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as fh:
            mounts = fh.read()
        mounted_user = " /mnt/user " in mounts
    except Exception:
        mounted_user = False

    try:
        proc = subprocess.run(
            ["mdcmd", "status"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return mounted_user

    if proc.returncode != 0:
        return mounted_user
    out = str(proc.stdout or "")
    if "mdState=STARTED" in out:
        return True

    # Fallback for environments/boot phases where mdcmd output is not reliable
    # but /mnt/user is already mounted and usable.
    return mounted_user

def get_conf_file(ui_config: dict) -> Path:
    """Return the persistent user configuration file."""
    scripts_dir = Path(ui_config["BACKUP_SCRIPTS_DIR"])
    return scripts_dir / "config" / "backup.conf"


def get_backup_conf_schema_file(ui_config: dict) -> Path:
    """Return the version-owned backup.conf schema shipped by the plugin."""
    override = str(ui_config.get("BACKUP_CONF_SCHEMA_FILE") or "").strip()
    if override:
        schema_file = Path(override)
    else:
        runtime_scripts = str(ui_config.get("BORG_SCRIPTS_DIR") or "").strip()
        if runtime_scripts:
            schema_file = Path(runtime_scripts).resolve().parent / "config" / "backup.conf.example"
        else:
            schema_file = Path(__file__).resolve().parent.parent / "runtime" / "config" / "backup.conf.example"
    if not schema_file.is_file():
        raise FileNotFoundError(f"Plugin backup.conf schema is missing: {schema_file}")
    return schema_file


def conf_exists(ui_config: dict) -> bool:
    conf = Path(ui_config["BACKUP_SCRIPTS_DIR"]) / "config" / "backup.conf"
    return conf.exists()


def _conf_backup_dir(ui_config: dict) -> Path:
    return Path(ui_config["BACKUP_SCRIPTS_DIR"]) / "config" / "backups"


def _backup_conf_timestamp_from_name(name: str) -> datetime | None:
    match = re.match(r"^backup\.conf\.(\d{8})-(\d{6})\.bak$", str(name or ""))
    if not match:
        return None
    try:
        return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _backup_conf_created_at_from_meta(meta: dict[str, Any], name: str, fallback_mtime: float) -> datetime:
    raw = str(meta.get("created_at") or "").strip()
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    from_name = _backup_conf_timestamp_from_name(name)
    if from_name is not None:
        return from_name
    return datetime.fromtimestamp(fallback_mtime)


def backup_conf_snapshot(ui_config: dict, keep: int = 10, reason: str = "") -> Optional[Path]:
    """Creates a timestamped backup of backup.conf before write operations."""
    conf_file = Path(ui_config["BACKUP_SCRIPTS_DIR"]) / "config" / "backup.conf"
    if not conf_file.exists():
        return None
    backup_dir = _conf_backup_dir(ui_config)
    backup_dir.mkdir(parents=True, exist_ok=True)
    created = datetime.now()
    ts = created.strftime("%Y%m%d-%H%M%S")
    dst = backup_dir / f"backup.conf.{ts}.bak"
    shutil.copy2(conf_file, dst)
    try:
        os.utime(dst, (created.timestamp(), created.timestamp()))
    except OSError:
        pass
    meta = {
        "reason": str(reason or "").strip(),
        "created_at": created.isoformat(timespec="seconds"),
        "source": str(conf_file),
    }
    meta_file = backup_dir / f"{dst.name}.meta.json"
    try:
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    backups = sorted(backup_dir.glob("backup.conf.*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
        old_meta = backup_dir / f"{old.name}.meta.json"
        try:
            old_meta.unlink()
        except OSError:
            pass
    return dst


def list_conf_backups(ui_config: dict) -> dict:
    backup_dir = _conf_backup_dir(ui_config)
    items = []
    if backup_dir.is_dir():
        for p in backup_dir.glob("backup.conf.*.bak"):
            st = p.stat()
            reason = ""
            meta: dict[str, Any] = {}
            meta_file = backup_dir / f"{p.name}.meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    reason = str(meta.get("reason") or "").strip()
                except (json.JSONDecodeError, OSError, TypeError, ValueError):
                    meta = {}
                    reason = ""
            created_at = _backup_conf_created_at_from_meta(meta, p.name, st.st_mtime)
            items.append({
                "name": p.name,
                "path": str(p),
                "size": int(st.st_size),
                "mtime": int(st.st_mtime),
                "created_at": created_at.isoformat(timespec="seconds"),
                "created_ts": int(created_at.timestamp()),
                "reason": reason,
            })
        items.sort(key=lambda row: int(row.get("created_ts") or row.get("mtime") or 0), reverse=True)
    return {"backups": items, "backup_dir": str(backup_dir)}


def restore_conf_backup(ui_config: dict, name: str) -> dict:
    if not name or "/" in name or ".." in name:
        raise ValueError("Invalid backup name")
    backup_dir = _conf_backup_dir(ui_config)
    src = backup_dir / name
    if not src.exists() or not src.is_file():
        raise FileNotFoundError("Backup file not found")
    conf_file = Path(ui_config["BACKUP_SCRIPTS_DIR"]) / "config" / "backup.conf"
    conf_file.parent.mkdir(parents=True, exist_ok=True)
    with inventory_lock(conf_file.parent):
        restored_content = src.read_text(encoding="utf-8")
        plan = canonical_backup_conf_plan(ui_config, source_content=restored_content)
        backup_conf_snapshot(ui_config, keep=10, reason="Restore before recovery")
        atomic_write_bytes(conf_file, plan["content"].encode("utf-8"))
    return {"restored": True, "name": name}


def delete_conf_backup(ui_config: dict, name: str) -> dict:
    if not name or "/" in name or ".." in name:
        raise ValueError("Invalid backup name")
    backup_dir = _conf_backup_dir(ui_config)
    target = backup_dir / name
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("Backup file not found")
    target.unlink()
    meta_file = backup_dir / f"{name}.meta.json"
    try:
        meta_file.unlink()
    except OSError:
        pass
    return {"deleted": True, "name": name}


def delete_conf_backups_keep_latest(ui_config: dict) -> dict:
    backup_dir = _conf_backup_dir(ui_config)
    if not backup_dir.is_dir():
        return {"deleted_count": 0, "kept": None}
    backups = sorted(backup_dir.glob("backup.conf.*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        return {"deleted_count": 0, "kept": None}
    kept = backups[0].name
    deleted = 0
    for p in backups[1:]:
        try:
            p.unlink()
            deleted += 1
        except OSError:
            pass
        meta_file = backup_dir / f"{p.name}.meta.json"
        try:
            meta_file.unlink()
        except OSError:
            pass
    return {"deleted_count": deleted, "kept": kept}


def diff_conf_backup(ui_config: dict, name: str, context_lines: int = 3) -> dict:
    """
    Zeigt Unified-Diff vom gewaehlten Backup zur aktiven backup.conf.
    """
    if not name or "/" in name or ".." in name:
        raise ValueError("Invalid backup name")
    backup_dir = _conf_backup_dir(ui_config)
    backup_file = backup_dir / name
    if not backup_file.exists() or not backup_file.is_file():
        raise FileNotFoundError("Backup file not found")

    conf_file = Path(ui_config["BACKUP_SCRIPTS_DIR"]) / "config" / "backup.conf"
    if not conf_file.exists() or not conf_file.is_file():
        raise FileNotFoundError("Active backup.conf not found")

    ctx = int(context_lines) if str(context_lines).strip().isdigit() else 3
    ctx = max(0, min(20, ctx))

    current_text = conf_file.read_text(encoding="utf-8", errors="replace").splitlines()
    backup_text = backup_file.read_text(encoding="utf-8", errors="replace").splitlines()

    diff_lines = list(
        difflib.unified_diff(
            backup_text,
            current_text,
            fromfile=str(backup_file),
            tofile=str(conf_file),
            lineterm="",
            n=ctx,
        )
    )
    changed = bool(diff_lines)
    # Side-by-side payload for UI rendering (line-based). The matcher uses the
    # conventional old->new direction, while the UI keeps the active file on the
    # left because that is the primary object the user is inspecting.
    matcher = difflib.SequenceMatcher(a=backup_text, b=current_text)
    side_by_side: List[Dict[str, Any]] = []
    left_ln = 1
    right_ln = 1
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for rj, li in zip(range(i1, i2), range(j1, j2)):
                side_by_side.append({
                    "tag": "equal",
                    "left_no": left_ln,
                    "left": current_text[li],
                    "right_no": right_ln,
                    "right": backup_text[rj],
                })
                left_ln += 1
                right_ln += 1
        elif tag == "replace":
            l_chunk = current_text[j1:j2]
            r_chunk = backup_text[i1:i2]
            max_len = max(len(l_chunk), len(r_chunk))
            for idx in range(max_len):
                l_val = l_chunk[idx] if idx < len(l_chunk) else ""
                r_val = r_chunk[idx] if idx < len(r_chunk) else ""
                side_by_side.append({
                    "tag": "replace",
                    "left_no": left_ln if idx < len(l_chunk) else None,
                    "left": l_val,
                    "right_no": right_ln if idx < len(r_chunk) else None,
                    "right": r_val,
                })
                if idx < len(l_chunk):
                    left_ln += 1
                if idx < len(r_chunk):
                    right_ln += 1
        elif tag == "delete":
            for rj in range(i1, i2):
                side_by_side.append({
                    "tag": "delete",
                    "left_no": None,
                    "left": "",
                    "right_no": right_ln,
                    "right": backup_text[rj],
                })
                right_ln += 1
        elif tag == "insert":
            for li in range(j1, j2):
                side_by_side.append({
                    "tag": "insert",
                    "left_no": left_ln,
                    "left": current_text[li],
                    "right_no": None,
                    "right": "",
                })
                left_ln += 1

    return {
        "name": name,
        "changed": changed,
        "diff": "\n".join(diff_lines) if changed else "",
        "side_by_side": side_by_side,
        "from_file": str(backup_file),
        "to_file": str(conf_file),
    }


# ── Lesen ────────────────────────────────────────────────────────────────────

def read_expanded_conf(ui_config: dict) -> dict:
    """Liest backup.conf via load_config() (Variablen expandiert)."""
    merged = read_conf_defaults(ui_config)
    try:
        from status import load_config
        conf_file = get_conf_file(ui_config)
        merged.update(load_config(conf_file))
    except ImportError:
        pass
    return merged


def read_raw_conf(ui_config: dict) -> dict:
    """
    Liest backup.conf OHNE Variablen-Expansion.
    Gibt die in backup.conf gespeicherten Original-Werte zurück.
    """
    conf_file = get_conf_file(ui_config)
    result: Dict[str, str] = {}
    if not conf_file.exists():
        return result
    for line in conf_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        clean = stripped.removeprefix("readonly ")
        if "=" not in clean or clean.startswith("("):
            continue
        key, _, value = clean.partition("=")
        key = key.strip()
        value = _decode_conf_value(value)
        if value.startswith("("):
            continue
        if key:
            result[key] = value
    return result


def _iter_conf_assignment_keys(lines: List[str]) -> List[str]:
    keys: List[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        clean = s.removeprefix("readonly ")
        if "=" not in clean or clean.startswith("("):
            continue
        key = clean.split("=", 1)[0].strip()
        if key and re.fullmatch(r"[A-Z0-9_]+", key):
            keys.append(key)
    return keys


def _quote_conf_value(val: str) -> str:
    txt = str(val)
    if "\n" in txt or "\r" in txt:
        raise ValueError("backup.conf values must not contain line breaks")
    # JSON string quoting is a strict subset of the supported configuration
    # syntax and gives quotes/backslashes an unambiguous round trip.
    return json.dumps(txt, ensure_ascii=True)


def _decode_conf_value(raw_value: str) -> str:
    """Decode one backup.conf value without expanding ${VAR} references."""
    value = str(raw_value or "").strip()
    if not value:
        return ""

    if value.startswith('"'):
        try:
            decoded, end = json.JSONDecoder().raw_decode(value)
            remainder = value[end:].strip()
            if isinstance(decoded, str) and (not remainder or remainder.startswith("#")):
                return decoded
        except (json.JSONDecodeError, TypeError):
            pass

    if value.startswith("'"):
        end = value.rfind("'")
        if end > 0:
            remainder = value[end + 1:].strip()
            if not remainder or remainder.startswith("#"):
                return value[1:end]

    comment_pos = value.find("  #")
    if comment_pos != -1:
        value = value[:comment_pos].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value


def _parse_raw_conf_text(content: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in str(content or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        clean = stripped.removeprefix("readonly ")
        if "=" not in clean or clean.startswith("("):
            continue
        key, _, value = clean.partition("=")
        key = key.strip()
        value = _decode_conf_value(value)
        if key and re.fullmatch(r"[A-Z0-9_]+", key):
            values[key] = value
    return values


def read_conf_defaults(ui_config: dict) -> Dict[str, str]:
    """Read defaults from the version-owned plugin schema."""
    example_file = get_backup_conf_schema_file(ui_config)
    return _parse_raw_conf_text(example_file.read_text(encoding="utf-8"))


def canonical_backup_conf_plan(
    ui_config: dict,
    *,
    source_content: Optional[str] = None,
    updates: Optional[Dict[str, str]] = None,
) -> dict:
    """Build canonical backup.conf content from the version-owned schema."""
    config_dir = Path(ui_config["BACKUP_SCRIPTS_DIR"]) / "config"
    conf_file = config_dir / "backup.conf"
    example_file = get_backup_conf_schema_file(ui_config)

    example_content = example_file.read_text(encoding="utf-8")
    if source_content is None:
        source_content = conf_file.read_text(encoding="utf-8") if conf_file.exists() else ""
    current_map = _parse_raw_conf_text(source_content)
    example_map = _parse_raw_conf_text(example_content)
    schema_keys = _iter_conf_assignment_keys(example_content.splitlines())
    schema_set = set(schema_keys)
    requested = {str(key): str(value) for key, value in (updates or {}).items()}
    unsupported = sorted(set(requested) - schema_set)
    if unsupported:
        raise ValueError("Unsupported backup.conf keys: " + ", ".join(unsupported))

    effective = {key: current_map.get(key, example_map.get(key, "")) for key in schema_keys}
    effective.update(requested)
    output: List[str] = []
    for line in example_content.splitlines(keepends=True):
        stripped = line.strip()
        clean = stripped.removeprefix("readonly ")
        if not stripped or stripped.startswith("#") or "=" not in clean or clean.startswith("("):
            output.append(line if line.endswith("\n") else line + "\n")
            continue
        key = clean.split("=", 1)[0].strip()
        if key not in schema_set:
            output.append(line if line.endswith("\n") else line + "\n")
            continue
        output.append(f"{key}={_quote_conf_value(effective[key])}\n")

    rendered = "".join(output)
    return {
        "content": rendered,
        "changed": rendered != source_content,
        "schema_keys": schema_keys,
        "missing_keys": sorted(schema_set - set(current_map)),
        "unknown_keys": sorted(set(current_map) - schema_set),
    }


# ── Schreiben ─────────────────────────────────────────────────────────────────

def write_conf(ui_config: dict, updates: Dict[str, str], snapshot_reason: str = "") -> bool:
    """
    Baut backup.conf aus dem versionsgebundenen kanonischen Schema neu auf.
    Zulässige Updates werden übernommen, fehlende Schema-Keys ergänzt und
    unbekannte beziehungsweise obsolete Keys entfernt.
    Gibt True zurück, wenn sich der Dateiinhalt geändert hat.
    """
    conf_file = Path(ui_config["BACKUP_SCRIPTS_DIR"]) / "config" / "backup.conf"
    conf_file.parent.mkdir(parents=True, exist_ok=True)

    config_dir = conf_file.parent
    with inventory_lock(config_dir):
        old_content = conf_file.read_text(encoding="utf-8") if conf_file.exists() else ""
        plan = canonical_backup_conf_plan(ui_config, source_content=old_content, updates=updates)
        if plan["changed"]:
            if snapshot_reason:
                backup_conf_snapshot(ui_config, keep=10, reason=snapshot_reason)
            atomic_write_bytes(conf_file, plan["content"].encode("utf-8"))
        return bool(plan["changed"])


# ── Repositories ──────────────────────────────────────────────────────────────

def get_repositories_data(ui_config: dict) -> dict:
    """
    Gibt die kanonischen Repository-Objekte gruppiert nach Location zurück.
    """
    groups: Dict[str, List[Dict]] = {"local": [], "usb": [], "smb": [], "storagebox": []}
    repository_info_refresh: Dict[str, object] = {}
    try:
        from repositories_api import build_repository_groups
        from storage_objects_api import read_storage_store
        groups = build_repository_groups(ui_config)
        storages = read_storage_store(ui_config).get("storages", [])
    except Exception:
        storages = []
    try:
        from repositories_api import get_repository_info_refresh_status
        repository_info_refresh = get_repository_info_refresh_status(ui_config)
    except Exception:
        repository_info_refresh = {}

    # Sortierung innerhalb Gruppen
    type_order = {}
    for i, t in enumerate(BACKUP_TYPES):
        type_order[t] = i
        type_order[t.lower()] = i
    for loc in groups:
        groups[loc].sort(key=lambda r: type_order.get(r["backup_type"], 99))

    return {
        "groups": groups,
        "storages": storages,
        "repository_info_refresh": repository_info_refresh,
        "smb_profiles": get_smb_profiles_with_status(ui_config),
        "conf_file": str(get_conf_file(ui_config)),
        "conf_writable": conf_exists(ui_config),
    }


def test_repository(ui_config: dict, repository_key: str) -> dict:
    """Run borg info for one canonical repository object."""
    from repository_context import repository_by_key, repository_path, storage_by_key

    key = str(repository_key or "").strip()
    if not key:
        raise ValueError("repository_key is required")
    repository = repository_by_key(ui_config, key)
    storage = storage_by_key(ui_config, str(repository.get("storage_key") or ""))
    resolved_path = repository_path(repository, storage)
    passphrase_ref = str(repository.get("passphrase_ref") or "").strip()

    from repositories_api import _repo_env

    passphrase_file = Path(passphrase_ref) if passphrase_ref else None
    if str(repository.get("encryption") or "").strip().lower() != "none":
        if passphrase_file is None or not passphrase_file.is_file():
            raise ValueError("Repository passphrase file is missing")
    env = _repo_env(
        storage,
        passphrase_file,
        ui_config,
        encryption=str(repository.get("encryption") or ""),
    )

    try:
        result = subprocess.run(
            ["borg", "info", "--json", resolved_path],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
        output = mask_secrets((result.stdout or "") + (result.stderr or ""))
        return {"success": result.returncode == 0, "output": output[:2000], "exit_code": result.returncode}
    except FileNotFoundError:
        return {"success": False, "output": "borg binary not found.", "exit_code": -1}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "Timeout (20s) - repository unreachable.", "exit_code": -1}
    except Exception as exc:
        return {"success": False, "output": mask_secrets(str(exc)), "exit_code": -1}


def _resolve_storage_profile(ui_config: dict, profile_key: str = "") -> dict:
    return resolve_storage_profile(ui_config, profile_key)


def get_storagebox_setup_status(ui_config: dict, profile_key: str = "", *, probe_auth: bool = True) -> dict:
    from storagebox_api import get_storagebox_setup_status as _get_storagebox_setup_status
    return _get_storagebox_setup_status(ui_config, profile_key=profile_key, probe_auth=probe_auth)


def storagebox_key_status(ui_config: dict, profile_key: str = "") -> dict:
    from storagebox_api import storagebox_key_status as _storagebox_key_status
    return _storagebox_key_status(ui_config, profile_key=profile_key)


def storagebox_key_generate(ui_config: dict, profile_key: str = "") -> dict:
    from storagebox_api import storagebox_key_generate as _storagebox_key_generate
    return _storagebox_key_generate(ui_config, profile_key=profile_key)


def storagebox_key_public(ui_config: dict, profile_key: str = "") -> dict:
    from storagebox_api import storagebox_key_public as _storagebox_key_public
    return _storagebox_key_public(ui_config, profile_key=profile_key)


def storagebox_key_deploy(ui_config: dict, password: str, profile_key: str = "") -> dict:
    from storagebox_api import storagebox_key_deploy as _storagebox_key_deploy
    return _storagebox_key_deploy(ui_config, password, profile_key=profile_key)


def storagebox_connection_test(ui_config: dict, profile_key: str = "") -> dict:
    from storagebox_api import storagebox_connection_test as _storagebox_connection_test
    return _storagebox_connection_test(ui_config, profile_key=profile_key)


def storagebox_deploy_start(ui_config: dict, target_override: str = "", profile_key: str = "") -> Dict[str, Any]:
    from storagebox_api import storagebox_deploy_start as _storagebox_deploy_start
    return _storagebox_deploy_start(ui_config, target_override=target_override, profile_key=profile_key)


def storagebox_deploy_input(session_id: str, text: str) -> Dict[str, Any]:
    from storagebox_api import storagebox_deploy_input as _storagebox_deploy_input
    return _storagebox_deploy_input(session_id, text)


def storagebox_deploy_cancel(session_id: str) -> Dict[str, Any]:
    from storagebox_api import storagebox_deploy_cancel as _storagebox_deploy_cancel
    return _storagebox_deploy_cancel(session_id)


def storagebox_deploy_state(session_id: str) -> Dict[str, Any]:
    from storagebox_api import storagebox_deploy_state as _storagebox_deploy_state
    return _storagebox_deploy_state(session_id)


# ── Settings ──────────────────────────────────────────────────────────────────

_SECRETS_DIR = Path("/boot/config/borg-backup/secrets")


def _scan_per_repo_passphrases() -> list:
    """Listet alle per-Repo Passphrase-Dateien in /boot/config/borg-backup/secrets/."""
    result = []
    if not _SECRETS_DIR.is_dir():
        return result
    for f in sorted(_SECRETS_DIR.glob(".borg-passphrase-*")):
        if not f.is_file():
            continue
        type_id = f.name.replace(".borg-passphrase-", "", 1)
        st = f.stat()
        result.append({
            "type_id":   type_id,
            "filename":  f.name,
            "path":      str(f),
            "size":      st.st_size,
            "mtime":     int(st.st_mtime),
        })
    return result


def send_test_email(ui_config: dict, recipient: str = "") -> dict:
    from smtp_api import send_test_email as _send_test_email
    return _send_test_email(ui_config, recipient)


def get_settings_data(ui_config: dict, include_storagebox_setup: bool = True) -> dict:
    """Gibt strukturierte Settings-Daten für die UI zurück."""
    conf = read_expanded_conf(ui_config)

    data = {
        "conf_file": str(get_conf_file(ui_config)),
        "conf_writable": conf_exists(ui_config),
        "general": {
            "GLOBAL_DATA_DIR":            conf.get("GLOBAL_DATA_DIR", ""),
            "GLOBAL_DATA_DIR_SUGGESTION": "/mnt/user/borg-backup-ui",
            "GLOBAL_LOG_DIR":             conf.get("GLOBAL_LOG_DIR", ""),
            "STATUS_DIR":                 conf.get("STATUS_DIR", ui_config.get("STATUS_DIR", "")),
            "RESTORE_TEST_STATUS_DIR":    conf.get("RESTORE_TEST_STATUS_DIR", ""),
            "GLOBAL_LOG_RETENTION_DAYS":  conf.get("GLOBAL_LOG_RETENTION_DAYS", "30"),
            "GLOBAL_BORG_CACHE_BASE":     conf.get("GLOBAL_BORG_CACHE_BASE", "/mnt/cache/borg-cache"),
            "GLOBAL_BORG_CHECK_INTERVAL_DAYS": conf.get("GLOBAL_BORG_CHECK_INTERVAL_DAYS", "30"),
            "BORG_MAX_RUNTIME_HOURS":     conf.get("BORG_MAX_RUNTIME_HOURS", "0"),
            "ABORT_ON_PARITY_CHECK":      conf.get("ABORT_ON_PARITY_CHECK", "true"),
        },
        "repository_info_refresh": {},
        "smtp": {
            "GLOBAL_MAIL_RECIPIENT":  conf.get("GLOBAL_MAIL_RECIPIENT", ""),
            "GLOBAL_MAIL_SENDER":     conf.get("GLOBAL_MAIL_SENDER", ""),
            "GLOBAL_SMTP_HOST":       conf.get("GLOBAL_SMTP_HOST", ""),
            "GLOBAL_SMTP_PORT":       conf.get("GLOBAL_SMTP_PORT", "587"),
            "GLOBAL_SMTP_USER":       conf.get("GLOBAL_SMTP_USER", ""),
            "GLOBAL_SMTP_PASSWORD":   "",
            "GLOBAL_SMTP_PASSWORD_SET": "true" if str(conf.get("GLOBAL_SMTP_PASSWORD", "")).strip() else "false",
            "GLOBAL_SMTP_USE_TLS":    conf.get("GLOBAL_SMTP_USE_TLS", "true"),
            "NOTIFY_EMAIL_EVENTS":    conf.get("NOTIFY_EMAIL_EVENTS", "backup_failed"),
        },
        "unraid_notifications": {
            "NOTIFY_UNRAID_EVENTS": conf.get("NOTIFY_UNRAID_EVENTS", "backup_success,backup_warning,backup_failed,backup_skipped"),
            "NOTIFY_REMINDER_INTERVAL_HOURS": conf.get("NOTIFY_REMINDER_INTERVAL_HOURS", "24"),
            "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": conf.get("NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS", "6"),
        },
        "per_repo_passphrases": _scan_per_repo_passphrases(),
        "docker": {
            "DOCKER_STOP_TIMEOUT": conf.get("DOCKER_STOP_TIMEOUT", "60"),
            "DOCKER_STOP_WAIT":    conf.get("DOCKER_STOP_WAIT", "5"),
            "DOCKER_START_WAIT":   conf.get("DOCKER_START_WAIT", "5"),
        },
        "vms": {
            "VM_SHUTDOWN_TIMEOUT":         conf.get("VM_SHUTDOWN_TIMEOUT", "120"),
            "VM_SHUTDOWN_WARNING_MINUTES": conf.get("VM_SHUTDOWN_WARNING_MINUTES", "5"),
            "VM_STARTUP_WAIT":             conf.get("VM_STARTUP_WAIT", "60"),
        },
        "restore_tests": {
            "RESTORE_TEST_LEVEL":         conf.get("RESTORE_TEST_LEVEL", "2"),
            "RESTORE_TEST_INTERVAL_DAYS": conf.get("RESTORE_TEST_INTERVAL_DAYS", "30"),
            "RESTORE_TEST_LOCATION":      conf.get("RESTORE_TEST_LOCATION", "local"),
            "RESTORE_TEST_FORCE_CHUNK_TYPES": conf.get("RESTORE_TEST_FORCE_CHUNK_TYPES", "vms,photos"),
            "RESTORE_TEST_FULL_DRYRUN_MAX_ARCHIVE_GB": conf.get("RESTORE_TEST_FULL_DRYRUN_MAX_ARCHIVE_GB", "500"),
            "RESTORE_TEST_MIN_COVERAGE": conf.get("RESTORE_TEST_MIN_COVERAGE", "5"),
            "RESTORE_TEST_MAX_ENTRIES": conf.get("RESTORE_TEST_MAX_ENTRIES", "1000"),
            "RESTORE_TEST_SAMPLE_SIZE": conf.get("RESTORE_TEST_SAMPLE_SIZE", "5"),
            "RESTORE_TEST_BORG_TIMEOUT": conf.get("RESTORE_TEST_BORG_TIMEOUT", "240"),
            "RESTORE_TEST_DRY_RUN_TIMEOUT": conf.get("RESTORE_TEST_DRY_RUN_TIMEOUT", "0"),
            "RESTORE_TEST_DRY_RUN_CHUNK_SIZE": conf.get("RESTORE_TEST_DRY_RUN_CHUNK_SIZE", "100"),
            "RESTORE_TEST_DRY_RUN_MAX_FILES": conf.get("RESTORE_TEST_DRY_RUN_MAX_FILES", "1000"),
            "RESTORE_TEST_LEVEL3_LEGACY_SAMPLING": conf.get("RESTORE_TEST_LEVEL3_LEGACY_SAMPLING", "false"),
        },
        "restore_browse": {
            "RESTORE_ALLOWED_ROOTS": conf.get("RESTORE_ALLOWED_ROOTS", "/mnt/user"),
        },
        "weekly_report": {
            "WEEKLY_REPORT_ENABLED":   conf.get("WEEKLY_REPORT_ENABLED", "false"),
            "WEEKLY_REPORT_DAY":       conf.get("WEEKLY_REPORT_DAY", "1"),
            "WEEKLY_REPORT_TIME":      conf.get("WEEKLY_REPORT_TIME", "09:00"),
            "WEEKLY_REPORT_RECIPIENT": conf.get("WEEKLY_REPORT_RECIPIENT", conf.get("GLOBAL_MAIL_RECIPIENT", "")),
        },
        "security": {
            "UI_LOGIN_PASSWORD_SET": "true" if str(conf.get("UI_LOGIN_PASSWORD", "")).strip() else "false",
            "UI_SESSION_TIMEOUT_MINUTES": conf.get("UI_SESSION_TIMEOUT_MINUTES", "30"),
        },
        "storagebox_setup": {},
    }
    if include_storagebox_setup:
        # Normal settings reads must never wait for a remote SSH probe. Explicit
        # connection tests remain available through the storage profile actions.
        data["storagebox_setup"] = get_storagebox_setup_status(ui_config, probe_auth=False)
    from storage_objects_api import settings_profiles_from_storages
    canonical_profiles = settings_profiles_from_storages(ui_config)
    from repositories_api import read_repository_store
    from repositories_api import get_repository_info_refresh_status
    data["repository_info_refresh"] = get_repository_info_refresh_status(ui_config)
    repository_rows = read_repository_store(ui_config).get("repositories", [])
    refs_by_storage: Dict[str, List[str]] = {}
    repositories_by_storage: Dict[str, List[str]] = {}
    for repository in repository_rows:
        storage_key = str(repository.get("storage_key") or "")
        if storage_key:
            label = str(repository.get("display_name") or repository.get("repository_key") or storage_key).strip()
            repositories_by_storage.setdefault(storage_key, []).append(label)
        refs = [str(value) for value in repository.get("used_by", []) if str(value)]
        refs_by_storage.setdefault(storage_key, []).extend(refs)
    data["local_profiles"] = [
        {
            **row,
            "jobs_count": len(set(refs_by_storage.get(str(row.get("storage_key") or ""), []))),
            "job_refs": sorted(set(refs_by_storage.get(str(row.get("storage_key") or ""), [])))[:10],
            "repositories_count": len(set(repositories_by_storage.get(str(row.get("storage_key") or ""), []))),
            "repository_refs": sorted(set(repositories_by_storage.get(str(row.get("storage_key") or ""), [])))[:10],
        }
        for row in canonical_profiles.get("local_profiles", [])
    ]
    usb_storage_keys = {
        str(row.get("key") or "").strip().lower(): str(row.get("storage_key") or "")
        for row in canonical_profiles.get("usb_profiles", [])
    }
    data["usb_profiles"] = _normalize_usb_profile_rows(canonical_profiles.get("usb_profiles", []))
    data["usb_profiles"] = [
        {
            **row,
            "storage_key": usb_storage_keys.get(str(row.get("key") or "").strip().lower(), ""),
            "jobs_count": len(set(refs_by_storage.get(usb_storage_keys.get(str(row.get("key") or "").strip().lower(), ""), []))),
            "job_refs": sorted(set(refs_by_storage.get(usb_storage_keys.get(str(row.get("key") or "").strip().lower(), ""), [])))[:10],
            "repositories_count": len(set(repositories_by_storage.get(usb_storage_keys.get(str(row.get("key") or "").strip().lower(), ""), []))),
            "repository_refs": sorted(set(repositories_by_storage.get(usb_storage_keys.get(str(row.get("key") or "").strip().lower(), ""), [])))[:10],
        }
        for row in data["usb_profiles"]
    ]
    ssh_storage_keys = {
        str(row.get("key") or "").strip().lower(): str(row.get("storage_key") or "")
        for row in canonical_profiles.get("storage_profiles", [])
    }
    data["storage_profiles"] = _normalize_storage_profile_rows(canonical_profiles.get("storage_profiles", []))
    data["storage_profiles"] = [
        {
            **row,
            "storage_key": ssh_storage_keys.get(str(row.get("key") or "").strip().lower(), ""),
            "jobs_count": len(set(refs_by_storage.get(ssh_storage_keys.get(str(row.get("key") or "").strip().lower(), ""), []))),
            "job_refs": sorted(set(refs_by_storage.get(ssh_storage_keys.get(str(row.get("key") or "").strip().lower(), ""), [])))[:10],
            "repositories_count": len(set(repositories_by_storage.get(ssh_storage_keys.get(str(row.get("key") or "").strip().lower(), ""), []))),
            "repository_refs": sorted(set(repositories_by_storage.get(ssh_storage_keys.get(str(row.get("key") or "").strip().lower(), ""), [])))[:10],
        }
        for row in data["storage_profiles"]
    ]
    smb_profiles: List[Dict[str, str]] = []
    smb_storage_keys = {
        str(row.get("key") or "").strip().lower(): str(row.get("storage_key") or "")
        for row in canonical_profiles.get("smb_profiles", [])
    }
    try:
        raw_rows = normalize_smb_profile_rows(
            canonical_profiles.get("smb_profiles", [])
        )
        smb_profiles = []
        for row in raw_rows:
            pf = str(row.get("password_file", "")).strip()
            key = str(row.get("key", "")).strip()
            storage_key = smb_storage_keys.get(key.lower(), "")
            refs = sorted(set(refs_by_storage.get(storage_key, [])))
            repository_refs = sorted(set(repositories_by_storage.get(storage_key, [])))
            smb_profiles.append({
                "key": key,
                "storage_key": storage_key,
                "name": str(row.get("name", "")).strip(),
                "server": str(row.get("server", "")).strip(),
                "share": str(row.get("share", "")).strip(),
                "mount_path": str(row.get("mount_path", "")).strip(),
                "username": str(row.get("username", "")).strip(),
                "vers": str(row.get("vers", "")).strip() or "auto",
                "sec": str(row.get("sec", "")).strip(),
                "password_set": bool(pf and Path(pf).is_file()),
                "jobs_count": len(refs),
                "job_refs": refs[:10],
                "repositories_count": len(repository_refs),
                "repository_refs": repository_refs[:10],
            })
    except ValueError:
        smb_profiles = []
    data["smb_profiles"] = smb_profiles
    return data


def get_setup_status(ui_config: dict) -> dict:
    """
    Schlanker Setup-Status für Navigation/Gates ohne teure Storagebox-Checks.
    """
    conf = read_expanded_conf(ui_config)
    data_dir = str(conf.get("GLOBAL_DATA_DIR", "")).strip()
    validation = validate_runtime_config(ui_config)
    counts = get_setup_milestone_counts(ui_config)
    milestones = [
        {
            "key": "data_dir",
            "required": True,
            "complete": bool(data_dir) and bool(validation.get("ok", False)),
            "count": 1 if data_dir else 0,
        },
        {
            "key": "storage",
            "required": False,
            "complete": counts["storage_count"] > 0,
            "count": counts["storage_count"],
        },
        {
            "key": "repository",
            "required": False,
            "complete": counts["repository_count"] > 0,
            "count": counts["repository_count"],
        },
        {
            "key": "job",
            "required": False,
            "complete": counts["job_count"] > 0,
            "count": counts["job_count"],
        },
    ]
    missing_optional = [
        item["key"]
        for item in milestones
        if not item["required"] and not item["complete"]
    ]
    wizard_state = read_setup_wizard_state(ui_config)
    ready = bool(validation.get("ok", False))
    optional_incomplete = ready and bool(missing_optional)
    return {
        "global_data_dir_set": bool(data_dir),
        "global_data_dir": data_dir,
        "global_data_dir_suggestion": "/mnt/user/borg-backup-ui",
        "ready": ready,
        "validation": validation,
        "setup": {
            "counts": counts,
            "milestones": milestones,
            "required": not bool(data_dir),
            "optional_incomplete": optional_incomplete,
            "missing_optional": missing_optional,
            "optional_dismissed": bool(wizard_state.get("optional_dismissed_at")),
            "show_optional_wizard": optional_incomplete and not bool(wizard_state.get("optional_dismissed_at")),
            "complete": ready and not missing_optional,
            "wizard_state": wizard_state,
        },
    }


def get_setup_milestone_counts(ui_config: dict) -> dict:
    counts = {
        "storage_count": 0,
        "repository_count": 0,
        "job_count": 0,
    }
    try:
        from storage_objects_api import read_storage_store

        rows = read_storage_store(ui_config).get("storages", [])
        counts["storage_count"] = len([row for row in rows if str(row.get("storage_key") or "").strip()])
    except Exception:
        counts["storage_count"] = 0
    try:
        from repositories_api import read_repository_store

        rows = read_repository_store(ui_config).get("repositories", [])
        counts["repository_count"] = len([row for row in rows if str(row.get("repository_key") or "").strip()])
    except Exception:
        counts["repository_count"] = 0
    try:
        from jobs_api import list_jobs

        rows = list_jobs(ui_config, {})
        counts["job_count"] = len([row for row in rows if not row.get("is_utility")])
    except Exception:
        counts["job_count"] = 0
    return counts


def setup_wizard_state_file(ui_config: dict) -> Path:
    raw = str(ui_config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    root = Path(raw)
    data_root = root.parent if root.name == "scripts" else root
    return data_root / "config" / "setup-wizard-state.json"


def read_setup_wizard_state(ui_config: dict) -> dict:
    path = setup_wizard_state_file(ui_config)
    try:
        if not path.exists():
            return {"schema_version": 1}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"schema_version": 1}
        return {"schema_version": 1, **data}
    except Exception:
        return {"schema_version": 1}


def update_setup_wizard_state(ui_config: dict, action: str) -> dict:
    clean_action = str(action or "").strip().lower()
    if clean_action not in {"dismiss_optional", "reset"}:
        raise ValueError("Unsupported setup wizard action")
    path = setup_wizard_state_file(ui_config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with inventory_lock(path.parent):
        state = read_setup_wizard_state(ui_config)
        if clean_action == "dismiss_optional":
            state["optional_dismissed_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        elif clean_action == "reset":
            state.pop("optional_dismissed_at", None)
        state["schema_version"] = 1
        atomic_write_bytes(path, (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        return state


def derive_data_dirs(global_data_dir: str) -> dict:
    base = Path((global_data_dir or "").strip())
    return {
        "base": str(base),
        "logs": str(base / "logs"),
        "status": str(base / "status"),
        "restore_status": str(base / "restore-status"),
        "cache": str(base / "cache"),
        "remotes": str(base / "remotes"),
    }


def ensure_data_dirs(global_data_dir: str) -> dict:
    root = (global_data_dir or "").strip()
    if not root:
        raise ValueError("GLOBAL_DATA_DIR is not set")
    # Unraid-spezifischer Guard:
    # /mnt/user darf erst beschrieben werden, wenn das Array gestartet ist.
    if root == "/mnt/user" or root.startswith("/mnt/user/"):
        if not _is_unraid_array_started():
            raise RuntimeError("The Unraid array has not started yet (/mnt/user is unavailable)")
    paths = derive_data_dirs(root)
    created = []
    for key in ("base", "logs", "status", "restore_status", "cache", "remotes"):
        p = Path(paths[key])
        p.mkdir(parents=True, exist_ok=True)
        created.append(str(p))
    # write test in status dir
    probe = Path(paths["status"]) / ".borg-ui-write-test"
    probe.write_text("ok\n", encoding="utf-8")
    probe.unlink(missing_ok=True)
    return {"ok": True, "paths": paths, "created": created}


def _as_int(v: str, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _is_safe_restore_root_value(raw: str) -> bool:
    path = str(raw or "").strip().rstrip("/") or "/"
    if path in {"/", "/mnt", "/mnt/disks", "/mnt/remotes", "/boot", "/etc", "/usr", "/var"}:
        return False
    if path == "/mnt/user" or path.startswith("/mnt/user/"):
        return True
    if path == "/mnt/data" or path.startswith("/mnt/data/"):
        return True
    if re.fullmatch(r"/mnt/disk[0-9]+(?:/.*)?", path):
        return True
    if re.fullmatch(r"/mnt/disks/[^/]+(?:/.*)?", path):
        return True
    if re.fullmatch(r"/mnt/remotes/[^/]+(?:/.*)?", path):
        return True
    return False


def validate_runtime_config(ui_config: dict) -> dict:
    """
    Validiert zentrale Runtime-Konfiguration ohne harte Abbrüche.
    Ergebnis enthält klare Fehler/Warnungen für UI und Gates.
    """
    conf = read_expanded_conf(ui_config)
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    data_dir = str(conf.get("GLOBAL_DATA_DIR", "")).strip()
    if not data_dir:
        errors.append({
            "key": "GLOBAL_DATA_DIR",
            "message": "GLOBAL_DATA_DIR is not set.",
            "message_code": "config_data_dir_missing",
        })
    else:
        if not data_dir.startswith("/"):
            errors.append({
                "key": "GLOBAL_DATA_DIR",
                "message": "GLOBAL_DATA_DIR must be an absolute path (for example /mnt/user/borg-backup-ui).",
                "message_code": "config_data_dir_absolute",
            })
        elif data_dir == "/":
            errors.append({
                "key": "GLOBAL_DATA_DIR",
                "message": "GLOBAL_DATA_DIR must not be '/'.",
                "message_code": "config_data_dir_root",
            })
        else:
            try:
                ensure_data_dirs(data_dir)
            except Exception as exc:
                errors.append({
                    "key": "GLOBAL_DATA_DIR",
                    "message": f"GLOBAL_DATA_DIR is not usable: {exc}",
                    "message_code": "config_data_dir_unusable",
                })

    smtp_port = _as_int(conf.get("GLOBAL_SMTP_PORT", "587"), -1)
    if smtp_port < 1 or smtp_port > 65535:
        warnings.append({
            "key": "GLOBAL_SMTP_PORT",
            "message": "GLOBAL_SMTP_PORT is outside 1..65535.",
            "message_code": "config_smtp_port",
        })

    rt_level = str(conf.get("RESTORE_TEST_LEVEL", "2")).strip()
    if rt_level not in {"1", "2", "3"}:
        warnings.append({
            "key": "RESTORE_TEST_LEVEL",
            "message": "RESTORE_TEST_LEVEL should be 1, 2, or 3.",
            "message_code": "config_restore_test_level",
        })

    restore_roots = [
        str(item or "").strip()
        for item in str(conf.get("RESTORE_ALLOWED_ROOTS", "/mnt/user") or "/mnt/user").split(",")
        if str(item or "").strip()
    ]
    invalid_restore_roots = [root for root in restore_roots if not _is_safe_restore_root_value(root)]
    if invalid_restore_roots:
        warnings.append({
            "key": "RESTORE_ALLOWED_ROOTS",
            "message": "RESTORE_ALLOWED_ROOTS contains unsafe or too broad restore target roots.",
            "message_code": "config_restore_allowed_roots",
            "message_params": {"paths": ", ".join(invalid_restore_roots)},
        })

    for key in (
        "GLOBAL_LOG_RETENTION_DAYS",
        "GLOBAL_BORG_CHECKPOINT_INTERVAL",
        "GLOBAL_BORG_CHECK_INTERVAL_DAYS",
        "BORG_MAX_RUNTIME_HOURS",
        "RESTORE_TEST_INTERVAL_DAYS",
        "RESTORE_TEST_BORG_TIMEOUT",
        "RESTORE_TEST_DRY_RUN_TIMEOUT",
        "RESTORE_TEST_DRY_RUN_CHUNK_SIZE",
        "RESTORE_TEST_DRY_RUN_MAX_FILES",
        "DOCKER_STOP_TIMEOUT",
        "DOCKER_STOP_WAIT",
        "DOCKER_START_WAIT",
        "VM_SHUTDOWN_TIMEOUT",
        "VM_SHUTDOWN_WARNING_MINUTES",
        "VM_STARTUP_WAIT",
    ):
        val = _as_int(conf.get(key, "0"), -1)
        if val < 0:
            warnings.append({
                "key": key,
                "message": f"{key} should be a non-negative integer.",
                "message_code": "config_non_negative_integer",
                "message_params": {"key": key},
            })

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
    }
