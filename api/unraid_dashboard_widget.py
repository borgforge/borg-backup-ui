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
STARTUP_IMPORT_KEY = "startup_status_import_v2"


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
    well so the dashboard tile does not wake array disks during boot. A
    previously written fresh cache with job metadata is preserved so the
    dashboard can continue to show the last event-based status after a reboot.
    If no usable fresh cache exists yet, one initial event-style cache is built
    from existing status and restore-test files after runtime storage is ready.
    """
    cache_path = widget_cache_path(config)
    existing = _read_existing_cache(cache_path)
    if _is_usable_fresh_cache(existing):
        return existing
    if _startup_import_attempted(existing):
        return existing
    if _startup_status_scan_configured(config):
        try:
            return write_unraid_dashboard_widget_status_file_cache(
                config,
                app_version=app_version,
                now=now,
                startup_import=True,
            )
        except Exception:
            pass
    payload = build_unraid_dashboard_widget_startup_cache(
        config,
        app_version=app_version,
        now=now,
    )
    _mark_startup_import(payload, "skipped", "status_scan_unavailable")
    atomic_write_json(cache_path, payload, mode=0o600)
    return payload


def write_unraid_dashboard_widget_status_file_cache(
    config: dict,
    *,
    app_version: str = "",
    now: datetime | None = None,
    startup_import: bool = False,
) -> dict[str, Any]:
    """Write a fresh widget cache from existing status files only.

    This is used after backup and restore-test activity, and by explicit UI
    status refreshes that already read the runtime status directory. It
    deliberately avoids Borg calls and the full dashboard status API snapshot
    writer, but it still applies the same schedule-overdue classification as
    the UI dashboard. Otherwise an event cache refresh could overwrite a
    warning cache with stale OK counts while the in-app dashboard still shows
    the job as overdue.
    """
    status_data = _read_status_file_data(config)
    _apply_status_file_overdue_metadata(config, status_data, now=now)
    payload = build_unraid_dashboard_widget_cache(
        config,
        status_data,
        app_version=app_version,
        now=now,
    )
    if startup_import:
        _mark_startup_import(payload, 'applied', 'canonical_status')
    cache_path = widget_cache_path(config)
    atomic_write_json(cache_path, payload, mode=0o600)
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

    jobs = _read_jobs(config, backups)
    backup_rows_by_key = _backup_rows_by_key(backups)
    # Runtime ownership takes precedence until the process actually finishes.
    by_id = {job['job_id']: job for job in jobs}
    backups = [{**job, **backup_rows_by_key.get(job_id, {}),
                'job_id': job_id, 'name': job.get('name'), 'display_name': job.get('display_name'),
                'enabled': job.get('enabled', True), 'running': bool(job.get('running')),
                'status': backup_rows_by_key.get(job_id, {}).get('status', 'unknown'),
                'never_run': backup_rows_by_key.get(job_id, {}).get('never_run', job_id not in backup_rows_by_key)}
               for job_id, job in by_id.items()]
    from status_read_model import summarize
    summary = summarize(backups)
    enabled_jobs = [job for job in jobs if job.get("enabled", True) and not job.get("is_utility")]
    running_jobs = [job for job in enabled_jobs if job.get("running")]
    restore = _restore_proof_summary([row for row in backups if row.get("enabled") is not False])
    repositories = _repository_summary(config)
    job_items = _job_cache_items(enabled_jobs, backup_rows_by_key)

    failed = _as_int(summary.get("error"))
    warnings = _as_int(summary.get("warning")) + _as_int(summary.get("skipped"))
    if failed:
        state = "error"
    elif warnings or restore["failed"] or restore["overdue"]:
        state = "warning"
    elif running_jobs:
        state = "running"
    elif not enabled_jobs or summary["never"] or summary["unknown"]:
        state = "unknown"
    else:
        state = "ok"

    return {
        "schema_version": SCHEMA_VERSION,
        "identity_schema_version": 1,
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
            "never": summary["never"],
            "disabled": summary["disabled"],
            "items": job_items,
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
        "identity_schema_version": 1,
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
            "items": _job_cache_items(enabled_jobs, {}),
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
    from status_api import get_status_data
    return get_status_data(config, write_snapshots=False)


def _backup_rows_by_key(backups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows = {}
    for row in backups:
        key = str(row.get("job_id") or "").strip()
        if key:
            rows[key] = row
    return rows


def _read_existing_cache(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _is_usable_fresh_cache(cache: dict[str, Any] | None) -> bool:
    if not isinstance(cache, dict):
        return False
    if cache.get("identity_schema_version") != 1:
        return False
    if str(cache.get("cache_state") or "").strip().lower() != "fresh":
        return False
    jobs = cache.get("jobs") if isinstance(cache.get("jobs"), dict) else {}
    if not isinstance(jobs.get("items"), list):
        return False
    from status_read_model import valid_job_id
    return (all(isinstance(item, dict) and valid_job_id(item.get('job_id')) for item in jobs['items'])
            and not _has_enabled_jobs_without_backup_status_evidence(cache))


def _startup_import_attempted(cache: dict[str, Any] | None) -> bool:
    if not isinstance(cache, dict):
        return False
    if cache.get("identity_schema_version") != 1:
        return False
    marker = cache.get(STARTUP_IMPORT_KEY)
    return isinstance(marker, dict) and str(marker.get("state") or "").strip() != ""


def _mark_startup_import(payload: dict[str, Any], state: str, reason: str) -> None:
    payload[STARTUP_IMPORT_KEY] = {
        "schema_version": 1,
        "state": str(state or "").strip(),
        "reason": str(reason or "").strip(),
    }


def _has_enabled_jobs_without_backup_status_evidence(cache: dict[str, Any] | None) -> bool:
    if not isinstance(cache, dict):
        return False
    jobs = cache.get("jobs") if isinstance(cache.get("jobs"), dict) else {}
    enabled = _as_int(jobs.get("enabled"))
    items = jobs.get("items") if isinstance(jobs.get("items"), list) else []
    if enabled <= 0 and items:
        enabled = sum(1 for item in items if isinstance(item, dict) and item.get("enabled", True))
    if enabled <= 0:
        return False
    counters = (
        _as_int(jobs.get("successful"))
        + _as_int(jobs.get("warnings"))
        + _as_int(jobs.get("failed"))
    )
    if counters > 0:
        return False
    for item in items:
        if not isinstance(item, dict) or item.get("enabled") is False:
            continue
        if str(item.get("last_status") or "").strip():
            return False
        if str(item.get("last_timestamp") or "").strip():
            return False
    return True


def _startup_status_scan_configured(config: dict) -> bool:
    return bool(str(config.get("STATUS_DIR") or "").strip())


def _job_cache_items(jobs: list[dict[str, Any]], backups_by_key: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for job in jobs:
        key = str(job.get("job_id") or "").strip()
        if not key:
            continue
        latest = backups_by_key.get(key) or {}
        name = str(job.get("display_name") or job.get("name") or key).strip()
        items.append({
            "job_id": key,
            "name": name or key,
            "enabled": bool(job.get("enabled", True)),
            "running": bool(job.get("running", False)),
            "run_id": str(job.get("run_id") or ""),
            "legacy_status": bool(latest.get("legacy_status")),
            "last_status": str(job.get("last_status") or latest.get("status") or "").strip().lower(),
            "last_timestamp": str(job.get("last_timestamp") or latest.get("timestamp") or "").strip(),
            "backup_overdue": bool(latest.get("backup_overdue", False)),
            "backup_overdue_state": str(latest.get("backup_overdue_state") or "").strip(),
            "backup_overdue_after": str(latest.get("backup_overdue_after") or "").strip(),
            "backup_overdue_expected_run": str(latest.get("backup_overdue_expected_run") or "").strip(),
            "backup_overdue_next_run": str(latest.get("backup_overdue_next_run") or "").strip(),
            "restore_verification_status": str(
                latest.get("restore_verification_status")
                or job.get("restore_verification_status")
                or "never"
            ).strip().lower(),
            "restore_verification_valid_until": str(
                latest.get("restore_verification_valid_until")
                or job.get("restore_verification_valid_until")
                or ""
            ).strip(),
            "restore_verification_is_overdue": bool(
                latest.get("restore_verification_is_overdue", job.get("restore_verification_is_overdue", False))
            ),
        })
    return items


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

    from status_read_model import summarize
    status_data['summary'] = summarize(rows)


def _read_jobs(config: dict, backups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from jobs_api import list_jobs
    return list_jobs(config, _backup_rows_by_key(backups))


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
                "job_id": info.job_id,
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
        offline = _as_int(counts.get("error"))
        online = max(0, total - offline)
        return {"online": online, "total": total}
    except Exception:
        return {"online": 0, "total": 0}


def _restore_proof_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    configured = 0
    verified = 0
    failed = 0
    overdue = 0
    open_count = 0
    for row in rows:
        status = str(row.get("restore_verification_status") or "never").strip().lower()
        if status == "not_required":
            continue
        configured += 1
        if status == "verified":
            verified += 1
        elif status == "failed":
            failed += 1
        elif status in {"never", ""}:
            open_count += 1
        if status == "stale" or bool(row.get("restore_verification_is_overdue", False)):
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

    by_key = {str(job.get("job_id") or ""): job for job in jobs}
    job = by_key.get(str(latest.get("job_id") or ""))
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
        key = str(job.get("job_id") or "").strip()
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
    name = str(row.get("name") or row.get("backup_type") or row.get("job_id") or "Backup").strip()
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
