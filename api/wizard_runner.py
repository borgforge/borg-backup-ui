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


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
BORG_BUNDLE_DIR = ROOT_DIR / "runtime" / "bin" / "borg"
BORG_BUNDLE_PLAIN = BORG_BUNDLE_DIR / "borg"
BORG_BUNDLE_VERSIONED = BORG_BUNDLE_DIR / "borg-linux-glibc231-x86_64-1.4.4"
BORG_TMP_BIN = Path("/tmp/borg")


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


def _ensure_warn_weak_crypto_suppressed(borg_rsh: str) -> str:
    option = "-o WarnWeakCrypto=no"
    if option in borg_rsh:
        return borg_rsh
    return f"{borg_rsh} {option}".strip()


def _ensure_legacy_remote_ssh_options(borg_rsh: str) -> str:
    options = [
        "-o Compression=no",
        "-o ServerAliveInterval=30",
        "-o ServerAliveCountMax=3",
        "-o Ciphers=aes128-gcm@openssh.com,chacha20-poly1305@openssh.com",
        "-o ControlMaster=auto",
        "-o ControlPath=/tmp/ssh-borg-%r@%h:%p",
        "-o ControlPersist=600",
        "-o LogLevel=ERROR",
    ]
    out = borg_rsh
    for opt in options:
        if opt not in out:
            out = f"{out} {opt}".strip()
    return out


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
    ) -> None:
        self.lock_dir = lock_dir
        self.job_key = job_key
        self.ttl_seconds = ttl_seconds
        self.grace_seconds = grace_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self._owned: list[Path] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._host = socket.gethostname()

    def _lock_path(self, resource: str) -> Path:
        safe = resource.replace("/", "_").replace(":", "_").replace(" ", "_")
        return self.lock_dir / f"{safe}.lock.json"

    def _payload(self, resource: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "resource": resource,
            "job_key": self.job_key,
            "pid": os.getpid(),
            "host": self._host,
            "started_at": now,
            "updated_at": now,
            "ttl_seconds": self.ttl_seconds,
        }

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

            holder = lock_data.get("job_key", "unknown")
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
    sys.path.insert(0, str(backup_scripts_dir))
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

    env = dict(os.environ)
    conf_file = backup_scripts_dir / "config" / "backup.conf"
    if conf_file.is_file():
        env.update(load_config(conf_file))

    type_id = str(meta.get("backup_type") or "").strip().lower()
    location = str(meta.get("location") or "local").strip().lower()
    if not type_id:
        raise ValueError("backup_type is missing from job metadata")
    if location not in {"local", "usb", "smb", "storagebox", "custom"}:
        raise ValueError(f"invalid location in job metadata: {location}")
    if location == "storagebox":
        storage_profile_key = str(meta.get("storage_profile_key") or "").strip().lower()
        if not storage_profile_key:
            raise ValueError("Storage profile is missing from job metadata (storage_profile_key).")
        try:
            from config_api import read_settings_payload
            payload = read_settings_payload({"BACKUP_SCRIPTS_DIR": str(backup_scripts_dir)})
            profiles = payload.get("storage_profiles") if isinstance(payload.get("storage_profiles"), list) else []
            selected = None
            for row in profiles:
                if not isinstance(row, dict):
                    continue
                key = str(row.get("key") or "").strip().lower()
                if key == storage_profile_key:
                    selected = row
                    break
            if not isinstance(selected, dict):
                raise ValueError(f"Storage profile not found: {storage_profile_key}")
            env["STORAGEBOX_HOST"] = str(selected.get("host", "")).strip()
            env["STORAGEBOX_PORT"] = str(selected.get("port", "23")).strip() or "23"
            env["STORAGEBOX_USER"] = str(selected.get("user", "")).strip()
            env["STORAGEBOX_BASE_PATH"] = str(selected.get("base_path", "/./backup")).strip() or "/./backup"
        except Exception as exc:
            raise ValueError(f"Storage profile resolution failed: {exc}")
    elif location == "smb":
        try:
            from config_api import read_settings_payload
            payload = read_settings_payload({"BACKUP_SCRIPTS_DIR": str(backup_scripts_dir)})
            smb_rows = payload.get("smb_profiles") if isinstance(payload.get("smb_profiles"), list) else []
            env["SMB_PROFILES_JSON"] = json.dumps(smb_rows, ensure_ascii=False)
        except Exception as exc:
            raise ValueError(f"SMB profile resolution failed: {exc}")

    tu = _type_upper(type_id)
    cache_base = env.get("GLOBAL_BORG_CACHE_BASE", "/mnt/cache/borg-cache")
    cache_dir = f"{cache_base}/{location}_{type_id}"
    date_tag = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_dir = env.get("GLOBAL_LOG_DIR", "/mnt/user/Logs")

    repo_cfg = meta.get("repo") if isinstance(meta.get("repo"), dict) else {}
    repo_key = str(repo_cfg.get("conf_key") or "")
    repo_default = str(repo_cfg.get("default") or "")

    paths_cfg = meta.get("paths") if isinstance(meta.get("paths"), dict) else {}
    paths_key = str(paths_cfg.get("conf_key") or f"BACKUP_PATHS_{tu}")
    paths_default = str(paths_cfg.get("default") or "")

    pass_cfg = meta.get("passphrase") if isinstance(meta.get("passphrase"), dict) else {}
    pass_key = str(pass_cfg.get("conf_key") or f"BORG_PASSPHRASE_FILE_{tu}")
    pass_default = str(
        pass_cfg.get("default")
        or f"/boot/config/borg-backup/secrets/.borg-passphrase-{type_id}_{location}"
    )
    pass_mode = str(pass_cfg.get("mode") or "existing_file")
    meta_compression = str(meta.get("compression") or "").strip()
    meta_ret = meta.get("retention") if isinstance(meta.get("retention"), dict) else {}
    meta_keep_daily = str(meta_ret.get("daily") or "").strip()
    meta_keep_weekly = str(meta_ret.get("weekly") or "").strip()
    meta_keep_monthly = str(meta_ret.get("monthly") or "").strip()
    meta_keep_yearly = str(meta_ret.get("yearly") or "").strip()

    env.setdefault("JOB_NAME", str(meta.get("name") or job_key))
    env.setdefault("BACKUP_TYPE", type_id)
    env.setdefault("BACKUP_LOCATION", location)
    env.setdefault("DATE_TAG", date_tag)
    env.setdefault("LOG_DIR", log_dir)
    # Use job_key for log filename so variants like flash_local/flash_usb are separated.
    env.setdefault("LOG_FILE", f"{log_dir}/Borg-Backup_{job_key}--{date_tag}.log")
    env.setdefault("LOG_RETENTION_DAYS", env.get("GLOBAL_LOG_RETENTION_DAYS", "30"))
    env.setdefault("BORG_REPO", env.get(repo_key, repo_default) if repo_key else repo_default)
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
    env.setdefault("BACKUP_PATHS", env.get(paths_key, paths_default))
    env.setdefault("STATUS_DIR_OVERRIDE", env.get("STATUS_DIR", "/mnt/user/backup-status"))

    repo = env.get("BORG_REPO", "")
    if repo.startswith("ssh://"):
        if env.get("BORG_RSH"):
            env["BORG_RSH"] = _ensure_warn_weak_crypto_suppressed(str(env["BORG_RSH"]))
        else:
            env["BORG_RSH"] = "ssh -o WarnWeakCrypto=no"
        env["BORG_RSH"] = _ensure_legacy_remote_ssh_options(str(env["BORG_RSH"]))

    if pass_mode != "none":
        pass_file = env.get(pass_key, pass_default)
        pass_path = Path(pass_file)
        if not pass_path.exists():
            raise FileNotFoundError(f"Passphrase file not found: {pass_file}")
        os.environ["BORG_PASSCOMMAND"] = f"cat {shlex.quote(str(pass_file))}"

    os.environ["BORG_REPO"] = env["BORG_REPO"]
    os.environ["BORG_CACHE_DIR"] = env["BORG_CACHE_DIR"]
    os.environ["BORG_SCRIPT_DIR"] = str(backup_scripts_dir)
    if env.get("BORG_RSH"):
        os.environ["BORG_RSH"] = str(env["BORG_RSH"])

    return env, meta


def _parse_smb_profiles(env: dict) -> dict[str, dict]:
    raw = str(env.get("SMB_PROFILES_JSON", "[]") or "[]")
    try:
        rows = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        rows = []
    out: dict[str, dict] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key", "")).strip()
            if not key:
                continue
            out[key] = row
    return out


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

    profile_key = str(meta.get("smb_profile_key") or "").strip()
    if not profile_key:
        raise ValueError("SMB profile is missing from job metadata (smb_profile_key).")

    profiles = _parse_smb_profiles(env)
    profile = profiles.get(profile_key)
    if not isinstance(profile, dict):
        raise ValueError(f"SMB profile not found: {profile_key}")

    server = str(profile.get("server", "")).strip()
    share = str(profile.get("share", "")).strip().lstrip("/")
    mount_path = str(profile.get("mount_path", "")).strip()
    username = str(profile.get("username", "")).strip()
    password_file = str(profile.get("password_file", "")).strip()
    if not server or not share or not mount_path or not username or not password_file:
        raise ValueError(f"SMB profile is incomplete: {profile_key}")

    mp = Path(mount_path)
    mp.mkdir(parents=True, exist_ok=True)
    sess.enabled = True
    sess.profile_key = profile_key
    sess.mount_path = mount_path
    sess.unmount_after_run = bool(meta.get("unmount_after_run", True))

    if _is_smb_mounted(mount_path):
        logging.info("SMB is already mounted: %s", mount_path)
        return sess

    src = f"//{server}/{share}"
    opts = [f"credentials={password_file}", "iocharset=utf8"]
    vers = str(profile.get("vers", "")).strip() or "3.0"
    opts.append(f"vers={vers}")
    sec = str(profile.get("sec", "")).strip()
    if sec:
        opts.append(f"sec={sec}")
    uid = str(profile.get("uid", "")).strip()
    if uid:
        opts.append(f"uid={uid}")
    gid = str(profile.get("gid", "")).strip()
    if gid:
        opts.append(f"gid={gid}")
    file_mode = str(profile.get("file_mode", "")).strip()
    if file_mode:
        opts.append(f"file_mode={file_mode}")
    dir_mode = str(profile.get("dir_mode", "")).strip()
    if dir_mode:
        opts.append(f"dir_mode={dir_mode}")

    cmd = ["mount", "-t", "cifs", src, mount_path, "-o", ",".join(opts)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if res.returncode != 0:
        msg = (res.stderr or res.stdout or "SMB mount failed").strip()
        raise RuntimeError(f"SMB mount failed ({src} -> {mount_path}): {msg}")
    sess.mounted_by_runner = True
    logging.info("SMB mount succeeded: %s -> %s", src, mount_path)
    return sess


def _init_repo_if_needed(env: dict, encryption: str) -> int:
    import subprocess

    repo = env.get("BORG_REPO", "")
    if not repo:
        return 0

    # Lokales Repo robust erkennen: wenn Borg-Config-Datei existiert, kein init.
    if "://" not in repo and not repo.startswith("ssh:"):
        repo_path = Path(repo)
        if repo_path.exists() and (repo_path / "config").exists():
            logging.info("Repository already exists (local check): %s", repo)
            return 0

    check = subprocess.run(
        ["borg", "info", repo],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if check.returncode == 0:
        return 0

    logging.info("Repository not found; initializing: %s", repo)
    result = subprocess.run(
        ["borg", "init", f"--encryption={encryption}", repo],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if "already exists at" in combined or "repository already exists" in combined:
        logging.info("Repository already exists (borg init output): %s", repo)
        return 0
    if result.returncode != 0:
        for line in (result.stdout + result.stderr).splitlines():
            if line.strip():
                logging.error("[borg init] %s", line)
        logging.error("borg init failed (exit %d)", result.returncode)
    else:
        logging.info("Repository initialized successfully: %s", repo)
    return result.returncode


def _normalize_storage_base_for_repo(base_path: str) -> str:
    raw = str(base_path or "").strip()
    if raw.startswith("/./"):
        return "/" + raw[3:].lstrip("/")
    if raw.startswith("./"):
        return "/" + raw[2:].lstrip("/")
    if raw.startswith("/"):
        return raw
    return "/" + raw.lstrip("/")


def _guard_remote_repo_init(env: dict, meta: dict) -> tuple[bool, str]:
    location = str(meta.get("location") or "").strip().lower()
    if location != "storagebox":
        return True, ""
    if not bool(meta.get("create_repo_if_missing", False)):
        return True, ""
    if not bool(meta.get("remote_init_confirmed", False)):
        return False, "Remote initialization is not confirmed."

    repo = str(env.get("BORG_REPO", "")).strip()
    if not repo.startswith("ssh://"):
        return False, "Storage Box repository is not an ssh:// URI."
    parts = urlsplit(repo)
    if ".." in (parts.path or ""):
        return False, "Invalid repository path ('..' is not allowed)."
    base_norm = _normalize_storage_base_for_repo(str(env.get("STORAGEBOX_BASE_PATH", "/./backup")))
    repo_path = str(parts.path or "")
    if not repo_path.startswith(base_norm.rstrip("/") + "/"):
        return False, f"Repository path is not below STORAGEBOX_BASE_PATH ({base_norm})."
    return True, ""


def _build_resources(env: dict, meta: dict) -> list[str]:
    resources = [f"repo:{env.get('BORG_REPO', '')}"]
    location = str(meta.get("location") or "").strip().lower()
    if location == "smb":
        smb_key = str(meta.get("smb_profile_key") or "").strip()
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
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in {"all", "selected", "none"}:
        mode = "all" if bool(features.get(kind, False)) else "none"
    selected = []
    if mode == "selected":
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
    usb_profile_key = str(meta.get("usb_profile_key") or "").strip().lower()
    if not usb_profile_key:
        return ""
    try:
        from config_api import read_settings_payload
        payload = read_settings_payload({"BACKUP_SCRIPTS_DIR": str(backup_scripts_dir)})
        profiles = payload.get("usb_profiles") if isinstance(payload.get("usb_profiles"), list) else []
        for row in profiles:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "").strip().lower()
            if key != usb_profile_key:
                continue
            mount_path = str(row.get("mount_path") or "").strip()
            if mount_path:
                return mount_path
    except Exception:
        return ""
    return ""


def main() -> int:
    _setup_stdout_logging()

    job_key = os.environ.get("BORG_UI_JOB_KEY", "").strip()
    borg_scripts_dir_raw = os.environ.get("BORG_UI_BORG_SCRIPTS_DIR", "").strip()
    backup_scripts_dir_raw = os.environ.get("BORG_SCRIPT_DIR", "").strip()
    if not job_key:
        logging.error("BORG_UI_JOB_KEY is missing")
        return 2
    if not borg_scripts_dir_raw or not backup_scripts_dir_raw:
        logging.error("Runner context is missing (BORG_UI_BORG_SCRIPTS_DIR / BORG_SCRIPT_DIR)")
        return 2

    borg_scripts_dir = Path(borg_scripts_dir_raw)
    backup_scripts_dir = Path(backup_scripts_dir_raw)
    try:
        borg_bin = _ensure_borg_available()
        logging.info("Active Borg binary: %s", borg_bin)
        env, meta = _load_env_from_job(job_key, borg_scripts_dir, backup_scripts_dir)
    except Exception as exc:
        logging.error("Loading job failed: %s", exc)
        return 2

    sys.path.insert(0, str(backup_scripts_dir))
    from lib.backup_job import BackupJob, BackupJobConfig  # type: ignore
    from lib.borg_runner import BorgConfig, BorgRunner, parse_borg_stats  # type: ignore
    from lib.notifications import MailConfig  # type: ignore
    from lib.docker_manager import DockerConfig, DockerManager  # type: ignore
    from lib.vm_manager import VmConfig, VmManager  # type: ignore

    job_config = BackupJobConfig.from_config(env)
    _setup_full_logging(job_config.log_file)
    borg_config = BorgConfig.from_config(env)
    mail_config = MailConfig.from_config(env)

    lock_dir = Path(env.get("BORG_RESOURCE_LOCK_DIR", "/boot/config/borg-backup/locks"))
    ttl_seconds = int(env.get("BORG_RESOURCE_LOCK_TTL_SECONDS", "7200") or "7200")
    grace_seconds = int(env.get("BORG_RESOURCE_LOCK_GRACE_SECONDS", "60") or "60")
    heartbeat_seconds = int(env.get("BORG_RESOURCE_LOCK_HEARTBEAT_SECONDS", "20") or "20")

    lock_set = ResourceLockSet(
        lock_dir=lock_dir,
        job_key=job_key,
        ttl_seconds=ttl_seconds,
        grace_seconds=grace_seconds,
        heartbeat_seconds=heartbeat_seconds,
    )
    resources = _build_resources(env, meta)
    ok, reason = lock_set.acquire(resources)
    if not ok:
        logging.warning("Job is being skipped: %s", reason)
        return 2

    smb_session = SmbMountSession()
    try:
        smb_session = _ensure_smb_mount(env, meta)
        encryption = str(meta.get("encryption") or "repokey-blake2")
        if bool(meta.get("create_repo_if_missing", True)):
            ok_guard, guard_msg = _guard_remote_repo_init(env, meta)
            if not ok_guard:
                logging.error("Remote initialization guard blocked the run: %s", guard_msg)
                return 2
            init_exit = _init_repo_if_needed(env, encryption)
            if init_exit != 0:
                return init_exit

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
        with BackupJob(job_config, docker_manager=docker_mgr, vm_manager=vm_mgr, mail_config=mail_config) as job:
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
            if docker_mgr is not None:
                selected = docker_control["selected"] if docker_control["mode"] == "selected" else None
                job.stop_docker(selected)
            if vm_mgr is not None:
                selected = vm_control["selected"] if vm_control["mode"] == "selected" else None
                job.shutdown_vms(selected)

            runner = BorgRunner(borg_config)
            create_exit = runner.create(job_config.backup_paths, archive_prefix)
            if create_exit >= 2:
                job.set_result(create_exit, final_msg=f"borg create failed (exit {create_exit})")
                return create_exit

            maint_exit = runner.maintenance()
            exit_code = max(create_exit, maint_exit)
            job.set_result(exit_code, parse_borg_stats(job_config.log_file))
            return exit_code
    finally:
        smb_session.cleanup()
        lock_set.release()


if __name__ == "__main__":
    sys.exit(main())
