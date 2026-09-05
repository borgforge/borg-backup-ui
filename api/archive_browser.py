"""Shared read-only Borg archive directory browser."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


ARCHIVE_INDEX_CACHE_TTL_SECONDS = 300
ARCHIVE_INDEX_CACHE_MAX_ENTRIES = 8

_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()


def _prune_expired_cache_entries(now: float) -> None:
    expired = [key for key, value in _CACHE.items() if float(value.get("expires", 0)) <= now]
    for key in expired:
        _CACHE.pop(key, None)


def build_archive_index(repo: str, archive: str, env: dict[str, str]) -> dict[str, dict[str, dict[str, Any]]]:
    """Load and briefly cache a parent-to-children index for one archive."""
    key = (str(repo), str(archive))
    now = time.monotonic()
    with _CACHE_LOCK:
        _prune_expired_cache_entries(now)
        cached = _CACHE.pop(key, None)
        if cached:
            _CACHE[key] = cached
            return cached["index"]

    repo_archive = f"{repo}::{archive}"
    try:
        result = subprocess.run(
            ["borg", "list", "--json-lines", repo_archive],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("borg archive listing timed out") from exc
    if result.returncode != 0:
        raise RuntimeError(f"borg list failed: {result.stderr.strip()}")

    index: dict[str, dict[str, dict[str, Any]]] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError("borg list returned invalid archive data") from exc
        if not isinstance(item, dict):
            continue
        item_path = str(item.get("path") or "")
        if not item_path:
            continue
        path = Path(item_path)
        parent = str(path.parent) if str(path.parent) != "." else ""
        name = path.name
        if not name:
            continue
        index.setdefault(parent, {})[name] = {
            "name": name,
            "path": item_path,
            "type": item.get("type", "-"),
            "size": item.get("size", 0),
            "mtime": item.get("mtime", ""),
            "mode": item.get("mode", ""),
        }

    all_paths: set[str] = set()
    for parent, children in index.items():
        if parent:
            all_paths.add(parent)
        all_paths.update(str(child["path"]) for child in children.values())

    for item_path in all_paths:
        path = Path(item_path)
        while True:
            parent_path = path.parent
            parent = str(parent_path) if str(parent_path) != "." else ""
            name = path.name
            if not name:
                break
            if name not in index.setdefault(parent, {}):
                index[parent][name] = {
                    "name": name,
                    "path": str(path),
                    "type": "d",
                    "size": 0,
                    "mtime": "",
                    "mode": "",
                }
            if not parent:
                break
            path = parent_path

    with _CACHE_LOCK:
        _prune_expired_cache_entries(time.monotonic())
        _CACHE.pop(key, None)
        while len(_CACHE) >= ARCHIVE_INDEX_CACHE_MAX_ENTRIES:
            oldest = next(iter(_CACHE), None)
            if oldest is None:
                break
            _CACHE.pop(oldest, None)
        _CACHE[key] = {
            "expires": time.monotonic() + ARCHIVE_INDEX_CACHE_TTL_SECONDS,
            "index": index,
        }
    return index


def list_archive_directory(
    repo: str,
    archive: str,
    path: str,
    env: dict[str, str],
) -> list[dict[str, Any]]:
    """Return the direct children of one directory in a Borg archive."""
    index = build_archive_index(repo, archive, env)
    current = str(path or "").rstrip("/")
    children = list(index.get(current, {}).values())
    children.sort(key=lambda item: (0 if item["type"] == "d" else 1, str(item["name"]).lower()))
    return children
