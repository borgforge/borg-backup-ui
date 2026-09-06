"""Retry read-only startup readiness after storage/old workers recover (#479).

Waiting is not migration consent. This watcher can resume ordinary startup only
when the identity assistant proves that no conversion or explicit continuation
is required. It never prepares a plan/snapshot, acknowledges, or applies one.
"""

import threading

from migration_barrier import data_root


_WATCHERS = {}
_WATCHERS_LOCK = threading.Lock()


def retry_startup_once(config, *, storage_ready, activate, assistant=None):
    """Return ready/waiting/restart_required; callbacks retain startup policy.

    ``storage_ready`` must check every configured runtime mount without waiting
    or creating directories. ``activate`` repeats the normal startup gate under
    exclusive writer ownership before publishing readiness or starting services;
    its True result means startup succeeded, even during empty first setup.
    """
    if assistant is None:
        from identity_migration_api import get_assistant
        assistant = get_assistant(config)
    # Serialize against both Prepare/Run actions, including the gap between
    # read-only eligibility detection and the repeated startup gate.
    if not assistant._operation.acquire(blocking=False):
        return "waiting"
    try:
        if assistant._failed_here:
            return "restart_required"
        # An explicit assistant action may already have completed activation
        # while this observer was asleep. Only an explicit normal state counts;
        # absent startup state must still pass the detection/startup gates.
        startup = config.get("_STARTUP_STATE")
        if isinstance(startup, dict) and startup.get("mode") == "normal":
            return "ready"
        if assistant._busy:
            return "waiting"
        if storage_ready(config) is not True:
            return "waiting"
        result = assistant.startup_detection()
        if not isinstance(result, dict) or result.get("required") is not False:
            return "waiting"
        if assistant._failed_here:
            return "restart_required"
        return "ready" if activate(config) is True else "waiting"
    except Exception:
        # A transient check cannot open the gate. Details belong to the normal
        # startup/assistant diagnostics, never arbitrary exception strings here.
        return "waiting"
    finally:
        assistant._operation.release()


def start_startup_readiness_watch(config, *, storage_ready, activate,
                                 interval_seconds=10, stop_event=None):
    """Start at most one readiness observer for this installation in the UI."""
    key = str(data_root(config))
    with _WATCHERS_LOCK:
        existing = _WATCHERS.get(key)
        if existing is not None and existing.is_alive():
            return existing
        stop = stop_event or threading.Event()
        interval = max(0.01, float(interval_seconds))

        def watch():
            try:
                while not stop.wait(interval):
                    result = retry_startup_once(config, storage_ready=storage_ready, activate=activate)
                    if result in {"ready", "restart_required"}:
                        return
            finally:
                with _WATCHERS_LOCK:
                    if _WATCHERS.get(key) is threading.current_thread():
                        _WATCHERS.pop(key, None)

        thread = threading.Thread(target=watch, name="identity-startup-readiness", daemon=True)
        _WATCHERS[key] = thread
        try:
            thread.start()
        except BaseException:
            _WATCHERS.pop(key, None)
            raise
        return thread
