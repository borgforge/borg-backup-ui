"""RAM-backed activity logs, retained only after the backup process exits (#463)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CAPTURE_ROOT = Path("/run/borg-backup-ui/activity-logs")


def file_identity(info) -> str:
    return f"{info.st_dev}:{info.st_ino}"


def read_record(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        required = ("job_id", "run_id", "active_file", "retained_file", "active_file_id", "started_at")
        if not isinstance(data, dict) or any(not isinstance(data.get(key), str) or not data[key] for key in required):
            return {}
        from job_model import validate_job_id
        from job_runs import validate_run_id
        validate_job_id(data["job_id"])
        validate_run_id(data["run_id"])
        return data if data.get("status") in {"running", "saved", "failed"} else {}
    except (OSError, ValueError):
        return {}


def write_record(path: Path, data: dict) -> None:
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
            json.dump(data, handle)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def capture_record(job_id: str, run_id: str) -> dict:
    from activity_log import activity_log_path

    activity_log_path(CAPTURE_ROOT, job_id, run_id)  # Validate both components.
    record = read_record(CAPTURE_ROOT / run_id / "capture.json")
    if record.get("job_id") != job_id or record.get("run_id") != run_id:
        return {}
    return record


def capture_path(record: dict) -> Path:
    return Path(record["retained_file"] if record.get("status") == "saved" else record["active_file"])


def open_capture_file(record_path: Path):
    from activity_log import open_activity_file

    for attempt in range(2):
        try:
            return open_activity_file(capture_path(read_record(record_path)))
        except FileNotFoundError:
            if attempt:
                raise


def prepare_capture(job_id: str, run_id: str, destination: Path, *, name: str = "job") -> tuple[Path, Path]:
    from activity_log import activity_log_path

    retained = activity_log_path(destination, job_id, run_id, name)
    active = activity_log_path(CAPTURE_ROOT / run_id, job_id, run_id, name)
    active.parent.mkdir(parents=True, mode=0o700)
    with os.fdopen(os.open(active, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        identity = file_identity(os.fstat(handle.fileno()))
    record_path = active.parent / "capture.json"
    write_record(record_path, {
        "job_id": job_id, "run_id": run_id, "job_name_snapshot": name, "status": "running",
        "active_file": str(active), "retained_file": str(retained),
        "active_file_id": identity, "started_at": datetime.now(timezone.utc).isoformat(),
    })
    return active, record_path


def retain_capture(record_path: Path, exit_code: int) -> bool:
    """Copy in bounded blocks, then release RAM. Never replace an existing log."""
    from activity_log import open_activity_file

    record = read_record(record_path)
    active, retained = Path(record["active_file"]), Path(record["retained_file"])
    created = False
    try:
        retained.parent.mkdir(parents=True, exist_ok=True)
        with open_activity_file(active) as source:
            with os.fdopen(os.open(retained, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as target:
                created = True
                shutil.copyfileobj(source, target, length=65536)
                target.flush()
                os.fsync(target.fileno())
                identity = file_identity(os.fstat(target.fileno()))
        # Publish the new location before unlinking the RAM file. Readers with
        # an already-open descriptor can finish; new readers retry the location.
        record.update(status="saved", exit_code=exit_code, retained_file_id=identity)
        write_record(record_path, record)
    except OSError as exc:
        if created:
            try:
                retained.unlink(missing_ok=True)
            except OSError:
                pass
        record.update(status="failed", exit_code=exit_code, persistence_error=type(exc).__name__)
        write_record(record_path, record)
        return False
    try:
        active.unlink()
    except OSError:
        # The complete persistent copy already exists; do not invalidate it.
        pass
    return True


def process_token(pid: int) -> str:
    # A stale capture must not become active again when Linux reuses its PID.
    if pid <= 0:
        return ""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
        return fields[19] if fields[0] != "Z" else ""
    except (OSError, IndexError):
        return ""


def running_captures() -> list[dict]:
    """Recover the short final-copy phase even after the runner released locks."""
    rows = []
    for path in CAPTURE_ROOT.glob("*/capture.json"):
        record = read_record(path)
        if record.get("status") != "running" or not record.get("pid"):
            continue
        try:
            if not record.get("process_start") or process_token(int(record["pid"])) != record["process_start"]:
                continue
        except (TypeError, ValueError):
            continue
        rows.append({
            "job_id": record["job_id"], "run_id": record["run_id"],
            "running": True, "exit_code": None, "file_activity": True,
            "log_file": record["active_file"], "pid": record["pid"],
            "start_time": record["started_at"], "source": "activity_capture",
        })
    return rows


def supervise(record_path: Path, command: list[str]) -> int:
    # This small process owns persistence independently of the WebUI process.
    # The runner and Borg inherit stdout/stderr pointing directly at the RAM
    # file, so browser speed cannot block them and no Python log list grows.
    record = read_record(record_path)
    record["pid"] = os.getpid()
    record["process_start"] = process_token(os.getpid())
    write_record(record_path, record)
    try:
        process = subprocess.Popen(command)
        code = process.wait()
        code = code if code >= 0 else 128 - code
    except OSError as exc:
        print(f"ERROR: Could not start backup runner ({type(exc).__name__})", flush=True)
        code = 2
    sys.stdout.flush()
    sys.stderr.flush()
    retain_capture(record_path, code)
    return code


if __name__ == "__main__":
    sys.exit(supervise(Path(sys.argv[1]), sys.argv[2:]))
