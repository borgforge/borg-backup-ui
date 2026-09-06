"""
api/status_api.py – Status-Daten für das Dashboard

Importiert lib/status.py aus dem Backup-Scripts-Verzeichnis (via sys.path,
gesetzt von borg_backup_ui.py). Gibt strukturierte Dicts zurück, die direkt
als JSON an den Browser gesendet werden.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_status_data(config: dict, force_snapshot_write: bool = False, *, write_snapshots: bool = True, now: Optional[datetime] = None) -> Dict[str, Any]:
    """One row per configured UUID with completed status and active runtime."""
    from status import StatusStore, BackupStatus, format_bytes, format_duration, time_ago
    from status_read_model import configured_jobs, historical_row, summarize, apply_restore_verification
    from jobs_api import get_all_runtime_states
    from weekly_snapshots import read_observations, write_current, chart_series

    jobs = configured_jobs(config)
    status_dir = Path(config['STATUS_DIR'])
    snapshot_file = Path(config.get('SNAPSHOT_FILE') or status_dir.parent / 'weekly-snapshots.json')
    legacy_file = status_dir / 'weekly-snapshots.json'
    store = StatusStore(status_dir)
    statuses = store.load()
    latest = {job_id: status for job_id, status in store.get_latest_per_key(statuses).items() if job_id in jobs}
    if write_snapshots:
        write_current(snapshot_file, latest, legacy_file=legacy_file, force=force_snapshot_write)
    snapshots = chart_series(read_observations(snapshot_file, legacy_file), jobs)
    today = (now or datetime.now()).date()
    week = (today - timedelta(days=today.weekday())).isoformat()
    previous_sizes = _load_previous_status_sizes(statuses, latest)
    runtime = get_all_runtime_states(config)
    backups = []
    for job_id, job in jobs.items():
        status = latest.get(job_id) or BackupStatus(job_id=job_id, identity_state='assigned', status='unknown')
        row = historical_row(status, jobs)
        prior_weeks = [entry for entry in snapshots.get(job_id, []) if entry['week'] < week]
        prev_size = previous_sizes.get(job_id, 0)
        if prior_weeks:
            prior = prior_weeks[-1]
            same_target = bool(prior['repository_snapshot'] and prior['repository_snapshot'] == status.repository_snapshot)
            prev_size = (prior['size'] or 0) if same_target and not prior['conflict'] else 0
        growth = status.repository_size - prev_size if prev_size > 0 else None
        growth_text = '—' if growth is None else ('±0' if growth == 0 else ('+' if growth > 0 else '-') + format_bytes(abs(growth)))
        run = runtime.get(job_id, {})
        row.update({**job,
            'never_run': job_id not in latest,
            'legacy_status': job_id in latest and row['legacy_status'],
            'running': bool(run.get('running')),
            'active_run_id': run.get('run_id', ''),
            'run_start_time': run.get('start_time'),
            'time_ago': time_ago(status.timestamp) if status.timestamp else '',
            'duration_formatted': format_duration(status.duration_seconds),
            'compression_pct': f'{(1-status.compressed_size/status.original_size)*100:.1f}%' if status.original_size and status.compressed_size else '',
            'dedup_pct': f'{(1-status.deduplicated_size/status.original_size)*100:.1f}%' if status.original_size and status.deduplicated_size else '',
            'growth_bytes': growth, 'growth_formatted': growth_text,
            'status_repository_changed': bool(status.repository_snapshot and status.repository_snapshot != job['repo_path']),
            **{key + '_formatted': format_bytes(getattr(status, key)) for key in ('original_size', 'compressed_size', 'deduplicated_size', 'repository_size')},
        })
        # Preserve the last recorded legacy check without attesting its unknown
        # historical target. A known previous target cannot attest a new one.
        if status.repository_snapshot == job['repo_path'] and status.repository_snapshot:
            row['repository_check_scope'] = 'current'
        elif not status.repository_snapshot and row['legacy_status']:
            row['repository_check_scope'] = 'historical_target_unknown'
        else:
            row['repository_check_scope'] = 'target_changed' if status.repository_snapshot else 'target_unknown'
            row.update(repository_check_status='unknown', repository_check_date='', repository_next_check='')
        backups.append(row)
    apply_restore_verification(config, backups)
    _apply_backup_overdue_metadata(config, backups, now=now)
    return {'backups': backups, 'summary': summarize(backups), 'snapshots': snapshots,
            'check_interval_days': int(config.get('GLOBAL_BORG_CHECK_INTERVAL_DAYS', '30') or '30')}


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
            str(job.get("job_id") or "").strip(): job
            for job in backups
            if isinstance(job, dict) and str(job.get("job_id") or "").strip()
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
        if row is None or row.get("running"):
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


def _status_key(st: Any) -> str:
    return getattr(st, 'key', '')


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
            if latest is not None and (st is latest or st.timestamp >= latest.timestamp):
                continue
            if (latest is not None and st.repository_snapshot
                    and st.repository_snapshot == latest.repository_snapshot):
                result[key] = int(getattr(st, "repository_size", 0) or 0)
            break
    return result
