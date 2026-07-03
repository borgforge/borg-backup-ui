from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LIB = ROOT / "runtime" / "lib"
API_ROOT = ROOT / "api"
for path in (RUNTIME_LIB, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import runtime_recovery  # noqa: E402
from system_health_api import get_system_health_data  # noqa: E402


def test_runtime_recovery_records_pending_and_restart_state(tmp_path: Path):
    state_file = tmp_path / "config" / "runtime-recovery.json"

    entry_id = runtime_recovery.record_runtime_stopped(
        state_file,
        kind="docker",
        targets=[{"id": "abc123", "name": "paperless-ngx"}],
        job_name="Appdata",
        backup_type="appdata",
        backup_location="local",
        log_file="/mnt/user/Logs/Borg-Backup.log",
    )

    summary = runtime_recovery.summarize_runtime_recovery(state_file)
    assert summary["pending_count"] == 1
    assert summary["attention_count"] == 0
    assert summary["active_count"] == 1
    assert summary["docker_pending_count"] == 1
    assert summary["active_entries"][0]["id"] == entry_id
    assert summary["active_entries"][0]["targets"][0]["name"] == "paperless-ngx"

    runtime_recovery.mark_runtime_restarted(state_file, entry_id, success=True, message="started")

    summary = runtime_recovery.summarize_runtime_recovery(state_file)
    assert summary["pending_count"] == 0
    assert runtime_recovery.read_runtime_recovery_state(state_file)["entries"] == []


def test_system_health_exposes_stale_runtime_recovery_warning(tmp_path: Path):
    state_file = tmp_path / "config" / "runtime-recovery.json"
    runtime_recovery.record_runtime_stopped(
        state_file,
        kind="vm",
        targets=[{"id": "LinuxMint", "name": "LinuxMint"}],
        job_name="VMs",
        backup_type="vms",
        backup_location="local",
        log_file="/mnt/user/Logs/Borg-Backup.log",
    )
    state = runtime_recovery.read_runtime_recovery_state(state_file)
    state["entries"][0]["pid"] = 999999999
    state_file.write_text(json.dumps(state), encoding="utf-8")

    health = get_system_health_data({"BACKUP_SCRIPTS_DIR": str(tmp_path)})

    recovery = health["runtime_recovery"]
    assert recovery["pending_count"] == 1
    assert recovery["attention_count"] == 1
    assert recovery["vm_pending_count"] == 1
    assert recovery["entries"][0]["job_name"] == "VMs"


def test_runtime_recovery_acknowledges_failed_entry(tmp_path: Path):
    state_file = tmp_path / "config" / "runtime-recovery.json"
    entry_id = runtime_recovery.record_runtime_stopped(
        state_file,
        kind="docker",
        targets=[{"id": "abc123", "name": "paperless-ngx"}],
        job_name="Appdata",
        backup_type="appdata",
        backup_location="local",
        log_file="/mnt/user/Logs/Borg-Backup.log",
    )
    runtime_recovery.mark_runtime_restarted(state_file, entry_id, success=False, message="restart failed")

    assert runtime_recovery.summarize_runtime_recovery(state_file)["attention_count"] == 1
    assert runtime_recovery.acknowledge_runtime_recovery(state_file, entry_id) is True
    assert runtime_recovery.summarize_runtime_recovery(state_file)["pending_count"] == 0
    assert runtime_recovery.acknowledge_runtime_recovery(state_file, entry_id) is False
