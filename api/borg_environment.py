"""Canonical Borg storage and repository-scoped access settings (#498)."""

from __future__ import annotations

import os
from pathlib import Path

from borg_key_store import apply_borg_key_environment, data_root


UNKNOWN_UNENCRYPTED = "BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK"


def borg_security_dir(config: dict) -> Path:
    """Return the persistent plugin-owned Borg security directory."""
    return data_root(config) / "borg-security"


def legacy_security_dir() -> Path:
    """Resolve the former Borg 1.x location without creating it."""
    if "BORG_SECURITY_DIR" in os.environ:
        return Path(os.environ["BORG_SECURITY_DIR"])
    base = Path(os.environ.get("BORG_BASE_DIR") or Path.home())
    config_home = base / ".config"
    if not os.environ.get("BORG_BASE_DIR"):
        config_home = Path(os.environ.get("XDG_CONFIG_HOME") or config_home)
    return Path(os.environ.get("BORG_CONFIG_DIR") or config_home / "borg") / "security"


def ensure_borg_security_dir(config: dict) -> Path:
    """Validate writable security storage and create its directory if needed.

    Raises ValueError for a relative path and OSError for unavailable storage
    or a symbolic-link directory. Newly created directories use mode 0700.
    """
    try:
        from status import status_storage_unavailable_reason
    except ImportError:  # Standalone restore-test worker exposes runtime/lib as lib.
        from lib.status import status_storage_unavailable_reason

    path = borg_security_dir(config)
    if not path.is_absolute():
        raise ValueError("Borg security storage requires an absolute configuration path")
    reason = status_storage_unavailable_reason(path)
    if reason:
        raise OSError(f"Borg security storage unavailable: {reason}")
    if path.is_symlink():
        raise OSError(f"Borg security directory must not be a symbolic link: {path}")
    # Restrict newly created plugin-owned storage; do not chmod its ancestors.
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def apply_borg_environment(
    env: dict[str, str], config: dict, *, encryption: str = "", persistent_keys: bool = True,
) -> dict[str, str]:
    """Return an isolated Borg environment with persistent security state.

    Only explicitly unencrypted repositories get Borg's unknown-repository
    acknowledgment. ``persistent_keys`` additionally configures key storage;
    security-directory validation can raise ValueError or OSError.
    """
    out = dict(env)
    out["BORG_SECURITY_DIR"] = str(ensure_borg_security_dir(config))
    # Missing state can be acknowledged only for an explicitly unencrypted
    # managed repository, never merely because no passphrase was supplied.
    out.pop(UNKNOWN_UNENCRYPTED, None)
    if str(encryption or "").strip().lower() == "none":
        out[UNKNOWN_UNENCRYPTED] = "yes"
    if persistent_keys:
        out = apply_borg_key_environment(out, config)
    return out
