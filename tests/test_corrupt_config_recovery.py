from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
RUNTIME_LIB = ROOT / "runtime" / "lib"
for path in (API_ROOT, RUNTIME_LIB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import config_api  # noqa: E402
import schedule_api  # noqa: E402
import runtime_recovery  # noqa: E402
from inventory_store import InventoryCorruptError  # noqa: E402
from storage_objects_api import read_storage_store  # noqa: E402
from status import BackupStatus  # noqa: E402


def test_corrupt_storage_inventory_is_not_silently_treated_as_empty(tmp_path: Path):
    storages = tmp_path / "config" / "storages.json"
    storages.parent.mkdir(parents=True)
    storages.write_text("{broken-json", encoding="utf-8")

    with pytest.raises(InventoryCorruptError, match="malformed JSON"):
        read_storage_store({"BACKUP_SCRIPTS_DIR": str(tmp_path)})


def test_corrupt_schedules_json_returns_empty_schedule_set(tmp_path: Path):
    schedules = tmp_path / "config" / "schedules.json"
    schedules.parent.mkdir(parents=True)
    schedules.write_text("{broken-json", encoding="utf-8")

    assert schedule_api.get_schedules({"BACKUP_SCRIPTS_DIR": str(tmp_path)}) == {}


def test_corrupt_runtime_recovery_state_is_reported_without_crashing(tmp_path: Path):
    state_file = tmp_path / "config" / "runtime-recovery.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("{broken-json", encoding="utf-8")

    state = runtime_recovery.read_runtime_recovery_state(state_file)

    assert state["entries"] == []
    assert state["read_error"] == "Runtime recovery state is not readable."


def test_corrupt_backup_status_file_returns_unknown_status(tmp_path: Path):
    status_file = tmp_path / "bad.status"
    status_file.write_text("{broken-json", encoding="utf-8")

    status = BackupStatus.from_file(status_file)

    assert status.source_path == status_file
    assert status.status == "unknown"
    assert status.exit_code == 99
