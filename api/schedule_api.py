"""
api/schedule_api.py – Cron-Schedule-Verwaltung für Borg Backup Jobs

schedules.json wird gespeichert unter:
  {BACKUP_SCRIPTS_DIR}/config/schedules.json

Crontab-Einträge werden via `crontab -` installiert (zuverlässiger als
direktes Schreiben der Datei). Abschnitt zwischen BORG-BACKUP-UI Markern.
Option B: curl POST an /api/jobs/run, damit JobManager den Lauf trackt.
"""

import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import List


_CRON_BEGIN = "# --- BORG-BACKUP-UI BEGIN ---"
_CRON_END   = "# --- BORG-BACKUP-UI END ---"
_JOB_KEY_RX = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _schedules_path(config: dict) -> Path:
    base = Path(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup"))
    return base / "config" / "schedules.json"


def get_schedules(config: dict) -> dict:
    path = _schedules_path(config)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def save_schedule(config: dict, job_key: str, cron: str, enabled: bool) -> dict:
    job_key = validate_schedule_job_key(config, job_key)
    _validate_cron(cron)
    schedules = get_schedules(config)
    schedules[job_key] = {"cron": cron, "enabled": enabled}
    write_schedules(config, schedules)
    try:
        apply_result = apply_all_schedules(config)
    except Exception as exc:
        raise RuntimeError(f"Schedule saved but could not be applied to crontab: {exc}") from exc
    return {"saved": True, "applied": True, "apply_result": apply_result}


def delete_schedule(config: dict, job_key: str) -> dict:
    job_key = _validate_job_key_text(job_key)
    schedules = get_schedules(config)
    schedules.pop(job_key, None)
    write_schedules(config, schedules)
    try:
        apply_result = apply_all_schedules(config)
    except Exception as exc:
        raise RuntimeError(f"Schedule deleted but crontab could not be updated: {exc}") from exc
    return {"deleted": True, "applied": True, "apply_result": apply_result}


def prune_orphaned_schedules(config: dict, log_fn=None) -> dict:
    """
    Entfernt verwaiste Schedule-Keys, für die kein Job mehr existiert.
    `restore_test` bleibt als Sonderfall erlaubt.
    """
    from jobs_api import discover_jobs, resolve_data_root, resolve_scripts_dir

    schedules = get_schedules(config)
    if not isinstance(schedules, dict) or not schedules:
        return {"changed": False, "removed_keys": []}

    scripts_dir = resolve_scripts_dir(config)
    data_root = resolve_data_root(config)
    known_keys = {j.key for j in discover_jobs(scripts_dir, data_root)}
    known_keys.add("restore_test")

    removed_keys = [k for k in list(schedules.keys()) if k not in known_keys]
    if not removed_keys:
        return {"changed": False, "removed_keys": []}

    for key in removed_keys:
        schedules.pop(key, None)
    write_schedules(config, schedules, validate_known_jobs=False)
    apply_all_schedules(config)

    removed_sorted = sorted(removed_keys)
    if callable(log_fn):
        try:
            log_fn(
                "AUTO-PRUNE schedules.json: entfernt=%d keys=%s",
                len(removed_sorted),
                ",".join(removed_sorted),
            )
        except TypeError:
            log_fn(
                f"AUTO-PRUNE schedules.json: entfernt={len(removed_sorted)} "
                f"keys={','.join(removed_sorted)}"
            )
    return {"changed": True, "removed_keys": removed_sorted}


def write_schedules(config: dict, schedules: dict, *, validate_known_jobs: bool = True) -> None:
    normalized: dict = {}
    for raw_key, raw_sched in (schedules or {}).items():
        key = validate_schedule_job_key(config, raw_key) if validate_known_jobs else _validate_job_key_text(raw_key)
        if not isinstance(raw_sched, dict):
            continue
        cron = str(raw_sched.get("cron") or "").strip()
        if cron:
            _validate_cron(cron)
        normalized[key] = {"cron": cron, "enabled": bool(raw_sched.get("enabled", True))}
    path = _schedules_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")


def apply_all_schedules(config: dict) -> dict:
    """Schreibt alle aktiven Schedules in den Crontab (idempotent, sicher bei Fehler)."""
    schedules = get_schedules(config)
    port = _validate_port(config.get("PORT", "8765"))
    token_file = str(Path(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")) / "config" / ".api-token")

    lines: List[str] = []
    for job_key, sched in schedules.items():
        job_key = validate_schedule_job_key(config, job_key)
        if not isinstance(sched, dict):
            continue
        if not sched.get("enabled", True):
            continue
        cron = str(sched.get("cron") or "").strip()
        _validate_cron(cron)
        if job_key == "restore_test":
            url  = f"http://127.0.0.1:{port}/api/restore-tests/run"
            body = json.dumps({"scheduled": True}, separators=(",", ":"))
        else:
            url  = f"http://127.0.0.1:{port}/api/jobs/run"
            body = json.dumps({"job_key": job_key}, separators=(",", ":"))
        line = f"{cron} {_build_schedule_command(url, body, token_file)} >/dev/null 2>&1"
        lines.append(line)

    return _update_crontab(lines)


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
    if b == -1 or e == -1:
        return text, ""
    return text[:b], text[e + len(_CRON_END):]


def _validate_cron(expr: str) -> None:
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Cron requires exactly 5 fields (found: {len(parts)})")
    for p in parts:
        if not re.fullmatch(r'[\d\*/,\-]+', p):
            raise ValueError(f"Invalid cron field: {p!r}")


def _validate_job_key_text(job_key: str) -> str:
    key = str(job_key or "").strip()
    if not key or not _JOB_KEY_RX.fullmatch(key):
        raise ValueError("Invalid job key")
    return key


def validate_schedule_job_key(config: dict, job_key: str) -> str:
    key = _validate_job_key_text(job_key)
    if key == "restore_test":
        return key
    if key not in _known_job_keys(config):
        raise ValueError(f"Unknown job key: {key}")
    return key


def _known_job_keys(config: dict) -> set[str]:
    try:
        from jobs_api import discover_jobs, resolve_data_root, resolve_scripts_dir
        scripts_dir = resolve_scripts_dir(config)
        data_root = resolve_data_root(config)
        return {str(j.key).strip() for j in discover_jobs(scripts_dir, data_root) if str(j.key).strip()}
    except Exception:
        return set()


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
