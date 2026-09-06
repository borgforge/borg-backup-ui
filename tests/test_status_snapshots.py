import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
RUNTIME_LIB = ROOT / "runtime" / "lib"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(ROOT / "runtime") not in sys.path:
    sys.path.insert(0, str(ROOT / "runtime"))
if str(RUNTIME_LIB) not in sys.path:
    sys.path.insert(0, str(RUNTIME_LIB))

import status_api  # noqa: E402
import status  # noqa: E402
from status_api import get_status_data
from weekly_snapshots import write_current as _auto_write_weekly_snapshot
from status_view_fixture_support import job_id_for, write_job, status_identity
import pytest
from test_canonical_status_views import observation, snapshot  # noqa: E402


def test_weekly_snapshots_block_unmigrated_input_without_modifying_it(tmp_path):
    path = tmp_path / 'weekly-snapshots.json'
    path.write_text(json.dumps({'appdata_local': [{'week': '2026-06-22', 'size': 100}]}))
    before = path.read_bytes()
    with pytest.raises(ValueError, match='approved identity migration'):
        _auto_write_weekly_snapshot(path, {}, force=True)
    assert path.read_bytes() == before


def test_weekly_snapshot_does_not_create_path_below_unmounted_user_share(monkeypatch):
    monkeypatch.setattr(status, "storage_mount_is_mounted", lambda _path: False)

    with (
        patch.object(Path, "mkdir") as mkdir_mock,
        patch.object(Path, "write_text") as write_mock,
    ):
        _auto_write_weekly_snapshot(
            Path("/mnt/user/borg_backup_ui/weekly-snapshots.json"),
            {"appdata_local": SimpleNamespace(repository_size=200)},
            force=True,
        )

    mkdir_mock.assert_not_called()
    write_mock.assert_not_called()


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
    write_job(status_dir.parent, 'appdata_local', name='Appdata')
    base.update(status_identity(status_dir.parent, 'appdata_local'))
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

    data = get_status_data({"BACKUP_SCRIPTS_DIR": str(tmp_path), "STATUS_DIR": str(status_dir), "SNAPSHOT_FILE": str(snapshot_file)})
    row = data["backups"][0]

    assert row["job_id"] == job_id_for("appdata_local")
    assert row["growth_bytes"] == 50
    assert row["growth_formatted"] == "+50 B"


def test_dashboard_growth_prefers_weekly_snapshot_over_previous_status(tmp_path: Path):
    status_dir = tmp_path / "status"
    snapshot_file = tmp_path / "weekly-snapshots.json"
    snapshot(snapshot_file, [observation(job_id_for('appdata_local'), week, size,
        repository_snapshot=str(tmp_path / 'repos/local/appdata_local')) for week, size in (
            ('2026-06-22', 120), ('2026-06-29', 140))])
    _write_status(status_dir, "old.status", {
        "timestamp": "2026-07-01 09:00:00",
        "repository_size": 100,
    })
    _write_status(status_dir, "new.status", {
        "timestamp": "2026-07-02 09:00:00",
        "repository_size": 150,
    })

    data = get_status_data({"BACKUP_SCRIPTS_DIR": str(tmp_path), "STATUS_DIR": str(status_dir), "SNAPSHOT_FILE": str(snapshot_file)})
    row = data["backups"][0]

    assert row["growth_bytes"] == 10
    assert row["growth_formatted"] == "+10 B"


def test_dashboard_marks_missed_scheduled_backup_overdue(monkeypatch):
    backups = [{
        "job_id": job_id_for("appdata_local"),
        "backup_type": "appdata",
        "location": "local",
        "status": "success",
        "timestamp": "2026-07-01 14:00:00",
    }]

    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {
        job_id_for("appdata_local"): {"enabled": True, "cron": "0 14 * * *"},
    })
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, ctx: [{
        "job_id": job_id_for("appdata_local"),
        "name": "Appdata",
        "enabled": True,
    }])

    status_api._apply_backup_overdue_metadata(
        {"NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": "1"},
        backups,
        now=status_api.datetime(2026, 7, 2, 15, 1, 0),
    )

    assert backups[0]["backup_overdue"] is True
    assert backups[0]["backup_overdue_state"] == "overdue_ready"
    assert backups[0]["backup_overdue_expected_run"] == "2026-07-02T14:00:00"
    assert backups[0]["backup_overdue_after"] == "2026-07-02T15:00:00"


def test_dashboard_keeps_current_scheduled_backup_success(monkeypatch):
    backups = [{
        "job_id": job_id_for("appdata_local"),
        "backup_type": "appdata",
        "location": "local",
        "status": "success",
        "timestamp": "2026-07-02 14:02:00",
    }]

    monkeypatch.setattr("schedule_api.get_schedules", lambda cfg: {
        job_id_for("appdata_local"): {"enabled": True, "cron": "0 14 * * *"},
    })
    monkeypatch.setattr("jobs_api.list_jobs", lambda cfg, ctx: [{
        "job_id": job_id_for("appdata_local"),
        "name": "Appdata",
        "enabled": True,
    }])

    status_api._apply_backup_overdue_metadata(
        {"NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": "1"},
        backups,
        now=status_api.datetime(2026, 7, 2, 15, 1, 0),
    )

    assert backups[0]["backup_overdue"] is False
    assert backups[0]["backup_overdue_state"] == "current"
