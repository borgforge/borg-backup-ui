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


def write_unraid_dashboard_widget_startup_cache(
    config: dict,
    *,
    app_version: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write a lightweight widget cache at service start.

    This intentionally avoids reading backup status files. If the configured
    data root lives on /mnt, static job and repository metadata are skipped as
    well so the dashboard tile does not wake array disks during boot.
    """
    payload = build_unraid_dashboard_widget_startup_cache(
        config,
        app_version=app_version,
        now=now,
    )
    atomic_write_json(widget_cache_path(config), payload, mode=0o600)
    return payload


def write_unraid_dashboard_widget_status_file_cache(
    config: dict,
    *,
    app_version: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write a fresh widget cache from existing status files only.

    This is used by the service-start background refresher. It deliberately
    avoids Borg calls and the full dashboard status API snapshot writer, but it
    still applies the same schedule-overdue classification as the UI dashboard.
    Otherwise a widget refresh could overwrite a warning cache with stale OK
    counts while the in-app dashboard still shows the job as overdue.
    """
    status_data = _read_status_file_data(config)
    _apply_status_file_overdue_metadata(config, status_data, now=now)
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
    elif warnings or restore["failed"] or restore["overdue"]:
        state = "warning"
    elif running_jobs:
        state = "running"
    elif not enabled_jobs:
        state = "unknown"
    else:
        state = "ok"

    return {
        "schema_version": SCHEMA_VERSION,
        "cache_state": "fresh",
        "generated_at": _format_iso(generated),
        "app_version": str(app_version or ""),
        "status": {"state": state},
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


def build_unraid_dashboard_widget_startup_cache(
    config: dict,
    *,
    app_version: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    generated = now or datetime.now(timezone.utc)
    jobs = _read_static_jobs(config)
    enabled_jobs = [job for job in jobs if job.get("enabled", True) and not job.get("is_utility")]

    return {
        "schema_version": SCHEMA_VERSION,
        "cache_state": "initial",
        "generated_at": _format_iso(generated),
        "app_version": str(app_version or ""),
        "status": {"state": "unknown"},
        "jobs": {
            "total": len(jobs),
            "enabled": len(enabled_jobs),
            "successful": 0,
            "warnings": 0,
            "failed": 0,
            "running": 0,
        },
        "repositories": _repository_summary(config, skip_if_array_root=True) if jobs else {"online": 0, "total": 0},
        "latest_backup": {
            "name": "",
            "detail": "",
            "status": "unknown",
        },
        "next_backups": _next_backups(config, enabled_jobs, generated),
        "restore_proof": {
            "configured": 0,
            "verified": 0,
            "failed": 0,
            "overdue": 0,
            "open": 0,
        },
    }


def _read_status_file_data(config: dict) -> dict[str, Any]:
    try:
        from status import StatusStore, format_duration, time_ago

        status_dir = Path(str(config.get("STATUS_DIR") or ""))
        store = StatusStore(status_dir)
        latest = store.get_latest_per_key(store.load())
    except Exception:
        latest = {}

    backups: list[dict[str, Any]] = []
    for key, st in sorted(latest.items()):
        backups.append({
            "key": str(key),
            "backup_type": st.backup_type,
            "location": st.location,
            "status": st.status,
            "timestamp": st.timestamp,
            "time_ago": time_ago(st.timestamp) if st.timestamp else "",
            "duration_seconds": st.duration_seconds,
            "duration_formatted": format_duration(st.duration_seconds),
            "exit_code": st.exit_code,
            "failure_code": getattr(st, "failure_code", "") or "",
            "missing_source_paths": list(getattr(st, "missing_source_paths", []) or []),
            "error_message": st.error_message or "",
            "skip_reason_code": getattr(st, "skip_reason_code", "") or "",
            "skip_reason_text": getattr(st, "skip_reason_text", "") or "",
            "archive_name": st.archive_name or "",
            "repository_check_status": st.repository_check_status,
            "repository_check_date": st.repository_check_date or "",
            "repository_next_check": st.repository_next_check or "",
        })

    return {
        "backups": backups,
        "summary": {
            "total": len(backups),
            "success": sum(1 for row in backups if row["status"] == "success"),
            "warning": sum(1 for row in backups if row["status"] in {"warning", "cancelled"}),
            "skipped": sum(1 for row in backups if row["status"] == "skipped"),
            "error": sum(1 for row in backups if row["status"] == "error"),
        },
        "snapshots": {},
    }


def _apply_status_file_overdue_metadata(
    config: dict,
    status_data: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    backups = status_data.get("backups")
    if not isinstance(backups, list):
        return
    rows = [row for row in backups if isinstance(row, dict)]
    try:
        from status_api import _apply_backup_overdue_metadata

        local_now = now
        if local_now is not None and local_now.tzinfo is not None:
            local_now = local_now.astimezone().replace(tzinfo=None)
        _apply_backup_overdue_metadata(config, rows, now=local_now)
    except Exception:
        return

    status_data["summary"] = {
        "total": len(rows),
        "success": sum(1 for row in rows if row.get("status") == "success" and not bool(row.get("backup_overdue"))),
        "warning": sum(1 for row in rows if row.get("status") in {"warning", "cancelled"} or bool(row.get("backup_overdue"))),
        "skipped": sum(1 for row in rows if row.get("status") == "skipped"),
        "error": sum(1 for row in rows if row.get("status") == "error"),
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


def _read_static_jobs(config: dict) -> list[dict[str, Any]]:
    try:
        from jobs_api import discover_jobs, resolve_data_root, resolve_scripts_dir

        data_root = resolve_data_root(config)
        if _path_may_wake_disks(data_root):
            return []
        scripts_dir = resolve_scripts_dir(config)
        if _path_may_wake_disks(scripts_dir):
            return []
        jobs = []
        for info in discover_jobs(scripts_dir, data_root):
            jobs.append({
                "key": info.key,
                "display_name": info.name or info.display_name,
                "name": info.name or info.display_name,
                "enabled": info.enabled,
                "running": False,
                "is_utility": info.is_utility,
            })
        return jobs
    except Exception:
        return []


def _path_may_wake_disks(path: Path) -> bool:
    text = str(path)
    return text == "/mnt" or text.startswith("/mnt/")


def _repository_summary(config: dict, *, skip_if_array_root: bool = False) -> dict[str, int]:
    if skip_if_array_root:
        try:
            from jobs_api import resolve_data_root

            if _path_may_wake_disks(resolve_data_root(config)):
                return {"online": 0, "total": 0}
        except Exception:
            pass
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
    return {
        "configured": configured,
        "verified": verified,
        "failed": failed,
        "overdue": overdue,
        "open": open_count,
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
        return {"name": "No backup", "detail": "No run found", "status": "unknown"}

    by_key = {str(job.get("key") or ""): job for job in jobs}
    job = by_key.get(str(latest.get("key") or ""))
    name = str((job or {}).get("display_name") or (job or {}).get("name") or _display_job_name(latest)).strip()
    status = str(latest.get("status") or "unknown").strip().lower()
    return {
        "name": name or "Backup",
        "detail": _latest_backup_detail(latest),
        "status": _normalize_status(status),
    }


def _latest_backup_detail(row: dict[str, Any]) -> str:
    parts = []
    time_ago = str(row.get("time_ago") or "").strip()
    duration = str(row.get("duration_formatted") or "").strip()
    if time_ago:
        parts.append(time_ago)
    if duration:
        parts.append(f"Duration {duration}")
    return " - ".join(parts) if parts else "Time unknown"


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
        prefix = "Today "
    elif value.date() == now.date() + timedelta(days=1):
        prefix = "Tomorrow "
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


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
