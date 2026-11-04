"""Fail-closed cgroup v2 supervision for restore-test workers on Linux."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import subprocess
import select
import signal
import sys
import time
import uuid


class ResourceGuardError(RuntimeError):
    """A test could not run safely; ``code`` identifies the report failure."""

    def __init__(self, code: str, message: str, *, cancelled: bool = False):
        super().__init__(message)
        self.code = code
        self.cancelled = cancelled


def available_memory() -> int:
    """Read Linux MemAvailable in bytes; fail closed if it is unavailable."""
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise OSError("MemAvailable is unavailable")


def cgroup_root() -> Path:
    """Find the cgroup v2 mount; v1-only systems are explicitly unsupported."""
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        before, _, after = line.partition(" - ")
        if after.split()[0] == "cgroup2":
            return Path(before.split()[4].replace("\\040", " ").replace("\\134", "\\"))
    raise OSError("A writable cgroup v2 memory controller is required")


class MemoryGroup:
    """Own one empty cgroup and enforce a combined worker/descendant RAM limit.

    Creation may enable the memory controller at the hierarchy root. Only
    plugin-owned groups are inspected/removed. Other processes are never moved.
    ``close`` kills remaining members and requires an empty group before removal;
    an already removed group is accepted, but missing files in a live group fail.
    A small OOM-exempt keeper holds the group until counters have been collected,
    preventing host cleanup of empty groups. It never launches workload children.
    """

    def __init__(self, limit: int):
        self.path = None
        self.keeper = None
        root = cgroup_root()
        for old in root.glob("borg-backup-ui-restore-*"):
            if "populated 1" in (old / "cgroup.events").read_text():
                raise OSError("An earlier restore-test worker is still active; inspect its log")
            old.rmdir()
        if "memory" not in (root / "cgroup.controllers").read_text().split():
            raise OSError("The cgroup v2 memory controller is unavailable")
        if "memory" not in (root / "cgroup.subtree_control").read_text().split():
            (root / "cgroup.subtree_control").write_text("+memory")
        self.path = root / f"borg-backup-ui-restore-{uuid.uuid4().hex}"
        self.path.mkdir()
        try:
            for name in ("memory.max", "memory.oom.group", "memory.events", "cgroup.kill",
                         "cgroup.events", "cgroup.procs"):
                if not (self.path / name).exists():
                    raise OSError(f"Required cgroup interface is unavailable: {name}")
            (self.path / "memory.max").write_text(str(limit))
            (self.path / "memory.oom.group").write_text("1")
            if (self.path / "memory.swap.max").exists():
                (self.path / "memory.swap.max").write_text("0")
            if int((self.path / "memory.max").read_text()) != limit:
                raise OSError("The kernel did not accept the memory limit")
            self._start_keeper()
        except BaseException:
            try:
                self.close()
            except OSError:
                # Keep the setup failure, rather than replacing it with cleanup.
                # The next protected run will inspect any remaining owned group.
                pass
            raise

    def _start_keeper(self) -> None:
        """Pin the group with an idle process; require its startup acknowledgement.

        The keeper requires permission to set its own oom_score_adj to -1000.
        A pipe EOF makes it exit if the supervisor dies; no workload inherits it.
        """
        self.keeper = subprocess.Popen(
            [sys.executable, "-E", "-s", "-S", "-B", str(Path(__file__).resolve()), "--keepalive", str(self.path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True,
        )
        ready, _, _ = select.select([self.keeper.stdout], [], [], 5)
        if not ready or self.keeper.stdout.read(1) != b"1" or self.keeper.poll() is not None:
            raise OSError("The memory-group keeper could not start (requires OOM-protection permission)")
        self.keeper.stdout.close()

    def check_alive(self) -> None:
        """Fail closed if the process retaining final memory counters has exited."""
        if self.keeper is None or self.keeper.poll() is not None:
            raise OSError("The memory-group keeper exited before final counter collection")

    def _stop_keeper(self) -> None:
        """Close the lifeline and reap the keeper, including failed startup."""
        keeper = self.keeper
        if keeper is None:
            return
        try:
            keeper.stdin.close()
            try:
                keeper.wait(timeout=2)
            except subprocess.TimeoutExpired:
                keeper.kill()
                keeper.wait()
        finally:
            keeper.stdout.close()
            self.keeper = None

    def events(self) -> dict[str, int]:
        """Return kernel memory-event counters for this fresh group."""
        self.check_alive()
        events = {key: int(value) for key, value in
                  (line.split() for line in (self.path / "memory.events").read_text().splitlines())}
        self.check_alive()
        return events

    def kill(self) -> None:
        """Kill all workload members, including descendants in other sessions."""
        (self.path / "cgroup.kill").write_text("1")

    def close(self) -> None:
        """Clean up the workload group and always reap its keeper."""
        try:
            self._remove_group()
        finally:
            self._stop_keeper()

    def _remove_group(self) -> None:
        """Remove the empty group idempotently; fail if an existing group is unreadable.

        A concurrent removal is harmless here. Missing final memory counters are
        still an error in ``events`` and cannot turn an unverified run into success.
        """
        if self.path is None:
            return
        try:
            if "populated 1" in (self.path / "cgroup.events").read_text():
                self.kill()
            for _ in range(40):
                if "populated 1" not in (self.path / "cgroup.events").read_text():
                    self.path.rmdir()
                    self.path = None
                    return
                time.sleep(0.05)
            raise OSError("Restore-test descendants did not exit; resources remain reserved")
        except FileNotFoundError:
            try:
                self.path.stat()
            except FileNotFoundError:
                self.path = None
                return
            raise


def check_cancelled(cancel_requested=None) -> None:
    """Raise a marked ResourceGuardError when the optional predicate requests cancellation."""
    if cancel_requested is not None and cancel_requested():
        raise ResourceGuardError("RT_CANCELLED", "Restore test cancelled by user", cancelled=True)


def run_guarded(command: list[str], env: dict, lock_dir: Path, limit_mib: int,
                reserve_mib: int, log, *, cancel_requested=None) -> int:
    """Serialize protected tests and supervise a separately executed worker.

    Limit applies to worker and children together; the small supervisor remains
    outside so it can report OOM failures. Reserve is checked before launch and
    polled during execution; it is not a kernel-enforced reservation for others.
    Unsupported enforcement, insufficient memory and OOM raise ResourceGuardError.
    The optional cancellation predicate is checked while queued and running;
    cancellation kills/reaps the worker group before releasing the queue lock.
    """
    limit, reserve = limit_mib * 1024**2, reserve_mib * 1024**2
    if limit_mib < 256 or reserve_mib < 256:
        raise ResourceGuardError("RT_RESOURCE_CONFIG", "Memory limit and host reserve must each be at least 256 MiB")
    group = None
    proc = None
    def interrupted(signum, _frame):
        """Unwind supervision so cancellation also cleans up worker descendants."""
        raise ResourceGuardError("RT_WORKER_INTERRUPTED", f"Restore-test supervisor received signal {signum}", cancelled=True)
    handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
        with (lock_dir / "restore-test-memory.lock").open("a") as lock:
            waiting = False
            while True:
                check_cancelled(cancel_requested)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if not waiting:
                        log("Waiting for the other memory-limited restore test to finish")
                        waiting = True
                    time.sleep(0.1)
            try:
                if available_memory() < limit + reserve:
                    raise ResourceGuardError("RT_HOST_MEMORY_LOW",
                                             f"Insufficient available RAM for {limit_mib} MiB test budget plus {reserve_mib} MiB host reserve")
                group = MemoryGroup(limit)
                log(f"Memory protection active: {limit_mib} MiB for worker and Borg children; host reserve {reserve_mib} MiB; group retained until final counter check")
                launch = [sys.executable, "-E", "-s", "-S", "-B", str(Path(__file__).resolve()), str(group.path), *command]
                proc = subprocess.Popen(launch, env=env)
                while proc.poll() is None:
                    check_cancelled(cancel_requested)
                    group.check_alive()
                    if available_memory() < reserve:
                        group.kill()
                        raise ResourceGuardError("RT_HOST_MEMORY_LOW", "Restore test stopped because available host RAM fell below the reserve")
                    time.sleep(0.1)
                check_cancelled(cancel_requested)
                events = group.events()
                log(f"Final memory counters: oom={events.get('oom', 0)}, oom_kill={events.get('oom_kill', 0)}")
                if events.get("oom", 0):
                    raise ResourceGuardError("RT_MEMORY_LIMIT", f"Restore test exceeded its {limit_mib} MiB memory budget")
                if events.get("oom_kill", 0):
                    raise ResourceGuardError("RT_HOST_MEMORY_LOW", "The kernel killed a restore-test process during host memory exhaustion")
                if proc.returncode < 0:
                    raise ResourceGuardError("RT_WORKER_INTERRUPTED", f"Restore-test worker ended with signal {-proc.returncode}")
                if proc.returncode == 125:
                    raise ResourceGuardError("RT_RESOURCE_UNAVAILABLE", "The restore-test worker could not enter its memory group")
                return proc.returncode
            finally:
                failure = sys.exc_info()[1]
                try:
                    if group is not None:
                        try:
                            group.close()
                        except OSError as exc:
                            if failure is None:
                                raise
                            log(f"WARNING: Memory group cleanup also failed ({type(exc).__name__}): {exc}")
                finally:
                    if proc is not None:
                        # The launcher may not yet have joined the cgroup.
                        if proc.poll() is None:
                            proc.kill()
                        proc.wait()
    except OSError as exc:
        raise ResourceGuardError("RT_RESOURCE_UNAVAILABLE",
                                 f"Memory protection unavailable ({type(exc).__name__}): {exc}") from exc
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def keep_group_alive(path: Path) -> None:
    """Hold a group until supervisor pipe EOF, exempting only this idle process.

    Linux memory.oom.group excludes oom_score_adj=-1000 processes. The separate
    workload launcher resets its own score to 0; no Borg process is exempted.
    Startup failures propagate as OSError and produce no ready acknowledgement.
    """
    score = Path("/proc/self/oom_score_adj")
    score.write_text("-1000")
    if score.read_text().strip() != "-1000":
        raise OSError("The kernel did not accept keeper OOM protection")
    (path / "cgroup.procs").write_text(str(os.getpid()))
    os.write(1, b"1")
    os.close(1)
    os.read(0, 1)


def launch_worker(path: Path, command: list[str]) -> None:
    """Join the limited group and exec the workload with normal OOM eligibility.

    Raises OSError before exec if either the OOM score or group cannot be set.
    """
    Path("/proc/self/oom_score_adj").write_text("0")
    (path / "cgroup.procs").write_text(str(os.getpid()))
    os.execvpe(command[0], command, os.environ)


if __name__ == "__main__":
    # Join before importing the runner or starting Borg, then replace the launcher.
    try:
        if sys.argv[1] == "--keepalive":
            keep_group_alive(Path(sys.argv[2]))
            sys.exit(0)
        launch_worker(Path(sys.argv[1]), sys.argv[2:])
    except OSError:
        sys.exit(125)
