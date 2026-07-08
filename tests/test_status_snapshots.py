import json
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
RUNTIME_LIB = ROOT / "runtime" / "lib"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(RUNTIME_LIB) not in sys.path:
    sys.path.insert(0, str(RUNTIME_LIB))

from status_api import get_status_data, _auto_write_weekly_snapshot, _import_legacy_snapshot_if_needed  # noqa: E402


def test_weekly_snapshots_import_legacy_once_and_write_only_canonical(tmp_path: Path):
    status_dir = tmp_path / "status"
    snapshot_file = tmp_path / "weekly-snapshots.json"
    legacy_snapshot_file = status_dir / "weekly-snapshots.json"
    legacy_snapshot_file.parent.mkdir(parents=True)
    legacy_snapshot_file.write_text(
        json.dumps({"appdata_local": [{"week": "2026-06-22", "size": 100}]}),
        encoding="utf-8",
    )

    _import_legacy_snapshot_if_needed(snapshot_file, legacy_snapshot_file)
    _auto_write_weekly_snapshot(
        snapshot_file,
        {"appdata_local": SimpleNamespace(repository_size=200)},
        force_write=True,
    )

    canonical = json.loads(snapshot_file.read_text(encoding="utf-8"))
    legacy = json.loads(legacy_snapshot_file.read_text(encoding="utf-8"))

    assert canonical["appdata_local"][-1]["size"] == 200
    assert legacy == {"appdata_local": [{"week": "2026-06-22", "size": 100}]}


def _write_status(status_dir: Path, name: str, payload: dict) -> None:
    status_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "backup_type": "appdata",
        "location": "local",
        "timestamp": "2026-07-01 10:00:00",
        "duration_seconds": 60,
        "exit_code": 0,
        "status": "success",
        "repository_size": 0,
    }
    base.update(payload)
    (status_dir / name).write_text(json.dumps(base), encoding="utf-8")


def test_dashboard_growth_falls_back_to_previous_status_when_snapshot_baseline_missing(tmp_path: Path):
    status_dir = tmp_path / "status"
    snapshot_file = tmp_path / "weekly-snapshots.json"
    _write_status(status_dir, "old.status", {
        "timestamp": "2026-07-01 09:00:00",
        "repository_size": 100,
    })
    _write_status(status_dir, "new.status", {
        "timestamp": "2026-07-02 09:00:00",
        "repository_size": 150,
    })

    data = get_status_data({"STATUS_DIR": str(status_dir), "SNAPSHOT_FILE": str(snapshot_file)})
    row = data["backups"][0]

    assert row["key"] == "appdata_local"
    assert row["growth_bytes"] == 50
    assert row["growth_formatted"] == "+50 B"


def test_dashboard_growth_prefers_weekly_snapshot_over_previous_status(tmp_path: Path):
    status_dir = tmp_path / "status"
    snapshot_file = tmp_path / "weekly-snapshots.json"
    snapshot_file.write_text(
        json.dumps({"appdata_local": [
            {"week": "2026-06-22", "size": 120},
            {"week": "2026-06-29", "size": 140},
        ]}),
        encoding="utf-8",
    )
    _write_status(status_dir, "old.status", {
        "timestamp": "2026-07-01 09:00:00",
        "repository_size": 100,
    })
    _write_status(status_dir, "new.status", {
        "timestamp": "2026-07-02 09:00:00",
        "repository_size": 150,
    })

    data = get_status_data({"STATUS_DIR": str(status_dir), "SNAPSHOT_FILE": str(snapshot_file)})
    row = data["backups"][0]

    assert row["growth_bytes"] == 10
    assert row["growth_formatted"] == "+10 B"
