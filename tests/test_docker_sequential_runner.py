"""Run the real runner in sequential Docker mode with simulated Docker and Borg."""

from pathlib import Path
from types import SimpleNamespace
import copy
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
from lib import borg_runner
from lib.borg_runner import BorgRunner, BorgStats
from lib import docker_manager, vm_manager, runtime_recovery
from lib.job_workflow import JobWorkflow


@pytest.fixture
def run_sequence(monkeypatch, tmp_path):
    """Run the real lifecycle; Docker, VMs and Borg only record their actions."""
    appdata = tmp_path / "appdata"
    for name in ("mariadb", "nextcloud", "orphan"):
        (appdata / name).mkdir(parents=True)
    cfg = BackupJobConfig(
        job_id=job_id("sequential"), job_name="Sequential", backup_type="appdata",
        backup_location="local", lock_file=tmp_path / "backup.lock", log_dir=tmp_path,
        log_file=tmp_path / "backup.log", backup_paths=[appdata],
        borg_cache_dir=tmp_path / "cache", date_tag="2026-10-24",
        runtime_recovery_file=tmp_path / "runtime-recovery.json",
    )
    state = SimpleNamespace(
        actions=[], phases=[], steps=[], creates=[], result=None, cancelled=False,
        mounts={
            "mariadb": [str(appdata / "mariadb")],
            "nextcloud": [str(appdata / "nextcloud"), "/mnt/user/media"],
            "whoami": [],
        },
        available=True, mount_error=False, fail_create="", fail_restart="", cancel_at="",
        vm_mode="all", series_pruned=None, config=cfg, appdata=appdata,
    )

    def action(name):
        state.actions.append(name)
        if state.cancel_at == name:
            state.cancelled = True

    class Docker:
        def __init__(self, config):
            self.config = config

        def running_targets(self, mode, selected):
            assert mode == "all" and selected == []
            return [(name, f"id-{name}") for name in sorted(state.mounts)] if state.available else None

        def writable_bind_mounts(self, ids):
            if state.mount_error:
                raise RuntimeError("Docker volume mappings could not be read (exit 1)")
            return {cid[3:]: state.mounts[cid[3:]] for cid in ids}

        def stop_selected(self, names, _log):
            action("stop:" + "+".join(names))
            return docker_manager.DockerStopResult(
                available=True, container_ids=[f"id-{name}" for name in names],
                container_names=list(names), count_before=len(names), success=True)

        def start_all(self, stopped):
            names = "+".join(stopped.container_names)
            action("start:" + names)
            failed = list(stopped.container_ids) if state.fail_restart == names else []
            return docker_manager.DockerStartResult(
                count_before=stopped.count_before, count_after=stopped.count_before - len(failed), failed_ids=failed)

    class Vms:
        def __init__(self, config):
            self.config = config

        def shutdown_all(self, *, before_shutdown):
            result = vm_manager.VmShutdownResult(target_vms=["vm"])
            before_shutdown(result)
            action("stop_vms")
            result.stopped_vms = ["vm"]
            return result

        def start_all(self, stopped):
            action("start_vms")
            return vm_manager.VmStartResult(target_vms=["vm"], started_vms=["vm"], failed_vms=[])

    def create(runner, paths, prefix, exclude_paths=None, archive_name=None):
        # Group archives end with "-YYYY-MM-DD_HH-MM-SS"; the main archive uses Borg's placeholder.
        label = archive_name[:-20] if archive_name else "main"
        state.creates.append({"label": label, "name": archive_name, "paths": [str(path) for path in paths],
                              "excludes": [str(path) for path in exclude_paths or []]})
        action("create:" + label)
        return 2 if state.fail_create == label else 0

    def stats(_log):
        return BorgStats(archive_name=state.creates[-1]["name"] or "appdata-2026-10-24_03-00-00",
                         original_size=100, compressed_size=50, deduplicated_size=10, files=3)

    def maintenance_step(runner, name):
        runner.phase_callback("borg_" + name)
        if name == "prune":
            state.series_pruned = runner.config.prune_container_series
        action(name)
        return 0

    def finish(job):
        action("finish")
        state.result = (job._borg_exit, job._failure_code, job._borg_stats, job.backup_exit_code)

    control = SimpleNamespace(
        update_phase=lambda phase, **kwargs: state.phases.append((phase, kwargs)),
        is_cancel_requested=lambda: state.cancelled,
        update_job_steps=lambda steps: state.steps.append(copy.deepcopy(steps)),
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
         "docker_control": {"mode": "all", "sequential": True}, "vm_control": {"mode": state.vm_mode}},
    ))
    monkeypatch.setattr(BackupJobConfig, "from_config", lambda _: cfg)
    monkeypatch.setattr(BackupJob, "check_prerequisites", lambda _: None)
    monkeypatch.setattr(BackupJob, "cleanup_old_logs", lambda _: None)
    monkeypatch.setattr(BackupJob, "_do_finish", finish)
    monkeypatch.setattr(BackupJob, "_refresh_unraid_dashboard_widget_cache", lambda *_: None)
    monkeypatch.setattr(docker_manager, "DockerManager", Docker)
    monkeypatch.setattr(vm_manager, "VmManager", Vms)
    monkeypatch.setattr(BorgRunner, "create", create)
    monkeypatch.setattr(borg_runner, "parse_borg_stats", stats)
    monkeypatch.setattr(BorgRunner, "prune", lambda self, *_: maintenance_step(self, "prune"))
    monkeypatch.setattr(BorgRunner, "compact", lambda self: maintenance_step(self, "compact"))
    monkeypatch.setattr(BorgRunner, "check", lambda self: maintenance_step(self, "check"))
    monkeypatch.setattr(lifecycle_log, "emit_lifecycle", lambda *_, **__: None)
    for key, value in {
        "BORG_UI_JOB_KEY": cfg.job_id, "BORG_UI_BORG_SCRIPTS_DIR": str(ROOT / "runtime/scripts"),
        "BORG_SCRIPT_DIR": str(tmp_path), "BORG_UI_RUN_ID": "20261024T030000Z-sequence",
    }.items():
        monkeypatch.setenv(key, value)
    state.run = wizard_runner.main
    return state


def _step(state, name):
    return next(step for step in state.steps[-1] if step["id"] == name)


def test_groups_are_stopped_archived_and_restarted_one_after_another(run_sequence):
    state = run_sequence
    assert state.run() == 0
    assert state.actions == [
        "stop:mariadb", "create:appdata@mariadb", "start:mariadb",
        "stop:nextcloud", "create:appdata@nextcloud", "start:nextcloud",
        "stop_vms", "create:main", "start_vms", "prune", "compact", "check", "finish", "release",
    ]
    mariadb, nextcloud, main = state.creates
    assert mariadb["paths"] == [str(state.appdata / "mariadb")]
    assert nextcloud["paths"] == [str(state.appdata / "nextcloud")]
    assert nextcloud["name"].startswith("appdata@nextcloud-")
    assert main["name"] is None and main["paths"] == [str(state.appdata)]
    assert main["excludes"] == [str(state.appdata / "mariadb"), str(state.appdata / "nextcloud")]
    assert state.series_pruned is True

    exit_code, failure, stats, backup_exit = state.result
    assert (exit_code, failure, backup_exit) == (0, "", 0)
    assert (stats.files, stats.original_size, stats.archive_name) == (9, 300, "appdata-2026-10-24_03-00-00")
    sequence = _step(state, "docker_sequence")
    assert sequence["status"] == "success"
    assert sequence["details"]["target_count"] == sequence["details"]["completed_count"] == 2
    assert [group["containers"] for group in sequence["details"]["groups"]] == [["mariadb"], ["nextcloud"]]
    assert [step["id"] for step in state.steps[-1]].count("stop_docker") == 0
    assert runtime_recovery.summarize_runtime_recovery(state.config.runtime_recovery_file)["pending_count"] == 0
    phases = [phase for phase, _details in state.phases]
    assert phases.index("stopping_docker") < phases.index("recovering_docker")
    assert all(not details["cancel_allowed"] for phase, details in state.phases if phase == "recovering_docker")


def test_cancellation_restarts_the_current_group_and_stops_no_further_group(run_sequence):
    state = run_sequence
    state.cancel_at = "create:appdata@mariadb"
    assert state.run() == 130
    assert state.actions == ["stop:mariadb", "create:appdata@mariadb", "start:mariadb", "finish", "release"]
    assert state.result[1] == "user_cancelled"
    assert runtime_recovery.summarize_runtime_recovery(state.config.runtime_recovery_file)["pending_count"] == 0


def test_group_create_error_restarts_the_group_and_skips_the_rest(run_sequence):
    state = run_sequence
    state.fail_create = "appdata@mariadb"
    assert state.run() == 2
    assert state.actions == ["stop:mariadb", "create:appdata@mariadb", "start:mariadb", "finish", "release"]
    assert state.result[0] == 2 and state.result[3] == 2
    sequence = _step(state, "docker_sequence")
    assert sequence["status"] == "error"
    assert sequence["details"]["groups"][0]["status"] == "error"


def test_restart_failure_stops_the_sequence_and_keeps_the_recovery_entry(run_sequence):
    state = run_sequence
    state.fail_restart = "mariadb"
    with pytest.raises(RuntimeError, match="Runtime recovery failed"):
        state.run()
    assert state.actions == ["stop:mariadb", "create:appdata@mariadb", "start:mariadb", "finish", "release"]
    assert state.result[:2] == (2, RUNTIME_RECOVERY_FAILED)
    summary = runtime_recovery.summarize_runtime_recovery(state.config.runtime_recovery_file)
    assert summary["attention_count"] == 1
    assert summary["entries"][0]["targets"] == [{"id": "id-mariadb", "name": "mariadb"}]


def test_no_main_archive_when_every_source_belongs_to_a_group(run_sequence):
    state = run_sequence
    state.config.backup_paths = [state.appdata / "mariadb", state.appdata / "nextcloud"]
    assert state.run() == 0
    assert state.actions == [
        "stop:mariadb", "create:appdata@mariadb", "start:mariadb",
        "stop:nextcloud", "create:appdata@nextcloud", "start:nextcloud",
        "prune", "compact", "check", "finish", "release",
    ]
    create = _step(state, "create")
    assert (create["status"], create["reason"]) == ("skipped", "no_main_archive")
    assert state.result[2].archive_name.startswith("appdata@nextcloud-")


def test_unavailable_docker_backs_up_everything_in_the_main_archive(run_sequence):
    state = run_sequence
    state.available = False
    state.vm_mode = "none"
    assert state.run() == 0
    assert state.actions == ["create:main", "prune", "compact", "check", "finish", "release"]
    assert state.creates[0]["paths"] == [str(state.appdata)] and state.creates[0]["excludes"] == []
    sequence = _step(state, "docker_sequence")
    assert (sequence["status"], sequence["reason"]) == ("skipped", "unavailable")


def test_unreadable_volume_mappings_fail_before_any_container_stops(run_sequence):
    state = run_sequence
    state.mount_error = True
    with pytest.raises(RuntimeError, match="volume mappings"):
        state.run()
    assert state.actions == ["finish", "release"]
    assert _step(state, "docker_sequence")["status"] == "error"


def test_workflow_replaces_the_docker_pair_in_sequential_mode():
    names = [step["id"] for step in JobWorkflow.configured(docker=True, vms=True, docker_sequence=True).steps]
    assert names == ["docker_sequence", "stop_vms", "create", "start_vms", "prune", "compact", "check"]
    names = [step["id"] for step in JobWorkflow.configured(docker=True, vms=False).steps]
    assert names == ["stop_docker", "create", "start_docker", "prune", "compact", "check"]
