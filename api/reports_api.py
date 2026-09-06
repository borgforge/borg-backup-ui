"""api/reports_api.py – Berichte: historische Auswertung aus .status-Dateien"""

from typing import List


def _fmt_bytes(b):
    if not b:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f}\u00a0{unit}"
        b /= 1024
    return f"{b:.1f}\u00a0PB"


def _fmt_duration(secs):
    if secs is None:
        return "—"
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def get_report_jobs(config: dict) -> List[dict]:
    from status_read_model import configured_jobs, history_rows, navigation_jobs, apply_restore_verification
    jobs = configured_jobs(config)
    apply_restore_verification(config, list(jobs.values()))
    rows = history_rows(config, jobs)
    result = navigation_jobs(jobs, rows)
    if any(row['identity_scope'] == 'unassigned' for row in rows):
        result.append({'job_id': '', 'identity_scope': 'unassigned', 'display_name': '', 'name': '', 'location': ''})
    return result


def get_report_data(config: dict, job_id: str = '', *, scope: str = '') -> dict:
    from status_read_model import configured_jobs, history_rows, navigation_jobs, apply_restore_verification, valid_job_id
    jobs = configured_jobs(config)
    apply_restore_verification(config, list(jobs.values()))
    rows = history_rows(config, jobs)
    if scope == 'unassigned' and not job_id:
        runs = [row for row in rows if row['identity_scope'] == 'unassigned']
        descriptor = {'identity_scope': 'unassigned', 'display_name': ''}
    else:
        if scope or not valid_job_id(job_id):
            raise ValueError('A canonical job_id or unassigned scope is required')
        runs = [row for row in rows if row['job_id'] == job_id and row['identity_scope'] != 'unassigned']
        descriptor = next((row for row in navigation_jobs(jobs, rows) if row['job_id'] == job_id), None)
        if descriptor is None:
            raise FileNotFoundError('Job history is not available')

    runs.sort(key=lambda r: r["timestamp"])

    # Summary from latest run
    latest = runs[-1] if runs else {}
    success_runs = [r for r in runs if r["status"] == "success"]
    durations = [r["duration_seconds"] for r in runs if r["duration_seconds"]]
    avg_duration = int(sum(durations) / len(durations)) if durations else None

    orig = latest.get("original_size", 0)
    repo_sz = latest.get("repository_size", 0)
    dedup_last = latest.get("deduplicated_size", 0)

    # Monthly status distribution
    months: dict = {}
    for r in runs:
        m = r["date"][:7] if r["date"] else ""
        if not m:
            continue
        bucket = months.setdefault(m, {"success": 0, "warning": 0, "error": 0})
        st = r["status"]
        if st in bucket:
            bucket[st] += 1

    monthly_status = [{"month": k, **v} for k, v in sorted(months.items())]

    return {
        "job_id": job_id,
        **descriptor,
        "run_count": len(runs),
        "success_count": len(success_runs),
        "avg_duration_seconds": avg_duration,
        "avg_duration_fmt": _fmt_duration(avg_duration),
        "latest_repository_size": repo_sz,
        "latest_repository_size_fmt": _fmt_bytes(repo_sz),
        "latest_original_size": orig,
        "latest_original_size_fmt": _fmt_bytes(orig),
        "latest_deduplicated_size": dedup_last,
        "latest_deduplicated_size_fmt": _fmt_bytes(dedup_last),
        "runs": runs,
        "monthly_status": monthly_status,
    }
