from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from system_health_api import _build_migration_summary, _collect_job_health, _last_migration_successful, _read_migration_state


def test_migration_summary_without_run():
    summary = _build_migration_summary({}, {"last_event": {}, "last_effective_event": {}})

    assert summary["status"] == "none"
    assert summary["state"] == "Noch kein Lauf"
    assert summary["last_run"] == ""
    assert summary["reason"] == "Noch kein Migrationslauf protokolliert"
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
        "reason_code": "storage_paths_changed",
        "message": "storage_paths=ok(changed=True,moved=2,move_errors=1)",
        "details": {
            "storage_paths": {
                "changed": True,
                "moved": 2,
                "move_errors": 1,
                "settings_changed": True,
                "forced_conf_write": True,
            },
            "jobs_layout": {"status": "error", "error": "jobs unreadable"},
        },
    }
    summary = _build_migration_summary(event, {
        "last_event": event,
        "last_effective_event": {"timestamp": "2026-06-06T23:41:00"},
    })

    assert summary["status"] == "failed"
    assert summary["state"] == "Fehlgeschlagen"
    assert summary["last_run"] == "2026-06-06T23:40:00"
    assert summary["last_effective_run"] == "2026-06-06T23:41:00"
    assert summary["reason"] == "Änderung des Cache/Remotes inkl. backup.conf-Anpassung"
    assert "2 Elemente verschoben" in summary["actions"]
    assert "Storage-Pfade aktualisiert" in summary["actions"]
    assert "Profileinstellungen angepasst" in summary["actions"]
    assert "backup.conf korrigiert" in summary["actions"]
    assert "1 Verschiebe-Fehler" in summary["errors"]
    assert "Job-Layout: jobs unreadable" in summary["errors"]


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


def test_collect_job_health_flags_broken_storagebox_repo_uri(tmp_path, monkeypatch):
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
    assert "fehlenden Slash" in " ".join(health["items"][0]["errors"])
    assert [row["code"] for row in health["items"][0]["error_details"]] == [
        "storagebox_repo_port_slash",
    ]
