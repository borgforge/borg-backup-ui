from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import restore_api  # noqa: E402


def test_list_restore_runs_returns_recent_and_active_runs(tmp_path: Path):
    restore_api._RESTORE_RUNS_LOADED = True
    restore_api._RESTORE_RUNS.clear()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    restore_api._RESTORE_RUNS.update({
        "old-done": {
            "restore_id": "old-done",
            "state": "done",
            "phase": "done",
            "started_at": "2026-06-28T10:00:00",
            "finished_at": "2026-06-28T10:05:00",
            "job_key": "photos_local",
            "archive": "photos-archive",
            "source_path": "photos",
            "target_dir": "/mnt/user/restore",
            "destination_path": "/mnt/user/restore/photos",
            "lines": ["done"],
        },
        "new-running": {
            "restore_id": "new-running",
            "state": "running",
            "phase": "extract",
            "started_at": "2026-06-29T10:00:00",
            "job_key": "appdata_local",
            "archive": "appdata-archive",
            "source_path": "appdata",
            "target_dir": "/mnt/user/restore",
            "lines": ["line1", "line2"],
        },
    })

    data = restore_api.list_restore_runs(config, limit=10)

    assert [row["restore_id"] for row in data["runs"]] == ["new-running"]
    assert [row["restore_id"] for row in data["active"]] == ["new-running"]
    assert data["runs"][0]["lines"] == ["line1", "line2"]


def test_loading_restore_runs_marks_stale_running_runs_aborted(tmp_path: Path):
    restore_api._RESTORE_RUNS_LOADED = False
    restore_api._RESTORE_RUNS.clear()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    fp = tmp_path / "config" / "restore-runs.json"
    fp.parent.mkdir(parents=True)
    fp.write_text(
        """{
  "schema_version": 1,
  "runs": {
    "stale": {
      "restore_id": "stale",
      "state": "running",
      "phase": "extract",
      "started_at": "2026-06-29T09:00:00",
      "job_key": "appdata_local",
      "archive": "appdata-archive",
      "lines": []
    }
  }
}
""",
        encoding="utf-8",
    )

    runs = restore_api.list_restore_runs(config, limit=10)
    history = restore_api.list_restore_history(config, limit=10)

    assert runs["runs"] == []
    assert runs["active"] == []
    assert history["runs"][0]["restore_id"] == "stale"
    assert history["runs"][0]["state"] == "aborted"
    assert history["runs"][0]["phase"] == "aborted"


def test_restore_history_keeps_all_details(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    for idx in range(105):
        restore_api._record_restore_history(config, {
            "restore_id": f"run-{idx}",
            "state": "done",
            "started_at": f"2026-06-29T08:00:00.{idx:03d}",
            "finished_at": f"2026-06-29T08:00:01.{idx:03d}",
            "job_key": "appdata_local",
            "archive": "appdata-archive",
            "lines": [f"line-{idx}"],
        }, "test")

    history = restore_api.list_restore_history(config, limit=200)
    runs_dir = tmp_path / "config" / "restore-history" / "runs"

    assert history["total"] == 105
    assert history["runs"][0]["restore_id"] == "run-104"
    assert (runs_dir / "run-0.json").exists()
    assert (runs_dir / "run-104.json").exists()


def test_restore_history_delete_removes_index_and_detail(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    restore_api._record_restore_history(config, {
        "restore_id": "delete-me",
        "state": "done",
        "started_at": "2026-06-29T08:00:00",
        "finished_at": "2026-06-29T08:00:01",
        "job_key": "appdata_local",
        "archive": "appdata-archive",
        "lines": ["restore done"],
    }, "test")
    runs_dir = tmp_path / "config" / "restore-history" / "runs"

    result = restore_api.delete_restore_history_entry(config, "delete-me")
    history = restore_api.list_restore_history(config, limit=0)

    assert result["deleted"] is True
    assert result["detail_deleted"] is True
    assert history["total"] == 0
    assert not (runs_dir / "delete-me.json").exists()
