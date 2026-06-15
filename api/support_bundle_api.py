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


SECRET_KEY_RE = re.compile(r"(password|passphrase|secret|token|auth|private[_-]?key|borg_passcommand)", re.IGNORECASE)
SECRET_LINE_RE = re.compile(r"(?i)(password|passphrase|token|secret|borg_passcommand)\s*=\s*([^\s]+)")
SSH_URI_RE = re.compile(r"ssh://[^\s\"'<>]+", re.IGNORECASE)
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
    text = SECRET_LINE_RE.sub(lambda m: f"{m.group(1)}=[MASKED]", text)
    return text


def sanitize_data(value: Any) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, raw in value.items():
            key_s = str(key)
            if SECRET_KEY_RE.search(key_s):
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
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
        prefix = f"[truncated to last {max_bytes} bytes]\n"
    else:
        prefix = ""
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


def _safe_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
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
    allowed = {".json", ".status", ".state", ".pid", ".txt", ".log"}
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


def create_support_bundle(config: dict, *, app_version: str = "") -> dict:
    from config_api import get_conf_file, read_expanded_conf, read_settings_payload
    from system_health_api import get_system_health_data

    created_at = datetime.now().isoformat(timespec="seconds")
    root = _root_from_config(config)
    scripts_dir = Path(str(config.get("BACKUP_SCRIPTS_DIR", root / "scripts")))
    expanded = read_expanded_conf(config)
    settings_payload = read_settings_payload(config)
    health = get_system_health_data(config)

    files: List[str] = []
    skipped: List[Dict[str, str]] = []

    def _record_added(name: str) -> None:
        files.append(name)

    def _record_skipped(path: Path, reason: str) -> None:
        skipped.append({"path": str(path), "reason": reason})

    buf = BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        _add_json(zf, "config/expanded-conf.sanitized.json", expanded)
        _record_added("config/expanded-conf.sanitized.json")
        _add_json(zf, "config/settings.sanitized.json", settings_payload)
        _record_added("config/settings.sanitized.json")
        _add_json(zf, "system/health.json", health)
        _record_added("system/health.json")

        conf_file = get_conf_file(config)
        if _add_text_file(zf, "config/backup.conf.sanitized.txt", conf_file, max_bytes=196608):
            _record_added("config/backup.conf.sanitized.txt")
        else:
            _record_skipped(conf_file, "not_found_or_unreadable")

        for jobs_dir in _candidate_jobs_dirs(root, scripts_dir):
            if not jobs_dir.is_dir():
                _record_skipped(jobs_dir, "jobs_dir_not_found")
                continue
            for p in sorted(jobs_dir.glob("*.json"))[:250]:
                rel = f"jobs/{p.stem}.json"
                _add_json(zf, rel, _safe_json_file(p))
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
