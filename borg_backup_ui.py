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
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from time import perf_counter
from urllib.parse import parse_qs, urlparse

from api.auth_store import (
    default_users_store as _default_users_store,
    has_active_admin as _has_active_admin,
    has_any_users as _has_any_users,
    hash_password as _hash_password,
    load_or_create_api_token as _load_or_create_api_token,
    load_ui_auth_config as _load_ui_auth_config,
    normalize_username as _normalize_username,
    parse_cookie_header as _parse_cookie_header,
    read_sessions_store as _read_sessions_store,
    read_users_store as _read_users_store,
    safe_user_view as _safe_user_view,
    verify_password_hash as _verify_password_hash,
    write_sessions_store as _write_sessions_store,
    write_users_store as _write_users_store,
)
from api.security_utils import mask_secrets as _mask_secrets

class RateLimitExceeded(Exception):
    pass


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


APP_VERSION = "2026.07.02.1117"
APP_AUTHOR  = "Thorsten Steinberg"

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
BORG_BUNDLE_VERSIONED = BORG_BUNDLE_DIR / "borg-linux-glibc231-x86_64-1.4.4"
BORG_STAGE_BIN = Path("/usr/local/bin/borg")

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _migration_state_file(config: dict) -> Path:
    data_root = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    return data_root / "config" / "migration-state.json"


def _migration_log_file(config: dict) -> Path:
    data_root = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    return data_root / "config" / "migrations.log.jsonl"


def _read_migration_state(config: dict) -> dict:
    state_file = _migration_state_file(config)
    if not state_file.exists():
        return {}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _migration_state_is_final(state: str) -> bool:
    return state in {"applied", "baseline_detected", "imported_from_legacy_marker", "not_applicable", "not_required", "skipped"}


def _storage_paths_state(details: dict) -> str:
    storage = details.get("storage_paths") if isinstance(details.get("storage_paths"), dict) else {}
    status = str(storage.get("status", "") or "").strip().lower()
    if status == "error" or int(storage.get("move_errors") or 0) > 0:
        return "failed"
    if bool(storage.get("changed")) or int(storage.get("moved") or 0) > 0 or bool(storage.get("settings_changed")) or bool(storage.get("forced_conf_write")):
        return "applied"
    return "baseline_detected"


def _restore_history_state(details: dict) -> str:
    restore_history = details.get("restore_history") if isinstance(details.get("restore_history"), dict) else {}
    status = str(restore_history.get("status", "") or "").strip().lower()
    imported = int(restore_history.get("imported") or 0)
    errors = int(restore_history.get("errors") or 0)
    if status == "failed" or errors > 0:
        return "failed"
    if status == "applied" or imported > 0:
        return "applied"
    if status in {"not_required", "skipped"}:
        return status
    if status == "not_applicable":
        return "not_applicable"
    return "not_applicable"


def _migration_log_is_effective(success: bool, reason_code: str, details: dict) -> bool:
    if not success:
        return True
    if str(reason_code or "").strip() != "no_changes":
        return True
    storage = details.get("storage_paths") if isinstance(details.get("storage_paths"), dict) else {}
    restore_history = details.get("restore_history") if isinstance(details.get("restore_history"), dict) else {}
    startup = details.get("startup_migrations") if isinstance(details.get("startup_migrations"), dict) else {}
    startup_applied = startup.get("applied") if isinstance(startup.get("applied"), list) else []
    startup_failed = startup.get("failed") if isinstance(startup.get("failed"), list) else []
    return bool(
        storage.get("changed")
        or storage.get("moved")
        or storage.get("move_errors")
        or storage.get("settings_changed")
        or storage.get("forced_conf_write")
        or restore_history.get("imported")
        or restore_history.get("errors")
        or startup_applied
        or startup_failed
    )


def _backup_conf_config_state(config: dict) -> dict:
    try:
        from migration_api import analyze_backup_conf_state
        return {"backup_conf_schema": analyze_backup_conf_state(config)}
    except Exception as exc:
        return {
            "backup_conf_schema": {
                "state": "failed",
                "checked": False,
                "error": str(exc),
            },
        }


def _write_migration_state(
    config: dict,
    success: bool,
    message: str,
    *,
    reason_code: str = "",
    reason_text: str = "",
    details: dict | None = None,
) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    run_details = details or {}
    previous = _read_migration_state(config)
    effective_run = _migration_log_is_effective(bool(success), reason_code, run_details)
    previous_migrations = previous.get("migrations") if isinstance(previous.get("migrations"), dict) else {}
    storage_state = _storage_paths_state(run_details)
    restore_history_state = _restore_history_state(run_details)
    previous_storage = previous_migrations.get("storage_paths_v1") if isinstance(previous_migrations.get("storage_paths_v1"), dict) else {}
    if _migration_state_is_final(str(previous_storage.get("state", "") or "")) and storage_state == "baseline_detected":
        storage_state = str(previous_storage.get("state"))
    previous_restore_history = previous_migrations.get("restore_history_v1") if isinstance(previous_migrations.get("restore_history_v1"), dict) else {}
    incoming_restore_history_state = restore_history_state
    if _migration_state_is_final(str(previous_restore_history.get("state", "") or "")) and restore_history_state == "not_applicable":
        restore_history_state = str(previous_restore_history.get("state"))

    jobs_details = run_details.get("jobs_layout") if isinstance(run_details.get("jobs_layout"), dict) else {}
    last_run = {
        "timestamp": ts,
        "success": bool(success),
        "message": str(message or ""),
        "reason_code": str(reason_code or ""),
        "reason_text": str(reason_text or ""),
        "details": run_details,
    }
    if not effective_run and isinstance(previous.get("last_run"), dict):
        last_run = previous["last_run"]

    storage_checked_at = ts
    if not effective_run and _migration_state_is_final(str(previous_storage.get("state", "") or "")):
        storage_checked_at = str(previous_storage.get("checked_at") or ts)
    storage_details = run_details.get("storage_paths", {})
    if not effective_run and _migration_state_is_final(str(previous_storage.get("state", "") or "")) and isinstance(previous_storage.get("details"), dict):
        storage_details = previous_storage["details"]
    restore_history_checked_at = ts
    if (
        not effective_run
        and incoming_restore_history_state == "not_applicable"
        and _migration_state_is_final(str(previous_restore_history.get("state", "") or ""))
    ):
        restore_history_checked_at = str(previous_restore_history.get("checked_at") or ts)
    restore_history_details = run_details.get("restore_history", {})
    if (
        not effective_run
        and incoming_restore_history_state == "not_applicable"
        and _migration_state_is_final(str(previous_restore_history.get("state", "") or ""))
        and isinstance(previous_restore_history.get("details"), dict)
    ):
        restore_history_details = previous_restore_history["details"]

    generic_migrations = dict(previous_migrations)
    startup = run_details.get("startup_migrations") if isinstance(run_details.get("startup_migrations"), dict) else {}
    startup_results = startup.get("results") if isinstance(startup.get("results"), dict) else {}
    for migration_id, result in startup_results.items():
        if migration_id in {"restore_history_v1"}:
            continue
        if not isinstance(result, dict):
            continue
        status = str(result.get("status") or result.get("previous_state") or "not_required")
        if status == "skipped" and str(result.get("previous_state") or "").strip():
            status = str(result.get("previous_state"))
        details = result.get("details") if isinstance(result.get("details"), dict) else {}
        previous_entry = previous_migrations.get(migration_id) if isinstance(previous_migrations.get(migration_id), dict) else {}
        if (
            not effective_run
            and _migration_state_is_final(str(previous_entry.get("state", "") or ""))
            and status in {"not_required", "skipped"}
        ):
            generic_migrations[migration_id] = previous_entry
            continue
        generic_migrations[migration_id] = {
            "state": status,
            "checked_at": ts,
            "source": "startup_check",
            "details": {
                **details,
                "runner": str(result.get("runner") or details.get("runner") or "central_migration_registry"),
                "introduced_in": str(result.get("introduced_in") or details.get("introduced_in") or ""),
            },
        }

    payload: dict = {
        "schema_version": 2,
        "last_run": last_run,
        "migrations": {
            **generic_migrations,
            "storage_paths_v1": {
                "state": storage_state,
                "checked_at": storage_checked_at,
                "source": "startup_check",
                "details": storage_details,
            },
            "restore_history_v1": {
                "state": restore_history_state,
                "checked_at": restore_history_checked_at,
                "source": "startup_check",
                "details": restore_history_details,
            },
        },
        "checks": {
            "jobs_layout": {
                "state": "ok" if str(jobs_details.get("status", "") or "").strip().lower() == "ok" else "failed",
                "checked_at": ts,
                "details": jobs_details,
            },
        },
        "config": _backup_conf_config_state(config),
    }
    target = _migration_state_file(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if effective_run:
        entry = dict(payload)
        entry.update(payload["last_run"])
        entry["event"] = "startup_migration"
        try:
            line = json.dumps(entry, ensure_ascii=False)
            log_file = _migration_log_file(config)
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except (OSError, TypeError, ValueError):
            pass


def load_ui_config() -> dict:
    """Lädt borg_backup_ui.conf (KEY=VALUE), fällt auf Defaults zurück."""
    config = {
        "PORT": "8765",
        "BIND": "0.0.0.0",
        "BACKUP_SCRIPTS_DIR": "/boot/config/borg-backup",
        "BORG_SCRIPTS_DIR": str(SCRIPT_DIR / "runtime" / "scripts"),
        "STATUS_DIR": "/mnt/user/backup-status",
        "DEV_MODE": "false",
        "UI_SESSION_TIMEOUT_MINUTES": "30",
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

    # Schema sync: add missing keys, keep legacy keys in explicit block.
    try:
        from config_api import sync_backup_conf_schema
        sync_result = sync_backup_conf_schema(config)
        if sync_result.get("changed"):
            _log(
                "Applied backup.conf schema sync "
                f"(missing={sync_result.get('missing_added', 0)}, legacy={sync_result.get('legacy_keys', 0)})"
            )
    except Exception as exc:
        _log(f"WARNING: backup.conf schema sync failed: {exc}")


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

    def _security_audit(self, event: str, result: str, *, target: str = "", detail: str = "") -> None:
        req_id = str(getattr(self, "_current_request_id", "") or "")
        session = self._get_current_session_meta() or {}
        actor = _mask_secrets(str(session.get("username", "") or ""))
        role = _mask_secrets(str(session.get("role", "") or ""))
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
        return not _has_any_users(self.config)

    def _ui_auth_enabled(self) -> bool:
        return _has_active_admin(self.config)

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
        if p in {"/api/auth/login", "/api/auth/status", "/api/auth/setup-admin", "/api/version"}:
            return None

        # Read-only endpoints
        if m == "GET" and (
            p.startswith("/api/status")
            or p.startswith("/api/system-health")
            or p.startswith("/api/jobs")
            or p.startswith("/api/schedules")
            or p.startswith("/api/storage")
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
            "/api/restore-tests/run",
            "/api/restore-tests/run-job",
            "/api/storage/test",
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
            or p in {"/api/jobs/enabled", "/api/jobs", "/api/schedules", "/api/restore-tests", "/api/restore-tests/policy"}
        ):
            return "admin"

        # Safe default for unknown API routes
        return "admin"

    # ── Routing ───────────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/setup-admin":
            self._serve_setup_admin_page()
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
            self._serve_file(UI_DIR / "index.html")
        elif path.startswith("/ui/"):
            # Static UI assets must stay directly reachable, otherwise browsers receive
            # HTML redirects for JS/CSS and fail with MIME/syntax errors on /login.
            self._serve_file(UI_DIR / path[4:])
        elif path == "/api/jobs/log/stream":
            qs = parse_qs(parsed.query)
            job_key = (qs.get("job") or [""])[0]
            self._handle_sse(job_key)
        elif path == "/api/restore-tests/log/stream":
            self._handle_sse("restore_test")
        elif path == "/api/restore/download":
            self._handle_restore_download(parsed)
        elif path == "/api/storage/check/stream":
            self._handle_check_sse()
        else:
            routes = {
                "/api/version": lambda: {"version": APP_VERSION, "author": APP_AUTHOR, "borg_version": _get_borg_version()},
                "/api/status": self._get_status,
                "/api/system-health": self._get_system_health,
                "/api/jobs": self._get_jobs,
                "/api/jobs/running": self._get_running,
                "/api/schedules": self._get_schedules,
                "/api/storage": self._get_storage,
                "/api/settings": self._get_settings,
                "/api/settings/basic": self._get_settings_basic,
                "/api/setup-status": self._get_setup_status,
                "/api/settings/backup-history": self._get_settings_backup_history,
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
                "/api/restore/history/migration": self._get_restore_history_migration,
                "/api/reports/jobs": self._get_report_jobs,
                "/api/reports/data": lambda: self._get_report_data(parsed.query),
                "/api/history/log": lambda: self._get_log_file(parsed.query),
                "/api/wizard/passphrase-check": lambda: self._get_wizard_passphrase_check(parsed.query),
                "/api/wizard/job": lambda: self._get_wizard_job(parsed.query),
                "/api/wizard/source-dirs": lambda: self._get_wizard_source_dirs(parsed.query),
                "/api/wizard/runtime-inventory": self._get_wizard_runtime_inventory,
                "/api/storage/check/jobs": self._get_check_jobs,
                "/api/storage/check/state": self._get_check_state,
                "/api/storagebox/deploy/state": lambda: self._get_storagebox_deploy_state(parsed.query),
                "/api/auth/status": self._get_auth_status,
                "/api/auth/users": self._get_auth_users,
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
            "/api/restore-tests/run": self._post_run_restore_test,
            "/api/restore-tests/run-job": self._post_run_restore_test_job,
            "/api/storage/test": self._post_test_repo,
            "/api/storage/smb-action": self._post_storage_smb_action,
            "/api/wizard/preview": self._post_wizard_preview,
            "/api/wizard/save": self._post_wizard_save,
            "/api/settings/test-smtp": self._post_test_smtp,
            "/api/settings/test-ntfy": self._post_test_ntfy,
            "/api/settings/weekly-report/send": self._post_send_weekly_report,
            "/api/settings/backup-restore": self._post_settings_backup_restore,
            "/api/settings/backup-delete": self._post_settings_backup_delete,
            "/api/settings/backup-delete-keep-latest": self._post_settings_backup_delete_keep_latest,
            "/api/settings/backup-diff": self._post_settings_backup_diff,
            "/api/settings/jobs-import": self._post_settings_jobs_import,
            "/api/settings/jobs-import-preview": self._post_settings_jobs_import_preview,
            "/api/settings/jobs-export-secure": self._post_settings_jobs_export_secure,
            "/api/settings/jobs-import-secure-preview": self._post_settings_jobs_import_secure_preview,
            "/api/settings/jobs-import-secure": self._post_settings_jobs_import_secure,
            "/api/settings/secrets-backup-export": self._post_settings_secrets_backup_export,
            "/api/settings/secrets-backup-preview": self._post_settings_secrets_backup_preview,
            "/api/settings/secrets-backup-import": self._post_settings_secrets_backup_import,
            "/api/settings/profile-secrets-export": self._post_settings_profile_secrets_export,
            "/api/settings/profile-secrets-preview": self._post_settings_profile_secrets_preview,
            "/api/settings/profile-secrets-import": self._post_settings_profile_secrets_import,
            "/api/settings/support-bundle": self._post_settings_support_bundle,
            "/api/settings/legacy-cleanup-apply": self._post_settings_legacy_cleanup_apply,
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
            "/api/auth/users": self._post_auth_user_create,
            "/api/auth/users/password-reset": self._post_auth_user_password_reset,
            "/api/auth/change-password": self._post_auth_change_password,
            "/api/auth/logout-all-sessions": self._post_auth_logout_all_sessions,
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
            "/api/auth/users": self._delete_auth_user,
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
        self._security_audit("auth_login", "ok", target=session_user)
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
        from jobs_api import JobManager
        return JobManager.get().get_all_states()

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
        from jobs_api import JobManager, discover_jobs, get_jobs_meta_dirs, resolve_data_root, resolve_scripts_dir
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

        if JobManager.get().is_running(job_key):
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
        deleted_metadata = False
        for jobs_meta_dir in jobs_meta_dirs:
            meta_file = jobs_meta_dir / f"{job_key}.json"
            if not meta_file.exists():
                continue
            try:
                meta_file.unlink()
                deleted_metadata = True
            except OSError:
                pass

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

    def _get_settings(self) -> dict:
        from config_api import get_settings_data
        return get_settings_data(self.config)

    def _get_settings_basic(self) -> dict:
        from config_api import get_settings_data
        return get_settings_data(self.config, include_storagebox_setup=False)

    def _get_setup_status(self) -> dict:
        from config_api import get_setup_status
        return get_setup_status(self.config)

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

    def _get_wizard_passphrase_check(self, qs: str) -> dict:
        import re as _re
        from urllib.parse import parse_qs as _pqs
        from wizard_api import check_passphrase_exists
        params = _pqs(qs)
        type_id = (params.get("type_id") or [""])[0].strip()
        location = (params.get("location") or [""])[0].strip().lower()
        if not _re.fullmatch(r"[a-z0-9_]+", type_id):
            raise ValueError("Invalid type_id")
        if location and location not in {"local", "usb", "smb", "storagebox", "custom"}:
            raise ValueError("Invalid location")
        return check_passphrase_exists(type_id, location or None)

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
        from restore_api import list_target_dirs
        params = _pqs(qs)
        prefix = (params.get("prefix") or [""])[0]
        try:
            limit = int((params.get("limit") or ["25"])[0])
        except Exception:
            limit = 25
        return {"dirs": list_target_dirs(prefix=prefix, limit=limit)}

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
        from restore_api import list_archives
        from urllib.parse import parse_qs
        qs = parse_qs(qs_str)
        job_key = (qs.get("job") or [""])[0]
        if not job_key:
            raise ValueError("job parameter is required")
        return {"archives": list_archives(self.config, job_key)}

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
        job_key = body.get("job", "")
        if not job_key:
            raise ValueError("job parameter is required")
        mode = str(body.get("mode", "quick")).strip().lower()
        if mode not in {"quick", "verbose", "verify_data"}:
            raise ValueError("Invalid mode parameter")
        from check_api import CheckManager
        ok, err = CheckManager.get().start(self.config, job_key, mode)
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

        try:
            from restore_api import get_repo_info, _borg_env
            info = get_repo_info(self.config, job_key)
            env = _borg_env(info["passphrase_file"])
        except Exception as exc:
            self.send_error(500, str(exc))
            return

        repo_archive = f"{info['repo']}::{archive}"
        source_path = path.lstrip("/")
        filename = Path(path).name or "archive"

        try:
            check = self._compute_restore_download_check(repo_archive, source_path, env)
        except RuntimeError as exc:
            self.send_error(400, str(exc)[:500])
            return
        entry_type = check["entry_type"]
        action = check["action"]
        if action == "block":
            self.send_error(413, check["message"])
            return
        if action == "confirm" and not confirm_large:
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

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
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
        from restore_api import get_repo_info, _borg_env
        qs = parse_qs(query or "")
        job_key = (qs.get("job") or [""])[0]
        archive = (qs.get("archive") or [""])[0]
        path = unquote((qs.get("path") or [""])[0])
        if not all([job_key, archive, path]):
            raise ValueError("job, archive, and path are required")
        info = get_repo_info(self.config, job_key)
        env = _borg_env(info["passphrase_file"])
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
        validate_params(body, scripts_dir, data_root, allow_existing=(mode in {"edit", "adopt"}))
        return {"flow": generate_flow_preview(body, self.config, scripts_dir)}

    def _post_wizard_save(self) -> dict:
        from wizard_api import validate_params, save_job
        from jobs_api import resolve_scripts_dir, resolve_data_root
        body = self._read_json_body()
        scripts_dir = resolve_scripts_dir(self.config)
        data_root = resolve_data_root(self.config)
        mode = str(body.get("_wizard_mode", "create")).strip().lower()
        validate_params(body, scripts_dir, data_root, allow_existing=(mode in {"edit", "adopt"}))
        return save_job(body, scripts_dir, data_root, self.config)

    def _start_restore_test_from_body(self, body: dict) -> dict:
        self._require_data_dir_ready()
        from jobs_api import JobManager
        from jobs_api import list_jobs
        from config_api import read_expanded_conf
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
        ok, err = JobManager.get().start(
            "restore_test",
            cmd,
            backup_scripts_dir,
        )
        if not ok:
            raise RuntimeError(err)
        return {
            "started": True,
            "scheduled": scheduled,
            "auto_selected": auto_selected,
            "selected_jobs": clean_job_keys,
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
        repo_path = body.get("repo_path", "")
        repo_conf_key = str(body.get("repo_conf_key", "")).strip()
        if not repo_path:
            raise ValueError("repo_path is required")
        return test_repository(repo_path, self.config, repo_conf_key=repo_conf_key)

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

    def _get_restore_history_migration(self) -> dict:
        from restore_api import get_restore_history_migration
        return get_restore_history_migration(self.config)

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
            read_settings_payload,
            write_settings_payload,
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
        from ntfy_api import prepare_ntfy_updates_for_save
        body = self._read_json_body()
        updates = body.get("updates", {})
        smb_cleanup_keys = body.get("smb_cleanup_keys", [])
        smb_secret_cleanup_keys = body.get("smb_secret_cleanup_keys", [])
        if not updates:
            raise ValueError("updates is required")
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
        settings_payload = read_settings_payload(self.config)
        try:
            prev_smb_rows = validate_smb_profiles_json(
                json.dumps(settings_payload.get("smb_profiles", []), ensure_ascii=False)
            )
        except ValueError:
            prev_smb_rows = []
        smb_removed_keys: set[str] = set()
        settings_changed = False
        if "GLOBAL_SMTP_PASSWORD" in updates:
            incoming_pw = str(updates.get("GLOBAL_SMTP_PASSWORD", ""))
            existing_pw = str(prev_conf.get("GLOBAL_SMTP_PASSWORD", ""))
            if not incoming_pw.strip() and existing_pw.strip():
                updates.pop("GLOBAL_SMTP_PASSWORD", None)
        if {"NTFY_PASSWORD", "NTFY_ACCESS_TOKEN"} & set(updates.keys()):
            updates = prepare_ntfy_updates_for_save(updates, prev_conf)
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
        if "SMB_PROFILES_JSON" in updates:
            normalized_preview = validate_smb_profiles_json(str(updates.get("SMB_PROFILES_JSON", "[]")))
            validate_smb_profile_usage_before_save(self.config, normalized_preview)
            prev_keys = {str(r.get("key") or "").strip().lower() for r in prev_smb_rows if str(r.get("key") or "").strip()}
            new_keys = {str(r.get("key") or "").strip().lower() for r in normalized_preview if str(r.get("key") or "").strip()}
            smb_removed_keys = {k for k in prev_keys if k not in new_keys}
            normalized_smb = prepare_smb_profiles_for_save(str(updates.get("SMB_PROFILES_JSON", "[]")))
            settings_payload["smb_profiles"] = normalized_smb
            updates.pop("SMB_PROFILES_JSON", None)
            settings_changed = True
        if "USB_PROFILES_JSON" in updates:
            raw_usb = str(updates.get("USB_PROFILES_JSON", "[]") or "[]")
            try:
                parsed_usb = json.loads(raw_usb)
            except (json.JSONDecodeError, TypeError, ValueError):
                raise ValueError("USB_PROFILES_JSON is not valid JSON.")
            if not isinstance(parsed_usb, list):
                raise ValueError("USB_PROFILES_JSON must be a list.")
            normalized_usb = _normalize_usb_profile_rows(parsed_usb)
            validate_usb_profile_usage_before_save(self.config, normalized_usb)
            settings_payload["usb_profiles"] = normalized_usb
            updates.pop("USB_PROFILES_JSON", None)
            settings_changed = True
        if "STORAGE_PROFILES_JSON" in updates:
            raw_storage = str(updates.get("STORAGE_PROFILES_JSON", "[]") or "[]")
            try:
                parsed_storage = json.loads(raw_storage)
            except (json.JSONDecodeError, TypeError, ValueError):
                raise ValueError("STORAGE_PROFILES_JSON is not valid JSON.")
            if not isinstance(parsed_storage, list):
                raise ValueError("STORAGE_PROFILES_JSON must be a list.")
            normalized_storage = _normalize_storage_profile_rows(parsed_storage)
            validate_storage_profiles_complete_before_save(normalized_storage)
            validate_storage_profile_usage_before_save(self.config, normalized_storage)
            settings_payload["storage_profiles"] = normalized_storage
            updates.pop("STORAGE_PROFILES_JSON", None)
            settings_changed = True
        storage_keys = {"STORAGEBOX_HOST", "STORAGEBOX_PORT", "STORAGEBOX_USER", "STORAGEBOX_BASE_PATH"}
        if storage_keys & set(updates.keys()):
            rows = settings_payload.get("storage_profiles") if isinstance(settings_payload.get("storage_profiles"), list) else []
            normalized_rows = []
            normalized_rows = _normalize_storage_profile_rows(rows)
            active = normalized_rows[0] if normalized_rows else {
                "key": "storage-1",
                "name": "Storagebox",
                "host": "",
                "port": "23",
                "user": "",
                "base_path": "/./backup",
                "target_type": "storagebox",
            }
            if "STORAGEBOX_HOST" in updates:
                active["host"] = str(updates.get("STORAGEBOX_HOST", "")).strip()
            if "STORAGEBOX_PORT" in updates:
                active["port"] = str(updates.get("STORAGEBOX_PORT", "23")).strip() or "23"
            if "STORAGEBOX_USER" in updates:
                active["user"] = str(updates.get("STORAGEBOX_USER", "")).strip()
            if "STORAGEBOX_BASE_PATH" in updates:
                active["base_path"] = str(updates.get("STORAGEBOX_BASE_PATH", "/./backup")).strip() or "/./backup"
            settings_payload["storage_profiles"] = _normalize_storage_profile_rows([active] + [r for r in normalized_rows[1:] if isinstance(r, dict)])
            validate_storage_profiles_complete_before_save(settings_payload["storage_profiles"])
            validate_storage_profile_usage_before_save(self.config, settings_payload["storage_profiles"])
            settings_changed = True
        if settings_changed:
            write_settings_payload(self.config, settings_payload)
        write_conf(self.config, updates, snapshot_reason="Manual change")
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

    def _post_test_ntfy(self) -> dict:
        from config_api import send_test_ntfy
        body = self._read_json_body()
        return send_test_ntfy(self.config, body)

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

    def _post_settings_legacy_cleanup_apply(self) -> dict:
        from migration_api import apply_legacy_cleanup
        body = self._read_json_body()
        mode = str((body or {}).get("mode", "comment_out")).strip()
        confirm = str((body or {}).get("confirm", "")).strip()
        result = apply_legacy_cleanup(self.config, mode=mode, confirm=confirm)
        _apply_runtime_dirs_from_conf(self.config)
        return result

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
        from jobs_api import JobManager, discover_jobs, resolve_data_root, resolve_scripts_dir
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

        info = jobs[job_key]
        plugin_runtime = Path(__file__).resolve().parent / "runtime"
        existing_pp = os.environ.get("PYTHONPATH", "")
        runtime_pp = str(plugin_runtime)
        merged_pp = f"{runtime_pp}:{existing_pp}" if existing_pp else runtime_pp
        if info.standard == "wizard":
            runner = Path(__file__).resolve().parent / "api" / "wizard_runner.py"
            extra_env = {
                "BORG_UI_BORG_SCRIPTS_DIR": str(borg_scripts_dir),
                "BORG_UI_JOB_KEY": job_key,
                "PYTHONPATH": merged_pp,
            }
            ok, err = JobManager.get().start(
                job_key,
                ["python3", str(runner)],
                backup_scripts_dir,
                extra_env=extra_env,
            )
        else:
            if info.script_path is None:
                raise RuntimeError("A legacy job without a script path cannot be executed")
            extra_env = {"PYTHONPATH": merged_pp}
            ok, err = JobManager.get().start(
                job_key,
                ["python3", str(info.script_path)],
                backup_scripts_dir,
                extra_env=extra_env,
            )
        if not ok:
            raise RuntimeError(err)
        return {"started": True, "job_key": job_key}

    # ── SSE-Handler ───────────────────────────────────────────────────────────

    def _handle_sse(self, job_key: str):
        from jobs_api import JobManager
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for chunk in JobManager.get().stream_output(job_key):
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

    def _serve_file(self, filepath: Path):
        filepath = filepath.resolve()
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
<html lang="de"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Borg Backup Login</title>
<script>
(() => {
  const key = 'bbui_theme_preference';
  const pref = localStorage.getItem(key);
  const clean = (pref === 'light' || pref === 'dark' || pref === 'system') ? pref : 'dark';
  const resolved = clean === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : clean;
  document.documentElement.setAttribute('data-theme', resolved);
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
<html lang="de"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Borg Backup Setup</title>
<script>
(() => {
  const key = 'bbui_theme_preference';
  const pref = localStorage.getItem(key);
  const clean = (pref === 'light' || pref === 'dark' || pref === 'system') ? pref : 'dark';
  const resolved = clean === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : clean;
  document.documentElement.setAttribute('data-theme', resolved);
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
<div class="form-group"><label class="form-label" data-i18n="auth.password"></label><input id="setup-password" class="form-input" type="password" autocomplete="new-password"></div>
<div class="form-group"><label class="form-label" data-i18n="auth.passwordConfirm"></label><input id="setup-password-confirm" class="form-input" type="password" autocomplete="new-password"></div>
<div id="setup-msg" class="status-message hidden login-msg"></div>
<button id="setup-btn" class="btn btn-primary" style="width:100%" data-i18n="auth.setupAction"></button>
</div></section></main>
<script>
const btn=document.getElementById('setup-btn');const msg=document.getElementById('setup-msg');
const i18nReady=window.BBUI.components.i18n.init().then(()=>{document.title=window.BBUI.components.i18n.t('auth.setupTitle');});
function authT(key){return window.BBUI.components.i18n.t(key);}
function authApiError(data,fallback){const code=String(data?.code||'').trim();if(code==='bad_request'||code==='forbidden')return authT(fallback);const key=code?`api.errors.${code}`:'';const translated=key?authT(key):'';return translated&&translated!==key?translated:authT(fallback);}
function showErr(t){msg.textContent=t;msg.className='status-message error login-msg';}
async function doSetup(){btn.classList.add('loading');msg.className='status-message hidden login-msg';
try{
 await i18nReady;
 const username=(document.getElementById('setup-username').value||'').trim();
 const password=document.getElementById('setup-password').value||'';
 const password_confirm=document.getElementById('setup-password-confirm').value||'';
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

    def _handle_api(self, fn):
        request_id = uuid.uuid4().hex[:12]
        started = perf_counter()
        try:
            self._current_request_id = request_id
            self._refreshed_session_cookie = ""
            path = urlparse(self.path).path
            auth_free_paths = {"/api/auth/login", "/api/auth/status", "/api/auth/setup-admin"}
            if self.command in {"POST", "PUT", "DELETE"}:
                if not self._has_valid_api_token_header():
                    if not self._is_same_origin_request():
                        self._send_api_error(403, "csrf_origin_mismatch", "Invalid Origin header", request_id=request_id)
                        return
            if path not in auth_free_paths and not self._is_api_authorized():
                self._send_api_error(401, "unauthorized", "The API token is missing or invalid", request_id=request_id)
                return
            required_role = self._required_role_for_request(path, self.command)
            if required_role:
                role = self._get_current_role()
                if not self._role_at_least(role, required_role):
                    self._send_api_error(403, "forbidden", f"Role '{required_role}' is required", request_id=request_id)
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
            self.send_header("Cache-Control", "no-cache")
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
            self._send_api_error(400, "bad_request", str(exc), request_id=request_id)
        except Exception as exc:
            self._send_api_error(500, "internal_error", str(exc), request_id=request_id)
        finally:
            self._current_request_id = ""
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
        ctx = self._extract_request_context()
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

        job_key_raw = (
            body.get("job_key")
            or (qs.get("job_key") or [""])[0]
            or (qs.get("job") or [""])[0]
            or ""
        )
        profile_key_raw = (
            body.get("profile_key")
            or body.get("smb_profile_key")
            or body.get("storage_profile_key")
            or body.get("usb_profile_key")
            or (qs.get("profile_key") or [""])[0]
            or (qs.get("smb_profile_key") or [""])[0]
            or (qs.get("storage_profile_key") or [""])[0]
            or (qs.get("usb_profile_key") or [""])[0]
            or ""
        )
        location_raw = body.get("location") or (qs.get("location") or [""])[0] or ""

        job_key = _mask_secrets(str(job_key_raw))
        profile_key = _mask_secrets(str(profile_key_raw))
        location = _mask_secrets(str(location_raw))
        return {
            "job_key": job_key,
            "profile_key": profile_key,
            "location": location,
        }

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
        return out

    def log_message(self, fmt, *args):
        _log(fmt % args)


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

    def _run() -> None:
        time.sleep(20)
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


def _apply_runtime_dirs_from_conf(config: dict) -> None:
    """Synchronisiert runtime-pfade aus backup.conf in die laufende UI-Konfiguration."""
    try:
        from config_api import read_expanded_conf
        conf = read_expanded_conf(config)
        status_dir = str(conf.get("STATUS_DIR", "")).strip()
        restore_test_status_dir = str(conf.get("RESTORE_TEST_STATUS_DIR", "")).strip()
        global_log_dir = str(conf.get("GLOBAL_LOG_DIR", "")).strip()
        global_cache_dir = str(conf.get("GLOBAL_BORG_CACHE_BASE", "")).strip()
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


def main():
    dev_mode = "--dev" in sys.argv

    setup_borg_path()

    api_dir = SCRIPT_DIR / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))

    config = load_ui_config()
    if dev_mode:
        config["DEV_MODE"] = "true"

    try:
        bootstrap_data_layout(config)
    except Exception as exc:
        _log(f"WARNING: Bootstrap skipped: {exc}")

    migration_ok = True
    migration_messages: list[str] = []
    migration_details: dict = {
        "jobs_layout": {"status": "ok"},
        "storage_paths": {
            "status": "ok",
            "changed": False,
            "moved": 0,
            "move_errors": 0,
            "settings_changed": False,
            "forced_conf_write": False,
        },
        "restore_history": {
            "status": "not_required",
            "imported": 0,
            "active_kept": 0,
            "errors": 0,
        },
        "startup_migrations": {
            "status": "ok",
            "applied": [],
            "skipped": [],
            "failed": [],
            "results": {},
        },
    }
    try:
        from jobs_api import migrate_data_layout
        migrate_data_layout(config)
        migration_messages.append("jobs_layout=ok")
    except Exception as exc:
        migration_ok = False
        migration_messages.append(f"jobs_layout=error:{exc}")
        migration_details["jobs_layout"] = {"status": "error", "error": str(exc)}
        _log(f"WARNING: Job data migration skipped: {exc}")

    try:
        from config_api import migrate_storage_paths_from_global_data_dir
        storage_mig = migrate_storage_paths_from_global_data_dir(config)
        if isinstance(storage_mig, dict):
            changed = bool(storage_mig.get("changed"))
            moved = len(storage_mig.get("migrated_files") or [])
            move_errors = len(storage_mig.get("migration_errors") or [])
            settings_changed = bool(storage_mig.get("settings_changed"))
            forced_conf_write = bool(storage_mig.get("forced_conf_write"))
            migration_details["storage_paths"] = {
                "status": "error" if move_errors else "ok",
                "changed": changed,
                "moved": moved,
                "move_errors": move_errors,
                "settings_changed": settings_changed,
                "forced_conf_write": forced_conf_write,
                "reason": str(storage_mig.get("reason", "") or ""),
            }
            migration_messages.append(
                f"storage_paths=ok(changed={changed},moved={moved},move_errors={move_errors},settings_changed={settings_changed},forced_conf_write={forced_conf_write})"
            )
            _log(
                f"Storage-Pfadmigration: changed={changed}, moved={moved}, move_errors={move_errors}, settings_changed={settings_changed}, forced_conf_write={forced_conf_write}"
            )
        else:
            migration_messages.append("storage_paths=ok")
            _log("Storage-Pfadmigration: ok")
    except Exception as exc:
        migration_ok = False
        migration_messages.append(f"storage_paths=error:{exc}")
        migration_details["storage_paths"] = {"status": "error", "error": str(exc)}
        _log(f"WARNING: Storage path migration skipped: {exc}")
    try:
        from migrations.registry import run_startup_migrations
        startup_mig = run_startup_migrations(config)
        migration_details["startup_migrations"] = startup_mig
        restore_mig = (startup_mig.get("results") or {}).get("restore_history_v1", {}) if isinstance(startup_mig.get("results"), dict) else {}
        restore_details = restore_mig.get("details") if isinstance(restore_mig.get("details"), dict) else {}
        imported = int(restore_details.get("imported") or 0)
        active_kept = int(restore_details.get("active_kept") or 0)
        errors = len(restore_details.get("errors") or [])
        status = str(restore_mig.get("status") or "not_required")
        migration_details["restore_history"] = {
            "status": status,
            "migration_id": str(restore_mig.get("migration_id") or "restore_history_v1"),
            "introduced_in": str(restore_mig.get("introduced_in") or ""),
            "runner": str(restore_mig.get("runner") or restore_details.get("runner") or ""),
            "imported": imported,
            "active_kept": active_kept,
            "errors": errors,
            "already_imported": int(restore_details.get("already_imported") or 0),
            "source_file": str(restore_details.get("source_file") or ""),
        }
        if errors or startup_mig.get("failed"):
            migration_ok = False
        migration_messages.extend([str(msg) for msg in (startup_mig.get("messages") or [])])
        _log(f"Startup-Migrationen: status={startup_mig.get('status')}, applied={startup_mig.get('applied')}, skipped={startup_mig.get('skipped')}, failed={startup_mig.get('failed')}")
    except Exception as exc:
        migration_ok = False
        migration_messages.append(f"restore_history=error:{exc}")
        migration_details["restore_history"] = {"status": "failed", "error": str(exc), "errors": 1}
        migration_details["startup_migrations"] = {"status": "failed", "failed": ["startup_registry"], "error": str(exc)}
        _log(f"WARNING: Startup migrations skipped: {exc}")
    reason_code = "no_changes"
    reason_text = "No changes required"
    storage_info = migration_details.get("storage_paths", {})
    restore_history_info = migration_details.get("restore_history", {})
    startup_info = migration_details.get("startup_migrations", {})
    startup_applied = [
        str(item)
        for item in (startup_info.get("applied") if isinstance(startup_info.get("applied"), list) else [])
        if str(item) != "restore_history_v1"
    ] if isinstance(startup_info, dict) else []
    if not migration_ok:
        reason_code = "error"
        reason_text = "Migration completed with errors"
    elif bool(storage_info.get("changed")):
        reason_code = "storage_paths_changed"
        reason_text = "Cache/Remotes/backup.conf an GLOBAL_DATA_DIR angepasst"
    elif int(restore_history_info.get("imported") or 0) > 0:
        reason_code = "restore_history_migrated"
        reason_text = "Restore-History aus restore-runs.json migriert"
    elif startup_applied:
        reason_code = "startup_migrations_applied"
        reason_text = "Startup-Migrationen angewendet"

    _write_migration_state(
        config,
        migration_ok,
        "; ".join(migration_messages) or "Migration completed",
        reason_code=reason_code,
        reason_text=reason_text,
        details=migration_details,
    )

    lib_found = setup_lib_path(config)
    if not lib_found:
        _log("WARNING: plugin runtime/lib was not found.")

    _apply_runtime_dirs_from_conf(config)

    if config.get("DEV_MODE", "false").lower() == "true":
        test_data = Path(config["BACKUP_SCRIPTS_DIR"]) / "test-data"
        if test_data.exists():
            config["STATUS_DIR"] = str(test_data / "backup-status")
            config["SNAPSHOT_FILE"] = str(test_data / "weekly-snapshots.json")
            _log(f"DEV_MODE: STATUS_DIR    = {config['STATUS_DIR']}")
            _log(f"DEV_MODE: SNAPSHOT_FILE = {config['SNAPSHOT_FILE']}")

    BackupUIHandler.config = config

    try:
        from schedule_api import apply_all_schedules, prune_orphaned_schedules
        pruned = prune_orphaned_schedules(config, log_fn=_log)
        if pruned.get("changed"):
            _log(f"AUTO-PRUNE schedules.json completed: removed={len(pruned.get('removed_keys', []))}")
        apply_all_schedules(config)
        _log("Cron-Schedules angewendet.")
    except Exception as exc:
        _log(f"WARNING: Cron schedules could not be applied: {exc}")

    _start_notification_reminder_loop(config)

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
