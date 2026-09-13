"""Explicit job settings, independent of the former backup type (#495)."""

import re

JOB_SETTINGS_SCHEMA = 5
DEFAULT_COMPRESSION = "lz4"
DEFAULT_RETENTION = {"daily": "7", "weekly": "4", "monthly": "6", "yearly": "3"}
DEFAULT_ICON = "archive"


class JobSettingsError(ValueError):
    api_code = "job_settings_invalid"


def explicit_job_settings(meta: dict) -> tuple[str, dict[str, str]]:
    compression = str(meta.get("compression") or "").strip()
    if not compression:
        raise JobSettingsError("Job compression is missing. Edit and save the job settings.")
    source = meta.get("retention")
    if not isinstance(source, dict):
        raise JobSettingsError("Job retention is missing. Edit and save the job settings.")
    from runtime.lib.retention_policy import normalize_retention
    return compression, normalize_retention(source)
