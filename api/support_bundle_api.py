"""
api/support_bundle_api.py - anonymisiertes Support-/Diagnosepaket.
"""
from __future__ import annotations

import base64
import json
import re
import socket
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List


SECRET_KEY_RE = re.compile(r"(exclude|exclusion|rules|patterns|password|passphrase|secret|token|auth|private[_-]?key|ssh[_-]?key|borg[_-]?key|keyfile|borg_passcommand)", re.IGNORECASE)
SECRET_LINE_RE = re.compile(r"(?i)(password|passphrase|token|secret|ssh[_-]?key|borg[_-]?key|keyfile|borg_passcommand)\s*=\s*([^\s]+)")
SECRET_WORD_RE = re.compile(r"(?i)\b(password|passphrase|token|secret)\s+([^\s\"'<>]+)")
# Keep legacy native ntfy keys in the sanitizer so old support snippets remain safe.
PRIVACY_KEY_RE = re.compile(
    r"(?i)(mail|email|recipient|sender|smtp_(host|user)|ntfy_(server_url|username|click_url)|storagebox_(host|user)|"
    r"\bhost\b|\buser(name)?\b|\burl\b)"
)
PRIVACY_LINE_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:MAIL|EMAIL|RECIPIENT|SENDER|SMTP_HOST|SMTP_USER|NTFY_SERVER_URL|"
    r"NTFY_USERNAME|NTFY_CLICK_URL|STORAGEBOX_HOST|STORAGEBOX_USER|HOST|USERNAME|USER|URL)[A-Z0-9_]*)\s*=\s*([^\n\r]+)"
)
SSH_URI_RE = re.compile(r"ssh://[^\s\"'<>]+", re.IGNORECASE)
HTTP_URI_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b")
SSH_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)


def _root_from_config(config: dict) -> Path:
    base = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    return base.parent if base.name == "scripts" else base


def _sanitize_scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = SSH_PRIVATE_KEY_RE.sub("[MASKED_PRIVATE_KEY]", value)
    text = SSH_URI_RE.sub("ssh://[MASKED_SSH_REMOTE]", text)
    text = HTTP_URI_RE.sub(lambda m: "https://[MASKED_URL]" if m.group(0).lower().startswith("https://") else "http://[MASKED_URL]", text)
    text = EMAIL_RE.sub("[MASKED_EMAIL]", text)
    text = SECRET_LINE_RE.sub(lambda m: f"{m.group(1)}=[MASKED]", text)
    text = SECRET_WORD_RE.sub(lambda m: f"{m.group(1)} [MASKED]", text)
    text = PRIVACY_LINE_RE.sub(lambda m: f"{m.group(1)}=[MASKED]", text)
    return text


def sanitize_data(value: Any) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, raw in value.items():
            key_s = str(key)
            if SECRET_KEY_RE.search(key_s):
                out[key_s] = "[MASKED]"
            elif PRIVACY_KEY_RE.search(key_s):
                out[key_s] = "[MASKED]"
            else:
                out[key_s] = sanitize_data(raw)
        return out
    if isinstance(value, list):
        return [sanitize_data(v) for v in value]
    return _sanitize_scalar(value)


def sanitize_text(text: str) -> str:
    return str(_sanitize_scalar(text))


def _read_text_tail(path: Path, max_bytes: int = 65536) -> str:
    with path.open('rb') as handle:
        size = handle.seek(0, 2)
        handle.seek(max(0, size - max_bytes))
        data = handle.read(max_bytes)
    prefix = f"[truncated to last {max_bytes} bytes]\n" if size > max_bytes else ""
    return prefix + data.decode("utf-8", errors="replace")


def _add_json(zf: zipfile.ZipFile, name: str, payload: Any) -> None:
    zf.writestr(name, json.dumps(sanitize_data(payload), ensure_ascii=False, indent=2) + "\n")


def _add_text_file(zf: zipfile.ZipFile, arcname: str, path: Path, *, max_bytes: int = 65536) -> bool:
    if not path.is_file():
        return False
    try:
        zf.writestr(arcname, sanitize_text(_read_text_tail(path, max_bytes=max_bytes)))
        return True
    except OSError:
        return False


def _add_jsonl_file(zf: zipfile.ZipFile, arcname: str, path: Path, *, max_bytes: int = 262144) -> bool:
    if not path.is_file():
        return False
    try:
        rows = []
        for line in _read_text_tail(path, max_bytes=max_bytes).splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                rows.append(sanitize_text(line))
                continue
            rows.append(json.dumps(sanitize_data(payload), ensure_ascii=False))
        zf.writestr(arcname, "\n".join(rows) + ("\n" if rows else ""))
        return True
    except OSError:
        return False
def _safe_json_file(path: Path) -> Any:
    try:
        if path.is_symlink() or path.stat().st_size > 1024 * 1024:
            return {"_omitted": "not_regular_or_too_large"}
        from job_store import read_json
        return read_json(path)
    except Exception:
        return {"_unreadable": True, "path": str(path)}


def _candidate_jobs_dirs(root: Path, scripts_dir: Path) -> List[Path]:
    candidates = [
        root / "config" / "jobs",
        scripts_dir / "config" / "jobs",
        scripts_dir / "jobs",
    ]
    out: List[Path] = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _status_files(status_dir: Path) -> List[Path]:
    allowed = {".json", ".status", ".state", ".pid", ".txt", ".log", ".test"}
    return sorted(
        [p for p in status_dir.iterdir() if p.is_file() and p.suffix.lower() in allowed],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )[:75]


def _plugin_log_candidates(expanded: dict) -> List[Path]:
    candidates: List[Path] = []
    for key in ("PLUGIN_LOG_FILE", "BORG_BACKUP_UI_LOG", "LOG_FILE"):
        raw = str(expanded.get(key, "")).strip()
        if raw:
            candidates.append(Path(raw))
    candidates.extend([
        Path("/var/log/borg_backup_ui.log"),
        Path("/var/log/borg_backup_ui_client.log"),
    ])
    out: List[Path] = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _arc_safe_path(prefix: str, path: Path) -> str:
    safe = str(path).strip("/").replace("/", "__") or path.name
    return f"{prefix}/{safe}"


def _maintenance_support_bundle(config, app_version):
    # No runtime readers, locks, cache refresh, or recovery blobs in diagnostics.
    from startup_state import get_startup_state
    from identity_migration_api import get_assistant
    assistant = get_assistant(config).status()
    migration = {key: assistant[key] for key in ("migration_id", "status", "stage", "reason_codes", "busy", "restart_required") if key in assistant}
    files = ["system/startup-state.json", "system/identity-migration.json", "manifest.json"]
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _add_json(archive, files[0], get_startup_state(config))
        _add_json(archive, files[1], migration)
        _add_json(archive, files[2], {"plugin_version": app_version, "maintenance": True,
                  "note": "Read-only startup diagnostics. Protected migration data and credentials are excluded."})
    payload = buf.getvalue()
    return {"filename": "borg-backup-ui-migration-support.zip", "payload_b64": base64.b64encode(payload).decode("ascii"),
            "size": len(payload), "file_count": len(files), "files": files}


def create_support_bundle(config: dict, *, app_version: str = "") -> dict:
    from startup_state import is_maintenance_mode
    if is_maintenance_mode(config):
        return _maintenance_support_bundle(config, app_version)
    from config_api import get_conf_file, read_expanded_conf
    from system_health_api import get_system_health_data

    created_at = datetime.now().isoformat(timespec="seconds")
    root = _root_from_config(config)
    scripts_dir = Path(str(config.get("BACKUP_SCRIPTS_DIR", root / "scripts")))
    expanded = read_expanded_conf(config)
    health = get_system_health_data(config)

    safe_settings = {key: value for key, value in expanded.items() if key in {
        "GLOBAL_DATA_DIR", "GLOBAL_LOG_DIR", "STATUS_DIR", "RESTORE_TEST_STATUS_DIR",
        "GLOBAL_LOG_LEVEL", "GLOBAL_DEBUG", "GLOBAL_WEEKLY_REPORT_ENABLED", "PORT"}}
    files: List[str] = []
    skipped: List[Dict[str, str]] = []

    def _record_added(name: str) -> None:
        files.append(name)

    def _record_skipped(path: Path, reason: str) -> None:
        skipped.append({"path": str(path), "reason": reason})

    buf = BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        _add_json(zf, "config/expanded-conf.sanitized.json", safe_settings)
        _record_added("config/expanded-conf.sanitized.json")
        for filename in (
            "storages.json",
            "repositories.json",
            "apprise-profiles.json",
            "notification-deliveries.json",
            "migration-state.json",
        ):
            source = root / "config" / filename
            if source.is_file():
                arcname = f"config/{source.stem}.sanitized.json"
                _add_json(zf, arcname, _safe_json_file(source))
                _record_added(arcname)
            else:
                _record_skipped(source, "not_found_or_unreadable")
        migration_log = root / "config" / "migrations.log.jsonl"
        if _add_jsonl_file(zf, "config/migrations.log.sanitized.jsonl", migration_log, max_bytes=262144):
            _record_added("config/migrations.log.sanitized.jsonl")
        else:
            _record_skipped(migration_log, "not_found_or_unreadable")
        factory_reset_log = Path(__file__).resolve().parents[1] / "factory-reset.log.jsonl"
        if factory_reset_log.is_file():
            if _add_jsonl_file(
                zf,
                "config/factory-reset.sanitized.jsonl",
                factory_reset_log,
                max_bytes=65536,
            ):
                _record_added("config/factory-reset.sanitized.jsonl")
            else:
                _record_skipped(factory_reset_log, "unreadable")
        _add_json(zf, "system/health.json", health)
        _record_added("system/health.json")

        _add_json(zf, "config/backup.conf.sanitized.json", safe_settings)
        _record_added("config/backup.conf.sanitized.json")
        from identity_lifecycle import identity_health
        _add_json(zf, "system/identity-integrity.json", identity_health(config))
        _record_added("system/identity-integrity.json")

        for jobs_dir in _candidate_jobs_dirs(root, scripts_dir):
            if not jobs_dir.is_dir():
                _record_skipped(jobs_dir, "jobs_dir_not_found")
                continue
            for p in sorted(jobs_dir.glob("*.json"))[:250]:
                rel = f"jobs/{p.stem}.json"
                raw = _safe_json_file(p)
                descriptor = {key: raw[key] for key in ('schema_version', 'job_id', 'name', 'repository_key', 'enabled') if key in raw}
                if isinstance(descriptor.get('name'), str): descriptor['name'] = descriptor['name'][:160]
                descriptor['source_count'] = len(raw.get('source_paths', [])) if isinstance(raw.get('source_paths'), list) else 0
                descriptor['exclusion_count'] = len(raw.get('exclude_paths', [])) if isinstance(raw.get('exclude_paths'), list) else 0
                _add_json(zf, rel, descriptor)
                _record_added(rel)

        status_dirs = []
        for key in ("STATUS_DIR", "RESTORE_TEST_STATUS_DIR"):
            raw = str(expanded.get(key, "")).strip()
            if raw:
                status_dirs.append(Path(raw))
        for status_dir in status_dirs:
            if not status_dir.is_dir():
                _record_skipped(status_dir, "status_dir_not_found")
                continue
            for p in _status_files(status_dir):
                rel = f"status/{status_dir.name}/{p.name}"
                if p.suffix.lower() == ".json":
                    _add_json(zf, rel, _safe_json_file(p))
                    _record_added(rel)
                elif _add_text_file(zf, rel, p, max_bytes=65536):
                    _record_added(rel)
                else:
                    _record_skipped(p, "status_file_unreadable")

        log_dir = Path(str(expanded.get("GLOBAL_LOG_DIR", "")).strip()) if str(expanded.get("GLOBAL_LOG_DIR", "")).strip() else Path("")
        if log_dir.is_dir():
            logs = sorted(
                [p for p in log_dir.iterdir() if p.is_file() and p.suffix.lower() in {".log", ".txt"}],
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )[:10]
            for p in logs:
                rel = f"logs/{p.name}"
                if _add_text_file(zf, rel, p, max_bytes=65536):
                    _record_added(rel)
                else:
                    _record_skipped(p, "log_file_unreadable")
        elif str(log_dir):
            _record_skipped(log_dir, "log_dir_not_found")

        for p in _plugin_log_candidates(expanded):
            rel = _arc_safe_path("logs/plugin", p)
            if _add_text_file(zf, rel, p, max_bytes=262144):
                _record_added(rel)
            else:
                _record_skipped(p, "plugin_log_not_found_or_unreadable")

        manifest = {
            "created_at": created_at,
            "plugin_version": app_version,
            "hostname": socket.gethostname(),
            "root": str(root),
            "scripts_dir": str(scripts_dir),
            "included_count": len(files),
            "skipped_count": len(skipped),
            "note": "Secrets are excluded or masked. Do not treat this as a full backup.",
        }
        _add_json(zf, "manifest.json", manifest)
        _record_added("manifest.json")
        _add_json(zf, "support/sanitizing-report.json", {
            "included_files": files,
            "skipped": skipped,
            "masking": {
                "secret_key_patterns": ["password", "passphrase", "secret", "token", "auth", "private_key", "borg_passcommand"],
                "uri_patterns": ["ssh://..."],
                "secret_files_exported": False,
            },
        })
        _record_added("support/sanitizing-report.json")

    payload = buf.getvalue()
    filename = f"borg-backup-ui-support-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return {
        "filename": filename,
        "payload_b64": base64.b64encode(payload).decode("ascii"),
        "size": len(payload),
        "file_count": len(files),
        "files": files,
    }
