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

    assert [row["restore_id"] for row in data["runs"]] == ["new-running", "old-done"]
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

    data = restore_api.list_restore_runs(config, limit=10)

    assert data["runs"][0]["state"] == "aborted"
    assert data["runs"][0]["phase"] == "aborted"
    assert data["active"] == []
