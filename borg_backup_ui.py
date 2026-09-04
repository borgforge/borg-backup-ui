#!/usr/bin/env python3
"""
borg_backup_ui.py – HTTP-Server-Daemon für das Borg Backup Web-UI

Startet einen leichtgewichtigen HTTP-Daemon (Python stdlib only, kein pip).

Verwendung:
    python3 borg_backup_ui.py          # Normal-Modus (liest borg_backup_ui.conf)
    python3 borg_backup_ui.py --dev    # Dev-Modus (nutzt test-data/)
"""

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from html import escape as _html_escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from time import perf_counter
from urllib.parse import parse_qs, urlparse

from api.auth_store import (
    UsersStoreError as _UsersStoreError,
    default_users_store as _default_users_store,
    has_any_users as _has_any_users,
    hash_password as _hash_password,
    homepage_widget_token_status as _homepage_widget_token_status,
    load_or_create_api_token as _load_or_create_api_token,
    load_ui_auth_config as _load_ui_auth_config,
    normalize_username as _normalize_username,
    parse_cookie_header as _parse_cookie_header,
    read_homepage_widget_token as _read_homepage_widget_token,
    read_sessions_store as _read_sessions_store,
    read_users_store as _read_users_store,
    safe_user_view as _safe_user_view,
    revoke_homepage_widget_token as _revoke_homepage_widget_token,
    rotate_homepage_widget_token as _rotate_homepage_widget_token,
    verify_password_hash as _verify_password_hash,
    users_file as _users_file,
    write_sessions_store as _write_sessions_store,
    write_users_store as _write_users_store,
)
from api.admin_recovery import (
    describe_admin_recovery_token as _describe_admin_recovery_token,
    recover_admin_access_with_token as _recover_admin_access_with_token,
)
from api.security_utils import mask_secrets as _mask_secrets
from api.startup_state import (
    get_startup_state as _get_startup_state,
    is_maintenance_mode as _is_maintenance_mode,
    migration_maintenance_state as _migration_maintenance_state,
    normal_startup_state as _normal_startup_state,
    set_startup_state as _set_startup_state,
)

class RateLimitExceeded(Exception):
    pass


class ApiConflictError(Exception):
    def __init__(self, message: str, code: str = "conflict") -> None:
        super().__init__(message)
        self.code = code


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _log_client(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open("/var/log/borg_backup_ui_client.log", "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        _log(f"CLIENT-LOG-FALLBACK {msg}")


def _restore_download_timeout_seconds(config: dict) -> int:
    raw = str(config.get("RESTORE_DOWNLOAD_TIMEOUT_SECONDS", "")).strip()
    if raw:
        try:
            return max(60, int(raw))
        except ValueError:
            pass
    return 6 * 60 * 60


def _start_bounded_stderr_collector(stream, *, limit: int = 8192):
    chunks: list[bytes] = []
    total = 0
    lock = threading.Lock()

    def collect() -> None:
        nonlocal total
        try:
            while True:
                data = stream.read(4096)
                if not data:
                    break
                if isinstance(data, str):
                    data = data.encode("utf-8", errors="replace")
                with lock:
                    chunks.append(data)
                    total += len(data)
                    while total > limit and chunks:
                        overflow = total - limit
                        first = chunks[0]
                        if len(first) <= overflow:
                            total -= len(chunks.pop(0))
                            continue
                        chunks[0] = first[overflow:]
                        total -= overflow
                        break
        except OSError:
            pass

    thread = threading.Thread(target=collect, name="restore-download-stderr", daemon=True)
    thread.start()

    def snapshot() -> str:
        with lock:
            data = b"".join(chunks)
        return data.decode("utf-8", errors="replace").strip()

    return thread, snapshot


APP_VERSION = "2026.09.04.1114"
APP_AUTHOR  = "Thorsten Steinberg"
APP_CONTACT_EMAIL = "thorsten.steinberg@gmx.de"
APP_REPOSITORY_URL = "https://github.com/borgforge/borg-backup-ui"

_BORG_VERSION: str = ""

def _get_borg_version() -> str:
    global _BORG_VERSION
    if not _BORG_VERSION:
        try:
            out = subprocess.check_output(["borg", "--version"], stderr=subprocess.DEVNULL, text=True)
            _BORG_VERSION = out.strip().split()[-1] if out.strip() else "unknown"
        except (subprocess.SubprocessError, OSError, IndexError):
            _BORG_VERSION = "unknown"
    return _BORG_VERSION

SCRIPT_DIR = Path(__file__).parent.resolve()
UI_DIR = SCRIPT_DIR / "ui"
BORG_BUNDLE_DIR = SCRIPT_DIR / "runtime" / "bin" / "borg"
BORG_BUNDLE_PLAIN = BORG_BUNDLE_DIR / "borg"
BORG_BUNDLE_VERSIONED = BORG_BUNDLE_DIR / "borg-linux-glibc231-x86_64-1.4.5"
BORG_STAGE_BIN = Path("/usr/local/bin/borg")
LICENSE_FILES = {
    "project": SCRIPT_DIR / "LICENSE",
    "third-party": SCRIPT_DIR / "runtime" / "licenses" / "THIRD-PARTY-NOTICES.md",
}

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def load_ui_config() -> dict:
    """Lädt borg_backup_ui.conf (KEY=VALUE), fällt auf Defaults zurück."""
    config = {
        "PORT": "8765",
        "BIND": "0.0.0.0",
        "BACKUP_SCRIPTS_DIR": "/boot/config/borg-backup",
        "BORG_SCRIPTS_DIR": str(SCRIPT_DIR / "runtime" / "scripts"),
        "PLUGIN_DIR": str(SCRIPT_DIR),
        "STATUS_DIR": "/mnt/user/backup-status",
        "DEV_MODE": "false",
        "UI_SESSION_TIMEOUT_MINUTES": "30",
        "LOG_VERBOSE_ACCESS": "false",
        "LOG_SLOW_GET_THRESHOLD_MS": "500",
        "LOG_LARGE_GET_THRESHOLD_BYTES": "262144",
    }
    conf_file = SCRIPT_DIR / "borg_backup_ui.conf"
    if conf_file.exists():
        for raw in conf_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                config[key.strip()] = val.strip().strip('"').strip("'")
    for key in list(config):
        if key in os.environ:
            config[key] = os.environ[key]
    return config


def bootstrap_data_layout(config: dict) -> None:
    """
    First-install bootstrap for canonical data layout under BACKUP_SCRIPTS_DIR:
      - config/, config/jobs/, secrets/, locks/, scripts/
      - seed backup.conf from runtime/config/backup.conf.example when missing
    """
    data_root = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    scripts_dir = data_root / "scripts"
    config_dir = data_root / "config"
    jobs_dir = config_dir / "jobs"
    secrets_dir = data_root / "secrets"
    locks_dir = data_root / "locks"

    for p in (scripts_dir, config_dir, jobs_dir, secrets_dir, locks_dir):
        p.mkdir(parents=True, exist_ok=True)

    conf_file = config_dir / "backup.conf"
    if not conf_file.exists():
        src = SCRIPT_DIR / "runtime" / "config" / "backup.conf.example"
        if src.exists():
            shutil.copy2(src, conf_file)
            _log(f"Created initial backup.conf: {conf_file}")
        else:
            conf_file.write_text("", encoding="utf-8")
            _log(f"WARNING: backup.conf.example is missing; created empty backup.conf: {conf_file}")

def setup_borg_path() -> None:
    """Prefer bundled borg binary from plugin runtime when present."""
    for candidate in (BORG_BUNDLE_PLAIN, BORG_BUNDLE_VERSIONED):
        if candidate.exists():
            try:
                candidate.chmod(0o755)
            except OSError:
                pass

    active = None
    if BORG_BUNDLE_PLAIN.is_file() and os.access(BORG_BUNDLE_PLAIN, os.X_OK):
        active = BORG_BUNDLE_PLAIN
    elif BORG_BUNDLE_VERSIONED.is_file() and os.access(BORG_BUNDLE_VERSIONED, os.X_OK):
        active = BORG_BUNDLE_VERSIONED
    elif BORG_BUNDLE_PLAIN.is_file():
        try:
            shutil.copy2(BORG_BUNDLE_PLAIN, BORG_STAGE_BIN)
            BORG_STAGE_BIN.chmod(0o755)
            if os.access(BORG_STAGE_BIN, os.X_OK):
                active = BORG_STAGE_BIN
        except OSError:
            pass
    elif BORG_BUNDLE_VERSIONED.is_file():
        try:
            shutil.copy2(BORG_BUNDLE_VERSIONED, BORG_STAGE_BIN)
            BORG_STAGE_BIN.chmod(0o755)
            if os.access(BORG_STAGE_BIN, os.X_OK):
                active = BORG_STAGE_BIN
        except OSError:
            pass

    if active is not None and active.name != "borg":
        # Ensure command name "borg" is resolvable even when only versioned binary exists.
        try:
            shutil.copy2(active, BORG_STAGE_BIN)
            BORG_STAGE_BIN.chmod(0o755)
            if os.access(BORG_STAGE_BIN, os.X_OK):
                active = BORG_STAGE_BIN
        except OSError:
            pass

    if active is not None:
        current_path = os.environ.get("PATH", "")
        prefix = f"/usr/local/bin:{BORG_BUNDLE_DIR}"
        os.environ["PATH"] = f"{prefix}:{current_path}" if current_path else prefix
        _log(f"Borg Binary aktiv: {active}")
    else:
        _log("WARNING: Bundled Borg binary is not active; using system PATH.")
def setup_lib_path(config: dict) -> bool:
    """Fügt ausschließlich plugin-runtime lib/ hinzu (kein Fallback)."""
    plugin_lib_dir = SCRIPT_DIR / "runtime" / "lib"
    if plugin_lib_dir.exists():
        # Für Importe wie `from status import ...` aus api/*
        if str(plugin_lib_dir) not in sys.path:
            sys.path.insert(0, str(plugin_lib_dir))
        # Für Importe wie `from lib.status import ...` aus runner/lib
        if str(plugin_lib_dir.parent) not in sys.path:
            sys.path.insert(0, str(plugin_lib_dir.parent))
    return plugin_lib_dir.exists()


def _wait_for_configured_data_storage(
    config: dict,
    *,
    include_runtime_paths: bool = True,
    wait_seconds: int | None = None,
    step_seconds: int | None = None,
    sleep_fn=time.sleep,
) -> bool:
    """Wait until mounts backing the configured runtime data paths are ready."""
    data_dir = str(config.get("GLOBAL_DATA_DIR", "")).strip()
    if not data_dir:
        return True

    from status import required_storage_mount, storage_mount_is_mounted

    configured_paths = [data_dir]
    if include_runtime_paths:
        configured_paths.extend(
            [
                str(config.get("STATUS_DIR", "")).strip(),
                str(config.get("RESTORE_TEST_STATUS_DIR", "")).strip(),
                str(config.get("GLOBAL_LOG_DIR", "")).strip(),
                str(config.get("GLOBAL_BORG_CACHE_BASE", "")).strip(),
            ]
        )
    required_mounts = sorted(
        {
            mount
            for raw_path in configured_paths
            if raw_path
            for mount in [required_storage_mount(Path(raw_path))]
            if mount is not None
        },
        key=str,
    )
    if not required_mounts:
        return True

    wait_seconds = max(
        0,
        int(
            wait_seconds
            if wait_seconds is not None
            else os.environ.get("BBUI_STORAGE_WAIT_SECONDS", "300")
        ),
    )
    step_seconds = max(
        1,
        int(
            step_seconds
            if step_seconds is not None
            else os.environ.get("BBUI_STORAGE_WAIT_STEP_SECONDS", "3")
        ),
    )

    pending = [mount for mount in required_mounts if not storage_mount_is_mounted(mount)]
    if not pending:
        return True

    mount_list = ", ".join(str(mount) for mount in pending)
    _log(
        "Runtime storage is not available yet, waiting up to "
        f"{wait_seconds}s for mount(s) {mount_list} "
        f"(configured data directory: {data_dir})..."
    )

    waited = 0
    while pending and waited < wait_seconds:
        current_step = min(step_seconds, wait_seconds - waited)
        sleep_fn(current_step)
        waited += current_step
        pending = [mount for mount in required_mounts if not storage_mount_is_mounted(mount)]

    if pending:
        mount_list = ", ".join(str(mount) for mount in pending)
        _log(
            "ERROR: Runtime storage mount(s) did not become available after "
            f"{waited}s: {mount_list}. Borg Backup UI was not started to prevent "
            "writes to the wrong filesystem."
        )
        return False

    _log(
        "Runtime storage became available after "
        f"{waited}s: {', '.join(str(mount) for mount in required_mounts)}"
    )
    return True


def _runtime_data_directory_configured(config: dict) -> bool:
    return bool(str(config.get("GLOBAL_DATA_DIR", "")).strip())


class BackupUIHandler(BaseHTTPRequestHandler):
    _CLIENT_LOG_BUCKET: dict[str, list[float]] = {}
    _CLIENT_LOG_LAST_SIG: dict[str, tuple[str, float]] = {}
    _CLIENT_LOG_WINDOW_SECONDS = 60.0
    _CLIENT_LOG_MAX_PER_WINDOW = 10
    _CLIENT_LOG_MAX_IPS_TRACKED = 512
    _LOGIN_FAILURES: dict[str, list[float]] = {}
    _LOGIN_FAILURES_LOCK = threading.RLock()
    _UI_SESSIONS: dict[str, dict] = {}
    _UI_SESSIONS_LOCK = threading.RLock()
    _USERS_LOCK = threading.RLock()
    config: dict = {}
    _last_json_body: dict = {}
    _extra_response_headers: list[tuple[str, str]] = []
    _refreshed_session_cookie: str = ""
    _ROLE_ORDER = {"viewer": 10, "operator": 20, "admin": 30}
    _ROUTINE_GET_PATHS = {
        "/api/auth/status",
        "/api/jobs",
        "/api/jobs/running",
        "/api/setup-status",
        "/api/status",
        "/api/system-health",
        "/api/version",
    }
    _ROUTINE_GET_PREFIXES = (
        "/api/help",
        "/api/history",
        "/api/notification-profiles",
        "/api/notification-reminders",
        "/api/reports",
        "/api/repositories",
        "/api/restore",
        "/api/restore-tests",
        "/api/schedules",
        "/api/settings/basic",
        "/api/storage",
    )

    def _security_audit(
        self,
        event: str,
        result: str,
        *,
        target: str = "",
        detail: str = "",
        actor_user: str = "",
        actor_role: str = "",
    ) -> None:
        req_id = str(getattr(self, "_current_request_id", "") or "")
        session = self._get_current_session_meta() or {}
        actor = _mask_secrets(str(actor_user or session.get("username", "") or ""))
        role = _mask_secrets(str(actor_role or session.get("role", "") or ""))
        ip = _mask_secrets(self.headers.get("X-Forwarded-For", "") or self.client_address[0] or "")
        endpoint = _mask_secrets(urlparse(self.path).path)
        tgt = _mask_secrets(str(target or ""))
        det = _mask_secrets(str(detail or ""))
        _log(
            f"SECURITY event={_mask_secrets(event)} result={_mask_secrets(result)} "
            f"user={actor} role={role} ip={ip} endpoint={endpoint} request_id={req_id} "
            f"target={tgt} detail={det}"
        )

    def _require_data_dir_ready(self) -> None:
        from config_api import read_expanded_conf, ensure_data_dirs
        conf = read_expanded_conf(self.config)
        data_dir = str(conf.get("GLOBAL_DATA_DIR", "")).strip()
        if not data_dir:
            raise RuntimeError(
                "GLOBAL_DATA_DIR is not set. Configure a primary data directory in Settings first."
            )
        ensure_data_dirs(data_dir)

    def _get_api_token(self) -> str:
        return _load_or_create_api_token(self.config)

    def _ui_auth_cfg(self) -> dict:
        return _load_ui_auth_config(self.config)

    def _auth_mode(self) -> str:
        return "users"

    def _bootstrap_required(self) -> bool:
        try:
            _read_users_store(self.config)
        except _UsersStoreError:
            return False
        return not _users_file(self.config).exists()

    def _ui_auth_enabled(self) -> bool:
        try:
            _read_users_store(self.config)
        except _UsersStoreError:
            # An existing but unreadable user store must never disable auth.
            return True
        # Only a missing file denotes a fresh installation. Any existing user
        # store keeps authentication enabled even if its admin entry needs
        # explicit local recovery.
        return _users_file(self.config).exists()

    def _auth_store_failure(self) -> str:
        try:
            _read_users_store(self.config)
        except _UsersStoreError as exc:
            return str(exc)
        return ""

    def _session_idle_timeout_seconds(self) -> int:
        timeout_min = int(self._ui_auth_cfg().get("session_timeout_minutes", 30) or 30)
        return max(5, timeout_min) * 60

    def _session_absolute_timeout_seconds(self) -> int:
        # hard limit to avoid endlessly prolonged sessions by activity
        return 12 * 60 * 60

    def _session_cookie_header(self, sid: str, max_age_seconds: int) -> str:
        return f"bbui_session={sid}; Path=/; Max-Age={int(max_age_seconds)}; HttpOnly; SameSite=Strict"

    def _load_sessions(self) -> None:
        cls = type(self)
        with cls._UI_SESSIONS_LOCK:
            if cls._UI_SESSIONS:
                return
            store = _read_sessions_store(self.config)
            now = time.time()
            out: dict[str, dict] = {}
            for item in store.get("sessions", []):
                if not isinstance(item, dict):
                    continue
                sid = str(item.get("sid", "")).strip()
                if not sid:
                    continue
                expires_at = float(item.get("expires_at", 0) or 0)
                if expires_at <= now:
                    continue
                out[sid] = item
            cls._UI_SESSIONS = out

    def _persist_sessions(self) -> None:
        cls = type(self)
        with cls._UI_SESSIONS_LOCK:
            rows = []
            for sid, meta in (cls._UI_SESSIONS or {}).items():
                if not isinstance(meta, dict):
                    continue
                item = dict(meta)
                item["sid"] = sid
                rows.append(item)
            _write_sessions_store(self.config, {"schema_version": 1, "sessions": rows})

    def _prune_sessions(self) -> None:
        self._load_sessions()
        cls = type(self)
        now = time.time()
        changed = False
        with cls._UI_SESSIONS_LOCK:
            for sid in list(cls._UI_SESSIONS.keys()):
                meta = cls._UI_SESSIONS.get(sid, {})
                exp = float(meta.get("expires_at", 0) or 0)
                if exp <= now:
                    cls._UI_SESSIONS.pop(sid, None)
                    changed = True
        if changed:
            self._persist_sessions()

    def _is_ui_session_valid(self) -> bool:
        if self._auth_store_failure():
            return False
        if not self._ui_auth_enabled():
            return True
        self._prune_sessions()
        cookies = _parse_cookie_header(self.headers.get("Cookie") or "")
        sid = str(cookies.get("bbui_session") or "").strip()
        if not sid:
            return False
        cls = type(self)
        now = time.time()
        with cls._UI_SESSIONS_LOCK:
            meta = cls._UI_SESSIONS.get(sid)
        if not isinstance(meta, dict):
            with cls._UI_SESSIONS_LOCK:
                cls._UI_SESSIONS.pop(sid, None)
            self._persist_sessions()
            return False
        exp = float(meta.get("expires_at", 0) or 0)
        created_at = float(meta.get("created_at", 0) or 0)
        if exp <= now:
            with cls._UI_SESSIONS_LOCK:
                cls._UI_SESSIONS.pop(sid, None)
            self._persist_sessions()
            return False
        if created_at > 0 and (now - created_at) > self._session_absolute_timeout_seconds():
            with cls._UI_SESSIONS_LOCK:
                cls._UI_SESSIONS.pop(sid, None)
            self._persist_sessions()
            return False
        meta["last_seen_at"] = now
        idle_sec = self._session_idle_timeout_seconds()
        meta["expires_at"] = now + idle_sec
        with cls._UI_SESSIONS_LOCK:
            cls._UI_SESSIONS[sid] = meta
        self._refreshed_session_cookie = self._session_cookie_header(sid, idle_sec)
        return True

    def _require_ui_session(self) -> bool:
        if self._is_ui_session_valid():
            return True
        if self.command == "GET":
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return False
        self._send_api_error(401, "auth_required", "Sign-in is required or the session has expired", request_id=uuid.uuid4().hex[:12])
        return False

    def _verify_user_credentials(self, username: str, password: str) -> dict | None:
        uname = _normalize_username(username)
        if not uname:
            return None
        store = _read_users_store(self.config)
        for u in store.get("users", []):
            if not isinstance(u, dict):
                continue
            if not bool(u.get("enabled", True)):
                continue
            if _normalize_username(u.get("username", "")) != uname:
                continue
            if _verify_password_hash(password, str(u.get("password_hash", ""))):
                return u
            return None
        return None

    def _is_api_authorized(self) -> bool:
        # Browser UI calls: valid UI session is sufficient.
        if self._ui_auth_enabled() and self._is_ui_session_valid():
            return True
        expected = self._get_api_token()
        if not expected:
            return False

        header_token = (self.headers.get("X-API-Token") or "").strip()
        if header_token and secrets.compare_digest(header_token, expected):
            return True

        auth_header = (self.headers.get("Authorization") or "").strip()
        if auth_header.lower().startswith("bearer "):
            bearer = auth_header[7:].strip()
            if bearer and secrets.compare_digest(bearer, expected):
                return True

        return False

    def _is_homepage_widget_authorized(self) -> bool:
        # Signed-in browser sessions may inspect the endpoint during setup.
        if self._ui_auth_enabled() and self._is_ui_session_valid():
            return True
        expected = _read_homepage_widget_token(self.config)
        if not expected:
            return False
        header_token = (self.headers.get("X-Borg-Widget-Token") or "").strip()
        if header_token and secrets.compare_digest(header_token, expected):
            return True
        auth_header = (self.headers.get("Authorization") or "").strip()
        if auth_header.lower().startswith("bearer "):
            bearer = auth_header[7:].strip()
            if bearer and secrets.compare_digest(bearer, expected):
                return True
        return False

    def _role_at_least(self, role: str, required: str) -> bool:
        have = self._ROLE_ORDER.get(str(role or "").strip().lower(), 0)
        need = self._ROLE_ORDER.get(str(required or "").strip().lower(), 9999)
        return have >= need

    def _has_valid_api_token_header(self) -> bool:
        expected = self._get_api_token()
        if not expected:
            return False
        header_token = (self.headers.get("X-API-Token") or "").strip()
        if header_token and secrets.compare_digest(header_token, expected):
            return True
        auth_header = (self.headers.get("Authorization") or "").strip()
        if auth_header.lower().startswith("bearer "):
            bearer = auth_header[7:].strip()
            if bearer and secrets.compare_digest(bearer, expected):
                return True
        return False

    def _get_current_role(self) -> str:
        # No login mode -> full access as before
        if not self._ui_auth_enabled():
            return "admin"

        # UI session role
        self._load_sessions()
        cookies = _parse_cookie_header(self.headers.get("Cookie") or "")
        sid = str(cookies.get("bbui_session") or "").strip()
        if sid:
            cls = type(self)
            with cls._UI_SESSIONS_LOCK:
                meta = cls._UI_SESSIONS.get(sid)
            if isinstance(meta, dict):
                role = str(meta.get("role", "")).strip().lower()
                if role in self._ROLE_ORDER:
                    return role

        # Explicit API token header/bearer keeps backward compatibility for automation
        if self._has_valid_api_token_header():
            return "admin"
        return "viewer"

    def _get_current_session_meta(self) -> dict | None:
        if not self._ui_auth_enabled():
            return None
        self._load_sessions()
        cookies = _parse_cookie_header(self.headers.get("Cookie") or "")
        sid = str(cookies.get("bbui_session") or "").strip()
        if not sid:
            return None
        cls = type(self)
        with cls._UI_SESSIONS_LOCK:
            meta = cls._UI_SESSIONS.get(sid)
        if not isinstance(meta, dict):
            return None
        return {
            "username": str(meta.get("username", "")).strip(),
            "role": str(meta.get("role", "")).strip().lower(),
            "mode": str(meta.get("mode", "")).strip().lower(),
        }

    def _client_ip(self) -> str:
        return str(getattr(self, "client_address", ("unknown",))[0] or "unknown")

    def _is_same_origin_request(self) -> bool:
        origin = str(self.headers.get("Origin") or "").strip()
        host = str(self.headers.get("Host") or "").strip()
        if not origin or not host:
            return False
        try:
            origin_host = urlparse(origin).netloc.strip().lower()
        except ValueError:
            return False
        return bool(origin_host and origin_host == host.strip().lower())

    def _required_role_for_request(self, path: str, method: str) -> str | None:
        p = str(path or "")
        m = str(method or "").upper()

        # Public/auth bootstrap endpoints
        if p in {"/api/auth/login", "/api/auth/status", "/api/auth/setup-admin", "/api/auth/admin-recovery", "/api/version"}:
            return None

        # Read-only endpoints
        if m == "GET" and (
            p.startswith("/api/status")
            or p.startswith("/api/system-health")
            or p.startswith("/api/notification-reminders")
            or p.startswith("/api/jobs")
            or p.startswith("/api/schedules")
            or p.startswith("/api/storage")
            or p.startswith("/api/repositories")
            or p.startswith("/api/notification-profiles")
            or p.startswith("/api/history")
            or p.startswith("/api/restore")
            or p.startswith("/api/reports")
            or p.startswith("/api/settings/basic")
            or p.startswith("/api/help")
            or p == "/api/restore-tests/plan"
        ):
            return "viewer"

        # Operator actions (run/test/restore)
        if p in {
            "/api/jobs/run",
            "/api/jobs/cancel",
            "/api/restore-tests/run",
            "/api/restore-tests/run-job",
            "/api/storage/test",
            "/api/storages/test",
            "/api/repositories/info",
            "/api/storage/smb-action",
            "/api/storage/check/run",
            "/api/restore/precheck",
            "/api/restore/start",
            "/api/auth/logout",
            "/api/auth/change-password",
            "/api/auth/logout-all-sessions",
        }:
            return "operator"

        # Settings and administrative endpoints -> admin
        if (
            p.startswith("/api/settings")
            or p.startswith("/api/storagebox")
            or p.startswith("/api/wizard")
            or p.startswith("/api/client-log")
            or p in {"/api/jobs/enabled", "/api/jobs", "/api/schedules", "/api/storages", "/api/repositories", "/api/restore-tests", "/api/restore-tests/policy"}
            or p in {"/api/repositories/key-export", "/api/repositories/key-import"}
        ):
            return "admin"

        # Safe default for unknown API routes
        return "admin"

    def _authorize_api_request(self, path: str, request_id: str) -> bool:
        auth_failure = self._auth_store_failure()
        if auth_failure:
            self._send_api_error(
                503,
                "auth_store_unavailable",
                "Authentication data is unavailable. Restore config/users.json from a trusted backup or follow the local recovery procedure.",
                request_id=request_id,
            )
            return False

        if path == "/api/widget/summary":
            if self.command == "GET" and self._is_homepage_widget_authorized():
                return self._authorize_maintenance_request(path, request_id)
            self._send_api_error(
                401,
                "widget_unauthorized",
                "The Homepage widget token is missing or invalid",
                request_id=request_id,
            )
            return False

        auth_free_paths = {"/api/auth/login", "/api/auth/status", "/api/auth/setup-admin", "/api/auth/admin-recovery", "/api/version"}
        if self.command in {"POST", "PUT", "DELETE"}:
            if not self._has_valid_api_token_header() and not self._is_same_origin_request():
                self._send_api_error(
                    403,
                    "csrf_origin_mismatch",
                    "Invalid Origin header",
                    request_id=request_id,
                )
                return False
        if path not in auth_free_paths and not self._is_api_authorized():
            self._send_api_error(
                401,
                "unauthorized",
                "The API token is missing or invalid",
                request_id=request_id,
            )
            return False
        required_role = self._required_role_for_request(path, self.command)
        if required_role:
            role = self._get_current_role()
            if not self._role_at_least(role, required_role):
                self._send_api_error(
                    403,
                    "forbidden",
                    f"Role '{required_role}' is required",
                    request_id=request_id,
                )
                return False
        return self._authorize_maintenance_request(path, request_id)

    def _authorize_maintenance_request(self, path: str, request_id: str) -> bool:
        if not _is_maintenance_mode(self.config):
            return True
        method = str(self.command or "").upper()
        allowed = path in {
            "/api/auth/login",
            "/api/auth/logout",
            "/api/auth/status",
            "/api/auth/setup-admin",
            "/api/auth/admin-recovery",
            "/api/version",
            "/api/system-health",
            "/api/setup-status",
        }
        allowed = allowed or (method == "GET" and path in {"/api/settings", "/api/settings/basic"})
        allowed = allowed or (method == "POST" and path == "/api/settings/support-bundle")
        if allowed:
            return True
        state = _get_startup_state(self.config)
        failed = ", ".join(state.get("failed_migrations") or []) or "startup migration registry"
        self._send_api_error(
            503,
            "maintenance_mode",
            f"Normal operation is blocked because startup migration failed: {failed}. Review System Health & Migration or create a support bundle.",
            request_id=request_id,
        )
        return False

    def _handle_direct_api(self, fn) -> None:
        request_id = uuid.uuid4().hex[:12]
        self._current_request_id = request_id
        self._refreshed_session_cookie = ""
        try:
            path = urlparse(self.path).path
            if self._authorize_api_request(path, request_id):
                fn()
        finally:
            self._current_request_id = ""
            self._refreshed_session_cookie = ""

    def _send_refreshed_session_header(self) -> None:
        if self._refreshed_session_cookie:
            self.send_header("Set-Cookie", self._refreshed_session_cookie)

    # ── Routing ───────────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/setup-admin":
            self._serve_setup_admin_page()
            return
        if path == "/admin-recovery":
            self._serve_admin_recovery_page(parsed.query)
            return
        if path == "/login":
            if self._bootstrap_required():
                self.send_response(302)
                self.send_header("Location", "/setup-admin")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return
            self._serve_login_page()
            return
        if path in ("/", "/index.html"):
            if self._bootstrap_required():
                self.send_response(302)
                self.send_header("Location", "/setup-admin")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return
            if self._ui_auth_enabled() and not self._is_ui_session_valid():
                self.send_response(302)
                self.send_header("Location", "/login")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return
            self._serve_file(UI_DIR / "index.html", allowed_root=UI_DIR)
        elif path.startswith("/ui/"):
            # Static UI assets must stay directly reachable, otherwise browsers receive
            # HTML redirects for JS/CSS and fail with MIME/syntax errors on /login.
            self._serve_file(UI_DIR / path[4:], allowed_root=UI_DIR)
        elif path == "/api/jobs/log/stream":
            qs = parse_qs(parsed.query)
            job_key = (qs.get("job") or [""])[0]
            self._handle_direct_api(lambda: self._handle_sse(job_key))
        elif path == "/api/restore-tests/log/stream":
            self._handle_direct_api(lambda: self._handle_sse("restore_test"))
        elif path == "/api/restore/download":
            self._handle_direct_api(lambda: self._handle_restore_download(parsed))
        elif path == "/api/storage/check/stream":
            self._handle_direct_api(self._handle_check_sse)
        else:
            routes = {
                "/api/version": lambda: {
                    "version": APP_VERSION,
                    "author": APP_AUTHOR,
                    "borg_version": _get_borg_version(),
                    "contact_email": APP_CONTACT_EMAIL,
                    "repository_url": APP_REPOSITORY_URL,
                    "startup_state": _public_startup_state(self.config),
                },
                "/api/licenses": lambda: self._get_license_file(parsed.query),
                "/api/status": self._get_status,
                "/api/system-health": self._get_system_health,
                "/api/notification-reminders/diagnostics": self._get_notification_reminder_diagnostics,
                "/api/jobs": self._get_jobs,
                "/api/jobs/running": self._get_running,
                "/api/schedules": self._get_schedules,
                "/api/storage": self._get_storage,
                "/api/repositories": self._get_repositories,
                "/api/notification-profiles": lambda: self._get_apprise_profiles(parsed.query),
                "/api/notification-profiles/providers": self._get_apprise_profile_providers,
                "/api/repositories/browse": lambda: self._get_repository_directories(parsed.query),
                "/api/repositories/archives": lambda: self._get_repository_archives(parsed.query),
                "/api/settings": self._get_settings,
                "/api/settings/basic": self._get_settings_basic,
                "/api/setup-status": self._get_setup_status,
                "/api/settings/backup-history": self._get_settings_backup_history,
                "/api/settings/factory-reset/status": self._get_factory_reset_status,
                "/api/settings/jobs-export": lambda: self._get_settings_jobs_export(parsed.query),
                "/api/history": lambda: self._get_history(parsed.query),
                "/api/restore-tests": self._get_restore_tests,
                "/api/restore-tests/plan": self._get_restore_tests_plan,
                "/api/restore-tests/running": self._get_rt_running,
                "/api/restore/archives": lambda: self._get_restore_archives(parsed.query),
                "/api/restore/files": lambda: self._get_restore_files(parsed.query),
                "/api/restore/download-check": lambda: self._get_restore_download_check(parsed.query),
                "/api/restore/repo-stats": lambda: self._get_repo_stats(parsed.query),
                "/api/restore/target-dirs": lambda: self._get_restore_target_dirs(parsed.query),
                "/api/restore/runs": lambda: self._get_restore_runs(parsed.query),
                "/api/restore/state": lambda: self._get_restore_state(parsed.query),
                "/api/restore/history": lambda: self._get_restore_history(parsed.query),
                "/api/restore/history/detail": lambda: self._get_restore_history_detail(parsed.query),
                "/api/reports/jobs": self._get_report_jobs,
                "/api/reports/data": lambda: self._get_report_data(parsed.query),
                "/api/history/log": lambda: self._get_log_file(parsed.query),
                "/api/wizard/job": lambda: self._get_wizard_job(parsed.query),
                "/api/wizard/source-dirs": lambda: self._get_wizard_source_dirs(parsed.query),
                "/api/wizard/runtime-inventory": self._get_wizard_runtime_inventory,
                "/api/storage/check/jobs": self._get_check_jobs,
                "/api/storage/check/state": self._get_check_state,
                "/api/storagebox/deploy/state": lambda: self._get_storagebox_deploy_state(parsed.query),
                "/api/auth/status": self._get_auth_status,
                "/api/auth/users": self._get_auth_users,
                "/api/widget/summary": self._get_homepage_widget_summary,
            }
            fn = routes.get(path)
            if fn is None:
                self.send_error(404, "Not found")
                return
            self._handle_api(fn)

    def do_POST(self):
        path = urlparse(self.path).path
        routes = {
            "/api/jobs/run": self._post_run_job,
            "/api/jobs/cancel": self._post_cancel_job,
            "/api/restore-tests/run": self._post_run_restore_test,
            "/api/restore-tests/run-job": self._post_run_restore_test_job,
            "/api/storage/test": self._post_test_repo,
            "/api/storages": self._post_storage_target,
            "/api/storages/test": self._post_storage_target_test,
            "/api/repositories": self._post_repository,
            "/api/notification-profiles": self._post_apprise_profile,
            "/api/notification-profiles/validate": self._post_apprise_profile_validate,
            "/api/notification-profiles/test": self._post_apprise_profile_test,
            "/api/repositories/validate": self._post_repository_validate,
            "/api/repositories/info": self._post_repository_info,
            "/api/repositories/lifecycle": self._post_repository_lifecycle,
            "/api/repositories/key-export": self._post_repository_key_export,
            "/api/repositories/key-import": self._post_repository_key_import,
            "/api/repositories/key-backup-preview": self._post_repository_key_backup_preview,
            "/api/repositories/key-backup-import": self._post_repository_key_backup_import,
            "/api/storage/smb-action": self._post_storage_smb_action,
            "/api/wizard/preview": self._post_wizard_preview,
            "/api/wizard/save": self._post_wizard_save,
            "/api/settings/test-smtp": self._post_test_smtp,
            "/api/settings/weekly-report/send": self._post_send_weekly_report,
            "/api/settings/backup-restore": self._post_settings_backup_restore,
            "/api/settings/backup-delete": self._post_settings_backup_delete,
            "/api/settings/backup-delete-keep-latest": self._post_settings_backup_delete_keep_latest,
            "/api/settings/backup-diff": self._post_settings_backup_diff,
            "/api/setup-wizard": self._post_setup_wizard,
            "/api/settings/migration-backups-cleanup": self._post_settings_migration_backups_cleanup,
            "/api/settings/jobs-import": self._post_settings_jobs_import,
            "/api/settings/jobs-import-preview": self._post_settings_jobs_import_preview,
            "/api/settings/jobs-export-secure": self._post_settings_jobs_export_secure,
            "/api/settings/jobs-import-secure-preview": self._post_settings_jobs_import_secure_preview,
            "/api/settings/jobs-import-secure": self._post_settings_jobs_import_secure,
            "/api/settings/repository-keys-export": self._post_settings_repository_keys_export,
            "/api/settings/secrets-backup-export": self._post_settings_secrets_backup_export,
            "/api/settings/secrets-backup-preview": self._post_settings_secrets_backup_preview,
            "/api/settings/secrets-backup-import": self._post_settings_secrets_backup_import,
            "/api/settings/profile-secrets-export": self._post_settings_profile_secrets_export,
            "/api/settings/profile-secrets-preview": self._post_settings_profile_secrets_preview,
            "/api/settings/profile-secrets-import": self._post_settings_profile_secrets_import,
            "/api/settings/support-bundle": self._post_settings_support_bundle,
            "/api/settings/factory-reset": self._post_factory_reset,
            "/api/system-health/runtime-recovery/ack": self._post_runtime_recovery_ack,
            "/api/settings/usb-profiles-status": self._post_settings_usb_profiles_status,
            "/api/settings/smb-profiles-status": self._post_settings_smb_profiles_status,
            "/api/storagebox/key-status": self._post_storagebox_key_status,
            "/api/storagebox/key-generate": self._post_storagebox_key_generate,
            "/api/storagebox/key-public": self._post_storagebox_key_public,
            "/api/storagebox/key-deploy": self._post_storagebox_key_deploy,
            "/api/storagebox/test": self._post_storagebox_test,
            "/api/storagebox/deploy/start": self._post_storagebox_deploy_start,
            "/api/storagebox/deploy/input": self._post_storagebox_deploy_input,
            "/api/storagebox/deploy/cancel": self._post_storagebox_deploy_cancel,
            "/api/storage/check/run": self._post_run_check,
            "/api/restore/precheck": self._post_restore_precheck,
            "/api/restore/start": self._post_restore_start,
            "/api/client-log": self._post_client_log,
            "/api/auth/login": self._post_auth_login,
            "/api/auth/logout": self._post_auth_logout,
            "/api/auth/setup-admin": self._post_auth_setup_admin,
            "/api/auth/admin-recovery": self._post_auth_admin_recovery,
            "/api/auth/users": self._post_auth_user_create,
            "/api/auth/users/password-reset": self._post_auth_user_password_reset,
            "/api/auth/change-password": self._post_auth_change_password,
            "/api/auth/logout-all-sessions": self._post_auth_logout_all_sessions,
            "/api/settings/homepage-widget-token": self._post_homepage_widget_token,
        }
        fn = routes.get(path)
        if fn is None:
            self.send_error(404, "Not found")
            return
        self._handle_api(fn)

    def do_PUT(self):
        path = urlparse(self.path).path
        routes = {
            "/api/storage": self._put_storage,
            "/api/settings": self._put_settings,
            "/api/schedules": self._put_schedule,
            "/api/jobs/enabled": self._put_job_enabled,
            "/api/auth/users": self._put_auth_user_update,
            "/api/restore-tests/policy": self._put_restore_test_policy,
            "/api/notification-profiles": self._put_apprise_profile,
        }
        fn = routes.get(path)
        if fn is None:
            self.send_error(404, "Not found")
            return
        self._handle_api(fn)

    def do_DELETE(self):
        path = urlparse(self.path).path
        routes = {
            "/api/schedules": self._delete_schedule,
            "/api/jobs": self._delete_job,
            "/api/restore-tests": self._delete_restore_test,
            "/api/restore/history": self._delete_restore_history,
            "/api/repositories": self._delete_repository,
            "/api/notification-profiles": self._delete_apprise_profile,
            "/api/auth/users": self._delete_auth_user,
            "/api/settings/homepage-widget-token": self._delete_homepage_widget_token,
        }
        fn = routes.get(path)
        if fn is None:
            self.send_error(404, "Not found")
            return
        self._handle_api(fn)

    # ── API-Handler ───────────────────────────────────────────────────────────

    def _get_status(self) -> dict:
        from status_api import get_status_data
        return get_status_data(self.config)

    def _get_homepage_widget_summary(self) -> dict:
        from homepage_widget_api import build_homepage_widget_summary
        return build_homepage_widget_summary(self.config)

    def _get_license_file(self, query: str = "") -> dict:
        qs = parse_qs(query or "")
        license_id = str((qs.get("id") or [""])[0] or "").strip()
        path = LICENSE_FILES.get(license_id)
        if path is None:
            exc = ValueError("Unknown license file.")
            exc.api_code = "unknown_license_file"
            exc.api_status = 404
            raise exc
        text = path.read_text(encoding="utf-8")
        return {
            "id": license_id,
            "path": str(path.relative_to(SCRIPT_DIR)),
            "content": text,
            "format": "markdown" if path.suffix.lower() == ".md" else "text",
        }

    def _get_apprise_profiles(self, query: str = "") -> dict:
        from apprise_profiles_api import get_profile, list_profiles

        qs = parse_qs(query or "")
        profile_id = (qs.get("id") or qs.get("profile_id") or [""])[0]
        if str(profile_id or "").strip():
            return get_profile(self.config, str(profile_id))
        return list_profiles(self.config)

    def _get_apprise_profile_providers(self) -> dict:
        from apprise_profiles_api import get_supported_providers

        return get_supported_providers(self.config)

    def _post_apprise_profile(self) -> dict:
        from apprise_profiles_api import create_profile

        return create_profile(self.config, self._read_json_body())

    def _put_apprise_profile(self) -> dict:
        from apprise_profiles_api import update_profile

        body = self._read_json_body()
        profile_id = str(body.get("id") or body.get("profile_id") or "").strip()
        if not profile_id:
            raise ValueError("profile_id is required")
        return update_profile(self.config, profile_id, body)

    def _delete_apprise_profile(self) -> dict:
        from apprise_profiles_api import AppriseProfileConflict, delete_profile

        qs = parse_qs(urlparse(self.path).query)
        profile_id = (qs.get("id") or qs.get("profile_id") or [""])[0]
        if not str(profile_id or "").strip():
            raise ValueError("profile_id is required")
        try:
            return delete_profile(self.config, str(profile_id))
        except AppriseProfileConflict as exc:
            raise ApiConflictError(str(exc), exc.code) from exc

    def _post_apprise_profile_validate(self) -> dict:
        from apprise_profiles_api import validate_profile_payload

        return validate_profile_payload(self.config, self._read_json_body())

    def _post_apprise_profile_test(self) -> dict:
        from apprise_profiles_api import test_profile

        return test_profile(self.config, self._read_json_body())

    def _get_factory_reset_status(self) -> dict:
        from factory_reset_api import factory_reset_status

        return factory_reset_status(self.config)

    def _post_factory_reset(self) -> dict:
        from factory_reset_api import (
            FactoryResetBlocked,
            schedule_factory_reset,
            validate_factory_reset_request,
        )

        body = self._read_json_body()
        session = self._get_current_session_meta() or {}
        username = _normalize_username(session.get("username", ""))
        role = str(session.get("role", "")).strip().lower()
        if role != "admin" or not username:
            raise PermissionError("An authenticated administrator is required")
        password = str(body.get("current_password") or "")
        if not password or not self._verify_user_credentials(username, password):
            self._security_audit("factory_reset", "failed", target=username, detail="invalid_current_password")
            raise PermissionError("The current administrator password is invalid")
        try:
            status = validate_factory_reset_request(self.config, body)
        except FactoryResetBlocked as exc:
            self._security_audit("factory_reset", "blocked", target=username, detail=str(exc))
            raise ApiConflictError(str(exc), "factory_reset_blocked") from exc
        try:
            result = schedule_factory_reset(
                self.config,
                status,
                actor=username,
                request_id=str(getattr(self, "_current_request_id", "") or ""),
                script_dir=SCRIPT_DIR,
            )
        except FactoryResetBlocked as exc:
            raise ApiConflictError(str(exc), "factory_reset_pending") from exc
        self._security_audit("factory_reset", "scheduled", target=username)
        return result

    def _get_auth_status(self) -> dict:
        mode = self._auth_mode()
        self._prune_sessions()
        current = self._get_current_session_meta() or {}
        self._load_sessions()
        cls = type(self)
        current_user = _normalize_username(current.get("username", ""))
        current_role = str(current.get("role", "")).strip().lower()
        with cls._UI_SESSIONS_LOCK:
            total_sessions = len(cls._UI_SESSIONS)
            own_sessions = 0
            if current_user:
                own_sessions = sum(
                    1 for meta in cls._UI_SESSIONS.values()
                    if _normalize_username(meta.get("username", "")) == current_user
                )
        return {
            "auth_enabled": self._ui_auth_enabled(),
            "authenticated": self._is_ui_session_valid(),
            "session_timeout_minutes": int(self._ui_auth_cfg().get("session_timeout_minutes", 30) or 30),
            "session_absolute_timeout_minutes": int(self._session_absolute_timeout_seconds() / 60),
            "auth_mode": mode,
            "bootstrap_required": self._bootstrap_required(),
            "current_user": str(current.get("username", "")).strip(),
            "current_role": str(current.get("role", "")).strip(),
            "active_sessions_own": own_sessions,
            "active_sessions_total": total_sessions if current_role == "admin" else None,
        }

    def _get_auth_users(self) -> dict:
        store = _read_users_store(self.config)
        users = [_safe_user_view(u) for u in store.get("users", []) if isinstance(u, dict)]
        users.sort(key=lambda x: x.get("username", ""))
        current = self._get_current_session_meta() or {}
        return {
            "users": users,
            "current_user": str(current.get("username", "")).strip(),
            "current_role": str(current.get("role", "")).strip(),
            "auth_mode": self._auth_mode(),
        }

    def _post_auth_login(self) -> dict:
        body = self._read_json_body()
        if self._bootstrap_required():
            raise PermissionError("Create the administrator account first")
        username = str(body.get("username", ""))
        password = str(body.get("password", ""))
        ip = self._client_ip()
        session_user = ""
        session_role = ""
        if not self._ui_auth_enabled():
            return {"ok": True, "auth_enabled": False}
        now = time.time()
        cls = type(self)
        with cls._LOGIN_FAILURES_LOCK:
            attempts = [t for t in cls._LOGIN_FAILURES.get(ip, []) if (now - t) < 300.0]
            cls._LOGIN_FAILURES[ip] = attempts
            if len(attempts) >= 5:
                raise RateLimitExceeded("Too many failed sign-in attempts. Try again later.")
        user = self._verify_user_credentials(username, password)
        if not user:
            with cls._LOGIN_FAILURES_LOCK:
                attempts = [t for t in cls._LOGIN_FAILURES.get(ip, []) if (now - t) < 300.0]
                attempts.append(now)
                cls._LOGIN_FAILURES[ip] = attempts
            self._security_audit("auth_login", "failed", target=_normalize_username(username), detail="invalid_credentials")
            raise PermissionError("Sign-in failed")
        with cls._LOGIN_FAILURES_LOCK:
            cls._LOGIN_FAILURES.pop(ip, None)
        session_user = _normalize_username(user.get("username", ""))
        session_role = str(user.get("role", "")).strip().lower() or "admin"
        try:
            store = _read_users_store(self.config)
            users = [u for u in store.get("users", []) if isinstance(u, dict)]
            now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            for u in users:
                if _normalize_username(u.get("username", "")) == session_user:
                    u["last_login_at"] = now_iso
                    u["updated_at"] = now_iso
                    break
            store["users"] = users
            _write_users_store(self.config, store)
        except OSError:
            pass
        sid = secrets.token_urlsafe(32)
        now = time.time()
        idle_sec = self._session_idle_timeout_seconds()
        self._load_sessions()
        cls = type(self)
        with cls._UI_SESSIONS_LOCK:
            cls._UI_SESSIONS[sid] = {
                "mode": "users",
                "username": session_user,
                "role": session_role,
                "created_at": now,
                "last_seen_at": now,
                "expires_at": now + idle_sec,
            }
        self._persist_sessions()
        self._extra_response_headers.append(
            ("Set-Cookie", self._session_cookie_header(sid, idle_sec))
        )
        self._security_audit("auth_login", "ok", actor_user=session_user, actor_role=session_role)
        return {"ok": True, "auth_enabled": True, "auth_mode": "users", "username": session_user, "role": session_role}

    def _post_auth_logout(self) -> dict:
        cookies = _parse_cookie_header(self.headers.get("Cookie") or "")
        sid = str(cookies.get("bbui_session") or "").strip()
        self._load_sessions()
        cls = type(self)
        if sid:
            with cls._UI_SESSIONS_LOCK:
                cls._UI_SESSIONS.pop(sid, None)
            self._persist_sessions()
        self._extra_response_headers.append(("Set-Cookie", "bbui_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"))
        self._extra_response_headers.append(("Set-Cookie", "bbui_api_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"))
        self._security_audit("auth_logout", "ok")
        return {"ok": True}

    def _post_auth_change_password(self) -> dict:
        body = self._read_json_body()
        current_password = str(body.get("current_password", ""))
        new_password = str(body.get("new_password", ""))
        new_password_confirm = str(body.get("new_password_confirm", ""))
        if len(new_password) < 12:
            raise ValueError("The new password must contain at least 12 characters")
        if new_password != new_password_confirm:
            raise ValueError("The password confirmation does not match")

        session = self._get_current_session_meta() or {}
        username = _normalize_username(session.get("username", ""))
        if not username:
            raise PermissionError("No active user session")

        user = self._verify_user_credentials(username, current_password)
        if not user:
            self._security_audit("auth_change_password", "failed", target=username, detail="invalid_current_password")
            raise PermissionError("The current password is invalid")

        cls = type(self)
        with cls._USERS_LOCK:
            store = _read_users_store(self.config)
            users = [u for u in store.get("users", []) if isinstance(u, dict)]
            idx = -1
            for i, u in enumerate(users):
                if _normalize_username(u.get("username", "")) == username:
                    idx = i
                    break
            if idx < 0:
                raise ValueError("User not found")
            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            users[idx]["password_hash"] = _hash_password(new_password)
            users[idx]["updated_at"] = now
            store["users"] = users
            _write_users_store(self.config, store)
        self._security_audit("auth_change_password", "ok", target=username)
        return {"ok": True, "password_changed": username}

    def _post_auth_logout_all_sessions(self) -> dict:
        body = self._read_json_body()
        scope = str(body.get("scope", "current")).strip().lower()
        if scope not in {"current", "all"}:
            scope = "current"

        session = self._get_current_session_meta() or {}
        current_username = _normalize_username(session.get("username", ""))
        current_role = str(session.get("role", "")).strip().lower()
        if not current_username:
            self._security_audit("auth_logout_all_sessions", "failed", detail="no_active_session")
            raise PermissionError("No active user session")

        self._load_sessions()
        cookies = _parse_cookie_header(self.headers.get("Cookie") or "")
        current_sid = str(cookies.get("bbui_session") or "").strip()
        cls = type(self)

        removed = 0
        with cls._UI_SESSIONS_LOCK:
            if scope == "all":
                if current_role != "admin":
                    self._security_audit("auth_logout_all_sessions", "failed", target=current_username, detail="admin_required_for_scope_all")
                    raise PermissionError("Only an administrator may terminate all sessions")
                removed = len(cls._UI_SESSIONS)
                cls._UI_SESSIONS = {}
            else:
                stale = [sid for sid, meta in cls._UI_SESSIONS.items()
                         if _normalize_username(meta.get("username", "")) == current_username]
                for sid in stale:
                    cls._UI_SESSIONS.pop(sid, None)
                removed = len(stale)
        self._persist_sessions()

        if scope == "all" or current_sid:
            self._extra_response_headers.append(("Set-Cookie", "bbui_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"))
            self._extra_response_headers.append(("Set-Cookie", "bbui_api_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"))
        self._security_audit("auth_logout_all_sessions", "ok", target=current_username, detail=f"scope={scope},removed={removed}")
        return {"ok": True, "scope": scope, "removed_sessions": removed}

    def _post_auth_setup_admin(self) -> dict:
        if not self._bootstrap_required():
            raise ValueError("Administrator setup is not required")
        body = self._read_json_body()
        username = _normalize_username(body.get("username", ""))
        password = str(body.get("password", ""))
        password_confirm = str(body.get("password_confirm", ""))
        if not username:
            raise ValueError("Username is required")
        if not re.fullmatch(r"[a-z0-9._-]{3,64}", username):
            raise ValueError("Username is invalid (3-64 characters: a-z, 0-9, ., _, -)")
        if len(password) < 12:
            raise ValueError("Password must contain at least 12 characters")
        if password != password_confirm:
            raise ValueError("The password confirmation does not match")

        cls = type(self)
        with cls._USERS_LOCK:
            if _has_any_users(self.config):
                raise ValueError("Administrator setup is not required")
            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            store = _default_users_store()
            store["users"] = [{
                "id": f"u_{secrets.token_hex(8)}",
                "username": username,
                "password_hash": _hash_password(password),
                "role": "admin",
                "enabled": True,
                "created_at": now,
                "updated_at": now,
                "last_login_at": "",
            }]
            _write_users_store(self.config, store)
        self._security_audit("auth_setup_admin", "ok", target=username)
        return {"ok": True, "created": True, "username": username}

    def _post_auth_admin_recovery(self) -> dict:
        body = self._read_json_body()
        token = str(body.get("token", "")).strip()
        password = str(body.get("password", ""))
        password_confirm = str(body.get("password_confirm", ""))
        if len(password) < 12:
            raise ValueError("Password must contain at least 12 characters")
        if password != password_confirm:
            raise ValueError("The password confirmation does not match")

        result = _recover_admin_access_with_token(self.config, token, password)
        username = str(result.get("username", "")).strip()
        cls = type(self)
        with cls._UI_SESSIONS_LOCK:
            cls._UI_SESSIONS = {}
        self._extra_response_headers.append(("Set-Cookie", "bbui_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"))
        self._extra_response_headers.append(("Set-Cookie", "bbui_api_token=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"))
        self._security_audit("auth_admin_recovery", "ok", target=username)
        return {"ok": True, "username": username, "sessions_invalidated": True}

    def _post_auth_user_create(self) -> dict:
        body = self._read_json_body()
        username = _normalize_username(body.get("username", ""))
        password = str(body.get("password", ""))
        role = str(body.get("role", "viewer")).strip().lower()
        if role not in {"viewer", "operator", "admin"}:
            raise ValueError("Invalid role")
        if not username:
            raise ValueError("Username is required")
        if not re.fullmatch(r"[a-z0-9._-]{3,64}", username):
            raise ValueError("Username is invalid (3-64 characters: a-z, 0-9, ., _, -)")
        if len(password) < 12:
            raise ValueError("Password must contain at least 12 characters")
        cls = type(self)
        with cls._USERS_LOCK:
            store = _read_users_store(self.config)
            users = [u for u in store.get("users", []) if isinstance(u, dict)]
            if any(_normalize_username(u.get("username", "")) == username for u in users):
                raise ValueError("Username already exists")
            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            users.append({
                "id": f"u_{secrets.token_hex(8)}",
                "username": username,
                "password_hash": _hash_password(password),
                "role": role,
                "enabled": True,
                "created_at": now,
                "updated_at": now,
                "last_login_at": "",
            })
            store["users"] = users
            _write_users_store(self.config, store)
        self._security_audit("auth_user_create", "ok", target=username, detail=f"role={role}")
        return {"ok": True, "created": username}

    def _put_auth_user_update(self) -> dict:
        body = self._read_json_body()
        username = _normalize_username(body.get("username", ""))
        if not username:
            raise ValueError("Username is required")
        role = body.get("role")
        enabled = body.get("enabled")
        if role is not None:
            role = str(role).strip().lower()
            if role not in {"viewer", "operator", "admin"}:
                raise ValueError("Invalid role")
        if enabled is not None:
            enabled = bool(enabled)

        cls = type(self)
        with cls._USERS_LOCK:
            store = _read_users_store(self.config)
            users = [u for u in store.get("users", []) if isinstance(u, dict)]
            idx = -1
            for i, u in enumerate(users):
                if _normalize_username(u.get("username", "")) == username:
                    idx = i
                    break
            if idx < 0:
                raise ValueError("User not found")

            current = users[idx]
            new_role = role if role is not None else str(current.get("role", "viewer")).strip().lower()
            new_enabled = enabled if enabled is not None else bool(current.get("enabled", True))
            was_admin_enabled = (str(current.get("role", "")).strip().lower() == "admin" and bool(current.get("enabled", True)))
            will_admin_enabled = (new_role == "admin" and bool(new_enabled))

            if was_admin_enabled and not will_admin_enabled:
                active_admins = [
                    u for u in users
                    if str(u.get("role", "")).strip().lower() == "admin"
                    and bool(u.get("enabled", True))
                    and _normalize_username(u.get("username", "")) != username
                ]
                if not active_admins:
                    raise ValueError("The last active administrator cannot be disabled or demoted")

            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            current["role"] = new_role
            current["enabled"] = bool(new_enabled)
            current["updated_at"] = now
            users[idx] = current
            store["users"] = users
            _write_users_store(self.config, store)
        self._security_audit("auth_user_update", "ok", target=username, detail=f"role={new_role},enabled={bool(new_enabled)}")
        return {"ok": True, "updated": username}

    def _post_auth_user_password_reset(self) -> dict:
        body = self._read_json_body()
        username = _normalize_username(body.get("username", ""))
        password = str(body.get("password", ""))
        if not username:
            raise ValueError("Username is required")
        if len(password) < 12:
            raise ValueError("Password must contain at least 12 characters")
        cls = type(self)
        with cls._USERS_LOCK:
            store = _read_users_store(self.config)
            users = [u for u in store.get("users", []) if isinstance(u, dict)]
            idx = -1
            for i, u in enumerate(users):
                if _normalize_username(u.get("username", "")) == username:
                    idx = i
                    break
            if idx < 0:
                raise ValueError("User not found")
            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            users[idx]["password_hash"] = _hash_password(password)
            users[idx]["updated_at"] = now
            store["users"] = users
            _write_users_store(self.config, store)
        self._security_audit("auth_user_password_reset", "ok", target=username)
        return {"ok": True, "password_reset": username}

    def _delete_auth_user(self) -> dict:
        body = self._read_json_body()
        username = _normalize_username(body.get("username", ""))
        if not username:
            raise ValueError("Username is required")

        current = self._get_current_session_meta() or {}
        current_username = _normalize_username(current.get("username", ""))
        if current_username and current_username == username:
            raise ValueError("The currently signed-in user cannot be deleted")

        cls = type(self)
        with cls._USERS_LOCK:
            store = _read_users_store(self.config)
            users = [u for u in store.get("users", []) if isinstance(u, dict)]
            idx = -1
            for i, u in enumerate(users):
                if _normalize_username(u.get("username", "")) == username:
                    idx = i
                    break
            if idx < 0:
                raise ValueError("User not found")

            victim = users[idx]
            is_admin_enabled = (
                str(victim.get("role", "")).strip().lower() == "admin"
                and bool(victim.get("enabled", True))
            )
            if is_admin_enabled:
                active_admins = [
                    u for u in users
                    if str(u.get("role", "")).strip().lower() == "admin"
                    and bool(u.get("enabled", True))
                    and _normalize_username(u.get("username", "")) != username
                ]
                if not active_admins:
                    raise ValueError("The last active administrator cannot be deleted")

            del users[idx]
            store["users"] = users
            _write_users_store(self.config, store)
        self._security_audit("auth_user_delete", "ok", target=username)

        # Sessions des gelöschten Benutzers sofort invalidieren
        self._load_sessions()
        cls = type(self)
        with cls._UI_SESSIONS_LOCK:
            stale_sids = [
                sid for sid, meta in cls._UI_SESSIONS.items()
                if _normalize_username(meta.get("username", "")) == username
            ]
            for sid in stale_sids:
                cls._UI_SESSIONS.pop(sid, None)
        self._persist_sessions()
        return {"ok": True, "deleted": username}

    def _get_system_health(self) -> dict:
        from system_health_api import get_system_health_data
        return get_system_health_data(self.config)

    def _post_runtime_recovery_ack(self) -> dict:
        body = self._read_json_body()
        entry_id = str(body.get("id") or "").strip()
        if not entry_id:
            raise ValueError("id is required")
        runtime_lib = SCRIPT_DIR / "runtime" / "lib"
        if str(runtime_lib) not in sys.path:
            sys.path.insert(0, str(runtime_lib))
        from runtime_recovery import acknowledge_runtime_recovery, runtime_recovery_file_from_env
        state_file = runtime_recovery_file_from_env(self.config)
        removed = acknowledge_runtime_recovery(state_file, entry_id)
        if not removed:
            raise FileNotFoundError("Runtime recovery entry not found")
        return {"ok": True, "removed": entry_id}

    def _get_jobs(self) -> dict:
        from jobs_api import list_jobs
        latest = {}
        try:
            from status_api import get_status_data
            status = get_status_data(self.config)
            for b in status.get("backups", []):
                key = str(b.get("key", ""))
                if not key:
                    continue
                latest[key] = b
                latest.setdefault(key.lower(), b)
        except Exception as exc:
            self.log_message("WARN /api/jobs status fallback active: %s", str(exc))
        return {"jobs": list_jobs(self.config, latest)}

    def _get_running(self) -> dict:
        from jobs_api import get_all_runtime_states
        return get_all_runtime_states(self.config)

    def _get_schedules(self) -> dict:
        from schedule_api import get_schedules, prune_orphaned_schedules
        prune_orphaned_schedules(self.config, log_fn=self.log_message)
        return get_schedules(self.config)

    def _put_schedule(self) -> dict:
        from schedule_api import save_schedule
        body = self._read_json_body()
        job_key = body.get("job_key", "")
        cron    = body.get("cron", "")
        enabled = bool(body.get("enabled", True))
        if not job_key or not cron:
            raise ValueError("job_key and cron are required")
        result = save_schedule(self.config, job_key, cron, enabled)
        return {"saved": True, **result}

    def _put_job_enabled(self) -> dict:
        from jobs_api import get_jobs_meta_dir, resolve_data_root, resolve_scripts_dir
        body = self._read_json_body()
        job_key = str(body.get("job_key", "")).strip()
        enabled = bool(body.get("enabled", True))
        if not job_key:
            raise ValueError("job_key is required")
        scripts_dir = resolve_scripts_dir(self.config)
        data_root = resolve_data_root(self.config)
        meta_file = get_jobs_meta_dir(scripts_dir, data_root) / f"{job_key}.json"
        if not meta_file.exists():
            raise FileNotFoundError(f"Job metadata file not found: {job_key}")
        raw = json.loads(meta_file.read_text(encoding="utf-8"))
        raw["enabled"] = enabled
        meta_file.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"saved": True, "job_key": job_key, "enabled": enabled}

    def _delete_job(self) -> dict:
        from jobs_api import discover_jobs, get_job_runtime_state, get_jobs_meta_dirs, resolve_data_root, resolve_scripts_dir
        from restore_tests_api import resolve_restore_test_dir
        from config_api import read_expanded_conf
        from schedule_api import delete_schedule
        body = self._read_json_body()
        job_key = body.get("job_key", "")
        if not job_key:
            raise ValueError("job_key is required")

        scripts_dir = resolve_scripts_dir(self.config)
        data_root = resolve_data_root(self.config)
        jobs = {j.key: j for j in discover_jobs(scripts_dir, data_root)}
        if job_key not in jobs:
            raise ValueError(f"Unknown job: {job_key}")

        if get_job_runtime_state(self.config, job_key).get("running"):
            raise RuntimeError("The job is currently running; wait for it to finish")

        info = jobs[job_key]
        conf = read_expanded_conf(self.config)
        status_dir = Path(self.config.get("STATUS_DIR", "/mnt/user/backup-status"))
        log_dir    = Path(conf.get("GLOBAL_LOG_DIR", "/mnt/user/Logs"))
        jobs_meta_dirs = get_jobs_meta_dirs(scripts_dir, data_root)

        # Skript (+ optionale .description) löschen
        deleted_script = False
        script_name = ""
        if info.script_path is not None:
            script_name = info.script_path.name
            try:
                if info.script_path.exists():
                    info.script_path.unlink()
                    deleted_script = True
            except OSError:
                pass
            desc = info.script_path.with_suffix(".description")
            if desc.exists():
                try:
                    desc.unlink()
                except OSError:
                    pass

        # Metadatei des Jobs löschen (Wizard-First)
        metadata_paths = [jobs_meta_dir / f"{job_key}.json" for jobs_meta_dir in jobs_meta_dirs]
        from repositories_api import delete_job_metadata_transaction
        deleted_metadata = bool(delete_job_metadata_transaction(self.config, metadata_paths, job_key))

        delete_artifacts = bool(body.get("delete_artifacts", False))

        # Status-Dateien: *_{backup_type}_{location}.status
        deleted_status = 0
        if delete_artifacts:
            for f in status_dir.glob(f"*_{info.backup_type}_{info.location}.status"):
                try:
                    f.unlink()
                    deleted_status += 1
                except OSError:
                    pass

        deleted_restore_test = False
        if delete_artifacts:
            rt_file = resolve_restore_test_dir(self.config) / f"{job_key}.test"
            try:
                if rt_file.exists():
                    rt_file.unlink()
                    deleted_restore_test = True
            except OSError:
                pass

        # Log-Dateien: Borg-Backup[_-]{backup_type}--*.log
        deleted_logs = 0
        if delete_artifacts:
            for pattern in (
                f"Borg-Backup_{info.backup_type}--*.log",
                f"Borg-Backup-{info.backup_type}--*.log",
            ):
                for f in log_dir.glob(pattern):
                    try:
                        f.unlink()
                        deleted_logs += 1
                    except OSError:
                        pass

        # Passphrase-Datei (optional)
        deleted_passphrase = False
        if body.get("delete_passphrase"):
            suffix = f"{info.backup_type}_{info.location}".lower()
            candidates = [
                Path(f"/boot/config/borg-backup/secrets/.borg-passphrase-{suffix}"),
                Path(f"/boot/config/borg-backup/secrets/.borg-passphrase-{info.backup_type}".lower()),
            ]
            for p in candidates:
                try:
                    if p.is_symlink() or p.exists():
                        p.unlink()
                        deleted_passphrase = True
                except OSError:
                    pass

        # Schedule-Eintrag immer mit aufräumen (idempotent),
        # damit keine verwaisten Cron-Trigger für gelöschte Jobs bleiben.
        delete_schedule(self.config, job_key)

        return {
            "deleted": True,
            "filename": script_name,
            "deleted_script": deleted_script,
            "deleted_metadata": deleted_metadata,
            "deleted_status_files": deleted_status,
            "deleted_restore_test": deleted_restore_test,
            "deleted_log_files": deleted_logs,
            "deleted_passphrase": deleted_passphrase,
            "deleted_artifacts": delete_artifacts,
        }

    def _delete_restore_test(self) -> dict:
        from restore_tests_api import delete_restore_test
        body = self._read_json_body()
        return delete_restore_test(self.config, body.get("job_key", ""))

    def _delete_schedule(self) -> dict:
        from schedule_api import delete_schedule
        body = self._read_json_body()
        job_key = body.get("job_key", "")
        if not job_key:
            raise ValueError("job_key is required")
        result = delete_schedule(self.config, job_key)
        return {"deleted": True, **result}

    def _get_storage(self) -> dict:
        from config_api import get_repositories_data
        return get_repositories_data(self.config)

    def _get_repositories(self) -> dict:
        from repositories_api import read_repository_store_for_api
        return read_repository_store_for_api(self.config)

    def _get_repository_directories(self, qs_str: str) -> dict:
        from repositories_api import browse_repository_directories
        from urllib.parse import parse_qs

        qs = parse_qs(qs_str)
        storage_key = str((qs.get("storage_key") or [""])[0]).strip()
        relative_path = str((qs.get("path") or [""])[0]).strip()
        if not storage_key:
            raise ValueError("storage_key is required")
        return browse_repository_directories(self.config, storage_key, relative_path)

    def _post_repository(self) -> dict:
        from repositories_api import (
            RepositoryTargetConflict,
            create_or_import_repository,
            validate_repository_target,
        )
        body = self._read_json_body()
        try:
            validate_repository_target(self.config, body)
            return create_or_import_repository(self.config, body)
        except RepositoryTargetConflict as exc:
            raise ApiConflictError(str(exc), code=exc.code) from exc

    def _post_repository_validate(self) -> dict:
        from repositories_api import RepositoryTargetConflict, validate_repository_target
        body = self._read_json_body()
        try:
            return validate_repository_target(self.config, body)
        except RepositoryTargetConflict as exc:
            raise ApiConflictError(str(exc), code=exc.code) from exc

    def _post_repository_info(self) -> dict:
        from repositories_api import RepositoryBusyError, refresh_repository_info
        body = self._read_json_body()
        try:
            return refresh_repository_info(self.config, str(body.get("repository_key") or ""))
        except RepositoryBusyError as exc:
            raise ApiConflictError(str(exc), code="repository_busy") from exc

    def _post_repository_lifecycle(self) -> dict:
        from repositories_api import RepositoryBusyError, prepare_repository_lifecycle

        body = self._read_json_body()
        try:
            return prepare_repository_lifecycle(
                self.config,
                str(body.get("repository_key") or ""),
                str(body.get("mode") or "remove"),
            )
        except RepositoryBusyError as exc:
            raise ApiConflictError(str(exc), code="repository_busy") from exc

    def _repository_audit_context(self, request_id: str = "") -> dict[str, str]:
        session = self._get_current_session_meta() or {}
        actor = _normalize_username(session.get("username", ""))
        actor_role = str(session.get("role", "") or "").strip().lower()
        auth_method = "session"
        if not actor:
            if self._has_valid_api_token_header():
                actor = "api-token"
                actor_role = "admin"
                auth_method = "api-token"
            else:
                actor = "system"
                actor_role = self._get_current_role() or "system"
                auth_method = "internal"
        return {
            "actor": actor,
            "actor_role": actor_role,
            "auth_method": auth_method,
            "request_id": request_id,
        }

    def _post_repository_key_export(self) -> dict:
        from repositories_api import RepositoryBusyError, export_repository_key

        body = self._read_json_body()
        try:
            return export_repository_key(
                self.config,
                str(body.get("repository_key") or ""),
                audit_context=self._repository_audit_context(str(getattr(self, "_current_request_id", "") or "")),
            )
        except RepositoryBusyError as exc:
            raise ApiConflictError(str(exc), code="repository_busy") from exc

    def _post_repository_key_import(self) -> dict:
        from repositories_api import RepositoryBusyError, import_repository_key

        body = self._read_json_body()
        try:
            return import_repository_key(
                self.config,
                str(body.get("repository_key") or ""),
                str(body.get("key_data") or ""),
                audit_context=self._repository_audit_context(str(getattr(self, "_current_request_id", "") or "")),
            )
        except RepositoryBusyError as exc:
            raise ApiConflictError(str(exc), code="repository_busy") from exc

    def _post_repository_key_backup_preview(self) -> dict:
        from settings_transfer_api import preview_repository_keys_backup_for_repository

        body = self._read_json_body()
        payload_b64 = str(body.get("payload_b64") or "")
        if not payload_b64:
            raise ValueError("payload_b64 is required")
        return preview_repository_keys_backup_for_repository(
            self.config,
            str(body.get("repository_key") or ""),
            str(body.get("password") or ""),
            payload_b64,
        )

    def _post_repository_key_backup_import(self) -> dict:
        from repositories_api import RepositoryBusyError
        from settings_transfer_api import import_repository_keys_backup_for_repository

        body = self._read_json_body()
        payload_b64 = str(body.get("payload_b64") or "")
        if not payload_b64:
            raise ValueError("payload_b64 is required")
        try:
            return import_repository_keys_backup_for_repository(
                self.config,
                str(body.get("repository_key") or ""),
                str(body.get("password") or ""),
                payload_b64,
            )
        except RepositoryBusyError as exc:
            raise ApiConflictError(str(exc), code="repository_busy") from exc

    def _delete_repository(self) -> dict:
        from repositories_api import RepositoryBusyError, RepositoryLifecycleConflict, apply_repository_lifecycle

        body = self._read_json_body()
        try:
            return apply_repository_lifecycle(
                self.config,
                body,
                audit_context=self._repository_audit_context(str(getattr(self, "_current_request_id", "") or "")),
            )
        except RepositoryLifecycleConflict as exc:
            raise ApiConflictError(str(exc), code=exc.code) from exc
        except RepositoryBusyError as exc:
            raise ApiConflictError(str(exc), code="repository_busy") from exc

    def _get_repository_archives(self, qs_str: str) -> dict:
        from repositories_api import get_repository_archives
        from urllib.parse import parse_qs
        qs = parse_qs(qs_str)
        repository_key = str((qs.get("repository_key") or [""])[0]).strip()
        limit = int(str((qs.get("limit") or ["100"])[0]) or "100")
        return get_repository_archives(self.config, repository_key, limit)

    def _post_storage_target(self) -> dict:
        from storage_objects_api import create_storage_target
        return create_storage_target(self.config, self._read_json_body())

    def _post_storage_target_test(self) -> dict:
        from storage_objects_api import test_storage_target
        body = self._read_json_body()
        return test_storage_target(self.config, str(body.get("storage_key") or ""))

    def _get_settings(self) -> dict:
        from config_api import get_settings_data
        data = get_settings_data(self.config)
        data["homepage_widget"] = _homepage_widget_token_status(self.config)
        return data

    def _post_homepage_widget_token(self) -> dict:
        token = _rotate_homepage_widget_token(self.config)
        self._security_audit("homepage_widget_token", "rotated")
        return {"configured": True, "token": token}

    def _delete_homepage_widget_token(self) -> dict:
        revoked = _revoke_homepage_widget_token(self.config)
        self._security_audit("homepage_widget_token", "revoked" if revoked else "not_configured")
        return {"configured": False, "revoked": revoked}

    def _get_notification_reminder_diagnostics(self) -> dict:
        from notification_reminder_api import get_notification_reminder_diagnostics
        return get_notification_reminder_diagnostics(self.config)

    def _get_settings_basic(self) -> dict:
        from config_api import get_settings_data
        return get_settings_data(self.config, include_storagebox_setup=False)

    def _get_setup_status(self) -> dict:
        from config_api import get_setup_status
        return get_setup_status(self.config)

    def _post_setup_wizard(self) -> dict:
        from config_api import update_setup_wizard_state
        body = self._read_json_body()
        action = str(body.get("action") or "").strip()
        state = update_setup_wizard_state(self.config, action)
        return {"saved": True, "setup_wizard": state}

    def _get_settings_backup_history(self) -> dict:
        from config_api import list_conf_backups
        return list_conf_backups(self.config)

    def _get_settings_jobs_export(self, qs_str: str) -> dict:
        from urllib.parse import parse_qs
        from settings_transfer_api import export_jobs_bundle
        qs = parse_qs(qs_str)
        keys = [str(x).strip() for x in (qs.get("job_key") or []) if str(x).strip()]
        return export_jobs_bundle(self.config, keys if keys else None)

    def _get_log_file(self, query_string: str) -> dict:
        from urllib.parse import parse_qs, unquote
        from config_api import read_expanded_conf
        qs = parse_qs(query_string)
        file_path = unquote((qs.get("file") or [""])[0])
        if not file_path:
            raise ValueError("file is required")
        requested = Path(file_path)
        if requested.suffix.lower() not in (".log", ".txt"):
            raise ValueError("Invalid file type")

        # Preferred: exact path from status entry.
        candidates = [requested]
        # Fallback: current configured log directory + same filename.
        conf = read_expanded_conf(self.config)
        current_log_dir = Path(str(conf.get("GLOBAL_LOG_DIR", "")).strip() or "/mnt/user/Logs")
        candidates.append(current_log_dir / requested.name)
        # Legacy fallback:
        candidates.append(Path("/mnt/user/Logs") / requested.name)

        resolved = None
        for p in candidates:
            if p.exists():
                resolved = p
                break
        if resolved is None:
            return {"exists": False, "content": "", "path": str(candidates[0])}
        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
            return {"exists": True, "content": content, "path": str(resolved)}
        except OSError as e:
            raise RuntimeError(f"Read error: {e}") from e

    def _get_history(self, query_string: str) -> dict:
        from history_api import get_history_data
        from urllib.parse import parse_qs
        qs = parse_qs(query_string)
        filters = {
            "type": (qs.get("type") or [""])[0].lower() or None,
            "location": (qs.get("location") or [""])[0].lower() or None,
            "status": (qs.get("status") or [""])[0].lower() or None,
            "page": (qs.get("page") or ["1"])[0],
            "per_page": (qs.get("per_page") or ["20"])[0],
        }
        return get_history_data(self.config, filters)

    def _get_restore_tests(self) -> dict:
        from restore_tests_api import list_restore_tests
        return {"tests": list_restore_tests(self.config)}

    def _get_restore_tests_plan(self) -> dict:
        from restore_tests_api import list_restore_test_plan
        return list_restore_test_plan(self.config)

    def _get_rt_running(self) -> dict:
        from jobs_api import JobManager
        return JobManager.get().get_state("restore_test")

    def _get_wizard_job(self, qs: str) -> dict:
        from urllib.parse import parse_qs as _pqs
        from wizard_api import load_job_for_wizard
        from jobs_api import resolve_scripts_dir
        params = _pqs(qs)
        job_key = (params.get("job_key") or [""])[0].strip()
        if not job_key:
            raise ValueError("job_key is required")
        scripts_dir = resolve_scripts_dir(self.config)
        return {"job": load_job_for_wizard(job_key, scripts_dir, self.config)}

    def _get_wizard_source_dirs(self, qs: str) -> dict:
        from urllib.parse import parse_qs as _pqs
        from wizard_api import list_source_directories
        params = _pqs(qs)
        prefix = (params.get("prefix") or [""])[0]
        try:
            limit = int((params.get("limit") or ["25"])[0])
        except Exception:
            limit = 25
        return {"dirs": list_source_directories(prefix=prefix, limit=limit)}

    def _get_wizard_runtime_inventory(self) -> dict:
        try:
            from lib.docker_manager import DockerManager
            docker_containers = DockerManager().list_containers()
        except Exception:
            docker_containers = []
        try:
            from lib.vm_manager import VmManager
            vms = VmManager().list_vms()
        except Exception:
            vms = []
        return {
            "docker_containers": docker_containers,
            "vms": vms,
        }

    def _get_restore_archives(self, qs_str: str) -> dict:
        self._require_data_dir_ready()
        from restore_api import list_archives_with_context
        from urllib.parse import parse_qs
        qs = parse_qs(qs_str)
        job_key = (qs.get("job") or [""])[0]
        if not job_key:
            raise ValueError("job parameter is required")
        return list_archives_with_context(self.config, job_key)

    def _get_restore_files(self, qs_str: str) -> dict:
        self._require_data_dir_ready()
        from restore_api import list_files
        from urllib.parse import parse_qs, unquote
        qs = parse_qs(qs_str)
        job_key = (qs.get("job") or [""])[0]
        archive = (qs.get("archive") or [""])[0]
        path = unquote((qs.get("path") or [""])[0])
        if not job_key or not archive:
            raise ValueError("job and archive parameters are required")
        return {"files": list_files(self.config, job_key, archive, path)}

    def _get_report_jobs(self) -> dict:
        from reports_api import get_report_jobs
        return {"jobs": get_report_jobs(self.config)}

    def _get_report_data(self, qs_str: str) -> dict:
        from reports_api import get_report_data
        from urllib.parse import parse_qs
        qs = parse_qs(qs_str)
        job_key = (qs.get("job") or [""])[0]
        if not job_key:
            raise ValueError("job parameter is required")
        return get_report_data(self.config, job_key)

    def _get_repo_stats(self, qs_str: str) -> dict:
        self._require_data_dir_ready()
        from restore_api import get_repo_stats
        from urllib.parse import parse_qs
        qs = parse_qs(qs_str)
        job_key = (qs.get("job") or [""])[0]
        if not job_key:
            raise ValueError("job parameter is required")
        return get_repo_stats(self.config, job_key)

    def _get_restore_target_dirs(self, qs_str: str) -> dict:
        self._require_data_dir_ready()
        from restore_api import list_allowed_target_roots, list_target_dirs_with_config
        from urllib.parse import parse_qs, unquote
        qs = parse_qs(qs_str)
        prefix = unquote((qs.get("prefix") or [""])[0])
        limit_raw = (qs.get("limit") or ["40"])[0]
        try:
            limit = int(limit_raw)
        except Exception:
            limit = 40
        return {
            "dirs": list_target_dirs_with_config(self.config, prefix, limit),
            "allowed_roots": list_allowed_target_roots(self.config),
        }

    def _get_restore_state(self, qs_str: str) -> dict:
        self._require_data_dir_ready()
        from restore_api import get_restore_state
        from urllib.parse import parse_qs
        qs = parse_qs(qs_str)
        restore_id = str((qs.get("restore_id") or [""])[0]).strip()
        if not restore_id:
            raise ValueError("restore_id is required")
        return get_restore_state(self.config, restore_id)

    def _get_check_jobs(self) -> dict:
        from check_api import get_check_jobs
        return {"jobs": get_check_jobs(self.config)}

    def _get_check_state(self) -> dict:
        from check_api import CheckManager
        return CheckManager.get().get_state()

    def _post_run_check(self) -> dict:
        self._require_data_dir_ready()
        body = self._read_json_body()
        repository_key = str(body.get("repository_key") or "").strip()
        if not repository_key:
            raise ValueError("repository_key parameter is required")
        mode = str(body.get("mode", "quick")).strip().lower()
        if mode not in {"quick", "verbose", "verify_data"}:
            raise ValueError("Invalid mode parameter")
        from check_api import CheckManager
        action = str(body.get("action") or "check").strip().lower()
        job_key = str(body.get("job_key") or "").strip()
        ok, err = CheckManager.get().start_repository(
            self.config,
            repository_key,
            action,
            mode,
            job_key=job_key,
        )
        if not ok:
            raise RuntimeError(err)
        return {"ok": True}

    def _handle_check_sse(self) -> None:
        from check_api import CheckManager
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._send_refreshed_session_header()
        self.end_headers()
        try:
            for chunk in CheckManager.get().stream_output():
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_restore_download(self, parsed) -> None:
        try:
            self._require_data_dir_ready()
        except Exception as exc:
            self.send_error(500, str(exc))
            return
        import subprocess
        from urllib.parse import parse_qs, unquote
        qs = parse_qs(parsed.query)
        job_key = (qs.get("job") or [""])[0]
        archive = (qs.get("archive") or [""])[0]
        path = unquote((qs.get("path") or [""])[0])
        confirm_large = str((qs.get("confirm_large") or ["0"])[0]).strip().lower() in {"1", "true", "yes"}

        if not all([job_key, archive, path]):
            self.send_error(400, "job, archive, and path are required")
            return

        lock_set = None
        try:
            from restore_api import RestoreRepositoryBusy, acquire_restore_repository_lock, get_repo_info, _repository_borg_env
            info = get_repo_info(self.config, job_key)
            lock_set = acquire_restore_repository_lock(
                self.config,
                info,
                job_key,
                f"restore-download-{datetime.now().strftime('%Y%m%dT%H%M%S')}",
            )
            env = _repository_borg_env(self.config, info)
        except RestoreRepositoryBusy as exc:
            self.send_error(409, str(exc))
            return
        except Exception as exc:
            self.send_error(500, str(exc))
            return

        repo_archive = f"{info['repo']}::{archive}"
        source_path = path.lstrip("/")
        filename = Path(path).name or "archive"

        try:
            check = self._compute_restore_download_check(repo_archive, source_path, env)
        except RuntimeError as exc:
            if lock_set is not None:
                lock_set.release()
            self.send_error(400, str(exc)[:500])
            return
        entry_type = check["entry_type"]
        action = check["action"]
        if action == "block":
            if lock_set is not None:
                lock_set.release()
            self.send_error(413, check["message"])
            return
        if action == "confirm" and not confirm_large:
            if lock_set is not None:
                lock_set.release()
            self.send_error(409, check["message"])
            return

        if entry_type == "dir":
            # export-tar syntax: borg export-tar REPO::ARCHIVE TARFILE [PATH...]
            # Use "-" as TARFILE to stream to stdout for HTTP download.
            cmd = ["borg", "export-tar", repo_archive, "-", source_path]
            dl_name = filename if filename.endswith(".tar") else f"{filename}.tar"
            content_type = "application/x-tar"
        else:
            cmd = ["borg", "extract", "--stdout", repo_archive, source_path]
            dl_name = filename
            content_type = "application/octet-stream"

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        except OSError as exc:
            if lock_set is not None:
                lock_set.release()
            self.send_error(500, f"Start failed: {exc}")
            return
        stderr_thread, stderr_snapshot = _start_bounded_stderr_collector(proc.stderr)
        finished = threading.Event()
        timed_out = threading.Event()
        timeout_seconds = _restore_download_timeout_seconds(self.config)

        def watchdog() -> None:
            if finished.wait(timeout_seconds):
                return
            if proc.poll() is None:
                timed_out.set()
                _log(f"Restore download timed out after {timeout_seconds}s; terminating Borg process")
                try:
                    proc.kill()
                except OSError:
                    pass

        watchdog_thread = threading.Thread(target=watchdog, name="restore-download-watchdog", daemon=True)
        watchdog_thread.start()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{dl_name}"')
        self.send_header("Cache-Control", "no-cache")
        self._send_refreshed_session_header()
        self.end_headers()
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
            rc = proc.wait()
            finished.set()
            stderr_thread.join(timeout=1)
            stderr_out = stderr_snapshot()
            if timed_out.is_set():
                _log(f"Restore download timeout: {stderr_out[:500] or 'no stderr'}")
                return
            if rc != 0:
                _log(f"Restore download error (rc={rc}): {stderr_out[:500] or 'no stderr'}")
        except (BrokenPipeError, ConnectionResetError):
            if proc.poll() is None:
                proc.kill()
        finally:
            finished.set()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                if proc.poll() is None:
                    proc.kill()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            try:
                if proc.stdout:
                    proc.stdout.close()
            except OSError:
                pass
            try:
                if proc.stderr:
                    proc.stderr.close()
            except OSError:
                pass
            stderr_thread.join(timeout=1)
            if lock_set is not None:
                lock_set.release()

    def _compute_restore_download_check(self, repo_archive: str, source_path: str, env: dict) -> dict:
        import subprocess

        warn_bytes = 5 * 1024 * 1024 * 1024
        hard_bytes = 20 * 1024 * 1024 * 1024

        probe_cmd = ["borg", "list", "--format", "{type}\n", repo_archive, source_path]
        probe = subprocess.run(probe_cmd, capture_output=True, text=True, env=env)
        if probe.returncode != 0:
            err = (probe.stderr or "The path could not be inspected").strip()
            raise RuntimeError(err)
        raw_type = (probe.stdout or "").strip().splitlines()[0:1]
        raw_type = raw_type[0].strip() if raw_type else ""
        type_map = {"file": "file", "dir": "dir", "-": "file", "d": "dir"}
        entry_type = type_map.get(raw_type, "")
        if entry_type not in {"file", "dir"}:
            raise RuntimeError(f"Unsupported path type: {raw_type or 'unknown'}")

        size_cmd = ["borg", "list", "--format", "{type}|{size}\n", repo_archive, source_path]
        size_run = subprocess.run(size_cmd, capture_output=True, text=True, env=env)
        if size_run.returncode != 0:
            err = (size_run.stderr or "The size could not be determined").strip()
            raise RuntimeError(err)
        total_bytes = 0
        for line in (size_run.stdout or "").splitlines():
            parts = line.strip().split("|", 1)
            if len(parts) != 2:
                continue
            t, s = parts[0].strip(), parts[1].strip()
            if t in {"file", "-"}:
                try:
                    total_bytes += int(s or "0")
                except ValueError:
                    continue

        action = "allow"
        message = "Download erlaubt."
        if total_bytes > hard_bytes:
            action = "block"
            message = (
                f"Direct download is too large ({self._fmt_bytes(total_bytes)}). "
                f"Limit: {self._fmt_bytes(hard_bytes)}. Restore to a target directory instead."
            )
        elif total_bytes > warn_bytes:
            action = "confirm"
            message = (
                f"Large download ({self._fmt_bytes(total_bytes)}). "
                f"Confirm to continue."
            )
        return {
            "entry_type": entry_type,
            "size_bytes": total_bytes,
            "warn_bytes": warn_bytes,
            "hard_bytes": hard_bytes,
            "action": action,
            "message": message,
        }

    @staticmethod
    def _fmt_bytes(value: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        size = float(max(0, int(value)))
        idx = 0
        while size >= 1024 and idx < len(units) - 1:
            size /= 1024
            idx += 1
        return f"{size:.1f} {units[idx]}" if idx > 0 else f"{int(size)} {units[idx]}"

    def _get_restore_download_check(self, query: str) -> dict:
        from urllib.parse import parse_qs, unquote
        from restore_api import ensure_restore_repository_available, get_repo_info, _repository_borg_env
        qs = parse_qs(query or "")
        job_key = (qs.get("job") or [""])[0]
        archive = (qs.get("archive") or [""])[0]
        path = unquote((qs.get("path") or [""])[0])
        if not all([job_key, archive, path]):
            raise ValueError("job, archive, and path are required")
        info = get_repo_info(self.config, job_key)
        ensure_restore_repository_available(self.config, info)
        env = _repository_borg_env(self.config, info)
        repo_archive = f"{info['repo']}::{archive}"
        source_path = path.lstrip("/")
        check = self._compute_restore_download_check(repo_archive, source_path, env)
        return {"ok": True, **check}

    def _post_wizard_preview(self) -> dict:
        from wizard_api import validate_params, generate_flow_preview
        from jobs_api import resolve_scripts_dir, resolve_data_root
        body = self._read_json_body()
        scripts_dir = resolve_scripts_dir(self.config)
        data_root = resolve_data_root(self.config)
        mode = str(body.get("_wizard_mode", "create")).strip().lower()
        validate_params(
            body,
            scripts_dir,
            data_root,
            allow_existing=(mode == "edit"),
            ui_config=self.config,
            require_runtime_ack=False,
        )
        return {"flow": generate_flow_preview(body, self.config, scripts_dir)}

    def _post_wizard_save(self) -> dict:
        from wizard_api import validate_params, save_job
        from jobs_api import resolve_scripts_dir, resolve_data_root
        body = self._read_json_body()
        scripts_dir = resolve_scripts_dir(self.config)
        data_root = resolve_data_root(self.config)
        mode = str(body.get("_wizard_mode", "create")).strip().lower()
        validate_params(body, scripts_dir, data_root, allow_existing=(mode == "edit"), ui_config=self.config)
        return save_job(body, scripts_dir, data_root, self.config)

    def _start_restore_test_from_body(self, body: dict) -> dict:
        self._require_data_dir_ready()
        from jobs_api import JobManager
        from jobs_api import list_jobs
        from config_api import read_expanded_conf
        from lifecycle_log import emit_lifecycle
        from restore_tests_api import list_restore_test_plan
        if not isinstance(body, dict):
            body = {}
        conf = read_expanded_conf(self.config)
        level = str(body.get("level", conf.get("RESTORE_TEST_LEVEL", "2"))).strip()
        location = str(body.get("location", conf.get("RESTORE_TEST_LOCATION", "local"))).strip().lower()
        smb_auto_mount = bool(body.get("smb_auto_mount", True))
        job_keys = body.get("job_keys", [])

        if level not in {"1", "2", "3"}:
            raise ValueError("Invalid level (allowed: 1, 2, 3)")
        if location not in {"local", "usb", "smb", "storagebox", "all"}:
            raise ValueError("Invalid location")
        if not isinstance(job_keys, list):
            raise ValueError("job_keys must be a list")
        clean_job_keys = [str(k).strip() for k in job_keys if str(k).strip()]
        auto_selected = False
        skipped = []
        if clean_job_keys:
            jobs = list_jobs(self.config, {})
            known = {str(j.get("key") or "").strip(): j for j in jobs if isinstance(j, dict)}
            for k in clean_job_keys:
                row = known.get(k)
                if not row:
                    raise ValueError(f"Unknown job: {k}")
                if row.get("enabled") is False:
                    raise ValueError(f"Job is disabled: {k}")
        scheduled = bool(body.get("scheduled", False))
        if scheduled and not clean_job_keys:
            plan = list_restore_test_plan(self.config)
            due_rows = []
            for row in (plan.get("jobs") or []):
                if not isinstance(row, dict):
                    continue
                policy = row.get("policy") if isinstance(row.get("policy"), dict) else {}
                mode = str(policy.get("mode") or "").strip().lower()
                if mode != "scheduled":
                    skipped.append({"job_key": str(row.get("job_key") or ""), "reason": f"mode={mode or 'unknown'}"})
                    continue
                if row.get("enabled") is False:
                    skipped.append({"job_key": str(row.get("job_key") or ""), "reason": "disabled"})
                    continue
                if not bool(row.get("is_overdue", False)):
                    skipped.append({"job_key": str(row.get("job_key") or ""), "reason": "not_due"})
                    continue
                due_rows.append(row)
            clean_job_keys = [str(r.get("job_key") or "").strip() for r in due_rows if str(r.get("job_key") or "").strip()]
            auto_selected = True
            location = "all"
            if not clean_job_keys:
                return {
                    "started": False,
                    "reason": "no_due_jobs",
                    "scheduled": True,
                    "selected_jobs": [],
                    "skipped_jobs": skipped,
                }

        from jobs_api import resolve_scripts_dir
        scripts_dir = resolve_scripts_dir(self.config)
        script_path = scripts_dir / "borg_restore_test.py"
        if not script_path.exists():
            raise FileNotFoundError(f"borg_restore_test.py not found in {scripts_dir}")

        backup_scripts_dir = Path(self.config["BACKUP_SCRIPTS_DIR"])
        cmd = ["python3", str(script_path), "--level", level, "--location", location]
        if smb_auto_mount:
            cmd.append("--smb-auto-mount")
        if scheduled:
            cmd.append("--scheduled")
        if not scheduled:
            cmd.append("--force")
        for job_key in clean_job_keys:
            cmd.extend(["--job-key", job_key])
        request_id = str(getattr(self, "_current_request_id", "") or "")
        session = self._get_current_session_meta() or {}
        actor = _normalize_username(session.get("username", ""))
        source = "schedule" if scheduled else ("api-token" if self._has_valid_api_token_header() else "manual")
        if not actor and source == "schedule":
            actor = "scheduler"
        if not actor and source == "api-token":
            actor = "api-token"
        ok, err = JobManager.get().start(
            "restore_test",
            cmd,
            backup_scripts_dir,
            extra_env={
                "BORG_UI_DATA_ROOT": str(backup_scripts_dir),
                "BORG_UI_APP_VERSION": APP_VERSION,
                "BORG_UI_REQUEST_ID": request_id,
                "BORG_UI_REQUEST_SOURCE": source,
                "BORG_UI_REQUEST_ACTOR": actor,
            },
        )
        if not ok:
            if "already running" in str(err or "").lower():
                raise ApiConflictError(
                    "A restore test is already running. Open the live log or wait until it finishes.",
                    "restore_test_already_running",
                )
            raise RuntimeError(err)
        state = JobManager.get().get_state("restore_test")
        emit_lifecycle(
            "RESTORE_TEST",
            "requested",
            request_id=request_id,
            source=source,
            actor=actor,
            run_id=state.get("run_id", ""),
            level=level,
            location=location,
            selected_jobs=clean_job_keys,
            auto_selected=auto_selected,
        )
        return {
            "started": True,
            "scheduled": scheduled,
            "auto_selected": auto_selected,
            "selected_jobs": clean_job_keys,
            "run_id": state.get("run_id", ""),
            "skipped_jobs": skipped,
        }

    def _post_run_restore_test(self) -> dict:
        body = self._read_json_body()
        return self._start_restore_test_from_body(body)

    def _post_run_restore_test_job(self) -> dict:
        from jobs_api import list_jobs
        body = self._read_json_body()
        job_key = str(body.get("job_key", "")).strip()
        if not job_key:
            raise ValueError("job_key is required")
        requested_level = str(body.get("level", "")).strip()
        effective_level = requested_level
        if not effective_level:
            jobs = list_jobs(self.config, {})
            row = next((j for j in jobs if str(j.get("key") or "").strip() == job_key), None)
            policy = row.get("restore_test_policy") if isinstance(row, dict) and isinstance(row.get("restore_test_policy"), dict) else {}
            policy_level = str(policy.get("level", "")).strip()
            effective_level = policy_level or str(self.config.get("RESTORE_TEST_LEVEL", "2"))
        run_body = {
            "job_keys": [job_key],
            "location": "all",
            "scheduled": False,
            "smb_auto_mount": bool(body.get("smb_auto_mount", True)),
            "level": effective_level,
        }
        return self._start_restore_test_from_body(run_body)

    def _put_restore_test_policy(self) -> dict:
        from restore_tests_api import update_restore_test_policy
        body = self._read_json_body()
        job_key = str(body.get("job_key", "")).strip()
        policy = body.get("policy")
        return update_restore_test_policy(self.config, job_key, policy if isinstance(policy, dict) else {})

    def _post_test_repo(self) -> dict:
        from config_api import test_repository
        body = self._read_json_body()
        repository_key = str(body.get("repository_key", "")).strip()
        if not repository_key:
            raise ValueError("repository_key is required")
        return test_repository(self.config, repository_key)

    def _post_storage_smb_action(self) -> dict:
        from config_api import run_smb_profile_action
        body = self._read_json_body()
        profile_key = str(body.get("profile_key", "")).strip()
        action = str(body.get("action", "")).strip().lower()
        return run_smb_profile_action(self.config, profile_key, action)

    def _post_restore_precheck(self) -> dict:
        self._require_data_dir_ready()
        from restore_api import restore_precheck
        body = self._read_json_body()
        return restore_precheck(
            self.config,
            str(body.get("job_key", "")).strip(),
            str(body.get("archive", "")).strip(),
            str(body.get("source_path", "")).strip(),
            str(body.get("target_dir", "")).strip(),
            str(body.get("conflict_mode", "skip")).strip(),
            bool(body.get("dry_run", True)),
        )

    def _post_restore_start(self) -> dict:
        self._require_data_dir_ready()
        from restore_api import start_restore_async
        body = self._read_json_body()
        confirm = bool(body.get("confirm", False))
        if not confirm:
            raise ValueError("Confirmation is required")
        return start_restore_async(
            self.config,
            str(body.get("job_key", "")).strip(),
            str(body.get("archive", "")).strip(),
            str(body.get("source_path", "")).strip(),
            str(body.get("target_dir", "")).strip(),
            str(body.get("conflict_mode", "skip")).strip(),
            bool(body.get("preserve_owner", False)),
        )

    def _get_restore_runs(self, query: str) -> dict:
        from restore_api import list_restore_runs
        qs = parse_qs(query)
        limit = (qs.get("limit") or ["20"])[0]
        return list_restore_runs(self.config, int(limit))

    def _get_restore_history(self, query: str) -> dict:
        from restore_api import list_restore_history
        qs = parse_qs(query)
        limit = (qs.get("limit") or ["20"])[0]
        offset = (qs.get("offset") or ["0"])[0]
        return list_restore_history(self.config, int(limit), int(offset))

    def _get_restore_history_detail(self, query: str) -> dict:
        from restore_api import get_restore_history_detail
        qs = parse_qs(query)
        restore_id = str((qs.get("restore_id") or [""])[0]).strip()
        if not restore_id:
            raise ValueError("restore_id is required")
        return get_restore_history_detail(self.config, restore_id)

    def _delete_restore_history(self) -> dict:
        from restore_api import delete_restore_history_entry
        body = self._read_json_body()
        return delete_restore_history_entry(self.config, body.get("restore_id", ""))

    def _post_client_log(self) -> dict:
        body = self._read_json_body() if self.headers.get("Content-Type", "").lower().startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        now = time.time()
        ip = self._client_ip()
        window = self._CLIENT_LOG_WINDOW_SECONDS
        max_per_window = self._CLIENT_LOG_MAX_PER_WINDOW

        bucket = self._CLIENT_LOG_BUCKET.get(ip, [])
        bucket = [t for t in bucket if (now - t) < window]
        if len(bucket) >= max_per_window:
            self._CLIENT_LOG_BUCKET[ip] = bucket
            raise RateLimitExceeded("Client-Log Rate-Limit erreicht")
        bucket.append(now)
        self._CLIENT_LOG_BUCKET[ip] = bucket
        # Keep memory bounded for long-running daemons with many unique source IPs.
        if len(self._CLIENT_LOG_BUCKET) > self._CLIENT_LOG_MAX_IPS_TRACKED:
            stale_cutoff = now - window
            self._CLIENT_LOG_BUCKET = {
                k: v for k, v in self._CLIENT_LOG_BUCKET.items()
                if v and v[-1] >= stale_cutoff
            }
            self._CLIENT_LOG_LAST_SIG = {
                k: v for k, v in self._CLIENT_LOG_LAST_SIG.items()
                if v and v[1] >= stale_cutoff
            }

        payload = {
            "type": _mask_secrets(str(body.get("type") or "client_event"))[:64],
            "message": _mask_secrets(str(body.get("message") or ""))[:1000],
            "stack": _mask_secrets(str(body.get("stack") or ""))[:4096],
            "page": _mask_secrets(str(body.get("page") or ""))[:256],
            "ui_version": _mask_secrets(str(body.get("ui_version") or APP_VERSION))[:64],
            "user_agent": _mask_secrets(str(body.get("ua") or self.headers.get("User-Agent", "")))[:256],
        }
        sig = f"{payload['type']}|{payload['message']}|{payload['stack'][:512]}|{payload['page']}"
        prev = self._CLIENT_LOG_LAST_SIG.get(ip)
        if prev and prev[0] == sig and (now - prev[1]) < window:
            return {"ok": True, "dropped": True, "reason": "duplicate"}
        self._CLIENT_LOG_LAST_SIG[ip] = (sig, now)

        req_id = uuid.uuid4().hex[:12]
        _log_client(
            f"CLIENT event request_id={req_id} ip={ip} type={payload['type']} "
            f"page={payload['page']} ui_version={payload['ui_version']} message=\"{payload['message']}\" "
            f"stack=\"{payload['stack']}\" ua=\"{payload['user_agent']}\""
        )
        return {"ok": True, "request_id": req_id}

    def _put_storage(self) -> dict:
        from config_api import write_conf
        body = self._read_json_body()
        updates = body.get("updates", {})
        if not updates:
            raise ValueError("updates is required")
        write_conf(self.config, updates, snapshot_reason="Manual change")
        return {"saved": True}

    def _put_settings(self) -> dict:
        from config_api import (
            write_conf,
            derive_data_dirs,
            ensure_data_dirs,
            read_expanded_conf,
            _normalize_usb_profile_rows,
            _normalize_storage_profile_rows,
            validate_usb_profile_usage_before_save,
            validate_storage_profiles_complete_before_save,
            validate_storage_profile_usage_before_save,
            prepare_smb_profiles_for_save,
            validate_smb_profiles_json,
            validate_smb_profile_usage_before_save,
            cleanup_removed_smb_mountpoints,
            cleanup_removed_smb_secrets,
        )
        from storage_objects_api import replace_profile_storages, settings_profiles_from_storages
        body = self._read_json_body()
        updates = body.get("updates", {})
        profile_updates = body.get("profile_updates", {})
        smb_cleanup_keys = body.get("smb_cleanup_keys", [])
        smb_secret_cleanup_keys = body.get("smb_secret_cleanup_keys", [])
        if not isinstance(updates, dict):
            raise ValueError("updates must be an object")
        if not isinstance(profile_updates, dict):
            raise ValueError("profile_updates must be an object")
        if not updates and not profile_updates:
            raise ValueError("updates or profile_updates is required")
        if smb_cleanup_keys is None:
            smb_cleanup_keys = []
        if smb_secret_cleanup_keys is None:
            smb_secret_cleanup_keys = []
        if not isinstance(smb_cleanup_keys, list):
            raise ValueError("smb_cleanup_keys must be a list")
        if not isinstance(smb_secret_cleanup_keys, list):
            raise ValueError("smb_secret_cleanup_keys must be a list")
        prev_conf = read_expanded_conf(self.config)
        prev_data_dir = str(prev_conf.get("GLOBAL_DATA_DIR", "")).strip()
        prev_smb_rows = []
        canonical_profiles = settings_profiles_from_storages(self.config)
        try:
            prev_smb_rows = validate_smb_profiles_json(
                json.dumps(canonical_profiles.get("smb_profiles", []), ensure_ascii=False)
            )
        except ValueError:
            prev_smb_rows = []
        smb_removed_keys: set[str] = set()
        if "local" in profile_updates:
            parsed_local = profile_updates.get("local")
            if not isinstance(parsed_local, list):
                raise ValueError("Local profile updates must be a list.")
            replace_profile_storages(self.config, "local", parsed_local)
        if "GLOBAL_SMTP_PASSWORD" in updates:
            incoming_pw = str(updates.get("GLOBAL_SMTP_PASSWORD", ""))
            existing_pw = str(prev_conf.get("GLOBAL_SMTP_PASSWORD", ""))
            if not incoming_pw.strip() and existing_pw.strip():
                updates.pop("GLOBAL_SMTP_PASSWORD", None)
        updates.pop("UI_LOGIN_PASSWORD", None)
        updates.pop("UI_LOGIN_PASSWORD_CLEAR", None)
        data_dir = updates.get("GLOBAL_DATA_DIR")
        if data_dir is not None:
            data_dir = str(data_dir).strip()
            if not data_dir:
                raise ValueError("GLOBAL_DATA_DIR must not be empty")
            dirs = derive_data_dirs(data_dir)
            updates["GLOBAL_DATA_DIR"] = data_dir
            updates["GLOBAL_LOG_DIR"] = dirs["logs"]
            updates["STATUS_DIR"] = dirs["status"]
            updates["RESTORE_TEST_STATUS_DIR"] = dirs["restore_status"]
            updates["GLOBAL_BORG_CACHE_BASE"] = dirs["cache"]
        if "smb" in profile_updates:
            raw_smb = profile_updates.get("smb")
            if not isinstance(raw_smb, list):
                raise ValueError("SMB profile updates must be a list.")
            raw_smb_json = json.dumps(raw_smb, ensure_ascii=False)
            normalized_preview = validate_smb_profiles_json(raw_smb_json)
            validate_smb_profile_usage_before_save(self.config, normalized_preview)
            prev_keys = {str(r.get("key") or "").strip().lower() for r in prev_smb_rows if str(r.get("key") or "").strip()}
            new_keys = {str(r.get("key") or "").strip().lower() for r in normalized_preview if str(r.get("key") or "").strip()}
            smb_removed_keys = {k for k in prev_keys if k not in new_keys}
            normalized_smb = prepare_smb_profiles_for_save(raw_smb_json)
            replace_profile_storages(self.config, "smb", normalized_smb)
        if "usb" in profile_updates:
            parsed_usb = profile_updates.get("usb")
            if not isinstance(parsed_usb, list):
                raise ValueError("USB profile updates must be a list.")
            normalized_usb = _normalize_usb_profile_rows(parsed_usb)
            validate_usb_profile_usage_before_save(self.config, normalized_usb)
            replace_profile_storages(self.config, "usb", normalized_usb)
        if "storagebox" in profile_updates:
            parsed_storage = profile_updates.get("storagebox")
            if not isinstance(parsed_storage, list):
                raise ValueError("SSH profile updates must be a list.")
            normalized_storage = _normalize_storage_profile_rows(parsed_storage)
            validate_storage_profiles_complete_before_save(normalized_storage)
            validate_storage_profile_usage_before_save(self.config, normalized_storage)
            replace_profile_storages(self.config, "storagebox", normalized_storage)
        write_conf(self.config, updates, snapshot_reason="Manual change")
        repository_refresh_keys = {
            "REPOSITORY_INFO_REFRESH_ENABLED",
            "REPOSITORY_INFO_REFRESH_INTERVAL_HOURS",
            "REPOSITORY_INFO_REFRESH_RETRY_HOURS",
        }
        if repository_refresh_keys & set(updates.keys()):
            try:
                from repositories_api import signal_repository_info_refresh_config_changed

                signal_repository_info_refresh_config_changed()
            except Exception as exc:
                self.log_message(
                    f"WARNING: Repository information refresh schedule could not be signalled: "
                    f"{_mask_secrets(str(exc))}"
                )
        created_paths = None
        if data_dir is not None:
            created = ensure_data_dirs(str(data_dir))
            created_paths = created.get("paths")
        _apply_runtime_dirs_from_conf(self.config)
        weekly_keys = {"WEEKLY_REPORT_ENABLED", "WEEKLY_REPORT_DAY", "WEEKLY_REPORT_TIME", "WEEKLY_REPORT_RECIPIENT"}
        if weekly_keys & set(updates.keys()):
            try:
                from report_mail_api import apply_weekly_report_cron
                apply_weekly_report_cron({**self.config, **read_expanded_conf(self.config)})
            except Exception:
                pass
        smb_cleanup_report = None
        smb_secret_cleanup_report = None
        if smb_removed_keys and smb_cleanup_keys:
            requested = {str(k or "").strip().lower() for k in smb_cleanup_keys if str(k or "").strip()}
            effective = sorted(k for k in smb_removed_keys if k in requested)
            if effective:
                smb_cleanup_report = cleanup_removed_smb_mountpoints(prev_smb_rows, effective)
        if smb_removed_keys and smb_secret_cleanup_keys:
            requested = {str(k or "").strip().lower() for k in smb_secret_cleanup_keys if str(k or "").strip()}
            effective = sorted(k for k in smb_removed_keys if k in requested)
            if effective:
                smb_secret_cleanup_report = cleanup_removed_smb_secrets(prev_smb_rows, effective)
        initialized_now = bool(data_dir is not None and not prev_data_dir and str(data_dir).strip())
        return {
            "saved": True,
            "data_dirs": created_paths,
            "data_dir_initialized": initialized_now,
            "smb_cleanup": smb_cleanup_report,
            "smb_secret_cleanup": smb_secret_cleanup_report,
        }

    def _post_test_smtp(self) -> dict:
        from config_api import send_test_email
        body = self._read_json_body()
        recipient = body.get("recipient", "")
        return send_test_email(self.config, recipient)

    def _post_settings_support_bundle(self) -> dict:
        from support_bundle_api import create_support_bundle
        return create_support_bundle(self.config, app_version=APP_VERSION)

    def _post_settings_usb_profiles_status(self) -> dict:
        from config_api import test_usb_profiles_status
        body = self._read_json_body()
        profiles = body.get("profiles", [])
        if not isinstance(profiles, list):
            raise ValueError("profiles must be a list")
        return test_usb_profiles_status(profiles)

    def _post_settings_smb_profiles_status(self) -> dict:
        from config_api import test_smb_profiles_status
        body = self._read_json_body()
        profiles = body.get("profiles", [])
        if not isinstance(profiles, list):
            raise ValueError("profiles must be a list")
        return test_smb_profiles_status(profiles)

    def _post_send_weekly_report(self) -> dict:
        from report_mail_api import send_weekly_report
        from status_api import get_status_data
        body = self._read_json_body()
        recipient = (body or {}).get("recipient", "")
        # Ensure weekly snapshots are up to date before generating/sending report.
        try:
            get_status_data(self.config, force_snapshot_write=True)
        except Exception:
            pass
        return send_weekly_report(self.config, recipient)

    def _post_settings_backup_restore(self) -> dict:
        from config_api import restore_conf_backup
        body = self._read_json_body()
        name = str((body or {}).get("name", "")).strip()
        if not name:
            raise ValueError("name is required")
        restored = restore_conf_backup(self.config, name)
        _apply_runtime_dirs_from_conf(self.config)
        return restored

    def _post_settings_backup_delete(self) -> dict:
        from config_api import delete_conf_backup
        body = self._read_json_body()
        name = str((body or {}).get("name", "")).strip()
        if not name:
            raise ValueError("name is required")
        return delete_conf_backup(self.config, name)

    def _post_settings_backup_delete_keep_latest(self) -> dict:
        from config_api import delete_conf_backups_keep_latest
        return delete_conf_backups_keep_latest(self.config)

    def _post_settings_backup_diff(self) -> dict:
        from config_api import diff_conf_backup
        body = self._read_json_body()
        name = str((body or {}).get("name", "")).strip()
        if not name:
            raise ValueError("name is required")
        context_lines = int((body or {}).get("context_lines", 3) or 3)
        return diff_conf_backup(self.config, name, context_lines=context_lines)

    def _post_settings_migration_backups_cleanup(self) -> dict:
        from migration_api import cleanup_migration_backups
        body = self._read_json_body()
        dry_run = bool((body or {}).get("dry_run", True))
        keep = int((body or {}).get("keep_per_active_id", 5) or 5)
        return cleanup_migration_backups(self.config, dry_run=dry_run, keep_per_active_id=keep)

    def _post_settings_jobs_import(self) -> dict:
        from settings_transfer_api import import_jobs_bundle
        body = self._read_json_body()
        bundle = body.get("bundle")
        bundle_text = str(body.get("bundle_text") or "").strip()
        if bundle is None and bundle_text:
            bundle = json.loads(bundle_text)
        if bundle is None:
            raise ValueError("bundle or bundle_text is required")
        mode = str(body.get("mode", "skip")).strip().lower()
        dry_run = bool(body.get("dry_run", True))
        selected_jobs = body.get("selected_jobs") if isinstance(body.get("selected_jobs"), list) else None
        per_job_mode = body.get("per_job_mode") if isinstance(body.get("per_job_mode"), dict) else None
        settings_mode = str(body.get("settings_mode", "merge")).strip().lower()
        per_profile_mode = body.get("per_profile_mode") if isinstance(body.get("per_profile_mode"), dict) else None
        return import_jobs_bundle(
            self.config,
            bundle,
            mode=mode,
            dry_run=dry_run,
            selected_jobs=selected_jobs,
            per_job_mode=per_job_mode,
            settings_mode=settings_mode,
            per_profile_mode=per_profile_mode,
        )

    def _post_settings_jobs_import_preview(self) -> dict:
        from settings_transfer_api import preview_jobs_bundle
        body = self._read_json_body()
        bundle = body.get("bundle")
        bundle_text = str(body.get("bundle_text") or "").strip()
        if bundle is None and bundle_text:
            bundle = json.loads(bundle_text)
        if bundle is None:
            raise ValueError("bundle or bundle_text is required")
        return preview_jobs_bundle(self.config, bundle)

    def _post_settings_jobs_export_secure(self) -> dict:
        from settings_transfer_api import export_jobs_bundle_encrypted
        body = self._read_json_body()
        password = str(body.get("password") or "")
        return export_jobs_bundle_encrypted(self.config, password)

    def _post_settings_repository_keys_export(self) -> dict:
        from settings_transfer_api import export_repository_keys_backup
        body = self._read_json_body()
        password = str(body.get("password") or "")
        return export_repository_keys_backup(self.config, password)

    def _post_settings_jobs_import_secure_preview(self) -> dict:
        from settings_transfer_api import preview_jobs_bundle_encrypted
        body = self._read_json_body()
        password = str(body.get("password") or "")
        payload_b64 = str(body.get("payload_b64") or "")
        if not payload_b64:
            raise ValueError("payload_b64 is required")
        return preview_jobs_bundle_encrypted(self.config, password, payload_b64)

    def _post_settings_jobs_import_secure(self) -> dict:
        from settings_transfer_api import import_jobs_bundle_encrypted
        body = self._read_json_body()
        password = str(body.get("password") or "")
        payload_b64 = str(body.get("payload_b64") or "")
        if not payload_b64:
            raise ValueError("payload_b64 is required")
        mode = str(body.get("mode", "skip")).strip().lower()
        dry_run = bool(body.get("dry_run", True))
        selected_jobs = body.get("selected_jobs") if isinstance(body.get("selected_jobs"), list) else None
        per_job_mode = body.get("per_job_mode") if isinstance(body.get("per_job_mode"), dict) else None
        settings_mode = str(body.get("settings_mode", "merge")).strip().lower()
        per_profile_mode = body.get("per_profile_mode") if isinstance(body.get("per_profile_mode"), dict) else None
        import_jobs = bool(body.get("import_jobs", True))
        import_passphrases = bool(body.get("import_passphrases", True))
        import_borg_keys = bool(body.get("import_borg_keys", False))
        return import_jobs_bundle_encrypted(
            self.config,
            password,
            payload_b64,
            mode=mode,
            dry_run=dry_run,
            selected_jobs=selected_jobs,
            per_job_mode=per_job_mode,
            settings_mode=settings_mode,
            per_profile_mode=per_profile_mode,
            import_jobs=import_jobs,
            import_passphrases=import_passphrases,
            import_borg_keys=import_borg_keys,
        )

    def _post_settings_secrets_backup_export(self) -> dict:
        from settings_transfer_api import export_secrets_backup
        body = self._read_json_body()
        password = str(body.get("password") or "")
        return export_secrets_backup(password)

    def _post_settings_secrets_backup_import(self) -> dict:
        from settings_transfer_api import import_secrets_backup
        body = self._read_json_body()
        password = str(body.get("password") or "")
        payload_b64 = str(body.get("payload_b64") or "")
        mode = str(body.get("mode", "skip")).strip().lower()
        selected_names = body.get("selected_names") if isinstance(body.get("selected_names"), list) else None
        if not payload_b64:
            raise ValueError("payload_b64 is required")
        return import_secrets_backup(password, payload_b64, mode=mode, selected_names=selected_names)

    def _post_settings_secrets_backup_preview(self) -> dict:
        from settings_transfer_api import preview_secrets_backup
        body = self._read_json_body()
        password = str(body.get("password") or "")
        payload_b64 = str(body.get("payload_b64") or "")
        if not payload_b64:
            raise ValueError("payload_b64 is required")
        return preview_secrets_backup(password, payload_b64)

    def _post_settings_profile_secrets_export(self) -> dict:
        from settings_transfer_api import export_profile_secrets_backup
        body = self._read_json_body()
        password = str(body.get("password") or "")
        return export_profile_secrets_backup(self.config, password)

    def _post_settings_profile_secrets_preview(self) -> dict:
        from settings_transfer_api import preview_profile_secrets_backup
        body = self._read_json_body()
        password = str(body.get("password") or "")
        payload_b64 = str(body.get("payload_b64") or "")
        if not payload_b64:
            raise ValueError("payload_b64 is required")
        return preview_profile_secrets_backup(self.config, password, payload_b64)

    def _post_settings_profile_secrets_import(self) -> dict:
        from settings_transfer_api import import_profile_secrets_backup
        body = self._read_json_body()
        password = str(body.get("password") or "")
        payload_b64 = str(body.get("payload_b64") or "")
        mode = str(body.get("mode", "skip")).strip().lower()
        settings_mode = str(body.get("settings_mode", "merge")).strip().lower()
        selected_entries = body.get("selected_entries") if isinstance(body.get("selected_entries"), list) else None
        profile_map = body.get("profile_map") if isinstance(body.get("profile_map"), dict) else None
        per_profile_mode = body.get("per_profile_mode") if isinstance(body.get("per_profile_mode"), dict) else None
        if not payload_b64:
            raise ValueError("payload_b64 is required")
        return import_profile_secrets_backup(
            self.config,
            password,
            payload_b64,
            mode=mode,
            selected_entries=selected_entries,
            profile_map=profile_map,
            settings_mode=settings_mode,
            per_profile_mode=per_profile_mode,
        )

    def _post_storagebox_key_status(self) -> dict:
        from config_api import storagebox_key_status
        body = self._read_json_body()
        profile_key = str(body.get("profile_key") or "").strip().lower()
        return storagebox_key_status(self.config, profile_key=profile_key)

    def _post_storagebox_key_generate(self) -> dict:
        from config_api import storagebox_key_generate
        body = self._read_json_body()
        profile_key = str(body.get("profile_key") or "").strip().lower()
        return storagebox_key_generate(self.config, profile_key=profile_key)

    def _post_storagebox_key_public(self) -> dict:
        from config_api import storagebox_key_public
        body = self._read_json_body()
        profile_key = str(body.get("profile_key") or "").strip().lower()
        return storagebox_key_public(self.config, profile_key=profile_key)

    def _post_storagebox_key_deploy(self) -> dict:
        from config_api import storagebox_key_deploy
        body = self._read_json_body()
        password = str(body.get("password") or "")
        profile_key = str(body.get("profile_key") or "").strip().lower()
        if not password:
            raise ValueError("password is required")
        return storagebox_key_deploy(self.config, password, profile_key=profile_key)

    def _post_storagebox_test(self) -> dict:
        from config_api import storagebox_connection_test
        body = self._read_json_body()
        profile_key = str(body.get("profile_key") or "").strip().lower()
        return storagebox_connection_test(self.config, profile_key=profile_key)

    def _get_storagebox_deploy_state(self, qs: str) -> dict:
        from urllib.parse import parse_qs as _pqs
        from config_api import storagebox_deploy_state
        params = _pqs(qs)
        sid = str((params.get("session_id") or [""])[0]).strip()
        if not sid:
            raise ValueError("session_id is required")
        return storagebox_deploy_state(sid)

    def _post_storagebox_deploy_start(self) -> dict:
        from config_api import storagebox_deploy_start
        body = self._read_json_body()
        target_override = str(body.get("target_type_override", "")).strip().lower()
        profile_key = str(body.get("profile_key") or "").strip().lower()
        return storagebox_deploy_start(self.config, target_override=target_override, profile_key=profile_key)

    def _post_storagebox_deploy_input(self) -> dict:
        from config_api import storagebox_deploy_input
        body = self._read_json_body()
        sid = str(body.get("session_id", "")).strip()
        text = str(body.get("text", ""))
        if not sid:
            raise ValueError("session_id is required")
        return storagebox_deploy_input(sid, text)

    def _post_storagebox_deploy_cancel(self) -> dict:
        from config_api import storagebox_deploy_cancel
        body = self._read_json_body()
        sid = str(body.get("session_id", "")).strip()
        if not sid:
            raise ValueError("session_id is required")
        return storagebox_deploy_cancel(sid)

    def _post_run_job(self) -> dict:
        self._require_data_dir_ready()
        from jobs_api import JobManager, discover_jobs, get_job_runtime_state, resolve_data_root, resolve_scripts_dir
        from lifecycle_log import emit_lifecycle
        body = self._read_json_body()
        job_key = body.get("job_key", "")
        if not job_key:
            raise ValueError("job_key is required")

        borg_scripts_dir = resolve_scripts_dir(self.config)
        backup_scripts_dir = Path(self.config["BACKUP_SCRIPTS_DIR"])
        data_root = resolve_data_root(self.config)
        jobs = {j.key: j for j in discover_jobs(borg_scripts_dir, data_root)}
        if job_key not in jobs:
            raise ValueError(f"Unknown job: {job_key}")
        if not jobs[job_key].enabled:
            raise RuntimeError(f"Job is disabled: {job_key}")
        if get_job_runtime_state(self.config, job_key).get("running"):
            raise RuntimeError("Job is already running")

        info = jobs[job_key]
        plugin_runtime = Path(__file__).resolve().parent / "runtime"
        existing_pp = os.environ.get("PYTHONPATH", "")
        runtime_pp = str(plugin_runtime)
        merged_pp = f"{runtime_pp}:{existing_pp}" if existing_pp else runtime_pp
        if info.standard != "wizard":
            raise RuntimeError(f"Unsupported job standard: {info.standard}")
        runner = Path(__file__).resolve().parent / "api" / "wizard_runner.py"
        request_id = str(getattr(self, "_current_request_id", "") or "")
        session = self._get_current_session_meta() or {}
        actor = _normalize_username(session.get("username", ""))
        source = "schedule" if bool(body.get("scheduled")) else (
            "api-token" if self._has_valid_api_token_header() else "manual"
        )
        if not actor and source == "schedule":
            actor = "scheduler"
        if not actor and source == "api-token":
            actor = "api-token"
        extra_env = {
            "BORG_UI_BORG_SCRIPTS_DIR": str(borg_scripts_dir),
            "BORG_UI_JOB_KEY": job_key,
            "BORG_UI_APP_VERSION": APP_VERSION,
            "BORG_UI_REQUEST_ID": request_id,
            "BORG_UI_REQUEST_SOURCE": source,
            "BORG_UI_REQUEST_ACTOR": actor,
            "PYTHONPATH": merged_pp,
        }
        ok, err = JobManager.get().start(
            job_key,
            ["python3", str(runner)],
            backup_scripts_dir,
            extra_env=extra_env,
        )
        if not ok:
            raise RuntimeError(err)
        state = JobManager.get().get_state(job_key)
        emit_lifecycle(
            "JOB",
            "requested",
            request_id=request_id,
            source=source,
            actor=actor,
            job_key=job_key,
            backup_type=info.backup_type,
            location=info.location,
            run_id=state.get("run_id", ""),
        )
        return {"started": True, "job_key": job_key, "run_id": state.get("run_id", "")}

    def _post_cancel_job(self) -> dict:
        from jobs_api import cancel_job

        body = self._read_json_body()
        job_key = str(body.get("job_key") or "").strip()
        run_id = str(body.get("run_id") or "").strip()
        if not job_key or not run_id:
            raise ValueError("job_key and run_id are required")
        session = self._get_current_session_meta() or {}
        requested_by = _normalize_username(session.get("username", ""))
        try:
            state = cancel_job(self.config, job_key, run_id, requested_by=requested_by)
        except (FileNotFoundError, RuntimeError) as exc:
            raise ApiConflictError(str(exc), "job_cancel_unavailable") from exc
        return {
            "cancel_requested": True,
            "job_key": job_key,
            "run_id": run_id,
            "phase": state.get("phase", ""),
            "cancellation_deferred": bool(state.get("cancellation_deferred")),
            "message_key": state.get("message_key", ""),
        }

    # ── SSE-Handler ───────────────────────────────────────────────────────────

    def _handle_sse(self, job_key: str):
        from jobs_api import stream_job_output
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._send_refreshed_session_header()
        self.end_headers()
        try:
            for chunk in stream_job_output(self.config, job_key):
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # Client hat Verbindung getrennt

    # ── Hilfsmethoden ────────────────────────────────────────────────────────

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self._last_json_body = {}
            return {}
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict):
            self._last_json_body = data
            return data
        self._last_json_body = {}
        return {}

    def _serve_file(self, filepath: Path, *, allowed_root: Path):
        root = allowed_root.resolve()
        filepath = filepath.resolve()
        try:
            filepath.relative_to(root)
        except ValueError:
            self.send_error(404, "Not found")
            return
        if not filepath.exists() or not filepath.is_file():
            self.send_error(404, "Not found")
            return
        content_type = MIME_TYPES.get(filepath.suffix.lower(), "application/octet-stream")
        try:
            content = filepath.read_bytes()
        except OSError:
            self.send_error(500, "Read error")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _serve_login_page(self):
        if self._bootstrap_required():
            self.send_response(302)
            self.send_header("Location", "/setup-admin")
            self.end_headers()
            return
        if not self._ui_auth_enabled():
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return
        username_field = """<div class="form-group">
        <label class="form-label" data-i18n="auth.username"></label>
        <input id="login-username" class="form-input" type="text" autocomplete="username" autofocus>
      </div>"""
        login_payload = "const un=(document.getElementById('login-username')?.value||'').trim();const payload={username:un,password:pw};"
        html = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Borg Backup Login</title>
<script>
(() => {
  try {
    const key = 'bbui_theme_preference';
    const pref = localStorage.getItem(key);
    const clean = (pref === 'light' || pref === 'dark' || pref === 'system') ? pref : 'system';
    const resolved = clean === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : clean;
    document.documentElement.setAttribute('data-theme', resolved);
  } catch (error) {
    const resolved = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', resolved);
  }
})();
</script>
<link rel="stylesheet" href="/ui/style.css">
<link rel="stylesheet" href="/ui/design-system.css">
<script src="/ui/js/components/i18n.js"></script>
<style>
  .login-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
  .login-card{width:min(440px,100%);background:var(--bg-surface);border:1px solid var(--border);border-radius:8px;box-shadow:var(--shadow-soft)}
  .login-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;border-bottom:1px solid var(--border)}
  .login-brand{display:flex;align-items:center;gap:9px}
  .login-logo{width:28px;height:28px;object-fit:contain;display:block}
  .login-title{font-size:14px;font-weight:600;color:var(--text-primary);line-height:1}
  .login-body{padding:12px 14px 14px 14px;display:grid;gap:10px}
  .login-msg{margin-top:2px}
  .login-sub{margin:0;color:var(--text-secondary);font-size:12px;line-height:1.35}
  .login-meta{font-size:11px;color:var(--text-muted)}
  .login-btn{width:100%;justify-content:center;height:34px}
  .form-group{margin:0}
  .form-label{font-size:12px}
  .form-input{height:34px}
</style>
</head>
<body>
<main class="login-wrap">
  <section class="login-card">
    <div class="login-head">
      <div class="login-brand">
        <img class="login-logo" src="/ui/assets/app-icon.png" alt="" aria-hidden="true">
        <div class="login-title">Borg Backup</div>
      </div>
      <div class="login-meta" data-i18n="auth.loginTitle"></div>
    </div>
    <div class="login-body">
      <p class="login-sub" data-i18n="auth.loginSubtitle"></p>
      __USERNAME_FIELD__
      <div class="form-group">
        <label class="form-label" data-i18n="auth.password"></label>
        <input id="login-password" class="form-input" type="password" autocomplete="current-password">
      </div>
      <div id="login-msg" class="status-message hidden login-msg"></div>
      <button id="login-btn" class="btn btn-primary login-btn" data-i18n="auth.loginAction"></button>
    </div>
  </section>
</main>
<script>
const btn=document.getElementById('login-btn');const msg=document.getElementById('login-msg');
const i18nReady=window.BBUI.components.i18n.init().then(()=>{document.title=window.BBUI.components.i18n.t('auth.loginTitle');});
function authT(key){return window.BBUI.components.i18n.t(key);}
function authApiError(data,fallback){const code=String(data?.code||'').trim();if(code==='forbidden')return authT(fallback);const key=code?`api.errors.${code}`:'';const translated=key?authT(key):'';return translated&&translated!==key?translated:authT(fallback);}
function showErr(t){msg.textContent=t;msg.className='status-message error login-msg';}
async function doLogin(){btn.classList.add('loading');msg.className='status-message hidden login-msg';
try{await i18nReady;const pw=document.getElementById('login-password').value||'';__LOGIN_PAYLOAD__const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
const d=await r.json();if(!r.ok||!d.ok)throw new Error(authApiError(d,'auth.loginFailed'));window.location.href='/';}
catch(e){showErr(e.message||authT('auth.loginFailed'));}
finally{btn.classList.remove('loading');}}
btn.addEventListener('click',doLogin);
document.getElementById('login-password').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin();});
if(document.getElementById('login-username')){document.getElementById('login-username').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin();});}
</script>
</body></html>"""
        html = html.replace("__USERNAME_FIELD__", username_field)
        html = html.replace("__LOGIN_PAYLOAD__", login_payload)
        content = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _serve_setup_admin_page(self):
        if not self._bootstrap_required():
            self.send_response(302)
            self.send_header("Location", "/login" if self._ui_auth_enabled() else "/")
            self.end_headers()
            return
        html = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Borg Backup Setup</title>
<script>
(() => {
  try {
    const key = 'bbui_theme_preference';
    const pref = localStorage.getItem(key);
    const clean = (pref === 'light' || pref === 'dark' || pref === 'system') ? pref : 'system';
    const resolved = clean === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : clean;
    document.documentElement.setAttribute('data-theme', resolved);
  } catch (error) {
    const resolved = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', resolved);
  }
})();
</script>
<link rel="stylesheet" href="/ui/style.css">
<link rel="stylesheet" href="/ui/design-system.css">
<script src="/ui/js/components/i18n.js"></script>
<style>
  .login-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
  .login-card{width:min(560px,100%);background:var(--bg-surface);border:1px solid var(--border);border-radius:10px;box-shadow:var(--shadow-soft)}
  .login-head{display:flex;align-items:center;gap:10px;padding:16px 18px;border-bottom:1px solid var(--border)}
  .login-logo{width:30px;height:30px;object-fit:contain;display:block}
  .login-title{font-size:16px;font-weight:600;color:var(--text-primary)}
  .login-sub{padding:12px 18px 0 18px;color:var(--text-secondary);font-size:13px}
  .login-body{padding:12px 18px 18px 18px}
  .login-msg{margin-top:10px}
</style>
</head><body>
<main class="login-wrap"><section class="login-card">
<div class="login-head"><img class="login-logo" src="/ui/assets/app-icon.png" alt="" aria-hidden="true"><div class="login-title" data-i18n="auth.setupTitle"></div></div>
<div class="login-sub" data-i18n="auth.setupSubtitle"></div>
<div class="login-body">
<div class="form-group"><label class="form-label" data-i18n="auth.username"></label><input id="setup-username" class="form-input" type="text" autocomplete="username" autofocus></div>
<div class="form-group"><label class="form-label" data-i18n="auth.password"></label><input id="setup-password" class="form-input" type="password" autocomplete="new-password"><div class="ui-field__hint" data-i18n="auth.passwordHint"></div></div>
<div class="form-group"><label class="form-label" data-i18n="auth.passwordConfirm"></label><input id="setup-password-confirm" class="form-input" type="password" autocomplete="new-password"></div>
<div id="setup-msg" class="status-message hidden login-msg"></div>
<button id="setup-btn" class="btn btn-primary" style="width:100%" data-i18n="auth.setupAction"></button>
</div></section></main>
<script>
const btn=document.getElementById('setup-btn');const msg=document.getElementById('setup-msg');
const i18nReady=window.BBUI.components.i18n.init().then(()=>{document.title=window.BBUI.components.i18n.t('auth.setupTitle');});
function authT(key){return window.BBUI.components.i18n.t(key);}
function setupValidationMessage(data){
 const raw=String(data?.message||data?.details||'').trim();
 const known={
  'Username is required':'auth.errors.usernameRequired',
  'Username is invalid (3-64 characters: a-z, 0-9, ., _, -)':'auth.errors.usernameInvalid',
  'Password must contain at least 12 characters':'auth.errors.passwordTooShort',
  'The password confirmation does not match':'auth.errors.passwordMismatch',
  'Administrator setup is not required':'auth.errors.setupNotRequired'
 };
 const key=known[raw]||'';return key?authT(key):'';
}
function authApiError(data,fallback){const code=String(data?.code||'').trim();if(code==='forbidden')return authT(fallback);if(code==='bad_request')return setupValidationMessage(data)||authT(fallback);const key=code?`api.errors.${code}`:'';const translated=key?authT(key):'';return translated&&translated!==key?translated:authT(fallback);}
function showErr(t){msg.textContent=t;msg.className='status-message error login-msg';}
async function doSetup(){btn.classList.add('loading');msg.className='status-message hidden login-msg';
try{
 await i18nReady;
 const username=(document.getElementById('setup-username').value||'').trim();
 const password=document.getElementById('setup-password').value||'';
 const password_confirm=document.getElementById('setup-password-confirm').value||'';
 if(!username)throw new Error(authT('auth.errors.usernameRequired'));
 if(!/^[a-z0-9._-]{3,64}$/.test(username))throw new Error(authT('auth.errors.usernameInvalid'));
 if(password.length<12)throw new Error(authT('auth.errors.passwordTooShort'));
 if(password!==password_confirm)throw new Error(authT('auth.errors.passwordMismatch'));
 const r=await fetch('/api/auth/setup-admin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password,password_confirm})});
 const d=await r.json();if(!r.ok||!d.ok)throw new Error(authApiError(d,'auth.setupFailed'));
 const lr=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
 const ld=await lr.json();if(!lr.ok||!ld.ok)throw new Error(authApiError(ld,'auth.autoLoginFailed'));
 window.location.href='/';
}catch(e){showErr(e.message||authT('auth.setupFailed'));}
finally{btn.classList.remove('loading');}}
btn.addEventListener('click',doSetup);
['setup-username','setup-password','setup-password-confirm'].forEach(id=>document.getElementById(id).addEventListener('keydown',e=>{if(e.key==='Enter')doSetup();}));
</script></body></html>"""
        content = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _serve_admin_recovery_page(self, query: str = ""):
        if self._bootstrap_required():
            self.send_response(302)
            self.send_header("Location", "/setup-admin")
            self.end_headers()
            return
        qs = parse_qs(query or "")
        token = str((qs.get("token") or [""])[0] or "").strip()
        token_json = json.dumps(token)
        try:
            recovery_token_info = _describe_admin_recovery_token(self.config, token)
        except Exception:
            recovery_token_info = {"valid": False, "username": "", "expires_at": ""}
        recovery_username = str(recovery_token_info.get("username") or "").strip()
        recovery_account_html = ""
        if recovery_username:
            recovery_account_html = (
                '<div class="recovery-account">'
                '<span data-i18n="auth.recoveryAccount"></span> '
                f'<strong>{_html_escape(recovery_username)}</strong>'
                '</div>'
            )
        html = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Borg Backup Admin Recovery</title>
<script>
(() => {
  try {
    const key = 'bbui_theme_preference';
    const pref = localStorage.getItem(key);
    const clean = (pref === 'light' || pref === 'dark' || pref === 'system') ? pref : 'system';
    const resolved = clean === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : clean;
    document.documentElement.setAttribute('data-theme', resolved);
  } catch (error) {
    const resolved = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', resolved);
  }
})();
</script>
<link rel="stylesheet" href="/ui/style.css">
<link rel="stylesheet" href="/ui/design-system.css">
<script src="/ui/js/components/i18n.js"></script>
<style>
  .login-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
  .login-card{width:min(520px,100%);background:var(--bg-surface);border:1px solid var(--border);border-radius:8px;box-shadow:var(--shadow-soft)}
  .login-head{display:flex;align-items:center;gap:10px;padding:16px 18px;border-bottom:1px solid var(--border)}
  .login-logo{width:30px;height:30px;object-fit:contain;display:block}
  .login-title{font-size:16px;font-weight:600;color:var(--text-primary)}
  .login-sub{padding:12px 18px 0 18px;color:var(--text-secondary);font-size:13px;line-height:1.45}
  .login-body{padding:12px 18px 18px 18px;display:grid;gap:12px}
  .login-msg{margin-top:10px}
  .recovery-account{font-size:13px;color:var(--text-secondary);padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-card)}
  .recovery-account strong{color:var(--text-primary)}
  .login-body .form-group{margin:0}
  .login-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .login-actions .btn{flex:1;justify-content:center;min-width:160px}
</style>
</head><body>
<main class="login-wrap"><section class="login-card">
<div class="login-head"><img class="login-logo" src="/ui/assets/app-icon.png" alt="" aria-hidden="true"><div class="login-title" data-i18n="auth.recoveryTitle"></div></div>
<div class="login-sub" data-i18n="auth.recoverySubtitle"></div>
<div class="login-body">
__RECOVERY_ACCOUNT__
<div class="form-group"><label class="form-label" data-i18n="auth.password"></label><input id="recovery-password" class="form-input" type="password" autocomplete="new-password" autofocus><div class="ui-field__hint" data-i18n="auth.passwordHint"></div></div>
<div class="form-group"><label class="form-label" data-i18n="auth.passwordConfirm"></label><input id="recovery-password-confirm" class="form-input" type="password" autocomplete="new-password"></div>
<div id="recovery-msg" class="status-message hidden login-msg"></div>
<div class="login-actions">
  <button id="recovery-btn" class="btn btn-primary" data-i18n="auth.recoveryAction"></button>
  <a id="login-link" class="btn btn-secondary hidden" href="/login" data-i18n="auth.recoveryLogin"></a>
</div>
</div></section></main>
<script>
const recoveryToken=__TOKEN__;
const btn=document.getElementById('recovery-btn');const msg=document.getElementById('recovery-msg');const loginLink=document.getElementById('login-link');
const i18nReady=window.BBUI.components.i18n.init().then(()=>{document.title=window.BBUI.components.i18n.t('auth.recoveryTitle');});
function authT(key){return window.BBUI.components.i18n.t(key);}
function recoveryValidationMessage(data){
 const raw=String(data?.message||data?.details||'').trim();
 const known={
  'Password must contain at least 12 characters':'auth.errors.passwordTooShort',
  'The password confirmation does not match':'auth.errors.passwordMismatch',
  'Admin recovery link is invalid or expired':'auth.errors.recoveryInvalid',
  'Admin user was not found':'auth.errors.recoveryInvalid'
 };
 const key=known[raw]||'';return key?authT(key):'';
}
function authApiError(data,fallback){const code=String(data?.code||'').trim();if(code==='bad_request')return recoveryValidationMessage(data)||authT(fallback);const key=code?`api.errors.${code}`:'';const translated=key?authT(key):'';return translated&&translated!==key?translated:authT(fallback);}
function showMsg(type,t){msg.textContent=t;msg.className='status-message '+type+' login-msg';}
async function doRecovery(){btn.classList.add('loading');msg.className='status-message hidden login-msg';
try{
 await i18nReady;
 if(!recoveryToken)throw new Error(authT('auth.errors.recoveryInvalid'));
 const password=document.getElementById('recovery-password').value||'';
 const password_confirm=document.getElementById('recovery-password-confirm').value||'';
 if(password.length<12)throw new Error(authT('auth.errors.passwordTooShort'));
 if(password!==password_confirm)throw new Error(authT('auth.errors.passwordMismatch'));
 const r=await fetch('/api/auth/admin-recovery',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:recoveryToken,password,password_confirm})});
 const d=await r.json();if(!r.ok||!d.ok)throw new Error(authApiError(d,'auth.recoveryFailed'));
 showMsg('success',authT('auth.recoverySuccess'));btn.disabled=true;loginLink.classList.remove('hidden');
}catch(e){showMsg('error',e.message||authT('auth.recoveryFailed'));}
finally{btn.classList.remove('loading');}}
btn.addEventListener('click',doRecovery);
['recovery-password','recovery-password-confirm'].forEach(id=>document.getElementById(id).addEventListener('keydown',e=>{if(e.key==='Enter')doRecovery();}));
</script></body></html>"""
        html = html.replace("__TOKEN__", token_json)
        html = html.replace("__RECOVERY_ACCOUNT__", recovery_account_html)
        content = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _handle_api(self, fn):
        request_id = uuid.uuid4().hex[:12]
        started = perf_counter()
        try:
            self._current_request_id = request_id
            self._refreshed_session_cookie = ""
            path = urlparse(self.path).path
            if not self._authorize_api_request(path, request_id):
                return
            refreshed_session_cookie = self._refreshed_session_cookie
            self._extra_response_headers = []
            data = fn()
            refreshed_session_cookie = self._refreshed_session_cookie or refreshed_session_cookie
            if refreshed_session_cookie:
                self._extra_response_headers.append(("Set-Cookie", refreshed_session_cookie))
            content = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            cache_control = (
                "no-store"
                if path in {"/api/widget/summary", "/api/settings/homepage-widget-token", "/api/repositories/key-export"}
                else "no-cache"
            )
            self.send_header("Cache-Control", cache_control)
            self.send_header("X-Request-Id", request_id)
            for hk, hv in self._extra_response_headers:
                self.send_header(hk, hv)
            self.end_headers()
            self.wfile.write(content)
            elapsed_ms = int((perf_counter() - started) * 1000)
            parsed_path = urlparse(self.path).path
            ctx = self._extract_request_context()
            if isinstance(data, dict):
                ctx = self._augment_context_from_response(parsed_path, data, ctx)
            if self._should_log_api_success(self.command, self.path, elapsed_ms, len(content)):
                _log(
                    f"API ok request_id={request_id} status=200 method={self.command} path={self.path} "
                    f"duration_ms={elapsed_ms} bytes={len(content)} context={json.dumps(ctx, ensure_ascii=False)}"
                )
        except FileNotFoundError as exc:
            self._send_api_error(404, "not_found", str(exc), request_id=request_id)
        except PermissionError as exc:
            self._send_api_error(403, "forbidden", str(exc), request_id=request_id)
        except RateLimitExceeded as exc:
            self._send_api_error(429, "rate_limited", str(exc), request_id=request_id)
        except ValueError as exc:
            error_code = str(getattr(exc, "api_code", "") or "bad_request")
            self._current_error_message_params = getattr(exc, "api_message_params", {}) if isinstance(getattr(exc, "api_message_params", {}), dict) else {}
            try:
                error_status = int(getattr(exc, "api_status", 400) or 400)
            except (TypeError, ValueError):
                error_status = 400
            self._send_api_error(error_status, error_code, str(exc), request_id=request_id)
        except ApiConflictError as exc:
            self._send_api_error(409, exc.code, str(exc), request_id=request_id)
        except Exception as exc:
            if exc.__class__.__module__.endswith("inventory_store"):
                self._send_api_error(503, "inventory_unavailable", str(exc), request_id=request_id)
            else:
                self._send_api_error(500, "internal_error", str(exc), request_id=request_id)
        finally:
            self._current_request_id = ""
            self._current_error_message_params = {}
            self._last_json_body = {}
            self._extra_response_headers = []

    def _send_api_error(self, status: int, code: str, message: str, *, request_id: str) -> None:
        safe_message = _mask_secrets(message)
        body = {
            "code": code,
            "message": safe_message,
            "details": safe_message,
            "request_id": request_id,
            "error": safe_message,  # backward-compatible field
        }
        params = getattr(self, "_current_error_message_params", {})
        if isinstance(params, dict) and params:
            body["message_params"] = params
        ctx = self._extract_request_context()
        if code == "maintenance_mode":
            ctx.update(self._startup_migration_context())
        elif safe_message:
            self._add_context_value(ctx, "reason", safe_message[:240])
        _log(
            f'API error request_id={request_id} status={status} method={self.command} path={self.path} code={code} '
            f'context={json.dumps(ctx, ensure_ascii=False)}'
        )
        try:
            p = urlparse(self.path).path
            if p.startswith("/api/auth/") and p not in {"/api/auth/status"}:
                self._security_audit("auth_api_error", "failed", target=p, detail=f"status={status},code={code}")
        except Exception:
            pass
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Request-Id", request_id)
        if status == 401:
            self.send_header("WWW-Authenticate", "Bearer")
        self.end_headers()
        self.wfile.write(payload)

    def _extract_request_context(self) -> dict:
        body = self._last_json_body if isinstance(self._last_json_body, dict) else {}
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path

        def pick(*keys: str) -> object:
            for key in keys:
                value = body.get(key)
                if self._context_value_present(value):
                    return value
                query_value = (qs.get(key) or [""])[0]
                if self._context_value_present(query_value):
                    return query_value
            return ""

        context: dict[str, object] = {}
        self._add_context_value(context, "job_key", pick("job_key", "job"))
        job_keys = body.get("job_keys")
        if not context.get("job_key") and isinstance(job_keys, list) and len(job_keys) == 1:
            self._add_context_value(context, "job_key", job_keys[0])
        elif isinstance(job_keys, list) and job_keys:
            self._add_context_value(context, "selected_jobs", job_keys[:10])
        self._add_context_value(context, "backup_type", pick("backup_type"))
        self._add_context_value(context, "location", pick("location"))
        self._add_context_value(context, "profile_key", pick("profile_key"))
        self._add_context_value(context, "storage_key", pick("storage_key"))
        self._add_context_value(context, "storage_type", pick("storage_type", "type", "location"))
        self._add_context_value(context, "repository_key", pick("repository_key"))
        self._add_context_value(context, "repository_mode", pick("mode"))
        self._add_context_value(context, "profile_id", pick("profile_id", "id"))
        self._add_context_value(context, "provider", pick("provider"))
        self._add_context_value(context, "event", pick("event", "event_type"))
        self._add_context_value(context, "restore_id", pick("restore_id"))
        self._add_context_value(context, "run_id", pick("run_id"))
        self._add_context_value(context, "archive", pick("archive"))
        self._add_context_value(context, "level", pick("level"))
        self._add_context_value(context, "mode", pick("mode"))
        self._add_context_value(context, "action", pick("action"))
        self._add_context_value(context, "phase", self._phase_for_request(getattr(self, "command", ""), path, body))
        self._add_context_value(context, "source", self._request_source(body))
        if path.startswith("/api/auth/"):
            self._add_context_value(context, "auth_user", pick("username"))
        if path.startswith("/api/notification-profiles") and context.get("profile_id"):
            self._add_apprise_profile_context(context, str(context.get("profile_id") or ""))
        return context

    @staticmethod
    def _augment_context_from_response(path: str, data: dict, ctx: dict) -> dict:
        out = dict(ctx or {})
        if path == "/api/jobs/running" and not str(out.get("job_key") or "").strip() and isinstance(data, dict):
            running_keys = [
                str(k) for k, v in data.items()
                if isinstance(v, dict) and bool(v.get("running"))
            ]
            if running_keys:
                out["job_key"] = _mask_secrets(",".join(running_keys[:5]))
        if path == "/api/repositories" and isinstance(data, dict):
            for key in ("repository_key", "mode"):
                if data.get(key):
                    context_key = "repository_mode" if key == "mode" else key
                    out[context_key] = _mask_secrets(str(data.get(key)))
            for key in ("repository_deleted", "secret_deleted"):
                if isinstance(data.get(key), bool):
                    out[key] = data[key]
        if isinstance(data, dict):
            for key in ("run_id", "restore_id", "repository_key", "profile_id", "provider"):
                if data.get(key):
                    BackupUIHandler._add_context_value(out, key, data.get(key))
            profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
            if profile:
                BackupUIHandler._add_context_value(out, "profile_id", profile.get("id"))
                BackupUIHandler._add_context_value(out, "profile_name", profile.get("name"))
                BackupUIHandler._add_context_value(out, "provider", profile.get("provider"))
            if path in {"/api/jobs/run", "/api/restore-tests/run", "/api/restore-tests/run-job"}:
                BackupUIHandler._add_context_value(out, "selected_jobs", data.get("selected_jobs"))
        return out

    @staticmethod
    def _context_value_present(value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set)):
            return any(BackupUIHandler._context_value_present(item) for item in value)
        return True

    @staticmethod
    def _safe_context_value(value: object, *, max_len: int = 160) -> str:
        text = _mask_secrets(str(value or "").replace("\r", " ").replace("\n", " ").strip())
        if len(text) > max_len:
            return text[: max_len - 3] + "..."
        return text

    @staticmethod
    def _add_context_value(context: dict, key: str, value: object) -> None:
        if not BackupUIHandler._context_value_present(value):
            return
        if isinstance(value, (list, tuple, set)):
            cleaned = [
                BackupUIHandler._safe_context_value(item, max_len=80)
                for item in value
                if BackupUIHandler._context_value_present(item)
            ]
            if cleaned:
                context[key] = cleaned
            return
        context[key] = BackupUIHandler._safe_context_value(value)

    def _request_source(self, body: dict) -> str:
        if bool(body.get("scheduled")):
            return "schedule"
        try:
            if self._has_valid_api_token_header():
                return "api-token"
        except Exception:
            pass
        return "manual"

    @staticmethod
    def _phase_for_request(method: str, path: str, body: dict) -> str:
        method = str(method or "").upper()
        if path == "/api/jobs/run":
            return "run"
        if path == "/api/jobs/cancel":
            return "cancel"
        if path == "/api/restore-tests/run" or path == "/api/restore-tests/run-job":
            return "restore-test-run"
        if path == "/api/restore/precheck":
            return "precheck"
        if path == "/api/restore/start":
            return "restore-start"
        if path == "/api/restore/repo-stats":
            return "repo-stats"
        if path == "/api/restore/archives":
            return "restore-archives"
        if path == "/api/restore/files":
            return "restore-files"
        if path == "/api/restore/download-check":
            return "download-check"
        if path == "/api/restore/state":
            return "restore-state"
        if path == "/api/restore/history":
            return "restore-history"
        if path == "/api/restore/history/detail":
            return "restore-history-detail"
        if path == "/api/reports/data":
            return "report-data"
        if path == "/api/reports/jobs":
            return "report-jobs"
        if path == "/api/history":
            return "history-list"
        if path == "/api/history/log":
            return "history-log"
        if path == "/api/storage/check/run":
            return str(body.get("action") or "check")
        if path == "/api/storage/smb-action":
            return str(body.get("action") or "smb-action")
        if path == "/api/storages/test" or path == "/api/storage/test":
            return "test"
        if path == "/api/storages":
            return "save"
        if path == "/api/repositories/validate":
            return "validate"
        if path == "/api/repositories/info":
            return "refresh-info"
        if path == "/api/repositories/key-export":
            return "key-export"
        if path == "/api/repositories/key-import":
            return "key-import"
        if path == "/api/repositories/lifecycle" or path == "/api/repositories":
            if method == "DELETE":
                return str(body.get("mode") or "delete")
            if method == "PUT":
                return "update"
            return str(body.get("mode") or "save")
        if path == "/api/notification-profiles/validate":
            return "validate"
        if path == "/api/notification-profiles/test":
            return "test"
        if path == "/api/notification-profiles":
            if method == "POST":
                return "create"
            if method == "PUT":
                return "update"
            if method == "DELETE":
                return "delete"
            return "save"
        return ""

    def _add_apprise_profile_context(self, context: dict, profile_id: str) -> None:
        if context.get("provider") and context.get("profile_name"):
            return
        try:
            from apprise_profiles_api import get_profile
            profile = get_profile(self.config, profile_id).get("profile", {})
        except Exception:
            return
        if isinstance(profile, dict):
            self._add_context_value(context, "profile_name", profile.get("name"))
            self._add_context_value(context, "provider", profile.get("provider"))

    def _startup_migration_context(self) -> dict:
        state = _public_startup_state(self.config)
        context: dict[str, object] = {}
        failures = state.get("failures") if isinstance(state.get("failures"), list) else []
        first = failures[0] if failures and isinstance(failures[0], dict) else {}
        self._add_context_value(context, "migration_id", first.get("migration_id") or ",".join(state.get("failed_migrations") or []))
        self._add_context_value(context, "phase", first.get("phase"))
        self._add_context_value(context, "status", state.get("reason_code") or state.get("severity"))
        self._add_context_value(context, "reason", first.get("error") or state.get("message"))
        return context

    def _verbose_access_log_enabled(self) -> bool:
        raw = str(
            os.environ.get("BBUI_VERBOSE_ACCESS_LOG")
            or self.config.get("LOG_VERBOSE_ACCESS", "")
            or ""
        ).strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _slow_get_threshold_ms(self) -> int:
        raw = str(self.config.get("LOG_SLOW_GET_THRESHOLD_MS", "500") or "500").strip()
        try:
            return max(1, int(raw))
        except ValueError:
            return 500

    def _large_get_threshold_bytes(self) -> int:
        raw = str(self.config.get("LOG_LARGE_GET_THRESHOLD_BYTES", "262144") or "262144").strip()
        try:
            return max(1024, int(raw))
        except ValueError:
            return 262144

    def _is_routine_success_get_path(self, path: str) -> bool:
        parsed_path = urlparse(str(path or "")).path
        if parsed_path in self._ROUTINE_GET_PATHS:
            return True
        return any(parsed_path.startswith(prefix) for prefix in self._ROUTINE_GET_PREFIXES)

    def _should_log_api_success(self, method: str, path: str, duration_ms: int, bytes_out: int) -> bool:
        if self._verbose_access_log_enabled():
            return True
        if str(method or "").upper() != "GET":
            return True
        if int(duration_ms) >= self._slow_get_threshold_ms():
            return True
        if int(bytes_out) >= self._large_get_threshold_bytes():
            return True
        return not self._is_routine_success_get_path(path)

    def log_message(self, fmt, *args):
        msg = fmt % args
        match = re.match(r'^"[A-Z]+ [^"]+ HTTP/[0-9.]+"\s+([0-9]{3})\b', msg)
        if match:
            status = int(match.group(1))
            if self._verbose_access_log_enabled() or status >= 400:
                _log(msg)
            return
        _log(msg)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _start_notification_reminder_loop(config: dict) -> threading.Thread | None:
    def _interval_seconds() -> int:
        try:
            from config_api import read_expanded_conf
            conf = read_expanded_conf(config)
            raw = str(conf.get("NOTIFY_REMINDER_CHECK_INTERVAL_SECONDS", "3600") or "3600")
            return max(300, int(raw.strip()))
        except Exception:
            return 3600

    def _startup_delay_seconds() -> int:
        try:
            from config_api import read_expanded_conf
            conf = read_expanded_conf(config)
            raw = str(conf.get("NOTIFY_REMINDER_STARTUP_DELAY_SECONDS", "420") or "420")
            return max(60, min(1800, int(raw.strip())))
        except Exception:
            return 420

    def _run() -> None:
        time.sleep(_startup_delay_seconds())
        while True:
            try:
                from notification_reminder_api import run_due_notification_reminders
                result = run_due_notification_reminders(config)
                if int(result.get("checked") or 0) or int(result.get("sent") or 0):
                    _log(
                        "Notification reminders checked: "
                        f"checked={result.get('checked')} sent={result.get('sent')} skipped={result.get('skipped')}"
                    )
            except Exception as exc:
                _log(f"WARNING: Notification reminder check failed: {exc}")
            time.sleep(_interval_seconds())

    try:
        thread = threading.Thread(target=_run, name="notification-reminders", daemon=True)
        thread.start()
        return thread
    except Exception as exc:
        _log(f"WARNING: Notification reminder loop could not be started: {exc}")
        return None


def _start_notification_delivery_loop(config: dict) -> threading.Thread | None:
    def _interval_seconds() -> int:
        try:
            from config_api import read_expanded_conf
            conf = read_expanded_conf(config)
            raw = str(conf.get("NOTIFY_APPRISE_DELIVERY_INTERVAL_SECONDS", "30") or "30")
            return max(10, min(3600, int(raw.strip())))
        except Exception:
            return 30

    def _run() -> None:
        time.sleep(5)
        while True:
            try:
                from lib.notification_events import drain_notification_queue

                result = drain_notification_queue(config)
                if int(result.get("checked") or 0) or int(result.get("remaining") or 0):
                    _log(
                        "Apprise notification queue checked: "
                        f"checked={result.get('checked')} delivered={result.get('delivered')} "
                        f"retrying={result.get('retrying')} failed={result.get('failed')} "
                        f"remaining={result.get('remaining')}"
                    )
            except Exception as exc:
                _log(f"WARNING: Apprise notification queue check failed: {_mask_secrets(str(exc))}")
            time.sleep(_interval_seconds())

    try:
        thread = threading.Thread(target=_run, name="apprise-notification-delivery", daemon=True)
        thread.start()
        return thread
    except Exception as exc:
        _log(f"WARNING: Apprise notification delivery loop could not be started: {_mask_secrets(str(exc))}")
        return None


def _start_repository_info_refresh_loop(config: dict) -> threading.Thread | None:
    """Refresh cached Borg repository information without blocking UI requests."""
    try:
        from repositories_api import run_repository_info_refresh_scheduler

        def _run() -> None:
            run_repository_info_refresh_scheduler(
                config,
                log_fn=lambda message: _log(_mask_secrets(str(message))),
                startup_delay_seconds=300,
            )

        thread = threading.Thread(target=_run, name="repository-info-refresh", daemon=True)
        thread.start()
        return thread
    except Exception as exc:
        _log(f"WARNING: Repository information refresh loop could not be started: {_mask_secrets(str(exc))}")
        return None


def _start_apprise_runtime_warmup(config: dict) -> threading.Thread | None:
    """Warm the bundled Apprise runtime so the first profile API call is not cold."""

    def _run() -> None:
        time.sleep(10)
        started = perf_counter()
        try:
            from apprise_profiles_api import get_supported_providers

            info = get_supported_providers(config)
            elapsed_ms = int((perf_counter() - started) * 1000)
            if info.get("success") is False:
                _log(
                    "WARNING: Apprise runtime warmup failed: "
                    f"{_mask_secrets(str(info.get('message') or 'unknown error'))}"
                )
                return
            _log(
                "Apprise runtime warmed: "
                f"version={_mask_secrets(str(info.get('version') or 'unknown'))}, "
                f"providers={int(info.get('provider_count') or 0)}, duration_ms={elapsed_ms}"
            )
        except Exception as exc:
            _log(f"WARNING: Apprise runtime warmup failed: {_mask_secrets(str(exc))}")

    try:
        thread = threading.Thread(target=_run, name="apprise-runtime-warmup", daemon=True)
        thread.start()
        return thread
    except Exception as exc:
        _log(f"WARNING: Apprise runtime warmup could not be started: {_mask_secrets(str(exc))}")
        return None


def _apply_runtime_dirs_from_conf(config: dict) -> None:
    """Synchronisiert runtime-pfade aus backup.conf in die laufende UI-Konfiguration."""
    try:
        from config_api import read_expanded_conf
        conf = read_expanded_conf(config)
        global_data_dir = str(conf.get("GLOBAL_DATA_DIR", "")).strip()
        status_dir = str(conf.get("STATUS_DIR", "")).strip()
        restore_test_status_dir = str(conf.get("RESTORE_TEST_STATUS_DIR", "")).strip()
        global_log_dir = str(conf.get("GLOBAL_LOG_DIR", "")).strip()
        global_cache_dir = str(conf.get("GLOBAL_BORG_CACHE_BASE", "")).strip()
        if global_data_dir:
            config["GLOBAL_DATA_DIR"] = global_data_dir
        if status_dir:
            config["STATUS_DIR"] = status_dir
        if restore_test_status_dir:
            config["RESTORE_TEST_STATUS_DIR"] = restore_test_status_dir
        if global_log_dir:
            config["GLOBAL_LOG_DIR"] = global_log_dir
        if global_cache_dir:
            config["GLOBAL_BORG_CACHE_BASE"] = global_cache_dir
    except Exception:
        pass


def _evaluate_startup_migrations(config: dict, migration_runner=None) -> tuple[bool, dict]:
    """Run required startup migrations and select normal or restricted mode."""
    _set_startup_state(config, _normal_startup_state())
    try:
        if migration_runner is None:
            from migrations.registry import run_startup_migrations
            migration_runner = run_startup_migrations
        summary = migration_runner(config)
    except Exception as exc:
        state = _set_startup_state(config, _migration_maintenance_state(runner_error=exc))
        _log(
            "ERROR: Startup migration runner failed. Normal operation is blocked: "
            f"{_mask_secrets(str(exc))}"
        )
        return False, {"status": "failed", "failed": state.get("failed_migrations", [])}

    if not isinstance(summary, dict):
        error = RuntimeError("Startup migration runner returned an invalid result")
        state = _set_startup_state(config, _migration_maintenance_state(runner_error=error))
        _log("ERROR: Startup migration runner returned an invalid result. Normal operation is blocked.")
        return False, {"status": "failed", "failed": state.get("failed_migrations", [])}

    status = str(summary.get("status") or "").strip().lower()
    failed = [str(item) for item in summary.get("failed", []) if str(item).strip()]
    results = summary.get("results") if isinstance(summary.get("results"), dict) else {}
    for migration_id, result in results.items():
        if isinstance(result, dict) and str(result.get("status") or "").strip().lower() == "failed":
            migration_id_text = str(migration_id).strip()
            if migration_id_text and migration_id_text not in failed:
                failed.append(migration_id_text)
    if status != "ok" or failed:
        summary["status"] = "failed"
        summary["failed"] = failed
        state = _set_startup_state(config, _migration_maintenance_state(summary))
        _log(
            "ERROR: Required startup migration failed. Normal operation is blocked: "
            f"{', '.join(state.get('failed_migrations', [])) or 'unknown migration'}"
        )
        return False, summary

    _set_startup_state(config, _normal_startup_state(summary))
    _log(
        "Startup migrations: "
        f"status={summary.get('status')}, applied={summary.get('applied')}, "
        f"skipped={summary.get('skipped')}, failed={summary.get('failed')}"
    )
    return True, summary


def _remove_obsolete_persistent_backup_conf_schema(config: dict) -> bool:
    """Remove an installer-created schema copy after canonicalization succeeded."""
    legacy_schema = Path(config["BACKUP_SCRIPTS_DIR"]) / "config" / "backup.conf.example"
    if not legacy_schema.is_file():
        return False
    try:
        from config_api import canonical_backup_conf_plan

        plan = canonical_backup_conf_plan(config)
        if plan["changed"]:
            _log(
                "WARNING: Obsolete persistent backup.conf.example retained because "
                "backup.conf is not canonical."
            )
            return False
        legacy_schema.unlink()
        _log("Removed obsolete persistent backup.conf.example copy.")
        return True
    except Exception as exc:
        _log(
            "WARNING: Obsolete persistent backup.conf.example could not be removed: "
            f"{_mask_secrets(str(exc))}"
        )
        return False


def _start_normal_runtime_services(config: dict) -> None:
    """Start services which must remain disabled in migration maintenance mode."""
    try:
        from repositories_api import reconcile_repository_usage
        repository_usage = reconcile_repository_usage(config)
        changed = repository_usage.get("reconciled_repository_keys", [])
        _log(
            "Repository assignments: "
            f"status={'ok' if repository_usage.get('ok') else 'attention'}, reconciled={len(changed)}, "
            f"errors={len(repository_usage.get('errors', []))}"
        )
    except Exception as exc:
        _log(f"WARNING: Repository assignments could not be reconciled: {_mask_secrets(str(exc))}")

    try:
        from schedule_api import apply_all_schedules, prune_orphaned_schedules
        pruned = prune_orphaned_schedules(config, log_fn=_log)
        if pruned.get("changed"):
            _log(f"AUTO-PRUNE schedules.json completed: removed={len(pruned.get('removed_keys', []))}")
        apply_all_schedules(config)
        _log("Cron schedules applied.")
    except Exception as exc:
        _log(f"WARNING: Cron schedules could not be applied: {_mask_secrets(str(exc))}")

    try:
        from smb_profiles_api import mount_startup_smb_profiles
        smb_mounts = mount_startup_smb_profiles(config)
        requested = len(smb_mounts.get("requested", []))
        if requested:
            _log(
                "Startup SMB mounts: "
                f"requested={requested}, mounted={len(smb_mounts.get('mounted', []))}, "
                f"already_mounted={len(smb_mounts.get('already_mounted', []))}, "
                f"failed={len(smb_mounts.get('failed', []))}"
            )
    except Exception as exc:
        _log(f"WARNING: Startup SMB mounts could not be processed: {_mask_secrets(str(exc))}")

    _start_notification_reminder_loop(config)
    _start_notification_delivery_loop(config)
    _start_repository_info_refresh_loop(config)
    _start_apprise_runtime_warmup(config)


def _activate_runtime_services(config: dict, startup_ready: bool, starter=None) -> bool:
    if not startup_ready:
        _log(
            "Migration maintenance mode active: repository reconciliation, schedules, "
            "reminders and repository refresh are disabled."
        )
        return False
    (starter or _start_normal_runtime_services)(config)
    return True


def _start_configured_runtime_writers(
    config: dict,
    startup_ready: bool,
    *,
    app_version: str = APP_VERSION,
    widget_startup_writer=None,
    runtime_activator=None,
) -> bool:
    if not _runtime_data_directory_configured(config):
        _log(
            "Initial setup pending: GLOBAL_DATA_DIR is not configured yet; "
            "runtime write services are disabled until the setup wizard completes."
        )
        return False

    if widget_startup_writer is None:
        from unraid_dashboard_widget import write_unraid_dashboard_widget_startup_cache

        widget_startup_writer = write_unraid_dashboard_widget_startup_cache
    if runtime_activator is None:
        runtime_activator = _activate_runtime_services

    try:
        widget_startup_writer(config, app_version=app_version)
    except Exception as exc:
        _log(f"WARNING: Unraid dashboard widget startup cache could not be written: {_mask_secrets(str(exc))}")

    _log("Unraid dashboard widget cache updates are event-based; periodic status scans are disabled.")
    runtime_activator(config, startup_ready)
    return True


def _public_startup_state(config: dict) -> dict:
    state = _get_startup_state(config)
    return {
        "mode": str(state.get("mode") or "normal"),
        "severity": str(state.get("severity") or "ok"),
        "blocking": bool(state.get("blocking")),
        "reason_code": str(state.get("reason_code") or ""),
        "message": str(state.get("message") or ""),
        "failed_migrations": [
            str(item) for item in state.get("failed_migrations", []) if str(item).strip()
        ],
        "failures": [
            {
                "migration_id": str(item.get("migration_id") or ""),
                "phase": str(item.get("phase") or ""),
                "error_type": str(item.get("error_type") or ""),
                "error": str(item.get("error") or ""),
            }
            for item in state.get("failures", [])
            if isinstance(item, dict)
        ],
        "checked_at": str(state.get("checked_at") or ""),
        "recommendation_codes": [
            str(item) for item in state.get("recommendation_codes", []) if str(item).strip()
        ],
    }


def main():
    dev_mode = "--dev" in sys.argv

    setup_borg_path()

    api_dir = SCRIPT_DIR / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))

    config = load_ui_config()
    _log(f"Borg Backup UI version: {APP_VERSION}")
    if dev_mode:
        config["DEV_MODE"] = "true"

    lib_found = setup_lib_path(config)
    if not lib_found:
        _log("WARNING: plugin runtime/lib was not found.")

    try:
        bootstrap_data_layout(config)
    except Exception as exc:
        _log(f"WARNING: Bootstrap skipped: {exc}")

    _apply_runtime_dirs_from_conf(config)
    if not _wait_for_configured_data_storage(config, include_runtime_paths=False):
        return

    startup_ready, _startup_mig = _evaluate_startup_migrations(config)
    if startup_ready:
        _remove_obsolete_persistent_backup_conf_schema(config)

    _apply_runtime_dirs_from_conf(config)
    if not _wait_for_configured_data_storage(config):
        return

    if config.get("DEV_MODE", "false").lower() == "true":
        test_data = Path(config["BACKUP_SCRIPTS_DIR"]) / "test-data"
        if test_data.exists():
            config["STATUS_DIR"] = str(test_data / "backup-status")
            config["SNAPSHOT_FILE"] = str(test_data / "weekly-snapshots.json")
            _log(f"DEV_MODE: STATUS_DIR    = {config['STATUS_DIR']}")
            _log(f"DEV_MODE: SNAPSHOT_FILE = {config['SNAPSHOT_FILE']}")

    BackupUIHandler.config = config

    _start_configured_runtime_writers(config, startup_ready)

    port = int(config["PORT"])
    bind = config["BIND"]
    server = ThreadedHTTPServer((bind, port), BackupUIHandler)
    _log(f"Borg Backup UI started: http://{bind}:{port}")
    _log(f"BACKUP_SCRIPTS_DIR = {config['BACKUP_SCRIPTS_DIR']}")
    _log(f"BORG_SCRIPTS_DIR   = {config.get('BORG_SCRIPTS_DIR', '(not set)')}")
    _log(f"STATUS_DIR         = {config['STATUS_DIR']}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("Server gestoppt.")
        server.server_close()


if __name__ == "__main__":
    main()
