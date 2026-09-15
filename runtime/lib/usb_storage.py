"""Read-only USB storage validation shared by profile checks and backups (#516)."""

from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import re
import stat

from .status import required_storage_mount


@dataclass(frozen=True)
class Mount:
    path: Path
    filesystem: str
    read_only: bool


@dataclass
class UsbStorageStatus:
    code: str = "not_mounted"
    exists: bool = False
    is_dir: bool = False
    is_mounted: bool = False
    writable: bool = False
    detected_mount: str = ""

    @property
    def ok(self) -> bool:
        return self.code == "ok"


def _read_mounts() -> list[Mount]:
    # Kernel data, not /etc/mtab: handles bind mounts and Btrfs without relying
    # on device-number comparisons. No subprocess or writes to the USB drive.
    lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8", errors="surrogateescape").splitlines()
    mounts = []
    try:
        for line in lines:
            before, after = line.split(" - ", 1)
            fields, filesystem = before.split(), after.split()
            point = re.sub(r"\\(040|011|012|134)", lambda m: chr(int(m[1], 8)), fields[4])
            if not point.startswith("/"):
                raise ValueError("Non-absolute mount point")
            mounts.append(Mount(Path(point), filesystem[0],
                                "ro" in fields[5].split(",") or "ro" in filesystem[2].split(",")))
        if not mounts:
            raise ValueError("Empty mount table")
    except (ValueError, IndexError) as exc:
        raise OSError(errno.EIO, "Cannot interpret the kernel mount table") from exc
    return mounts


def _containing_mount(path: Path, mounts: list[Mount]) -> Mount | None:
    candidates = [mount for mount in mounts if path == mount.path or mount.path in path.parents]
    if not candidates:
        return None
    depth = max(len(mount.path.parts) for mount in candidates)
    deepest = [mount for mount in candidates if len(mount.path.parts) == depth]
    if len(deepest) != 1:
        raise OSError(errno.EBUSY, "Ambiguous stacked mounts for USB storage", str(path))
    return deepest[0]


def inspect_usb_storage(path: Path) -> UsbStorageStatus:
    """Accept a mount root or a directory on it; propagate real access errors.

    A directory left on Unraid's system filesystem is not an available drive.
    Symlinks within a mount are allowed, but cannot escape to another mount.
    This is a point-in-time preflight, not a guarantee against later unplugging.
    """
    result = UsbStorageStatus()
    if not path.is_absolute():
        result.code = "invalid_path"
        return result
    configured = Path(os.path.abspath(path))
    try:
        mode = configured.stat().st_mode
        result.exists = True
        result.is_dir = stat.S_ISDIR(mode)
        if not result.is_dir:
            result.code = "not_directory"
            return result
        resolved = configured.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        result.code = "not_found"
        return result

    mounts = _read_mounts()
    mount = _containing_mount(resolved, mounts)
    if mount is None:
        return result
    result.detected_mount = str(mount.path)
    if mount != _containing_mount(configured, mounts):
        result.code = "outside_mount"
        return result
    if mount.path in {Path("/"), Path("/mnt"), Path("/mnt/disks"), Path("/mnt/remotes")}:
        return result
    if mount.filesystem in {"rootfs", "ramfs", "tmpfs", "devtmpfs", "overlay", "proc", "sysfs", "devpts"}:
        return result
    required = required_storage_mount(configured)
    if required is not None and mount.path != required and required not in mount.path.parents:
        return result

    # Retain EIO/ENODEV from a detached drive instead of treating it as missing.
    mount.path.stat()
    result.is_mounted = True
    if not os.access(configured, os.R_OK | os.X_OK):
        raise PermissionError(errno.EACCES, "USB storage directory is not readable/searchable", str(configured))
    result.writable = not mount.read_only and os.access(configured, os.W_OK)
    result.code = "ok" if result.writable else "not_writable"
    return result
