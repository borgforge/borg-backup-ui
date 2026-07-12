from pathlib import Path
from datetime import datetime, timedelta, timezone
import inspect
import json
import os
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
from migrations.registry import run_startup_migrations  # noqa: E402
from repositories_api import create_or_import_repository, get_repository_archives, read_repository_store, refresh_due_repository_info, refresh_repository_info, repository_key_for, write_repository_store  # noqa: E402
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
    jobs_dir.mkdir(parents=True)
    secret = root / "secrets" / f".borg-passphrase-{job_key}"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("secret\n", encoding="utf-8")
    job = {
        "job_key": job_key,
        "name": "Appdata",
        "backup_type": "appdata",
        "location": location,
        "usb_profile_key": profile_key if location == "usb" else "",
        "smb_profile_key": profile_key if location == "smb" else "",
        "storage_profile_key": profile_key if location == "storagebox" else "",
        "repo": {
            "conf_key": f"REPO_APPDATA_{location.upper()}",
            "default": repo_path,
        },
        "passphrase": {
            "conf_key": f"BORG_PASSPHRASE_FILE_APPDATA_{location.upper()}",
            "default": f"{root}/secrets/.borg-passphrase-{job_key}",
        },
        "paths": {
            "conf_key": "BACKUP_PATHS_APPDATA",
            "default": "/mnt/user/appdata",
        },
        "encryption": encryption,
    }
    path = jobs_dir / f"{job_key}.json"
    path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_repository_objects_migration_links_existing_jobs(tmp_path: Path):
    job_file = _write_job(tmp_path, "appdata_local", "/mnt/backup/borg-backup-appdata")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    result = run_startup_migrations(config)
    store = read_repository_store(config)
    job = json.loads(job_file.read_text(encoding="utf-8"))
    expected_key = repository_key_for("repo_appdata_local", "/mnt/backup/borg-backup-appdata")

    assert result["results"]["canonical_data_model_v1"]["status"] == "applied"
    assert job["repository_key"] == expected_key
    assert job["schema_version"] == 2
    assert "repo" not in job
    assert "passphrase" not in job
    assert "encryption" not in job
    assert store["repositories"][0]["repository_key"] == expected_key
    assert store["repositories"][0]["repository_name"] == "borg-backup-appdata"
    assert store["repositories"][0]["job_name"] == "Appdata"
    assert store["repositories"][0]["storage_name"] == "Local"
    assert store["repositories"][0]["storage_key"].startswith("storage_local_")
    assert store["repositories"][0]["relative_path"] == "borg-backup-appdata"
    assert "path_raw" not in store["repositories"][0]
    assert store["repositories"][0]["used_by"] == ["appdata_local"]
    assert "repo_conf_key" not in store["repositories"][0]
    assert "storage_profile_key" not in store["repositories"][0]
    assert "usb_profile_key" not in store["repositories"][0]
    assert "smb_profile_key" not in store["repositories"][0]
    storages = read_storage_store(config)["storages"]
    assert len(storages) == 1
    assert storages[0]["storage_key"] == store["repositories"][0]["storage_key"]
    assert storages[0]["base_path"] == "/mnt/backup"


def test_repository_contract_cleanup_removes_transitional_fields_once(tmp_path: Path):
    from migrations import repository_contract_cleanup_v1

    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "repositories.json").write_text(json.dumps({
        "schema_version": 1,
        "repositories": [{
            "repository_key": "repo_flash_local",
            "display_name": "Flash",
            "storage_key": "storage_local_test",
            "relative_path": "borg-backup-flash",
            "path_raw": "/mnt/backup/borg-backup-flash",
            "repo_path": "/mnt/backup/borg-backup-flash",
            "repo_conf_key": "REPO_FLASH_LOCAL",
            "encryption": "none",
        }],
    }), encoding="utf-8")

    result = repository_contract_cleanup_v1.apply(config)
    second = repository_contract_cleanup_v1.apply(config)
    row = json.loads((config_dir / "repositories.json").read_text(encoding="utf-8"))["repositories"][0]

    assert result["status"] == "applied"
    assert result["details"]["removed_fields"] == 3
    assert second["status"] == "not_required"
    assert not repository_contract_cleanup_v1.LEGACY_FIELDS.intersection(row)
    assert row["storage_key"] == "storage_local_test"
    assert row["relative_path"] == "borg-backup-flash"


def test_repository_objects_migration_is_idempotent(tmp_path: Path):
    _write_job(tmp_path, "appdata_local", "/mnt/backup/borg-backup-appdata")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    first = run_startup_migrations(config)
    second = run_startup_migrations(config)

    assert first["results"]["canonical_data_model_v1"]["status"] == "applied"
    assert second["results"]["canonical_data_model_v1"]["status"] == "skipped"
    assert len(read_repository_store(config)["repositories"]) == 1
    assert len(read_storage_store(config)["storages"]) == 1


def test_storage_data_prefers_repository_objects(tmp_path: Path):
    _write_job(tmp_path, "appdata_local", "/mnt/backup/borg-backup-appdata")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    run_startup_migrations(config)

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
        "source_paths": str(source),
        "repository_key": repo_key,
        "location": "local",
    }

    result = save_job(params, scripts, tmp_path, config)
    job = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))
    store = read_repository_store(config)
    assert job["repository_key"] == repo_key
    assert job["schema_version"] == 2
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
    run_startup_migrations(config)
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


def test_repository_objects_v2_enriches_existing_repository_names(tmp_path: Path):
    job_file = _write_job(tmp_path, "appdata_local", "/mnt/backup/borg-backup-appdata")
    job = json.loads(job_file.read_text(encoding="utf-8"))
    job["repository_key"] = "repo_appdata_local"
    job_file.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    repo_file = tmp_path / "config" / "repositories.json"
    repo_file.write_text(json.dumps({
        "schema_version": 1,
        "updated_at": "2026-07-09T10:00:00Z",
        "repositories": [{
            "repository_key": "repo_appdata_local",
            "display_name": "Appdata - Local",
            "backup_type": "appdata",
            "location": "local",
            "storage_type": "local",
            "storage_key": "local",
            "repo_path": "/mnt/backup/borg-backup-appdata",
            "path_raw": "/mnt/backup/borg-backup-appdata",
            "path_display": "/mnt/backup/borg-backup-appdata",
            "source_job_keys": ["appdata_local"],
            "used_by": ["appdata_local"],
        }],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    result = run_startup_migrations(config)
    store = read_repository_store(config)
    repo = store["repositories"][0]

    assert result["results"]["canonical_data_model_v1"]["status"] == "applied"
    assert repo["display_name"] == "Appdata"
    assert repo["repository_name"] == "borg-backup-appdata"
    assert repo["job_name"] == "Appdata"
    assert repo["storage_name"] == "Local"


def test_storage_objects_v1_links_existing_repository_objects(tmp_path: Path):
    job_file = _write_job(tmp_path, "appdata_local", "/mnt/backup/borg-backup-appdata")
    job = json.loads(job_file.read_text(encoding="utf-8"))
    job["repository_key"] = "repo_appdata_local"
    job_file.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    repo_file = tmp_path / "config" / "repositories.json"
    repo_file.write_text(json.dumps({
        "schema_version": 1,
        "updated_at": "2026-07-09T10:00:00Z",
        "repositories": [{
            "repository_key": "repo_appdata_local",
            "display_name": "Appdata",
            "repository_name": "borg-backup-appdata",
            "job_name": "Appdata",
            "backup_type": "appdata",
            "location": "local",
            "storage_type": "local",
            "storage_key": "local",
            "storage_name": "Local",
            "repo_path": "/mnt/backup/borg-backup-appdata",
            "path_raw": "/mnt/backup/borg-backup-appdata",
            "path_display": "/mnt/backup/borg-backup-appdata",
            "source_job_keys": ["appdata_local"],
            "used_by": ["appdata_local"],
        }],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    result = run_startup_migrations(config)
    second = run_startup_migrations(config)
    repo = read_repository_store(config)["repositories"][0]
    storages = read_storage_store(config)["storages"]

    assert result["results"]["canonical_data_model_v1"]["status"] == "applied"
    assert second["results"]["canonical_data_model_v1"]["status"] == "skipped"
    assert len(storages) == 1
    assert storages[0]["storage_key"].startswith("storage_local_")
    assert storages[0]["display_name"] == "Local"
    assert storages[0]["base_path"] == "/mnt/backup"
    assert repo["storage_key"] == storages[0]["storage_key"]
    assert repo["relative_path"] == "borg-backup-appdata"


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
    }]})
    monkeypatch.setattr(repositories_api, "_borg_info", lambda *_args: {
        "repository": {"id": "flash-repo"},
        "encryption": {"mode": "repokey-blake2"},
        "cache": {"stats": {"total_size": 100, "total_csize": 90, "unique_csize": 10}},
    })
    monkeypatch.setattr(repositories_api, "_borg_list", lambda *_args: {
        "archives": [{"name": f"flash-{index}"} for index in range(17)],
    })

    result = refresh_repository_info(config, "repo_flash")

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
    }]})
    monkeypatch.setattr(repositories_api, "_borg_list", lambda *_args: {
        "archives": [
            {"name": "flash-1", "id": "one", "start": "2026-07-09T09:00:00", "duration": 2.0},
            {"name": "flash-2", "id": "two", "start": "2026-07-10T09:00:00", "duration": 2.5},
        ],
    })

    result = get_repository_archives(config, "repo_flash", 1)

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


def test_repository_objects_v3_migrates_legacy_repository_keys(tmp_path: Path):
    job_file = _write_job(tmp_path, "flash_local", "/mnt/backup/borg-backup-flash")
    job = json.loads(job_file.read_text(encoding="utf-8"))
    job["repository_key"] = "repo_flash_local"
    job_file.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    repo_file = tmp_path / "config" / "repositories.json"
    repo_file.write_text(json.dumps({
        "schema_version": 1,
        "updated_at": "2026-07-09T10:00:00Z",
        "repositories": [{
            "repository_key": "repo_flash_local",
            "display_name": "Flash",
            "repository_name": "borg-backup-flash",
            "job_name": "Flash",
            "backup_type": "flash",
            "location": "local",
            "storage_type": "local",
            "storage_key": "storage_local_old",
            "storage_name": "Local",
            "repo_path": "/mnt/backup/borg-backup-flash",
            "path_raw": "/mnt/backup/borg-backup-flash",
            "path_display": "/mnt/backup/borg-backup-flash",
            "source_job_keys": ["flash_local"],
            "used_by": ["flash_local"],
        }],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    result = run_startup_migrations(config)
    repo = read_repository_store(config)["repositories"][0]
    job_after = json.loads(job_file.read_text(encoding="utf-8"))
    expected_key = repository_key_for("repo_flash_local", "/mnt/backup/borg-backup-flash")

    assert result["results"]["canonical_data_model_v1"]["status"] == "applied"
    assert repo["repository_key"] == expected_key
    assert job_after["repository_key"] == expected_key


def test_repository_objects_v4_enriches_missing_encryption_from_jobs(tmp_path: Path):
    job_file = _write_job(
        tmp_path,
        "flash_local",
        "/mnt/backup/borg-backup-flash",
        encryption="repokey-blake2",
    )
    job = json.loads(job_file.read_text(encoding="utf-8"))
    job["repository_key"] = "repo_flash_local"
    job_file.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    repo_file = tmp_path / "config" / "repositories.json"
    repo_file.write_text(json.dumps({
        "schema_version": 1,
        "updated_at": "2026-07-09T10:00:00Z",
        "repositories": [{
            "repository_key": "repo_flash_local",
            "display_name": "Flash",
            "repository_name": "borg-backup-flash",
            "job_name": "Flash",
            "backup_type": "flash",
            "location": "local",
            "storage_type": "local",
            "storage_key": "storage_local_old",
            "storage_name": "Local",
            "repo_path": "/mnt/backup/borg-backup-flash",
            "path_raw": "/mnt/backup/borg-backup-flash",
            "path_display": "/mnt/backup/borg-backup-flash",
            "encryption": "",
            "source_job_keys": ["flash_local"],
            "used_by": ["flash_local"],
        }],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    result = run_startup_migrations(config)
    second = run_startup_migrations(config)
    repo = read_repository_store(config)["repositories"][0]

    assert result["results"]["canonical_data_model_v1"]["status"] == "applied"
    assert second["results"]["canonical_data_model_v1"]["status"] == "skipped"
    assert repo["encryption"] == "repokey-blake2"


def test_storage_objects_v2_enriches_storage_profile_fields(tmp_path: Path):
    from migrations import storage_objects_v2
    repo_file = tmp_path / "config" / "repositories.json"
    repo_file.parent.mkdir(parents=True, exist_ok=True)
    repo_key = repository_key_for("repo_flash_storagebox", "ssh://u1@example.test:23/./backup/borg-backup-flash")
    storage_key = storage_key_for("storagebox", "storagebox-profile:storage-1")
    repo_file.write_text(json.dumps({
        "schema_version": 1,
        "updated_at": "2026-07-09T10:00:00Z",
        "repositories": [{
            "repository_key": repo_key,
            "display_name": "Flash",
            "repository_name": "borg-backup-flash",
            "job_name": "Flash",
            "backup_type": "flash",
            "location": "storagebox",
            "storage_type": "ssh",
            "storage_key": storage_key,
            "storage_name": "storage-1",
            "storage_profile_key": "storage-1",
            "repo_uri": "ssh://u1@example.test:23/./backup/borg-backup-flash",
            "path_raw": "ssh://u1@example.test:23/./backup/borg-backup-flash",
            "path_display": "ssh://u1@example.test:23/./backup/borg-backup-flash",
            "source_job_keys": ["flash_storagebox"],
            "used_by": ["flash_storagebox"],
        }],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    settings_file = tmp_path / "config" / "settings.json"
    settings_file.write_text(json.dumps({
        "schema_version": 1,
        "usb_profiles": [],
        "smb_profiles": [],
        "storage_profiles": [{
            "key": "storage-1",
            "name": "Hetzner Storagebox",
            "host": "example.test",
            "port": "23",
            "user": "u1",
            "base_path": "./backup",
            "target_type": "storagebox",
            "ssh_key_path": "/root/.ssh/id_rsa_storagebox",
        }],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (tmp_path / "config" / "storages.json").write_text(json.dumps({
        "schema_version": 1,
        "updated_at": "2026-07-09T10:00:00Z",
        "storages": [{
            "storage_key": storage_key,
            "display_name": "Storagebox",
            "storage_type": "ssh",
            "location": "storagebox",
            "identity": "storagebox-profile:storage-1",
            "profile_key": "storage-1",
            "base_path": "./backup",
            "source": "storage_profile",
        }],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (tmp_path / "config" / "migration-state.json").write_text(json.dumps({
        "schema_version": 2,
        "migrations": {
            "storage_objects_v1": {
                "state": "applied",
                "checked_at": "2026-07-09T10:00:00",
                "source": "startup_registry",
                "details": {"runner": "central_migration_registry"},
            }
        },
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    result = storage_objects_v2.apply(config)
    storages = read_storage_store(config)["storages"]
    storage = next(row for row in storages if row["profile_key"] == "storage-1")

    assert result["status"] == "applied"
    assert storage["storage_key"].startswith("storage_storagebox_")
    assert storage["display_name"] == "Hetzner Storagebox"
    assert storage["host"] == "example.test"
    assert storage["port"] == "23"
    assert storage["user"] == "u1"
    assert storage["base_path"] == "./backup"
    assert storage["ssh_key_path"] == "/root/.ssh/id_rsa_storagebox"


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
