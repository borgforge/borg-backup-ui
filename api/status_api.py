"""
api/status_api.py – Status-Daten für das Dashboard

Importiert lib/status.py aus dem Backup-Scripts-Verzeichnis (via sys.path,
gesetzt von borg_backup_ui.py). Gibt strukturierte Dicts zurück, die direkt
als JSON an den Browser gesendet werden.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_status_data(config: dict, force_snapshot_write: bool = False) -> Dict[str, Any]:
    """
    Lädt alle aktuellen Backup-Status und gibt Dashboard-Daten zurück.

    Gibt zurück:
        {
          "backups": [...],   # neuester Status pro backup_type+location
          "summary": {...},   # Zähler success/warning/error
          "snapshots": {...}, # wöchentliche Repo-Größen (letzten 8 Wochen)
        }
    """
    from status import (
        StatusStore,
        format_bytes,
        format_duration,
        time_ago,
    )

    status_dir = Path(config["STATUS_DIR"])
    snapshot_file = Path(
        config.get("SNAPSHOT_FILE", str(status_dir.parent / "weekly-snapshots.json"))
    )
    legacy_snapshot_file = status_dir / "weekly-snapshots.json"
    _import_legacy_snapshot_if_needed(snapshot_file, legacy_snapshot_file)

    store = StatusStore(status_dir)
    all_statuses = store.load()
    latest = store.get_latest_per_key(all_statuses)

    _auto_write_weekly_snapshot(snapshot_file, latest, force_write=force_snapshot_write)
    last_week_sizes = _load_last_week_sizes(snapshot_file)
    previous_status_sizes = _load_previous_status_sizes(all_statuses, latest)

    backups: List[Dict[str, Any]] = []
    for key, st in sorted(latest.items()):
        prev_size = last_week_sizes.get(key, 0) or previous_status_sizes.get(key, 0)
        growth: Optional[int] = (st.repository_size - prev_size) if prev_size > 0 else None

        if growth is None:
            growth_str = "—"
        elif growth > 0:
            growth_str = f"+{format_bytes(growth)}"
        elif growth < 0:
            growth_str = f"-{format_bytes(-growth)}"
        else:
            growth_str = "±0"

        compression_pct = ""
        if st.original_size > 0 and st.compressed_size > 0:
            ratio = (1 - st.compressed_size / st.original_size) * 100
            compression_pct = f"{ratio:.1f}%"

        dedup_pct = ""
        if st.original_size > 0 and st.deduplicated_size > 0:
            ratio = (1 - st.deduplicated_size / st.original_size) * 100
            dedup_pct = f"{ratio:.1f}%"

        backups.append(
            {
                "key": key,
                "backup_type": st.backup_type,
                "location": st.location,
                "status": st.status,
                "timestamp": st.timestamp,
                "time_ago": time_ago(st.timestamp) if st.timestamp else "unbekannt",
                "duration_seconds": st.duration_seconds,
                "duration_formatted": format_duration(st.duration_seconds),
                "exit_code": st.exit_code,
                "failure_code": getattr(st, "failure_code", "") or "",
                "missing_source_paths": list(
                    getattr(st, "missing_source_paths", []) or []
                ),
                "error_message": st.error_message or "",
                "skip_reason_code": getattr(st, "skip_reason_code", "") or "",
                "skip_reason_text": getattr(st, "skip_reason_text", "") or "",
                "archive_name": st.archive_name or "",
                "files_count": st.files_count,
                "original_size": st.original_size,
                "original_size_formatted": format_bytes(st.original_size),
                "compressed_size": st.compressed_size,
                "compressed_size_formatted": format_bytes(st.compressed_size),
                "compression_pct": compression_pct,
                "deduplicated_size": st.deduplicated_size,
                "deduplicated_size_formatted": format_bytes(st.deduplicated_size),
                "dedup_pct": dedup_pct,
                "repository_size": st.repository_size,
                "repository_size_formatted": format_bytes(st.repository_size),
                "repository_check_status": st.repository_check_status,
                "repository_check_date": st.repository_check_date or "",
                "repository_next_check": st.repository_next_check or "",
                "growth_bytes": growth,
                "growth_formatted": growth_str,
            }
        )

    try:
        from jobs_api import discover_jobs, resolve_data_root, resolve_scripts_dir
        from restore_tests_api import build_restore_verification_map

        scripts_dir = resolve_scripts_dir(config)
        data_root = resolve_data_root(config)
        jobs = []
        for j in discover_jobs(scripts_dir, data_root):
            jobs.append(
                {
                    "key": j.key,
                    "location": j.location,
                    "restore_test_policy": {
                        "mode": j.restore_test_policy_mode,
                        "interval_days": j.restore_test_interval_days,
                        "validity_days": j.restore_test_validity_days,
                        "level": j.restore_test_level,
                        "max_runtime_minutes": j.restore_test_max_runtime_minutes,
                    },
                }
            )
        verification = build_restore_verification_map(config, jobs)
    except Exception:
        verification = {}

    for b in backups:
        meta = verification.get(str(b.get("key") or ""), {})
        b["restore_verification_status"] = meta.get("status", "never")
        b["restore_verification_reason"] = meta.get("reason", "")
        b["restore_verification_last_test_date"] = meta.get("last_test_date", "")
        b["restore_verification_valid_until"] = meta.get("valid_until", "")
        b["restore_verification_is_overdue"] = bool(meta.get("is_overdue", False))
        b["restore_verification_failure_code"] = meta.get("failure_code", "")
        b["restore_verification_failure_hint"] = meta.get("failure_hint", "")
        b["restore_verification_failure_category"] = meta.get("failure_category", "")
        if isinstance(meta.get("policy"), dict):
            b["restore_test_policy"] = meta.get("policy")

    _apply_backup_overdue_metadata(config, backups)

    total = len(backups)
    success = sum(1 for b in backups if b["status"] == "success" and not bool(b.get("backup_overdue")))
    warning = sum(1 for b in backups if b["status"] in {"warning", "cancelled"} or bool(b.get("backup_overdue")))
    skipped = sum(1 for b in backups if b["status"] == "skipped")
    error = sum(1 for b in backups if b["status"] == "error")

    snapshots = _load_all_snapshots(snapshot_file)

    check_interval_days = int(config.get("GLOBAL_BORG_CHECK_INTERVAL_DAYS", "30") or "30")

    return {
        "backups": backups,
        "summary": {
            "total": total,
            "success": success,
            "warning": warning,
            "skipped": skipped,
            "error": error,
        },
        "snapshots": snapshots,
        "check_interval_days": check_interval_days,
    }


def _apply_backup_overdue_metadata(
    config: dict,
    backups: List[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> None:
    for row in backups:
        row["backup_overdue"] = False
        row["backup_overdue_state"] = ""
        row["backup_overdue_expected_run"] = ""
        row["backup_overdue_after"] = ""
        row["backup_overdue_next_run"] = ""

    try:
        from jobs_api import list_jobs
        from notification_reminder_api import (
            _backup_overdue_item,
            _backup_overdue_tolerance_hours,
            _latest_backup_status_by_key,
        )
        from schedule_api import get_schedules
    except Exception:
        return

    try:
        schedules = get_schedules(config)
        if not isinstance(schedules, dict) or not schedules:
            return
        jobs = {
            str(job.get("key") or "").strip(): job
            for job in list_jobs(config, {})
            if isinstance(job, dict) and str(job.get("key") or "").strip()
        }
        latest = _latest_backup_status_by_key(backups)
        tolerance_hours = _backup_overdue_tolerance_hours(config)
        current_time = now or datetime.now()
    except Exception:
        return

    for job_key, sched in schedules.items():
        job_key = str(job_key or "").strip()
        if job_key == "restore_test" or not job_key or not isinstance(sched, dict) or not bool(sched.get("enabled", True)):
            continue
        job = jobs.get(job_key)
        if not job or job.get("enabled") is False:
            continue
        row = latest.get(job_key)
        if row is None:
            continue
        try:
            item = _backup_overdue_item(
                job_key,
                sched,
                job,
                row,
                {},
                current_time,
                1,
                tolerance_hours,
            )
        except Exception:
            continue
        state = str(item.get("state") or "")
        if state == "unsupported":
            continue
        row["backup_overdue_state"] = state
        row["backup_overdue_expected_run"] = str(item.get("expected_run") or "")
        row["backup_overdue_after"] = str(item.get("overdue_after") or "")
        row["backup_overdue_next_run"] = str(item.get("next_scheduled_run") or "")
        row["backup_overdue"] = state in {"overdue_ready", "overdue_waiting"}


def _read_snapshot_data(*paths: Path) -> Dict[str, List[Dict]]:
    from status import status_storage_unavailable_reason

    for p in paths:
        try:
            if p and not status_storage_unavailable_reason(p) and p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return {}


def _import_legacy_snapshot_if_needed(snapshot_file: Path, legacy_snapshot_file: Path) -> None:
    from status import status_storage_unavailable_reason

    if (
        status_storage_unavailable_reason(snapshot_file)
        or status_storage_unavailable_reason(legacy_snapshot_file)
    ):
        return
    if snapshot_file == legacy_snapshot_file or snapshot_file.exists() or not legacy_snapshot_file.exists():
        return
    try:
        data = json.loads(legacy_snapshot_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict):
        return
    try:
        from status import ensure_status_storage_directory

        ensure_status_storage_directory(snapshot_file.parent)
        snapshot_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _auto_write_weekly_snapshot(
    snapshot_file: Path,
    latest_per_key: dict,
    force_write: bool = False,
) -> None:
    """
    Schreibt einmal pro Woche (Montags-Datum als Tag) einen Snapshot-Eintrag.
    Ersetzt den externen borg_summary_mail.py-Aufruf.
    """
    from status import status_storage_unavailable_reason

    if status_storage_unavailable_reason(snapshot_file):
        return

    today = date.today()
    week_tag = (today - timedelta(days=today.weekday())).isoformat()  # Dieser Montag

    data: Dict[str, List[Dict]] = _read_snapshot_data(snapshot_file)

    changed = False
    for key, st in latest_per_key.items():
        size = int(getattr(st, "repository_size", 0) or 0)
        entries: List[Dict] = data.get(key, [])
        if entries and entries[-1].get("week") == week_tag:
            if entries[-1].get("size") != size:
                entries[-1]["size"] = size
                changed = True
        else:
            entries.append({"week": week_tag, "size": size})
            changed = True
        data[key] = entries[-52:]  # max. 1 Jahr

    if changed or force_write:
        try:
            from status import ensure_status_storage_directory

            ensure_status_storage_directory(snapshot_file.parent)
            snapshot_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass


def _load_last_week_sizes(snapshot_file: Path) -> Dict[str, int]:
    """Gibt Repository-Größen der Vorwoche zurück (Index -2)."""
    data = _read_snapshot_data(snapshot_file)
    if not data:
        return {}
    result: Dict[str, int] = {}
    for key, entries in data.items():
        if isinstance(entries, list) and len(entries) >= 2:
            entry = entries[-2]
            result[key] = int(entry.get("size", 0) or 0)
    return result


def _status_key(st: Any) -> str:
    key = getattr(st, "key", None)
    if key:
        return str(key)
    return f"{getattr(st, 'backup_type', 'unknown')}_{getattr(st, 'location', 'unknown')}"


def _load_previous_status_sizes(all_statuses: List[Any], latest_per_key: Dict[str, Any]) -> Dict[str, int]:
    """Returns the previous repository size per key from .status history."""
    grouped: Dict[str, List[Any]] = {}
    for st in all_statuses:
        key = _status_key(st)
        if not key:
            continue
        size = int(getattr(st, "repository_size", 0) or 0)
        if size <= 0:
            continue
        grouped.setdefault(key, []).append(st)

    result: Dict[str, int] = {}
    for key, rows in grouped.items():
        latest = latest_per_key.get(key)
        rows_sorted = sorted(rows, key=lambda st: str(getattr(st, "timestamp", "") or ""), reverse=True)
        for st in rows_sorted:
            if latest is not None and st is latest:
                continue
            result[key] = int(getattr(st, "repository_size", 0) or 0)
            break
    return result


def _load_all_snapshots(snapshot_file: Path) -> Dict[str, List[Dict]]:
    """Lädt alle Snapshot-Einträge (max. 8 Wochen) für Trend-Charts."""
    data = _read_snapshot_data(snapshot_file)
    if not data:
        return {}
    result: Dict[str, List[Dict]] = {}
    for key, entries in data.items():
        if isinstance(entries, list):
            result[key] = [
                {"week": e.get("week", ""), "size": int(e.get("size", 0) or 0)}
                for e in entries[-8:]
                if isinstance(e, dict)
            ]
    return result
