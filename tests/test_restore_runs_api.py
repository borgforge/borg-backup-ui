from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import restore_api  # noqa: E402
from migrations.registry import run_startup_migrations  # noqa: E402


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

    migration = run_startup_migrations(config)
    runs = restore_api.list_restore_runs(config, limit=10)
    history = restore_api.list_restore_history(config, limit=10)
    detail = restore_api.get_restore_history_detail(config, "done-1")

    assert runs["runs"] == []
    assert [row["restore_id"] for row in history["runs"]] == ["active-1", "done-1"]
    done_row = next(row for row in history["runs"] if row["restore_id"] == "done-1")
    active_row = next(row for row in history["runs"] if row["restore_id"] == "active-1")
    assert done_row["duration_seconds"] == 90
    assert active_row["state"] == "aborted"
    assert detail["lines"] == ["extract", "done"]
    assert detail["preserve_owner"] is True
    assert migration["results"]["restore_history_v1"]["migration_id"] == "restore_history_v1"
    assert migration["results"]["restore_history_v1"]["status"] == "applied"
    assert migration["results"]["restore_history_v1"]["details"]["imported"] == 1
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

    first_migration = run_startup_migrations(config)
    first = restore_api.list_restore_history(config, limit=10)
    restore_api._RESTORE_RUNS_LOADED = False
    second_migration = run_startup_migrations(config)
    second = restore_api.list_restore_history(config, limit=10)

    assert first_migration["results"]["restore_history_v1"]["status"] == "applied"
    assert second_migration["results"]["restore_history_v1"]["status"] == "not_required"
    assert [row["restore_id"] for row in first["runs"]] == ["done-1"]
    assert [row["restore_id"] for row in second["runs"]] == ["done-1"]
    assert not (tmp_path / "config" / "restore-history" / "migrations.log.jsonl").exists()


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

    first_migration = run_startup_migrations(config)
    first = restore_api.list_restore_history(config, limit=10)
    fp.write_text(json.dumps(legacy_payload), encoding="utf-8")
    restore_api._RESTORE_RUNS_LOADED = False
    second_migration = run_startup_migrations(config)
    second = restore_api.list_restore_history(config, limit=10)
    persisted = json.loads(fp.read_text(encoding="utf-8"))

    assert first_migration["results"]["restore_history_v1"]["status"] == "applied"
    assert second_migration["results"]["restore_history_v1"]["status"] == "not_required"
    assert second_migration["results"]["restore_history_v1"]["details"]["already_imported"] == 1
    assert [row["restore_id"] for row in first["runs"]] == ["done-1"]
    assert [row["restore_id"] for row in second["runs"]] == ["done-1"]
    assert persisted["runs"] == {}


def test_restore_history_startup_ignores_previous_internal_import_count_when_legacy_file_empty(tmp_path: Path):
    restore_api._RESTORE_RUNS_LOADED = False
    restore_api._RESTORE_RUNS.clear()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    fp = tmp_path / "config" / "restore-runs.json"
    fp.parent.mkdir(parents=True)
    fp.write_text(
        json.dumps({
            "schema_version": 1,
            "updated_at": "2026-06-29T15:38:37",
            "runs": {},
        }),
        encoding="utf-8",
    )
    legacy_internal_state = tmp_path / "config" / "restore-history" / "migration-state.json"
    legacy_internal_state.parent.mkdir(parents=True)
    legacy_internal_state.write_text(json.dumps({
        "schema_version": 1,
        "migration_id": "restore_history_v1_from_restore_runs",
        "status": "applied",
        "details": {"source_file": str(fp), "imported": 5, "active_kept": 0, "errors": []},
    }), encoding="utf-8")
    before = fp.read_text(encoding="utf-8")

    result = run_startup_migrations(config)["results"]["restore_history_v1"]
    after = fp.read_text(encoding="utf-8")

    assert result["status"] == "applied"
    assert result["details"]["imported"] == 0
    assert result["details"]["removed_obsolete_tracking_files"] == [str(legacy_internal_state)]
    assert not legacy_internal_state.exists()
    assert after == before


def test_restore_history_registry_skips_central_registry_completion(tmp_path: Path):
    restore_api._RESTORE_RUNS_LOADED = False
    restore_api._RESTORE_RUNS.clear()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "migration-state.json").write_text(json.dumps({
        "schema_version": 2,
        "migrations": {
            "restore_history_v1": {
                "state": "applied",
                "details": {
                    "migration_id": "restore_history_v1",
                    "runner": "central_migration_registry",
                    "imported": 5,
                },
            },
        },
    }), encoding="utf-8")
    fp = config_dir / "restore-runs.json"
    fp.write_text(json.dumps({"schema_version": 1, "runs": {}}), encoding="utf-8")

    result = run_startup_migrations(config)["results"]["restore_history_v1"]

    assert result["status"] == "skipped"
    assert result["previous_state"] == "applied"


def test_restore_history_registry_rechecks_old_completion_without_runner(tmp_path: Path):
    restore_api._RESTORE_RUNS_LOADED = False
    restore_api._RESTORE_RUNS.clear()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "migration-state.json").write_text(json.dumps({
        "schema_version": 2,
        "migrations": {
            "restore_history_v1": {
                "state": "applied",
                "checked_at": "2026-06-29T15:54:20",
                "source": "startup_check",
                "details": {
                    "status": "applied",
                    "imported": 5,
                    "active_kept": 0,
                    "errors": 0,
                    "source_file": str(config_dir / "restore-runs.json"),
                },
            },
        },
    }), encoding="utf-8")
    fp = config_dir / "restore-runs.json"
    fp.write_text(json.dumps({"schema_version": 1, "runs": {}}), encoding="utf-8")

    result = run_startup_migrations(config)["results"]["restore_history_v1"]

    assert result["status"] == "not_required"
    assert result["runner"] == "central_migration_registry"
    assert result["details"]["pending_count"] == 0
    assert result["details"]["already_imported"] == 0


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
