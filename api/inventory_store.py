"""Durable persistence primitives for canonical inventory files."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class InventoryError(RuntimeError):
    """Base error for canonical inventory access."""


class InventoryCorruptError(InventoryError):
    """An existing inventory does not contain valid JSON data."""


class InventoryAccessError(InventoryError):
    """An inventory cannot be read or written safely."""


_thread_state = threading.local()
_process_locks: dict[str, threading.RLock] = {}
_process_locks_guard = threading.Lock()
_inventory_cache: dict[str, tuple[tuple[int, int, int], dict[str, Any]]] = {}
_inventory_cache_guard = threading.Lock()


def _inventory_signature(path: Path) -> tuple[int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    return (int(stat.st_mtime_ns), int(stat.st_size), int(stat.st_ino))


def read_cached_inventory(path: Path) -> dict[str, Any] | None:
    """Return a complete cached snapshot while the inventory file is unchanged."""
    source = Path(path)
    signature = _inventory_signature(source)
    if signature is None:
        return None
    with _inventory_cache_guard:
        cached = _inventory_cache.get(str(source))
        if cached is None or cached[0] != signature:
            return None
        return copy.deepcopy(cached[1])


def _cache_inventory(path: Path, payload: dict[str, Any]) -> None:
    signature = _inventory_signature(Path(path))
    if signature is None:
        return
    with _inventory_cache_guard:
        _inventory_cache[str(Path(path))] = (signature, copy.deepcopy(payload))


def _process_lock(path: Path) -> threading.RLock:
    key = str(path)
    with _process_locks_guard:
        lock = _process_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _process_locks[key] = lock
        return lock


@contextmanager
def inventory_lock(config_dir: Path) -> Iterator[None]:
    """Serialize canonical inventory transactions across threads and processes."""
    directory = Path(config_dir)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".inventory.lock"
    state = getattr(_thread_state, "inventory_locks", None)
    if state is None:
        state = {}
        _thread_state.inventory_locks = state
    key = str(lock_path)
    current = state.get(key)
    if current:
        current["depth"] += 1
        try:
            yield
        finally:
            current["depth"] -= 1
        return

    process_lock = _process_lock(lock_path)
    with process_lock:
        try:
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError as exc:
            raise InventoryAccessError(f"Cannot acquire inventory lock: {lock_path}") from exc
        state[key] = {"depth": 1, "fd": fd}
        try:
            yield
        finally:
            state.pop(key, None)
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def read_inventory(path: Path, *, collection_key: str, schema_version: int) -> dict[str, Any]:
    """Read one inventory and reject malformed existing content."""
    source = Path(path)
    if not source.exists():
        return {"schema_version": schema_version, "updated_at": "", collection_key: []}
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise InventoryAccessError(f"Inventory is not readable: {source}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InventoryCorruptError(
            f"Inventory contains malformed JSON: {source} (line {exc.lineno}, column {exc.colno})"
        ) from exc
    if not isinstance(payload, dict):
        raise InventoryCorruptError(f"Inventory root must be an object: {source}")
    rows = payload.get(collection_key)
    if not isinstance(rows, list):
        raise InventoryCorruptError(f"Inventory field '{collection_key}' must be a list: {source}")
    _cache_inventory(source, payload)
    return payload


def atomic_write_inventory(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON durably and replace the target only after a complete fsync."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        fd, raw_temp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
        temp_path = Path(raw_temp)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        temp_path = None
        os.chmod(target, 0o600)
        directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        _cache_inventory(target, payload)
    except OSError as exc:
        raise InventoryAccessError(f"Inventory could not be written atomically: {target}") from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def atomic_write_bytes(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    """Atomically replace an arbitrary protected data file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        fd, raw_temp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
        temp_path = Path(raw_temp)
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        temp_path = None
        os.chmod(target, mode)
        directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise InventoryAccessError(f"File could not be written atomically: {target}") from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def atomic_write_json(path: Path, payload: dict[str, Any], *, mode: int = 0o600) -> None:
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(path, content, mode=mode)
