"""
api/jobs_api.py – Job-Verwaltung: Erkennung, Start, State-Tracking

JobManager ist ein Singleton und thread-safe. Backup-Scripts werden als
Subprozesse gestartet; deren stdout wird live gepuffert und per SSE ausgeliefert.
"""

import json
import os
import re
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


def _validate_job_key(job_key: str) -> str:
    key = str(job_key or "").strip()
    if not _JOB_KEY_RX.fullmatch(key):
        raise ValueError("Ungültiger Job-Key")
    return key


def _safe_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


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
    preferred = get_jobs_meta_dir(scripts_dir, data_root)
    runtime_legacy = Path("/boot/config/plugins/borg-backup-ui/runtime/config/jobs")
    legacy = scripts_dir / "config" / "jobs"
    dirs = [preferred]
    if runtime_legacy not in dirs:
        dirs.append(runtime_legacy)
    if legacy != preferred:
        dirs.append(legacy)
    return dirs


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
    standard: str = "legacy"
    enabled: bool = True
    compression: str = ""
    retention_daily: str = ""
    retention_weekly: str = ""
    retention_monthly: str = ""
    retention_yearly: str = ""
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
                return False, "Job läuft bereits"

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
            return False, f"Start fehlgeschlagen: {exc}"

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
            yield "event: error\ndata: Job nicht gefunden\n\n"
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
    Findet Backup- und Restore-Test-Skripte im scripts/-Verzeichnis.

    Namensschema borg_backup_*.py:
      borg_backup_{type}.py            → local
      borg_backup_{type}_usb.py        → usb
      borg_backup_storagebox_{type}.py → storagebox

    Namensschema borg_restore_test*.py:
      borg_restore_test.py             → restore_test / local
      borg_restore_test_usb.py         → restore_test / usb
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
        standard: str = "legacy",
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
                restore_test_policy_mode=str(rt_policy.get("mode") or "").strip().lower(),
                restore_test_interval_days=_safe_int(rt_policy.get("interval_days"), 30),
                restore_test_validity_days=_safe_int(rt_policy.get("validity_days") or rt_policy.get("interval_days"), 30),
                restore_test_level=_safe_int(rt_policy.get("level"), 2),
                restore_test_max_runtime_minutes=_safe_int(rt_policy.get("max_runtime_minutes"), 0),
            ))

    # ── borg_backup_*.py ───────────────────────────────────────────────────────
    if scripts_dir.exists():
        for py_file in sorted(scripts_dir.glob("borg_backup_*.py")):
            if not py_file.is_file():
                continue
            name = py_file.stem[len("borg_backup_"):]
            if name.startswith("storagebox_"):
                backup_type, location = name[len("storagebox_"):], "storagebox"
            elif name.endswith("_usb"):
                backup_type, location = name[: -len("_usb")], "usb"
            else:
                backup_type, location = name, "local"
            legacy = _make_job(py_file, backup_type, location, standard="legacy")
            # Fallback: nur übernehmen, wenn Metadaten-Job den Key nicht schon abdeckt
            jobs_by_key.setdefault(legacy.key, legacy)

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
