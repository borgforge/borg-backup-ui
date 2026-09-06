from pathlib import Path
import json
import multiprocessing
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LIB = ROOT / "runtime" / "lib"
API_ROOT = ROOT / "api"
for path in (RUNTIME_LIB, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from runtime_fixture_support import identity_snapshot
import runtime_recovery  # noqa: E402
from system_health_api import get_system_health_data  # noqa: E402


def _record_runtime_recovery_worker(path: str, index: int, queue) -> None:
    try:
        entry_id = runtime_recovery.record_runtime_stopped(
            Path(path),
            kind="docker",
            targets=[{"id": f"container-{index}", "name": f"container-{index}"}],
            snapshot=identity_snapshot(f"Job {index}"),
            log_file=f"/mnt/user/Logs/Borg-Backup-{index}.log",
        )
        queue.put(("ok", entry_id))
    except Exception as exc:
        queue.put(("error", repr(exc)))


def test_runtime_recovery_records_pending_and_restart_state(tmp_path: Path):
    state_file = tmp_path / "config" / "runtime-recovery.json"

    entry_id = runtime_recovery.record_runtime_stopped(
        state_file,
        kind="docker",
        targets=[{"id": "abc123", "name": "paperless-ngx"}],
        snapshot=identity_snapshot("Appdata"),
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
        snapshot=identity_snapshot("VMs"),
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
    assert recovery["entries"][0]["job_name_snapshot"] == "VMs"


def test_runtime_recovery_acknowledges_failed_entry(tmp_path: Path):
    state_file = tmp_path / "config" / "runtime-recovery.json"
    entry_id = runtime_recovery.record_runtime_stopped(
        state_file,
        kind="docker",
        targets=[{"id": "abc123", "name": "paperless-ngx"}],
        snapshot=identity_snapshot("Appdata"),
        log_file="/mnt/user/Logs/Borg-Backup.log",
    )
    runtime_recovery.mark_runtime_restarted(state_file, entry_id, success=False, message="restart failed")

    assert runtime_recovery.summarize_runtime_recovery(state_file)["attention_count"] == 1
    assert runtime_recovery.acknowledge_runtime_recovery(state_file, entry_id) is True
    assert runtime_recovery.summarize_runtime_recovery(state_file)["pending_count"] == 0
    assert runtime_recovery.acknowledge_runtime_recovery(state_file, entry_id) is False


def test_runtime_recovery_records_concurrent_stops_without_tmp_race(tmp_path: Path):
    state_file = tmp_path / "config" / "runtime-recovery.json"
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue()
    processes = [
        ctx.Process(target=_record_runtime_recovery_worker, args=(str(state_file), index, queue))
        for index in range(8)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)

    for process in processes:
        assert process.exitcode == 0
    results = [queue.get(timeout=1) for _process in processes]
    assert all(kind == "ok" and entry_id for kind, entry_id in results)

    state = runtime_recovery.read_runtime_recovery_state(state_file)
    names = sorted(entry["targets"][0]["name"] for entry in state["entries"])
    assert names == [f"container-{index}" for index in range(8)]
    assert list(state_file.parent.glob("*.tmp")) == []
