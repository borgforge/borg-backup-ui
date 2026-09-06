from runtime_fixture_support import job_config_identity
import json
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
RUNTIME_ROOT = ROOT / "runtime"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from job_control import JobControl, read_control_state, request_cancel  # noqa: E402
from runtime.lib.backup_job import (  # noqa: E402
    BackupJob,
    BackupJobConfig,
    RUNTIME_RECOVERY_FAILED,
    USER_CANCELLED,
)
from runtime.lib.vm_manager import VmShutdownResult, VmStartResult  # noqa: E402


def _config(tmp_path: Path) -> BackupJobConfig:
    return BackupJobConfig(
        job_name="cancel-test",
        **job_config_identity("appdata"),
        backup_location="local",
        lock_file=tmp_path / "backup.lock",
        log_dir=tmp_path,
        log_file=tmp_path / "backup.log",
        backup_paths=[tmp_path],
        borg_cache_dir=tmp_path / "cache",
        date_tag="2026-07-16",
        runtime_recovery_file=tmp_path / "runtime-recovery.json",
    )


def test_cancel_marker_preserves_deferred_stop_phase(tmp_path: Path):
    control = JobControl("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", tmp_path)
    control.update_phase(
        "stopping_docker",
        cancel_allowed=True,
        cancellation_deferred=True,
        message_key="jobs.cancelPendingDocker",
    )

    state = request_cancel(
        "11111111-1111-4111-8111-111111111111",
        control.run_id,
        requested_by="admin",
        root=tmp_path,
    )

    assert state["cancel_requested"] is True
    assert state["cancellation_deferred"] is True
    assert state["message_key"] == "jobs.cancelPendingDocker"
    marker = json.loads(control.cancel_file.read_text(encoding="utf-8"))
    assert marker["requested_by"] == "admin"
    assert read_control_state(control.run_id, tmp_path)["cancel_requested"] is True


def test_cancel_is_rejected_during_runtime_recovery(tmp_path: Path):
    control = JobControl("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", tmp_path)
    control.update_phase(
        "recovering_vms",
        cancel_allowed=False,
        message_key="jobs.cancelUnavailableRecovery",
    )

    with pytest.raises(RuntimeError, match="no longer possible"):
        request_cancel("11111111-1111-4111-8111-111111111111", control.run_id, root=tmp_path)


def test_cancel_monitor_sends_sigint_to_active_borg_process(tmp_path: Path):
    class Process:
        def __init__(self):
            self.signals = []

        def poll(self):
            return None

        def send_signal(self, sig):
            self.signals.append(sig)

    process = Process()
    control = JobControl("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", tmp_path)
    control.update_phase("borg_create", cancel_allowed=True)
    control.attach_process(process)
    try:
        request_cancel("11111111-1111-4111-8111-111111111111", control.run_id, root=tmp_path)
        deadline = time.monotonic() + 2.0
        while not process.signals and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        control.detach_process()

    assert process.signals == [signal.SIGINT]


def test_cancelled_job_skips_normal_notifications(monkeypatch, tmp_path: Path):
    job = BackupJob(_config(tmp_path))
    calls = []
    monkeypatch.setattr(job, "_save_status", lambda _duration: calls.append("status"))
    monkeypatch.setattr(job, "_send_notification_event", lambda *_args, **_kwargs: calls.append("notify"))

    with job:
        job.set_cancelled()

    assert job._borg_exit == 130
    assert job._failure_code == USER_CANCELLED
    assert calls == ["status"]


def test_recovery_failure_overrides_accepted_cancellation(monkeypatch, tmp_path: Path):
    class FailingVmManager:
        config = SimpleNamespace(shutdown_timeout=60)

        def start_all(self, _shutdown_result):
            return VmStartResult(
                target_vms=["LinuxMint"],
                started_vms=[],
                failed_vms=["LinuxMint"],
            )

    job = BackupJob(_config(tmp_path), vm_manager=FailingVmManager())
    job._vm_shutdown_result = VmShutdownResult(stopped_vms=["LinuxMint"])
    monkeypatch.setattr(job, "_mark_runtime_restarted", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(job, "_do_finish", lambda: None)

    with pytest.raises(RuntimeError, match="Backup cleanup failed"):
        with job:
            job.set_cancelled()

    assert job._borg_exit == 2
    assert job._cancelled is False
    assert job._failure_code == RUNTIME_RECOVERY_FAILED


def test_runner_defers_cancellation_until_runtime_stop_finishes():
    source = (API_ROOT / "wizard_runner.py").read_text(encoding="utf-8")

    docker_stop = source.index("job.stop_docker(selected)")
    docker_except_stop = source.index("job.stop_docker(exclude_names=selected)")
    docker_cancel = source.index("Cancellation requested; Docker stop completed")
    vm_stop = source.index("job.shutdown_vms(selected)")
    vm_cancel = source.index("Cancellation requested; VM shutdown completed")

    assert docker_stop < docker_cancel < vm_stop < vm_cancel
    assert docker_except_stop < docker_cancel
    assert 'phase in {"recovering_docker", "recovering_vms", "unmounting"}' in source
    assert 'terminal_phase = "cancelled" if result_code == 130' in source


def test_cancelled_status_is_localized_across_primary_views():
    jobs = (ROOT / "ui/js/pages/jobs.js").read_text(encoding="utf-8")
    dashboard = (ROOT / "ui/js/pages/dashboard.js").read_text(encoding="utf-8")
    history = (ROOT / "ui/js/pages/history.js").read_text(encoding="utf-8")
    reports = (ROOT / "ui/js/pages/reports.js").read_text(encoding="utf-8")

    assert "statusCancelled" in jobs
    assert "statusCancelled" in dashboard
    assert "statusCancelled" in history
    assert "statusCancelled" in reports


def test_jobs_page_keeps_runtime_state_during_full_refresh():
    jobs = (ROOT / "ui/js/pages/jobs.js").read_text(encoding="utf-8")

    refresh_start = jobs.index("async function refreshJobs()")
    refresh_end = jobs.index("// ── Jobs-Polling", refresh_start)
    refresh_source = jobs[refresh_start:refresh_end]

    assert "fetch('/api/jobs/running')" in refresh_source
    assert "jobRuntimeState(runningData[j.job_id])" in refresh_source
    assert "setInterval(_pollRunningStates, 3_000)" in jobs


def test_jobs_page_uses_structured_runtime_actions():
    jobs = (ROOT / "ui/js/pages/jobs.js").read_text(encoding="utf-8")
    styles = (ROOT / "ui/dashboard-jobs.css").read_text(encoding="utf-8")

    assert 'class="jobs-running-state"' in jobs
    assert 'class="jobs-running-buttons"' in jobs
    assert 'class="jobs-running-message"' in jobs
    assert ".jobs-running-actions" in styles
    assert ".jobs-running-message" in styles
