"""Measured, configured job steps for live and saved job cards (#579).

This ledger observes existing actions; it never decides execution or recovery.
Only structured counters/reasons are retained, never subprocess output.
"""
from contextlib import contextmanager, nullcontext
from functools import wraps
import copy
import time


class JobWorkflow:
    """Keep ordered step results; optional controller writes are best-effort."""

    def __init__(self, names, controller=None):
        self.steps = [{"id": name, "status": "pending"} for name in names]
        self.controller = controller
        self.publish()

    @classmethod
    def configured(cls, *, hooks=None, docker=False, vms=False, prune=True, controller=None, databases=False,
                   docker_sequence=False):
        """Build the existing runner order from enabled hooks/workload policies.

        ``docker_sequence`` replaces the Docker stop/start pair with one step
        for the per-group archives that precede the main archive.
        """
        hooks = hooks or {}
        docker_pair = docker and not docker_sequence
        names = (["pre_script"] if hooks.get("pre") else [])
        names += (["database_backup"] if databases else [])
        names += (["docker_sequence"] if docker_sequence else [])
        names += (["stop_docker"] if docker_pair else []) + (["stop_vms"] if vms else [])
        names += ["create"]
        names += (["start_docker"] if docker_pair else []) + (["start_vms"] if vms else [])
        names += (["prune"] if prune else []) + ["compact", "check"]
        names += (["post_script"] if hooks.get("post") else [])
        return cls(names, controller)

    def get(self, name):
        """Return a configured step or None (disabled steps are never added)."""
        return next((step for step in self.steps if step["id"] == name), None)

    def publish(self):
        """Publish a snapshot without letting status I/O interrupt the backup."""
        callback = getattr(self.controller, "update_job_steps", None)
        if callable(callback):
            try:
                callback(self.steps)
            except (OSError, ValueError, TypeError):
                pass

    def update(self, name, **values):
        """Merge measured fields into a configured step and publish them."""
        step = self.get(name)
        if step is not None:
            step.update(copy.deepcopy(values))
            self.publish()

    @contextmanager
    def track(self, name):
        """Measure one action, preserve explicit outcomes, re-raise exceptions."""
        step = self.get(name)
        if step is None or step["status"] != "pending":
            yield
            return
        started = time.monotonic()
        self.update(name, status="running", started_at=time.time())
        try:
            yield
        except BaseException:
            self.update(name, status="error")
            raise
        else:
            if step["status"] == "running":
                step["status"] = "success"
        finally:
            if step["status"] != "skipped":
                step.update(duration_seconds=round(max(0, time.monotonic() - started), 3),
                            finished_at=time.time())
            self.publish()

    def finalize(self, reason="not_run"):
        """Mark remaining pending steps as unexecuted without inventing timings."""
        for step in self.steps:
            if step["status"] == "pending":
                step.update(status="skipped", reason=reason)
            elif step["status"] == "running":
                step.update(status="interrupted")
        self.publish()


def tracked_runtime_step(name):
    """Observe a BackupJob runtime action when it has a workflow ledger."""
    def decorate(method):
        @wraps(method)
        def tracked(self, *args, **kwargs):
            workflow = getattr(self, "workflow", None)
            with workflow.track(name) if workflow is not None else nullcontext():
                return method(self, *args, **kwargs)
        return tracked
    return decorate
