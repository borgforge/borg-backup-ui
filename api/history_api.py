"""Backup status history and confined access to retained history logs."""

import errno
import json
import os
import stat
from datetime import datetime
from pathlib import Path


LEGACY_LOG_DIR = Path("/mnt/user/Logs")
_LOG_SUFFIXES = {".log", ".txt"}


def _read_regular_history_log(path: Path) -> str:
    """Read a previously authorized, absolute canonical log path as UTF-8.

    Pin each directory by descriptor and refuse symlinks while opening, so a
    path component replaced after authorization cannot redirect the read.
    Non-regular files raise ValueError; OS errors propagate to the caller.
    All descriptors close on both success and failure. Linux/Unraid is required.
    """
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open(path.anchor, directory_flags)
    try:
        for name in path.parts[1:-1]:
            next_fd = os.open(name, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
    finally:
        os.close(directory_fd)
    try:
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise ValueError("Log file must be a regular file")
        with os.fdopen(file_fd, "r", encoding="utf-8", errors="replace", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(file_fd)


def get_history_log(config: dict, file_path: str) -> dict:
    """Read a .log/.txt file only within configured or legacy log storage.

    ``file_path`` must already be URL-decoded once. Relative paths are anchored
    to GLOBAL_LOG_DIR, never the process working directory. Canonical paths
    must stay below GLOBAL_LOG_DIR or the explicit legacy /mnt/user/Logs root;
    configured root symlinks and links staying within these roots are supported.
    The current/legacy basename fallback preserves references to moved logs.

    Returns the existing ``exists``, ``content``, ``path`` response, including
    ``exists=False`` for missing allowed files. Traversal, escaping symlinks and
    unauthorized paths raise PermissionError; malformed requests and special
    files raise ValueError. Other read failures raise RuntimeError.
    """
    from config_api import read_expanded_conf

    if not file_path:
        raise ValueError("file is required")
    if "\x00" in file_path:
        raise ValueError("Invalid log file path")
    requested = Path(file_path)
    if ".." in requested.parts:
        raise PermissionError("Log file is outside the allowed log directories")
    if requested.suffix.lower() not in _LOG_SUFFIXES:
        raise ValueError("Invalid file type")

    conf = read_expanded_conf(config)
    current_log_dir = Path(str(conf.get("GLOBAL_LOG_DIR", "")).strip() or LEGACY_LOG_DIR)
    roots = (current_log_dir.resolve(), LEGACY_LOG_DIR.resolve())
    candidates = [
        requested if requested.is_absolute() else current_log_dir / requested,
        current_log_dir / requested.name,
        LEGACY_LOG_DIR / requested.name,
    ]
    denied = False
    for candidate in dict.fromkeys(candidates):
        try:
            resolved = candidate.resolve()
            if not any(resolved.is_relative_to(root) for root in roots):
                denied = True
                continue
            if resolved.suffix.lower() not in _LOG_SUFFIXES:
                denied = True
                continue
            content = _read_regular_history_log(resolved)
            return {"exists": True, "content": content, "path": str(resolved)}
        except FileNotFoundError:
            continue
        except RuntimeError as exc:
            # Path.resolve() reports symlink loops as RuntimeError on Python 3.11.
            raise PermissionError("Log file path cannot be safely resolved") from exc
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise PermissionError("Log file path cannot be safely opened") from exc
            if isinstance(exc, PermissionError):
                raise PermissionError("Log file cannot be read") from exc
            raise RuntimeError("Unable to read log file") from exc
    if denied:
        raise PermissionError("Log file is outside the allowed log directories")
    return {"exists": False, "content": "", "path": str(candidates[0])}



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
    """Read and paginate known jobs' backup status history.

    ``filters`` may constrain job, type, status, location and page size.
    Unreadable status files and records without a discovered job are omitted;
    the result includes filtered entries, job choices and location counts.
    """
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
    from jobs_api import discover_jobs, resolve_data_root, resolve_scripts_dir
    jobs = {job.key: job for job in discover_jobs(resolve_scripts_dir(config), resolve_data_root(config))} if config.get("BACKUP_SCRIPTS_DIR") else {}
    location_counts = {location: 0 for location in ("storagebox", "usb", "smb", "local")}
    known_types = {"flash", "appdata", "photos", "vms", "sonstiges"}
    for f in sorted(status_dir.glob("*.status"), reverse=True):
        # Filename: YYYY-MM-DD_HH-MM-SS_type_location.status
        stem = f.stem
        parts = stem.split("_", 2)
        if len(parts) < 3:
            continue
        date_part = parts[0]          # 2026-03-01
        time_part = parts[1]          # 02-15-43

        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        backup_type = str(raw.get("backup_type") or "unknown")
        location = str(raw.get("location") or "unknown")
        job_id = str(raw.get("job_id") or "")
        job = jobs.get(job_id)
        if job is None:
            continue
        if filters.get("job_key") and filters["job_key"] != job_id:
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
        if filters.get("status") and filters["status"] != status:
            continue

        normalized_location = str(raw.get("location", location) or location).strip().lower()
        if normalized_location in location_counts:
            location_counts[normalized_location] += 1
        if filters.get("location") and filters["location"] != normalized_location:
            continue

        entries.append({
            "entry_kind": "backup_run",
            "job_id": job_id,
            "job_key": job_id,
            "job_name": (job.name or job.display_name) if job else backup_type,
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
        "jobs": [{"job_id": job.key, "name": job.name or job.display_name, "location": job.location} for job in jobs.values()],
        "entries": entries[start:end],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "location_counts": location_counts,
        "location_total": sum(location_counts.values()),
    }
