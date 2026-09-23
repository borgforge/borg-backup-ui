"""Optional, read-only Prometheus exporter (#534).

Only plugin metadata is read. Never use inventory/API refresh helpers here:
some acquire write locks, migrate files, probe storage or execute Borg.
"""
from __future__ import annotations

import json
import math
import os
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

from api.auth_store import data_root

CACHE_SECONDS = 60
_guard = threading.RLock()
_cache: dict[tuple, tuple[float, str]] = {}


def settings_file(config: dict) -> Path:
    """Return the private exporter settings path under the plugin data root."""
    return data_root(config) / "config" / ".prometheus-exporter.json"


def read_settings(config: dict) -> dict:
    """Read enabled state and token, returning an empty mapping on invalid data."""
    try:
        value = json.loads(settings_file(config).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return {}
        return {"enabled": value.get("enabled") is True, "token": str(value.get("token") or "")}
    except (OSError, ValueError):
        return {}


def settings_status(config: dict) -> dict:
    """Return public exporter state without exposing the bearer token."""
    value = read_settings(config)
    return {"enabled": value.get("enabled", False), "configured": bool(value.get("token")),
            "cache_seconds": CACHE_SECONDS}


def update_settings(config: dict, body: dict) -> dict:
    """Validate and atomically persist exporter enable/rotate/revoke settings.

    ``body`` accepts boolean ``enabled``, ``rotate`` and ``revoke`` fields.
    Returns public status plus the token only when a new token is created.
    Raises ValueError for invalid or conflicting input; callers enforce admin
    authorization before invoking this operation.
    """
    if not isinstance(body, dict) or set(body) - {"enabled", "rotate", "revoke"} or not body:
        raise ValueError("Invalid Prometheus settings")
    if any(type(value) is not bool for value in body.values()):
        raise ValueError("Prometheus settings must be boolean")
    if body.get("revoke") and (body.get("rotate") or body.get("enabled")):
        raise ValueError("Cannot enable or rotate while revoking the token")
    with _guard:
        current = read_settings(config)
        token = current.get("token", "")
        enabled = body.get("enabled", current.get("enabled", False))
        fresh_token = ""
        if body.get("revoke"):
            token, enabled = "", False
        elif body.get("rotate") or (enabled and not token):
            token = fresh_token = secrets.token_hex(32)
        path = settings_file(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"enabled": enabled, "token": token}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        _cache.clear()
        result = settings_status(config)
        if fresh_token:
            result["token"] = fresh_token
        return result


def _json_file(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _timestamp(value) -> float | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            return None
    return parsed.timestamp()


def _escape(value) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class Metrics:
    """Accumulate finite gauge samples in Prometheus text format."""

    def __init__(self):
        self.families: dict[str, tuple[str, list[str]]] = {}

    def add(self, name: str, help_text: str, value, **labels) -> None:
        """Append a ``bbui_`` gauge sample, omitting absent/nonfinite values.

        ``labels`` are escaped and sorted for stable output.
        """
        if value is None:
            return
        number = float(value)
        if not math.isfinite(number):
            return
        name = "bbui_" + name
        _, samples = self.families.setdefault(name, (help_text, []))
        suffix = "{" + ",".join(f'{key}="{_escape(val)}"' for key, val in sorted(labels.items())) + "}" if labels else ""
        samples.append(f"{name}{suffix} {number:.17g}")

    def render(self) -> str:
        """Render metric families with HELP and TYPE declarations."""
        return "".join(f"# HELP {name} {help_text}\n# TYPE {name} gauge\n" + "\n".join(samples) + "\n"
                       for name, (help_text, samples) in sorted(self.families.items()))


def _jobs(config: dict) -> list[dict]:
    from job_identity import metadata_job_id
    rows = []
    for path in sorted((data_root(config) / "config" / "jobs").glob("*.json")):
        row = _json_file(path, {})
        key = metadata_job_id(row)
        if not row.get("is_utility"):
            rows.append({**row, "key": key})
    return rows


def _labels(job: dict) -> dict:
    return {"job_id": job["key"], "job_name": str(job.get("name") or job["key"]),
            "location": str(job.get("location") or "unknown"),
            "repository": str(job.get("repository_key") or "")}


def _backups(metrics: Metrics, config: dict, jobs: list[dict], now: datetime) -> None:
    from status import StatusStore, status_storage_unavailable_reason
    from notification_reminder_api import _backup_overdue_item, _backup_overdue_tolerance_hours, _next_expected_run
    path = Path(config.get("STATUS_DIR") or "/mnt/user/backup-status")
    if status_storage_unavailable_reason(path):
        raise OSError("Status storage unavailable")
    store = StatusStore(path)
    statuses = store.load() if path.exists() else []
    latest = store.get_latest_per_key(statuses)
    successful = store.get_latest_per_key([row for row in statuses if row.status == "success"])
    archives = store.get_latest_per_key([row for row in statuses if row.status in {"success", "warning"} and row.archive_name])
    schedules = _json_file(data_root(config) / "config" / "schedules.json", {})
    for job in jobs:
        labels = _labels(job)
        row = latest.get(job["key"])
        state = row.status if row and row.status in {"success", "warning", "error", "skipped", "cancelled"} else "unknown"
        for candidate in ("success", "warning", "error", "skipped", "cancelled", "unknown"):
            metrics.add("backup_last_result", "Result of the latest backup run (one-hot).", int(candidate == state), result=candidate, **labels)
        if row:
            metrics.add("backup_last_run_timestamp_seconds", "Latest backup completion time, Unix seconds.", _timestamp(row.timestamp), **labels)
            metrics.add("backup_last_duration_seconds", "Duration of the latest backup run.", row.duration_seconds, **labels)
        success = successful.get(job["key"])
        metrics.add("backup_last_success_timestamp_seconds", "Latest successful backup retained in status history, Unix seconds.", _timestamp(success.timestamp) if success else None, **labels)
        archive = archives.get(job["key"])
        if archive:
            metrics.add("backup_archive_timestamp_seconds", "Completion time of the backup providing the archive statistics.", _timestamp(archive.timestamp), **labels)
            for field, name, help_text in (
                ("files_count", "backup_archive_files", "Files in the latest recorded backup archive."),
                ("original_size", "backup_archive_original_bytes", "Original bytes in the latest recorded backup archive."),
                ("compressed_size", "backup_archive_compressed_bytes", "Compressed bytes in the latest recorded backup archive."),
                ("deduplicated_size", "backup_archive_deduplicated_bytes", "New deduplicated bytes in the latest recorded backup archive."),
            ):
                metrics.add(name, help_text, getattr(archive, field), **labels)
        schedule = schedules.get(job["key"], {})
        scheduled = bool(job.get("enabled", True) and schedule.get("enabled", True) and schedule.get("cron"))
        metrics.add("backup_scheduled", "Whether a backup schedule is configured and enabled.", int(scheduled), **labels)
        if scheduled:
            due = _backup_overdue_item(job["key"], schedule, job,
                                      {"timestamp": row.timestamp, "status": row.status} if row else {}, {}, now, 24,
                                      _backup_overdue_tolerance_hours(config))
            if due.get("state") not in {"missing_status", "unsupported"}:
                metrics.add("backup_overdue", "Backup overdue according to the plugin reminder policy.", int(str(due.get("state")).startswith("overdue_")), **labels)
            upcoming = _next_expected_run(schedule["cron"], now)
            metrics.add("backup_next_run_timestamp_seconds", "Next configured backup schedule occurrence; execution is not guaranteed.", upcoming.timestamp() if upcoming else None, **labels)


def _repositories(metrics: Metrics, config: dict, jobs: list[dict], now: datetime) -> None:
    # Read the atomically replaced inventory directly: its normal accessor can
    # create an inventory lock file. An exporter must never do that.
    store = _json_file(data_root(config) / "config" / "repositories.json", {"repositories": []})
    for row in store["repositories"]:
        labels = {"repository": str(row["repository_key"]), "repository_name": str(row.get("display_name") or row["repository_key"]),
                  "location": str(row.get("location") or row.get("storage_type") or "unknown")}
        metrics.add("repository_info", "Configured repository (no connection probe).", 1, **labels)
        stats = row.get("repository_stats") or {}
        for field, name in (("archives_count", "archives"), ("total_size", "original_bytes"),
                            ("total_csize", "compressed_bytes"), ("unique_csize", "deduplicated_bytes")):
            metrics.add("repository_" + name, "Cached repository " + name.replace("_", " ") + ".", stats.get(field), **labels)
        metrics.add("repository_refresh_timestamp_seconds", "Last repository information refresh attempt, Unix seconds.", _timestamp(row.get("last_info_refresh_at")), **labels)
        for state in ("success", "warning", "error", "busy", "unknown"):
            actual = row.get("last_info_refresh_status") or "unknown"
            metrics.add("repository_refresh_result", "Result of the last repository information refresh (one-hot).", int(actual == state), result=state, **labels)
        metrics.add("repository_modified_timestamp_seconds", "Repository modification time reported by the last successful Borg info.", _timestamp(row.get("borg_last_modified")), **labels)


def _restore_tests(metrics: Metrics, config: dict, jobs: list[dict], now: datetime) -> None:
    from restore_tests_api import build_restore_verification_map
    from notification_reminder_api import _next_expected_run
    verification = build_restore_verification_map(config, jobs)
    schedules = _json_file(data_root(config) / "config" / "schedules.json", {})
    for job in jobs:
        labels = _labels(job)
        item = verification[job["key"]]
        for state in ("verified", "stale", "failed", "never", "not_required"):
            metrics.add("restore_verification_state", "Restore evidence state according to plugin policy (one-hot).", int(item["status"] == state), state=state, **labels)
        metrics.add("restore_test_last_timestamp_seconds", "Last recorded restore verification time, Unix seconds.", _timestamp(item.get("last_test_date")), **labels)
        metrics.add("restore_test_valid_until_timestamp_seconds", "Restore evidence expiry, Unix seconds; absent without an expiry.", _timestamp(item.get("valid_until")), **labels)
        if item.get("last_test_date"):
            metrics.add("restore_test_last_duration_seconds", "Last restore test duration.", item.get("last_test_duration_seconds"), **labels)
            metrics.add("restore_test_last_level", "Last restore test level (1 to 3).", item.get("last_test_level"), **labels)
        metrics.add("restore_test_overdue", "Restore evidence overdue according to plugin policy.", int(item.get("is_overdue", False)), **labels)
        policy = item["policy"]
        legacy = schedules.get("restore_test", {})
        cron = policy.get("cron") or (legacy.get("cron") if legacy.get("enabled", True) else "")
        scheduled = policy.get("mode") == "scheduled" and job.get("enabled", True) and bool(cron)
        metrics.add("restore_test_scheduled", "Whether a restore test schedule is configured and enabled.", int(scheduled), **labels)
        if scheduled:
            next_run = _next_expected_run(cron, now)
            metrics.add("restore_test_next_run_timestamp_seconds", "Next configured restore test occurrence; execution is not guaranteed.", next_run.timestamp() if next_run else None, **labels)


def _running(metrics: Metrics, config: dict, jobs: list[dict], now: datetime) -> None:
    from jobs_api import get_all_runtime_states, active_resource_locks
    states = get_all_runtime_states(config)
    tests = {str(row.get("job_key")) for row in active_resource_locks(config) if row.get("operation") == "restore_test"}
    for job in jobs:
        labels = _labels(job)
        metrics.add("backup_running", "Backup runtime currently active.", int(bool(states.get(job["key"], {}).get("running"))), **labels)
        metrics.add("restore_test_running", "Restore test currently holding a repository resource lock.", int(job["key"] in tests), **labels)


def collect_metrics(config: dict, version: str) -> str:
    """Read cached plugin state into a Prometheus snapshot without running Borg.

    Configuration failure returns only base metrics and a failed collector flag.
    Each later collector fails independently and contributes its own status;
    exceptions are intentionally omitted from the public metrics response.
    """
    from config_api import read_expanded_conf
    now = datetime.now().astimezone()
    metrics = Metrics()
    metrics.add("build_info", "Borg Backup UI version.", 1, version=version)
    metrics.add("metrics_generated_timestamp_seconds", "Time at which this cached metrics snapshot was collected.", now.timestamp())
    metrics.add("metrics_cache_seconds", "Maximum in-memory metrics cache age.", CACHE_SECONDS)
    try:
        effective = {**config, **read_expanded_conf(config)}
        jobs = _jobs(config)
        for job in jobs:
            metrics.add("job_enabled", "Whether the backup job is enabled.", int(bool(job.get("enabled", True))), **_labels(job))
    except Exception:
        metrics.add("collector_success", "Whether the collector could read its local data.", 0, collector="configuration")
        return metrics.render()
    metrics.add("collector_success", "Whether the collector could read its local data.", 1, collector="configuration")
    for name, collector in (("backups", _backups), ("repositories", _repositories), ("restore_tests", _restore_tests), ("runtime", _running)):
        # Publish a collector atomically: failed collection must not look like a
        # complete, current sample set, nor leak exceptions, paths or credentials.
        section = Metrics()
        try:
            collector(section, effective, jobs, now.replace(tzinfo=None))
            metrics.families.update(section.families)
            ok = 1
        except Exception:
            ok = 0
        metrics.add("collector_success", "Whether the collector could read its local data.", ok, collector=name)
    return metrics.render()


def cached_metrics(config: dict, version: str) -> str:
    """Return a snapshot cached for at most ``CACHE_SECONDS`` under a lock.

    The cache key includes configured data/status roots and plugin version.
    """
    key = (str(data_root(config)), str(config.get("STATUS_DIR")), str(config.get("RESTORE_TEST_STATUS_DIR")), version)
    with _guard:
        stamp, text = _cache.get(key, (0.0, ""))
        if not text or time.monotonic() - stamp >= CACHE_SECONDS:
            text = collect_metrics(config, version)
            _cache.clear()  # One running application; keep memory bounded in tests/reloads too.
            _cache[key] = (time.monotonic(), text)
        return text
