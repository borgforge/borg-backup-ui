"""Cooperative control state for long-running backup jobs."""

from __future__ import annotations

import json
import os
import re
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


CONTROL_ROOT = Path("/run/borg-backup-ui/jobs")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,96}$")
_JOB_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _safe_component(value: str, pattern: re.Pattern[str], label: str) -> str:
    clean = str(value or "").strip()
    if not pattern.fullmatch(clean):
        raise ValueError(f"Invalid {label}")
    return clean


class JobControl:
    """Runner-owned state plus an API-owned cancellation marker."""

    def __init__(self, job_key: str, run_id: str, root: Path = CONTROL_ROOT) -> None:
        self.job_key = _safe_component(job_key, _JOB_KEY_RE, "job key")
        self.run_id = _safe_component(run_id, _RUN_ID_RE, "run id")
        self.run_dir = Path(root) / self.run_id
        self.state_file = self.run_dir / "state.json"
        self.cancel_file = self.run_dir / "cancel.request.json"
        self._process_lock = threading.Lock()
        self._active_process = None
        self._monitor_stop = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self.run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.run_dir.chmod(0o700)
        except OSError:
            pass

    def update_phase(
        self,
        phase: str,
        *,
        cancel_allowed: bool,
        cancellation_deferred: bool = False,
        message_key: str = "",
        finished: bool = False,
        exit_code: Optional[int] = None,
    ) -> Dict[str, Any]:
        previous = read_control_state(self.run_id, self.run_dir.parent)
        data: Dict[str, Any] = {
            "schema_version": 1,
            "job_key": self.job_key,
            "run_id": self.run_id,
            "pid": os.getpid(),
            "phase": str(phase),
            "cancel_allowed": bool(cancel_allowed),
            "cancellation_deferred": bool(cancellation_deferred),
            "cancel_requested": self.is_cancel_requested(),
            "message_key": str(message_key or ""),
            "started_at": str(previous.get("started_at") or _utc_now()),
            "updated_at": _utc_now(),
            "finished": bool(finished),
            "exit_code": exit_code,
        }
        _atomic_json(self.state_file, data)
        return data

    def is_cancel_requested(self) -> bool:
        return self.cancel_file.is_file()

    def attach_process(self, process: Any) -> None:
        with self._process_lock:
            self._active_process = process
        self._monitor_stop.clear()

        def _monitor() -> None:
            signalled = False
            while not self._monitor_stop.wait(0.2):
                if not self.is_cancel_requested() or signalled:
                    continue
                with self._process_lock:
                    current = self._active_process
                if current is None or current.poll() is not None:
                    continue
                try:
                    current.send_signal(signal.SIGINT)
                    signalled = True
                except (OSError, ProcessLookupError):
                    return

        self._monitor_thread = threading.Thread(
            target=_monitor,
            daemon=True,
            name=f"cancel-monitor-{self.job_key}",
        )
        self._monitor_thread.start()

    def detach_process(self) -> None:
        self._monitor_stop.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=1.0)
        self._monitor_thread = None
        with self._process_lock:
            self._active_process = None


def read_control_state(run_id: str, root: Path = CONTROL_ROOT) -> Dict[str, Any]:
    safe_run_id = _safe_component(run_id, _RUN_ID_RE, "run id")
    path = Path(root) / safe_run_id / "state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    if (path.parent / "cancel.request.json").is_file():
        data["cancel_requested"] = True
    return data


def request_cancel(
    job_key: str,
    run_id: str,
    *,
    requested_by: str = "",
    root: Path = CONTROL_ROOT,
) -> Dict[str, Any]:
    safe_job_key = _safe_component(job_key, _JOB_KEY_RE, "job key")
    safe_run_id = _safe_component(run_id, _RUN_ID_RE, "run id")
    state = read_control_state(safe_run_id, root)
    if not state or state.get("finished"):
        raise FileNotFoundError("The backup run is no longer active")
    if str(state.get("job_key") or "") != safe_job_key:
        raise ValueError("The run does not belong to this job")
    if not bool(state.get("cancel_allowed")):
        raise RuntimeError("Cancellation is no longer possible during runtime recovery")

    run_dir = Path(root) / safe_run_id
    marker = run_dir / "cancel.request.json"
    payload = {
        "schema_version": 1,
        "job_key": safe_job_key,
        "run_id": safe_run_id,
        "requested_at": _utc_now(),
        "requested_by": str(requested_by or ""),
    }
    if not marker.exists():
        _atomic_json(marker, payload)
    state["cancel_requested"] = True
    state["cancel_requested_at"] = payload["requested_at"]
    return state
