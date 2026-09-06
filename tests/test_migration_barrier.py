"""#479: real process races, durable denial, and admitted-worker completion."""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
import migration_barrier as gate
from migration_gate_support import ready_gate


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("BORG_UI_MIGRATION_GATE_ROOT", str(tmp_path / "gate"))
    data = tmp_path / "data"
    data.mkdir()
    return {"BACKUP_SCRIPTS_DIR": str(data)}


def ready(config):
    gate.block_writers(config)
    with gate.exclusive_migration(config):
        assert gate.quiescence_held(config)
        gate.clear_block(config)


def test_no_startup_proof_means_default_denied(config):
    with pytest.raises(gate.MigrationBlocked, match="startup_validation_required"):
        with gate.writer_lease(config):
            pytest.fail("unvalidated startup entered")
    assert not (gate.data_root(config) / ".migration-gate").exists()


def test_only_exclusive_verified_coordinator_can_clear(config):
    with pytest.raises(gate.MigrationBlocked, match="exclusive_migration_required"):
        gate.clear_block(config)
    ready(config)
    assert not gate.quiescence_held(config)
    with gate.writer_lease(config):
        pass


def test_existing_worker_finishes_nested_work_but_new_thread_is_denied(config):
    ready(config)
    errors = []
    with gate.writer_lease(config):
        gate.block_writers(config)
        with gate.writer_lease(config):
            pass  # Same admitted worker can finish recovery/status/notification.
        def newcomer():
            try:
                with gate.writer_lease(config):
                    errors.append("admitted")
            except gate.MigrationBlocked as exc:
                errors.append(exc.reason)
        thread = threading.Thread(target=newcomer)
        thread.start()
        thread.join(timeout=5)
        assert errors == ["migration_maintenance"]
        with pytest.raises(gate.MigrationBlocked, match="writers_running"):
            with gate.exclusive_migration(config):
                pytest.fail("active worker was ignored")
    with gate.exclusive_migration(config):
        pass


def test_lease_handoff_covers_async_worker_after_request_returns(config):
    ready(config)
    with gate.writer_lease(config):
        lease = gate.acquire_writer_lease(config)
    gate.block_writers(config)
    with pytest.raises(gate.MigrationBlocked, match="writers_running"):
        with gate.exclusive_migration(config):
            pass
    result = []
    def finish():
        try:
            with lease.activate(), gate.writer_lease(config):
                result.append("completed")
        finally:
            lease.close()
    worker = threading.Thread(target=finish)
    worker.start()
    worker.join(timeout=5)
    assert result == ["completed"]
    with gate.exclusive_migration(config):
        pass


def test_real_process_lease_is_released_after_exit_without_killing(config):
    ready(config)
    code = (
        "import sys; sys.path.insert(0,sys.argv[1]); import migration_barrier as m; "
        "lease=m.acquire_writer_lease({'BACKUP_SCRIPTS_DIR':sys.argv[2]}); "
        "print('ready',flush=True); sys.stdin.readline(); lease.close()"
    )
    process = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "api"), config["BACKUP_SCRIPTS_DIR"]],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "ready"
        gate.block_writers(config)
        with pytest.raises(gate.MigrationBlocked, match="writers_running"):
            with gate.exclusive_migration(config):
                pass
        assert process.poll() is None
        process.communicate("finish\n", timeout=5)
        assert process.returncode == 0
        with gate.exclusive_migration(config):
            pass
    finally:
        if process.poll() is None:
            process.communicate("finish\n", timeout=5)


def test_reboot_or_old_protocol_cannot_reuse_ready_proof(config):
    ready(config)
    _, runtime = gate._paths(config)
    (runtime / "ready.json").unlink()
    with pytest.raises(gate.MigrationBlocked, match="startup_validation_required"):
        gate.acquire_writer_lease(config)
    (runtime / "ready.json").write_text(json.dumps({"protocol_version": 0, "ready": True}))
    (runtime / "ready.json").chmod(0o600)
    with pytest.raises(gate.MigrationBlocked, match="startup_validation_required"):
        gate.acquire_writer_lease(config)


def test_persistent_inhibit_survives_runtime_directory_change(config, tmp_path, monkeypatch):
    ready(config)
    gate.block_writers(config)
    marker, _ = gate._paths(config)
    original = marker.read_bytes()
    monkeypatch.setenv("BORG_UI_MIGRATION_GATE_ROOT", str(tmp_path / "after-reboot"))
    with pytest.raises(gate.MigrationBlocked, match="migration_maintenance"):
        gate.acquire_writer_lease(config)
    assert marker.read_bytes() == original


def test_symlink_gate_cannot_touch_external_files(config, tmp_path):
    target = tmp_path / "external"
    target.mkdir()
    (gate.data_root(config) / ".migration-gate").symlink_to(target, target_is_directory=True)
    with pytest.raises(gate.MigrationBlocked, match="unsafe_gate_path"):
        gate.block_writers(config)
    assert list(target.iterdir()) == []


def test_hardlink_pending_publish_is_not_truncated(config, tmp_path):
    marker, _ = gate._paths(config)
    marker.parent.mkdir()
    external = tmp_path / "external"
    external.write_bytes(b"must survive")
    os.link(external, marker.with_name("blocked.json.pending"))
    with pytest.raises(gate.MigrationBlocked, match="unsafe_gate_state"):
        gate.block_writers(config)
    assert external.read_bytes() == b"must survive"


def test_old_worker_detection_is_bounded_and_masks_arguments(config, tmp_path):
    proc = tmp_path / "proc"
    for pid, argv in [(1001, ["python3", "/old/api/wizard_runner.py", "secret=do-not-show"]),
                      (1002, ["python3", "-c", "from lib.notification_events import drain_notification_queue\npassword='hidden'"]),
                      (1003, ["python3", "/old/api/factory_reset_worker.py"]),
                      (1004, ["borg", "create", "secret"]),
                      (1005, ["unrelated-app", "nothing"])]:
        directory = proc / str(pid)
        directory.mkdir(parents=True)
        (directory / "cmdline").write_bytes("\0".join(argv).encode())
    rows = gate.blockers(config, proc_root=proc)
    assert len(rows) == 4
    assert {row["kind"] for row in rows} == {"backup_worker", "notification_worker", "factory_reset_worker", "borg_worker"}
    assert not any(word in json.dumps(rows) for word in ("secret", "password", "hidden"))
    assert gate.blockers(config, proc_root=proc / "missing") == [{"reason": "process_inspection_unavailable"}]


def test_old_workers_prevent_exclusive_even_without_leases(config, monkeypatch):
    gate.block_writers(config)
    monkeypatch.setattr(gate, "blockers", lambda cfg: [{"reason": "worker_running", "pid": 42}])
    with pytest.raises(gate.MigrationBlocked, match="legacy_workers_running"):
        with gate.exclusive_migration(config):
            pass


def test_detached_notification_does_not_dequeue_under_maintenance(config):
    sys.path.insert(0, str(ROOT / "runtime"))
    from lib.notification_events import drain_notification_queue
    queue = gate.data_root(config) / "config" / "notification-queue.json"
    queue.parent.mkdir()
    queue.write_bytes(b'{"queue":[{"queue_id":"keep-attempt-and-retry"}]}')
    original = queue.read_bytes()
    gate.block_writers(config)
    result = drain_notification_queue(config)
    assert result["blocked"] and result["checked"] == 0
    assert queue.read_bytes() == original


def test_runner_and_capture_refuse_before_any_owned_write(config, monkeypatch):
    import wizard_runner
    import retention_runner
    import activity_log_capture
    monkeypatch.setenv("BORG_SCRIPT_DIR", config["BACKUP_SCRIPTS_DIR"])
    monkeypatch.setattr(wizard_runner, "_run_admitted", lambda: pytest.fail("runner entered"))
    monkeypatch.setattr(retention_runner, "_run_admitted", lambda *a: pytest.fail("prune entered"))
    monkeypatch.setattr(activity_log_capture, "_supervise_admitted", lambda *a: pytest.fail("capture entered"))
    assert wizard_runner.main() == 2
    assert retention_runner.main("id", "run", config["BACKUP_SCRIPTS_DIR"]) == 2
    assert activity_log_capture.supervise(Path("missing"), []) == 2


def test_async_restore_refuses_before_run_or_thread_creation(config, monkeypatch):
    import restore_api
    monkeypatch.setattr(restore_api, "_start_restore_async_admitted", lambda *a, **k: pytest.fail("restore entered"))
    with pytest.raises(gate.MigrationBlocked):
        restore_api.start_restore_async(config, "id", "archive", "source", "target", "skip")


def test_missing_mount_does_not_create_persistent_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("BORG_UI_MIGRATION_GATE_ROOT", str(tmp_path / "gate"))
    config = {"BACKUP_SCRIPTS_DIR": "/mnt/unavailable-identity-test/data"}
    with pytest.raises(gate.MigrationBlocked, match="gate_storage_unavailable"):
        gate.block_writers(config)
    assert not Path(config["BACKUP_SCRIPTS_DIR"]).exists()


def test_repository_scheduler_releases_lease_during_wait_and_rechecks(config, monkeypatch):
    import repositories_api as repositories
    ready(config)
    class Event:
        def wait(self, timeout):
            if timeout:
                gate.block_writers(config)
                with gate.exclusive_migration(config):
                    pass
            return False
        def clear(self):
            pass
    monkeypatch.setattr(repositories, "_REFRESH_WAKE_EVENT", Event())
    monkeypatch.setattr(repositories, "_schedule_repository_info_refresh", lambda cfg: (30, True))
    monkeypatch.setattr(repositories, "_run_repository_info_refresh", lambda *a: pytest.fail("new refresh started"))
    repositories.run_repository_info_refresh_scheduler(config, startup_delay_seconds=0)
    assert repositories._REFRESH_RUNTIME_STATE["worker_state"] == "maintenance"


def test_admitted_repository_refresh_finishes_final_state_before_quiescence(config, monkeypatch):
    from types import SimpleNamespace
    import repositories_api as repositories
    ready(config)
    written = []
    monkeypatch.setattr(repositories, "_REFRESH_WAKE_EVENT", SimpleNamespace(wait=lambda _: False, clear=lambda: None))
    monkeypatch.setattr(repositories, "_schedule_repository_info_refresh", lambda cfg: (0, True))
    monkeypatch.setattr(repositories, "repository_info_refresh_settings", lambda cfg: {})
    monkeypatch.setattr(repositories, "_compute_repository_info_next_run", lambda *a, **k: None)
    monkeypatch.setattr(repositories, "_write_repository_info_refresh_state", lambda cfg, value: written.append(value))
    def refresh(cfg):
        gate.block_writers(cfg)
        with pytest.raises(gate.MigrationBlocked, match="writers_running"):
            with gate.exclusive_migration(cfg):
                pass
        return {"checked": 1, "refreshed": 1}
    monkeypatch.setattr(repositories, "refresh_all_repository_info", refresh)
    repositories.run_repository_info_refresh_scheduler(config, startup_delay_seconds=0)
    assert written[-1]["last_result"]["refreshed"] == 1
    with gate.exclusive_migration(config):
        pass


def test_async_check_and_key_deployment_refuse_before_side_effects(config, monkeypatch):
    from check_api import CheckManager
    from storagebox_api import _StorageKeyDeployManager
    monkeypatch.setattr(CheckManager, "_start_repository_locked", lambda *a, **k: pytest.fail("check entered"))
    monkeypatch.setattr(_StorageKeyDeployManager, "_start_admitted", lambda *a, **k: pytest.fail("key deployment entered"))
    with pytest.raises(gate.MigrationBlocked):
        CheckManager().start_repository(config, "repo")
    with pytest.raises(gate.MigrationBlocked):
        _StorageKeyDeployManager().start(config)
