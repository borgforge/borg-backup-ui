import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import storage_objects_api  # noqa: E402
from check_api import CheckManager  # noqa: E402
from repositories_api import write_repository_store  # noqa: E402
from storage_objects_api import create_storage_target, read_storage_store, test_storage_target as run_storage_target_test, write_storage_store  # noqa: E402


def test_create_local_storage_target_is_stable_and_testable(tmp_path: Path, monkeypatch):
    base = tmp_path / "backup"
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    monkeypatch.setattr(storage_objects_api, "_safe_local_storage_path", lambda *_args, **_kwargs: str(base))

    first = create_storage_target(config, {
        "storage_type": "local",
        "display_name": "Local backup",
        "base_path": str(base),
    })
    second = create_storage_target(config, {
        "storage_type": "local",
        "display_name": "Duplicate",
        "base_path": str(base),
    })

    assert first["created"] is True
    assert second["created"] is False
    assert first["storage"]["storage_key"] == second["storage"]["storage_key"]
    assert base.is_dir()
    assert run_storage_target_test(config, first["storage"]["storage_key"])["ok"] is True
    assert len(read_storage_store(config)["storages"]) == 1


def test_create_usb_storage_target_updates_settings_and_inventory(tmp_path: Path, monkeypatch):
    mount = tmp_path / "usb"
    mount.mkdir()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    monkeypatch.setattr(storage_objects_api, "_safe_local_storage_path", lambda *_args, **_kwargs: str(mount))

    result = create_storage_target(config, {
        "storage_type": "usb",
        "display_name": "USB archive",
        "mount_path": str(mount),
    })

    settings = json.loads((tmp_path / "config" / "settings.json").read_text(encoding="utf-8"))
    assert result["storage"]["display_name"] == "USB archive"
    assert result["storage"]["profile_key"].startswith("usb-")
    assert settings["usb_profiles"][0]["mount_path"] == str(mount)


def test_repository_maintenance_commands_use_repository_and_job_retention(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    jobs = tmp_path / "config" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "photos_local.json").write_text(json.dumps({
        "job_key": "photos_local",
        "retention": {"daily": "7", "weekly": "4", "monthly": "6", "yearly": "3"},
    }), encoding="utf-8")
    repository = {"repository_key": "repo_photos", "used_by": ["photos_local"]}
    manager = CheckManager()

    assert manager._repository_command(config, repository, "/mnt/backup/photos", "check", "quick") == [
        "borg", "check", "--progress", "/mnt/backup/photos",
    ]
    assert manager._repository_command(config, repository, "/mnt/backup/photos", "compact", "quick") == [
        "borg", "compact", "--progress", "/mnt/backup/photos",
    ]
    assert manager._repository_command(config, repository, "/mnt/backup/photos", "prune", "quick") == [
        "borg", "prune", "--list", "--progress",
        "--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "6", "--keep-yearly", "3",
        "/mnt/backup/photos",
    ]


def test_repository_maintenance_uses_repository_secret_without_shell(tmp_path: Path, monkeypatch):
    secret = tmp_path / "secrets" / ".borg-passphrase-repo_test"
    secret.parent.mkdir(parents=True)
    secret.write_text("secret", encoding="utf-8")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_test",
        "display_name": "Test",
        "repository_name": "test",
        "storage_key": "storage_local_test",
        "location": "local",
        "path_raw": "/mnt/backup/test",
        "passphrase_ref": str(secret),
    }]})
    captured = {}

    class Process:
        stdout = None

        def wait(self):
            return 0

        returncode = 0

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("threading.Thread.start", lambda _self: None)

    ok, error = CheckManager().start_repository(config, "repo_test", "check", "quick")

    assert ok is True and error is None
    assert captured["cmd"] == ["borg", "check", "--progress", "/mnt/backup/test"]
    assert "shell" not in captured["kwargs"]
    assert captured["kwargs"]["env"]["BORG_PASSCOMMAND"].endswith(str(secret))
