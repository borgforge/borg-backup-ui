import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_restore_runner():
    path = ROOT / "runtime" / "scripts" / "borg_restore_test.py"
    spec = importlib.util.spec_from_file_location("borg_restore_test_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_due_restore_run_uses_all_locations_after_selecting_jobs() -> None:
    source = (ROOT / "borg_backup_ui.py").read_text(encoding="utf-8")

    assert 'auto_selected = True\n            location = "all"' in source
    assert 'cmd.append("--scheduled")' in source


def test_restore_runner_supports_scheduled_notifications() -> None:
    source = (ROOT / "runtime" / "scripts" / "borg_restore_test.py").read_text(encoding="utf-8")

    assert 'parser.add_argument("--scheduled"' in source
    assert 'restore_test_success' in source
    assert 'restore_test_failed' in source
    assert 'self._notify_event("restore_test_overdue"' not in source
    assert 'clear_reminder_prefix(self.conf, f"restore_test_overdue:{job_name}:")' in source


def test_restore_runner_discovers_usb_profile_repository(tmp_path, monkeypatch) -> None:
    runner = _load_restore_runner()
    script_dir = tmp_path / "runtime" / "scripts"
    config_dir = tmp_path / "runtime" / "config"
    jobs_dir = config_dir / "jobs"
    jobs_dir.mkdir(parents=True)
    script_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "SCRIPT_DIR", script_dir)
    monkeypatch.setenv("BORG_UI_DATA_ROOT", str(tmp_path / "runtime"))

    (jobs_dir / "testjob_usb.json").write_text(
        json.dumps({
            "schema_version": 2,
            "enabled": True,
            "runner": "scriptless-wizard-runner",
            "job_key": "testjob_usb",
            "backup_type": "testjob",
            "location": "usb",
            "repository_key": "repo_testjob_usb",
        }),
        encoding="utf-8",
    )
    (config_dir / "storages.json").write_text(json.dumps({
        "schema_version": 1,
        "storages": [{
            "storage_key": "storage_usb_test",
            "display_name": "USB-5TB",
            "storage_type": "usb",
            "location": "usb",
            "identity": "usb-profile:usb-5tb",
            "profile_key": "usb-5tb",
            "base_path": "/mnt/disks/WCJ54TRQ",
            "mount_path": "/mnt/disks/WCJ54TRQ",
        }],
    }), encoding="utf-8")
    (config_dir / "repositories.json").write_text(json.dumps({
        "schema_version": 1,
        "repositories": [{
            "repository_key": "repo_testjob_usb",
            "display_name": "Testjob",
            "storage_key": "storage_usb_test",
            "relative_path": "borg-backup-testjob",
            "path_raw": "/mnt/disks/WCJ54TRQ/borg-backup-testjob",
            "encryption": "none",
        }],
    }), encoding="utf-8")

    repos = runner.discover_repos({})

    assert [{key: row[key] for key in (
        "job_key", "type", "location", "path", "passphrase_file", "profile_key",
        "mount_before_run", "unmount_after_run",
    )} for row in repos] == [{
        "job_key": "testjob_usb",
        "type": "testjob",
        "location": "usb",
        "path": "/mnt/disks/WCJ54TRQ/borg-backup-testjob",
        "passphrase_file": "",
        "profile_key": "usb-5tb",
        "mount_before_run": True,
        "unmount_after_run": True,
    }]
    assert repos[0]["storage"]["storage_key"] == "storage_usb_test"


def test_restore_runner_discovers_smb_profile_repository(tmp_path, monkeypatch) -> None:
    runner = _load_restore_runner()
    script_dir = tmp_path / "runtime" / "scripts"
    config_dir = tmp_path / "runtime" / "config"
    jobs_dir = config_dir / "jobs"
    jobs_dir.mkdir(parents=True)
    script_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "SCRIPT_DIR", script_dir)
    monkeypatch.setenv("BORG_UI_DATA_ROOT", str(tmp_path / "runtime"))

    (jobs_dir / "photos_smb.json").write_text(
        json.dumps({
            "schema_version": 2,
            "enabled": True,
            "runner": "scriptless-wizard-runner",
            "job_key": "photos_smb",
            "backup_type": "photos",
            "location": "smb",
            "repository_key": "repo_photos_smb",
        }),
        encoding="utf-8",
    )
    (config_dir / "storages.json").write_text(json.dumps({
        "schema_version": 1,
        "storages": [{
            "storage_key": "storage_smb_test",
            "display_name": "NAS A",
            "storage_type": "smb",
            "location": "smb",
            "identity": "smb-profile:nas-a",
            "profile_key": "nas-a",
            "base_path": "/mnt/remotes/nas-a",
            "mount_path": "/mnt/remotes/nas-a",
        }],
    }), encoding="utf-8")
    (config_dir / "repositories.json").write_text(json.dumps({
        "schema_version": 1,
        "repositories": [{
            "repository_key": "repo_photos_smb",
            "display_name": "Photos",
            "storage_key": "storage_smb_test",
            "relative_path": "borg-backup-photos",
            "path_raw": "/mnt/remotes/nas-a/borg-backup-photos",
            "encryption": "none",
        }],
    }), encoding="utf-8")

    repos = runner.discover_repos({})

    assert repos[0]["path"] == "/mnt/remotes/nas-a/borg-backup-photos"
    assert repos[0]["profile_key"] == "nas-a"
