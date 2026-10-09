"""Exercise real runner recovery before maintenance and on failure (#552)."""

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / "api", ROOT / "runtime"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from job_fixtures import job_id
import job_control
import lifecycle_log
import wizard_runner
from lib.backup_job import BackupJob, BackupJobConfig, RUNTIME_RECOVERY_FAILED
from lib.borg_runner import BorgRunner
from lib import docker_manager, vm_manager, runtime_recovery
from wizard_api import generate_flow_preview


@pytest.fixture
def run_backup(monkeypatch, tmp_path):
    """Run the real lifecycle with simulated Borg and workload processes."""
    cfg = BackupJobConfig(
        job_id=job_id("early-recovery"), job_name="Early recovery",
        backup_type="appdata", backup_location="local",
        lock_file=tmp_path / "backup.lock", log_dir=tmp_path,
        log_file=tmp_path / "backup.log", backup_paths=[tmp_path],
        borg_cache_dir=tmp_path / "cache", date_tag="2026-10-09",
        runtime_recovery_file=tmp_path / "runtime-recovery.json",
    )
    state = SimpleNamespace(
        actions=[], phases=[], result=None, cancelled=False, create_exit=0,
        fail_restart="", cancel_at="", create_error=False, check_exit=0,
        docker_mode="all", vm_mode="all",
    )

    def action(name):
        state.actions.append(name)
        if state.cancel_at == name:
            state.cancelled = True

    class Docker:
        def __init__(self, config):
            self.config = config

        def stop_all(self, _log):
            action("stop_docker")
            return docker_manager.DockerStopResult(
                available=True, container_ids=["openhab-id"],
                container_names=["OpenHAB"], count_before=1, success=True,
            )

        def start_all(self, stopped):
            assert stopped.container_ids == ["openhab-id"]
            action("start_docker")
            return docker_manager.DockerStartResult(
                count_before=1, count_after=0 if state.fail_restart == "docker" else 1,
                failed_ids=["openhab-id"] if state.fail_restart == "docker" else [],
            )

    class Vms:
        def __init__(self, config):
            self.config = config

        def shutdown_all(self):
            action("stop_vms")
            return vm_manager.VmShutdownResult(stopped_vms=["test-vm"])

        def start_all(self, stopped):
            assert stopped.stopped_vms == ["test-vm"]
            action("start_vms")
            return vm_manager.VmStartResult(
                target_vms=["test-vm"],
                started_vms=[] if state.fail_restart == "vm" else ["test-vm"],
                failed_vms=["test-vm"] if state.fail_restart == "vm" else [],
            )

    def create(*_args, **_kwargs):
        action("create")
        if state.create_error:
            raise RuntimeError("create process failed")
        return state.create_exit

    def maintenance_step(runner, name):
        runner.phase_callback("borg_" + name)
        action(name)
        return state.check_exit if name == "check" else 0

    def finish(job):
        action("finish")
        state.result = (job._borg_exit, job._failure_code)

    control = SimpleNamespace(
        update_phase=lambda phase, **kwargs: state.phases.append((phase, kwargs)),
        is_cancel_requested=lambda: state.cancelled,
    )
    monkeypatch.setattr(job_control, "JobControl", lambda *_: control)
    monkeypatch.setattr(wizard_runner, "ResourceLockSet", lambda **_: SimpleNamespace(
        acquire=lambda _: (True, ""), release=lambda: action("release")))
    monkeypatch.setattr(wizard_runner, "_ensure_borg_available", lambda: "borg")
    monkeypatch.setattr(wizard_runner, "_setup_stdout_logging", lambda: None)
    monkeypatch.setattr(wizard_runner, "_setup_full_logging", lambda _: None)
    monkeypatch.setattr(wizard_runner, "_ensure_runtime_import_paths", lambda _: None)
    monkeypatch.setattr(wizard_runner, "_load_env_from_job", lambda *_: (
        {"BACKUP_SCRIPTS_DIR": str(tmp_path), "ABORT_ON_PARITY_CHECK": "false"},
        {"job_id": cfg.job_id, "location": "local", "archive_prefix": "appdata",
         "docker_control": {"mode": state.docker_mode}, "vm_control": {"mode": state.vm_mode}},
    ))
    monkeypatch.setattr(BackupJobConfig, "from_config", lambda _: cfg)
    monkeypatch.setattr(BackupJob, "check_prerequisites", lambda _: None)
    monkeypatch.setattr(BackupJob, "cleanup_old_logs", lambda _: None)
    monkeypatch.setattr(BackupJob, "_do_finish", finish)
    monkeypatch.setattr(BackupJob, "_refresh_unraid_dashboard_widget_cache", lambda *_: None)
    monkeypatch.setattr(docker_manager, "DockerManager", Docker)
    monkeypatch.setattr(vm_manager, "VmManager", Vms)
    monkeypatch.setattr(BorgRunner, "create", create)
    monkeypatch.setattr(BorgRunner, "prune", lambda self, *_: maintenance_step(self, "prune"))
    monkeypatch.setattr(BorgRunner, "compact", lambda self: maintenance_step(self, "compact"))
    monkeypatch.setattr(BorgRunner, "check", lambda self: maintenance_step(self, "check"))
    monkeypatch.setattr(lifecycle_log, "emit_lifecycle", lambda *_, **__: None)
    for key, value in {
        "BORG_UI_JOB_KEY": cfg.job_id, "BORG_UI_BORG_SCRIPTS_DIR": str(ROOT / "runtime/scripts"),
        "BORG_SCRIPT_DIR": str(tmp_path), "BORG_UI_RUN_ID": "20261009T120000Z-recovery",
    }.items():
        monkeypatch.setenv(key, value)
    state.config = cfg
    state.run = wizard_runner.main
    return state


@pytest.mark.parametrize("create_exit,check_exit", [(0, 0), (1, 0), (0, 1), (0, 2)])
def test_restart_precedes_all_maintenance_once(run_backup, create_exit, check_exit):
    state = run_backup
    state.create_exit, state.check_exit = create_exit, check_exit
    assert state.run() == max(create_exit, check_exit)
    assert state.actions == ["stop_docker", "stop_vms", "create", "start_docker", "start_vms",
                             "prune", "compact", "check", "finish", "release"]
    assert not state.config.lock_file.exists()
    assert runtime_recovery.summarize_runtime_recovery(state.config.runtime_recovery_file)["pending_count"] == 0
    for phase, details in state.phases:
        if phase in {"recovering_docker", "recovering_vms"}:
            assert details["cancel_allowed"] is False
        if phase == "borg_prune":
            assert details["cancel_allowed"] is True


@pytest.mark.parametrize("failure", ["exit", "exception", "cancel_create", "cancel_restart"])
def test_failed_or_cancelled_create_recovers_without_maintenance(run_backup, failure):
    state = run_backup
    state.create_exit = 2 if failure == "exit" else 0
    state.create_error = failure == "exception"
    state.cancel_at = {"cancel_create": "create", "cancel_restart": "start_docker"}.get(failure, "")
    if state.create_error:
        with pytest.raises(RuntimeError, match="create process failed"):
            state.run()
    else:
        assert state.run() == (130 if state.cancel_at else 2)
    assert state.actions == ["stop_docker", "stop_vms", "create", "start_docker", "start_vms", "finish", "release"]
    assert not state.config.lock_file.exists()


@pytest.mark.parametrize("kind", ["docker", "vm"])
def test_restart_failure_recovers_other_workloads_and_preserves_failure(run_backup, kind):
    state = run_backup
    state.fail_restart = kind
    with pytest.raises(RuntimeError, match="Runtime recovery failed"):
        state.run()
    assert state.actions == ["stop_docker", "stop_vms", "create", "start_docker", "start_vms", "finish", "release"]
    assert state.result == (2, RUNTIME_RECOVERY_FAILED)
    assert state.phases[-1][0] == "failed"
    summary = runtime_recovery.summarize_runtime_recovery(state.config.runtime_recovery_file)
    assert summary["pending_count"] == summary["attention_count"] == 1
    assert summary["entries"][0]["state"] == "restart_failed"
    assert not state.config.lock_file.exists()


@pytest.mark.parametrize("docker_mode,vm_mode", [("all", "none"), ("none", "all"), ("none", "none")])
def test_only_enabled_workload_controls_restart(run_backup, docker_mode, vm_mode):
    state = run_backup
    state.docker_mode, state.vm_mode = docker_mode, vm_mode
    assert state.run() == 0
    for kind, mode in [("docker", docker_mode), ("vms", vm_mode)]:
        assert state.actions.count("start_" + kind) == (1 if mode == "all" else 0)
    assert "check" in state.actions


@pytest.mark.parametrize("retention,step", [({"retention_mode": "all"}, "borgMaintenanceKeepAll"),
                                           ({"retention_mode": "last", "keep_last": 2}, "borgMaintenance")])
def test_preview_restarts_before_maintenance(tmp_path, retention, step):
    flow = generate_flow_preview({
        "location": "local", "source_paths": [str(tmp_path)],
        "docker_control": {"mode": "all"}, "vm_control": {"mode": "all"},
        **retention,
    }, {"BACKUP_SCRIPTS_DIR": str(tmp_path)}, tmp_path)
    codes = [item["code"] for item in flow["step_codes"]]
    assert codes.index("borgCreate") < codes.index("dockerStart") < codes.index("vmStart") < codes.index(step)
