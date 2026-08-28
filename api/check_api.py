"""Run and record Borg repository maintenance actions.

Check, data verification, prune, and compact run as subprocesses. Only one
maintenance action may run at a time; the UI consumes SSE only as a completion
signal and presents the persisted structured result.
"""

import subprocess
import threading
import time
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, List, Optional


def _archive_prefix_from_job_key(job_key: str) -> str:
    """Return the archive prefix used by wizard jobs, e.g. appdata-backup."""
    key = str(job_key or "").strip()
    for location in ("storagebox", "local", "usb", "smb"):
        suffix = f"_{location}"
        if key.endswith(suffix):
            backup_type = key[: -len(suffix)]
            return f"{backup_type}-backup" if backup_type else ""
    backup_type = key.rsplit("_", 1)[0] if "_" in key else key
    return f"{backup_type}-backup" if backup_type else ""


class _CheckState:
    def __init__(
        self,
        proc: subprocess.Popen,
        target_key: str,
        mode: str,
        start_time: datetime,
        action: str = "check",
        *,
        config: Optional[dict] = None,
        repository: Optional[dict] = None,
    ):
        self.proc = proc
        self.target_key = target_key
        self.job_key = target_key
        self.mode = mode
        self.action = action
        self.start_time = start_time
        self.lines: List[str] = []
        self.finished = False
        self.exit_code: Optional[int] = None
        self.cleanup = None
        self.config = dict(config or {})
        self.repository = dict(repository or {})
        self.result: Optional[dict] = None
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
    _LOCK_WAIT_SECONDS = "30"
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

    def start_repository(self, config: dict, repository_key: str, action: str = "check", mode: str = "quick") -> tuple:
        """Start a maintenance action for one managed repository object."""
        with self._lock:
            if self._state is not None and not self._state.finished:
                return False, "A repository maintenance action is already running"

        action = str(action or "check").strip().lower()
        mode = str(mode or "quick").strip().lower()
        if action not in {"check", "prune", "compact"}:
            return False, f"Invalid repository action: {action}"
        if action == "check" and mode not in self._MODE_ARGS:
            return False, f"Invalid check mode: {mode}"

        cleanup = None
        try:
            from repositories_api import _repo_env, effective_repository_path, read_repository_store
            from storage_objects_api import read_storage_store
            repositories = {
                str(row.get("repository_key") or ""): row
                for row in read_repository_store(config).get("repositories", [])
            }
            repository = repositories.get(str(repository_key or "").strip())
            if not repository:
                return False, "Repository object was not found"
            storages = {
                str(row.get("storage_key") or ""): row
                for row in read_storage_store(config).get("storages", [])
            }
            storage = storages.get(str(repository.get("storage_key") or ""), {})
            repo_path = effective_repository_path(storage, str(repository.get("relative_path") or ""))
            if not repo_path:
                return False, "Repository path is missing"
            passphrase_ref = str(repository.get("passphrase_ref") or "").strip()
            passphrase_file = Path(passphrase_ref) if passphrase_ref else None
            if passphrase_file is not None and not passphrase_file.is_file():
                return False, "Repository passphrase file is missing"
            if str(storage.get("location") or "").lower() == "smb":
                from smb_profiles_api import run_smb_profile_action
                mounted = run_smb_profile_action(config, str(storage.get("profile_key") or ""), "mount")
                if not mounted.get("ok"):
                    return False, str(mounted.get("message") or "SMB mount failed")
                if mounted.get("message_code") == "smb_mount_success":
                    profile_key = str(storage.get("profile_key") or "")
                    cleanup = lambda: run_smb_profile_action(config, profile_key, "unmount")
            env = _repo_env(
                storage,
                passphrase_file,
                config,
                encryption=str(repository.get("encryption") or ""),
            )
            cmd = self._repository_command(config, repository, repo_path, action, mode)
        except Exception as exc:
            return False, f"Repository information is not readable: {exc}"

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
            if cleanup:
                cleanup()
            return False, f"Start failed: {exc}"

        state = _CheckState(
            proc,
            str(repository_key),
            mode,
            datetime.now(timezone.utc),
            action=action,
            config=config,
            repository=repository,
        )
        state.cleanup = cleanup
        state.append_line(f"[Info] Starting repository {action}: {' '.join(cmd[:-1])} {repo_path}")
        with self._lock:
            self._state = state
        threading.Thread(
            target=self._reader,
            args=(state,),
            daemon=True,
            name=f"borg-{action}-reader",
        ).start()
        return True, None

    def _repository_command(self, config: dict, repository: dict, repo_path: str, action: str, mode: str) -> list[str]:
        if action == "check":
            return [
                "borg", "check", "--lock-wait", self._LOCK_WAIT_SECONDS,
                *self._MODE_ARGS[mode], repo_path,
            ]
        if action == "compact":
            return [
                "borg", "compact", "--lock-wait", self._LOCK_WAIT_SECONDS,
                "--progress", repo_path,
            ]

        from repository_context import jobs_using_repository
        used_by = jobs_using_repository(config, str(repository.get("repository_key") or ""))
        job_key = next((str(item or "").strip() for item in used_by if str(item or "").strip()), "")
        if not job_key:
            raise ValueError("Prune requires a backup job with a retention policy")
        retention = self._job_retention(config, job_key)
        archive_prefix = _archive_prefix_from_job_key(job_key)
        cmd = [
            "borg", "prune", "--lock-wait", self._LOCK_WAIT_SECONDS,
            "--list", "--progress",
        ]
        if archive_prefix:
            cmd.extend(["--glob-archives", f"{archive_prefix}-*"])
        for key, option in (("daily", "--keep-daily"), ("weekly", "--keep-weekly"), ("monthly", "--keep-monthly"), ("yearly", "--keep-yearly")):
            value = str(retention.get(key) or "").strip()
            if value:
                cmd.extend([option, value])
        if len(cmd) == 4:
            raise ValueError("The selected job has no retention policy")
        cmd.append(repo_path)
        return cmd

    @staticmethod
    def _job_retention(config: dict, job_key: str) -> dict:
        from jobs_api import get_jobs_meta_dirs, resolve_data_root, resolve_scripts_dir
        scripts_dir = resolve_scripts_dir(config)
        data_root = resolve_data_root(config)
        for directory in get_jobs_meta_dirs(scripts_dir, data_root):
            path = directory / f"{job_key}.json"
            if not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload.get("retention") if isinstance(payload.get("retention"), dict) else {}
        raise ValueError(f"Job metadata not found: {job_key}")

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
            if state.cleanup:
                try:
                    state.cleanup()
                except Exception as exc:
                    state.append_line(f"[Warning] Repository cleanup failed: {exc}")
            result = None
            if state.repository and state.config:
                try:
                    result = self._persist_repository_result(state)
                except Exception as exc:
                    state.append_line(f"[Warning] Maintenance result could not be saved: {exc}")
            with state._lock:
                state.exit_code = state.proc.returncode
                state.result = result
                state.finished = True

    @staticmethod
    def _maintenance_result(state: _CheckState) -> dict:
        from borg_ssh import SSH_INTERRUPTION_CODE, SSH_INTERRUPTION_MESSAGE, is_ssh_connection_interruption
        from security_utils import mask_secrets

        lines, _, _ = state.snapshot()
        exit_code = int(state.proc.returncode or 0)
        has_warning = any(str(line).lstrip().lower().startswith("[warning]") for line in lines)
        status = "success" if exit_code == 0 and not has_warning else ("warning" if exit_code in {0, 1} else "error")
        finished_at = datetime.now(timezone.utc)
        started_at = state.start_time
        if started_at.tzinfo is None:
            started_at = started_at.astimezone()
        started_at = started_at.astimezone(timezone.utc)
        action_key = "verify_data" if state.action == "check" and state.mode == "verify_data" else state.action
        deleted_archives = []
        freed_space = ""
        for raw in lines:
            line = str(raw or "").strip()
            match = re.search(r"\bPruning archive(?:\s*\([^)]*\))?\s*:\s*(.+)$", line, re.IGNORECASE)
            if match:
                archive = match.group(1).strip()
                if archive and archive not in deleted_archives:
                    deleted_archives.append(archive)
            freed = re.search(
                r"\bfreed(?:\s+about)?\s+([0-9]+(?:[.,][0-9]+)?\s*(?:[KMGTPE]i?B|bytes?))",
                line,
                re.IGNORECASE,
            )
            if freed:
                freed_space = freed.group(1).replace(",", ".")

        details = []
        if status != "success":
            visible = [
                mask_secrets(str(line or "").strip())
                for line in lines
                if str(line or "").strip() and not str(line or "").startswith("[Info] Starting repository")
            ]
            details = visible[-20:]
        combined_output = "\n".join(str(line or "") for line in lines)
        interrupted = status != "success" and is_ssh_connection_interruption(combined_output)
        return {
            "action": action_key,
            "mode": state.mode,
            "status": status,
            "started_at": started_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "finished_at": finished_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "duration_seconds": max(0, math.ceil((finished_at - started_at).total_seconds())),
            "exit_code": exit_code,
            "deleted_archives_count": len(deleted_archives),
            "deleted_archives": deleted_archives[:50],
            "freed_space": freed_space,
            "details": details,
            "error_category": "network" if interrupted else "",
            "failure_code": SSH_INTERRUPTION_CODE if interrupted else "",
            "failure_hint": SSH_INTERRUPTION_MESSAGE if interrupted else "",
        }

    @classmethod
    def _persist_repository_result(cls, state: _CheckState) -> dict:
        from repositories_api import read_repository_store, write_repository_store

        result = cls._maintenance_result(state)
        repository_key = str(state.target_key or "").strip()
        store = read_repository_store(state.config)
        updated_rows = []
        found = False
        for row in store.get("repositories", []):
            if str(row.get("repository_key") or "") != repository_key:
                updated_rows.append(row)
                continue
            found = True
            maintenance = row.get("maintenance_results") if isinstance(row.get("maintenance_results"), dict) else {}
            maintenance = {**maintenance, str(result["action"]): result}
            updated = {**row, "maintenance_results": maintenance, "updated_at": result["finished_at"]}
            if result["action"] in {"check", "verify_data"}:
                updated["last_check_status"] = result["status"]
            updated_rows.append(updated)
        if not found:
            raise ValueError("Repository object was not found while saving maintenance result")
        write_repository_store(state.config, {"repositories": updated_rows})
        return result

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
            "target_key": state.target_key,
            "action": state.action,
            "mode": state.mode,
            "start_time": state.start_time.isoformat(),
            "result": state.result,
        }

    def stream_output(self) -> Generator[str, None, None]:
        with self._lock:
            state = self._state
        if state is None:
            yield "event: error\ndata: No check was started\n\n"
            return

        yield ": heartbeat\n\n"
        last_heartbeat = time.monotonic()
        while True:
            _, finished, exit_code = state.snapshot()
            if finished:
                yield f"event: done\ndata: {exit_code if exit_code is not None else '?'}\n\n"
                return
            if time.monotonic() - last_heartbeat >= 10:
                yield ": heartbeat\n\n"
                last_heartbeat = time.monotonic()
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
