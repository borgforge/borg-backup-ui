"""Persistent Borg keyfile handling for the Unraid plugin.

Unraid's default Borg key directory lives below ``/root`` and is not a
persistent plugin data location.  All Borg processes therefore use the
plugin-owned key directory managed here.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable


KEYFILE_ENCRYPTION_MODES = {"keyfile", "keyfile-blake2"}


def data_root(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip()
    base = Path(raw or "/boot/config/borg-backup")
    return base.parent if base.name == "scripts" else base


def borg_keys_dir(config: dict) -> Path:
    return data_root(config) / "secrets" / "borg-keys"


def ensure_borg_keys_dir(config: dict) -> Path:
    path = borg_keys_dir(config)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def apply_borg_key_environment(env: dict[str, str], config: dict) -> dict[str, str]:
    """Set the canonical persistent key directory on a Borg environment."""
    out = dict(env)
    out["BORG_KEYS_DIR"] = str(ensure_borg_keys_dir(config))
    return out


def is_keyfile_encryption(mode: object) -> bool:
    return str(mode or "").strip().lower() in KEYFILE_ENCRYPTION_MODES


def repository_id_from_key_file(path: Path) -> str:
    """Read the repository ID from a Borg key file without exposing its body."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            return ""
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            first = handle.readline().strip()
    except OSError:
        return ""
    prefix = "BORG_KEY "
    if not first.startswith(prefix):
        return ""
    value = first[len(prefix):].strip().lower()
    return value if value and all(ch in "0123456789abcdef" for ch in value) else ""


def find_key_file(directory: Path, repository_id: str) -> Path | None:
    expected = str(repository_id or "").strip().lower()
    if not expected or not directory.is_dir():
        return None
    try:
        candidates = sorted(directory.iterdir())
    except OSError:
        return None
    for candidate in candidates:
        if repository_id_from_key_file(candidate) == expected:
            return candidate
    return None


def import_default_key_if_present(config: dict, repository_id: str) -> Path | None:
    """Copy only the exact matching legacy Borg key into persistent storage.

    Existing persistent files are never overwritten and unrelated files in
    Borg's default key directory are never copied.
    """
    target_dir = ensure_borg_keys_dir(config)
    current = find_key_file(target_dir, repository_id)
    if current is not None:
        os.chmod(current, 0o600)
        return current
    source = find_key_file(Path.home() / ".config" / "borg" / "keys", repository_id)
    if source is None:
        return None
    target = target_dir / source.name
    try:
        with source.open("rb") as src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        os.chmod(target, 0o600)
    except FileExistsError:
        return find_key_file(target_dir, repository_id)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def remove_repository_key(
    config: dict,
    repository_id: str,
    remaining_repository_ids: Iterable[str],
) -> bool:
    """Remove the exact persistent key only when no inventory object uses it."""
    expected = str(repository_id or "").strip().lower()
    if not expected:
        return False
    if expected in {str(item or "").strip().lower() for item in remaining_repository_ids}:
        return False
    candidate = find_key_file(ensure_borg_keys_dir(config), expected)
    if candidate is None:
        return False
    candidate.unlink()
    return True
