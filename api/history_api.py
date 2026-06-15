"""history_api.py – Liest alle .status-Dateien und gibt sie als Liste zurück."""

import json
from datetime import datetime
from pathlib import Path



def _fmt_bytes(b):
    if b is None:
        return None
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _fmt_duration(secs):
    if secs is None:
        return None
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def get_history_data(config: dict, filters: dict | None = None) -> dict:
    status_dir = Path(config["STATUS_DIR"])
    filters = filters or {}
    try:
        page = max(1, int(filters.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = max(1, min(200, int(filters.get("per_page") or 20)))
    except (TypeError, ValueError):
        per_page = 20

    entries = []
    known_types = {"flash", "appdata", "photos", "vms", "sonstiges"}
    for f in sorted(status_dir.glob("*.status"), reverse=True):
        # Filename: YYYY-MM-DD_HH-MM-SS_type_location.status
        stem = f.stem
        parts = stem.split("_")
        if len(parts) < 4:
            continue
        date_part = parts[0]          # 2026-03-01
        time_part = parts[1]          # 02-15-43
        backup_type = parts[2]        # flash / appdata / …
        location = "_".join(parts[3:]) # local / usb / storagebox

        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        status = raw.get("status", "unknown")
        exit_code = raw.get("borg_exit_code", raw.get("exit_code"))

        # Apply filters
        filt_type = str(filters.get("type") or "").strip().lower()
        if filt_type:
            bt_low = str(backup_type or "").strip().lower()
            if filt_type == "custom":
                if bt_low in known_types:
                    continue
            elif filt_type != bt_low:
                continue
        if filters.get("location") and filters["location"] != location.lower():
            continue
        if filters.get("status") and filters["status"] != status:
            continue

        entries.append({
            "entry_kind": "backup_run",
            "filename": f.name,
            "date": date_part,
            "time": time_part.replace("-", ":"),
            "timestamp": raw.get("timestamp", f"{date_part} {time_part.replace('-', ':')}"),
            "backup_type": raw.get("backup_type", backup_type),
            "location": raw.get("location", location),
            "status": status,
            "exit_code": exit_code,
            "duration_seconds": raw.get("duration_seconds"),
            "duration_fmt": _fmt_duration(raw.get("duration_seconds")),
            "original_size": raw.get("original_size"),
            "original_size_fmt": _fmt_bytes(raw.get("original_size")),
            "compressed_size": raw.get("compressed_size"),
            "compressed_size_fmt": _fmt_bytes(raw.get("compressed_size")),
            "deduplicated_size": raw.get("deduplicated_size"),
            "deduplicated_size_fmt": _fmt_bytes(raw.get("deduplicated_size")),
            "repository_size": raw.get("repository_size"),
            "repository_size_fmt": _fmt_bytes(raw.get("repository_size")),
            "files_count": raw.get("files_count"),
            "archive_name": raw.get("archive_name"),
            "log_file": raw.get("log_file"),
            "error_message": raw.get("error_message"),
            "skip_reason_code": raw.get("skip_reason_code", ""),
            "skip_reason_text": raw.get("skip_reason_text", ""),
            "repository_check_date": raw.get("repository_check_date"),
            "repository_check_status": raw.get("repository_check_status"),
            "repository_next_check": raw.get("repository_next_check"),
        })

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
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }
