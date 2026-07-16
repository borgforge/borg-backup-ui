from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from runtime.lib.backup_job import BackupJob, BackupJobConfig  # noqa: E402
from runtime.lib import runtime_recovery, vm_manager  # noqa: E402


def _completed(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def _backup_config(tmp_path: Path) -> BackupJobConfig:
    return BackupJobConfig(
        job_name="VMs",
        backup_type="vms",
        backup_location="local",
        lock_file=tmp_path / "backup.lock",
        log_dir=tmp_path,
        log_file=tmp_path / "backup.log",
        backup_paths=[tmp_path],
        borg_cache_dir=tmp_path / "cache",
        date_tag="2026-07-14",
        runtime_recovery_file=tmp_path / "runtime-recovery.json",
    )


def test_start_all_checks_only_target_vms(monkeypatch):
    calls = []
    manager = vm_manager.VmManager(vm_manager.VmConfig(startup_wait=0))
    monkeypatch.setattr(vm_manager, "virsh_available", lambda: True)
    monkeypatch.setattr(vm_manager.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        vm_manager.subprocess,
        "run",
        lambda cmd, **_kwargs: calls.append(cmd) or _completed(cmd),
    )
    monkeypatch.setattr(
        manager,
        "_get_running_vms",
        lambda: ["Unrelated", "LinuxMint", "Windows11"],
    )

    result = manager.start_all(
        vm_manager.VmShutdownResult(stopped_vms=["LinuxMint", "Windows11"])
    )

    assert result.success is True
    assert result.started_vms == ["LinuxMint", "Windows11"]
    assert result.failed_vms == []
    assert result.count_after == 2
    assert calls == [["virsh", "start", "LinuxMint"], ["virsh", "start", "Windows11"]]


def test_start_all_reports_partial_failure(monkeypatch, caplog):
    manager = vm_manager.VmManager(vm_manager.VmConfig(startup_wait=0))
    monkeypatch.setattr(vm_manager, "virsh_available", lambda: True)
    monkeypatch.setattr(vm_manager.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(vm_manager.subprocess, "run", lambda cmd, **_kwargs: _completed(cmd))
    monkeypatch.setattr(manager, "_get_running_vms", lambda: ["Unrelated", "LinuxMint"])

    with caplog.at_level("WARNING", logger="runtime.lib.vm_manager"):
        result = manager.start_all(
            vm_manager.VmShutdownResult(stopped_vms=["LinuxMint", "Windows11"])
        )

    assert result.success is False
    assert result.started_vms == ["LinuxMint"]
    assert result.failed_vms == ["Windows11"]
    assert "Windows11" in caplog.text


def test_start_all_reports_all_targets_failed_when_virsh_is_unavailable(monkeypatch):
    manager = vm_manager.VmManager(vm_manager.VmConfig(startup_wait=0))
    monkeypatch.setattr(vm_manager, "virsh_available", lambda: False)

    result = manager.start_all(
        vm_manager.VmShutdownResult(stopped_vms=["LinuxMint", "Windows11"])
    )

    assert result.available is False
    assert result.success is False
    assert result.started_vms == []
    assert result.failed_vms == ["LinuxMint", "Windows11"]


def test_backup_job_keeps_failed_vm_recovery_open(monkeypatch, tmp_path: Path):
    class FailingVmManager:
        def start_all(self, _shutdown_result):
            return vm_manager.VmStartResult(
                target_vms=["LinuxMint", "Windows11"],
                started_vms=["LinuxMint"],
                failed_vms=["Windows11"],
            )

    job = BackupJob(_backup_config(tmp_path), vm_manager=FailingVmManager())
    job._vm_shutdown_result = vm_manager.VmShutdownResult(
        stopped_vms=["LinuxMint", "Windows11"]
    )
    job._record_vm_recovery_state()

    with pytest.raises(RuntimeError, match="Windows11"):
        job.start_vms()

    summary = runtime_recovery.summarize_runtime_recovery(
        job.config.runtime_recovery_file
    )
    assert summary["pending_count"] == 1
    assert summary["attention_count"] == 1
    assert summary["vm_attention_count"] == 1
    assert summary["entries"][0]["state"] == "restart_failed"
    assert "Windows11" in summary["entries"][0]["message"]


def test_backup_job_removes_successful_vm_recovery(tmp_path: Path):
    class SuccessfulVmManager:
        def start_all(self, _shutdown_result):
            return vm_manager.VmStartResult(
                target_vms=["LinuxMint", "Windows11"],
                started_vms=["LinuxMint", "Windows11"],
            )

    job = BackupJob(_backup_config(tmp_path), vm_manager=SuccessfulVmManager())
    job._vm_shutdown_result = vm_manager.VmShutdownResult(
        stopped_vms=["LinuxMint", "Windows11"]
    )
    job._record_vm_recovery_state()

    job.start_vms()

    summary = runtime_recovery.summarize_runtime_recovery(
        job.config.runtime_recovery_file
    )
    assert summary["pending_count"] == 0
    assert summary["attention_count"] == 0
    assert runtime_recovery.read_runtime_recovery_state(
        job.config.runtime_recovery_file
    )["entries"] == []
