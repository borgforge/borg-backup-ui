"""history_api.py – Liest alle .status-Dateien und gibt sie als Liste zurück."""

from datetime import datetime


def get_history_data(config: dict, filters: dict | None = None) -> dict:
    filters = filters or {}
    try:
        page = max(1, int(filters.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = max(1, min(200, int(filters.get("per_page") or 20)))
    except (TypeError, ValueError):
        per_page = 20

    from status_read_model import configured_jobs, history_rows, navigation_jobs, valid_job_id
    jobs = configured_jobs(config)
    all_rows = history_rows(config, jobs)
    job_id = filters.get('job_id') or ''
    if job_id and not valid_job_id(job_id):
        raise ValueError('A canonical job_id is required')
    scope = filters.get('scope') or 'all'
    if scope not in {'all', 'configured', 'deleted', 'unassigned'}:
        raise ValueError('Invalid history scope')
    entries = []
    location_counts = {location: 0 for location in ('storagebox', 'usb', 'smb', 'local', 'unknown')}
    for row in all_rows:
        if job_id and (row['job_id'] != job_id or row['identity_scope'] == 'unassigned'):
            continue
        if scope != 'all' and row['identity_scope'] != scope:
            continue
        if filters.get('status') and row['status'] != filters['status']:
            continue
        location = row['location'] if row['location'] in location_counts else 'unknown'
        location_counts[location] += 1
        if filters.get('location') and filters['location'] != location:
            continue
        entries.append(row)

    def _ts_key(entry: dict):
        ts = str(entry.get("timestamp") or "")
        try:
            return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return datetime.min

    entries.sort(key=_ts_key, reverse=True)

    total = len(entries)
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    end = start + per_page

    return {
        "entries": entries[start:end],
        "jobs": navigation_jobs(jobs, all_rows),
        "scope_counts": {scope: sum(row["identity_scope"] == scope for row in all_rows) for scope in ("configured", "deleted", "unassigned")},
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "location_counts": location_counts,
        "location_total": sum(location_counts.values()),
    }
