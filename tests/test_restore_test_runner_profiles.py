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
    assert 'restore_test_overdue' in source


def test_restore_runner_discovers_usb_profile_repository(tmp_path, monkeypatch) -> None:
    runner = _load_restore_runner()
    script_dir = tmp_path / "runtime" / "scripts"
    config_dir = tmp_path / "runtime" / "config"
    jobs_dir = config_dir / "jobs"
    jobs_dir.mkdir(parents=True)
    script_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "SCRIPT_DIR", script_dir)

    (config_dir / "settings.json").write_text(
        json.dumps({
            "schema_version": 1,
            "usb_profiles": [
                {"key": "usb-5tb", "name": "USB-5TB", "mount_path": "/mnt/disks/WCJ54TRQ"},
            ],
            "smb_profiles": [],
            "storage_profiles": [],
        }),
        encoding="utf-8",
    )
    (jobs_dir / "testjob_usb.json").write_text(
        json.dumps({
            "enabled": True,
            "runner": "scriptless-wizard-runner",
            "job_key": "testjob_usb",
            "backup_type": "testjob",
            "location": "usb",
            "usb_profile_key": "usb-5tb",
            "repo": {"conf_key": "REPO_TESTJOB_USB", "default": ""},
            "passphrase": {"conf_key": "BORG_PASSPHRASE_FILE_TESTJOB_USB", "default": "/secret"},
        }),
        encoding="utf-8",
    )

    repos = runner.discover_repos({})

    assert repos == [{
        "job_key": "testjob_usb",
        "type": "testjob",
        "location": "usb",
        "path": "/mnt/disks/WCJ54TRQ/borg-backup-testjob",
        "passphrase_file": "/secret",
        "usb_profile_key": "usb-5tb",
        "smb_profile_key": "",
        "mount_before_run": True,
        "unmount_after_run": True,
    }]


def test_restore_runner_discovers_smb_profile_repository(tmp_path, monkeypatch) -> None:
    runner = _load_restore_runner()
    script_dir = tmp_path / "runtime" / "scripts"
    config_dir = tmp_path / "runtime" / "config"
    jobs_dir = config_dir / "jobs"
    jobs_dir.mkdir(parents=True)
    script_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "SCRIPT_DIR", script_dir)

    (config_dir / "settings.json").write_text(
        json.dumps({
            "schema_version": 1,
            "usb_profiles": [],
            "smb_profiles": [
                {"key": "nas-a", "name": "NAS A", "mount_path": "/mnt/remotes/nas-a"},
            ],
            "storage_profiles": [],
        }),
        encoding="utf-8",
    )
    (jobs_dir / "photos_smb.json").write_text(
        json.dumps({
            "enabled": True,
            "runner": "scriptless-wizard-runner",
            "job_key": "photos_smb",
            "backup_type": "photos",
            "location": "smb",
            "smb_profile_key": "nas-a",
            "repo": {"conf_key": "REPO_PHOTOS_SMB", "default": ""},
            "passphrase": {"conf_key": "BORG_PASSPHRASE_FILE_PHOTOS_SMB", "default": "/secret"},
        }),
        encoding="utf-8",
    )

    repos = runner.discover_repos({})

    assert repos[0]["path"] == "/mnt/remotes/nas-a/borg-backup-photos"
    assert repos[0]["smb_profile_key"] == "nas-a"
