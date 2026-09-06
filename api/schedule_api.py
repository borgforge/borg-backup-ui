"""Verified UUID schedules and managed cron installation (#447, #474).

The singleton restore_test service remains separate from backup job identities.
Legacy schedule conversion belongs exclusively to the explicit migration.
"""

from copy import deepcopy
import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import List

from inventory_store import inventory_lock
from job_model import JobValidationError, validate_job_id
from job_store import read_jobs, read_json, write_transaction

_CRON_BEGIN = "# --- BORG-BACKUP-UI BEGIN ---"
_CRON_END = "# --- BORG-BACKUP-UI END ---"


def _schedules_path(config: dict) -> Path:
    from jobs_api import resolve_data_root
    return resolve_data_root(config) / "config" / "schedules.json"


def validate_schedules(schedules, jobs):
    if not isinstance(schedules, dict):
        raise JobValidationError("invalid_job_schedule", "Schedules must be an object")
    for job_id, entry in schedules.items():
        if job_id != "restore_test":
            validate_job_id(job_id)
            if job_id not in jobs:
                raise JobValidationError("dangling_job_schedule", f"Schedule references an unknown job_id: {job_id}")
        if not isinstance(entry, dict) or type(entry.get("enabled")) is not bool or not isinstance(entry.get("cron"), str):
            raise JobValidationError("invalid_job_schedule", "A schedule requires a cron string and boolean enabled state")
        if entry["cron"] or entry["enabled"]:
            _validate_cron(entry["cron"])
    return schedules


def get_schedules(config: dict) -> dict:
    path = _schedules_path(config)
    with inventory_lock(path.parent):
        return validate_schedules(read_json(path, missing={}), read_jobs(path.parent / "jobs"))


def validate_schedule_job_id(config: dict, job_id: str) -> str:
    if job_id == "restore_test":
        return job_id
    validate_job_id(job_id)
    if job_id not in read_jobs(_schedules_path(config).parent / "jobs"):
        raise JobValidationError("unknown_job_id", "Unknown schedule job_id")
    return job_id


def schedule_lines(config, schedules, jobs):
    # Verify the entire map (including disabled entries) before invoking cron.
    validate_schedules(schedules, jobs)
    port = _validate_port(config.get("PORT", "8765"))
    token_file = str(_schedules_path(config).parent / ".api-token")
    lines = []
    for job_id, entry in schedules.items():
        if not entry["enabled"] or (job_id != "restore_test" and not jobs[job_id].get("enabled", True)):
            continue
        if job_id == "restore_test":
            url = f"http://127.0.0.1:{port}/api/restore-tests/run"
            body = {"scheduled": True}
        else:
            url = f"http://127.0.0.1:{port}/api/jobs/run"
            body = {"job_id": job_id, "scheduled": True}
        command = _build_schedule_command(url, json.dumps(body, separators=(",", ":")), token_file)
        if any(char in command for char in ("\n", "\r", "\x00")):
            raise ValueError("Schedule paths must not contain control characters")
        # Cron interprets percent signs before handing the command to the shell.
        command = command.replace("%", "\\%")
        lines.append(f"{entry['cron']} {command} >/dev/null 2>&1")
    return lines


def _change_schedule(config, job_id, update):
    path = _schedules_path(config)
    with inventory_lock(path.parent):
        validate_schedule_job_id(config, job_id)
        jobs = read_jobs(path.parent / "jobs")
        before = get_schedules(config)
        after = deepcopy(before)
        update(after)
        old_lines = schedule_lines(config, before, jobs)
        new_lines = schedule_lines(config, after, jobs)
        result = write_transaction({path: after},
            after_write=lambda: _update_crontab(new_lines),
            rollback_after=lambda: _update_crontab(old_lines))
        return {"applied": True, "apply_result": result}


def save_schedule(config: dict, job_id: str, cron: str, enabled: bool) -> dict:
    def update(schedules):
        schedules[job_id] = {**schedules.get(job_id, {}), "cron": cron, "enabled": enabled}
    return {"saved": True, **_change_schedule(config, job_id, update)}


def delete_schedule(config: dict, job_id: str) -> dict:
    return {"deleted": True, **_change_schedule(config, job_id, lambda schedules: schedules.pop(job_id, None))}


def write_schedules(config: dict, schedules: dict) -> None:
    path = _schedules_path(config)
    with inventory_lock(path.parent):
        validate_schedules(schedules, read_jobs(path.parent / "jobs"))
        write_transaction({path: schedules})


def apply_all_schedules(config: dict) -> dict:
    path = _schedules_path(config)
    with inventory_lock(path.parent):
        jobs = read_jobs(path.parent / "jobs")
        return _update_crontab(schedule_lines(config, get_schedules(config), jobs))


def _update_crontab(lines: List[str]) -> dict:
    # Bestehenden Crontab lesen
    result = subprocess.run(
        ["crontab", "-l"],
        capture_output=True, text=True, timeout=10
    )
    # Exitcode 1 ohne Ausgabe = leerer Crontab (kein Fehler)
    if result.returncode not in (0, 1):
        detail = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
        raise RuntimeError(f"Could not read crontab: {detail}")
    existing = result.stdout if result.returncode == 0 else ""

    before, after = _split_crontab(existing)

    parts: List[str] = []
    if before.strip():
        parts.append(before.rstrip("\n"))
    if lines:
        parts.append(_CRON_BEGIN + "\n" + "\n".join(lines) + "\n" + _CRON_END)
    after_stripped = after.strip("\n")
    if after_stripped:
        parts.append(after_stripped)

    combined = "\n\n".join(parts) + "\n" if parts else ""

    # Via `crontab -` installieren — zuverlässiger als direktes Schreiben
    try:
        proc = subprocess.run(
            ["crontab", "-"],
            input=combined,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Could not update crontab: command timed out") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not update crontab: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"Could not update crontab: {detail}")
    return {"line_count": len(lines), "changed": combined != existing}


def _split_crontab(text: str):
    b = text.find(_CRON_BEGIN)
    e = text.find(_CRON_END)
    if b == -1 and e == -1:
        return text, ""
    if b == -1 or e < b or text.count(_CRON_BEGIN) != 1 or text.count(_CRON_END) != 1:
        raise RuntimeError("Managed crontab markers are malformed; crontab was not changed")
    return text[:b], text[e + len(_CRON_END):]


def _validate_cron(expr: str) -> None:
    if not isinstance(expr, str) or any(char in expr for char in ("\n", "\r", "\x00")):
        raise ValueError("Cron must be a single line")
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Cron requires exactly 5 fields (found: {len(parts)})")
    for p in parts:
        if not re.fullmatch(r'[\d\*/,\-]+', p):
            raise ValueError(f"Invalid cron field: {p!r}")


def _validate_port(raw: str) -> int:
    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError("Invalid UI port")
    if port < 1 or port > 65535:
        raise ValueError("Invalid UI port")
    return port


def _build_schedule_command(url: str, body: str, token_file: str) -> str:
    script = (
        f"token_file={shlex.quote(token_file)}; "
        f"token=$(cat \"$token_file\" 2>/dev/null); "
        f"exec curl -s -X POST {shlex.quote(url)} "
        f"-H \"X-API-Token: $token\" "
        f"-H {shlex.quote('Content-Type: application/json')} "
        f"--data-binary {shlex.quote(body)}"
    )
    return f"/bin/sh -c {shlex.quote(script)}"
