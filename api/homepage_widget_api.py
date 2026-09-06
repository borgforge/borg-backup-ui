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
        if state == 'stale' and item.get('reason') in {'target_unknown', 'target_changed', 'test_date_unknown'}:
            never += 1  # Existing API counter for proof that remains open.
            continue
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
    from config_api import read_expanded_conf
    from status_api import get_status_data
    effective = {**config, **read_expanded_conf(config)}
    generated = now or datetime.now(timezone.utc)
    local_now = generated.astimezone().replace(tzinfo=None) if generated.tzinfo else generated
    data = get_status_data(effective, write_snapshots=False, now=local_now)
    jobs = data['backups']
    enabled_jobs = [row for row in jobs if row.get('enabled') is not False]
    summary = data['summary']
    counts = {'successful': summary['success'], 'warning': summary['warning'],
              'failed': summary['error'], 'skipped': summary['skipped'],
              'never': summary['never'], 'unknown': summary['unknown']}
    counts['overdue'] = sum(bool(row.get('backup_overdue')) for row in enabled_jobs if not row.get('running'))
    restore = _restore_summary(effective, enabled_jobs)
    active_jobs = [str(row.get('name') or 'Backup')[:160] for row in enabled_jobs if row.get('running')]

    critical = counts["failed"] + restore["failed"]
    attention = (
        counts["warning"] + counts["skipped"] + counts["never"] + counts["unknown"]
        + restore["overdue"] + restore["never"]
    )
    if critical:
        state, label, severity = "critical", "Critical", 3
    elif active_jobs:
        state, label, severity = "active", "Backup running", 1
    elif attention:
        state, label, severity = "attention", "Attention required", 2
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
        "active": {"count": len(active_jobs), "jobs": active_jobs,
                   "job_ids": [row["job_id"] for row in enabled_jobs if row.get("running")]},
    }
