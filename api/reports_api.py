"""api/reports_api.py – Berichte: historische Auswertung aus .status-Dateien"""

import json
from pathlib import Path
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


def _parse_job_key(job_key: str):
    """Split 'appdata_local' → ('appdata', 'local'). Handles multi-underscore locations."""
    known_locations = ("local", "usb", "storagebox")
    for loc in known_locations:
        if job_key.endswith("_" + loc):
            btype = job_key[: -(len(loc) + 1)]
            return btype, loc
    parts = job_key.rsplit("_", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (job_key, "")


def get_report_jobs(config: dict) -> List[dict]:
    """Returns all unique jobs found in status files."""
    status_dir = Path(config["STATUS_DIR"])
    seen = {}
    for f in sorted(status_dir.glob("*.status")):
        stem = f.stem
        parts = stem.split("_")
        if len(parts) < 4:
            continue
        backup_type = parts[2]
        location = "_".join(parts[3:])
        key = f"{backup_type}_{location}"
        if key not in seen:
            seen[key] = {
                "key": key,
                "backup_type": backup_type,
                "location": location,
                "display_name": f"{backup_type.capitalize()} ({location})",
            }
    return list(seen.values())


def get_report_data(config: dict, job_key: str) -> dict:
    """Returns full time-series report for a job from its .status files."""
    backup_type, location = _parse_job_key(job_key)
    status_dir = Path(config["STATUS_DIR"])

    runs = []
    for f in sorted(status_dir.glob("*.status")):
        stem = f.stem
        parts = stem.split("_")
        if len(parts) < 4:
            continue
        ftype = parts[2]
        floc = "_".join(parts[3:])
        if ftype != backup_type or floc != location:
            continue
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        ts = raw.get("timestamp", "")
        runs.append({
            "timestamp": ts,
            "date": ts[:10] if ts else "",
            "status": raw.get("status", "unknown"),
            "duration_seconds": raw.get("duration_seconds"),
            "original_size": raw.get("original_size") or 0,
            "compressed_size": raw.get("compressed_size") or 0,
            "deduplicated_size": raw.get("deduplicated_size") or 0,
            "repository_size": raw.get("repository_size") or 0,
            "files_count": raw.get("files_count") or 0,
        })

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
        "job_key": job_key,
        "backup_type": backup_type,
        "location": location,
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
