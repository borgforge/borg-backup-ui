"""
api/jobs_api.py – Job-Verwaltung: Erkennung, Start, State-Tracking

JobManager ist ein Singleton und thread-safe. Backup-Scripts werden als
Subprozesse gestartet; deren stdout wird live gepuffert und per SSE ausgeliefert.
"""

import json
import io
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Generator, List, Optional

DEFAULT_DATA_ROOT = Path("/boot/config/borg-backup")
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0
_RUNTIME_MODES = {"all", "selected", "none"}
_DOCKER_RUNTIME_MODES = _RUNTIME_MODES | {"except_selected"}


def _validate_runtime_id(job_id: str) -> str:
    # Restore verification remains a separate service during its #477 cutover.
    if job_id == "restore_test":
        return job_id
    from job_model import validate_job_id
    return validate_job_id(job_id)


def _control_state_for_run(run_id: str) -> dict:
    if not run_id:
        return {}
    try:
        from job_control import read_control_state

        state = read_control_state(run_id)
    except (ImportError, OSError, TypeError, ValueError):
        return {}
    return {
        key: state.get(key)
        for key in (
            "phase",
            "cancel_allowed",
            "cancellation_deferred",
            "cancel_requested",
            "message_key",
        )
        if key in state
    }


def cancel_job(config: dict, job_id: str, run_id: str, requested_by: str = "") -> dict:
    """Request cooperative cancellation for the currently active run."""
    key = _validate_runtime_id(job_id)
    runtime = get_job_runtime_state(config, key)
    active_run_id = str(runtime.get("run_id") or "").strip()
    if not runtime.get("running") or not active_run_id:
        raise FileNotFoundError("The backup run is no longer active")
    if str(run_id or "").strip() != active_run_id:
        raise ValueError("The selected backup run is no longer active")
    from job_control import request_cancel

    return request_cancel(key, active_run_id, requested_by=requested_by)


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


def _runtime_modes(kind: str) -> set[str]:
    return _DOCKER_RUNTIME_MODES if kind == "docker" else _RUNTIME_MODES


def _runtime_control_from_meta(meta: dict, kind: str) -> dict:
    raw = meta.get(f"{kind}_control") if isinstance(meta.get(f"{kind}_control"), dict) else {}
    features = meta.get("features") if isinstance(meta.get("features"), dict) else {}
    legacy_enabled = bool(features.get(kind, False))
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in _runtime_modes(kind):
        mode = "all" if legacy_enabled else "none"
    ack_key = "ack_appdata_risk" if kind == "docker" else "ack_domains_risk"
    return {
        "mode": mode,
        "selected": _split_runtime_selected(raw.get("selected", [])) if mode in {"selected", "except_selected"} else [],
        ack_key: bool(raw.get(ack_key, False)),
    }


def resolve_data_root(config: dict) -> Path:
    base = Path(str(config.get("BACKUP_SCRIPTS_DIR", str(DEFAULT_DATA_ROOT))).strip() or str(DEFAULT_DATA_ROOT))
    # If BACKUP_SCRIPTS_DIR points to scripts/, use parent as data root.
    if base.name == "scripts":
        return base.parent
    return base


def resolve_resource_lock_dir(config: dict) -> Path:
    """Return the shared runner lock directory for the current data root."""
    configured = str(config.get("BORG_RESOURCE_LOCK_DIR") or "").strip()
    if not configured:
        try:
            from config_api import read_expanded_conf
            configured = str(read_expanded_conf(config).get("BORG_RESOURCE_LOCK_DIR") or "").strip()
        except Exception:
            configured = ""
    return Path(configured) if configured else resolve_data_root(config) / "locks"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def active_resource_locks(config: dict) -> List[dict]:
    """Read live runner locks without mutating or recovering them."""
    lock_dir = resolve_resource_lock_dir(config)
    if not lock_dir.is_dir():
        return []
    rows: List[dict] = []
    for path in sorted(lock_dir.glob("*.lock.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        job_id = str(raw.get("job_id") or "").strip()
        try:
            if not job_id and raw.get("service") in {"restore", "restore_test"} and raw.get("operation") == raw["service"]:
                pass
            else:
                job_id = _validate_runtime_id(job_id)
        except ValueError:
            continue
        pid = _safe_int(raw.get("pid"), 0)
        if not _pid_alive(pid):
            continue
        from activity_log_capture import process_token
        if raw.get("process_start") and process_token(pid) != raw["process_start"]:
            continue
        rows.append({
            **{key: raw[key] for key in ("job_name_snapshot", "archive_prefix_snapshot", "repository_key_snapshot", "repository_snapshot", "location_snapshot") if key in raw},
            "job_id": job_id,
            "pid": pid,
            "resource": str(raw.get("resource") or "").strip(),
            "operation": str(raw.get("operation") or "backup").strip().lower() or "backup",
            "started_at": str(raw.get("started_at") or "").strip(),
            "updated_at": str(raw.get("updated_at") or "").strip(),
            "log_file": str(raw.get("log_file") or "").strip(),
            "run_id": str(raw.get("run_id") or "").strip(),
            "file_activity": raw.get("file_activity") is True,
        })
    return rows


def is_resource_active(config: dict, resource: str) -> bool:
    expected = str(resource or "").strip()
    return bool(expected) and any(row.get("resource") == expected for row in active_resource_locks(config))


def _runtime_log_dir(config: dict) -> Path:
    configured = str(config.get("GLOBAL_LOG_DIR") or "").strip()
    if not configured:
        try:
            from config_api import read_expanded_conf
            configured = str(read_expanded_conf(config).get("GLOBAL_LOG_DIR") or "").strip()
        except Exception:
            configured = ""
    return Path(configured or "/mnt/user/Logs")


def durable_running_states(config: dict) -> Dict[str, dict]:
    """Aggregate live runner locks into one durable state per job."""
    grouped: Dict[str, dict] = {}
    for lock in active_resource_locks(config):
        if str(lock.get("operation") or "backup").strip().lower() != "backup":
            continue
        job_id = str(lock.get("job_id") or "")
        current = grouped.setdefault(job_id, {
            **{key: value for key, value in lock.items() if key.endswith("_snapshot")},
            "job_id": job_id,
            "running": True,
            "exit_code": None,
            "start_time": str(lock.get("started_at") or ""),
            "pid": lock.get("pid"),
            "log_file": str(lock.get("log_file") or ""),
            "source": "resource_lock",
            "run_id": str(lock.get("run_id") or ""),
            "file_activity": lock.get("file_activity") is True,
        })
        started_at = str(lock.get("started_at") or "")
        if started_at and (not current["start_time"] or started_at < current["start_time"]):
            current["start_time"] = started_at
        if not current["log_file"] and lock.get("log_file"):
            current["log_file"] = str(lock.get("log_file"))
        if not current.get("run_id") and lock.get("run_id"):
            current["run_id"] = str(lock.get("run_id"))
    from activity_log_capture import running_captures
    for capture in running_captures():
        grouped.setdefault(capture['job_id'], capture)
    for job_id, state in grouped.items():
        state["log_available"] = bool(state.get("log_file") and Path(str(state["log_file"])).is_file())
        state.update(_control_state_for_run(str(state.get("run_id") or "")))
    return grouped


def get_job_runtime_state(config: dict, job_id: str) -> dict:
    key = _validate_runtime_id(job_id)
    memory = JobManager.get().get_state(key)
    if memory.get("running"):
        return memory
    return durable_running_states(config).get(key, memory)


def get_all_runtime_states(config: dict) -> Dict[str, dict]:
    states = JobManager.get().get_all_states()
    for job_id, durable in durable_running_states(config).items():
        if not states.get(job_id, {}).get("running"):
            states[job_id] = durable
    return states


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


@dataclass
class JobInfo:
    job_id: str
    repository_key: str
    archive_prefixes: list[str]
    location: str
    script_path: Optional[Path] = None
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
    file_activity: bool = False

    @property
    def display_name(self) -> str:
        return self.name


class _JobState:
    def __init__(self, proc: subprocess.Popen, start_time: datetime, run_id: str, log_file: Path | None = None, capture_record_file: Path | None = None):
        self.proc = proc
        self.start_time = start_time
        self.run_id = run_id
        self.log_file = log_file
        self.capture_record_file = capture_record_file
        self.run_snapshot = {}
        self.line_count = 0
        self.lines: List[str] = []
        self.finished = False
        self.exit_code: Optional[int] = None
        self._lock = threading.Lock()

    def open_log(self):
        if self.capture_record_file:
            from activity_log_capture import open_capture_file
            return open_capture_file(self.capture_record_file)
        return self.log_file.open("rb")

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
        job_id: str,
        command: List[str],
        cwd: Path,
        extra_env: Optional[Dict[str, str]] = None,
        *, run_context: dict | None = None,
    ) -> tuple:
        with self._lock:
            return self._start_locked(job_id, command, cwd, extra_env, run_context=run_context)

    def _start_locked(self, job_id, command, cwd, extra_env, *, run_context):
        """
        Startet einen Backup-Job als Subprozess.
        Gibt (True, None) bei Erfolg zurück, (False, Fehlermeldung) sonst.
        """
        job_id = _validate_runtime_id(job_id)
        state = self._states.get(job_id)
        if state is not None and not state.finished:
            return False, "Job is already running"
        if job_id != "restore_test":
            from job_runs import read_run_context
            if not run_context:
                raise ValueError("An immutable run context is required")
            run_context = read_run_context(job_id, run_context["run_id"])

        env = dict(os.environ)
        # Damit das Script seine lib/ findet
        env["BORG_SCRIPT_DIR"] = str(cwd)
        if extra_env:
            env.update(extra_env)
        run_id = run_context["run_id"] if run_context else str(uuid.uuid4())
        env["BORG_UI_RUN_ID"] = run_id
        if run_context:
            env["BORG_UI_JOB_ID"] = job_id
            env.pop("BORG_UI_JOB_KEY", None)
            env["BORG_UI_FILE_ACTIVITY_RUN"] = "1" if run_context["context"]["job"].get("file_activity") else "0"
            env["BORG_UI_ACTIVITY_LOG_DIR"] = str(Path(run_context["log_file"]).parent)

        log_file = None
        capture_record_file = None
        log_handle = None
        try:
            if env.get("BORG_UI_FILE_ACTIVITY_RUN") == "1":
                from activity_log import activity_log_path
                from activity_log_capture import prepare_capture

                log_file, capture_record_file = prepare_capture(job_id, run_id, Path(env["BORG_UI_ACTIVITY_LOG_DIR"]), name=run_context["job_name_snapshot"])
                log_handle = os.fdopen(os.open(log_file, os.O_WRONLY | os.O_NOFOLLOW), "wb")
                env["BORG_UI_CAPTURE_LOG"] = str(log_file)
                env["BORG_UI_RETAINED_LOG"] = run_context["log_file"]
                command = [sys.executable, str(Path(__file__).with_name("activity_log_capture.py")), str(capture_record_file), *command]
                env["PYTHONUNBUFFERED"] = "1"
                env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.Popen(
                command,
                stdout=log_handle if log_handle is not None else subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=1,
                cwd=str(cwd),
            )
        except OSError as exc:
            return False, f"Start failed: {exc}"
        finally:
            if log_handle is not None:
                log_handle.close()

        new_state = _JobState(proc, datetime.now(), run_id, log_file, capture_record_file)
        if run_context:
            from job_runs import descriptors
            new_state.run_snapshot = {**descriptors(run_context), "log_file": run_context["log_file"], "file_activity": False}
        self._states[job_id] = new_state

        t = threading.Thread(
            target=self._reader,
            args=(job_id, new_state),
            daemon=True,
            name=f"job-reader-{job_id}",
        )
        t.start()
        return True, None

    def _reader(self, job_id: str, state: _JobState) -> None:
        """Liest stdout des Subprozesses Zeile für Zeile in den Puffer."""
        try:
            if state.log_file is None:
                for line in state.proc.stdout:
                    state.append_line(line.rstrip("\n"))
            else:
                # Preserve the existing running-state line_count contract.
                # Count once in blocks, independently of all browser readers.
                pending_line = False
                with state.open_log() as handle:
                    while True:
                        finished = state.proc.poll() is not None
                        chunk = handle.read(65536)
                        if chunk:
                            with state._lock:
                                state.line_count += chunk.count(b"\n")
                            pending_line = not chunk.endswith(b"\n")
                        elif finished:
                            if pending_line:
                                with state._lock:
                                    state.line_count += 1
                            break
                        else:
                            time.sleep(0.1)
        except Exception:
            pass
        finally:
            state.proc.wait()
            if state.capture_record_file:
                from activity_log_capture import capture_path, read_record
                record = read_record(state.capture_record_file)
                if record:
                    state.log_file = capture_path(record)
            with state._lock:
                state.exit_code = state.proc.returncode
                state.finished = True

    # ── State-Abfrage ─────────────────────────────────────────────────────────

    def get_state(self, job_id: str) -> dict:
        job_id = _validate_runtime_id(job_id)
        with self._lock:
            state = self._states.get(job_id)
        if state is None:
            return {"running": False}
        if state.log_file is not None:
            with state._lock:
                return {
                    **state.run_snapshot,
                    "running": not state.finished,
                    "exit_code": state.exit_code,
                    "line_count": state.line_count,
                    "start_time": state.start_time.isoformat(),
                    "run_id": state.run_id,
                    "file_activity": True,
                    "log_file": str(state.log_file),
                    "log_available": state.log_file.is_file(),
                    **_control_state_for_run(state.run_id),
                }
        lines, finished, exit_code = state.snapshot()
        return {
            **state.run_snapshot,
            "running": not finished,
            "exit_code": exit_code,
            "start_time": state.start_time.isoformat(),
            "line_count": len(lines),
            "run_id": state.run_id,
            **_control_state_for_run(state.run_id),
        }

    def get_all_states(self) -> dict:
        with self._lock:
            keys = list(self._states.keys())
        return {k: self.get_state(k) for k in keys}

    def is_running(self, job_id: str) -> bool:
        job_id = _validate_runtime_id(job_id)
        with self._lock:
            state = self._states.get(job_id)
        return state is not None and not state.finished

    # ── SSE-Stream ────────────────────────────────────────────────────────────

    def stream_output(self, job_id: str, run_id: str = "") -> Generator[str, None, None]:
        """
        SSE-Generator: liefert neue Log-Zeilen als 'data:' Events.
        Schließt mit einem 'done'-Event (Daten = Exit-Code).
        Bricht sofort ab wenn Job unbekannt ist.
        """
        job_id = _validate_runtime_id(job_id)
        with self._lock:
            state = self._states.get(job_id)
        if state is None or (run_id and state.run_id != run_id):
            yield "event: error\ndata: Job not found\n\n"
            return
        if state.log_file is not None:
            # Keep the existing SSE contract for API clients. The activity UI
            # uses bounded file windows and does not open this per-line stream.
            with io.TextIOWrapper(state.open_log(), encoding="utf-8", errors="replace") as handle:
                while True:
                    line = handle.readline()
                    if line:
                        yield f"data: {line.rstrip(chr(10))}\n\n"
                    elif state.finished:
                        yield f"event: done\ndata: {state.exit_code}\n\n"
                        return
                    else:
                        yield ": heartbeat\n\n"
                        time.sleep(0.5)
            return

        # Heartbeat damit der Browser nicht timeoutet
        yield ": heartbeat\n\n"

        idx = 0
        last_heartbeat = time.monotonic()
        while True:
            lines, finished, exit_code = state.snapshot()
            new_lines = lines[idx:]

            for line in new_lines:
                # Escape colons in data lines is not needed for SSE
                yield f"data: {line}\n\n"
            idx += len(new_lines)
            if new_lines:
                last_heartbeat = time.monotonic()

            if finished and not new_lines:
                yield f"event: done\ndata: {exit_code if exit_code is not None else '?'}\n\n"
                return
            if not new_lines and time.monotonic() - last_heartbeat >= SSE_HEARTBEAT_INTERVAL_SECONDS:
                yield ": heartbeat\n\n"
                last_heartbeat = time.monotonic()

            time.sleep(0.1)


def stream_job_output(config: dict, job_id: str, run_id: str = "") -> Generator[str, None, None]:
    """Stream one immutable run; a newer run never changes this stream's owner."""
    key = _validate_runtime_id(job_id)
    manager = JobManager.get()
    if key == "restore_test":
        yield from manager.stream_output(key)
        return
    from job_runs import validate_run_id, find_run_status
    from job_control import read_control_state
    from activity_log import open_activity_file
    validate_run_id(run_id)
    memory = manager.get_state(key)
    if memory.get("run_id") == run_id:
        yield from manager.stream_output(key, run_id)
        return
    durable = durable_running_states(config).get(key, {})
    state = durable if durable.get("run_id") == run_id else find_run_status(config, key, run_id)
    if not state.get("log_file"):
        yield "event: error\ndata: Log is not available for this run.\n\n"
        return
    from activity_log_capture import capture_record, open_capture_file
    capture = capture_record(key, run_id) if state.get("file_activity") else {}
    try:
        binary = (open_capture_file(Path(capture["active_file"]).parent / "capture.json")
                  if capture else open_activity_file(Path(state["log_file"])))
    except OSError:
        yield "event: error\ndata: Log could not be read.\n\n"
        return
    yield ": heartbeat\n\n"
    last_heartbeat = time.monotonic()
    idle_after_finish = 0
    with io.TextIOWrapper(binary, encoding="utf-8", errors="replace") as handle:
        while True:
            line = handle.readline()
            if line:
                yield f"data: {line.rstrip(chr(10))}\n\n"
                idle_after_finish = 0
                continue
            current = durable_running_states(config).get(key, {})
            running = current.get("running") and current.get("run_id") == run_id
            if not running:
                idle_after_finish += 1
                if idle_after_finish >= 2:
                    control = read_control_state(run_id)
                    terminal = control if control.get("job_id") == key else find_run_status(config, key, run_id)
                    code = terminal.get("exit_code")
                    yield f"event: done\ndata: {code if code is not None else '?'}\n\n"
                    return
            if time.monotonic() - last_heartbeat >= SSE_HEARTBEAT_INTERVAL_SECONDS:
                yield ": heartbeat\n\n"
                last_heartbeat = time.monotonic()
            time.sleep(0.5)


# ── Job-Erkennung ─────────────────────────────────────────────────────────────

def _discover_jobs_uncached(scripts_dir: Path, data_root: Path | None = None) -> List[JobInfo]:
    from job_store import read_jobs
    from repository_context import load_repository_inventory, resolve_job_repository_context
    root = data_root if data_root is not None else (scripts_dir.parent if scripts_dir.name == "scripts" else scripts_dir)
    config = {"BACKUP_SCRIPTS_DIR": str(root)}
    inventory = load_repository_inventory(config)
    jobs = []
    for job_id, raw in read_jobs(get_jobs_meta_dir(scripts_dir, root)).items():
        context = resolve_job_repository_context(config, job_id, job=raw,
            require_passphrase_file=False, inventory=inventory)
        retention = raw.get("retention", {})
        policy = raw.get("restore_test_policy", {})
        docker = _runtime_control_from_meta(raw, "docker")
        vm = _runtime_control_from_meta(raw, "vm")
        jobs.append(JobInfo(
            job_id=job_id, repository_key=raw["repository_key"], archive_prefixes=list(raw["archive_prefixes"]),
            location=context["location"], name=raw["name"], description=raw.get("description", ""),
            icon=raw.get("icon", ""), icon_color=raw.get("icon_color", ""),
            enabled=raw.get("enabled", True), standard=raw.get("standard", "wizard"),
            file_activity=raw.get("file_activity", False), compression=raw.get("compression", ""),
            has_docker=docker["mode"] != "none", has_vm=vm["mode"] != "none",
            docker_control=docker, vm_control=vm,
            **{"retention_" + key: retention.get(key, "") for key in ("daily", "weekly", "monthly", "yearly")},
            restore_test_policy_mode=policy.get("mode", ""),
            restore_test_interval_days=_safe_int(policy.get("interval_days"), 30),
            restore_test_validity_days=_safe_int(policy.get("validity_days"), 30),
            restore_test_level=_safe_int(policy.get("level"), 2),
            restore_test_max_runtime_minutes=_safe_int(policy.get("max_runtime_minutes"), 0),
        ))
    return jobs


def discover_jobs(scripts_dir: Path, data_root: Path | None = None) -> List[JobInfo]:
    """Read the validated canonical inventory; never migrate on discovery."""
    from inventory_store import inventory_lock
    root = data_root if data_root is not None else (scripts_dir.parent if scripts_dir.name == "scripts" else scripts_dir)
    with inventory_lock(root / "config"):
        return _discover_jobs_uncached(scripts_dir, root)


def latest_job_statuses(config: dict) -> dict:
    """Job controls read status directly, without reporting/snapshot side effects."""
    from wizard_runner import _ensure_runtime_import_paths
    _ensure_runtime_import_paths(resolve_data_root(config))
    from lib.status import StatusStore, time_ago
    store = StatusStore(Path(config.get("STATUS_DIR") or "/mnt/user/backup-status"))
    return {job_id: {
        "job_id": job_id, "run_id": row.run_id, "status": row.status,
        "timestamp": row.timestamp, "time_ago": time_ago(row.timestamp),
        "exit_code": row.exit_code, "file_activity": row.file_activity,
        "job_name_snapshot": row.job_name_snapshot, "log_file": row.log_file,
    } for job_id, row in store.get_latest_per_key(store.load()).items()}


def list_jobs(config: dict, latest_statuses: dict) -> List[dict]:
    """
    Gibt alle erkannten Jobs als JSON-serialisierbares Dict zurück,
    angereichert mit dem letzten Backup-Status.
    """
    scripts_dir = resolve_scripts_dir(config)
    data_root = resolve_data_root(config)
    runtime_states = get_all_runtime_states(config)
    from repository_context import load_repository_inventory, resolve_job_repository_context
    repository_inventory = load_repository_inventory(config)
    result = []
    for info in discover_jobs(scripts_dir, data_root):
        last = latest_statuses.get(info.job_id)
        run_state = runtime_states.get(info.job_id, {"running": False})
        if not run_state.get("run_id") and last and last.get("run_id"):
            run_state = {"running": False, "run_id": last["run_id"],
                         "file_activity": last.get("file_activity", False),
                         "job_name_snapshot": last.get("job_name_snapshot", ""),
                         "log_available": bool(last.get("log_file"))}
        repository_context = resolve_job_repository_context(config, info.job_id,
            require_passphrase_file=False, inventory=repository_inventory)
        repo_path = repository_context["repository_path"]
        repository_key = repository_context["repository_key"]
        repository = repository_context["repository"]
        repository_name = repository.get("display_name") or repository.get("repository_name") or repository_key

        result.append(
            {
                "job_id": info.job_id,
                "archive_prefix": info.archive_prefixes[0],
                "archive_prefixes": list(info.archive_prefixes),
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
                "repository_key": repository_key,
                "repository_name": repository_name,
                "repo_path": repo_path,
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
                "run_log_available": run_state.get("log_available", True),
                "run_file_activity": run_state.get("file_activity", False),
                "run_id": run_state.get("run_id", ""),
                "run_name_snapshot": run_state.get("job_name_snapshot", ""),
            }
        )
    try:
        from restore_tests_api import build_restore_verification_map
        verification = build_restore_verification_map(config, result)
    except Exception:
        verification = {}

    for job in result:
        meta = verification.get(job["job_id"], {})
        job["restore_verification_status"] = meta.get("status", "never")
        job["restore_verification_reason"] = meta.get("reason", "")
        job["restore_verification_last_test_date"] = meta.get("last_test_date", "")
        job["restore_verification_valid_until"] = meta.get("valid_until", "")
        job["restore_verification_is_overdue"] = bool(meta.get("is_overdue", False))
        job["restore_verification_failure_code"] = meta.get("failure_code", "")
        job["restore_verification_failure_hint"] = meta.get("failure_hint", "")
        job["restore_verification_failure_category"] = meta.get("failure_category", "")
        if isinstance(meta.get("policy"), dict):
            job["restore_test_policy"] = meta.get("policy")
    return result
