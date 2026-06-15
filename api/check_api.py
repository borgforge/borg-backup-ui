"""
api/check_api.py – Manueller Borg-Check mit SSE-Ausgabe

Startet `borg check ... <repo>` als Subprozess und streamt die
Ausgabe per SSE. Es läuft immer nur ein Check gleichzeitig.
"""

import subprocess
import threading
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Generator, List, Optional


class _CheckState:
    def __init__(self, proc: subprocess.Popen, job_key: str, mode: str, start_time: datetime):
        self.proc = proc
        self.job_key = job_key
        self.mode = mode
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


class CheckManager:
    _instance: Optional["CheckManager"] = None
    _init_lock = threading.Lock()
    _MODE_ARGS = {
        "quick": ["--progress"],
        "verbose": ["--progress", "--verbose"],
        "verify_data": ["--progress", "--verbose", "--verify-data"],
    }

    def __init__(self) -> None:
        self._state: Optional[_CheckState] = None
        self._lock = threading.Lock()

    @classmethod
    def get(cls) -> "CheckManager":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def start(self, config: dict, job_key: str, mode: str = "quick") -> tuple:
        """
        Startet borg check für den angegebenen Job.
        Gibt (True, None) bei Erfolg zurück, (False, Fehlermeldung) sonst.
        """
        with self._lock:
            if self._state is not None and not self._state.finished:
                return False, "Ein Check läuft bereits"

        mode = (mode or "quick").strip().lower()
        if mode not in self._MODE_ARGS:
            return False, f"Ungültiger Check-Modus: {mode}"

        try:
            from restore_api import _get_job_repo_info, _borg_env
            from smb_mount import ensure_smb_mount_for_job
            ensure_smb_mount_for_job(config, job_key)
            info = _get_job_repo_info(config, job_key)
            env = _borg_env(info["passphrase_file"])
        except Exception as exc:
            return False, f"Repository-Info nicht lesbar: {exc}"

        cmd = ["borg", "check"] + self._MODE_ARGS[mode] + [info["repo"]]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            return False, f"Start fehlgeschlagen: {exc}"

        state = _CheckState(proc, job_key, mode, datetime.now())
        state.append_line(f"[Info] Starte: {' '.join(cmd[:-1])} {info['repo']}")
        with self._lock:
            self._state = state

        t = threading.Thread(
            target=self._reader,
            args=(state,),
            daemon=True,
            name="borg-check-reader",
        )
        t.start()
        return True, None

    def _reader(self, state: _CheckState) -> None:
        last_emitted: Optional[str] = None

        def _emit(buf: List[str]) -> None:
            nonlocal last_emitted
            if not buf:
                return
            line = "".join(buf).strip()
            if not line:
                return
            # Progress output can repeat the same frame multiple times.
            if line == last_emitted:
                return
            state.append_line(line)
            last_emitted = line

        try:
            if state.proc.stdout is None:
                return

            buf: List[str] = []
            while True:
                ch = state.proc.stdout.read(1)
                if ch == "":
                    _emit(buf)
                    break
                if ch in ("\r", "\n"):
                    _emit(buf)
                    buf = []
                    continue
                buf.append(ch)
        except Exception:
            pass
        finally:
            state.proc.wait()
            with state._lock:
                state.exit_code = state.proc.returncode
                state.finished = True

    def get_state(self) -> dict:
        with self._lock:
            state = self._state
        if state is None:
            return {"running": False}
        lines, finished, exit_code = state.snapshot()
        return {
            "running": not finished,
            "exit_code": exit_code,
            "job_key": state.job_key,
            "mode": state.mode,
            "start_time": state.start_time.isoformat(),
        }

    def stream_output(self) -> Generator[str, None, None]:
        with self._lock:
            state = self._state
        if state is None:
            yield "event: error\ndata: Kein Check gestartet\n\n"
            return

        yield ": heartbeat\n\n"

        idx = 0
        while True:
            lines, finished, exit_code = state.snapshot()
            new_lines = lines[idx:]

            for line in new_lines:
                yield f"data: {line}\n\n"
            idx += len(new_lines)

            if finished and not new_lines:
                yield f"event: done\ndata: {exit_code if exit_code is not None else '?'}\n\n"
                return

            time.sleep(0.1)


def get_check_jobs(config: dict) -> List[dict]:
    """Gibt alle bekannten Jobs zurück (key + display_name) für den Selektor."""
    from jobs_api import discover_jobs, get_jobs_meta_dirs, resolve_data_root, resolve_scripts_dir
    loc_label = {"local": "local", "usb": "usb", "smb": "smb", "storagebox": "storagebox", "custom": "custom"}

    def _label(name: str, location: str) -> str:
        return f"{name} ({loc_label.get(location, location)})"

    scripts_dir = resolve_scripts_dir(config)
    data_root = resolve_data_root(config)
    jobs = discover_jobs(scripts_dir, data_root)
    result = [
        {"key": j.key, "name": _label((j.name or j.display_name), j.location)}
        for j in jobs
        if not j.is_utility
    ]
    if result:
        return result

    # Fallback: lies Wizard-Metadaten direkt, falls discover_jobs nichts liefert.
    seen = set()
    for meta_dir in get_jobs_meta_dirs(scripts_dir, data_root):
        if not meta_dir.is_dir():
            continue
        for meta_file in sorted(meta_dir.glob("*.json")):
            try:
                raw = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            key = str(raw.get("job_key") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            name = str(raw.get("name") or key).strip()
            location = str(raw.get("location") or "").strip().lower() or "local"
            result.append({"key": key, "name": _label(name, location)})
    return result
