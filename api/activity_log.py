"""Bounded access to complete file-activity logs (#463).

The retained file is the queue for slow readers. Cursors are byte offsets in
one immutable run identity; neither requests nor status polling copy the log.
"""

from __future__ import annotations

import codecs
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path

WINDOW_BYTES = 65536
SEARCH_BYTES = 1024 * 1024
def activity_log_path(directory: Path, job_id: str, run_id: str, name: str = "job") -> Path:
    from job_runs import log_filename
    return directory / log_filename(job_id, run_id, name)


def open_activity_file(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("Activity log is not a regular file")
    return os.fdopen(fd, "rb")


def resolve_activity_run(config: dict, job_id: str, run_id: str = "") -> tuple[Path, dict]:
    from jobs_api import JobManager, durable_running_states
    from job_control import read_control_state
    from job_model import validate_job_id
    from job_runs import find_run_status, validate_run_id
    validate_job_id(job_id)
    validate_run_id(run_id)
    memory = JobManager.get().get_state(job_id)
    current = memory if memory.get("running") else durable_running_states(config).get(job_id, memory)
    if current.get("run_id") == run_id:
        state = dict(current)
    else:
        state = find_run_status(config, job_id, run_id)
    control = read_control_state(run_id)
    if control.get("job_id") == job_id:
        if not state:
            state = {**control, "running": not control.get("finished")}
        state["phase"] = control.get("phase", "")
        if control.get("finished") and not state.get("running"):
            state["exit_code"] = control.get("exit_code")
    from activity_log_capture import capture_record, capture_path
    capture = capture_record(job_id, run_id)
    if capture:
        state.setdefault("run_id", run_id)
        state["file_activity"] = True
        state["log_file"] = str(capture_path(capture))
        state["capture"] = capture
        if capture.get("status") in {"saved", "failed"}:
            state["running"] = False
            state["exit_code"] = capture.get("exit_code")
        state["log_persistence_failed"] = capture.get("status") == "failed" or (capture.get("status") == "running" and not state.get("running"))
    if not state or not state.get("file_activity") or not state.get("log_file"):
        raise FileNotFoundError("File activity is not available for this run")
    return Path(state["log_file"]), state


@contextmanager
def open_activity_run(config: dict, job_id: str, run_id: str = ""):
    # RAM can be released between resolving its path and opening it. The saved
    # location is published first, allowing a retry without resetting cursors.
    for attempt in range(2):
        path, state = resolve_activity_run(config, job_id, run_id)
        try:
            handle = open_activity_file(path)
            break
        except FileNotFoundError:
            if attempt:
                raise
    with handle:
        yield path, state, handle


def _number(qs: dict, name: str, default: int) -> int:
    raw = (qs.get(name) or [str(default)])[0]
    if len(raw) > 20 or not raw.isascii() or not raw.isdecimal():
        raise ValueError(f"Invalid log {name}")
    return int(raw)


def read_window(handle, start: int, end: int, *, running: bool = False, align_start: bool = False, align_end: bool = False) -> dict:
    """Return a bounded UTF-8 slice. Adjacent returned cursors lose no bytes."""
    handle.seek(start)
    data = handle.read(min(WINDOW_BYTES + 4, end - start))
    # Arbitrary seeks (tail or search context) can land inside a character.
    skip = 0
    while skip < min(3, len(data)) and data[skip] & 0xC0 == 0x80:
        skip += 1
    data = data[skip:]
    start += skip
    if align_start and start:
        newline = data.find(b"\n")
        if 0 <= newline < len(data) - 1:
            start += newline + 1
            data = data[newline + 1:]
    if align_end:
        newline = data.rfind(b"\n")
        if newline >= 0:
            data = data[:newline + 1]
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    text = decoder.decode(data, final=not running and handle.tell() >= end)
    pending, _flag = decoder.getstate()
    return {"start": start, "end": start + len(data) - len(pending), "text": text}


def get_activity_window(config: dict, qs: dict) -> dict:
    job = (qs.get("job_id") or [""])[0]
    run = (qs.get("run_id") or [""])[0]
    with open_activity_run(config, job, run) as (_path, state, handle):
        info = os.fstat(handle.fileno())
        size = info.st_size
        identity = f"{info.st_dev}:{info.st_ino}"
        capture = state.get("capture")
        if capture:
            expected_identity = capture.get("active_file_id" if _path == Path(capture["active_file"]) else "retained_file_id")
            if identity != expected_identity:
                raise ValueError("The log file has been replaced; reopen the log")
            # The original file identity stays valid across the verified copy.
            identity = capture["active_file_id"]
        if qs.get("file_id") and qs["file_id"][0] != identity:
            raise ValueError("The log file has been replaced; reopen the log")
        result = {
            "run_id": state["run_id"], "file_id": identity, "size": size,
            "running": bool(state.get("running")), "exit_code": state.get("exit_code"),
            "phase": state.get("phase", ""),
            "log_persistence_failed": bool(state.get("log_persistence_failed")),
        }
        if "status" in qs:
            return result
        if "search" in qs:
            query = qs["search"][0]
            if not query or len(query) > 256:
                raise ValueError("Search text must contain 1 to 256 characters")
            needle = query.encode("utf-8")
            start = _number(qs, "start", 0)
            limit = min(size, _number(qs, "search_end", size))
            if start > limit:
                raise ValueError("Search cursor exceeds log size")
            handle.seek(start)
            data = handle.read(min(SEARCH_BYTES + len(needle) - 1, limit - start))
            index = data.find(needle)
            found = start + index if index >= 0 else None
            result.update({
                "match": found, "search_end": limit,
                "next": found + len(needle) if found is not None else min(start + SEARCH_BYTES, limit),
                "search_done": found is not None or start + SEARCH_BYTES >= limit,
            })
            if found is None:
                return result
            start = max(0, found - 1024)
            end = min(size, start + WINDOW_BYTES)
        elif "before" in qs:
            end = _number(qs, "before", size)
            if end > size:
                raise ValueError("The log file has shrunk; reopen the log")
            start = max(0, end - WINDOW_BYTES)
        elif "start" in qs:
            start = _number(qs, "start", 0)
            if start > size:
                raise ValueError("The log file has shrunk; reopen the log")
            end = min(size, start + WINDOW_BYTES + 4)
        else:
            start, end = max(0, size - WINDOW_BYTES), size
        # Do not prematurely decode a character split across a growing EOF or
        # an artificial block boundary. Retry its bytes on the next request.
        result.update(read_window(
            handle, start, end, running=result["running"] or end < size,
            align_start="search" not in qs and "start" not in qs,
            align_end="search" not in qs and "start" in qs and end < size,
        ))
        return result
