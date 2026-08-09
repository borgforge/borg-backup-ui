"""Precomputed status cache for the Unraid dashboard tile.

The Unraid dashboard page reads only the JSON cache written by this module.
It must not call Borg, probe repositories, or read array-backed status files
from PHP. The Python app updates the cache while it is already handling normal
status data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from inventory_store import atomic_write_json


SCHEMA_VERSION = 1
DEFAULT_CACHE_PATH = "/boot/config/plugins/borg-backup-ui/widget-status.json"


def widget_cache_path(config: dict) -> Path:
    raw = str(config.get("UNRAID_DASHBOARD_WIDGET_FILE") or "").strip()
    if raw:
        return Path(raw)
    plugin_dir = str(config.get("PLUGIN_DIR") or "").strip()
    if plugin_dir:
        return Path(plugin_dir) / "widget-status.json"
    return Path(DEFAULT_CACHE_PATH)


def write_unraid_dashboard_widget_cache(
    config: dict,
    status_data: dict[str, Any],
    *,
    app_version: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = build_unraid_dashboard_widget_cache(
        config,
        status_data,
        app_version=app_version,
        now=now,
    )
    atomic_write_json(widget_cache_path(config), payload, mode=0o600)
    return payload


def build_unraid_dashboard_widget_cache(
    config: dict,
    status_data: dict[str, Any],
    *,
    app_version: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    generated = now or datetime.now(timezone.utc)
    backups = [row for row in status_data.get("backups", []) if isinstance(row, dict)]
    summary = status_data.get("summary") if isinstance(status_data.get("summary"), dict) else {}
    jobs = _read_jobs(config, backups)
    enabled_jobs = [job for job in jobs if job.get("enabled", True) and not job.get("is_utility")]
    running_jobs = [job for job in enabled_jobs if job.get("running")]
    restore = _restore_proof_summary(enabled_jobs)
    repositories = _repository_summary(config)

    failed = _as_int(summary.get("error"))
    warnings = _as_int(summary.get("warning")) + _as_int(summary.get("skipped"))
    if failed:
        state = "error"
        label = "Fehler"
    elif warnings or restore["failed"] or restore["overdue"]:
        state = "warning"
        label = "Warnung"
    elif running_jobs:
        state = "running"
        label = "Laeuft"
    elif not enabled_jobs:
        state = "unknown"
        label = "Keine Jobs"
    else:
        state = "ok"
        label = "OK"

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _format_iso(generated),
        "app_version": str(app_version or ""),
        "status": {"state": state, "label": label},
        "jobs": {
            "total": len(jobs),
            "enabled": len(enabled_jobs),
            "successful": _as_int(summary.get("success")),
            "warnings": warnings,
            "failed": failed,
            "running": len(running_jobs),
        },
        "repositories": repositories,
        "latest_backup": _latest_backup(backups, jobs),
        "next_backups": _next_backups(config, enabled_jobs, generated),
        "restore_proof": restore,
    }


def _read_jobs(config: dict, backups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = {}
    for row in backups:
        key = str(row.get("key") or "").strip()
        if key:
            latest[key] = row
            latest.setdefault(key.lower(), row)
    try:
        from jobs_api import list_jobs

        return [row for row in list_jobs(config, latest) if isinstance(row, dict)]
    except Exception:
        return [
            {
                "key": str(row.get("key") or "").strip(),
                "display_name": _display_job_name(row),
                "name": _display_job_name(row),
                "enabled": True,
                "running": False,
                "restore_verification_status": row.get("restore_verification_status") or "never",
                "restore_verification_is_overdue": bool(row.get("restore_verification_is_overdue", False)),
            }
            for row in backups
            if str(row.get("key") or "").strip()
        ]


def _repository_summary(config: dict) -> dict[str, int]:
    try:
        from repositories_api import get_repository_info_refresh_status

        status = get_repository_info_refresh_status(config)
        counts = status.get("counts") if isinstance(status.get("counts"), dict) else {}
        total = _as_int(status.get("repository_count"))
        online = _as_int(counts.get("success"))
        return {"online": online, "total": total}
    except Exception:
        return {"online": 0, "total": 0}


def _restore_proof_summary(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    configured = 0
    verified = 0
    failed = 0
    overdue = 0
    open_count = 0
    for job in jobs:
        status = str(job.get("restore_verification_status") or "never").strip().lower()
        if status == "not_required":
            continue
        configured += 1
        if status == "verified":
            verified += 1
        elif status == "failed":
            failed += 1
        elif status in {"never", ""}:
            open_count += 1
        if status == "stale" or bool(job.get("restore_verification_is_overdue", False)):
            overdue += 1
    if configured:
        label = f"{verified}/{configured} verifiziert"
    else:
        label = "Nicht geplant"
    return {
        "configured": configured,
        "verified": verified,
        "failed": failed,
        "overdue": overdue,
        "open": open_count,
        "label": label,
    }


def _latest_backup(backups: list[dict[str, Any]], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    latest = None
    latest_dt = None
    for row in backups:
        parsed = _parse_datetime(str(row.get("timestamp") or ""))
        if parsed is None:
            continue
        if latest_dt is None or parsed > latest_dt:
            latest = row
            latest_dt = parsed
    if latest is None:
        return {"name": "Noch kein Backup", "detail": "Kein Lauf gefunden", "status": "unknown", "status_label": "-"}

    by_key = {str(job.get("key") or ""): job for job in jobs}
    job = by_key.get(str(latest.get("key") or ""))
    name = str((job or {}).get("display_name") or (job or {}).get("name") or _display_job_name(latest)).strip()
    status = str(latest.get("status") or "unknown").strip().lower()
    return {
        "name": name or "Backup",
        "detail": _latest_backup_detail(latest),
        "status": _normalize_status(status),
        "status_label": _status_label(status),
    }


def _latest_backup_detail(row: dict[str, Any]) -> str:
    parts = []
    time_ago = str(row.get("time_ago") or "").strip()
    duration = str(row.get("duration_formatted") or "").strip()
    if time_ago:
        parts.append(time_ago)
    if duration:
        parts.append(f"Dauer {duration}")
    return " - ".join(parts) if parts else "Zeit unbekannt"


def _next_backups(config: dict, jobs: list[dict[str, Any]], now: datetime) -> list[dict[str, str]]:
    try:
        from notification_reminder_api import _next_expected_run
        from schedule_api import get_schedules

        schedules = get_schedules(config)
    except Exception:
        return []
    rows: list[tuple[datetime, dict[str, str]]] = []
    local_now = now.astimezone().replace(tzinfo=None) if now.tzinfo else now
    for job in jobs:
        key = str(job.get("key") or "").strip()
        schedule = schedules.get(key) if isinstance(schedules, dict) else None
        if not key or not isinstance(schedule, dict) or not bool(schedule.get("enabled", True)):
            continue
        next_run = _next_expected_run(str(schedule.get("cron") or ""), local_now)
        if next_run is None:
            continue
        rows.append((next_run, {
            "name": str(job.get("display_name") or job.get("name") or key).strip(),
            "time": _format_short_datetime(next_run, local_now),
        }))
    rows.sort(key=lambda item: item[0])
    return [row for _dt, row in rows[:2]]


def _display_job_name(row: dict[str, Any]) -> str:
    name = str(row.get("name") or row.get("backup_type") or row.get("key") or "Backup").strip()
    location = str(row.get("location") or "").strip()
    return f"{name} - {location.upper()}" if location else name


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y, %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _format_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_short_datetime(value: datetime, now: datetime) -> str:
    prefix = ""
    if value.date() == now.date():
        prefix = "Heute "
    elif value.date() == now.date() + timedelta(days=1):
        prefix = "Morgen "
    else:
        prefix = value.strftime("%d.%m. ")
    return f"{prefix}{value.strftime('%H:%M')}"


def _normalize_status(status: str) -> str:
    value = str(status or "").lower()
    if value == "success":
        return "ok"
    if value in {"warning", "cancelled", "skipped"}:
        return "warning"
    if value in {"error", "failed", "failure"}:
        return "error"
    return "unknown"


def _status_label(status: str) -> str:
    normalized = _normalize_status(status)
    return {
        "ok": "OK",
        "warning": "Warnung",
        "error": "Fehler",
    }.get(normalized, "-")


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
