"""Versioned, allowlisted mobile HTTP contract; independent of legacy tokens."""
from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import mobile_auth as auth

PREFIX = "/api/mobile/v1/"
BROWSER = "/api/auth/mobile/"
ROUTES = {
    "GET": {PREFIX + "capabilities", PREFIX + "snapshot", BROWSER + "sessions"},
    "POST": {PREFIX + "pair", PREFIX + "exchange", PREFIX + "refresh", PREFIX + "logout",
             BROWSER + "approve", BROWSER + "revoke", PREFIX + "jobs/start", PREFIX + "jobs/cancel"},
}


def authorize(handler, path: str, request_id: str) -> bool:
    """Authorize exact routes; cookies/internal tokens never authorize device reads.

    Browser approval/revocation requires an existing user session and HTTPS
    same-origin CSRF validation. Bearers have no access to legacy endpoints.
    """
    try:
        if path not in ROUTES.get(handler.command, set()) or urlparse(handler.path).query:
            raise auth.MobileError("mobile_not_found", 404)
        if handler._bootstrap_required():
            raise auth.MobileError("mobile_setup_required", 403)
        if handler.command == "POST":
            if handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise auth.MobileError("mobile_bad_request", 400)
        if path.startswith(BROWSER):
            if not handler._ui_auth_enabled() or not handler._is_ui_session_valid():
                raise auth.MobileError("mobile_unauthorized", 401)
            session = handler._get_current_session_meta() or {}
            username = session.get("username", "")
            auth._user(handler.config, username)
            if handler.command == "POST" and (not handler._is_same_origin_request()
                    or urlparse(handler.headers.get("Origin", "")).scheme != "https"):
                raise auth.MobileError("csrf_origin_mismatch", 403)
            handler._mobile_user = username
        elif path not in {PREFIX + "capabilities", PREFIX + "pair", PREFIX + "exchange", PREFIX + "refresh"}:
            header = handler.headers.get("Authorization", "")
            token = header[7:] if header.startswith("Bearer ") else ""
            handler._mobile_session = auth.authenticate(handler.config, token)
        elif handler.command == "POST" and handler.headers.get("Origin"):
            raise auth.MobileError("csrf_origin_mismatch", 403)
        return handler._authorize_maintenance_request(path, request_id)
    except auth.MobileError as exc:
        handler._send_api_error(exc.api_status, exc.api_code, str(exc), request_id=request_id)
        return False


def handle(handler) -> dict:
    """Execute the already-authorized operation with bounded JSON input."""
    path = urlparse(handler.path).path
    body = {}
    if handler.command == "POST":
        try:
            size = int(handler.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise auth.MobileError("mobile_bad_request", 400) from exc
        if size <= 0 or size > 4096:
            raise auth.MobileError("mobile_bad_request", 400)
        body = handler._read_json_body()
    if path == PREFIX + "capabilities":
        return {"api_version": 1, "authentication": "device_pairing", "scope": auth.SCOPE,
                "session_expires_in": auth.SESSION_TTL, "job_control": True, "persistent_pairing": True}
    if path == PREFIX + "pair":
        return auth.begin(handler.config, body.get("device_name"), handler._client_ip(), body.get("persistent", False))
    if path == PREFIX + "exchange":
        return auth.exchange(handler.config, body.get("device_code"))
    if path == PREFIX + "refresh":
        return auth.refresh(handler.config, body.get("refresh_token"))
    if path == BROWSER + "approve":
        return auth.approve(handler.config, handler._mobile_user, body.get("user_code"), body.get("allow_job_control", False))
    if path == BROWSER + "sessions":
        return auth.sessions(handler.config, handler._mobile_user)
    if path == BROWSER + "revoke":
        return auth.revoke(handler.config, handler._mobile_user, body.get("session_id"))
    if path == PREFIX + "logout":
        session = handler._mobile_session
        return auth.revoke(handler.config, session["username"], session["id"])
    if path in {PREFIX + "jobs/start", PREFIX + "jobs/cancel"}:
        return control(handler, path.rsplit("/", 1)[-1], body)
    return snapshot(handler)


def _stamp(value: object) -> str | None:
    """Normalize recorded server-local naive timestamps to UTC; invalid is absent."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _number(value: object) -> int | None:
    if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return int(value)
    return None


def _id(value: object) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()[:32]


def _name(value: object) -> str:
    return str(value or "")[:160]


def _status(value: object) -> str:
    if value == "failed":
        return "error"
    return value if value in {"success", "warning", "error", "running", "cancelled", "skipped", "unavailable"} else "unknown"


def _code(value: object) -> str | None:
    """Expose structured identifiers only, never free-form error text/paths."""
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value) else None


def _schedule(job: dict, schedules: dict) -> dict:
    """Use the existing server-local reminder calculator; preserve unsupported cron."""
    from notification_reminder_api import _next_expected_run
    schedule = schedules.get(job["key"])
    if not schedule:
        return {"schedule_state": "none", "next_run": None, "cron": None}
    cron = schedule.get("cron", "")
    cron = cron if isinstance(cron, str) and re.fullmatch(r"[0-9*/ ,\-]{5,120}", cron) else ""
    enabled = schedule.get("enabled", True) and job.get("enabled", True)
    next_run = _next_expected_run(cron, datetime.now()) if enabled else None
    return {"schedule_state": "active" if next_run else "unsupported" if enabled else "disabled",
            "next_run": _stamp(next_run.isoformat()) if next_run else None, "cron": cron or None}


def _eligible(job: dict) -> bool:
    return job.get("enabled") is True and job.get("standard") == "wizard" and job.get("is_utility") is False


def control(handler, action: str, body: dict) -> dict:
    """Resolve opaque IDs and use existing launch/cancel services, never shell input."""
    from jobs_api import get_job_runtime_state, cancel_job
    from job_launch import start_backup
    job_id, run_id = body.get("job_id"), body.get("run_id")
    if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise auth.MobileError("mobile_bad_request", 400)
    if action == "cancel" and not _code(run_id):
        raise auth.MobileError("mobile_bad_request", 400)
    session = handler._mobile_session

    def execute():
        job = next((j for j in handler._get_jobs()["jobs"] if _id(j["key"]) == job_id), None)
        if not job or job.get("is_utility") is not False or job.get("standard") != "wizard":
            raise auth.MobileError("mobile_forbidden", 403)
        runtime = get_job_runtime_state(handler.config, job["key"])
        try:
            if action == "start":
                if not _eligible(job) or runtime.get("running"):
                    raise auth.MobileError("mobile_job_changed", 409)
                from borg_backup_ui import APP_VERSION
                started = start_backup(handler.config, job["key"], app_version=APP_VERSION,
                                       request_id=body["request_id"], source="mobile", actor=session["username"])
                return {"accepted": True, "run_id": started["run_id"]}
            if (not runtime.get("running") or runtime.get("run_id") != run_id
                    or runtime.get("cancel_allowed") is not True or runtime.get("cancel_requested")):
                raise auth.MobileError("mobile_job_changed", 409)
            result = cancel_job(handler.config, job["key"], run_id, requested_by=session["username"])
            return {"accepted": True, "run_id": run_id,
                    "cancellation_deferred": bool(result.get("cancellation_deferred"))}
        except auth.MobileError:
            raise
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            raise auth.MobileError("mobile_job_changed", 409) from exc

    return auth.command(handler.config, session, body.get("request_id"),
                        {"action": action, "job_id": job_id, "run_id": run_id}, execute)


def snapshot(handler) -> dict:
    """Project recorded status, schedules and runtime without config paths or logs.

    Optional v1 additions preserve older clients. Absent measurements stay null;
    percentages remain absent when Borg does not report a measured percentage.
    """
    from schedule_api import get_schedules
    jobs = handler._get_jobs()["jobs"]
    status = {row["key"]: row for row in handler._get_status().get("backups", [])}
    runtime = handler._get_running()
    schedules = get_schedules(handler.config)
    allowed = auth.can_control(handler.config, handler._mobile_session)
    history = handler._get_history("per_page=100&page=1")["entries"]
    overview = handler._get_report_overview("days=30&location=all")
    result = {"api_version": 1, "sampled_at": datetime.now(timezone.utc).isoformat(),
              "job_control": allowed,
              "jobs": [], "history": [], "repositories": [], "restore_tests": [], "restore_verifications": [],
              "storage_daily": [{"date": p["date"], "bytes": _number(p.get("repository_bytes"))}
                                for p in overview["daily"]]}
    repo_samples = {}
    for job in jobs:
        recorded = status.get(job["key"], {})
        live = runtime.get(job["key"], {})
        running = live.get("running", job.get("running", False))
        state = ("running" if running else "disabled" if job.get("enabled") is False else
                 _status(recorded.get("status") or job.get("last_status")) if job.get("last_status") or recorded.get("status") else "ready")
        progress = live.get("borg_progress") or {}
        percent = progress.get("percent")
        percent = percent if type(percent) in (int, float) and math.isfinite(percent) and 0 <= percent <= 100 else None
        result["jobs"].append({"id": _id(job["key"]), "name": _name(job.get("display_name") or job.get("name")),
                               "status": state,
                               "repository_id": _id(job["repository_key"]) if job.get("repository_key") else "",
                               "last_run": _stamp(recorded.get("timestamp") or job.get("last_timestamp")),
                               **_schedule(job, schedules),
                               "duration_seconds": _number(recorded.get("duration_seconds", job.get("last_duration_seconds"))),
                               "bytes": _number(recorded.get("original_size")),
                               "compressed_bytes": _number(recorded.get("compressed_size")),
                               "deduplicated_bytes": _number(recorded.get("deduplicated_size")),
                               "files_count": _number(recorded.get("files_count")),
                               "exit_code": _number(recorded.get("exit_code", job.get("last_exit_code"))),
                               "reason_code": _code(recorded.get("failure_code") or recorded.get("skip_reason_code")),
                               "run_id": _code(live.get("run_id")) if running else None,
                               "phase": _code(live.get("phase")) if running else None,
                               "percent": percent if running else None,
                               "processed_bytes": _number(progress.get("original_size")) if running else None,
                               "cancel_requested": live.get("cancel_requested") is True,
                               "can_start": allowed and _eligible(job) and not running,
                               "can_cancel": allowed and running and job.get("is_utility") is False
                                   and job.get("standard") == "wizard" and live.get("cancel_allowed") is True
                                   and bool(_code(live.get("run_id"))) and not live.get("cancel_requested", False)})
        stamp = _stamp(job.get("restore_verification_last_test_date"))
        verification = job.get("restore_verification_status")
        if stamp or verification:
            result["restore_verifications"].append({"job_name": _name(job.get("display_name") or job.get("name")),
                                            "status": _status(job.get("restore_verification_last_test_result")),
                                            "checked_at": stamp, "verification": _code(verification),
                                            "valid_until": _stamp(job.get("restore_verification_valid_until")),
                                            "reason_code": _code(job.get("restore_verification_failure_code"))})
        key = job.get("repository_key")
        if key:
            sample = {"id": _id(key), "name": _name(job.get("repository_name")),
                      "bytes": _number(recorded.get("repository_size")),
                      "checked_at": _stamp(recorded.get("repository_check_date")),
                      "measured_at": _stamp(recorded.get("timestamp"))}
            previous = repo_samples.get(key)
            if previous is None or (sample["bytes"] is not None and
                    (sample["measured_at"] or "") > (previous["measured_at"] or "")):
                repo_samples[key] = sample
    # Initial v1 clients require a non-null checked_at in restore_tests. Keep
    # that subset while newer clients read all evidence, including never tested.
    result["restore_tests"] = [r for r in result["restore_verifications"] if r["checked_at"]]
    result["repositories"] = list(repo_samples.values())
    for item in history:
        stamp = _stamp(item.get("timestamp"))
        if not stamp:
            continue
        result["history"].append({"id": _id(str(item.get("job_key")) + stamp + str(item.get("run_id"))),
                                  "job_id": _id(item.get("job_key")),
                                  "job_name": _name(item.get("job_name")), "timestamp": stamp,
                                  "status": _status(item.get("status")),
                                  "reason_code": _code(item.get("failure_code") or item.get("skip_reason_code")),
                                  "exit_code": _number(item.get("exit_code")),
                                  "duration_seconds": _number(item.get("duration_seconds")),
                                  "bytes": _number(item.get("original_size"))})
    return result
