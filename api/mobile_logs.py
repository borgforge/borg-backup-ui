"""Explicitly approved, bounded run-log reads for mobile clients (#743).

Only server-resolved identities are accepted. Text is transient, masked and never
written to a mobile audit/telemetry stream. Free-form logs remain private data.
"""
from __future__ import annotations

import re

import mobile_auth as auth
from mobile_api import _id, _stamp
from security_utils import mask_secrets


def _masked_tail(text: str) -> str:
    """Mask full lines before limiting output; omit private file activity/details.

    Common secret assignments, credentials, key material, paths and addresses are
    suppressed. This is defense in depth, not a guarantee for arbitrary custom
    script prose; explicit log permission remains mandatory.
    """
    lines = []
    for line in text.splitlines()[-200:]:
        if (len(line) > 8192 or re.search(r"(?i)(password|passphrase|token|secret|authorization|private key|passcommand|api[_-]?key)", line)
                or re.search(r"(?:^|\s)[A-Z?+-] [^\s]", line)
                or re.search(r"[A-Za-z0-9+/=_-]{40,}", line)):
            lines.append("[private detail omitted]")
            continue
        line = mask_secrets(line)
        line = re.sub(r"(?:[a-z][a-z0-9+.-]*://|[\w.-]+@)[^\s]+", "[address]", line, flags=re.I)
        # Omit the entire line to cover spaces in paths and quoted filenames.
        if re.search(r"(?:^|[\s=:('\"])(?:/|~[/\\]|[A-Za-z]:\\)|\b(?:\d{1,3}\.){3}\d{1,3}\b", line):
            lines.append("[private detail omitted]")
            continue
        lines.append(re.sub(r"[\x00-\x1f\x7f]", "", line))
    result = "\n".join(lines)
    if len(result) > 6000:
        result = result[-6000:].partition("\n")[2]
    return result


def _history(handler) -> list:
    """Use the same bounded, known-job history selection as the snapshot."""
    return handler._get_history("per_page=100&page=1")["entries"]


def _retained(handler, row: dict) -> str:
    """Read only a retained log referenced by the selected server-side record."""
    from history_api import get_history_log
    path = row.get("log_file")
    if not isinstance(path, str) or not path:
        raise auth.MobileError("mobile_log_unavailable", 404)
    result = get_history_log(handler.config, path, tail_bytes=8192)
    if not result["exists"]:
        raise auth.MobileError("mobile_log_unavailable", 404)
    return result["content"]


def read_log(handler, body: dict) -> dict:
    """Return a masked tail by event ID or exact job/run; never accept a path.

    400 rejects malformed identities, 403 missing consent, 404 missing logs and
    409 a replaced/ambiguous run. Auth is rechecked after reading for revocation.
    No backup operation or unbounded stream is started.
    """
    auth.require_logs(handler.config, handler._mobile_session)
    event = body.get("event_id")
    live = event is None
    if set(body) != ({"job_id", "run_id"} if live else {"event_id"}):
        raise auth.MobileError("mobile_bad_request", 400)
    opaque = body.get("job_id") if live else event
    if not isinstance(opaque, str) or not re.fullmatch(r"[a-f0-9]{32}", opaque):
        raise auth.MobileError("mobile_bad_request", 400)
    running = False
    try:
        if not live:
            matches = [r for r in _history(handler) if _id(str(r.get("job_key")) + str(_stamp(r.get("timestamp"))) + str(r.get("run_id"))) == event]
            if len(matches) != 1:
                raise auth.MobileError("mobile_log_unavailable", 404)
            text = _retained(handler, matches[0])
        else:
            run = body.get("run_id")
            if not isinstance(run, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", run):
                raise auth.MobileError("mobile_bad_request", 400)
            job = next((j for j in handler._get_jobs()["jobs"] if _id(j["key"]) == opaque), None)
            if not job:
                raise auth.MobileError("mobile_log_unavailable", 404)
            from jobs_api import JobManager, get_job_runtime_state
            manager = JobManager.get()
            result = manager.output_tail(job["key"], run)
            if result is not None:
                text, running = result["text"], result["running"]
            else:
                state = get_job_runtime_state(handler.config, job["key"])
                if state.get("run_id") == run and state.get("file_activity"):
                    from activity_log import get_activity_window
                    window = get_activity_window(handler.config, {"job": [job["key"]], "run": [run]})
                    text, running = window["text"], window["running"]
                elif state.get("run_id") == run and state.get("log_file"):
                    text, running = _retained(handler, state), bool(state.get("running"))
                else:
                    matches = [r for r in _history(handler) if r.get("job_key") == job["key"] and r.get("run_id") == run]
                    if len(matches) != 1:
                        raise auth.MobileError("mobile_job_changed", 409)
                    text = _retained(handler, matches[0])
            if running:
                text = text.rsplit("\n", 1)[0] if "\n" in text else ""  # Do not expose a growing partial line.
        result = {"text": _masked_tail(text), "running": running, "limited": True, "redacted": True}
        auth.require_logs(handler.config, handler._mobile_session)
        return result
    except auth.MobileError:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise auth.MobileError("mobile_log_unavailable", 404) from exc
