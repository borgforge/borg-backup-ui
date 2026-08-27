from pathlib import Path
from datetime import datetime, timedelta, timezone
import inspect
import json
import os
import pytest
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import config_api  # noqa: E402
import repositories_api  # noqa: E402
import smb_profiles_api  # noqa: E402
from config_api import get_repositories_data  # noqa: E402
from repositories_api import browse_repository_directories, create_or_import_repository, export_repository_key, get_repository_archives, import_repository_key, read_repository_store, refresh_due_repository_info, refresh_repository_info, repository_key_for, write_repository_store  # noqa: E402
from restore_tests_api import list_restore_test_plan  # noqa: E402
from storage_objects_api import read_storage_store, storage_key_for, write_storage_store  # noqa: E402
from wizard_api import save_job  # noqa: E402


def _write_job(
    root: Path,
    job_key: str,
    repo_path: str,
    *,
    location: str = "local",
    profile_key: str = "",
    encryption: str = "repokey-blake2",
) -> Path:
    jobs_dir = root / "config" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    config = {"BACKUP_SCRIPTS_DIR": str(root)}
    secret = root / "secrets" / f".borg-passphrase-{job_key}"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("secret\n", encoding="utf-8")
    repo_name = Path(repo_path).name
    base_path = str(Path(repo_path).parent)
    storage_key = storage_key_for(location, f"{location}:{base_path}")
    repo_key = repository_key_for(f"repo_{job_key}", repo_path)
    write_storage_store(config, {"storages": [{
        "storage_key": storage_key,
        "display_name": "Local" if location == "local" else location,
        "storage_type": location,
        "location": location,
        "identity": f"{location}:{base_path}",
        "profile_key": profile_key,
        "base_path": base_path,
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": repo_key,
        "display_name": "Appdata",
        "repository_name": repo_name,
        "job_name": "Appdata",
        "backup_type": "appdata",
        "location": location,
        "storage_type": location,
        "storage_key": storage_key,
        "storage_name": "Local" if location == "local" else location,
        "relative_path": repo_name,
        "encryption": encryption,
        "passphrase_ref": str(secret),
        "used_by": [job_key],
    }]})
    job = {
        "schema_version": 3,
        "job_key": job_key,
        "name": "Appdata",
        "backup_type": "appdata",
        "location": location,
        "repository_key": repo_key,
        "source_paths": ["/mnt/user/appdata"],
    }
    path = jobs_dir / f"{job_key}.json"
    path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_storage_data_prefers_repository_objects(tmp_path: Path):
    _write_job(tmp_path, "appdata_local", "/mnt/backup/borg-backup-appdata")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    data = get_repositories_data(config)
    rows = data["groups"]["local"]
    expected_key = repository_key_for("repo_appdata_local", "/mnt/backup/borg-backup-appdata")

    assert rows[0]["repository_key"] == expected_key
    assert rows[0]["display_name"] == "Appdata"
    assert rows[0]["repository_name"] == "borg-backup-appdata"
    assert rows[0]["job_name"] == "Appdata"
    assert rows[0]["storage_key"].startswith("storage_local_")
    assert rows[0]["used_by"] == ["appdata_local"]
    assert rows[0]["path_raw"] == "/mnt/backup/borg-backup-appdata"
    assert rows[0]["path_display"] == "/mnt/backup/borg-backup-appdata"
    assert data["storages"][0]["storage_key"] == rows[0]["storage_key"]
    assert data["repository_info_refresh"]["enabled"] is False


def test_storage_data_derives_remote_repository_path_from_storage(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_storagebox_test",
        "display_name": "Offsite",
        "storage_type": "ssh",
        "location": "storagebox",
        "identity": "storagebox-profile:storage-1",
        "profile_key": "storage-1",
        "host": "backup.example.test",
        "port": "23",
        "user": "backup-user",
        "base_path": "./backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_appdata_storagebox_test",
        "display_name": "Appdata Offsite",
        "backup_type": "appdata",
        "location": "storagebox",
        "storage_type": "ssh",
        "storage_key": "storage_storagebox_test",
        "relative_path": "borg-backup-appdata",
        "repository_name": "borg-backup-appdata",
        "job_name": "Appdata",
        "encryption": "repokey-blake2",
        "used_by": ["appdata_storagebox"],
    }]})

    data = get_repositories_data(config)
    row = data["groups"]["storagebox"][0]

    expected = "ssh://backup-user@backup.example.test:23/./backup/borg-backup-appdata"
    assert row["path_raw"] == expected
    assert row["path_display"] == expected
    assert row["storage_name"] == "Offsite"
    persisted = read_repository_store(config)["repositories"][0]
    assert "path_raw" not in persisted
    assert "path_display" not in persisted


def test_wizard_save_uses_selected_repository_object(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    scripts = tmp_path / "scripts"
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    monkeypatch.setattr(repositories_api, "_borg_info", lambda *_args: {
        "repository": {"id": "photos-repo"},
        "encryption": {"mode": "none"},
        "cache": {"stats": {}},
    })
    created = create_or_import_repository(config, {
        "action": "import",
        "storage_key": "storage_local_test",
        "display_name": "Photos",
        "repository_name": "borg-backup-photos",
        "relative_path": "borg-backup-photos",
        "encryption": "none",
    })
    repo_key = created["repository"]["repository_key"]
    params = {
        "type_id": "photos",
        "job_name": "Photos",
        "source_paths": [str(source)],
        "repository_key": repo_key,
        "location": "local",
    }

    result = save_job(params, scripts, tmp_path, config)
    job = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))
    store = read_repository_store(config)
    assert job["repository_key"] == repo_key
    assert job["schema_version"] == 3
    assert job["source_paths"] == [str(source)]
    assert "repo" not in job
    assert "passphrase" not in job
    assert "encryption" not in job
    assert "create_repo_if_missing" not in job
    assert store["repositories"][0]["repository_key"] == repo_key
    assert store["repositories"][0]["repository_name"] == "borg-backup-photos"
    assert store["repositories"][0]["job_name"] == "Photos"
    assert store["repositories"][0]["storage_key"].startswith("storage_local_")
    assert store["repositories"][0]["relative_path"] == "borg-backup-photos"
    assert store["repositories"][0]["used_by"] == ["photos_local"]
    assert read_storage_store(config)["storages"][0]["base_path"] == "/mnt/backup"

    job["restore_test_policy"] = {
        "mode": "scheduled",
        "interval_days": 30,
        "validity_days": 30,
        "level": 3,
    }
    Path(result["metadata_path"]).write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    save_job({**params, "existing_job_key": "photos_local"}, scripts, tmp_path, config)
    updated_job = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))
    assert updated_job["restore_test_policy"] == job["restore_test_policy"]


def test_restore_test_plan_loads_repository_inventory_once(tmp_path: Path, monkeypatch):
    job_file = _write_job(tmp_path, "appdata_local", "/mnt/backup/borg-backup-appdata")
    config = {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "STATUS_DIR": str(tmp_path / "status"),
        "RESTORE_TEST_STATUS_DIR": str(tmp_path / "restore-status"),
        "RUNTIME_RUNS_DIR": str(tmp_path / "runtime-runs"),
    }
    job = json.loads(job_file.read_text(encoding="utf-8"))
    job["restore_test_policy"] = {"mode": "scheduled", "interval_days": 30, "level": 3}
    job_file.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")

    original_repo_read = repositories_api.read_repository_store
    original_storage_read = read_storage_store
    reads = {"repositories": 0, "storages": 0}

    def counted_repo_read(cfg):
        reads["repositories"] += 1
        return original_repo_read(cfg)

    def counted_storage_read(cfg):
        reads["storages"] += 1
        return original_storage_read(cfg)

    monkeypatch.setattr(repositories_api, "read_repository_store", counted_repo_read)
    monkeypatch.setattr("storage_objects_api.read_storage_store", counted_storage_read)

    plan = list_restore_test_plan(config)

    assert plan["jobs"][0]["policy"]["level"] == 3
    assert reads == {"repositories": 1, "storages": 1}


def test_repository_manager_import_uses_profile_storage_key(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    storage_key = storage_key_for("usb", "usb-profile:usb-5tb")
    write_storage_store(config, {"storages": [{
        "storage_key": storage_key,
        "display_name": "USB-5TB",
        "storage_type": "usb",
        "location": "usb",
        "identity": "usb-profile:usb-5tb",
        "profile_key": "usb-5tb",
        "base_path": "/mnt/disks/USB5TB",
        "mount_path": "/mnt/disks/USB5TB",
        "source": "usb_profile",
    }]})
    storage = read_storage_store(config)["storages"][0]
    monkeypatch.setattr(repositories_api, "_borg_info", lambda *_args: {
        "repository": {"id": "usb-photos"},
        "encryption": {"mode": "none"},
        "cache": {"stats": {}},
    })
    create_or_import_repository(config, {
        "action": "import",
        "storage_key": storage["storage_key"],
        "display_name": "Photos",
        "repository_name": "borg-backup-photos",
        "relative_path": "borg-backup-photos",
        "encryption": "none",
    })
    repo = read_repository_store(config)["repositories"][0]

    assert repo["storage_key"] == storage["storage_key"]
    assert repo["storage_key"].startswith("storage_usb_")
    assert repo["storage_name"] == "USB-5TB"
    assert storage["display_name"] == "USB-5TB"
    assert storage["profile_key"] == "usb-5tb"
    assert storage["base_path"] == "/mnt/disks/USB5TB"
    assert "usb_profile_key" not in repo
    assert repo["relative_path"] == "borg-backup-photos"


def test_repository_info_counts_archives_from_borg_list(tmp_path: Path, monkeypatch):
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
        "repository_key": "repo_flash",
        "display_name": "Flash",
        "repository_name": "borg-backup-flash",
        "storage_key": "storage_local_test",
        "location": "local",
        "relative_path": "borg-backup-flash",
        "encryption": "none",
    }]})
    calls = []

    def fake_info(_config, _storage, _repo_path, _passphrase_file, encryption=""):
        calls.append(("info", encryption))
        return {
        "repository": {"id": "flash-repo"},
        "encryption": {"mode": "repokey-blake2"},
        "cache": {"stats": {"total_size": 100, "total_csize": 90, "unique_csize": 10}},
        }

    def fake_list(_config, _storage, _repo_path, _passphrase_file, encryption=""):
        calls.append(("list", encryption))
        return {"archives": [{"name": f"flash-{index}"} for index in range(17)]}

    monkeypatch.setattr(repositories_api, "_borg_info", fake_info)
    monkeypatch.setattr(repositories_api, "_borg_list", fake_list)

    result = refresh_repository_info(config, "repo_flash")

    assert calls == [("info", "none"), ("list", "none")]
    assert result["repository"]["repository_stats"]["archives_count"] == 17
    stored = read_repository_store(config)["repositories"][0]
    assert stored["repository_stats"]["archives_count"] == 17
    assert stored["last_info_refresh_status"] == "success"
    assert stored["last_info_refresh_at"]


def test_due_repository_info_uses_24_hour_cache(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_flash",
        "display_name": "Flash",
        "storage_key": "storage_local_test",
        "relative_path": "borg-backup-flash",
    }]})
    monkeypatch.setattr(repositories_api, "_borg_info", lambda *_args: {
        "repository": {"id": "flash-repo"},
        "encryption": {"mode": "repokey-blake2"},
        "cache": {"stats": {"total_size": 100}},
    })
    monkeypatch.setattr(repositories_api, "_borg_list", lambda *_args: {"archives": []})
    now = datetime.now(timezone.utc)

    first = refresh_due_repository_info(config, now=now)
    second = refresh_due_repository_info(config, now=now + timedelta(hours=23))
    third = refresh_due_repository_info(config, now=now + timedelta(hours=25))

    assert first["refreshed"] == 1
    assert second["due"] == 0
    assert third["refreshed"] == 1


def test_failed_repository_info_refresh_is_masked_and_retried_hourly(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_flash",
        "display_name": "Flash",
        "storage_key": "storage_local_test",
        "relative_path": "borg-backup-flash",
    }]})
    monkeypatch.setattr(
        repositories_api,
        "_borg_info",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("password=hunter2 network unavailable")),
    )
    now = datetime.now(timezone.utc)

    first = refresh_due_repository_info(config, now=now)
    second = refresh_due_repository_info(config, now=now + timedelta(minutes=30))
    third = refresh_due_repository_info(config, now=now + timedelta(hours=2))

    stored = read_repository_store(config)["repositories"][0]
    assert first["failed"] == 1
    assert second["due"] == 0
    assert third["failed"] == 1
    assert stored["last_info_refresh_status"] == "error"
    assert "hunter2" not in stored["last_info_refresh_error"]
    assert "password=***" in stored["last_info_refresh_error"]


def test_repository_info_refresh_is_deferred_while_backup_uses_repository(tmp_path: Path, monkeypatch):
    config = {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "BORG_RESOURCE_LOCK_DIR": str(tmp_path / "locks"),
    }
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_appdata",
        "display_name": "Appdata",
        "storage_key": "storage_local_test",
        "relative_path": "borg-backup-appdata",
        "repository_stats": {"total_size": 100},
        "last_info_refresh_status": "error",
        "last_info_refresh_at": datetime.now(timezone.utc).isoformat(),
        "last_info_refresh_error": "Failed to create/acquire the lock",
    }]})
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    (lock_dir / "repo.lock.json").write_text(json.dumps({
        "resource": "repo:/mnt/backup/borg-backup-appdata",
        "job_key": "appdata_local",
        "pid": os.getpid(),
        "started_at": "2026-07-10T09:00:00+00:00",
    }), encoding="utf-8")
    monkeypatch.setattr(
        repositories_api,
        "_borg_info",
        lambda *_args: (_ for _ in ()).throw(AssertionError("borg info must not run")),
    )

    result = refresh_due_repository_info(config)

    stored = read_repository_store(config)["repositories"][0]
    assert result["deferred"] == 1
    assert result["failed"] == 0
    assert stored["last_info_refresh_status"] == "busy"
    assert "in use" in stored["last_info_refresh_error"]


def test_repository_archives_are_loaded_by_repository_key(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_flash",
        "display_name": "Flash",
        "storage_key": "storage_local_test",
        "relative_path": "borg-backup-flash",
        "encryption": "none",
    }]})
    captured = {}

    def fake_list(_config, _storage, _repo_path, _passphrase_file, encryption=""):
        captured["encryption"] = encryption
        return {"archives": [
            {"name": "flash-1", "id": "one", "start": "2026-07-09T09:00:00", "duration": 2.0},
            {"name": "flash-2", "id": "two", "start": "2026-07-10T09:00:00", "duration": 2.5},
        ]}

    monkeypatch.setattr(repositories_api, "_borg_list", fake_list)

    result = get_repository_archives(config, "repo_flash", 1)

    assert captured["encryption"] == "none"
    assert result["archive_count"] == 2
    assert result["archives"] == [{
        "name": "flash-2",
        "id": "two",
        "start": "2026-07-10T09:00:00",
        "end": "",
        "duration": 2.5,
    }]


def test_repository_archives_unmounts_smb_only_when_api_mounted_it(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_smb_test",
        "display_name": "NAS",
        "storage_type": "smb",
        "location": "smb",
        "profile_key": "smb-1",
        "mount_path": "/mnt/borg-backup-ui/smb/smb-1",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_smb_test",
        "display_name": "SMB Test",
        "storage_key": "storage_smb_test",
        "location": "smb",
        "relative_path": "borg-test",
    }]})
    calls = []

    def fake_action(_config, profile_key, action):
        calls.append((profile_key, action))
        return {
            "ok": True,
            "message_code": "smb_mount_success" if action == "mount" else "smb_unmount_success",
        }

    monkeypatch.setattr(smb_profiles_api, "run_smb_profile_action", fake_action)
    monkeypatch.setattr(repositories_api, "_borg_list", lambda *_args: {"archives": []})

    result = get_repository_archives(config, "repo_smb_test")

    assert result["archive_count"] == 0
    assert calls == [("smb-1", "mount"), ("smb-1", "unmount")]


def test_repository_info_keeps_smb_mounted_when_profile_requests_keep(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_smb_test",
        "display_name": "NAS",
        "storage_type": "smb",
        "location": "smb",
        "profile_key": "smb-1",
        "mount_path": "/mnt/borg-backup-ui/smb/smb-1",
        "base_path": "/mnt/borg-backup-ui/smb/smb-1",
        "keep_mounted": True,
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_smb_test",
        "display_name": "SMB Test",
        "storage_key": "storage_smb_test",
        "location": "smb",
        "relative_path": "borg-test",
        "encryption": "none",
    }]})
    calls = []

    def fake_action(_config, profile_key, action):
        calls.append((profile_key, action))
        return {"ok": True, "message_code": "smb_mount_success"}

    monkeypatch.setattr(smb_profiles_api, "run_smb_profile_action", fake_action)
    monkeypatch.setattr(repositories_api, "_borg_info", lambda *_args: {
        "repository": {"id": "smb-test"},
        "encryption": {"mode": "none"},
        "cache": {"stats": {"total_size": 10}},
    })
    monkeypatch.setattr(repositories_api, "_borg_list", lambda *_args: {"archives": []})
    monkeypatch.setattr("jobs_api.is_resource_active", lambda *_args: False)

    result = refresh_repository_info(config, "repo_smb_test")

    assert result["ok"] is True
    assert calls == [("smb-1", "mount")]


def _write_key_recovery_repository(tmp_path: Path, repository_id: str) -> tuple[dict, Path, Path]:
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    base = tmp_path / "backup"
    repository_path = base / "appdata"
    repository_path.mkdir(parents=True)
    secret = tmp_path / "secrets" / ".borg-passphrase-repo_appdata"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("secret\n", encoding="utf-8")
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": f"local:{base}",
        "base_path": str(base),
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_appdata",
        "display_name": "Appdata",
        "storage_key": "storage_local_test",
        "storage_name": "Local",
        "location": "local",
        "relative_path": "appdata",
        "passphrase_ref": str(secret),
        "encryption": "repokey-blake2",
        "borg_repository_id": repository_id,
    }]})
    return config, repository_path, secret


def test_repository_key_export_returns_download_and_tracks_state(tmp_path: Path, monkeypatch):
    repository_id = "a" * 64
    config, repository_path, _secret = _write_key_recovery_repository(tmp_path, repository_id)
    key_data = f"BORG_KEY {repository_id}\nexample-key-data\n"
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        assert cmd[:3] == ["borg", "key", "export"]
        assert cmd[3] == str(repository_path)
        Path(cmd[4]).write_text(key_data, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(repositories_api.subprocess, "run", fake_run)
    monkeypatch.setattr("jobs_api.is_resource_active", lambda *_args: False)

    result = export_repository_key(config, "repo_appdata")
    repository = read_repository_store(config)["repositories"][0]

    assert result["ok"] is True
    assert result["repository_id"] == repository_id
    assert result["key_data"] == key_data
    assert result["filename"].startswith("borg-key-appdata-aaaaaaaaaaaa-")
    assert repository["borg_key_exported_at"]
    assert repository["borg_key_repository_id"] == repository_id
    assert calls[0][:4] == ["borg", "key", "export", str(repository_path)]
    assert not list((tmp_path / "config").glob(".key-recovery-export-*"))


def test_repository_key_import_rejects_mismatched_repository_id_before_borg(tmp_path: Path, monkeypatch):
    config, _repository_path, _secret = _write_key_recovery_repository(tmp_path, "a" * 64)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("borg must not be called for a mismatched key")

    monkeypatch.setattr(repositories_api.subprocess, "run", fail_run)

    with pytest.raises(ValueError, match="different repository ID"):
        import_repository_key(config, "repo_appdata", f"BORG_KEY {'b' * 64}\nexample-key-data\n")


def test_repository_key_import_runs_borg_and_verifies_repository_id(tmp_path: Path, monkeypatch):
    repository_id = "c" * 64
    config, repository_path, _secret = _write_key_recovery_repository(tmp_path, repository_id)
    key_data = f"BORG_KEY {repository_id}\nexample-key-data\n"
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd[:4])
        if cmd[:3] == ["borg", "key", "import"]:
            assert cmd[3] == str(repository_path)
            assert Path(cmd[4]).read_text(encoding="utf-8").startswith(f"BORG_KEY {repository_id}")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["borg", "info", "--json"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps({
                    "repository": {"id": repository_id, "last_modified": "2026-08-06T10:00:00.000000"},
                    "encryption": {"mode": "repokey-blake2"},
                }),
                "",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(repositories_api.subprocess, "run", fake_run)
    monkeypatch.setattr("jobs_api.is_resource_active", lambda *_args: False)

    result = import_repository_key(config, "repo_appdata", key_data)
    repository = read_repository_store(config)["repositories"][0]

    assert result["ok"] is True
    assert result["repository_id"] == repository_id
    assert repository["borg_key_imported_at"]
    assert repository["borg_key_repository_id"] == repository_id
    assert repository["borg_repository_id"] == repository_id
    assert calls == [
        ["borg", "key", "import", str(repository_path)],
        ["borg", "info", "--json", str(repository_path)],
    ]
    assert not list((tmp_path / "config").glob(".key-recovery-import-*"))


def test_repository_archives_keep_smb_mounted_when_profile_requests_keep(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_smb_test",
        "display_name": "NAS",
        "storage_type": "smb",
        "location": "smb",
        "profile_key": "smb-1",
        "mount_path": "/mnt/borg-backup-ui/smb/smb-1",
        "keep_mounted": True,
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_smb_test",
        "display_name": "SMB Test",
        "storage_key": "storage_smb_test",
        "location": "smb",
        "relative_path": "borg-test",
    }]})
    calls = []

    def fake_action(_config, profile_key, action):
        calls.append((profile_key, action))
        return {"ok": True, "message_code": "smb_mount_success"}

    monkeypatch.setattr(smb_profiles_api, "run_smb_profile_action", fake_action)
    monkeypatch.setattr(repositories_api, "_borg_list", lambda *_args: {"archives": []})

    get_repository_archives(config, "repo_smb_test")

    assert calls == [("smb-1", "mount")]


def test_repository_browser_lists_safe_local_directories_and_managed_state(tmp_path: Path):
    base = tmp_path / "storage"
    (base / "borg-backup-appdata").mkdir(parents=True)
    (base / "team" / "photos").mkdir(parents=True)
    (base / "unsupported name").mkdir()
    (base / "plain-file").write_text("not a directory", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (base / "escape").symlink_to(outside, target_is_directory=True)
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Backup Local",
        "storage_type": "local",
        "location": "local",
        "base_path": str(base),
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_appdata_local_test",
        "display_name": "Appdata",
        "storage_key": "storage_local_test",
        "relative_path": "borg-backup-appdata",
    }]})

    root = browse_repository_directories(config, "storage_local_test")
    nested = browse_repository_directories(config, "storage_local_test", "team")

    assert root["storage_name"] == "Backup Local"
    assert root["relative_path"] == ""
    assert root["parent_path"] == ""
    assert [row["name"] for row in root["directories"]] == [
        "borg-backup-appdata",
        "team",
        "unsupported name",
    ]
    appdata = next(row for row in root["directories"] if row["name"] == "borg-backup-appdata")
    unsupported = next(row for row in root["directories"] if row["name"] == "unsupported name")
    assert appdata["managed"] is True
    assert appdata["display_name"] == "Appdata"
    assert unsupported["supported"] is False
    assert nested["relative_path"] == "team"
    assert nested["parent_path"] == ""
    assert nested["directories"][0]["relative_path"] == "team/photos"


def test_repository_browser_rejects_absolute_traversal_and_symlink_escape(tmp_path: Path):
    base = tmp_path / "storage"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (base / "escape").symlink_to(outside, target_is_directory=True)
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "base_path": str(base),
    }]})

    with pytest.raises(ValueError, match="must be relative"):
        browse_repository_directories(config, "storage_local_test", "/etc")
    with pytest.raises(ValueError, match="unsafe path segments"):
        browse_repository_directories(config, "storage_local_test", "../outside")
    with pytest.raises(ValueError, match="inside the storage target"):
        browse_repository_directories(config, "storage_local_test", "escape")


def test_repository_browser_mounts_and_unmounts_smb_only_for_its_request(tmp_path: Path, monkeypatch):
    base = tmp_path / "smb"
    (base / "borg-existing").mkdir(parents=True)
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_smb_test",
        "display_name": "NAS",
        "storage_type": "smb",
        "location": "smb",
        "profile_key": "smb-1",
        "base_path": str(base),
        "mount_path": str(base),
    }]})
    calls = []

    def fake_action(_config, profile_key, action):
        calls.append((profile_key, action))
        return {
            "ok": True,
            "message_code": "smb_mount_success" if action == "mount" else "smb_unmount_success",
        }

    monkeypatch.setattr(smb_profiles_api, "run_smb_profile_action", fake_action)

    result = browse_repository_directories(config, "storage_smb_test")

    assert result["directories"][0]["name"] == "borg-existing"
    assert calls == [("smb-1", "mount"), ("smb-1", "unmount")]


def test_repository_browser_keeps_preexisting_smb_mount(tmp_path: Path, monkeypatch):
    base = tmp_path / "smb"
    (base / "borg-existing").mkdir(parents=True)
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_smb_test",
        "display_name": "NAS",
        "storage_type": "smb",
        "location": "smb",
        "profile_key": "smb-1",
        "base_path": str(base),
    }]})
    calls = []

    def fake_action(_config, profile_key, action):
        calls.append((profile_key, action))
        return {"ok": True, "message_code": "smb_already_mounted"}

    monkeypatch.setattr(smb_profiles_api, "run_smb_profile_action", fake_action)

    browse_repository_directories(config, "storage_smb_test")

    assert calls == [("smb-1", "mount")]


def test_repository_browser_keeps_smb_mounted_when_profile_requests_keep(tmp_path: Path, monkeypatch):
    base = tmp_path / "smb"
    (base / "borg-existing").mkdir(parents=True)
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_smb_test",
        "display_name": "NAS",
        "storage_type": "smb",
        "location": "smb",
        "profile_key": "smb-1",
        "base_path": str(base),
        "keep_mounted": True,
    }]})
    calls = []

    def fake_action(_config, profile_key, action):
        calls.append((profile_key, action))
        return {"ok": True, "message_code": "smb_mount_success"}

    monkeypatch.setattr(smb_profiles_api, "run_smb_profile_action", fake_action)

    browse_repository_directories(config, "storage_smb_test")

    assert calls == [("smb-1", "mount")]


def test_repository_browser_lists_storagebox_directories_with_quoted_path(tmp_path: Path, monkeypatch):
    import storagebox_api

    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_storagebox_test",
        "display_name": "Offsite",
        "storage_type": "storagebox",
        "location": "storagebox",
        "base_path": "./backup",
        "host": "box.example.test",
        "port": "23",
        "user": "u123",
        "ssh_key_path": "/root/.ssh/id_test",
    }]})
    calls = []

    class Result:
        returncode = 0
        stdout = "borg-one/\nplain-file\nchild two/\n"
        stderr = ""

    monkeypatch.setattr(storagebox_api, "_storagebox_ssh_base_cmd", lambda profile: ["ssh", profile["host"]])

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Result()

    monkeypatch.setattr(repositories_api.subprocess, "run", fake_run)

    result = browse_repository_directories(config, "storage_storagebox_test", "team data")

    assert calls[0][0] == ["ssh", "box.example.test", "ls -1Ap -- './backup/team data'"]
    assert calls[0][1]["timeout"] == 15
    assert [row["name"] for row in result["directories"]] == ["borg-one", "child two"]
    assert all(row["supported"] is False for row in result["directories"])


def test_repository_browser_rejects_borg_serve_only_storage(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_storagebox_test",
        "display_name": "Borg Server",
        "storage_type": "ssh",
        "location": "storagebox",
        "base_path": "/repositories",
        "host": "borg.example.test",
        "port": "2222",
        "user": "borg",
        "ssh_mode": "borg_serve",
    }]})

    monkeypatch.setattr(
        repositories_api,
        "_list_ssh_storage_directories",
        lambda *_args: (_ for _ in ()).throw(AssertionError("SSH shell browse must not run")),
    )

    with pytest.raises(ValueError, match="Borg serve only"):
        browse_repository_directories(config, "storage_storagebox_test")


def test_repository_test_uses_repository_object_passphrase(tmp_path: Path, monkeypatch):
    secret = tmp_path / "secrets" / ".borg-passphrase-repo_test"
    secret.parent.mkdir(parents=True)
    secret.write_text("test-passphrase\n", encoding="utf-8")
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
        "repository_name": "borg-backup-test",
        "location": "local",
        "storage_type": "local",
        "storage_key": "storage_local_test",
        "relative_path": "borg-backup-test",
        "repo_path": "/mnt/backup/borg-backup-test",
        "path_raw": "/mnt/backup/borg-backup-test",
        "path_display": "/mnt/backup/borg-backup-test",
        "passphrase_ref": str(secret),
        "encryption": "repokey-blake2",
    }]})
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}
        return subprocess.CompletedProcess(cmd, 0, '{"ok":true}', "")

    monkeypatch.setattr(config_api.subprocess, "run", fake_run)

    result = config_api.test_repository(config, "repo_test")

    assert result["success"] is True
    assert captured["cmd"] == ["borg", "info", "--json", "/mnt/backup/borg-backup-test"]
    assert captured["env"]["BORG_PASSCOMMAND"].endswith(str(secret))


def test_repository_test_contract_requires_only_repository_key():
    assert list(inspect.signature(config_api.test_repository).parameters) == [
        "ui_config",
        "repository_key",
    ]
    handler = (ROOT / "borg_backup_ui.py").read_text(encoding="utf-8")
    assert 'body.get("repo_path")' not in handler
    assert 'body.get("repo_conf_key")' not in handler
    assert 'raise ValueError("repository_key is required")' in handler


def test_job_wizard_repository_choice_uses_readable_labels():
    source = (ROOT / "ui" / "js" / "pages" / "wizard.js").read_text(encoding="utf-8")
    german = json.loads((ROOT / "ui" / "i18n" / "de.json").read_text(encoding="utf-8"))
    english = json.loads((ROOT / "ui" / "i18n" / "en.json").read_text(encoding="utf-8"))

    assert "`${name} (${path})`" in source
    assert "[name, storage, repoName].filter(Boolean).join(' — ')" not in source
    assert "repositorySelectedHint" not in german["wizard"]
    assert "repositorySelectedHint" not in english["wizard"]
    assert "storageTargetSelectedHint" not in german["wizard"]
    assert "storageTargetSelectedHint" not in english["wizard"]
    assert "hintEl.hidden = true" in source
    assert "hint.hidden = !!storage" in source


def test_repository_manager_create_runs_borg_init_and_stores_secret(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    calls = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = create_or_import_repository(config, {
        "action": "create",
        "storage_key": "storage_local_test",
        "display_name": "Photos",
        "repository_name": "borg-backup-photos",
        "relative_path": "borg-backup-photos",
        "encryption": "repokey-blake2",
        "passphrase": "super-secret-passphrase",
        "append_only": True,
        "make_parent_dirs": True,
        "storage_quota": "5G",
    })

    repo = result["repository"]
    assert result["ok"] is True
    assert calls
    cmd = calls[0][0]
    assert cmd == [
        "borg",
        "init",
        "--encryption=repokey-blake2",
        "--append-only",
        "--storage-quota",
        "5G",
        "--make-parent-dirs",
        "/mnt/backup/borg-backup-photos",
    ]
    assert "shell" not in calls[0][1]
    secret = Path(repo["passphrase_ref"])
    assert secret.is_file()
    assert secret.read_text(encoding="utf-8") == "super-secret-passphrase"
    assert "super-secret-passphrase" not in result["output"]
    assert repo["initialized"] is True


def test_repository_manager_import_can_store_passphrase_without_borg_init(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_storagebox_test",
        "display_name": "Storagebox",
        "storage_type": "ssh",
        "location": "storagebox",
        "identity": "storagebox-profile:storage-1",
        "profile_key": "storage-1",
        "host": "example.test",
        "port": "23",
        "user": "u1",
        "base_path": "./backup",
        "ssh_key_path": "/root/.ssh/id_rsa",
    }]})

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, json.dumps({
            "repository": {"id": "remote-flash", "last_modified": "2026-07-09T10:00:00Z"},
            "encryption": {"mode": "repokey-blake2"},
            "cache": {"stats": {"total_size": 42}},
        }), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = create_or_import_repository(config, {
        "action": "import",
        "storage_key": "storage_storagebox_test",
        "display_name": "Flash Storagebox",
        "repository_name": "borg-backup-flash",
        "relative_path": "borg-backup-flash",
        "encryption": "repokey-blake2",
        "passphrase": "import-secret",
    })

    repo = result["repository"]
    assert calls[0][0][:3] == ["borg", "info", "--json"]
    assert all("init" not in call[0] for call in calls)
    assert repo["initialized"] is True
    assert "storage_profile_key" not in repo
    assert read_storage_store(config)["storages"][0]["profile_key"] == "storage-1"
    assert repo["path_raw"] == "ssh://u1@example.test:23/./backup/borg-backup-flash"
    assert "repo_uri" not in repo
    secret = Path(repo["passphrase_ref"])
    assert secret.is_file()
    assert secret.read_text(encoding="utf-8") == "import-secret"


def test_repository_import_failure_restores_existing_secret(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    secret = tmp_path / "secrets" / ".borg-passphrase-repo_test"
    secret.parent.mkdir(parents=True)
    secret.write_text("correct-secret", encoding="utf-8")
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
        "encryption": "repokey-blake2",
    }]})
    monkeypatch.setattr(repositories_api, "_borg_info", lambda *_args: (_ for _ in ()).throw(RuntimeError("wrong passphrase")))

    try:
        create_or_import_repository(config, {
            "action": "import",
            "storage_key": "storage_local_test",
            "display_name": "Test",
            "repository_name": "test",
            "relative_path": "test",
            "passphrase": "wrong-secret",
        })
        raise AssertionError("import should fail")
    except RuntimeError as exc:
        assert "wrong passphrase" in str(exc)

    assert secret.read_text(encoding="utf-8") == "correct-secret"
