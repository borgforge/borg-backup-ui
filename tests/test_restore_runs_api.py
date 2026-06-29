from pathlib import Path
import json
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


def test_restore_runs_v1_migration_writes_history_index_details_and_audit(tmp_path: Path):
    restore_api._RESTORE_RUNS_LOADED = False
    restore_api._RESTORE_RUNS.clear()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    fp = tmp_path / "config" / "restore-runs.json"
    fp.parent.mkdir(parents=True)
    fp.write_text(
        json.dumps({
            "schema_version": 1,
            "runs": {
                "done-1": {
                    "restore_id": "done-1",
                    "state": "done",
                    "phase": "done",
                    "started_at": "2026-06-29T08:00:00",
                    "finished_at": "2026-06-29T08:01:30",
                    "job_key": "appdata_local",
                    "archive": "appdata-archive",
                    "source_path": "appdata",
                    "target_dir": "/mnt/user/restore",
                    "destination_path": "/mnt/user/restore/appdata",
                    "conflict_mode": "skip",
                    "preserve_owner": True,
                    "lines": ["extract", "done"],
                },
                "active-1": {
                    "restore_id": "active-1",
                    "state": "running",
                    "phase": "extract",
                    "started_at": "2026-06-29T09:00:00",
                    "job_key": "photos_local",
                    "archive": "photos-archive",
                    "lines": ["running"],
                },
            },
        }),
        encoding="utf-8",
    )

    runs = restore_api.list_restore_runs(config, limit=10)
    history = restore_api.list_restore_history(config, limit=10)
    detail = restore_api.get_restore_history_detail(config, "done-1")
    migration = restore_api.get_restore_history_migration(config)

    assert runs["runs"] == []
    assert [row["restore_id"] for row in history["runs"]] == ["active-1", "done-1"]
    done_row = next(row for row in history["runs"] if row["restore_id"] == "done-1")
    active_row = next(row for row in history["runs"] if row["restore_id"] == "active-1")
    assert done_row["duration_seconds"] == 90
    assert active_row["state"] == "aborted"
    assert detail["lines"] == ["extract", "done"]
    assert detail["preserve_owner"] is True
    assert migration["state"]["migration_id"] == "restore_history_v1_from_restore_runs"
    assert migration["state"]["status"] == "applied"
    assert migration["state"]["details"]["imported"] == 2
    assert migration["log"][-1]["status"] == "applied"
    persisted = json.loads(fp.read_text(encoding="utf-8"))
    assert persisted["runs"] == {}


def test_restore_history_migration_is_idempotent(tmp_path: Path):
    restore_api._RESTORE_RUNS_LOADED = False
    restore_api._RESTORE_RUNS.clear()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    fp = tmp_path / "config" / "restore-runs.json"
    fp.parent.mkdir(parents=True)
    fp.write_text(
        json.dumps({
            "schema_version": 1,
            "runs": {
                "done-1": {
                    "restore_id": "done-1",
                    "state": "done",
                    "started_at": "2026-06-29T08:00:00",
                    "finished_at": "2026-06-29T08:00:10",
                    "job_key": "appdata_local",
                    "archive": "appdata-archive",
                    "lines": ["done"],
                }
            },
        }),
        encoding="utf-8",
    )

    first = restore_api.list_restore_history(config, limit=10)
    restore_api._RESTORE_RUNS_LOADED = False
    second = restore_api.list_restore_history(config, limit=10)
    log_file = tmp_path / "config" / "restore-history" / "migrations.log.jsonl"

    assert [row["restore_id"] for row in first["runs"]] == ["done-1"]
    assert [row["restore_id"] for row in second["runs"]] == ["done-1"]
    assert len(log_file.read_text(encoding="utf-8").splitlines()) == 1


def test_restore_history_migration_skips_already_imported_legacy_entries(tmp_path: Path):
    restore_api._RESTORE_RUNS_LOADED = False
    restore_api._RESTORE_RUNS.clear()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    fp = tmp_path / "config" / "restore-runs.json"
    fp.parent.mkdir(parents=True)
    legacy_payload = {
        "schema_version": 1,
        "runs": {
            "done-1": {
                "restore_id": "done-1",
                "state": "done",
                "started_at": "2026-06-29T08:00:00",
                "finished_at": "2026-06-29T08:00:10",
                "job_key": "appdata_local",
                "archive": "appdata-archive",
                "lines": ["done"],
            }
        },
    }
    fp.write_text(json.dumps(legacy_payload), encoding="utf-8")

    first = restore_api.list_restore_history(config, limit=10)
    fp.write_text(json.dumps(legacy_payload), encoding="utf-8")
    restore_api._RESTORE_RUNS_LOADED = False
    second = restore_api.list_restore_history(config, limit=10)
    log_file = tmp_path / "config" / "restore-history" / "migrations.log.jsonl"
    persisted = json.loads(fp.read_text(encoding="utf-8"))

    assert [row["restore_id"] for row in first["runs"]] == ["done-1"]
    assert [row["restore_id"] for row in second["runs"]] == ["done-1"]
    assert len(log_file.read_text(encoding="utf-8").splitlines()) == 1
    assert persisted["runs"] == {}


def test_restore_history_retention_keeps_latest_details(tmp_path: Path):
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

    assert history["total"] == 100
    assert history["runs"][0]["restore_id"] == "run-104"
    assert not (runs_dir / "run-0.json").exists()
    assert (runs_dir / "run-104.json").exists()
