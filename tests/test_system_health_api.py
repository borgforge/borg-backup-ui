from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from system_health_api import _build_migration_summary, _collect_job_health, _last_migration_successful, _probe_cifs_support, _read_migration_state, get_system_health_data


def test_migration_summary_without_run():
    summary = _build_migration_summary({}, {"last_event": {}, "last_effective_event": {}})

    assert summary["status"] == "none"
    assert summary["state"] == "No run yet"
    assert summary["last_run"] == ""
    assert summary["reason"] == "No migration run has been recorded yet"
    assert summary["actions"] == []
    assert summary["errors"] == []


def test_last_migration_successful_reads_v2_last_run():
    migration = {
        "schema_version": 2,
        "last_run": {
            "success": True,
            "reason_code": "no_changes",
        },
    }

    assert _last_migration_successful(migration) is True


def test_read_migration_state_preserves_v2_last_run(tmp_path):
    state_file = tmp_path / "migration-state.json"
    state_file.write_text(
        """{
  "schema_version": 2,
  "last_run": {
    "timestamp": "2026-06-07T10:02:47",
    "success": true,
    "reason_code": "no_changes"
  },
  "migrations": {}
}
""",
        encoding="utf-8",
    )

    migration = _read_migration_state(state_file)

    assert migration["schema_version"] == 2
    assert migration["last_run"]["success"] is True
    assert _last_migration_successful(migration) is True


def test_last_migration_successful_keeps_legacy_state_support():
    assert _last_migration_successful({"success": True}) is True
    assert _last_migration_successful({"success": False}) is False


def test_migration_summary_extracts_actions_and_errors():
    event = {
        "success": False,
        "timestamp": "2026-06-06T23:40:00",
        "reason_code": "error",
        "message": "broken_v1=failed",
        "details": {
            "startup_migrations": {
                "status": "failed",
                "applied": [],
                "failed": ["broken_v1"],
                "results": {
                    "broken_v1": {
                        "migration_id": "broken_v1",
                        "status": "failed",
                        "details": {"errors": [{"error": "boom"}]},
                    },
                },
            },
        },
    }
    summary = _build_migration_summary(event, {
        "last_event": event,
        "last_effective_event": {"timestamp": "2026-06-06T23:41:00"},
    })

    assert summary["status"] == "failed"
    assert summary["state"] == "Failed"
    assert summary["last_run"] == "2026-06-06T23:40:00"
    assert summary["last_effective_run"] == "2026-06-06T23:41:00"
    assert summary["reason"] == "Migration completed with errors"
    assert summary["actions"] == []
    assert "broken_v1: 1 error(s)" in summary["errors"]


def test_migration_summary_extracts_restore_history_migration():
    event = {
        "success": True,
        "timestamp": "2026-06-29T13:45:00",
        "reason_code": "restore_history_migrated",
        "reason_text": "Restore-History aus restore-runs.json migriert",
        "message": "restore_history_v1=applied",
        "details": {
            "startup_migrations": {
                "status": "ok",
                "applied": ["restore_history_v1"],
                "failed": [],
                "results": {
                    "restore_history_v1": {
                        "migration_id": "restore_history_v1",
                        "status": "applied",
                        "details": {
                            "migration_id": "restore_history_v1",
                            "runner": "central_migration_registry",
                            "imported": 5,
                        },
                    },
                },
            },
        },
    }

    summary = _build_migration_summary(event, {"last_event": event, "last_effective_event": event})

    assert summary["status"] == "success"
    assert summary["reason_code"] == "restore_history_migrated"
    assert "restore_history_v1 applied" in summary["actions"]
    assert "5 restore run(s) migrated" in summary["actions"]
    assert summary["errors"] == []


def test_migration_summary_extracts_startup_migration_actions():
    event = {
        "success": True,
        "timestamp": "2026-06-29T22:41:34",
        "reason_code": "startup_migrations_applied",
        "reason_text": "Startup-Migrationen angewendet",
        "message": "notification_events_v1=applied",
        "details": {
            "startup_migrations": {
                "status": "ok",
                "applied": ["notification_events_v1"],
                "skipped": [],
                "failed": [],
                "results": {
                    "notification_events_v1": {
                        "status": "applied",
                        "details": {
                            "updated_keys": ["NTFY_EVENTS"],
                        },
                    },
                },
            },
        },
    }

    summary = _build_migration_summary(event, {"last_event": event, "last_effective_event": event})

    assert summary["status"] == "success"
    assert summary["reason_code"] == "startup_migrations_applied"
    assert summary["last_run"] == "2026-06-29T22:41:34"
    assert summary["last_effective_run"] == "2026-06-29T22:41:34"
    assert "notification_events_v1 applied" in summary["actions"]
    assert "Updated keys: NTFY_EVENTS" in summary["actions"]
    assert summary["errors"] == []


def test_migration_summary_no_changes_has_no_actions():
    event = {
        "success": True,
        "timestamp": "2026-06-07T00:30:00",
        "reason_code": "no_changes",
        "reason_text": "Keine Änderungen nötig",
        "message": "jobs_layout=ok; storage_paths=ok(changed=False)",
        "details": {
            "storage_paths": {"changed": False, "moved": 0, "move_errors": 0},
            "jobs_layout": {"status": "ok"},
        },
    }

    summary = _build_migration_summary(event, {"last_event": event, "last_effective_event": {}})

    assert summary["reason"] == "Keine Änderungen nötig"
    assert summary["actions"] == []
    assert summary["errors"] == []


def test_collect_job_health_rejects_job_without_repository_assignment(tmp_path, monkeypatch):
    import config_api

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    pass_file = tmp_path / ".borg-passphrase-flash_storagebox"
    pass_file.write_text("secret\n", encoding="utf-8")
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "flash_storagebox.json").write_text(
        json.dumps({
            "job_key": "flash_storagebox",
            "name": "Flash",
            "location": "storagebox",
            "storage_profile_key": "storage-1",
            "repo": {"default": "ssh://u123@u123.your-storagebox.de:23./backup/borg-backup-flash"},
            "paths": {"default": str(source_dir)},
            "encryption": "repokey-blake2",
            "passphrase": {"default": str(pass_file), "mode": "existing_file"},
        }) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_api, "read_settings_payload", lambda _cfg: {
        "storage_profiles": [{
            "key": "storage-1",
            "name": "Storagebox",
            "host": "u123.your-storagebox.de",
            "port": "23",
            "user": "u123",
            "base_path": "./backup",
            "target_type": "storagebox",
        }]
    })

    health = _collect_job_health({"BACKUP_SCRIPTS_DIR": str(tmp_path)}, jobs_dir)

    assert health["summary"]["failed"] == 1
    assert "awaits repository migration" in " ".join(health["items"][0]["errors"])
    assert [row["code"] for row in health["items"][0]["error_details"]] == [
        "repository_context_invalid",
    ]


def test_system_health_surfaces_corrupt_canonical_inventory(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "jobs").mkdir()
    (tmp_path / "secrets").mkdir()
    (config_dir / "repositories.json").write_text("{broken", encoding="utf-8")
    (config_dir / "storages.json").write_text('{"schema_version":1,"storages":[]}', encoding="utf-8")

    health = get_system_health_data({"BACKUP_SCRIPTS_DIR": str(tmp_path)})

    assert health["checks"]["canonical_inventories_ok"] is False
    assert health["canonical_inventories"]["errors"][0]["inventory"] == "repositories"
    assert "malformed JSON" in health["canonical_inventories"]["errors"][0]["error"]


def test_cifs_probe_uses_local_capabilities_without_external_process(monkeypatch) -> None:
    monkeypatch.setattr("system_health_api.shutil.which", lambda name: "/sbin/mount.cifs" if name == "mount.cifs" else None)

    supported, state = _probe_cifs_support()

    assert supported is True
    assert state in {"loaded", "available"}


def test_collect_job_health_loads_canonical_inventory_once_for_all_jobs(tmp_path, monkeypatch) -> None:
    import repository_context

    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for job_key in ("flash_local", "appdata_local", "photos_local"):
        (jobs_dir / f"{job_key}.json").write_text(
            json.dumps({
                "schema_version": 2,
                "job_key": job_key,
                "name": job_key,
                "location": "local",
                "repository_key": f"repo_{job_key}",
                "paths": {"default": str(source_dir)},
            }) + "\n",
            encoding="utf-8",
        )

    loads = []
    inventory = {"repositories": {}, "storages": {}}
    monkeypatch.setattr(repository_context, "load_repository_inventory", lambda _config: loads.append(True) or inventory)
    monkeypatch.setattr(
        repository_context,
        "resolve_job_repository_context",
        lambda _config, _job_key, *, job, inventory: {"location": job["location"]},
    )

    health = _collect_job_health({"BACKUP_SCRIPTS_DIR": str(tmp_path)}, jobs_dir)

    assert health["summary"] == {"total": 3, "ok": 3, "failed": 0, "warnings": 0}
    assert loads == [True]
