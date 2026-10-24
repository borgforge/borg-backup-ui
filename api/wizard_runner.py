#!/usr/bin/env python3
"""
api/wizard_runner.py - Scriptless Runner fuer Wizard-Jobs (Phase 4)
"""

from __future__ import annotations

import json
import fcntl
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
    for path in (backup_scripts_dir, ROOT_DIR, plugin_runtime, plugin_runtime / "lib"):
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
        job_key: str,
        ttl_seconds: int = 7200,
        grace_seconds: int = 60,
        heartbeat_seconds: int = 20,
        log_file: str = "",
        run_id: str = "",
        operation: str = "backup",
        file_activity: bool = False,
    ) -> None:
        self.lock_dir = lock_dir
        self.job_key = job_key
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

    def _lock_path(self, resource: str) -> Path:
        safe = resource.replace("/", "_").replace(":", "_").replace(" ", "_")
        return self.lock_dir / f"{safe}.lock.json"

    def _payload(self, resource: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "resource": resource,
            "job_key": self.job_key,
            "pid": os.getpid(),
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
        pid = int(lock_data.get("pid") or 0)
        if _pid_alive(pid):
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
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        # Serialize only lock acquisition/recovery, never the operation itself.
        # Another starter must not treat a newly created, not-yet-written file
        # as a corrupt stale lock and remove it.
        with (self.lock_dir / ".acquire.guard").open("a") as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            return self._acquire_locked(resources)

    def _acquire_locked(self, resources: list[str]) -> tuple[bool, str]:
        for resource in resources:
            path = self._lock_path(resource)
            payload = self._payload(resource)
            if self._write_new(path, payload):
                self._owned.append(path)
                continue

            lock_data = self._read_lock(path)
            if self._is_stale(lock_data):
                old_job = lock_data.get("job_key", "?")
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
            holder = lock_data.get("job_key", "unknown")
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
                        if int(data.get("pid") or 0) != os.getpid():
                            continue
                        data["updated_at"] = now
                        temporary = path.with_suffix(f".heartbeat-{os.getpid()}")
                        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                        temporary.replace(path)
                    except OSError:
                        continue

        self._thread = threading.Thread(target=_loop, daemon=True, name=f"lock-heartbeat-{self.job_key}")
        self._thread.start()

    def release(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        for path in list(self._owned):
            try:
                data = self._read_lock(path)
                if int(data.get("pid") or 0) == os.getpid():
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
        """Unmount runner-owned shares; raise on failure so the job cannot report success."""
        if not self.enabled or not self.mounted_by_runner or not self.mount_path or not self.unmount_after_run:
            return
        try:
            result = subprocess.run(["umount", self.mount_path], capture_output=True, text=True, timeout=15, check=False)
            if result.returncode:
                raise RuntimeError("Unmount returned a nonzero exit code")
            self.mounted_by_runner = False
            logging.info("SMB unmount completed: %s", self.mount_path)
        except Exception as exc:
            logging.warning("SMB unmount failed (%s): %s", self.mount_path, type(exc).__name__)
            raise RuntimeError("Network share cleanup failed") from None


def _load_env_from_job(job_key: str, borg_scripts_dir: Path, backup_scripts_dir: Path) -> tuple[dict, dict]:
    from job_identity import validate_job_id
    job_key = validate_job_id(job_key)
    _ensure_runtime_import_paths(backup_scripts_dir)
    from lib.status import load_config  # type: ignore

    from jobs_api import get_jobs_meta_dirs, resolve_data_root
    data_root = resolve_data_root({"BACKUP_SCRIPTS_DIR": str(backup_scripts_dir), "BORG_SCRIPTS_DIR": str(borg_scripts_dir)})
    meta_path = None
    for meta_dir in get_jobs_meta_dirs(borg_scripts_dir, data_root):
        candidate = meta_dir / f"{job_key}.json"
        if candidate.exists():
            meta_path = candidate
            break
    if meta_path is None:
        raise FileNotFoundError(f"Job metadata file not found: {job_key}")
    from inventory_store import inventory_lock
    from job_exclusions import marker_names, read_file
    with inventory_lock(meta_path.parent.parent):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["exclude_if_present"] = marker_names(meta.get("exclude_if_present"))
        if meta.get("exclude_from"):
            meta["_exclude_file_bytes"] = read_file(meta["exclude_from"], meta_path.parent, job_key)

    from repository_context import resolve_job_repository_context
    repository_context = resolve_job_repository_context(
        {"BACKUP_SCRIPTS_DIR": str(backup_scripts_dir)},
        job_key,
        job=meta,
    )
    storage = repository_context["storage"]
    meta = {
        **meta,
        "_resolved_repository": repository_context["repository"],
        "_resolved_storage": storage,
    }

    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    conf_file = backup_scripts_dir / "config" / "backup.conf"
    if conf_file.is_file():
        env.update(load_config(conf_file))

    env["BORG_UI_JOB_KEY"] = job_key
    location = str(repository_context.get("location") or meta.get("location") or "local").strip().lower()
    if location not in {"local", "usb", "smb", "storagebox", "custom"}:
        raise ValueError(f"invalid location in job metadata: {location}")
    if location == "storagebox":
        env["STORAGEBOX_HOST"] = str(storage.get("host", "")).strip()
        env["STORAGEBOX_PORT"] = str(storage.get("port", "23")).strip() or "23"
        env["STORAGEBOX_USER"] = str(storage.get("user", "")).strip()
        env["STORAGEBOX_BASE_PATH"] = str(storage.get("base_path", "/./backup")).strip() or "/./backup"

    cache_base = env.get("GLOBAL_BORG_CACHE_BASE", "/mnt/cache/borg-cache")
    cache_subdir = str(meta["cache_subdir"])
    check_flag_name = str(meta["check_flag_name"])
    if any(not name or Path(name).name != name or name in {".", ".."} for name in (cache_subdir, check_flag_name)):
        raise ValueError("Invalid job cache reference")
    cache_dir = f"{cache_base}/{cache_subdir}"
    from job_identity import job_run_date_tag
    date_tag = job_run_date_tag(os.environ.get("BORG_UI_RUN_ID", ""))
    log_dir = env.get("GLOBAL_LOG_DIR", "/mnt/user/Logs")

    from job_source_paths import normalize_source_paths
    from database_profiles import snapshot_profiles
    meta["_database_profiles"] = snapshot_profiles({"BACKUP_SCRIPTS_DIR": str(data_root)}, meta.get("database_profile_ids"))
    env["BORG_UI_DATABASE_PROFILES"] = "1" if meta["_database_profiles"] else "0"
    source_paths = normalize_source_paths(meta.get("source_paths"), field=f"Job '{job_key}' source_paths", allow_empty=bool(meta["_database_profiles"]))
    exclude_paths = meta.get("exclude_paths") if isinstance(meta.get("exclude_paths"), list) else []

    from job_settings import explicit_job_settings
    meta_compression, meta_ret = explicit_job_settings(meta)
    meta_file_activity = _env_flag(meta.get("file_activity"), default=False)
    # A managed run keeps its start-time option even if the job is edited.
    if os.environ.get("BORG_UI_FILE_ACTIVITY_RUN") in {"0", "1"}:
        meta_file_activity = os.environ["BORG_UI_FILE_ACTIVITY_RUN"] == "1"
    meta_keep_daily = str(meta_ret.get("daily") or "").strip()
    meta_keep_weekly = str(meta_ret.get("weekly") or "").strip()
    meta_keep_monthly = str(meta_ret.get("monthly") or "").strip()
    meta_keep_yearly = str(meta_ret.get("yearly") or "").strip()

    env["JOB_NAME"] = os.environ.get("BORG_UI_JOB_NAME") or str(meta.get("name") or job_key)
    env.setdefault("BACKUP_SCRIPTS_DIR", str(backup_scripts_dir))
    env.pop("BACKUP_TYPE", None)
    env["BACKUP_LOCATION"] = os.environ.get("BORG_UI_JOB_LOCATION") or location
    env.setdefault("DATE_TAG", date_tag)
    env.setdefault("LOG_DIR", log_dir)
    from job_identity import job_log_filename
    env.setdefault("LOG_FILE", str(Path(log_dir) / job_log_filename(
        env["JOB_NAME"], env["BACKUP_LOCATION"], job_key, date_tag,
    )))
    if meta_file_activity and os.environ.get("BORG_UI_CAPTURE_LOG"):
        env["LOG_FILE"] = os.environ["BORG_UI_CAPTURE_LOG"]
        # Retention still applies to saved logs; only this run's writes use RAM.
        env["BORG_UI_RETAINED_LOG"] = os.environ.get("BORG_UI_RETAINED_LOG", "")
    env.setdefault("LOG_RETENTION_DAYS", env.get("GLOBAL_LOG_RETENTION_DAYS", "30"))
    env["BORG_REPO"] = str(repository_context["repository_path"])
    # Storagebox compatibility: if ssh repo URI misses user component, inject STORAGEBOX_USER.
    repo_uri = str(env.get("BORG_REPO", "") or "").strip()
    storagebox_user = str(env.get("STORAGEBOX_USER", "") or "").strip()
    if location == "storagebox" and repo_uri.startswith("ssh://") and storagebox_user:
        parts = urlsplit(repo_uri)
        netloc = parts.netloc or ""
        if "@" not in netloc and netloc:
            env["BORG_REPO"] = urlunsplit((parts.scheme, f"{storagebox_user}@{netloc}", parts.path, parts.query, parts.fragment))
            logging.info("Storage Box repository URI has no user; using STORAGEBOX_USER=%s", storagebox_user)
    env["BORG_COMPRESSION"] = meta_compression
    env["BORG_FILE_ACTIVITY"] = "1" if meta_file_activity else "0"
    env.setdefault("BORG_CHECKPOINT_INTERVAL", env.get("GLOBAL_BORG_CHECKPOINT_INTERVAL", "1800"))
    env["BORG_CACHE_DIR"] = cache_dir
    env.setdefault("BORG_CHECK_INTERVAL_DAYS", env.get("GLOBAL_BORG_CHECK_INTERVAL_DAYS", "30"))
    env["BORG_CHECK_FLAG_FILE"] = f"{cache_dir}/{check_flag_name}"
    env["BORG_RETENTION_JSON"] = json.dumps(meta_ret)
    env["BORG_KEEP_DAILY"] = meta_keep_daily
    env["BORG_KEEP_WEEKLY"] = meta_keep_weekly
    env["BORG_KEEP_MONTHLY"] = meta_keep_monthly
    env["BORG_KEEP_YEARLY"] = meta_keep_yearly
    env.setdefault("LOCK_FILE", f"{env.get('LOCK_FILE_DIR', '/var/run')}/borg-backup-{job_key}.lock")
    env["BACKUP_PATHS_JSON"] = json.dumps(source_paths, ensure_ascii=False)
    env["BACKUP_EXCLUDE_PATHS_JSON"] = json.dumps(
        [str(path).strip() for path in exclude_paths if str(path).strip()],
        ensure_ascii=False,
    )
    env.setdefault("STATUS_DIR_OVERRIDE", env.get("STATUS_DIR", "/mnt/user/backup-status"))
    from borg_environment import UNKNOWN_UNENCRYPTED, apply_borg_environment

    env = apply_borg_environment(
        env, {"BACKUP_SCRIPTS_DIR": str(data_root)},
        encryption=repository_context.get("encryption", ""),
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
    os.environ["BORG_SECURITY_DIR"] = env["BORG_SECURITY_DIR"]
    os.environ.pop(UNKNOWN_UNENCRYPTED, None)
    if UNKNOWN_UNENCRYPTED in env:
        os.environ[UNKNOWN_UNENCRYPTED] = env[UNKNOWN_UNENCRYPTED]
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
    location = str(meta.get("location") or "").strip().lower()
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
    resources = [f"repo:{env.get('BORG_REPO', '')}"]
    location = str(meta.get("location") or "").strip().lower()
    if location == "smb":
        storage = meta.get("_resolved_storage") if isinstance(meta.get("_resolved_storage"), dict) else {}
        smb_key = str(storage.get("profile_key") or "").strip()
        if smb_key:
            resources.append(f"smb-mount:{smb_key}")
    if _runtime_control_enabled_for_lock(meta, "docker") or meta.get("database_profile_ids"):
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
    return {"mode": mode, "selected": selected,
            **({"force_stop": raw.get("force_stop") is True} if kind == "vm" else {}),
            **({"sequential": mode != "none" and raw.get("sequential") is True} if kind == "docker" else {})}


def _plan_docker_sequence(docker_mgr, docker_control: dict, source_paths: list, exclude_paths: list):
    """Plan container groups from the containers running now.

    Returns None when Docker is unavailable. Unreadable volume mappings raise
    RuntimeError before any container is stopped.
    """
    from lib.docker_sequence import plan_sequence  # type: ignore

    targets = docker_mgr.running_targets(docker_control["mode"], docker_control["selected"])
    if targets is None:
        return None
    mounts = docker_mgr.writable_bind_mounts([cid for _name, cid in targets]) if targets else {}
    return plan_sequence(source_paths, targets, mounts, exclude_paths)


def _log_docker_sequence(plan) -> None:
    logging.info("Sequential Docker backup: %d container group(s)", len(plan.groups))
    for position, group in enumerate(plan.groups, 1):
        logging.info("  %d. %s -> %s", position, ", ".join(group.containers), ", ".join(group.paths))
        if len(group.containers) > 1:
            logging.info("     Stopped together because their writable paths overlap")
    if plan.idle_containers:
        logging.info("Keep running (no writable path in the backup sources): %s", ", ".join(plan.idle_containers))
    for name, path, reason in plan.skipped_paths:
        logging.info("Ignored path of %s (%s): %s", name, reason, path)
    if plan.main_paths:
        logging.info("Main archive afterwards: %s (%d container path(s) excluded)",
                     ", ".join(plan.main_paths), len(plan.main_excludes))
    else:
        logging.info("Main archive afterwards: no remaining source path")


def _run_docker_sequence(job, plan, *, runner, control, set_phase, workflow, archive_prefix,
                         exclude_paths, log_file) -> tuple[int, list]:
    """Archive each planned group while only that group is stopped.

    Each group is stopped, archived as '<prefix>@<key>-<timestamp>' and
    restarted through ``job.recover_runtime`` before the next group starts.
    Returns ``(exit_code, stats)``: the worst create exit (0 or 1), 130 after
    cancellation or the first create error (>= 2), which ends the sequence.
    Restart failures propagate as RuntimeError and no further group stops.
    """
    from lib.borg_runner import parse_borg_stats  # type: ignore
    from lib.docker_sequence import TIMESTAMP_FORMAT, archive_name  # type: ignore

    groups: list[dict] = []
    stats: list = []

    def publish(current: str = "") -> None:
        done = sum(1 for row in groups if row["status"] in {"success", "warning"})
        workflow.update("docker_sequence", details={
            "target_count": len(plan.groups), "completed_count": done,
            "current": current, "groups": groups,
        })

    publish()
    worst = 0
    for position, group in enumerate(plan.groups, 1):
        if control.is_cancel_requested():
            return 130, stats
        name = archive_name(archive_prefix, group.key, datetime.now().strftime(TIMESTAMP_FORMAT))
        row = {"containers": list(group.containers), "archive": name, "status": "running"}
        groups.append(row)
        publish(", ".join(group.containers))
        logging.info("Container group %d/%d: %s -> archive %s", position, len(plan.groups),
                     ", ".join(group.containers), name)
        set_phase("stopping_docker")
        started = time.monotonic()
        code = 2
        try:
            job.stop_docker_group(group.containers)
            if control.is_cancel_requested():
                code = 130
            else:
                code = runner.create(group.paths, archive_prefix, exclude_paths=exclude_paths, archive_name=name)
        finally:
            row.update(status={0: "success", 1: "warning", 130: "cancelled"}.get(code, "error"),
                       exit_code=code, duration_seconds=round(max(0.0, time.monotonic() - started), 3))
            publish()
            job.recover_runtime()
        if code in (0, 1):
            stats.append(parse_borg_stats(log_file))
            worst = max(worst, code)
        else:
            return code, stats
    return worst, stats


def _combined_stats(stats: list, archive_name: str):
    """Sum the statistics of all archives one sequential run created."""
    from lib.borg_runner import BorgStats  # type: ignore

    present = [item for item in stats if item is not None]
    if not present:
        return None
    return BorgStats(
        archive_name=archive_name or present[-1].archive_name,
        original_size=sum(item.original_size for item in present),
        compressed_size=sum(item.compressed_size for item in present),
        deduplicated_size=sum(item.deduplicated_size for item in present),
        files=sum(item.files for item in present),
    )


def _resolve_usb_mount_path(meta: dict, backup_scripts_dir: Path) -> str:
    location = str(meta.get("location") or "").strip().lower()
    if location != "usb":
        return ""
    storage = meta.get("_resolved_storage") if isinstance(meta.get("_resolved_storage"), dict) else {}
    return str(storage.get("mount_path") or storage.get("base_path") or "").strip()


def main() -> int:
    _setup_stdout_logging()

    job_key = os.environ.get("BORG_UI_JOB_KEY", "").strip()
    run_id = os.environ.get("BORG_UI_RUN_ID", "").strip() or (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}"
    )
    borg_scripts_dir_raw = os.environ.get("BORG_UI_BORG_SCRIPTS_DIR", "").strip()
    backup_scripts_dir_raw = os.environ.get("BORG_SCRIPT_DIR", "").strip()
    if not job_key:
        logging.error("BORG_UI_JOB_KEY is missing")
        return 2
    if not borg_scripts_dir_raw or not backup_scripts_dir_raw:
        logging.error("Runner context is missing (BORG_UI_BORG_SCRIPTS_DIR / BORG_SCRIPT_DIR)")
        return 2

    from job_control import JobControl
    from database_profiles import DatabaseError

    control = JobControl(job_key, run_id)

    def set_phase(phase: str) -> None:
        recovery_phase = phase in {"recovering_docker", "recovering_vms", "unmounting", "post_script"}
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
        env, meta = _load_env_from_job(job_key, borg_scripts_dir, backup_scripts_dir)
    except Exception as exc:
        logging.error("Loading job failed: %s", exc)
        control.update_phase("failed", cancel_allowed=False, finished=True, exit_code=2)
        return 2

    _ensure_runtime_import_paths(backup_scripts_dir)
    from lib.backup_job import (  # type: ignore
        BackupJob,
        BackupJobConfig,
        RequiredSourcePathsMissing,
        UsbMountAccessError,
    )
    from lib.borg_runner import BorgConfig, BorgRunner, parse_borg_stats  # type: ignore
    from lib.notifications import MailConfig  # type: ignore
    from lib.docker_manager import DockerConfig, DockerManager  # type: ignore
    from lib.vm_manager import VmConfig, VmManager, VmShutdownError  # type: ignore

    job_config = BackupJobConfig.from_config(env)
    _setup_full_logging(job_config.log_file)
    os.environ["BORG_UI_GROUP_LOG_FILE"] = str(job_config.retained_log_file or job_config.log_file)
    if job_config.retained_log_file:
        # Also avoid including the active log if a source covers /run itself.
        job_config.exclude_paths.append(job_config.log_file.parent)
    from lifecycle_log import emit_lifecycle
    borg_config = BorgConfig.from_config(env)
    docker_sequence = _runtime_control(meta, "docker")["sequential"]
    borg_config.prune_container_series = docker_sequence
    from lib.job_workflow import JobWorkflow
    workflow = JobWorkflow.configured(
        hooks=meta.get("hooks"), docker=_runtime_control(meta, "docker")["mode"] != "none",
        vms=_runtime_control(meta, "vm")["mode"] != "none",
        prune=BorgRunner(borg_config).retention().get("mode") != "all", controller=control,
        databases=bool(meta.get("_database_profiles")), docker_sequence=docker_sequence,
    )
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
        job_key=job_key,
        ttl_seconds=ttl_seconds,
        grace_seconds=grace_seconds,
        heartbeat_seconds=heartbeat_seconds,
        log_file=str(env.get("LOG_FILE") or ""),
        run_id=run_id,
        file_activity=borg_config.file_activity,
    )
    resources = _build_resources(env, meta)
    ok, reason = lock_set.acquire(resources)
    if not ok:
        skipped_job = BackupJob(job_config, mail_config=mail_config, notification_config=env)
        skipped_job.workflow = workflow
        workflow.finalize("not_run")
        skipped_job.record_prestart_skip(reason)
        logging.warning("Job is being skipped: %s", reason)
        control.update_phase("skipped", cancel_allowed=False, finished=True, exit_code=2)
        return 2
    emit_lifecycle(
        "JOB",
        "process_started",
        request_id=os.environ.get("BORG_UI_REQUEST_ID", ""),
        source=os.environ.get("BORG_UI_REQUEST_SOURCE", "manual"),
        actor=os.environ.get("BORG_UI_REQUEST_ACTOR", ""),
        job_key=job_key,
        run_id=run_id,
        pid=os.getpid(),
        log_file=str(job_config.log_file),
        status_dir=str(job_config.status_dir),
    )

    from job_scripts import snapshot_hooks, run_hook
    smb_session = SmbMountSession()
    result_code = 2
    exclusion_temp = None
    cleanup_done = False
    job = None
    hooks = {"post_when": "success"}
    scripts = {}

    def complete_job(job):
        """Finish resource cleanup and Post before persisting the overall result."""
        nonlocal cleanup_done, exclusion_temp
        job.prepare_completion()
        if exclusion_temp is not None:
            try:
                exclusion_temp.cleanup()
            except OSError:
                logging.warning("Could not remove the temporary exclusion file")
            exclusion_temp = None
        set_phase("unmounting")
        try:
            smb_session.cleanup()
        except Exception:
            job.set_result(2, job._borg_stats, "Network share cleanup failed.")
            raise
        finally:
            cleanup_done = True
            if "post" in scripts and (hooks["post_when"] == "always" or
                    (job.exit_code < 2 and not job._skip_finish)):
                set_phase("post_script")
                outcome = "skipped" if job._skip_finish else (
                    "cancelled" if job._cancelled else
                    "success" if job.exit_code == 0 else "warning" if job.exit_code == 1 else "failed")
                with workflow.track("post_script"):
                    job.record_hook_result("post", run_hook(scripts["post"], "post", job_key, result=outcome))
            elif workflow.get("post_script") is not None:
                workflow.update("post_script", status="skipped", reason="post_condition")

    database_results = []

    def execute_backup(job):
        """Execute the backup body; the context manager always completes cleanup."""
        nonlocal exclusion_temp, database_results
        set_phase("preparing")
        borg_config.exclude_if_present = meta.get("exclude_if_present", [])
        if meta.get("exclude_from"):
            import tempfile
            exclusion_temp = tempfile.TemporaryDirectory(prefix="bbui-exclusions-")
            pattern_file = Path(exclusion_temp.name) / "exclude.txt"
            pattern_file.write_bytes(meta["_exclude_file_bytes"])
            pattern_file.chmod(0o600)
            borg_config.exclude_from = str(pattern_file)
            logging.info("Exclusion file: %s; SHA-256 %s", meta["exclude_from"]["original_name"], meta["exclude_from"]["sha256"])
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
        # Container groups are planned from the job sources, never from database dumps.
        sequence_sources = list(job_config.backup_paths)
        database_paths = []
        if meta.get("_database_profiles"):
            from database_backup import export_profiles, validate_sources, borg_artifact_paths
            validate_sources(meta["_database_profiles"], job_config.backup_paths)
            set_phase("database_backup")
            with workflow.track("database_backup"):
                database_results = export_profiles(
                    {"BACKUP_SCRIPTS_DIR": str(data_root)}, meta["_database_profiles"], job_key, run_id,
                    control.is_cancel_requested,
                    progress=lambda result: workflow.update("database_backup", details={"results": database_results}),
                    results=database_results,
                )
                workflow.update("database_backup", details={"results": database_results})
            database_paths = borg_artifact_paths(database_results)
            job_config.backup_paths.extend(database_paths)
        sequence = None
        sequence_exit = 0
        sequence_stats = []
        if docker_mgr is not None and docker_control["sequential"]:
            with workflow.track("docker_sequence"):
                sequence = _plan_docker_sequence(docker_mgr, docker_control, sequence_sources, job_config.exclude_paths)
                if sequence is None:
                    logging.info("Docker is disabled or unavailable; skipping sequential container backup")
                    workflow.update("docker_sequence", status="skipped", reason="unavailable")
                elif not sequence.groups:
                    _log_docker_sequence(sequence)
                    workflow.update("docker_sequence", status="skipped", reason="no_container_paths")
                else:
                    _log_docker_sequence(sequence)
                    sequence_exit, sequence_stats = _run_docker_sequence(
                        job, sequence,
                        runner=BorgRunner(borg_config, process_controller=control, phase_callback=set_phase),
                        control=control, set_phase=set_phase, workflow=workflow, archive_prefix=archive_prefix,
                        exclude_paths=job_config.exclude_paths, log_file=job_config.log_file,
                    )
                    workflow.update("docker_sequence", status={0: "success", 1: "warning", 130: "cancelled"}
                                    .get(sequence_exit, "error"))
            if sequence_exit == 130 or control.is_cancel_requested():
                logging.info("Cancellation requested; the last container group was restarted")
                job.set_cancelled()
                result_code = 130
                return result_code
            if sequence_exit >= 2:
                job.backup_exit_code = sequence_exit
                job.set_result(sequence_exit, final_msg=f"borg create failed for a container group (exit {sequence_exit})")
                result_code = sequence_exit
                return result_code
        elif docker_mgr is not None:
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
        main_archive = sequence is None or bool(sequence.main_paths or database_paths)
        if vm_mgr is not None and not main_archive:
            logging.info("No main archive is needed; VMs keep running")
        if vm_mgr is not None and main_archive:
            set_phase("stopping_vms")
            selected = vm_control["selected"] if vm_control["mode"] == "selected" else None
            job.shutdown_vms(selected)
            if control.is_cancel_requested():
                logging.info("Cancellation requested; VM shutdown completed and recovery starts now")
                job.set_cancelled()
                result_code = 130
                return result_code

        runner = BorgRunner(
            borg_config,
            process_controller=control,
            phase_callback=set_phase,
            workflow=workflow,
        )
        job.borg_steps = runner.steps
        database_archive = archive_prefix + "-" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S") if database_results else None
        create_options = {"archive_name": database_archive} if database_archive else {}
        if sequence is None:
            create_exit = runner.create(
                job_config.backup_paths,
                archive_prefix,
                exclude_paths=job_config.exclude_paths,
                **create_options,
            )
        elif main_archive:
            # Remaining paths and database dumps, without the container group paths.
            create_exit = runner.create(
                [*sequence.main_paths, *database_paths],
                archive_prefix,
                exclude_paths=[*job_config.exclude_paths, *sequence.main_excludes],
                **create_options,
            )
        else:
            logging.info("No main archive is needed; every source path is in a container archive")
            runner.skip_create("no_main_archive")
            create_exit = 0
        overall_exit = max(create_exit, sequence_exit)
        job.backup_exit_code = overall_exit
        run_stats = None
        if create_exit < 2:
            run_stats = parse_borg_stats(job_config.log_file)
            if sequence is not None:
                run_stats = _combined_stats(
                    [*sequence_stats, *([run_stats] if main_archive else [])],
                    run_stats.archive_name if main_archive and run_stats is not None else "",
                )
            job.set_result(overall_exit, run_stats)
        if control.is_cancel_requested():
            job.set_cancelled()
            result_code = 130
            return result_code
        if create_exit >= 2:
            job.set_result(create_exit, final_msg=f"borg create failed (exit {create_exit})")
            result_code = create_exit
            return result_code

        job.recover_runtime()
        if database_results:
            from database_backup import verify_archive, cleanup_run, write_manifest
            try:
                verify_archive(borg_config.repo, database_archive, database_results, control.is_cancel_requested)
                workflow.update("database_backup", details={"results": database_results})
                for result, profile in zip(database_results, meta["_database_profiles"]):
                    write_manifest(result)
                    if create_exit == 0 and profile['retention'] == 'after_archive':
                        cleanup_run(result, profile, verified=True)
            except Exception:
                workflow.update("database_backup", status="error")
                raise
        if control.is_cancel_requested():
            job.set_cancelled()
            result_code = 130
            return result_code

        maint_exit = runner.maintenance(archive_prefix=archive_prefix)
        if control.is_cancel_requested():
            job.set_cancelled()
            result_code = 130
            return result_code
        exit_code = max(overall_exit, maint_exit)
        job.set_result(exit_code, run_stats if sequence is not None else parse_borg_stats(job_config.log_file))
        result_code = exit_code
        return result_code

    try:
        docker_mgr = None
        vm_mgr = None
        docker_control = _runtime_control(meta, "docker")
        vm_control = _runtime_control(meta, "vm")
        if docker_control["mode"] != "none":
            docker_mgr = DockerManager(DockerConfig.from_config(env))
        if vm_control["mode"] != "none":
            vm_config = VmConfig.from_config(env)
            vm_config.force_stop = vm_control.get("force_stop") is True
            vm_mgr = VmManager(vm_config)
        from archive_prefix import archive_prefix_from_metadata
        archive_prefix = archive_prefix_from_metadata(meta)
        abort_on_parity = _env_flag(env.get("ABORT_ON_PARITY_CHECK"), default=True)
        with BackupJob(
            job_config, docker_manager=docker_mgr, vm_manager=vm_mgr,
            mail_config=mail_config, notification_config=env,
            phase_callback=set_phase, completion_callback=complete_job,
        ) as job:
            job.workflow = workflow
            if "docker-control" in resources:
                from database_backup import reconcile_operations
                reconcile_operations({"BACKUP_SCRIPTS_DIR": str(data_root)})
            hooks, scripts = snapshot_hooks({"BACKUP_SCRIPTS_DIR": str(data_root)}, meta.get("hooks"))
            if control.is_cancel_requested():
                job.set_cancelled()
            else:
                if "pre" in scripts:
                    set_phase("pre_script")
                    with workflow.track("pre_script"):
                        job.record_hook_result("pre", run_hook(scripts["pre"], "pre", job_key,
                                                               cancelled=control.is_cancel_requested))
                pre_ok = "pre" not in scripts or job.hook_results["pre"]["status"] == "success"
                if pre_ok and not control.is_cancel_requested():
                    set_phase("mounting")
                    smb_session = _ensure_smb_mount(env, meta)
                    try:
                        execute_backup(job)
                    except DatabaseError as exc:
                        workflow.update("database_backup", status="interrupted" if exc.reason == "cancelled" else "error",
                                        details={"results": database_results, "error_code": exc.api_code})
                        if exc.reason == "cancelled":
                            job.set_cancelled()
                        else:
                            job.set_result(2, final_msg=exc.api_code)
                elif control.is_cancel_requested():
                    job.set_cancelled()
        result_code = job.exit_code
        return result_code
    except SystemExit as exc:
        result_code = job.exit_code if exc.code == 0 else 2
        return result_code
    except DatabaseError as exc:
        logging.error("%s", exc.api_code)
        if exc.reason == "cancelled" and job is not None:
            job.set_cancelled()
            result_code = 130
            return 130
        result_code = 2
        return 2
    except (RequiredSourcePathsMissing, UsbMountAccessError, VmShutdownError):
        result_code = 2
        return 2
    except Exception:
        result_code = 2
        raise
    finally:
        from database_backup import close_results
        close_results(database_results)
        try:
            if not cleanup_done:
                if exclusion_temp is not None:
                    exclusion_temp.cleanup()
                set_phase("unmounting")
                smb_session.cleanup()
        finally:
            try:
                lock_set.release()
            finally:
                terminal_phase = "cancelled" if result_code == 130 else (
                    "skipped" if job is not None and job._skip_finish else
                    "completed" if result_code < 2 else "failed")
                workflow.finalize("after_cancel" if result_code == 130 else "not_run")
                control.update_phase(terminal_phase, cancel_allowed=False, finished=True, exit_code=result_code)


if __name__ == "__main__":
    sys.exit(main())
