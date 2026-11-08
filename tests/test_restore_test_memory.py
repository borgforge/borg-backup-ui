"""Bounded listing, resource failure and retained evidence regressions (#599)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tracemalloc

import pytest

from restore_test_io import ArchiveSample, run_borg
from restore_test_reports import save_report
from restore_test_resources import MemoryGroup
import restore_test_resources as resources
from job_fixtures import job_id


def test_large_listing_has_bounded_memory_and_exact_regular_file_count():
    sample = ArchiveSample(1000)
    tracemalloc.start()
    try:
        for index in range(200_000):
            sample.feed(json.dumps({"type": "-", "path": f"folder/{index}"}).encode() + b"\n")
            if index % 100 == 0:
                sample.feed(b'{"type":"d","path":"directory"}\n')
        sample.finish()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert sample.count == 200_000
    assert len(set(sample.paths)) == 1000
    assert peak < 4 * 1024**2
    # The reservoir must consider the complete stream, not only its first entries.
    assert max(int(path.split("/")[1]) for path in sample.paths) > 190_000


def test_listing_handles_split_unicode_legacy_selection_and_final_line():
    sample = ArchiveSample(2, first=True)
    data = b'\n'.join(json.dumps({"type": "-", "path": path}, ensure_ascii=False).encode()
                      for path in ["one", "gr\u00fc\u00dfe", "three"])
    for byte in data:
        sample.feed(bytes([byte]))
    sample.finish()
    assert sample.count == 3
    assert sample.paths == ["one", "gr\u00fc\u00dfe"]


@pytest.mark.parametrize("data", [b"not-json\n", b"[]\n", b"x" * (1024**2 + 1)])
def test_listing_rejects_invalid_or_unbounded_lines(data):
    with pytest.raises(ValueError):
        ArchiveSample(1).feed(data)


@pytest.fixture
def borg_env(tmp_path):
    script = tmp_path / "borg"
    script.write_text(f"#!{sys.executable}\n" + '''
import os, sys, time
if sys.argv[1] == 'stream':
    for i in range(10000):
        os.write(2, b'x' * 128)
        os.write(1, ('{"type":"-","path":"%d"}\\n' % i).encode())
elif sys.argv[1] == 'hang':
    pid = os.fork()
    if pid:
        open(sys.argv[2], 'w').write(str(pid))
    time.sleep(60)
elif sys.argv[1] == 'overflow':
    os.write(1, b'x' * (2 * 1024**2))
''')
    script.chmod(0o755)
    return dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))


def test_borg_drains_stderr_while_streaming_stdout(borg_env):
    sample = ArchiveSample(10)
    result = run_borg(["stream"], borg_env, 10, sample.feed)
    sample.finish()
    assert result.returncode == 0
    assert sample.count == 10_000
    assert len(sample.paths) == 10
    assert result.stdout == ""
    assert len(result.stderr) == 65536


def test_borg_timeout_kills_descendants_even_without_output(tmp_path, borg_env):
    child_file = tmp_path / "child-pid"
    started = time.monotonic()
    result = run_borg(["hang", str(child_file)], borg_env, 1)
    assert result.returncode == 124
    assert time.monotonic() - started < 5
    pid = int(child_file.read_text())
    for _ in range(50):
        status = Path(f"/proc/{pid}/status")
        try:
            if "State:\tZ" in status.read_text():
                break
        except (FileNotFoundError, ProcessLookupError):
            break
        time.sleep(0.02)
    else:
        pytest.fail("Borg descendant survived the timeout")


def test_nonstreaming_output_overflow_fails(borg_env):
    result = run_borg(["overflow"], borg_env, 10)
    assert result.returncode == 2
    assert "Invalid Borg output" in result.stderr


def test_report_history_preserves_failed_retry_and_legacy_bytes(tmp_path, monkeypatch):
    from restore_tests_api import list_restore_tests
    key = job_id("appdata_local")
    monkeypatch.setattr("job_identity.active_job_ids", lambda _config: {key})
    latest = tmp_path / f"{key}.test"
    original = b'{"job_id":"' + key.encode() + b'","test_result":"failed","report_id":"old"}'
    latest.write_bytes(original)
    data = {"job_id": key, "report_id": "new", "test_result": "success", "log_file": "/logs/test.log"}
    save_report(latest, data)
    save_report(latest, data)
    files = list((tmp_path / "runs" / key).glob("*.test"))
    assert len(files) == 2
    assert original in [p.read_bytes() for p in files]
    config = {"RESTORE_TEST_STATUS_DIR": str(tmp_path)}
    assert len(list_restore_tests(config)) == 1
    history = list_restore_tests(config, history=True)
    assert {item["report_id"] for item in history} == {"new", "old"}
    assert next(item for item in history if item["report_id"] == "new")["log_file"] == "/logs/test.log"


def test_history_write_failure_keeps_previous_result(tmp_path, monkeypatch):
    import restore_test_reports
    latest = tmp_path / "job.test"
    latest.write_text("unreadable legacy report")
    def fail(*_args):
        raise OSError("disk full")
    monkeypatch.setattr(restore_test_reports, "_atomic_write", fail)
    with pytest.raises(OSError):
        save_report(latest, {"job_id": job_id("appdata_local")})
    assert latest.read_text() == "unreadable legacy report"


@pytest.fixture
def guard_fakes(tmp_path, monkeypatch):
    state = {"events": {}, "memory": 8 * 1024**3, "rc": 0, "closed": False, "killed": False, "started": False}
    class Group:
        path = tmp_path / "group"
        keeper = None
        _remove_group = MemoryGroup._remove_group
        _stop_keeper = MemoryGroup._stop_keeper
        def __init__(self, limit):
            state["limit"] = limit
        def check_alive(self):
            pass
        def events(self):
            return state["events"]
        def kill(self):
            state["killed"] = True
        def close(self):
            state["closed"] = True
    class Process:
        def __init__(self, command, env):
            state["started"] = True
            state["command"] = command
            self.returncode = state["rc"]
        def poll(self):
            return self.returncode
        def wait(self):
            return self.returncode
    monkeypatch.setattr(resources, "MemoryGroup", Group)
    monkeypatch.setattr(resources.subprocess, "Popen", Process)
    monkeypatch.setattr(resources, "available_memory", lambda: state["memory"])
    return state


@pytest.mark.parametrize("events,rc,code", [
    ({"oom": 1, "oom_kill": 1}, -9, "RT_MEMORY_LIMIT"),
    ({"oom_kill": 1}, -9, "RT_HOST_MEMORY_LOW"),
    ({"oom": 1}, 0, "RT_MEMORY_LIMIT"),
    ({}, -15, "RT_WORKER_INTERRUPTED"),
    ({}, 125, "RT_RESOURCE_UNAVAILABLE"),
])
def test_guard_reports_resource_failures_and_cleans_up(tmp_path, guard_fakes, events, rc, code):
    guard_fakes.update(events=events, rc=rc)
    with pytest.raises(resources.ResourceGuardError) as error:
        resources.run_guarded(["worker"], {}, tmp_path, 2048, 1024, lambda _line: None)
    assert error.value.code == code
    assert guard_fakes["closed"]
    assert guard_fakes["limit"] == 2 * 1024**3


def test_guard_does_not_launch_without_host_headroom(tmp_path, guard_fakes):
    guard_fakes["memory"] = 2 * 1024**3
    with pytest.raises(resources.ResourceGuardError, match="Insufficient"):
        resources.run_guarded(["worker"], {}, tmp_path, 2048, 1024, print)
    assert not guard_fakes["started"]


def test_guard_unavailable_is_not_an_unlimited_fallback(tmp_path, guard_fakes, monkeypatch):
    def unavailable(_limit):
        raise PermissionError("cgroup is read-only")
    monkeypatch.setattr(resources, "MemoryGroup", unavailable)
    with pytest.raises(resources.ResourceGuardError) as error:
        resources.run_guarded(["worker"], {}, tmp_path, 2048, 1024, print)
    assert error.value.code == "RT_RESOURCE_UNAVAILABLE"
    assert not guard_fakes["started"]


def test_supervisor_cancellation_restores_signal_handlers(tmp_path, guard_fakes, monkeypatch):
    import signal
    old = signal.getsignal(signal.SIGTERM)
    def interrupt():
        os.kill(os.getpid(), signal.SIGTERM)
    monkeypatch.setattr(resources, "available_memory", interrupt)
    with pytest.raises(resources.ResourceGuardError) as error:
        resources.run_guarded(["worker"], {}, tmp_path, 2048, 1024, print)
    assert error.value.cancelled
    assert error.value.code == "RT_WORKER_INTERRUPTED"
    assert signal.getsignal(signal.SIGTERM) == old
    assert not guard_fakes["started"]


@pytest.mark.parametrize("missing", [None, "cgroup.events", "cgroup.procs", "memory.max"])
def test_cgroup_configuration_checks_kernel_interfaces_and_cleans_up(tmp_path, monkeypatch, missing):
    root = tmp_path / "cgroups"
    root.mkdir()
    (root / "cgroup.controllers").write_text("memory cpu")
    (root / "cgroup.subtree_control").write_text("")
    monkeypatch.setattr(resources, "cgroup_root", lambda: root)
    monkeypatch.setattr(resources.MemoryGroup, "_start_keeper", lambda _self: None)
    monkeypatch.setattr(resources.MemoryGroup, "check_alive", lambda _self: None)
    mkdir, rmdir = Path.mkdir, Path.rmdir
    def create(path, *args, **kwargs):
        mkdir(path, *args, **kwargs)
        if path.parent == root:
            for name, value in {"memory.max": "max", "memory.oom.group": "0", "memory.swap.max": "max",
                                "memory.events": "oom 0\noom_kill 0\n", "cgroup.kill": "",
                                "cgroup.events": "populated 0\n", "cgroup.procs": ""}.items():
                if name != missing:
                    (path / name).write_text(value)
    def remove(path):
        if path.parent == root:
            for file in path.iterdir():
                file.unlink()
        rmdir(path)
    monkeypatch.setattr(Path, "mkdir", create)
    monkeypatch.setattr(Path, "rmdir", remove)
    if missing:
        with pytest.raises(OSError, match=f"Required cgroup interface is unavailable: {missing}"):
            resources.MemoryGroup(256 * 1024**2)
        return
    group = resources.MemoryGroup(256 * 1024**2)
    path = group.path
    assert (path / "memory.max").read_text() == str(256 * 1024**2)
    assert (path / "memory.oom.group").read_text() == "1"
    assert (path / "memory.swap.max").read_text() == "0"
    assert (root / "cgroup.subtree_control").read_text() == "+memory"
    assert group.events() == {"oom": 0, "oom_kill": 0}
    group.close()
    assert not path.exists()


@pytest.mark.parametrize("stage", ["before-close", "during-remove"])
def test_cgroup_cleanup_accepts_only_a_removed_group(tmp_path, monkeypatch, stage):
    group = resources.MemoryGroup.__new__(resources.MemoryGroup)
    group.keeper = None
    group.path = tmp_path / "group"
    if stage == "during-remove":
        group.path.mkdir()
        (group.path / "cgroup.events").write_text("populated 0\n")
        remove = Path.rmdir
        def removed_elsewhere(path):
            (path / "cgroup.events").unlink()
            remove(path)
            raise FileNotFoundError(str(path))
        monkeypatch.setattr(Path, "rmdir", removed_elsewhere)
    group.close()
    assert group.path is None
    group.close()


def test_cgroup_cleanup_rejects_missing_events_in_existing_group(tmp_path):
    group = resources.MemoryGroup.__new__(resources.MemoryGroup)
    group.keeper = None
    group.path = tmp_path
    with pytest.raises(FileNotFoundError):
        group.close()
    assert group.path == tmp_path


@pytest.mark.parametrize("final_counters_read", [True, False])
def test_guard_accepts_removed_group_only_after_final_counter_check(tmp_path, guard_fakes, monkeypatch, final_counters_read):
    # Use production cleanup on a group removed around the final counter read.
    monkeypatch.setattr(resources.MemoryGroup, "close", MemoryGroup.close)
    def events(_group):
        if not final_counters_read:
            raise FileNotFoundError("memory.events")
        return {"oom": 0, "oom_kill": 0}
    monkeypatch.setattr(resources.MemoryGroup, "events", events)
    if final_counters_read:
        assert resources.run_guarded(["worker"], {}, tmp_path, 2048, 1024, print) == 0
    else:
        with pytest.raises(resources.ResourceGuardError, match="memory.events") as error:
            resources.run_guarded(["worker"], {}, tmp_path, 2048, 1024, print)
        assert error.value.code == "RT_RESOURCE_UNAVAILABLE"


@pytest.mark.parametrize("failure", ["oom", "counters-missing", "none"])
def test_cleanup_cannot_mask_memory_failure_or_missing_final_counters(tmp_path, guard_fakes, monkeypatch, failure):
    def missing(_group):
        raise FileNotFoundError("memory.events")
    def broken_cleanup(_group):
        raise FileNotFoundError("cgroup.events")
    monkeypatch.setattr(resources.MemoryGroup, "close", broken_cleanup)
    if failure == "counters-missing":
        monkeypatch.setattr(resources.MemoryGroup, "events", missing)
    elif failure == "oom":
        guard_fakes["events"] = {"oom": 1}
    messages = []
    with pytest.raises(resources.ResourceGuardError) as error:
        resources.run_guarded(["worker"], {}, tmp_path, 2048, 1024, messages.append)
    assert error.value.code == ("RT_MEMORY_LIMIT" if failure == "oom" else "RT_RESOURCE_UNAVAILABLE")
    if failure == "counters-missing":
        assert "memory.events" in str(error.value)
    assert any("cleanup also failed" in message for message in messages) == (failure != "none")


def test_supervisors_queue_instead_of_combining_budgets(tmp_path):
    """Use real independent supervisors/flocks, with a simulated kernel backend."""
    harness = tmp_path / "supervisor.py"
    harness.write_text(f"import sys; sys.path.insert(0, {str(Path(resources.__file__).resolve().parent)!r})\n" + '''
import os, sys, time
from pathlib import Path
import restore_test_resources as r
root = Path(sys.argv[1])
tag = sys.argv[2]
class Group:
    def __init__(self, limit):
        self.path = root / tag
        self.path.mkdir()
    def events(self): return {}
    def check_alive(self): pass
    def close(self):
        for file in self.path.iterdir(): file.unlink()
        self.path.rmdir()
r.MemoryGroup = Group
r.available_memory = lambda: 8 * 1024**3
worker = "import pathlib,time; p=pathlib.Path(%r); p.open('a').write(%r); time.sleep(0.4); p.open('a').write(%r)" % (str(root / 'events'), tag + ':start\\n', tag + ':end\\n')
assert r.run_guarded([sys.executable, '-c', worker], dict(os.environ), root / 'locks', 256, 256, lambda line: None) == 0
''')
    processes = [subprocess.Popen([sys.executable, str(harness), str(tmp_path), str(index)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for index in range(2)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
    events = (tmp_path / "events").read_text().splitlines()
    assert events in [["0:start", "0:end", "1:start", "1:end"],
                      ["1:start", "1:end", "0:start", "0:end"]]


def test_guard_stops_on_falling_host_headroom(tmp_path, guard_fakes, monkeypatch):
    guard_fakes["rc"] = None
    readings = iter([8 * 1024**3, 128 * 1024**2])
    monkeypatch.setattr(resources, "available_memory", lambda: next(readings))
    # Simulate the process exiting after the kernel kills its cgroup.
    original = resources.MemoryGroup.kill
    def kill(group):
        original(group)
        guard_fakes["rc"] = -9
    monkeypatch.setattr(resources.MemoryGroup, "kill", kill)
    # The process stub exposes the shared return code for this asynchronous case.
    monkeypatch.setattr(resources.subprocess.Popen, "poll", lambda _self: guard_fakes["rc"])
    with pytest.raises(resources.ResourceGuardError) as error:
        resources.run_guarded(["worker"], {}, tmp_path, 2048, 1024, print)
    assert error.value.code == "RT_HOST_MEMORY_LOW"
    assert guard_fakes["killed"] and guard_fakes["closed"]


@pytest.mark.parametrize("failure", ["metadata", "full-dry-run"])
def test_timeout_never_becomes_successful_test_evidence(tmp_path, monkeypatch, failure):
    from test_restore_test_runner_profiles import _load_restore_runner
    from types import SimpleNamespace
    runner = _load_restore_runner()
    monkeypatch.setattr(runner.RestoreTest, "_load_notification_config", lambda _s: None)
    monkeypatch.setattr(runner, "_refresh_unraid_dashboard_widget_cache", lambda *_args: None)
    conf = {"GLOBAL_LOG_DIR": str(tmp_path / "logs"), "RESTORE_TEST_STATUS_DIR": str(tmp_path / "reports")}
    tester = runner.RestoreTest(conf, SimpleNamespace(level=2, force=True, dry_run=False, scheduled=False))
    monkeypatch.setattr(tester, "_env", lambda *_args, **_kw: {})
    def borg(args, _env, timeout=None, consume=None):
        if args[0] == "list" and "--json-lines" not in args:
            return subprocess.CompletedProcess(args, 0, "archive\n", "")
        if args[0] == "info":
            return subprocess.CompletedProcess(args, 124 if failure == "metadata" else 0,
                                               '{"archives":[{"stats":{"original_size":1}}]}', "timed out")
        if args[0] == "list":
            consume(b'{"type":"-","path":"file"}\n')
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 124, "", "timed out")
    monkeypatch.setattr(tester, "_borg", borg)
    repo = {"job_key": job_id("appdata_local"), "path": str(tmp_path), "location": "local",
            "encryption": "none", "passphrase_file": ""}
    try:
        assert tester._test_repo_locked(repo) == 1
        report = json.loads((tester.status_dir / f"{repo['job_key']}.test").read_text())
        assert report["test_result"] == "failed"
        assert report["failure_code"] == "RT_TIMEOUT"
        assert report["tested_files"] == 0
        assert report["coverage_percent"] == 0
        assert report["log_file"] == str(tester.log_path)
    finally:
        tester.close()


def test_supervisor_retains_oom_failure_and_releases_repository_lock(tmp_path, monkeypatch):
    from test_restore_test_scheduling import _tester
    tester, repo = _tester(tmp_path, monkeypatch)
    tester.conf["RESTORE_TEST_MEMORY_LIMIT_MIB"] = "2048"
    def oom(*_args, **_kwargs):
        raise resources.ResourceGuardError("RT_MEMORY_LIMIT", "Budget exceeded")
    monkeypatch.setattr(resources, "run_guarded", oom)
    try:
        assert tester.test_repo(repo) == 1
        path = tester.status_dir / f"{repo['job_key']}.test"
        report = json.loads(path.read_text())
        assert report["failure_code"] == "RT_MEMORY_LIMIT"
        assert report["tested_files"] == 0
        assert list((tester.status_dir / "runs" / repo["job_key"]).glob("*.test"))
        assert not list((tmp_path / "locks").glob("*.lock.json"))
    finally:
        tester.close()


@pytest.mark.parametrize("oom_after_result", [False, True])
def test_worker_success_is_published_only_after_supervisor_accepts_it(tmp_path, monkeypatch, oom_after_result):
    from test_restore_test_scheduling import _tester
    tester, repo = _tester(tmp_path, monkeypatch)
    tester.conf["RESTORE_TEST_MEMORY_LIMIT_MIB"] = "2048"
    latest = tester.status_dir / f"{repo['job_key']}.test"
    def worker(_command, env, *_args, **_kwargs):
        # Stage exactly the result format emitted by the worker.
        monkeypatch.setenv("BORG_UI_RESTORE_RESULT", env["BORG_UI_RESTORE_RESULT"])
        tester.args.resource_worker = True
        try:
            tester._write(repo["job_key"], repo, "success", 1, 1, 0, 1, "complete",
                          "archive", {"files_count": 1}, ["- file"], test_coverage_pct=100)
        finally:
            tester.args.resource_worker = False
        assert not latest.exists()
        if oom_after_result:
            raise resources.ResourceGuardError("RT_MEMORY_LIMIT", "Budget exceeded")
        return 0
    monkeypatch.setattr(resources, "run_guarded", worker)
    try:
        assert tester.test_repo(repo) == (1 if oom_after_result else 0)
        report = json.loads(latest.read_text())
        assert report["test_result"] == ("failed" if oom_after_result else "success")
        assert len(list((tester.status_dir / "runs" / repo["job_key"]).glob("*.test"))) == 1
        assert not list(tester.status_dir.glob(".pending-*.json"))
    finally:
        tester.close()


@pytest.mark.parametrize("key,value", [
    ("RESTORE_TEST_MEMORY_LIMIT_MIB", "bad"), ("RESTORE_TEST_MEMORY_LIMIT_MIB", "-1"),
    ("RESTORE_TEST_MEMORY_LIMIT_MIB", "1"), ("RESTORE_TEST_HOST_RESERVE_MIB", "0"),
])
def test_invalid_memory_settings_are_rejected_before_saving(tmp_path, key, value):
    from config_api import canonical_backup_conf_plan
    with pytest.raises(ValueError, match=key):
        canonical_backup_conf_plan({"BACKUP_SCRIPTS_DIR": str(tmp_path)}, updates={key: value})


@pytest.mark.skipif(os.environ.get("BBUI_CGROUP_TESTS") != "1", reason="Requires an explicitly enabled writable cgroup v2 test host")
def test_kernel_limit_kills_worker_and_children_but_not_supervisor(tmp_path):
    command = [sys.executable, "-c", "import os; os.fork(); data=bytearray(180*1024*1024); import time; time.sleep(20)"]
    with pytest.raises(resources.ResourceGuardError) as error:
        resources.run_guarded(command, dict(os.environ), tmp_path, 256, 256, print)
    assert error.value.code == "RT_MEMORY_LIMIT"


@pytest.fixture
def keeper_harness(tmp_path, monkeypatch):
    """Run real keeper pipes/processes, mapping only kernel files to fixture files."""
    harness = tmp_path / "keeper.py"
    harness.write_text(f'''
import sys
from pathlib import Path
sys.path.insert(0, {str(Path(resources.__file__).resolve().parent)!r})
import restore_test_resources as r
root = Path(sys.argv[2])
def mapped_path(value):
    return root / 'oom_score_adj' if str(value) == '/proc/self/oom_score_adj' else Path(value)
r.Path = mapped_path
try:
    r.keep_group_alive(root)
except OSError:
    sys.exit(125)
''')
    monkeypatch.setattr(resources, "__file__", str(harness))
    group = MemoryGroup.__new__(MemoryGroup)
    group.path = tmp_path / "group"
    group.path.mkdir()
    group.keeper = None
    (group.path / "oom_score_adj").write_text("0")
    (group.path / "cgroup.procs").write_text("")
    return group


def test_keeper_is_ready_in_group_before_work_and_exits_on_pipe_eof(keeper_harness):
    group = keeper_harness
    try:
        group._start_keeper()
        keeper = group.keeper
        group.check_alive()
        assert int((group.path / "cgroup.procs").read_text()) == keeper.pid
        assert (group.path / "oom_score_adj").read_text() == "-1000"
        # EOF also occurs automatically when the supervisor dies.
        keeper.stdin.close()
        assert keeper.wait(timeout=5) == 0
        with pytest.raises(OSError, match="keeper exited"):
            group.check_alive()
    finally:
        group._stop_keeper()
    assert keeper.stdout.closed
    assert group.keeper is None


def test_keeper_startup_failure_never_acknowledges_readiness(keeper_harness):
    group = keeper_harness
    # A directory at the OOM setting simulates a failed kernel write.
    (group.path / "oom_score_adj").unlink()
    (group.path / "oom_score_adj").mkdir()
    try:
        with pytest.raises(OSError, match="keeper could not start"):
            group._start_keeper()
        keeper = group.keeper
        assert (group.path / "cgroup.procs").read_text() == ""
    finally:
        group._stop_keeper()
    assert keeper.returncode == 125


def test_keeper_startup_timeout_is_reaped(keeper_harness, monkeypatch):
    monkeypatch.setattr(resources.select, "select", lambda *_args: ([], [], []))
    try:
        with pytest.raises(OSError, match="keeper could not start"):
            keeper_harness._start_keeper()
        process = keeper_harness.keeper
    finally:
        keeper_harness._stop_keeper()
    assert process.poll() is not None


@pytest.mark.parametrize("oom", [0, 1])
def test_empty_group_reaper_cannot_remove_counters_before_collection(keeper_harness, oom):
    """Model Unraid's empty-group reaper with real keeper/workload processes."""
    group = keeper_harness
    counter = group.path / "memory.events"
    counter.write_text(f"oom {oom}\noom_kill {oom}\n")
    group._start_keeper()
    keeper = group.keeper
    worker = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        worker.wait(timeout=5)
        # On the reported host, removal happens when the last member exits.
        def reap_empty_group():
            if worker.poll() is not None and keeper.poll() is not None:
                for file in group.path.iterdir():
                    file.unlink()
                group.path.rmdir()
        reap_empty_group()
        assert group.events() == {"oom": oom, "oom_kill": oom}
        group._stop_keeper()
        reap_empty_group()
        assert not group.path.exists()
        group.close()
    finally:
        group._stop_keeper()


def test_supervisor_stops_if_keeper_dies_during_work(tmp_path, guard_fakes, monkeypatch):
    guard_fakes['rc'] = None
    def died(_group):
        raise OSError("keeper exited")
    monkeypatch.setattr(resources.MemoryGroup, "check_alive", died)
    monkeypatch.setattr(resources.subprocess.Popen, "kill", lambda _self: guard_fakes.update(rc=-9), raising=False)
    monkeypatch.setattr(resources.subprocess.Popen, "poll", lambda _self: guard_fakes['rc'])
    with pytest.raises(resources.ResourceGuardError, match="keeper exited"):
        resources.run_guarded(["worker"], {}, tmp_path, 2048, 1024, print)
    assert guard_fakes['closed']
    assert guard_fakes['rc'] == -9


def test_workload_is_never_exempted_from_oom_killing(tmp_path, monkeypatch):
    score = tmp_path / 'oom_score_adj'
    score.write_text('-1000')
    monkeypatch.setattr(resources, 'Path', lambda value: score if value == '/proc/self/oom_score_adj' else Path(value))
    executed = []
    def exec_workload(executable, command, _env):
        assert score.read_text() == '0'
        assert (tmp_path / 'cgroup.procs').read_text() == str(os.getpid())
        executed.append(command)
    monkeypatch.setattr(resources.os, 'execvpe', exec_workload)
    resources.launch_worker(tmp_path, ['borg', 'extract'])
    assert executed == [['borg', 'extract']]


@pytest.mark.skipif(os.environ.get('BBUI_CGROUP_TESTS') != '1', reason='Requires an explicitly enabled writable cgroup v2 test host')
@pytest.mark.parametrize('oom', [False, True])
def test_kernel_final_counters_survive_an_empty_group_reaper(tmp_path, monkeypatch, oom):
    """Exercise real cgroup retention against an independent empty-group remover."""
    groups, reapers = [], []
    class ObservedGroup(MemoryGroup):
        def __init__(self, limit):
            super().__init__(limit)
            groups.append(self)
            reapers.append(subprocess.Popen([sys.executable, '-c', '''
import pathlib,sys,time
p=pathlib.Path(sys.argv[1])
while p.exists():
    try:
        if 'populated 1' not in (p/'cgroup.events').read_text():
            p.rmdir()
            break
    except FileNotFoundError:
        break
    except OSError:
        pass
    time.sleep(0.001)
''', str(self.path)]))
    monkeypatch.setattr(resources, 'MemoryGroup', ObservedGroup)
    workload = 'import os; os.fork(); data=bytearray(180*1024*1024); import time; time.sleep(20)' if oom else 'pass'
    try:
        if oom:
            with pytest.raises(resources.ResourceGuardError) as error:
                resources.run_guarded([sys.executable, '-c', workload], dict(os.environ), tmp_path, 256, 256, print)
            assert error.value.code == 'RT_MEMORY_LIMIT'
        else:
            assert resources.run_guarded([sys.executable, '-c', workload], dict(os.environ), tmp_path, 256, 256, print) == 0
        assert groups[0].path is None
        assert groups[0].keeper is None
    finally:
        for reaper in reapers:
            reaper.terminate()
            reaper.wait(timeout=5)


def test_queue_state_is_explicit_and_changes_before_worker_start(tmp_path, guard_fakes):
    """Only actual slot contention reports waiting; release changes state before work."""
    import fcntl

    states = []
    with (tmp_path / "restore-test-memory.lock").open("a") as occupied:
        fcntl.flock(occupied, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def state_changed(state):
            assert not guard_fakes["started"]
            states.append(state)
            if state == "waiting":
                fcntl.flock(occupied, fcntl.LOCK_UN)
        assert resources.run_guarded(["worker"], {}, tmp_path, 2048, 1024,
                                     lambda _: None, on_state=state_changed) == 0
    assert states == ["waiting", "running"]
    assert guard_fakes["started"]
