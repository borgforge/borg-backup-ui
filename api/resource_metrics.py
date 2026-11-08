"""Read-only, shared Linux resource sampling for the dashboard (#602).

No Borg commands, workload controls or metric files are created. History is
bounded and volatile; collection starts on the first authenticated request.
"""

from __future__ import annotations

from collections import deque
import copy
import os
from pathlib import Path
import threading
import time


def host_counters(proc: Path) -> dict:
    """Read host CPU ticks and RAM bytes; absent/invalid counters raise errors.

    Guest ticks are already included in user/nice and must not be counted twice.
    Available RAM includes reclaimable memory, as reported by Linux MemAvailable.
    """
    fields = (proc / "stat").read_text().splitlines()[0].split()
    if fields[0] != "cpu" or len(fields) < 6:
        raise ValueError("Missing aggregate CPU counters")
    ticks = [int(value) for value in fields[1:9]]
    memory = {line.split()[0].rstrip(":"): int(line.split()[1]) * 1024
              for line in (proc / "meminfo").read_text().splitlines()
              if line.startswith(("MemTotal:", "MemAvailable:"))}
    return {"ticks": sum(ticks), "idle": ticks[3] + ticks[4],
            "memory_total_bytes": memory["MemTotal"],
            "memory_available_bytes": memory["MemAvailable"]}


def cpu_percent(previous: dict | None, current: dict) -> float | None:
    """Return busy CPU percent over an interval, or None without valid deltas."""
    if previous is None:
        return None
    total = current["ticks"] - previous["ticks"]
    idle = current["idle"] - previous["idle"]
    if total <= 0 or idle < 0 or idle > total:
        return None
    return round(100 * (total - idle) / total, 1)


def protected_groups(root: Path, proc: Path, runs: list[dict]) -> list[dict]:
    """Read only plugin restore-test groups owned by a live run supervisor.

    Match a member's PPid to the lock owner (keeper/worker are direct children).
    Waiting tests have no group and must not inherit another test's measurements.
    Groups disappearing during a read are omitted; no filesystem paths are exposed.
    """
    owners = {run["pid"]: run for run in runs if run["operation"] == "restore_test"}
    result = []
    for group in root.glob("borg-backup-ui-restore-*") if owners else []:
        try:
            owner = None
            for pid in (group / "cgroup.procs").read_text().split():
                try:
                    parent = next(int(line.split()[1]) for line in
                                  (proc / pid / "status").read_text().splitlines() if line.startswith("PPid:"))
                    if parent in owners:
                        owner = owners[parent]
                        break
                except (OSError, ValueError, StopIteration):
                    continue
            if owner is None:
                continue
            counters = dict(line.split() for line in (group / "cpu.stat").read_text().splitlines())
            limit = (group / "memory.max").read_text().strip()
            result.append({"id": group.name, "job_key": owner["job_key"],
                           "run_id": owner["run_id"], "usage_usec": int(counters["usage_usec"]),
                           "memory_bytes": int((group / "memory.current").read_text()),
                           "memory_limit_bytes": None if limit == "max" else int(limit)})
        except (OSError, ValueError, KeyError):
            continue
    return result


class ResourceSampler:
    """One shared sampler with ten minutes of history and no persistent writes.

    Sample every second during tracked runs, every ten seconds otherwise. The
    thread continues when browsers close; daemon shutdown discards its history.
    Failures invalidate the affected measurements without affecting jobs.
    """

    def __init__(self, config: dict, *, proc: Path = Path("/proc")):
        self.config = dict(config)
        self.proc = proc
        self.lock = threading.Lock()
        self.history = deque(maxlen=600)
        self.latest = None
        self.previous_host = None
        self.previous_groups = {}
        self.metadata_at = -float("inf")
        self.reserve = None
        self.thread = None
        self.stop = threading.Event()

    def _metadata(self, now: float) -> None:
        """Refresh configured reserve at most once per ten seconds, best effort."""
        if now - self.metadata_at < 10:
            return
        self.metadata_at = now
        try:
            from config_api import read_expanded_conf
            conf = read_expanded_conf(self.config)
            self.reserve = int(conf.get("RESTORE_TEST_HOST_RESERVE_MIB", 1024)) * 1024**2
        except (OSError, ValueError, TypeError):
            self.reserve = None

    def sample(self) -> dict:
        """Collect a snapshot and explicit runner activity, updating bounded history.

        Called by one thread. Queue state is independent of cgroup measurements;
        missing runner metadata remains unknown.
        """
        from jobs_api import active_resource_locks
        from restore_test_resources import cgroup_root
        now = time.monotonic()
        self._metadata(now)
        host = {"cpu_percent": None, "memory_total_bytes": None, "memory_available_bytes": None}
        try:
            current = host_counters(self.proc)
            host = {key: current[key] for key in ("memory_total_bytes", "memory_available_bytes")}
            host["cpu_percent"] = cpu_percent(self.previous_host, current)
            self.previous_host = current
        except (OSError, ValueError, KeyError, IndexError):
            self.previous_host = None
        runs = []
        runs_available = True
        try:
            seen = set()
            for row in active_resource_locks(self.config):
                identity = (row["pid"], row["job_key"], row["operation"], row["run_id"])
                if identity not in seen:
                    seen.add(identity)
                    runs.append({**{key: row[key] for key in ("pid", "job_key", "operation", "run_id")},
                                 "activity_state": row.get("activity_state", "unknown")})
        except (OSError, ValueError):
            runs_available = False
        groups = []
        try:
            if any(run["operation"] == "restore_test" for run in runs):
                groups = protected_groups(cgroup_root(), self.proc, runs)
        except (OSError, ValueError, IndexError):
            pass
        previous = self.previous_groups
        self.previous_groups = {}
        cores = max(1, os.cpu_count() or 1)
        for group in groups:
            usage = group.pop("usage_usec")
            before = previous.get(group["id"])
            self.previous_groups[group["id"]] = (now, usage)
            group["cpu_percent"] = None
            if before and now > before[0] and usage >= before[1]:
                group["cpu_percent"] = round(min(100, 100 * (usage - before[1]) / ((now - before[0]) * 1e6 * cores)), 1)
        snapshot = {"timestamp": time.time(), "host": host,
                    "runs": [{key: value for key, value in run.items() if key != "pid"} for run in runs],
                    "runs_available": runs_available, "protected_tests": groups,
                    "configured_reserve_bytes": self.reserve, "interval_seconds": 1 if runs else 10}
        with self.lock:
            self.latest = snapshot
            self.history.append((now, snapshot))
            while self.history and now - self.history[0][0] > 600:
                self.history.popleft()
        return snapshot

    def _loop(self) -> None:
        """Keep sampling independently of browser polling; mark unexpected failures stale."""
        delay = 1
        while not self.stop.wait(delay):
            try:
                delay = self.sample()["interval_seconds"]
            except Exception:
                # Optional observability must never affect the backup/restore path.
                delay = 10

    def start(self) -> None:
        """Initialize counters and launch the service-owned daemon once."""
        if self.thread is None:
            self.sample()
            self.thread = threading.Thread(target=self._loop, name="resource-metrics", daemon=True)
            self.thread.start()

    def snapshot(self) -> dict:
        """Copy current data and a five-second trend (at most 121 points).

        Raw samples remain in memory at the sampling cadence; trend thinning
        limits network payload. No per-run peak or complete run history is claimed.
        """
        with self.lock:
            if self.latest is None:
                return {"available": False, "stale": True, "history": []}
            result = copy.deepcopy(self.latest)
            history = []
            last = -float("inf")
            for when, sample in self.history:
                if when - last >= 5 or sample is self.latest:
                    history.append({"timestamp": sample["timestamp"], "host": sample["host"],
                                    "protected_tests": sample["protected_tests"]})
                    last = when
            result["history"] = copy.deepcopy(history)
            result["available"] = True
            result["stale"] = time.monotonic() - self.history[-1][0] > max(5, result["interval_seconds"] * 3)
            return result


_sampler = None
_sampler_lock = threading.Lock()


def get_resource_metrics(config: dict) -> dict:
    """Return shared, authenticated dashboard telemetry; never start one thread per client."""
    global _sampler
    with _sampler_lock:
        if _sampler is None:
            sampler = ResourceSampler(config)
            sampler.start()
            _sampler = sampler
        elif _sampler.config != config:
            # Configuration replacement is atomic; the next sample uses the
            # current data root without adding another sampling thread.
            _sampler.config = dict(config)
            _sampler.metadata_at = -float("inf")
        return _sampler.snapshot()
