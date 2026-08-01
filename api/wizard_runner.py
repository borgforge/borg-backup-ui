#!/usr/bin/env python3
"""
api/wizard_runner.py - Scriptless Runner fuer Wizard-Jobs (Phase 4)
"""

from __future__ import annotations

import json
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
BORG_BUNDLE_VERSIONED = BORG_BUNDLE_DIR / "borg-linux-glibc231-x86_64-1.4.4"
BORG_TMP_BIN = Path("/tmp/borg")


def _ensure_runtime_import_paths(backup_scripts_dir: Path) -> None:
    """Prefer the installed plugin runtime while keeping data-root fallbacks."""
    plugin_runtime = ROOT_DIR / "runtime"
    for path in (backup_scripts_dir, plugin_runtime):
        raw = str(path)
        while raw in sys.path:
            sys.path.remove(raw)
        sys.path.insert(0, raw)


def _type_upper(type_id: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in type_id.upper())


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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
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
    ) -> None:
        self.lock_dir = lock_dir
        self.job_key = job_key
        self.ttl_seconds = ttl_seconds
        self.grace_seconds = grace_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.log_file = str(log_file or "").strip()
        self.run_id = str(run_id or "").strip()
        self.operation = str(operation or "backup").strip().lower() or "backup"
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
                        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
        if not self.enabled or not self.mounted_by_runner or not self.mount_path or not self.unmount_after_run:
            return
        try:
            subprocess.run(["umount", self.mount_path], capture_output=True, text=True, timeout=15, check=False)
            logging.info("SMB unmount completed: %s", self.mount_path)
        except Exception as exc:
            logging.warning("SMB unmount failed (%s): %s", self.mount_path, exc)


def _load_env_from_job(job_key: str, borg_scripts_dir: Path, backup_scripts_dir: Path) -> tuple[dict, dict]:
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
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

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

    type_id = str(meta.get("backup_type") or "").strip().lower()
    location = str(repository_context.get("location") or meta.get("location") or "local").strip().lower()
    if not type_id:
        raise ValueError("backup_type is missing from job metadata")
    if location not in {"local", "usb", "smb", "storagebox", "custom"}:
        raise ValueError(f"invalid location in job metadata: {location}")
    if location == "storagebox":
        env["STORAGEBOX_HOST"] = str(storage.get("host", "")).strip()
        env["STORAGEBOX_PORT"] = str(storage.get("port", "23")).strip() or "23"
        env["STORAGEBOX_USER"] = str(storage.get("user", "")).strip()
        env["STORAGEBOX_BASE_PATH"] = str(storage.get("base_path", "/./backup")).strip() or "/./backup"

    tu = _type_upper(type_id)
    cache_base = env.get("GLOBAL_BORG_CACHE_BASE", "/mnt/cache/borg-cache")
    cache_dir = f"{cache_base}/{location}_{type_id}"
    date_tag = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_dir = env.get("GLOBAL_LOG_DIR", "/mnt/user/Logs")

    from job_source_paths import normalize_source_paths
    source_paths = normalize_source_paths(meta.get("source_paths"), field=f"Job '{job_key}' source_paths")
    exclude_paths = meta.get("exclude_paths") if isinstance(meta.get("exclude_paths"), list) else []

    meta_compression = str(meta.get("compression") or "").strip()
    meta_ret = meta.get("retention") if isinstance(meta.get("retention"), dict) else {}
    meta_keep_daily = str(meta_ret.get("daily") or "").strip()
    meta_keep_weekly = str(meta_ret.get("weekly") or "").strip()
    meta_keep_monthly = str(meta_ret.get("monthly") or "").strip()
    meta_keep_yearly = str(meta_ret.get("yearly") or "").strip()

    env.setdefault("JOB_NAME", str(meta.get("name") or job_key))
    env.setdefault("BACKUP_SCRIPTS_DIR", str(backup_scripts_dir))
    env.setdefault("BACKUP_TYPE", type_id)
    env.setdefault("BACKUP_LOCATION", location)
    env.setdefault("DATE_TAG", date_tag)
    env.setdefault("LOG_DIR", log_dir)
    # Use job_key for log filename so variants like flash_local/flash_usb are separated.
    env.setdefault("LOG_FILE", f"{log_dir}/Borg-Backup_{job_key}--{date_tag}.log")
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
    env.setdefault("BORG_COMPRESSION", meta_compression or env.get(f"COMPRESSION_{tu}", "lz4"))
    env.setdefault("BORG_CHECKPOINT_INTERVAL", env.get("GLOBAL_BORG_CHECKPOINT_INTERVAL", "1800"))
    env.setdefault("BORG_CACHE_DIR", cache_dir)
    env.setdefault("BORG_CHECK_INTERVAL_DAYS", env.get("GLOBAL_BORG_CHECK_INTERVAL_DAYS", "30"))
    env.setdefault("BORG_CHECK_FLAG_FILE", f"{cache_dir}/.last_check_{type_id}")
    env.setdefault("BORG_KEEP_DAILY", meta_keep_daily or env.get(f"RETENTION_{tu}_DAILY", "7"))
    env.setdefault("BORG_KEEP_WEEKLY", meta_keep_weekly or env.get(f"RETENTION_{tu}_WEEKLY", "4"))
    env.setdefault("BORG_KEEP_MONTHLY", meta_keep_monthly or env.get(f"RETENTION_{tu}_MONTHLY", "6"))
    env.setdefault("BORG_KEEP_YEARLY", meta_keep_yearly or env.get(f"RETENTION_{tu}_YEARLY", "3"))
    env.setdefault("LOCK_FILE", f"{env.get('LOCK_FILE_DIR', '/var/run')}/borg-backup-{type_id}.lock")
    env["BACKUP_PATHS_JSON"] = json.dumps(source_paths, ensure_ascii=False)
    env["BACKUP_EXCLUDE_PATHS_JSON"] = json.dumps(
        [str(path).strip() for path in exclude_paths if str(path).strip()],
        ensure_ascii=False,
    )
    env.setdefault("STATUS_DIR_OVERRIDE", env.get("STATUS_DIR", "/mnt/user/backup-status"))
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


def _build_resources(env: dict, meta: dict) -> list[str]:
    resources = [f"repo:{env.get('BORG_REPO', '')}"]
    location = str(meta.get("location") or "").strip().lower()
    if location == "smb":
        storage = meta.get("_resolved_storage") if isinstance(meta.get("_resolved_storage"), dict) else {}
        smb_key = str(storage.get("profile_key") or "").strip()
        if smb_key:
            resources.append(f"smb-mount:{smb_key}")
    features = meta.get("features") if isinstance(meta.get("features"), dict) else {}
    if bool(features.get("docker", False)):
        resources.append("docker-control")
    if bool(features.get("vm", False)):
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

    control = JobControl(job_key, run_id)

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
    )
    from lib.borg_runner import BorgConfig, BorgRunner, parse_borg_stats  # type: ignore
    from lib.notifications import MailConfig  # type: ignore
    from lib.docker_manager import DockerConfig, DockerManager  # type: ignore
    from lib.vm_manager import VmConfig, VmManager  # type: ignore

    job_config = BackupJobConfig.from_config(env)
    _setup_full_logging(job_config.log_file)
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
        job_key=job_key,
        ttl_seconds=ttl_seconds,
        grace_seconds=grace_seconds,
        heartbeat_seconds=heartbeat_seconds,
        log_file=str(env.get("LOG_FILE") or ""),
        run_id=run_id,
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
            job_key=job_key,
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
        job_key=job_key,
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

        archive_prefix = f"{env.get('BACKUP_TYPE', 'job')}-backup"
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

            runner = BorgRunner(
                borg_config,
                process_controller=control,
                phase_callback=set_phase,
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

            maint_exit = runner.maintenance()
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
