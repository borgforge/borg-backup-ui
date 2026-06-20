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
import subprocess
from pathlib import Path
from typing import List


_CRON_BEGIN = "# --- BORG-BACKUP-UI BEGIN ---"
_CRON_END   = "# --- BORG-BACKUP-UI END ---"


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


def save_schedule(config: dict, job_key: str, cron: str, enabled: bool) -> None:
    _validate_cron(cron)
    schedules = get_schedules(config)
    schedules[job_key] = {"cron": cron, "enabled": enabled}
    _write_schedules(config, schedules)
    apply_all_schedules(config)


def delete_schedule(config: dict, job_key: str) -> None:
    schedules = get_schedules(config)
    schedules.pop(job_key, None)
    _write_schedules(config, schedules)
    apply_all_schedules(config)


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
    _write_schedules(config, schedules)
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


def _write_schedules(config: dict, schedules: dict) -> None:
    path = _schedules_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schedules, indent=2, ensure_ascii=False), encoding="utf-8")


def apply_all_schedules(config: dict) -> None:
    """Schreibt alle aktiven Schedules in den Crontab (idempotent, sicher bei Fehler)."""
    schedules = get_schedules(config)
    port = config.get("PORT", "8765")
    token_file = str(Path(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")) / "config" / ".api-token")

    lines: List[str] = []
    for job_key, sched in schedules.items():
        if not sched.get("enabled", True):
            continue
        cron = sched["cron"]
        if job_key == "restore_test":
            url  = f"http://127.0.0.1:{port}/api/restore-tests/run"
            body = '{"scheduled":true}'
        else:
            url  = f"http://127.0.0.1:{port}/api/jobs/run"
            body = f'{{\"job_key\":\"{job_key}\"}}'
        line = (
            f'{cron} curl -s -X POST {url} '
            f'-H "X-API-Token: $(cat {token_file} 2>/dev/null)" '
            f'-H "Content-Type: application/json" '
            f"-d '{body}' >/dev/null 2>&1"
        )
        lines.append(line)

    _update_crontab(lines)


def _update_crontab(lines: List[str]) -> None:
    # Bestehenden Crontab lesen
    result = subprocess.run(
        ["crontab", "-l"],
        capture_output=True, text=True, timeout=10
    )
    # Exitcode 1 ohne Ausgabe = leerer Crontab (kein Fehler)
    if result.returncode not in (0, 1):
        return
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
        subprocess.run(
            ["crontab", "-"],
            input=combined, text=True, timeout=10, check=True
        )
    except (subprocess.SubprocessError, OSError):
        pass


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
        if not re.match(r'^[\d\*/,\-]+$', p):
            raise ValueError(f"Invalid cron field: {p!r}")
