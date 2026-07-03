"""
api/jobs_api.py – Job-Verwaltung: Erkennung, Start, State-Tracking

JobManager ist ein Singleton und thread-safe. Backup-Scripts werden als
Subprozesse gestartet; deren stdout wird live gepuffert und per SSE ausgeliefert.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Generator, List, Optional

DEFAULT_DATA_ROOT = Path("/boot/config/borg-backup")
DEFAULT_SECRETS_DIR = DEFAULT_DATA_ROOT / "secrets"
_JOB_KEY_RX = re.compile(r"^[a-zA-Z0-9_.-]+$")
_RUNTIME_MODES = {"all", "selected", "none"}


def _validate_job_key(job_key: str) -> str:
    key = str(job_key or "").strip()
    if not _JOB_KEY_RX.fullmatch(key):
        raise ValueError("Invalid job key")
    return key


def _safe_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


def _split_runtime_selected(raw) -> List[str]:
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, str):
        values = raw.splitlines() if "\n" in raw else raw.split(",")
    else:
        values = []

    selected: List[str] = []
    seen = set()
    for value in values:
        name = str(value or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        selected.append(name)
    return selected


def _runtime_control_from_meta(meta: dict, kind: str) -> dict:
    raw = meta.get(f"{kind}_control") if isinstance(meta.get(f"{kind}_control"), dict) else {}
    features = meta.get("features") if isinstance(meta.get("features"), dict) else {}
    legacy_enabled = bool(features.get(kind, False))
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in _RUNTIME_MODES:
        mode = "all" if legacy_enabled else "none"
    ack_key = "ack_appdata_risk" if kind == "docker" else "ack_domains_risk"
    return {
        "mode": mode,
        "selected": _split_runtime_selected(raw.get("selected", [])) if mode == "selected" else [],
        ack_key: bool(raw.get(ack_key, False)),
    }


def resolve_data_root(config: dict) -> Path:
    base = Path(str(config.get("BACKUP_SCRIPTS_DIR", str(DEFAULT_DATA_ROOT))).strip() or str(DEFAULT_DATA_ROOT))
    # If BACKUP_SCRIPTS_DIR points to scripts/, use parent as data root.
    if base.name == "scripts":
        return base.parent
    return base


def resolve_scripts_dir(config: dict) -> Path:
    """
    Normalize scripts directory across old/new layouts.
    Supports both:
      - /boot/config/borg-backup/scripts
      - /boot/config/borg-backup   (base dir, scripts live in ./scripts)
    """
    scripts_dir = Path(config.get("BORG_SCRIPTS_DIR", config["BACKUP_SCRIPTS_DIR"]))
    nested = scripts_dir / "scripts"
    if scripts_dir.name != "scripts" and nested.is_dir():
        return nested
    if not scripts_dir.is_dir():
        fallback = resolve_data_root(config) / "scripts"
        if fallback.is_dir():
            return fallback
    return scripts_dir


def get_jobs_meta_dir(scripts_dir: Path, data_root: Path | None = None) -> Path:
    """Canonical jobs metadata directory: <data-root>/config/jobs."""
    root = data_root if data_root is not None else (scripts_dir.parent if scripts_dir.name == "scripts" else scripts_dir)
    return root / "config" / "jobs"


def get_jobs_meta_dirs(scripts_dir: Path, data_root: Path | None = None) -> List[Path]:
    """Canonical metadata lookup order for normal operation."""
    return [get_jobs_meta_dir(scripts_dir, data_root)]


def migrate_jobs_metadata_dir(scripts_dir: Path, data_root: Path | None = None) -> None:
    """One-time migration: move legacy jobs/*.json into canonical config/jobs/."""
    preferred = get_jobs_meta_dir(scripts_dir, data_root)
    preferred.mkdir(parents=True, exist_ok=True)
    sources = [
        scripts_dir / "config" / "jobs",
        Path("/boot/config/plugins/borg-backup-ui/runtime/config/jobs"),
    ]
    for legacy in sources:
        if legacy == preferred or not legacy.is_dir():
            continue
        for src in legacy.glob("*.json"):
            dst = preferred / src.name
            if dst.exists():
                continue
            try:
                src.rename(dst)
            except OSError:
                try:
                    shutil.copy2(src, dst)
                    src.unlink()
                except OSError:
                    continue


def migrate_data_layout(config: dict) -> None:
    """
    One-time idempotent migration to canonical data layout:
      - jobs -> /boot/config/borg-backup/config/jobs
      - secrets -> /boot/config/borg-backup/secrets
      - backup.conf passphrase paths -> /boot/config/borg-backup/secrets/.borg-passphrase-*
      - job metadata passphrase defaults -> /boot/config/borg-backup/secrets/.borg-passphrase-*
    """
    data_root = resolve_data_root(config)
    scripts_dir = resolve_scripts_dir(config)
    jobs_dir = data_root / "config" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    migrate_jobs_metadata_dir(scripts_dir, data_root)

    secrets_dir = DEFAULT_SECRETS_DIR
    secrets_dir.mkdir(parents=True, exist_ok=True)

    # Move secrets from old location.
    old_secrets = Path("/boot/config/borg-secrets")
    if old_secrets.is_dir():
        for src in old_secrets.glob(".borg-passphrase-*"):
            if not src.is_file():
                continue
            dst = secrets_dir / src.name
            if dst.exists():
                continue
            try:
                src.rename(dst)
            except OSError:
                pass

    # Normalize metadata passphrase default path.
    for meta in jobs_dir.glob("*.json"):
        try:
            raw = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            continue
        changed = False
        pass_cfg = raw.get("passphrase")
        if isinstance(pass_cfg, dict):
            default = str(pass_cfg.get("default") or "").strip()
            m = re.search(r"\.borg-passphrase-[A-Za-z0-9_]+$", default)
            if m:
                desired = str(secrets_dir / m.group(0))
                if default != desired:
                    pass_cfg["default"] = desired
                    changed = True
        if changed:
            try:
                meta.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            except OSError:
                pass

    # Update backup.conf passphrase values.
    conf_file = data_root / "config" / "backup.conf"
    if conf_file.exists():
        try:
            lines = conf_file.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            lines = []
        out: list[str] = []
        changed = False
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                out.append(line)
                continue
            key, _, val = s.partition("=")
            key = key.strip()
            if not key.startswith("BORG_PASSPHRASE_FILE_"):
                out.append(line)
                continue
            raw_val = val.strip().strip('"').strip("'")
            name = Path(raw_val).name
            if not name.startswith(".borg-passphrase-"):
                out.append(line)
                continue
            new_val = str(secrets_dir / name)
            q = '"' if (' ' in new_val or '/' in new_val or ':' in new_val) else ""
            newline = f"{key}={q}{new_val}{q}\n"
            if line != newline:
                changed = True
            out.append(newline)
        if changed:
            try:
                conf_file.write_text("".join(out), encoding="utf-8")
            except OSError:
                pass


def _type_upper(type_id: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", str(type_id or "").upper())


def _repo_conf_key(type_id: str, location: str) -> str:
    loc = "STORAGEBOX" if location == "storagebox" else location.upper()
    return f"REPO_{_type_upper(type_id)}_{loc}"


def _paths_conf_key(type_id: str) -> str:
    return f"BACKUP_PATHS_{_type_upper(type_id)}"


def _passphrase_conf_key(type_id: str, location: str) -> str:
    return f"BORG_PASSPHRASE_FILE_{_type_upper(type_id)}_{location.upper()}"


def _infer_legacy_script_identity(py_file: Path) -> Optional[dict]:
    stem = py_file.stem
    if not stem.startswith("borg_backup_"):
        return None
    name = stem[len("borg_backup_"):]
    if not name:
        return None
    if name.startswith("storagebox_"):
        backup_type, location = name[len("storagebox_"):], "storagebox"
    elif name.endswith("_usb"):
        backup_type, location = name[: -len("_usb")], "usb"
    else:
        backup_type, location = name, "local"
    backup_type = backup_type.strip().lower()
    key = f"{backup_type}_{location}"
    if not backup_type or not _JOB_KEY_RX.fullmatch(key):
        return None
    return {"job_key": key, "backup_type": backup_type, "location": location}


def _read_script_content(script_path: Path) -> str:
    try:
        return script_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _extract_script_string(content: str, pattern: str) -> str:
    if not content:
        return ""
    m = re.search(pattern, content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _extract_script_var_string(content: str, var_name: str) -> str:
    if not content or not var_name:
        return ""
    m = re.search(
        rf"^{re.escape(var_name)}\s*=\s*(\((?:.|\n)*?\)|[\"'](?:.|\n)*?[\"'])",
        content,
        re.MULTILINE,
    )
    if not m:
        return ""
    raw = m.group(1).strip()
    parts = re.findall(r"[\"']([^\"']*)[\"']", raw, re.MULTILINE)
    if parts:
        return "".join(parts).strip()
    return ""


def _extract_env_default_literal(content: str, env_name: str) -> tuple[str, str]:
    if not content or not env_name:
        return "", ""
    m = re.search(
        rf'env\.setdefault\(\s*["\']{re.escape(env_name)}["\']\s*,\s*env\.get\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']*)["\']\s*\)\s*\)',
        content,
        re.MULTILINE,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.search(
        rf'env\.setdefault\(\s*["\']{re.escape(env_name)}["\']\s*,\s*env\.get\(\s*["\']([^"\']+)["\']\s*,\s*([_A-Za-z][_A-Za-z0-9]*)\s*\)\s*\)',
        content,
        re.MULTILINE,
    )
    if m:
        return m.group(1).strip(), _extract_script_var_string(content, m.group(2).strip())
    return "", ""


def _extract_passphrase_default(content: str) -> tuple[str, str]:
    if not content:
        return "", ""
    m = re.search(
        r'env\.get\(\s*["\'](BORG_PASSPHRASE_FILE_[^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)',
        content,
        re.MULTILINE,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", ""


def _read_expanded_conf_safe(config: dict) -> dict:
    try:
        from config_api import read_expanded_conf
        conf = read_expanded_conf(config)
        return conf if isinstance(conf, dict) else {}
    except Exception:
        return {}


def _first_profile_key(config: dict, profile_name: str) -> str:
    try:
        from config_api import read_settings_payload
        payload = read_settings_payload(config)
    except Exception:
        return ""
    rows = payload.get(profile_name) if isinstance(payload.get(profile_name), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip().lower()
        if key:
            return key
    return ""


def _legacy_script_candidates(scripts_dir: Path, data_root: Path) -> list[dict]:
    jobs_dir = get_jobs_meta_dir(scripts_dir, data_root)
    out: list[dict] = []
    if not scripts_dir.is_dir():
        return out
    for py_file in sorted(scripts_dir.glob("borg_backup_*.py")):
        if not py_file.is_file():
            continue
        ident = _infer_legacy_script_identity(py_file)
        if ident is None:
            out.append({"script": str(py_file), "status": "skipped", "reason": "invalid legacy script name"})
            continue
        meta_path = jobs_dir / f"{ident['job_key']}.json"
        if meta_path.exists():
            continue
        out.append({**ident, "script": str(py_file), "status": "pending", "metadata_path": str(meta_path)})
    return out


def detect_legacy_script_jobs(config: dict) -> dict:
    data_root = resolve_data_root(config)
    scripts_dir = resolve_scripts_dir(config)
    migrate_jobs_metadata_dir(scripts_dir, data_root)
    candidates = _legacy_script_candidates(scripts_dir, data_root)
    pending = [row for row in candidates if row.get("status") == "pending"]
    skipped = [row for row in candidates if row.get("status") == "skipped"]
    return {
        "pending": pending,
        "skipped": skipped,
        "pending_count": len(pending),
        "skipped_count": len(skipped),
    }


def _build_migrated_metadata(config: dict, candidate: dict, conf: dict) -> tuple[dict, dict]:
    script_path = Path(str(candidate["script"]))
    content = _read_script_content(script_path)
    type_id = str(candidate["backup_type"]).strip().lower()
    location = str(candidate["location"]).strip().lower()
    job_key = str(candidate["job_key"]).strip()
    type_upper = _type_upper(type_id)

    repo_key = _repo_conf_key(type_id, location)
    paths_key = _paths_conf_key(type_id)
    pass_key = _passphrase_conf_key(type_id, location)

    script_repo_key, script_repo_default = _extract_env_default_literal(content, "BORG_REPO")
    if script_repo_key:
        repo_key = script_repo_key
    if not script_repo_default:
        script_repo_default = _extract_script_string(content, r'_DEFAULT_REPO\s*=\s*["\']([^"\']+)["\']')
    repo_default = str(conf.get(repo_key) or script_repo_default or "").strip()

    script_paths_key, script_paths_default = _extract_env_default_literal(content, "BACKUP_PATHS")
    if script_paths_key:
        paths_key = script_paths_key
    if not script_paths_default:
        script_paths_default = _extract_script_var_string(content, "_DEFAULT_PATHS")
    paths_default = str(conf.get(paths_key) or script_paths_default or "").strip()

    script_pass_key, script_pass_default = _extract_passphrase_default(content)
    if script_pass_key:
        pass_key = script_pass_key
    pass_default = str(
        conf.get(pass_key)
        or script_pass_default
        or (DEFAULT_SECRETS_DIR / f".borg-passphrase-{type_id}_{location}")
    ).strip()

    desc_file = script_path.with_suffix(".description")
    try:
        description = desc_file.read_text(encoding="utf-8").strip() if desc_file.exists() else ""
    except OSError:
        description = ""
    job_name = _extract_script_string(content, r'env\.setdefault\(["\']JOB_NAME["\'],\s*["\']([^"\']+)["\']\)')
    if not job_name:
        job_name = type_id.capitalize()

    usb_profile_key = _first_profile_key(config, "usb_profiles") if location == "usb" else ""
    storage_profile_key = _first_profile_key(config, "storage_profiles") if location == "storagebox" else ""
    review_reasons = []
    if not repo_default:
        review_reasons.append("repository default missing")
    if not paths_default:
        review_reasons.append("source paths missing")
    if location == "storagebox" and not storage_profile_key:
        review_reasons.append("storage profile missing")
    enabled = not review_reasons
    if review_reasons:
        note = (
            "Migrated from a legacy script and disabled because required values could not be resolved: "
            + ", ".join(review_reasons)
            + ". Review and save the job before enabling it."
        )
        description = f"{description}\n\n{note}".strip()

    now_iso = datetime.now().astimezone().replace(microsecond=0).isoformat()
    metadata = {
        "job_key": job_key,
        "name": job_name,
        "description": description,
        "icon": "",
        "icon_color": "",
        "enabled": enabled,
        "standard": "wizard",
        "backup_type": type_id,
        "location": location,
        "usb_profile_key": usb_profile_key,
        "smb_profile_key": "",
        "storage_profile_key": storage_profile_key,
        "mount_before_run": True,
        "unmount_after_run": True,
        "remote_init_confirmed": False,
        "script": "",
        "runner": "scriptless-wizard-runner",
        "repo": {
            "conf_key": repo_key,
            "default": repo_default,
        },
        "passphrase": {
            "conf_key": pass_key,
            "default": pass_default,
            "mode": "existing_file",
        },
        "paths": {
            "conf_key": paths_key,
            "default": paths_default,
        },
        "features": {
            "docker": type_id == "appdata",
            "vm": type_id == "vms",
        },
        "docker_control": {
            "mode": "all" if type_id == "appdata" else "none",
            "selected": [],
            "ack_appdata_risk": False,
        },
        "vm_control": {
            "mode": "all" if type_id == "vms" else "none",
            "selected": [],
            "ack_domains_risk": False,
        },
        "compression": str(conf.get(f"COMPRESSION_{type_upper}") or "lz4").strip() or "lz4",
        "retention": {
            "daily": str(conf.get(f"RETENTION_{type_upper}_DAILY") or "7").strip() or "7",
            "weekly": str(conf.get(f"RETENTION_{type_upper}_WEEKLY") or "4").strip() or "4",
            "monthly": str(conf.get(f"RETENTION_{type_upper}_MONTHLY") or "6").strip() or "6",
            "yearly": str(conf.get(f"RETENTION_{type_upper}_YEARLY") or "3").strip() or "3",
        },
        "create_repo_if_missing": True,
        "encryption": "repokey-blake2",
        "created_at": now_iso,
        "updated_at": now_iso,
        "migrated_from": {
            "migration_id": "legacy_script_jobs_v1",
            "script": str(script_path),
        },
    }
    if repo_default and "://" not in repo_default and not repo_default.startswith("ssh:"):
        repo_path = Path(repo_default)
        if repo_path.exists() and (repo_path / "config").exists():
            metadata["create_repo_if_missing"] = False

    audit = {
        "job_key": job_key,
        "script": str(script_path),
        "metadata_path": str(candidate["metadata_path"]),
        "enabled": enabled,
        "review_reasons": review_reasons,
        "repo_key": repo_key,
        "paths_key": paths_key,
        "passphrase_key": pass_key,
    }
    return metadata, audit


def migrate_legacy_script_jobs(config: dict) -> dict:
    data_root = resolve_data_root(config)
    scripts_dir = resolve_scripts_dir(config)
    jobs_dir = get_jobs_meta_dir(scripts_dir, data_root)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    migrate_jobs_metadata_dir(scripts_dir, data_root)

    detected = detect_legacy_script_jobs(config)
    conf = _read_expanded_conf_safe(config)
    details = {
        "migrated": [],
        "skipped": detected.get("skipped", []),
        "errors": [],
    }
    for candidate in detected.get("pending", []):
        meta_path = Path(str(candidate["metadata_path"]))
        if meta_path.exists():
            continue
        try:
            metadata, audit = _build_migrated_metadata(config, candidate, conf)
            meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            details["migrated"].append(audit)
        except Exception as exc:
            details["errors"].append({
                "job_key": str(candidate.get("job_key") or ""),
                "script": str(candidate.get("script") or ""),
                "error": str(exc),
            })
    return details


@dataclass
class JobInfo:
    key: str
    backup_type: str
    location: str
    script_path: Optional[Path]
    name: str = ""
    has_docker: bool = False
    has_vm: bool = False
    description: str = ""
    icon: str = ""
    icon_color: str = ""
    is_utility: bool = False
    standard: str = "wizard"
    enabled: bool = True
    compression: str = ""
    retention_daily: str = ""
    retention_weekly: str = ""
    retention_monthly: str = ""
    retention_yearly: str = ""
    docker_control: dict = None
    vm_control: dict = None
    restore_test_policy_mode: str = ""
    restore_test_interval_days: int = 30
    restore_test_validity_days: int = 30
    restore_test_level: int = 2
    restore_test_max_runtime_minutes: int = 0

    @property
    def display_name(self) -> str:
        loc_label = {"local": "Lokal", "usb": "USB", "smb": "SMB", "storagebox": "Storagebox"}.get(
            self.location, self.location
        )
        return f"{self.backup_type.capitalize()} – {loc_label}"


class _JobState:
    def __init__(self, proc: subprocess.Popen, start_time: datetime):
        self.proc = proc
        self.start_time = start_time
        self.lines: List[str] = []
        self.finished = False
        self.exit_code: Optional[int] = None
        self._lock = threading.Lock()

    def append_line(self, line: str) -> None:
        with self._lock:
            self.lines.append(line)

    def snapshot(self) -> tuple:
        with self._lock:
            return list(self.lines), self.finished, self.exit_code


class JobManager:
    _instance: Optional["JobManager"] = None
    _init_lock = threading.Lock()

    def __init__(self) -> None:
        self._states: Dict[str, _JobState] = {}
        self._lock = threading.Lock()

    @classmethod
    def get(cls) -> "JobManager":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Job starten ──────────────────────────────────────────────────────────

    def start(
        self,
        job_key: str,
        command: List[str],
        cwd: Path,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> tuple:
        """
        Startet einen Backup-Job als Subprozess.
        Gibt (True, None) bei Erfolg zurück, (False, Fehlermeldung) sonst.
        """
        job_key = _validate_job_key(job_key)
        with self._lock:
            state = self._states.get(job_key)
            if state is not None and not state.finished:
                return False, "Job is already running"

        env = dict(os.environ)
        # Damit das Script seine lib/ findet
        env["BORG_SCRIPT_DIR"] = str(cwd)
        if extra_env:
            env.update(extra_env)

        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=1,
                cwd=str(cwd),
            )
        except OSError as exc:
            return False, f"Start failed: {exc}"

        new_state = _JobState(proc, datetime.now())
        with self._lock:
            self._states[job_key] = new_state

        t = threading.Thread(
            target=self._reader,
            args=(job_key, new_state),
            daemon=True,
            name=f"job-reader-{job_key}",
        )
        t.start()
        return True, None

    def _reader(self, job_key: str, state: _JobState) -> None:
        """Liest stdout des Subprozesses Zeile für Zeile in den Puffer."""
        try:
            for line in state.proc.stdout:
                state.append_line(line.rstrip("\n"))
        except Exception:
            pass
        finally:
            state.proc.wait()
            with state._lock:
                state.exit_code = state.proc.returncode
                state.finished = True

    # ── State-Abfrage ─────────────────────────────────────────────────────────

    def get_state(self, job_key: str) -> dict:
        job_key = _validate_job_key(job_key)
        with self._lock:
            state = self._states.get(job_key)
        if state is None:
            return {"running": False}
        lines, finished, exit_code = state.snapshot()
        return {
            "running": not finished,
            "exit_code": exit_code,
            "start_time": state.start_time.isoformat(),
            "line_count": len(lines),
        }

    def get_all_states(self) -> dict:
        with self._lock:
            keys = list(self._states.keys())
        return {k: self.get_state(k) for k in keys}

    def is_running(self, job_key: str) -> bool:
        job_key = _validate_job_key(job_key)
        with self._lock:
            state = self._states.get(job_key)
        return state is not None and not state.finished

    # ── SSE-Stream ────────────────────────────────────────────────────────────

    def stream_output(self, job_key: str) -> Generator[str, None, None]:
        """
        SSE-Generator: liefert neue Log-Zeilen als 'data:' Events.
        Schließt mit einem 'done'-Event (Daten = Exit-Code).
        Bricht sofort ab wenn Job unbekannt ist.
        """
        job_key = _validate_job_key(job_key)
        with self._lock:
            state = self._states.get(job_key)
        if state is None:
            yield "event: error\ndata: Job not found\n\n"
            return

        # Heartbeat damit der Browser nicht timeoutet
        yield ": heartbeat\n\n"

        idx = 0
        while True:
            lines, finished, exit_code = state.snapshot()
            new_lines = lines[idx:]

            for line in new_lines:
                # Escape colons in data lines is not needed for SSE
                yield f"data: {line}\n\n"
            idx += len(new_lines)

            if finished and not new_lines:
                yield f"event: done\ndata: {exit_code if exit_code is not None else '?'}\n\n"
                return

            time.sleep(0.1)


# ── Job-Erkennung ─────────────────────────────────────────────────────────────

def discover_jobs(scripts_dir: Path, data_root: Path | None = None) -> List[JobInfo]:
    """
    Finds backup jobs from canonical JSON metadata.

    Legacy `borg_backup_*.py` script-only jobs are intentionally not returned.
    The one-time `legacy_script_jobs_v1` migration imports them into metadata
    before normal discovery runs.
    """
    utility_types = {"restore_test"}

    def _make_job(
        py_file: Optional[Path],
        backup_type: str,
        location: str,
        *,
        key: Optional[str] = None,
        name: Optional[str] = None,
        has_docker: Optional[bool] = None,
        has_vm: Optional[bool] = None,
        description: Optional[str] = None,
        icon: Optional[str] = None,
        icon_color: Optional[str] = None,
        standard: str = "wizard",
        enabled: bool = True,
        compression: str = "",
        retention_daily: str = "",
        retention_weekly: str = "",
        retention_monthly: str = "",
        retention_yearly: str = "",
        restore_test_policy_mode: str = "",
        restore_test_interval_days: int = 30,
        restore_test_validity_days: int = 30,
        restore_test_level: int = 2,
        restore_test_max_runtime_minutes: int = 0,
        docker_control: Optional[dict] = None,
        vm_control: Optional[dict] = None,
    ) -> JobInfo:
        desc_file = py_file.with_suffix(".description") if py_file is not None else None
        desc_text = (
            description
            if description is not None
            else (
                desc_file.read_text(encoding="utf-8").strip()
                if desc_file is not None and desc_file.exists()
                else ""
            )
        )
        bt_lc = backup_type.lower()
        default_docker_control = {
            "mode": "all" if ((bt_lc == "appdata") if has_docker is None else bool(has_docker)) else "none",
            "selected": [],
            "ack_appdata_risk": False,
        }
        default_vm_control = {
            "mode": "all" if ((bt_lc == "vms") if has_vm is None else bool(has_vm)) else "none",
            "selected": [],
            "ack_domains_risk": False,
        }
        return JobInfo(
            key=key or f"{bt_lc}_{location}",
            backup_type=backup_type,
            location=location,
            script_path=py_file,
            name=(name or "").strip(),
            has_docker=(bt_lc == "appdata") if has_docker is None else bool(has_docker),
            has_vm=(bt_lc == "vms") if has_vm is None else bool(has_vm),
            description=desc_text,
            icon=(icon or "").strip().lower(),
            icon_color=(icon_color or "").strip().lower(),
            # Only explicit utility jobs should be filtered from normal
            # backup selectors. Custom/unknown backup types are still jobs.
            is_utility=bt_lc in utility_types,
            standard=standard,
            enabled=bool(enabled),
            compression=str(compression or "").strip(),
            retention_daily=str(retention_daily or "").strip(),
            retention_weekly=str(retention_weekly or "").strip(),
            retention_monthly=str(retention_monthly or "").strip(),
            retention_yearly=str(retention_yearly or "").strip(),
            docker_control=docker_control or default_docker_control,
            vm_control=vm_control or default_vm_control,
            restore_test_policy_mode=str(restore_test_policy_mode or "").strip().lower(),
            restore_test_interval_days=_safe_int(restore_test_interval_days, 30),
            restore_test_validity_days=_safe_int(restore_test_validity_days, 30),
            restore_test_level=_safe_int(restore_test_level, 2),
            restore_test_max_runtime_minutes=_safe_int(restore_test_max_runtime_minutes, 0),
        )

    jobs_by_key: Dict[str, JobInfo] = {}
    root = data_root if data_root is not None else (scripts_dir.parent if scripts_dir.name == "scripts" else scripts_dir)
    migrate_jobs_metadata_dir(scripts_dir, root)

    # ── Wizard-Metadaten (prioritär) ──────────────────────────────────────────
    meta_dirs = get_jobs_meta_dirs(scripts_dir, root)
    for meta_dir in meta_dirs:
        if not meta_dir.is_dir():
            continue
        for meta_file in sorted(meta_dir.glob("*.json")):
            try:
                raw = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                continue

            # Pflichtfelder V1
            try:
                key = str(raw["job_key"]).strip()
                backup_type = str(raw["backup_type"]).strip()
                location = str(raw["location"]).strip().lower()
                script_name = str(raw.get("script") or "").strip()
            except (KeyError, TypeError, ValueError):
                continue

            if not key or not backup_type or not location:
                continue
            if location not in {"local", "usb", "smb", "storagebox", "custom"}:
                continue

            script_path = (scripts_dir / script_name).resolve()
            if script_name:
                try:
                    script_path.relative_to(scripts_dir.resolve())
                except ValueError:
                    # Pfad außerhalb scripts_dir ignorieren
                    continue
            else:
                script_path = None

            features = raw.get("features") if isinstance(raw.get("features"), dict) else {}
            retention = raw.get("retention") if isinstance(raw.get("retention"), dict) else {}
            rt_policy = raw.get("restore_test_policy") if isinstance(raw.get("restore_test_policy"), dict) else {}
            docker_control = _runtime_control_from_meta(raw, "docker")
            vm_control = _runtime_control_from_meta(raw, "vm")
            has_docker = bool(features.get("docker", False))
            has_vm = bool(features.get("vm", False))
            description = raw.get("description")
            if description is not None:
                description = str(description)

            # Preferred dir wins: only set if job key not seen yet.
            jobs_by_key.setdefault(key, _make_job(
                script_path,
                backup_type,
                location,
                key=key,
                name=str(raw.get("name") or "").strip(),
                has_docker=has_docker,
                has_vm=has_vm,
                description=description,
                icon=str(raw.get("icon") or "").strip().lower(),
                icon_color=str(raw.get("icon_color") or "").strip().lower(),
                standard="wizard",
                enabled=bool(raw.get("enabled", True)),
                compression=str(raw.get("compression") or "").strip(),
                retention_daily=str(retention.get("daily") or "").strip(),
                retention_weekly=str(retention.get("weekly") or "").strip(),
                retention_monthly=str(retention.get("monthly") or "").strip(),
                retention_yearly=str(retention.get("yearly") or "").strip(),
                docker_control=docker_control,
                vm_control=vm_control,
                restore_test_policy_mode=str(rt_policy.get("mode") or "").strip().lower(),
                restore_test_interval_days=_safe_int(rt_policy.get("interval_days"), 30),
                restore_test_validity_days=_safe_int(rt_policy.get("validity_days") or rt_policy.get("interval_days"), 30),
                restore_test_level=_safe_int(rt_policy.get("level"), 2),
                restore_test_max_runtime_minutes=_safe_int(rt_policy.get("max_runtime_minutes"), 0),
            ))

    return list(jobs_by_key.values())


def list_jobs(config: dict, latest_statuses: dict) -> List[dict]:
    """
    Gibt alle erkannten Jobs als JSON-serialisierbares Dict zurück,
    angereichert mit dem letzten Backup-Status.
    """
    scripts_dir = resolve_scripts_dir(config)
    data_root = resolve_data_root(config)
    manager = JobManager.get()

    result = []
    for info in discover_jobs(scripts_dir, data_root):
        last = latest_statuses.get(info.key)
        run_state = manager.get_state(info.key)

        result.append(
            {
                "key": info.key,
                "backup_type": info.backup_type,
                "location": info.location,
                "display_name": info.display_name,
                "name": info.name or info.display_name,
                "has_docker": info.has_docker,
                "has_vm": info.has_vm,
                "docker_control": info.docker_control or {"mode": "all" if info.has_docker else "none", "selected": []},
                "vm_control": info.vm_control or {"mode": "all" if info.has_vm else "none", "selected": []},
                "description": info.description,
                "icon": info.icon,
                "icon_color": info.icon_color,
                "is_utility": info.is_utility,
                "standard": info.standard,
                "enabled": info.enabled,
                "compression": info.compression,
                "retention_daily": info.retention_daily,
                "retention_weekly": info.retention_weekly,
                "retention_monthly": info.retention_monthly,
                "retention_yearly": info.retention_yearly,
                "restore_test_policy": {
                    "mode": info.restore_test_policy_mode,
                    "interval_days": info.restore_test_interval_days,
                    "validity_days": info.restore_test_validity_days,
                    "level": info.restore_test_level,
                    "max_runtime_minutes": info.restore_test_max_runtime_minutes,
                },
                # Letzter Status (aus status_api)
                "last_status": last["status"] if last else None,
                "last_time_ago": last["time_ago"] if last else None,
                "last_timestamp": last["timestamp"] if last else None,
                "last_exit_code": last["exit_code"] if last else None,
                # Aktueller Laufzustand
                "running": run_state.get("running", False),
                "run_start_time": run_state.get("start_time"),
            }
        )
    try:
        from restore_tests_api import build_restore_verification_map
        verification = build_restore_verification_map(config, result)
    except Exception:
        verification = {}

    for job in result:
        meta = verification.get(job["key"], {})
        job["restore_verification_status"] = meta.get("status", "never")
        job["restore_verification_reason"] = meta.get("reason", "")
        job["restore_verification_last_test_date"] = meta.get("last_test_date", "")
        job["restore_verification_valid_until"] = meta.get("valid_until", "")
        job["restore_verification_is_overdue"] = bool(meta.get("is_overdue", False))
        if isinstance(meta.get("policy"), dict):
            job["restore_test_policy"] = meta.get("policy")
    return result
