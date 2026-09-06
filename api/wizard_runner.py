#!/usr/bin/env python3
"""
api/wizard_runner.py - Scriptless Runner fuer Wizard-Jobs (Phase 4)
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from smb_protocol import build_smb_mount_options, classify_smb_mount_error, sanitize_smb_error


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
BORG_BUNDLE_DIR = ROOT_DIR / "runtime" / "bin" / "borg"
BORG_BUNDLE_PLAIN = BORG_BUNDLE_DIR / "borg"
BORG_BUNDLE_VERSIONED = BORG_BUNDLE_DIR / "borg-linux-glibc231-x86_64-1.4.5"
BORG_TMP_BIN = Path("/tmp/borg")


def _ensure_runtime_import_paths(backup_scripts_dir: Path) -> None:
    """Prefer the installed plugin runtime while keeping data-root fallbacks."""
    plugin_runtime = ROOT_DIR / "runtime"
    for path in (backup_scripts_dir, plugin_runtime, plugin_runtime / "lib"):
        raw = str(path)
        while raw in sys.path:
            sys.path.remove(raw)
        sys.path.insert(0, raw)


def _env_flag(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _setup_stdout_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def _setup_full_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    captured = os.environ.get("BORG_UI_CAPTURE_LOG", "")
    handlers = [logging.StreamHandler(sys.stdout)]
    if not captured or Path(captured) != log_file:
        handlers.insert(0, logging.FileHandler(log_file))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def _ensure_borg_available() -> str:
    """
    Ensure `borg` is resolvable for subprocess calls in this runner.
    Returns resolved executable path (for logging).
    """
    found = shutil.which("borg")
    if found:
        return found

    checked = []
    for candidate in (BORG_BUNDLE_PLAIN, BORG_BUNDLE_VERSIONED):
        try:
            checked.append(str(candidate))
            if candidate.is_file():
                try:
                    candidate.chmod(0o755)
                except Exception:
                    # Continue with copy fallback below.
                    pass
            if candidate.is_file() and os.access(candidate, os.X_OK):
                # If binary already named "borg", PATH prepend is enough.
                if candidate.name == "borg":
                    bundle_path = str(candidate.parent)
                    os.environ["PATH"] = f"{bundle_path}:{os.environ.get('PATH', '')}".strip(":")
                    found = shutil.which("borg")
                    if found:
                        return found
                # If only versioned binary exists, copy to /tmp/borg alias.
                else:
                    try:
                        shutil.copy2(candidate, BORG_TMP_BIN)
                        BORG_TMP_BIN.chmod(0o755)
                        if os.access(BORG_TMP_BIN, os.X_OK):
                            os.environ["PATH"] = f"/tmp:{os.environ.get('PATH', '')}".strip(":")
                            found = shutil.which("borg")
                            if found:
                                return found
                    except Exception:
                        pass
            # Fallback: copy bundled binary to /tmp and chmod there.
            if candidate.is_file():
                try:
                    shutil.copy2(candidate, BORG_TMP_BIN)
                    BORG_TMP_BIN.chmod(0o755)
                    if os.access(BORG_TMP_BIN, os.X_OK):
                        os.environ["PATH"] = f"/tmp:{os.environ.get('PATH', '')}".strip(":")
                        found = shutil.which("borg")
                        if found:
                            return found
                except Exception:
                    pass
        except Exception:
            continue

    raise FileNotFoundError(
        "borg command not found "
        f"(neither in PATH nor runtime/bin/borg). checked={checked} uid={os.geteuid()}"
    )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ResourceLockSet:
    def __init__(
        self,
        lock_dir: Path,
        job_id: str,
        ttl_seconds: int = 7200,
        grace_seconds: int = 60,
        heartbeat_seconds: int = 20,
        log_file: str = "",
        run_id: str = "",
        operation: str = "backup",
        file_activity: bool = False,
        snapshot: dict | None = None,
    ) -> None:
        self.lock_dir = lock_dir
        from job_model import validate_job_id
        from job_runs import validate_run_id
        if operation == "backup":
            validate_job_id(job_id)
            validate_run_id(run_id)
        elif job_id:
            validate_job_id(job_id)
        self.snapshot = dict(snapshot or {})
        self.job_id = job_id
        self.ttl_seconds = ttl_seconds
        self.grace_seconds = grace_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.log_file = str(log_file or "").strip()
        self.run_id = str(run_id or "").strip()
        self.operation = str(operation or "backup").strip().lower() or "backup"
        self.file_activity = file_activity
        self._owned: list[Path] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._host = socket.gethostname()
        from activity_log_capture import process_token
        self._process_start = process_token(os.getpid())

    def _lock_path(self, resource: str) -> Path:
        safe = hashlib.sha256(resource.encode()).hexdigest()
        return self.lock_dir / f"{safe}.lock.json"

    def _payload(self, resource: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            **self.snapshot,
            "schema_version": 1,
            "resource": resource,
            **({"job_id": self.job_id} if self.job_id else {"service": self.operation}),
            "pid": os.getpid(),
            "process_start": self._process_start,
            "host": self._host,
            "operation": self.operation,
            "started_at": now,
            "updated_at": now,
            "ttl_seconds": self.ttl_seconds,
        }
        if self.log_file:
            payload["log_file"] = self.log_file
        if self.run_id:
            payload["run_id"] = self.run_id
        if self.file_activity:
            payload["file_activity"] = True
        return payload

    def _write_new(self, path: Path, payload: dict) -> bool:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(path, flags, 0o644)
        except FileExistsError:
            return False
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return True

    def _read_lock(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _is_stale(self, lock_data: dict) -> bool:
        from activity_log_capture import process_token
        pid = int(lock_data.get("pid") or 0)
        if _pid_alive(pid) and (not lock_data.get("process_start") or process_token(pid) == lock_data["process_start"]):
            return False
        updated = str(lock_data.get("updated_at") or "")
        if not updated:
            return True
        try:
            updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - updated_dt).total_seconds()
            return age > self.grace_seconds
        except Exception:
            return True

    def acquire(self, resources: list[str]) -> tuple[bool, str]:
        from inventory_store import inventory_lock
        # Serialize the stale-read/unlink/recreate sequence across processes.
        # Without this gate two starters can unlink each other's fresh lock.
        with inventory_lock(self.lock_dir):
            return self._acquire(resources)

    def _acquire(self, resources: list[str]) -> tuple[bool, str]:
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        for resource in resources:
            path = self._lock_path(resource)
            payload = self._payload(resource)
            if self._write_new(path, payload):
                self._owned.append(path)
                continue

            lock_data = self._read_lock(path)
            if self._is_stale(lock_data):
                old_job = lock_data.get("job_id", "?")
                old_pid = lock_data.get("pid", "?")
                logging.warning(
                    "stale lock recovered: %s (job=%s pid=%s)",
                    resource, old_job, old_pid,
                )
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                if self._write_new(path, payload):
                    self._owned.append(path)
                    continue

            operation = str(lock_data.get("operation") or "backup").strip().lower()
            run_id = str(lock_data.get("run_id") or "").strip()
            holder = lock_data.get("job_name_snapshot") or lock_data.get("job_id", "unknown")
            if operation and operation != "backup" and run_id:
                holder = f"{operation} {run_id}"
            self.release()
            return False, f"resource locked by {holder} ({resource})"

        self._start_heartbeat()
        return True, ""

    def _start_heartbeat(self) -> None:
        def _loop() -> None:
            while not self._stop.wait(self.heartbeat_seconds):
                now = datetime.now(timezone.utc).isoformat()
                for path in list(self._owned):
                    try:
                        data = self._read_lock(path)
                        if int(data.get("pid") or 0) != os.getpid() or data.get("run_id") != self.run_id:
                            continue
                        data["updated_at"] = now
                        from job_control import _atomic_json
                        _atomic_json(path, data)
                    except OSError:
                        continue

        self._thread = threading.Thread(target=_loop, daemon=True, name=f"lock-heartbeat-{self.job_id}")
        self._thread.start()

    def release(self) -> None:
        self._stop.set()
        if self._thread is not None:
            # A slow final heartbeat is still an owned-state writer. Do not
            # release the run lease or remove locks while its write is pending.
            self._thread.join()
        for path in list(self._owned):
            try:
                data = self._read_lock(path)
                if int(data.get("pid") or 0) == os.getpid() and data.get("run_id") == self.run_id:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        self._owned.clear()


class SmbMountSession:
    def __init__(self) -> None:
        self.enabled = False
        self.profile_key = ""
        self.mount_path = ""
        self.mounted_by_runner = False
        self.unmount_after_run = True

    def cleanup(self) -> None:
        if not self.enabled or not self.mounted_by_runner or not self.mount_path or not self.unmount_after_run:
            return
        try:
            subprocess.run(["umount", self.mount_path], capture_output=True, text=True, timeout=15, check=False)
            logging.info("SMB unmount completed: %s", self.mount_path)
        except Exception as exc:
            logging.warning("SMB unmount failed (%s): %s", self.mount_path, exc)


def _load_env_from_job(job_id: str, borg_scripts_dir: Path, backup_scripts_dir: Path) -> tuple[dict, dict]:
    _ensure_runtime_import_paths(backup_scripts_dir)
    from job_runs import read_run_context
    from jobs_api import resolve_data_root
    snapshot = read_run_context(job_id, os.environ.get("BORG_UI_RUN_ID", ""))
    repository_context = snapshot["context"]
    storage = repository_context["storage"]
    meta = {
        **repository_context["job"],
        "_resolved_repository": repository_context["repository"],
        "_resolved_storage": storage,
        "_resolved_location": snapshot["location_snapshot"],
        "_run_snapshot": snapshot,
    }
    data_root = resolve_data_root({"BACKUP_SCRIPTS_DIR": str(backup_scripts_dir)})
    env = {**os.environ, **snapshot["settings"], "LC_ALL": "C", "LANG": "C"}
    # Explicit canonical settings always win over legacy type/global defaults.
    location = snapshot["location_snapshot"]
    cache = meta.get("cache_reference") or {}
    cache_dir = cache.get("directory") or str(Path(env.get("GLOBAL_BORG_CACHE_BASE") or "/mnt/cache/borg-cache") / job_id)
    retained_log = snapshot["log_file"]
    file_activity = snapshot["file_activity"]
    active_log = os.environ.get("BORG_UI_CAPTURE_LOG") if file_activity else None
    env.update({
        "JOB_ID": job_id, "RUN_ID": snapshot["run_id"],
        "JOB_NAME": snapshot["job_name_snapshot"],
        "ARCHIVE_PREFIX": snapshot["archive_prefix_snapshot"],
        "ARCHIVE_PREFIXES_JSON": json.dumps(snapshot["archive_prefixes_snapshot"]),
        "REPOSITORY_KEY": snapshot["repository_key_snapshot"],
        "BACKUP_SCRIPTS_DIR": str(data_root),
        "BACKUP_LOCATION": location,
        "DATE_TAG": datetime.fromisoformat(snapshot["started_at"]).astimezone().strftime("%Y-%m-%d_%H-%M-%S"),
        "LOG_DIR": str(Path(retained_log).parent),
        "LOG_FILE": active_log or retained_log,
        "BORG_UI_RETAINED_LOG": retained_log if active_log else "",
        "LOG_RETENTION_DAYS": env.get("GLOBAL_LOG_RETENTION_DAYS", "30"),
        "BORG_REPO": snapshot["repository_snapshot"],
        "BORG_COMPRESSION": meta.get("compression", "lz4"),
        "BORG_FILE_ACTIVITY": "1" if file_activity else "0",
        "BORG_CACHE_DIR": cache_dir,
        "BORG_CHECK_FLAG_FILE": (cache["check_flag_file"] if cache.get("repository_key") == snapshot["repository_key_snapshot"]
                                 else str(Path(cache_dir) / (".last_check-" + hashlib.sha256(snapshot["repository_snapshot"].encode()).hexdigest()))),
        "LOCK_FILE": str(Path(env.get("LOCK_FILE_DIR") or "/var/run") / ("borg-backup-" + job_id + ".lock")),
        "BACKUP_PATHS_JSON": json.dumps(meta["source_paths"], ensure_ascii=False),
        "BACKUP_EXCLUDE_PATHS_JSON": json.dumps(meta.get("exclude_paths", []), ensure_ascii=False),
        "STATUS_DIR_OVERRIDE": env.get("STATUS_DIR", "/mnt/user/backup-status"),
    })
    env.pop("BACKUP_TYPE", None)
    for period in ("daily", "weekly", "monthly", "yearly"):
        env["BORG_KEEP_" + period.upper()] = str(meta["retention"][period])
    env.setdefault("BORG_CHECKPOINT_INTERVAL", env.get("GLOBAL_BORG_CHECKPOINT_INTERVAL", "1800"))
    env.setdefault("BORG_CHECK_INTERVAL_DAYS", env.get("GLOBAL_BORG_CHECK_INTERVAL_DAYS", "30"))
    from borg_key_store import apply_borg_key_environment

    env = apply_borg_key_environment(
        env, {"BACKUP_SCRIPTS_DIR": str(data_root)}
    )

    repo = env.get("BORG_REPO", "")
    from borg_ssh import configure_borg_ssh

    configure_borg_ssh(env, storage, repo)

    pass_file = str(repository_context.get("passphrase_ref") or "").strip()
    if repository_context.get("encryption") != "none":
        os.environ["BORG_PASSCOMMAND"] = f"cat {shlex.quote(pass_file)}"
    else:
        os.environ.pop("BORG_PASSCOMMAND", None)

    os.environ["BORG_REPO"] = env["BORG_REPO"]
    os.environ["BORG_CACHE_DIR"] = env["BORG_CACHE_DIR"]
    os.environ["BORG_KEYS_DIR"] = env["BORG_KEYS_DIR"]
    os.environ["BORG_SCRIPT_DIR"] = str(backup_scripts_dir)
    os.environ["LC_ALL"] = "C"
    os.environ["LANG"] = "C"
    if env.get("BORG_RSH"):
        os.environ["BORG_RSH"] = str(env["BORG_RSH"])

    return env, meta


def _is_smb_mounted(mount_path: str) -> bool:
    if not mount_path:
        return False
    try:
        proc = subprocess.run(
            ["findmnt", "-T", mount_path, "-n", "-o", "FSTYPE"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        fs = (proc.stdout or "").strip().lower()
        return proc.returncode == 0 and fs in {"cifs", "smb3", "smbfs"}
    except Exception:
        return False


def _ensure_smb_mount(env: dict, meta: dict) -> SmbMountSession:
    sess = SmbMountSession()
    location = str(meta.get("_resolved_location") or "").strip().lower()
    if location != "smb":
        return sess
    if not bool(meta.get("mount_before_run", True)):
        logging.info("SMB mount before run is disabled (mount_before_run=false)")
        return sess

    storage = meta.get("_resolved_storage") if isinstance(meta.get("_resolved_storage"), dict) else {}
    profile_key = str(storage.get("profile_key") or storage.get("storage_key") or "").strip()
    server = str(storage.get("server", "")).strip()
    share = str(storage.get("share", "")).strip().lstrip("/")
    mount_path = str(storage.get("mount_path") or storage.get("base_path") or "").strip()
    username = str(storage.get("username", "")).strip()
    password_file = str(storage.get("password_file", "")).strip()
    if not server or not share or not mount_path or not username or not password_file:
        raise ValueError(f"SMB storage target is incomplete: {profile_key}")

    mp = Path(mount_path)
    mp.mkdir(parents=True, exist_ok=True)
    sess.enabled = True
    sess.profile_key = profile_key
    sess.mount_path = mount_path
    sess.unmount_after_run = bool(meta.get("unmount_after_run", True)) and not bool(storage.get("keep_mounted", False))

    if _is_smb_mounted(mount_path):
        logging.info("SMB is already mounted: %s", mount_path)
        return sess

    src = f"//{server}/{share}"
    opts = build_smb_mount_options(storage, password_file)

    cmd = ["mount", "-t", "cifs", src, mount_path, "-o", ",".join(opts)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if res.returncode != 0:
        technical = sanitize_smb_error(res.stderr or res.stdout or "SMB mount failed")
        _code, hint = classify_smb_mount_error(technical)
        raise RuntimeError(f"{hint} Technical details: {technical}")
    sess.mounted_by_runner = True
    logging.info("SMB mount succeeded: %s -> %s", src, mount_path)
    return sess


def _runtime_control_enabled_for_lock(meta: dict, kind: str) -> bool:
    raw = meta.get(f"{kind}_control") if isinstance(meta.get(f"{kind}_control"), dict) else {}
    features = meta.get("features") if isinstance(meta.get("features"), dict) else {}
    allowed_modes = {"all", "selected", "none"}
    if kind == "docker":
        allowed_modes.add("except_selected")
    mode = str(raw.get("mode") or "").strip().lower()
    if mode in allowed_modes:
        return mode != "none"
    return bool(features.get(kind, False))


def _build_resources(env: dict, meta: dict) -> list[str]:
    resources = [f"job:{meta['job_id']}", f"repo:{env.get('BORG_REPO', '')}"]
    location = str(meta.get("_resolved_location") or "").strip().lower()
    if location == "smb":
        storage = meta.get("_resolved_storage") if isinstance(meta.get("_resolved_storage"), dict) else {}
        smb_key = str(storage.get("profile_key") or "").strip()
        if smb_key:
            resources.append(f"smb-mount:{smb_key}")
    if _runtime_control_enabled_for_lock(meta, "docker"):
        resources.append("docker-control")
    if _runtime_control_enabled_for_lock(meta, "vm"):
        resources.append("vm-control")
    return resources


def _runtime_control(meta: dict, kind: str) -> dict:
    raw = meta.get(f"{kind}_control") if isinstance(meta.get(f"{kind}_control"), dict) else {}
    features = meta.get("features") if isinstance(meta.get("features"), dict) else {}
    allowed_modes = {"all", "selected", "none"}
    if kind == "docker":
        allowed_modes.add("except_selected")
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in allowed_modes:
        mode = "all" if bool(features.get(kind, False)) else "none"
    selected = []
    if mode in {"selected", "except_selected"}:
        raw_selected = raw.get("selected") if isinstance(raw.get("selected"), list) else []
        seen = set()
        for item in raw_selected:
            name = str(item or "").strip()
            if name and name not in seen:
                seen.add(name)
                selected.append(name)
    return {"mode": mode, "selected": selected}


def _resolve_usb_mount_path(meta: dict, backup_scripts_dir: Path) -> str:
    location = str(meta.get("_resolved_location") or "").strip().lower()
    if location != "usb":
        return ""
    storage = meta.get("_resolved_storage") if isinstance(meta.get("_resolved_storage"), dict) else {}
    return str(storage.get("mount_path") or storage.get("base_path") or "").strip()


def main() -> int:
    """Admission precedes run-state, logs, locks, runtime control and Borg."""
    from migration_barrier import MigrationBlocked, writer_lease
    config = {"BACKUP_SCRIPTS_DIR": os.environ.get("BORG_SCRIPT_DIR") or "/boot/config/borg-backup"}
    try:
        with writer_lease(config):
            return _run_admitted()
    except MigrationBlocked as exc:
        _setup_stdout_logging()
        logging.error("Backup start blocked: %s", exc.reason)
        return 2


def _run_admitted() -> int:
    _setup_stdout_logging()

    job_id = os.environ.get("BORG_UI_JOB_ID", "")
    run_id = os.environ.get("BORG_UI_RUN_ID", "")
    borg_scripts_dir_raw = os.environ.get("BORG_UI_BORG_SCRIPTS_DIR", "").strip()
    backup_scripts_dir_raw = os.environ.get("BORG_SCRIPT_DIR", "").strip()
    if not job_id:
        logging.error("BORG_UI_JOB_ID is missing")
        return 2
    if not borg_scripts_dir_raw or not backup_scripts_dir_raw:
        logging.error("Runner context is missing (BORG_UI_BORG_SCRIPTS_DIR / BORG_SCRIPT_DIR)")
        return 2

    from job_control import JobControl

    from job_runs import descriptors, read_run_context
    try:
        snapshot = read_run_context(job_id, run_id)
    except (ValueError, OSError):
        logging.error("A valid immutable run context is required")
        return 2
    control = JobControl(job_id, run_id, snapshot=descriptors(snapshot))

    def set_phase(phase: str) -> None:
        recovery_phase = phase in {"recovering_docker", "recovering_vms", "unmounting"}
        stopping_phase = phase in {"stopping_docker", "stopping_vms"}
        message_key = ""
        if phase == "stopping_docker":
            message_key = "jobs.cancelPendingDocker"
        elif phase == "stopping_vms":
            message_key = "jobs.cancelPendingVm"
        elif recovery_phase:
            message_key = "jobs.cancelUnavailableRecovery"
        control.update_phase(
            phase,
            cancel_allowed=not recovery_phase,
            cancellation_deferred=stopping_phase,
            message_key=message_key,
        )

    set_phase("preparing")

    borg_scripts_dir = Path(borg_scripts_dir_raw)
    backup_scripts_dir = Path(backup_scripts_dir_raw)
    try:
        borg_bin = _ensure_borg_available()
        logging.info("Active Borg binary: %s", borg_bin)
        env, meta = _load_env_from_job(job_id, borg_scripts_dir, backup_scripts_dir)
    except Exception as exc:
        logging.error("Loading job failed: %s", exc)
        control.update_phase("failed", cancel_allowed=False, finished=True, exit_code=2)
        return 2

    _ensure_runtime_import_paths(backup_scripts_dir)
    from lib.backup_job import (  # type: ignore
        BackupJob,
        BackupJobConfig,
        RequiredSourcePathsMissing,
    )
    from lib.borg_runner import BorgConfig, BorgRunner, parse_borg_stats  # type: ignore
    from lib.notifications import MailConfig  # type: ignore
    from lib.docker_manager import DockerConfig, DockerManager  # type: ignore
    from lib.vm_manager import VmConfig, VmManager  # type: ignore

    job_config = BackupJobConfig.from_config(env)
    _setup_full_logging(job_config.log_file)
    if job_config.retained_log_file:
        # Also avoid including the active log if a source covers /run itself.
        job_config.exclude_paths.append(job_config.log_file.parent)
    from lifecycle_log import emit_lifecycle
    borg_config = BorgConfig.from_config(env)
    mail_config = MailConfig.from_config(env)

    data_root = Path(str(env.get("BACKUP_SCRIPTS_DIR") or backup_scripts_dir))
    if data_root.name == "scripts":
        data_root = data_root.parent
    lock_dir = Path(env.get("BORG_RESOURCE_LOCK_DIR", str(data_root / "locks")))
    ttl_seconds = int(env.get("BORG_RESOURCE_LOCK_TTL_SECONDS", "7200") or "7200")
    grace_seconds = int(env.get("BORG_RESOURCE_LOCK_GRACE_SECONDS", "60") or "60")
    heartbeat_seconds = int(env.get("BORG_RESOURCE_LOCK_HEARTBEAT_SECONDS", "20") or "20")

    lock_set = ResourceLockSet(
        lock_dir=lock_dir,
        job_id=job_id,
        ttl_seconds=ttl_seconds,
        grace_seconds=grace_seconds,
        heartbeat_seconds=heartbeat_seconds,
        log_file=str(env.get("LOG_FILE") or ""),
        run_id=run_id,
        file_activity=borg_config.file_activity,
        snapshot=descriptors(snapshot),
    )
    resources = _build_resources(env, meta)
    ok, reason = lock_set.acquire(resources)
    if not ok:
        emit_lifecycle(
            "JOB",
            "finished",
            request_id=os.environ.get("BORG_UI_REQUEST_ID", ""),
            source=os.environ.get("BORG_UI_REQUEST_SOURCE", "manual"),
            actor=os.environ.get("BORG_UI_REQUEST_ACTOR", ""),
            job_id=job_id,
            run_id=run_id,
            status="skipped",
            exit_code=2,
            duration_seconds=0,
            log_file=str(job_config.log_file),
            reason=reason,
            failure_code="resource_lock_unavailable",
        )
        logging.warning("Job is being skipped: %s", reason)
        control.update_phase("skipped", cancel_allowed=False, finished=True, exit_code=2)
        return 2
    emit_lifecycle(
        "JOB",
        "process_started",
        request_id=os.environ.get("BORG_UI_REQUEST_ID", ""),
        source=os.environ.get("BORG_UI_REQUEST_SOURCE", "manual"),
        actor=os.environ.get("BORG_UI_REQUEST_ACTOR", ""),
        job_id=job_id,
        run_id=run_id,
        pid=os.getpid(),
        log_file=str(job_config.log_file),
        status_dir=str(job_config.status_dir),
    )

    smb_session = SmbMountSession()
    result_code = 2
    try:
        set_phase("mounting")
        smb_session = _ensure_smb_mount(env, meta)
        docker_mgr = None
        vm_mgr = None
        docker_control = _runtime_control(meta, "docker")
        vm_control = _runtime_control(meta, "vm")
        if docker_control["mode"] != "none":
            docker_mgr = DockerManager(DockerConfig.from_config(env))
        if vm_control["mode"] != "none":
            vm_mgr = VmManager(VmConfig.from_config(env))

        archive_prefix = snapshot["archive_prefix_snapshot"]
        abort_on_parity = _env_flag(env.get("ABORT_ON_PARITY_CHECK"), default=True)
        with BackupJob(
            job_config,
            docker_manager=docker_mgr,
            vm_manager=vm_mgr,
            mail_config=mail_config,
            notification_config=env,
            phase_callback=set_phase,
        ) as job:
            set_phase("preparing")
            if control.is_cancel_requested():
                job.set_cancelled()
                result_code = 130
                return result_code
            if abort_on_parity:
                logging.info("Parity check enabled (ABORT_ON_PARITY_CHECK=true)")
                job.check_parity()
            else:
                logging.info("Parity check disabled (ABORT_ON_PARITY_CHECK=false)")
            usb_mount_path = _resolve_usb_mount_path(meta, backup_scripts_dir)
            if usb_mount_path:
                logging.info("USB mount check enabled: %s", usb_mount_path)
                job.check_usb_mount(Path(usb_mount_path))
            job.check_prerequisites()
            job.cleanup_old_logs()
            if control.is_cancel_requested():
                job.set_cancelled()
                result_code = 130
                return result_code
            if docker_mgr is not None:
                set_phase("stopping_docker")
                selected = docker_control["selected"]
                if docker_control["mode"] == "selected":
                    job.stop_docker(selected)
                elif docker_control["mode"] == "except_selected":
                    job.stop_docker(exclude_names=selected)
                else:
                    job.stop_docker()
                if control.is_cancel_requested():
                    logging.info("Cancellation requested; Docker stop completed and recovery starts now")
                    job.set_cancelled()
                    result_code = 130
                    return result_code
            if vm_mgr is not None:
                set_phase("stopping_vms")
                selected = vm_control["selected"] if vm_control["mode"] == "selected" else None
                job.shutdown_vms(selected)
                if control.is_cancel_requested():
                    logging.info("Cancellation requested; VM shutdown completed and recovery starts now")
                    job.set_cancelled()
                    result_code = 130
                    return result_code

            from inventory_store import inventory_lock
            runner = BorgRunner(
                borg_config,
                process_controller=control,
                phase_callback=set_phase,
                prune_guard=lambda: inventory_lock(data_root / "config"),
            )
            create_exit = runner.create(
                job_config.backup_paths,
                archive_prefix,
                exclude_paths=job_config.exclude_paths,
            )
            if control.is_cancel_requested():
                job.set_cancelled()
                result_code = 130
                return result_code
            if create_exit >= 2:
                job.set_result(create_exit, final_msg=f"borg create failed (exit {create_exit})")
                result_code = create_exit
                return result_code

            from job_runs import maintenance_context_unchanged
            if maintenance_context_unchanged({"BACKUP_SCRIPTS_DIR": str(data_root)}, snapshot):
                maint_exit = runner.maintenance(
                    archive_prefixes=snapshot["archive_prefixes_snapshot"],
                    before_delete=lambda: maintenance_context_unchanged({"BACKUP_SCRIPTS_DIR": str(data_root)}, snapshot),
                )
            else:
                logging.warning("Repository assignment changed during this run; maintenance skipped")
                maint_exit = 1
            if control.is_cancel_requested():
                job.set_cancelled()
                result_code = 130
                return result_code
            exit_code = max(create_exit, maint_exit)
            job.set_result(exit_code, parse_borg_stats(job_config.log_file))
            result_code = exit_code
            return result_code
    except RequiredSourcePathsMissing:
        result_code = 2
        return 2
    except Exception:
        # Runtime recovery can fail while unwinding an accepted cancellation.
        # That failure must win over the earlier exit code 130.
        result_code = 2
        raise
    finally:
        set_phase("unmounting")
        try:
            smb_session.cleanup()
        finally:
            try:
                lock_set.release()
            finally:
                terminal_phase = "cancelled" if result_code == 130 else ("completed" if result_code < 2 else "failed")
                control.update_phase(
                    terminal_phase,
                    cancel_allowed=False,
                    finished=True,
                    exit_code=result_code,
                )


if __name__ == "__main__":
    sys.exit(main())
