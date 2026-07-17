"""Process-local startup state for restricted migration maintenance mode."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from .security_utils import mask_secrets
except ImportError:  # Runtime imports api modules directly from API_ROOT.
    from security_utils import mask_secrets


CONFIG_KEY = "_STARTUP_STATE"
NORMAL_MODE = "normal"
MAINTENANCE_MODE = "maintenance"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_error(value: Any) -> str:
    return mask_secrets(str(value or "").strip())[:500]


def normal_startup_state(summary: dict[str, Any] | None = None) -> dict[str, Any]:
    data = summary if isinstance(summary, dict) else {}
    return {
        "mode": NORMAL_MODE,
        "severity": "ok",
        "blocking": False,
        "reason_code": "",
        "message": "Normal operation is available.",
        "failed_migrations": [],
        "failures": [],
        "checked_at": _timestamp(),
        "applied_migrations": [str(item) for item in data.get("applied", []) if str(item).strip()],
        "recommendation_codes": [],
    }


def migration_maintenance_state(
    summary: dict[str, Any] | None = None,
    *,
    runner_error: BaseException | None = None,
) -> dict[str, Any]:
    data = summary if isinstance(summary, dict) else {}
    failed = [str(item) for item in data.get("failed", []) if str(item).strip()]
    results = data.get("results") if isinstance(data.get("results"), dict) else {}
    failures: list[dict[str, str]] = []
    for migration_id in failed:
        result = results.get(migration_id) if isinstance(results.get(migration_id), dict) else {}
        details = result.get("details") if isinstance(result.get("details"), dict) else {}
        failures.append(
            {
                "migration_id": migration_id,
                "phase": str(details.get("failed_phase") or "apply"),
                "error_type": str(details.get("error_type") or "MigrationError"),
                "error": _safe_error(details.get("error")),
            }
        )

    reason_code = "startup_migration_failed"
    if runner_error is not None:
        reason_code = "startup_migration_runner_failed"
        failed = failed or ["startup_migration_registry"]
        failures.append(
            {
                "migration_id": "startup_migration_registry",
                "phase": "runner",
                "error_type": type(runner_error).__name__,
                "error": _safe_error(runner_error),
            }
        )

    return {
        "mode": MAINTENANCE_MODE,
        "severity": "critical",
        "blocking": True,
        "reason_code": reason_code,
        "message": "Normal operation is blocked because a required startup migration failed.",
        "failed_migrations": failed,
        "failures": failures,
        "checked_at": _timestamp(),
        "applied_migrations": [str(item) for item in data.get("applied", []) if str(item).strip()],
        "recommendation_codes": [
            "create_support_bundle",
            "review_migration_log",
            "correct_failure",
            "restart_plugin",
            "preserve_migration_state",
        ],
    }


def set_startup_state(config: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(state if isinstance(state, dict) else normal_startup_state())
    normalized["mode"] = (
        MAINTENANCE_MODE
        if str(normalized.get("mode") or "").strip() == MAINTENANCE_MODE
        else NORMAL_MODE
    )
    config[CONFIG_KEY] = normalized
    return dict(normalized)


def get_startup_state(config: dict[str, Any] | None) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    state = source.get(CONFIG_KEY) if isinstance(source.get(CONFIG_KEY), dict) else None
    return dict(state) if state is not None else normal_startup_state()


def is_maintenance_mode(config: dict[str, Any] | None) -> bool:
    return get_startup_state(config).get("mode") == MAINTENANCE_MODE
