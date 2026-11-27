"""Explicitly approved, bounded run-log reads for mobile clients (#743).

Only server-resolved identities are accepted. Text is transient and never
written to a mobile audit/telemetry stream. Free-form logs remain private data.
"""
from __future__ import annotations

import re
import os
from pathlib import Path

from mobile_log_window import file_window, options

import mobile_auth as auth
from mobile_api import _id, _stamp


def _history(handler) -> list:
    """Use the same bounded, known-job history selection as the snapshot."""
    return handler._get_history("per_page=100&page=1")["entries"]


def _retained(handler, row: dict, request: dict, *, running: bool = False) -> dict:
    """Read only a retained log referenced by the selected server-side record."""
    from history_api import get_history_log
    path = row.get("log_file")
    if not isinstance(path, str) or not path:
        raise auth.MobileError("mobile_log_unavailable", 404)
    result = get_history_log(handler.config, path, window=request, window_running=running)
    if not result["exists"]:
        raise auth.MobileError("mobile_log_unavailable", 404)
    return result["content"]


def read_log(handler, body: dict) -> dict:
    """Navigate an original log by event ID or exact job/run; never accept a path.

    400 rejects malformed identities, 403 missing consent, 404 missing logs and
    409 a replaced/ambiguous run, changed source or observed truncation. Auth is rechecked after reading for revocation.
    No backup operation or unbounded stream is started.
    """
    auth.require_logs(handler.config, handler._mobile_session)
    event = body.get("event_id")
    live = event is None
    request = options(body)
    if set(body) - set(request) != ({"job_id", "run_id"} if live else {"event_id"}):
        raise auth.MobileError("mobile_bad_request", 400)
    opaque = body.get("job_id") if live else event
    if not isinstance(opaque, str) or not re.fullmatch(r"[a-f0-9]{32}", opaque):
        raise auth.MobileError("mobile_bad_request", 400)
    try:
        if not live:
            matches = [r for r in _history(handler) if _id(str(r.get("job_key")) + str(_stamp(r.get("timestamp"))) + str(r.get("run_id"))) == event]
            if len(matches) != 1:
                raise auth.MobileError("mobile_log_unavailable", 404)
            result = _retained(handler, matches[0], request)
        else:
            run = body.get("run_id")
            if not isinstance(run, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", run):
                raise auth.MobileError("mobile_bad_request", 400)
            job = next((j for j in handler._get_jobs()["jobs"] if _id(j["key"]) == opaque), None)
            if not job:
                raise auth.MobileError("mobile_log_unavailable", 404)
            from jobs_api import JobManager, get_job_runtime_state
            manager = JobManager.get()
            result = manager.output_window(job["key"], run, request)
            if result is None:
                state = get_job_runtime_state(handler.config, job["key"])
                if state.get("run_id") == run and state.get("file_activity"):
                    from activity_log import open_activity_run
                    with open_activity_run(handler.config, job["key"], run) as (path, current, handle):
                        info = os.fstat(handle.fileno())
                        identity = f'{info.st_dev}:{info.st_ino}'
                        capture = current.get('capture')
                        if capture:
                            expected = capture.get('active_file_id' if path == Path(capture['active_file']) else 'retained_file_id')
                            if identity != expected:
                                raise auth.MobileError('mobile_job_changed', 409)
                            identity = capture['active_file_id']
                        result = file_window(handle, request, running=bool(current.get('running')), identity='file:' + identity)
                elif state.get("run_id") == run and state.get("log_file"):
                    result = _retained(handler, state, request, running=bool(state.get("running")))
                else:
                    matches = [r for r in _history(handler) if r.get("job_key") == job["key"] and r.get("run_id") == run]
                    if len(matches) != 1:
                        raise auth.MobileError("mobile_job_changed", 409)
                    result = _retained(handler, matches[0], request)
        auth.require_logs(handler.config, handler._mobile_session)
        return result
    except auth.MobileError:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise auth.MobileError("mobile_log_unavailable", 404) from exc
