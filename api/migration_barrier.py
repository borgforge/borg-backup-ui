"""Cross-process admission and writer leases for the #479 migration.

Admission defaults to denied, including before the first UI startup and after
a reboot. Only the startup coordinator may publish the versioned runtime ready
proof. The persistent inhibit is deliberately outside migrated owned stores.
Neither an admission check nor a PID list alone is a quiescence guarantee:
the coordinator must hold ``exclusive_migration`` throughout prepare/apply.
"""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import threading


PROTOCOL_VERSION = 1
_local = threading.local()


class MigrationBlocked(RuntimeError):
    api_status = 503
    api_code = "migration_maintenance"

    def __init__(self, reason="migration_maintenance"):
        self.reason = reason
        super().__init__(reason)


def data_root(config):
    raw = str(config.get("BACKUP_SCRIPTS_DIR") or "/boot/config/borg-backup")
    path = Path(os.path.abspath(raw))
    return path.parent if path.name == "scripts" else path


def _paths(config):
    root = data_root(config)
    namespace = hashlib.sha256(os.fsencode(root)).hexdigest()
    runtime = Path(os.environ.get("BORG_UI_MIGRATION_GATE_ROOT") or "/run/borg-backup-ui/migration-gate") / namespace
    return root / ".migration-gate" / "blocked.json", runtime


def _safe_directory(path, *, create=False):
    path = Path(path)
    if not path.is_absolute():
        raise MigrationBlocked("unsafe_gate_path")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if not create:
                raise MigrationBlocked("gate_storage_unavailable") from None
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            info = current.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise MigrationBlocked("unsafe_gate_path")
    return path


def _mounted_root(root):
    parts = root.parts
    mount = None
    if len(parts) > 2 and parts[1] == "mnt":
        mount = Path(*parts[:4]) if parts[2] in {"disks", "remotes"} and len(parts) > 3 else Path(*parts[:3])
    elif len(parts) > 1 and parts[1] == "boot":
        mount = Path("/boot")
    if mount is not None and not mount.is_mount():
        raise MigrationBlocked("gate_storage_unavailable")
    _safe_directory(root)


def _open_lock(path):
    _safe_directory(path.parent, create=True)
    directory_info = path.parent.stat()
    if directory_info.st_uid != os.geteuid() or directory_info.st_mode & 0o022:
        raise MigrationBlocked("unsafe_gate_lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
        os.close(fd)
        raise MigrationBlocked("unsafe_gate_lock")
    return fd


@contextmanager
def _admission(config):
    _, runtime = _paths(config)
    fd = _open_lock(runtime / "admission.lock")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield runtime
    finally:
        os.close(fd)


def _proof(path):
    try:
        path.parent.lstat()
    except FileNotFoundError:
        return None
    _safe_directory(path.parent)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise MigrationBlocked("unsafe_gate_state")
        if path.name == "ready.json" and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
            raise MigrationBlocked("unsafe_gate_state")
        raw = os.read(fd, 4097)
        if len(raw) > 4096:
            raise MigrationBlocked("invalid_gate_state")
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise MigrationBlocked("invalid_gate_state") from None
    finally:
        os.close(fd)


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish(path, value):
    _safe_directory(path.parent, create=True)
    # The admission lock serializes this fixed temporary name; an interrupted
    # publish is never accepted as ready and can be safely replaced on restart.
    temporary = path.with_name(path.name + ".pending")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise MigrationBlocked("unsafe_gate_state")
        os.ftruncate(fd, 0)
        raw = (json.dumps(value, sort_keys=True) + "\n").encode()
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    _sync_dir(path.parent)


def _held(kind, key):
    return getattr(_local, kind, {}).get(key, 0) > 0


@contextmanager
def _activate(kind, key):
    entries = getattr(_local, kind, None)
    if entries is None:
        entries = {}
        setattr(_local, kind, entries)
    entries[key] = entries.get(key, 0) + 1
    try:
        yield
    finally:
        entries[key] -= 1
        if not entries[key]:
            del entries[key]


class WriterLease:
    """An acquired lease can be handed to an already-admitted worker thread."""

    def __init__(self, fd, key):
        self.fd, self.key = fd, key

    @contextmanager
    def activate(self):
        if self.fd is None:
            raise MigrationBlocked("writer_lease_closed")
        with _activate("writers", self.key):
            yield self

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def acquire_writer_lease(config):
    """Acquire before creating a worker; close only after its final write."""
    marker, runtime = _paths(config)
    key = str(runtime)
    with _admission(config):
        # Existing admitted work may finish, including nested finalization.
        if not _held("writers", key):
            _mounted_root(data_root(config))
            if _proof(marker) is not None:
                raise MigrationBlocked()
            if _proof(runtime / "ready.json") != {"protocol_version": PROTOCOL_VERSION, "ready": True}:
                raise MigrationBlocked("startup_validation_required")
        fd = _open_lock(runtime / "writers.lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise MigrationBlocked("migration_in_progress") from None
    return WriterLease(fd, key)


@contextmanager
def writer_lease(config):
    lease = acquire_writer_lease(config)
    try:
        with lease.activate():
            yield lease
    finally:
        lease.close()


def block_writers(config):
    """Close admission durably without waiting for or terminating live work."""
    marker, runtime = _paths(config)
    with _admission(config):
        (runtime / "ready.json").unlink(missing_ok=True)
        _sync_dir(runtime)
        _mounted_root(data_root(config))
        _publish(marker, {"protocol_version": PROTOCOL_VERSION, "blocked": True})


def _process_kind(arguments):
    names = {Path(arg).name for arg in arguments if arg and not arg.startswith("-")}
    if "borg_backup_ui.py" in names:
        return "previous_ui_process"
    if "wizard_runner.py" in names:
        return "backup_worker"
    if "activity_log_capture.py" in names:
        return "backup_capture_worker"
    if "retention_runner.py" in names:
        return "retention_worker"
    if "factory_reset_worker.py" in names:
        return "factory_reset_worker"
    if "borg" in names or any(name.startswith("borg-linux-") for name in names):
        return "borg_worker"
    if names.intersection({"borg_restore_test.py", "borg_restore_test.sh"}):
        return "restore_test_worker"
    if any(name.startswith("borg_backup_") and name.endswith((".py", ".sh")) for name in names):
        return "legacy_backup_worker"
    if "-c" in arguments and any("from lib.notification_events import drain_notification_queue" in arg for arg in arguments):
        return "notification_worker"
    return ""


def blockers(config, *, proc_root=Path("/proc")):
    """Bounded, read-only evidence for workers from a previously installed build.

    All known plugin workers on this host block, including legacy ones without
    leases. No command line, job payload or environment is returned.
    """
    rows = []
    try:
        processes = list(Path(proc_root).iterdir())
    except OSError:
        return [{"reason": "process_inspection_unavailable"}]
    for process in processes:
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            with (process / "cmdline").open("rb") as handle:
                raw = handle.read(65537)
        except FileNotFoundError:
            continue  # Process exited before inspection.
        except OSError:
            rows.append({"reason": "process_inspection_unavailable", "pid": int(process.name)})
            continue
        if len(raw) > 65536:
            rows.append({"reason": "process_inspection_incomplete", "pid": int(process.name)})
            continue
        arguments = raw.decode("utf-8", errors="replace").split("\x00")
        kind = _process_kind(arguments)
        if kind:
            rows.append({"reason": "worker_running", "kind": kind, "pid": int(process.name)})
        if len(rows) >= 100:
            break
    return rows


@contextmanager
def exclusive_migration(config):
    """Try quiescence without waiting; retain exclusive ownership until exit."""
    marker, runtime = _paths(config)
    fd = None
    with _admission(config):
        if _proof(marker) != {"protocol_version": PROTOCOL_VERSION, "blocked": True}:
            raise MigrationBlocked("migration_gate_not_blocked")
        fd = _open_lock(runtime / "writers.lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise MigrationBlocked("writers_running") from None
    try:
        if blockers(config):
            raise MigrationBlocked("legacy_workers_running")
        with _activate("exclusive", str(runtime)):
            yield
    finally:
        os.close(fd)


def clear_block(config):
    """Only call after successful startup/integrity verification under exclusion."""
    marker, runtime = _paths(config)
    if not _held("exclusive", str(runtime)):
        raise MigrationBlocked("exclusive_migration_required")
    with _admission(config):
        _mounted_root(data_root(config))
        marker.unlink(missing_ok=True)
        _sync_dir(marker.parent)
        _publish(runtime / "ready.json", {"protocol_version": PROTOCOL_VERSION, "ready": True})


def quiescence_held(config):
    """A precondition callback must prove ownership, not just absence of PIDs."""
    return _held("exclusive", str(_paths(config)[1]))
