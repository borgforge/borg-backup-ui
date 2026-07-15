"""Read-only summary data for external Homepage dashboard widgets.

The widget deliberately reads canonical local state only. It must never invoke
Borg, probe a repository, run a migration, or expose paths and error details.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _data_root(config: dict) -> Path:
    base = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    return base.parent if base.name == "scripts" else base


def _read_jobs(config: dict) -> list[dict]:
    jobs_dir = _data_root(config) / "config" / "jobs"
    rows: list[dict] = []
    if not jobs_dir.is_dir():
        return rows
    for path in sorted(jobs_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("job_key") or path.stem).strip()
        if not key:
            continue
        policy = raw.get("restore_test_policy") if isinstance(raw.get("restore_test_policy"), dict) else {}
        location = str(raw.get("location") or "").strip().lower()
        name = str(raw.get("name") or raw.get("backup_type") or key).strip()
        location_label = {
            "local": "Local",
            "usb": "USB",
            "smb": "SMB",
            "storagebox": "Storagebox",
        }.get(location, location.title())
        rows.append({
            "key": key,
            "name": name,
            "display_name": f"{name} - {location_label}" if location_label else name,
            "location": location,
            "enabled": bool(raw.get("enabled", True)),
            "is_utility": bool(raw.get("is_utility", False)),
            "restore_test_policy": policy,
        })
    return rows


def _read_latest_backup_rows(config: dict) -> list[dict]:
    from status import StatusStore

    status_dir = Path(str(config.get("STATUS_DIR") or "/mnt/user/backup-status"))
    store = StatusStore(status_dir)
    latest = store.get_latest_per_key(store.load())
    rows: list[dict] = []
    for key, status in latest.items():
        rows.append({
            "key": str(key),
            "backup_type": str(getattr(status, "backup_type", "") or ""),
            "location": str(getattr(status, "location", "") or ""),
            "status": str(getattr(status, "status", "") or "").strip().lower(),
            "timestamp": str(getattr(status, "timestamp", "") or ""),
        })
    return rows


def _backup_overdue_count(config: dict, jobs: list[dict], latest_rows: list[dict], now: datetime) -> int:
    from config_api import read_expanded_conf
    from notification_reminder_api import (
        _backup_overdue_item,
        _backup_overdue_tolerance_hours,
        _latest_backup_status_by_key,
    )
    from schedule_api import get_schedules

    effective = {**config, **read_expanded_conf(config)}
    schedules = get_schedules(effective)
    latest = _latest_backup_status_by_key(latest_rows)
    by_key = {str(row.get("key") or ""): row for row in jobs}
    tolerance = _backup_overdue_tolerance_hours(effective)
    count = 0
    for job_key, schedule in schedules.items():
        if job_key == "restore_test" or not isinstance(schedule, dict) or not bool(schedule.get("enabled", True)):
            continue
        job = by_key.get(str(job_key))
        if not job or not job.get("enabled", True):
            continue
        item = _backup_overdue_item(
            str(job_key), schedule, job, latest.get(str(job_key)) or {}, {}, now, 24, tolerance
        )
        if str(item.get("state") or "").startswith("overdue_"):
            count += 1
    return count


def _restore_summary(config: dict, jobs: list[dict]) -> dict[str, int]:
    from config_api import read_expanded_conf
    from restore_tests_api import build_restore_verification_map

    effective = {**config, **read_expanded_conf(config)}
    verification = build_restore_verification_map(effective, jobs)
    configured = 0
    verified = 0
    failed = 0
    overdue = 0
    never = 0
    for item in verification.values():
        if not isinstance(item, dict) or item.get("status") == "not_required":
            continue
        configured += 1
        state = str(item.get("status") or "")
        if state == "verified":
            verified += 1
        elif state == "failed":
            failed += 1
        elif state == "never":
            never += 1
        if state == "stale" or bool(item.get("is_overdue", False)):
            overdue += 1
    return {
        "configured": configured,
        "verified": verified,
        "failed": failed,
        "overdue": overdue,
        "never": never,
    }


def build_homepage_widget_summary(config: dict, *, now: datetime | None = None) -> dict[str, Any]:
    """Build a stable, redacted and side-effect-free widget response."""
    from jobs_api import get_all_runtime_states

    generated = now or datetime.now(timezone.utc)
    local_now = generated.astimezone().replace(tzinfo=None) if generated.tzinfo else generated
    jobs = [row for row in _read_jobs(config) if not row.get("is_utility")]
    enabled_jobs = [row for row in jobs if row.get("enabled", True)]
    latest_rows = _read_latest_backup_rows(config)
    latest_by_key = {str(row.get("key") or ""): row for row in latest_rows}

    counts = {"successful": 0, "warning": 0, "failed": 0, "skipped": 0, "never": 0}
    for job in enabled_jobs:
        status = str((latest_by_key.get(str(job.get("key") or "")) or {}).get("status") or "").lower()
        if status == "success":
            counts["successful"] += 1
        elif status == "warning":
            counts["warning"] += 1
        elif status in {"error", "failed", "failure"}:
            counts["failed"] += 1
        elif status == "skipped":
            counts["skipped"] += 1
        else:
            counts["never"] += 1

    counts["overdue"] = _backup_overdue_count(config, enabled_jobs, latest_rows, local_now)
    restore = _restore_summary(config, enabled_jobs)

    by_key = {str(row.get("key") or ""): row for row in enabled_jobs}
    running_states = get_all_runtime_states(config)
    active_jobs = [
        str(by_key[key].get("display_name") or by_key[key].get("name") or key)
        for key, state in sorted(running_states.items())
        if key in by_key and isinstance(state, dict) and bool(state.get("running", False))
    ]

    critical = counts["failed"] + restore["failed"]
    attention = (
        counts["warning"] + counts["skipped"] + counts["never"] + counts["overdue"]
        + restore["overdue"] + restore["never"]
    )
    if critical:
        state, label, severity = "critical", "Critical", 3
    elif attention:
        state, label, severity = "attention", "Attention required", 2
    elif active_jobs:
        state, label, severity = "active", "Backup running", 1
    else:
        state, label, severity = "healthy", "Healthy", 0

    enabled_count = len(enabled_jobs)
    restore_display = (
        f"{restore['verified']}/{restore['configured']} verified"
        if restore["configured"] else "Not configured"
    )
    return {
        "schema_version": 1,
        "generated_at": generated.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if generated.tzinfo else generated.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": {"state": state, "label": label, "severity": severity},
        "display": {
            "backups": f"{counts['successful']}/{enabled_count} successful",
            "restore_tests": restore_display,
            "attention": str(critical + attention),
            "active": ", ".join(active_jobs) if active_jobs else "None",
        },
        "backups": {
            "total": len(jobs),
            "enabled": enabled_count,
            "disabled": len(jobs) - enabled_count,
            **counts,
        },
        "restore_tests": restore,
        "active": {"count": len(active_jobs), "jobs": active_jobs},
    }
