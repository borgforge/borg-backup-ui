"""Versioned, allowlisted mobile HTTP contract; independent of legacy tokens."""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from urllib.parse import urlparse

import mobile_auth as auth

PREFIX = "/api/mobile/v1/"
BROWSER = "/api/auth/mobile/"
ROUTES = {
    "GET": {PREFIX + "capabilities", PREFIX + "snapshot", BROWSER + "sessions"},
    "POST": {PREFIX + "pair", PREFIX + "exchange", PREFIX + "logout",
             BROWSER + "approve", BROWSER + "revoke"},
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
        elif path not in {PREFIX + "capabilities", PREFIX + "pair", PREFIX + "exchange"}:
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
                "session_expires_in": auth.SESSION_TTL}
    if path == PREFIX + "pair":
        return auth.begin(handler.config, body.get("device_name"), handler._client_ip())
    if path == PREFIX + "exchange":
        return auth.exchange(handler.config, body.get("device_code"))
    if path == BROWSER + "approve":
        return auth.approve(handler.config, handler._mobile_user, body.get("user_code"))
    if path == BROWSER + "sessions":
        return auth.sessions(handler.config, handler._mobile_user)
    if path == BROWSER + "revoke":
        return auth.revoke(handler.config, handler._mobile_user, body.get("session_id"))
    if path == PREFIX + "logout":
        session = handler._mobile_session
        return auth.revoke(handler.config, session["username"], session["id"])
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
    return value if value in {"success", "warning", "error", "running"} else "unknown"


def snapshot(handler) -> dict:
    """Project existing job/history/overview reads without paths, config or logs.

    Missing measurements remain null; no runtime percentage or schedule is
    inferred. History is bounded to the latest 100 records. IDs are opaque.
    """
    jobs = handler._get_jobs()["jobs"]
    history = handler._get_history("per_page=100&page=1")["entries"]
    overview = handler._get_report_overview("days=30&location=all")
    result = {"api_version": 1, "sampled_at": datetime.now(timezone.utc).isoformat(),
              "jobs": [], "history": [], "repositories": [], "restore_tests": [],
              "storage_daily": [{"date": p["date"], "bytes": _number(p.get("repository_bytes"))}
                                for p in overview["daily"]]}
    for job in jobs:
        result["jobs"].append({"id": _id(job["key"]), "name": _name(job.get("display_name") or job.get("name")),
                               "status": "running" if job.get("running") else _status(job.get("last_status")),
                               "repository_id": _id(job["repository_key"]) if job.get("repository_key") else "",
                               "last_run": _stamp(job.get("last_timestamp")), "next_run": None,
                               "duration_seconds": _number(job.get("last_duration_seconds"))})
        stamp = _stamp(job.get("restore_verification_last_test_date"))
        if stamp:
            result["restore_tests"].append({"job_name": _name(job.get("display_name") or job.get("name")),
                                            "status": _status(job.get("restore_verification_last_test_result")), "checked_at": stamp})
        key = job.get("repository_key")
        if key and not any(r["id"] == _id(key) for r in result["repositories"]):
            result["repositories"].append({"id": _id(key), "name": _name(job.get("repository_name")),
                                           "bytes": None, "checked_at": None})
    for item in history:
        stamp = _stamp(item.get("timestamp"))
        if not stamp:
            continue
        result["history"].append({"id": _id(str(item.get("job_key")) + stamp + str(item.get("run_id"))),
                                  "job_name": _name(item.get("job_name")), "timestamp": stamp,
                                  "status": _status(item.get("status")),
                                  "duration_seconds": _number(item.get("duration_seconds")),
                                  "bytes": _number(item.get("original_size"))})
    return result
