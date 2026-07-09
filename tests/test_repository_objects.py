from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from config_api import get_repositories_data  # noqa: E402
from migrations.registry import run_startup_migrations  # noqa: E402
from repositories_api import read_repository_store  # noqa: E402
from storage_objects_api import read_storage_store  # noqa: E402
from wizard_api import save_job  # noqa: E402


def _write_job(root: Path, job_key: str, repo_path: str, *, location: str = "local", profile_key: str = "") -> Path:
    jobs_dir = root / "config" / "jobs"
    jobs_dir.mkdir(parents=True)
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

    assert result["results"]["repository_objects_v1"]["status"] == "applied"
    assert job["repository_key"] == "repo_appdata_local"
    assert store["repositories"][0]["repository_key"] == "repo_appdata_local"
    assert store["repositories"][0]["repository_name"] == "borg-backup-appdata"
    assert store["repositories"][0]["job_name"] == "Appdata"
    assert store["repositories"][0]["storage_name"] == "Local"
    assert store["repositories"][0]["storage_key"].startswith("storage_local_")
    assert store["repositories"][0]["relative_path"] == "borg-backup-appdata"
    assert store["repositories"][0]["path_raw"] == "/mnt/backup/borg-backup-appdata"
    assert store["repositories"][0]["used_by"] == ["appdata_local"]
    storages = read_storage_store(config)["storages"]
    assert len(storages) == 1
    assert storages[0]["storage_key"] == store["repositories"][0]["storage_key"]
    assert storages[0]["base_path"] == "/mnt/backup"


def test_repository_objects_migration_is_idempotent(tmp_path: Path):
    _write_job(tmp_path, "appdata_local", "/mnt/backup/borg-backup-appdata")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    first = run_startup_migrations(config)
    second = run_startup_migrations(config)

    assert first["results"]["repository_objects_v1"]["status"] == "applied"
    assert second["results"]["repository_objects_v1"]["status"] == "skipped"
    assert len(read_repository_store(config)["repositories"]) == 1
    assert len(read_storage_store(config)["storages"]) == 1


def test_storage_data_prefers_repository_objects(tmp_path: Path):
    _write_job(tmp_path, "appdata_local", "/mnt/backup/borg-backup-appdata")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    run_startup_migrations(config)

    data = get_repositories_data(config)
    rows = data["groups"]["local"]

    assert rows[0]["repository_key"] == "repo_appdata_local"
    assert rows[0]["display_name"] == "Appdata"
    assert rows[0]["repository_name"] == "borg-backup-appdata"
    assert rows[0]["job_name"] == "Appdata"
    assert rows[0]["storage_key"].startswith("storage_local_")
    assert rows[0]["used_by"] == ["appdata_local"]
    assert data["storages"][0]["storage_key"] == rows[0]["storage_key"]


def test_wizard_save_creates_repository_object(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    scripts = tmp_path / "scripts"
    params = {
        "type_id": "photos",
        "job_name": "Photos",
        "source_paths": str(source),
        "repo_path": "/mnt/backup/borg-backup-photos",
        "location": "local",
        "encryption": "none",
    }

    result = save_job(params, scripts, tmp_path, {"BACKUP_SCRIPTS_DIR": str(tmp_path)})
    job = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))
    store = read_repository_store({"BACKUP_SCRIPTS_DIR": str(tmp_path)})

    assert job["repository_key"] == "repo_photos_local"
    assert store["repositories"][0]["repository_key"] == "repo_photos_local"
    assert store["repositories"][0]["repository_name"] == "borg-backup-photos"
    assert store["repositories"][0]["job_name"] == "Photos"
    assert store["repositories"][0]["storage_key"].startswith("storage_local_")
    assert store["repositories"][0]["relative_path"] == "borg-backup-photos"
    assert store["repositories"][0]["used_by"] == ["photos_local"]
    assert read_storage_store({"BACKUP_SCRIPTS_DIR": str(tmp_path)})["storages"][0]["base_path"] == "/mnt/backup"


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

    assert result["results"]["repository_objects_v2"]["status"] == "applied"
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

    assert result["results"]["storage_objects_v1"]["status"] == "applied"
    assert second["results"]["storage_objects_v1"]["status"] == "skipped"
    assert len(storages) == 1
    assert storages[0]["storage_key"].startswith("storage_local_")
    assert storages[0]["display_name"] == "Local"
    assert storages[0]["base_path"] == "/mnt/backup"
    assert repo["storage_key"] == storages[0]["storage_key"]
    assert repo["relative_path"] == "borg-backup-appdata"


def test_repository_objects_use_profile_storage_key_for_new_jobs(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    settings_file = tmp_path / "config" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps({
        "schema_version": 1,
        "usb_profiles": [{
            "key": "usb-5tb",
            "name": "USB-5TB",
            "mount_path": "/mnt/disks/USB5TB",
        }],
        "smb_profiles": [],
        "storage_profiles": [],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    params = {
        "type_id": "photos",
        "job_name": "Photos",
        "source_paths": str(source),
        "repo_path": "/mnt/disks/USB5TB/borg-backup-photos",
        "location": "usb",
        "usb_profile_key": "usb-5tb",
        "encryption": "none",
    }

    save_job(params, tmp_path / "scripts", tmp_path, {"BACKUP_SCRIPTS_DIR": str(tmp_path)})
    repo = read_repository_store({"BACKUP_SCRIPTS_DIR": str(tmp_path)})["repositories"][0]
    storage = read_storage_store({"BACKUP_SCRIPTS_DIR": str(tmp_path)})["storages"][0]

    assert repo["storage_key"] == storage["storage_key"]
    assert repo["storage_key"].startswith("storage_usb_")
    assert repo["storage_name"] == "USB-5TB"
    assert storage["display_name"] == "USB-5TB"
    assert storage["profile_key"] == "usb-5tb"
    assert storage["base_path"] == "/mnt/disks/USB5TB"
    assert repo["relative_path"] == "borg-backup-photos"
