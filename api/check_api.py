"""Run and record Borg repository maintenance actions.

Check, data verification, prune, and compact run as subprocesses. Only one
maintenance action may run at a time; the UI consumes SSE only as a completion
signal and presents the persisted structured result.
"""

import subprocess
import sys
import threading
import time
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, List, Optional


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

    def start_repository(
        self,
        config: dict,
        repository_key: str,
        action: str = "check",
        mode: str = "quick",
        *,
        job_id: str = "",
    ) -> tuple:
        """Start a maintenance action for one managed repository object."""
        from migration_barrier import acquire_writer_lease
        lease = acquire_writer_lease(config)
        try:
            with self._lock, lease.activate():
                result = self._start_repository_locked(config, repository_key, action, mode,
                                                       job_id=job_id, lease=lease)
            if not result[0]:
                lease.close()
            return result
        except BaseException:
            lease.close()
            raise

    def _start_repository_locked(self, config, repository_key, action, mode, *, job_id, lease):
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
            # Validate the selected UUID and complete archive scope before a
            # mount or any other operation with external side effects.
            cmd = self._repository_command(config, repository, repo_path, action, mode, job_id=job_id)
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
        state.migration_lease = lease
        state.append_line(f"[Info] Starting repository {action}: {' '.join(cmd[:-1])} {repo_path}")
        self._state = state
        threading.Thread(
            target=self._reader,
            args=(state,),
            daemon=True,
            name=f"borg-{action}-reader",
        ).start()
        return True, None

    def _repository_command(
        self,
        config: dict,
        repository: dict,
        repo_path: str,
        action: str,
        mode: str,
        *,
        job_id: str = "",
    ) -> list[str]:
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

        from job_model import validate_job_id
        from repository_context import jobs_using_repository, load_job_metadata
        ids = jobs_using_repository(config, repository["repository_key"])
        if job_id:
            validate_job_id(job_id)
            if job_id not in ids:
                raise ValueError("The selected retention source job does not use this repository")
        elif len(ids) == 1:
            job_id = ids[0]
        else:
            raise ValueError("Select one backup job as the retention source")
        metadata = load_job_metadata(config, job_id)
        retention = metadata.get("retention", {})
        counts = [int(retention.get(period, "0")) for period in ("daily", "weekly", "monthly", "yearly")]
        if not any(counts):
            raise ValueError("At least one retention value must be greater than zero")
        from job_runs import create_run_context
        from jobs_api import resolve_data_root
        snapshot = create_run_context(config, job_id, require_enabled=False)
        if snapshot["repository_snapshot"] != repo_path or snapshot["repository_key_snapshot"] != repository["repository_key"]:
            raise ValueError("Repository assignment changed during maintenance preparation")
        return [sys.executable, str(Path(__file__).with_name("retention_runner.py")),
                job_id, snapshot["run_id"], str(resolve_data_root(config))]

    def _reader(self, state: _CheckState) -> None:
        lease = getattr(state, "migration_lease", None)
        if lease is None:
            return self._reader_admitted(state)
        try:
            with lease.activate():
                self._reader_admitted(state)
        finally:
            lease.close()

    def _reader_admitted(self, state: _CheckState) -> None:
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
        archive_metadata = (
            r"\s+(?:\S+,\s+)?\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}"
            r"(?:\s*[+-]\d{2}:?\d{2})?\s+\[[0-9a-f]{64}\]"
        )
        log_timestamp = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
        logger_prefix = re.compile(
            r"^(?:(?:\[" + log_timestamp + r"\]|" + log_timestamp + r")\s+(?:INFO\s+)?|INFO\s+)"
        )
        for raw in lines:
            line = str(raw or "").strip()
            # The manual runner adds INFO; backup runners also add a timestamp.
            # Remove only these known prefixes so plan/dry-run text cannot match.
            line = logger_prefix.sub("", line, count=1)
            # Borg logs deletion before it finishes/commits. A failed process
            # cannot confirm which of its announced deletions were persisted.
            archive = ""
            if exit_code == 0:
                legacy = re.match(r"Pruning archive(?:\s*\([^)]*\))?\s*:\s*(.+)$", line, re.IGNORECASE)
                if legacy:
                    payload = legacy.group(1).strip()
                    formatted = re.fullmatch(r"(.+?)" + archive_metadata, payload, re.IGNORECASE)
                    archive = formatted.group(1).strip() if formatted else payload
                else:
                    deleted = re.fullmatch(
                        r"Deleting archive:\s*(.+?)" + archive_metadata + r"\s+\(\d+/\d+\)",
                        line, re.IGNORECASE,
                    )
                    if deleted:
                        archive = deleted.group(1).strip()
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
    from jobs_api import discover_jobs, resolve_data_root, resolve_scripts_dir
    return [{"job_id": job.job_id, "name": f"{job.name} ({job.location})"}
            for job in discover_jobs(resolve_scripts_dir(config), resolve_data_root(config))]
