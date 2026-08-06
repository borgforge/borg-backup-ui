"""Persistent runtime recovery state for Docker/VM stop-start handling."""

from __future__ import annotations

import json
import fcntl
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


_SCHEMA_VERSION = 1


def runtime_recovery_file_from_env(env: dict[str, Any]) -> Path:
    explicit = str(env.get("RUNTIME_RECOVERY_FILE") or "").strip()
    if explicit:
        return Path(explicit)
    root = str(env.get("BACKUP_SCRIPTS_DIR") or "/boot/config/borg-backup").strip() or "/boot/config/borg-backup"
    base = Path(root)
    if base.name == "scripts":
        base = base.parent
    return base / "config" / "runtime-recovery.json"


def read_runtime_recovery_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {
            **_empty_state(),
            "read_error": "Runtime recovery state is not readable.",
        }
    if not isinstance(raw, dict):
        return _empty_state()
    entries = raw.get("entries") if isinstance(raw.get("entries"), list) else []
    return {
        "schema_version": int(raw.get("schema_version") or _SCHEMA_VERSION),
        "updated_at": str(raw.get("updated_at") or ""),
        "entries": [entry for entry in entries if isinstance(entry, dict)],
    }


def pending_runtime_recovery_entries(path: Path) -> list[dict[str, Any]]:
    state = read_runtime_recovery_state(path)
    return [
        entry for entry in state.get("entries", [])
        if str(entry.get("state") or "").strip() in {"pending_restart", "restart_failed"}
    ]


def record_runtime_stopped(
    path: Path,
    *,
    kind: str,
    targets: list[dict[str, str]],
    job_name: str,
    backup_type: str,
    backup_location: str,
    log_file: str,
) -> str:
    normalized_targets = _normalize_targets(targets)
    if not normalized_targets:
        return ""
    entry_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    entry = {
        "id": entry_id,
        "state": "pending_restart",
        "kind": str(kind or "").strip(),
        "job_name": str(job_name or "").strip(),
        "backup_type": str(backup_type or "").strip(),
        "backup_location": str(backup_location or "").strip(),
        "log_file": str(log_file or "").strip(),
        "pid": os.getpid(),
        "stopped_at": _now(),
        "restarted_at": "",
        "message": "Runtime targets were stopped by Borg Backup UI and have not been marked as restarted.",
        "targets": normalized_targets,
    }

    def _mutate(state: dict[str, Any]) -> tuple[str, bool]:
        entries = [e for e in state.get("entries", []) if isinstance(e, dict)]
        entries.append(entry)
        state["entries"] = _prune_completed(entries)
        return entry_id, True

    return str(_mutate_state(path, _mutate))


def mark_runtime_restarted(path: Path, entry_id: str, *, success: bool = True, message: str = "") -> None:
    if not entry_id:
        return

    def _mutate(state: dict[str, Any]) -> tuple[None, bool]:
        changed = False
        entries = [entry for entry in state.get("entries", []) if isinstance(entry, dict)]
        remaining: list[dict[str, Any]] = []
        for entry in entries:
            if str(entry.get("id") or "") != entry_id:
                remaining.append(entry)
                continue
            if success:
                changed = True
                continue
            entry["state"] = "restart_failed"
            entry["restarted_at"] = _now()
            entry["message"] = str(message or "Runtime restart failed.")
            remaining.append(entry)
            changed = True
        if changed:
            state["entries"] = _open_entries(remaining)
        return None, changed

    _mutate_state(path, _mutate)


def acknowledge_runtime_recovery(path: Path, entry_id: str) -> bool:
    clean_id = str(entry_id or "").strip()
    if not clean_id:
        return False

    def _mutate(state: dict[str, Any]) -> tuple[bool, bool]:
        entries = [entry for entry in state.get("entries", []) if isinstance(entry, dict)]
        remaining = [entry for entry in entries if str(entry.get("id") or "") != clean_id]
        if len(remaining) == len(entries):
            return False, False
        state["entries"] = _open_entries(remaining)
        return True, True

    return bool(_mutate_state(path, _mutate))


def summarize_runtime_recovery(path: Path) -> dict[str, Any]:
    state = read_runtime_recovery_state(path)
    pending = pending_runtime_recovery_entries(path)
    attention = [e for e in pending if _entry_needs_attention(e)]
    active = [e for e in pending if e not in attention]
    docker_pending = [e for e in pending if str(e.get("kind") or "") == "docker"]
    vm_pending = [e for e in pending if str(e.get("kind") or "") == "vm"]
    docker_attention = [e for e in attention if str(e.get("kind") or "") == "docker"]
    vm_attention = [e for e in attention if str(e.get("kind") or "") == "vm"]
    return {
        "state_file": str(path),
        "pending_count": len(pending),
        "docker_pending_count": len(docker_pending),
        "vm_pending_count": len(vm_pending),
        "attention_count": len(attention),
        "docker_attention_count": len(docker_attention),
        "vm_attention_count": len(vm_attention),
        "active_count": len(active),
        "entries": attention,
        "active_entries": active,
        "updated_at": str(state.get("updated_at") or ""),
        "read_error": str(state.get("read_error") or ""),
    }


def _empty_state() -> dict[str, Any]:
    return {"schema_version": _SCHEMA_VERSION, "updated_at": "", "entries": []}


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _normalize_targets(targets: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen = set()
    for target in targets or []:
        if not isinstance(target, dict):
            continue
        ident = str(target.get("id") or target.get("name") or "").strip()
        name = str(target.get("name") or ident).strip()
        if not ident or ident in seen:
            continue
        seen.add(ident)
        out.append({"id": ident, "name": name})
    return out


def _prune_completed(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _open_entries(entries)


def _open_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if str(e.get("state") or "") in {"pending_restart", "restart_failed"}]


def _entry_needs_attention(entry: dict[str, Any]) -> bool:
    state = str(entry.get("state") or "").strip()
    if state == "restart_failed":
        return True
    if state != "pending_restart":
        return False
    pid = _safe_int(entry.get("pid"), 0)
    return pid <= 0 or not _pid_alive(pid)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _mutate_state(
    path: Path,
    mutate: Callable[[dict[str, Any]], tuple[Any, bool]],
) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            state = read_runtime_recovery_state(path)
            result, should_write = mutate(state)
            if should_write:
                _write_state_unlocked(path, state)
            return result
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            _write_state_unlocked(path, state)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _write_state_unlocked(path: Path, state: dict[str, Any]) -> None:
    state["schema_version"] = _SCHEMA_VERSION
    state["updated_at"] = _now()
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        tmp.replace(path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
