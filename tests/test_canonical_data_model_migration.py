from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from migrations import canonical_data_model_v1, job_source_paths_v1  # noqa: E402
from migrations.registry import run_startup_migrations  # noqa: E402
from repositories_api import read_repository_store, repository_key_for, write_repository_store  # noqa: E402
from storage_objects_api import read_storage_store, write_storage_store  # noqa: E402


def _config(root: Path) -> dict:
    return {"BACKUP_SCRIPTS_DIR": str(root)}


def _write_legacy_job(root: Path, job_key: str = "appdata_local") -> Path:
    jobs = root / "config" / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    secret = root / "secrets" / f".borg-passphrase-{job_key}"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("test-secret\n", encoding="utf-8")
    path = jobs / f"{job_key}.json"
    path.write_text(json.dumps({
        "job_key": job_key,
        "name": "Appdata",
        "backup_type": "appdata",
        "location": "local",
        "repo": {
            "conf_key": "REPO_APPDATA_LOCAL",
            "default": "/mnt/backup/borg-backup-appdata",
        },
        "passphrase": {
            "conf_key": "BORG_PASSPHRASE_FILE_APPDATA_LOCAL",
            "default": str(secret),
        },
        "paths": {"default": "/mnt/user/appdata"},
        "encryption": "repokey-blake2",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_legacy_target_job(
    root: Path,
    *,
    job_key: str,
    location: str,
    repo_path: str,
    profile_key: str = "",
) -> Path:
    path = _write_legacy_job(root, job_key)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update({
        "job_key": job_key,
        "name": job_key.replace("_", " ").title(),
        "location": location,
        "usb_profile_key": profile_key if location == "usb" else "",
        "smb_profile_key": profile_key if location == "smb" else "",
        "storage_profile_key": profile_key if location == "storagebox" else "",
        "restore_test_policy": {"mode": "scheduled", "interval_days": 30, "level": 3},
    })
    payload["repo"]["default"] = repo_path
    payload["repo"]["conf_key"] = f"REPO_{job_key.upper()}"
    payload["passphrase"]["conf_key"] = f"BORG_PASSPHRASE_FILE_{job_key.upper()}"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_canonical_model(root: Path, *, settings: bool = False) -> tuple[str, str]:
    config = _config(root)
    storage_key = "storage_local_preserved"
    repository_key = "repo_appdata_preserved"
    passphrase = root / "secrets" / ".borg-passphrase-appdata"
    passphrase.parent.mkdir(parents=True, exist_ok=True)
    passphrase.write_text("test-secret\n", encoding="utf-8")
    write_storage_store(config, {"storages": [{
        "storage_key": storage_key,
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": repository_key,
        "display_name": "Appdata",
        "repository_name": "borg-backup-appdata",
        "job_name": "Appdata",
        "storage_key": storage_key,
        "storage_name": "Local",
        "storage_type": "local",
        "location": "local",
        "relative_path": "borg-backup-appdata",
        "encryption": "repokey-blake2",
        "passphrase_ref": str(passphrase),
        "used_by": ["appdata_local"],
        "source_job_keys": ["appdata_local"],
    }]})
    jobs = root / "config" / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    (jobs / "appdata_local.json").write_text(json.dumps({
        "schema_version": 2,
        "job_key": "appdata_local",
        "name": "Appdata",
        "backup_type": "appdata",
        "location": "local",
        "repository_key": repository_key,
        "paths": {"default": "/mnt/user/appdata"},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if settings:
        (root / "config" / "settings.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
    return storage_key, repository_key


def _events(root: Path) -> list[dict]:
    path = root / "config" / "migrations.log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_stable_legacy_install_is_migrated_and_audited(tmp_path: Path):
    job_file = _write_legacy_job(tmp_path)
    settings = tmp_path / "config" / "settings.json"
    settings.write_text(json.dumps({"schema_version": 1, "usb_profiles": [], "smb_profiles": [], "storage_profiles": []}), encoding="utf-8")
    conf = tmp_path / "config" / "backup.conf"
    conf.write_text(
        'REPO_APPDATA_LOCAL="/mnt/backup/borg-backup-appdata"\n'
        f'BORG_PASSPHRASE_FILE_APPDATA_LOCAL="{tmp_path}/secrets/.borg-passphrase-appdata_local"\n',
        encoding="utf-8",
    )

    first = run_startup_migrations(_config(tmp_path))
    second = run_startup_migrations(_config(tmp_path))

    assert first["results"][canonical_data_model_v1.MIGRATION_ID]["status"] == "applied"
    assert first["results"][job_source_paths_v1.MIGRATION_ID]["status"] == "applied"
    assert second["results"][canonical_data_model_v1.MIGRATION_ID]["status"] == "skipped"
    assert second["results"][job_source_paths_v1.MIGRATION_ID]["status"] == "skipped"
    assert not settings.exists()
    migrated_job = json.loads(job_file.read_text(encoding="utf-8"))
    assert migrated_job["schema_version"] == 3
    assert migrated_job["source_paths"] == ["/mnt/user/appdata"]
    assert "paths" not in migrated_job
    assert "repo" not in migrated_job
    assert "REPO_APPDATA_LOCAL" not in conf.read_text(encoding="utf-8")
    assert len(read_storage_store(_config(tmp_path))["storages"]) == 1
    assert len(read_repository_store(_config(tmp_path))["repositories"]) == 1
    state = json.loads((tmp_path / "config" / "migration-state.json").read_text(encoding="utf-8"))
    entry = state["migrations"][canonical_data_model_v1.MIGRATION_ID]
    assert entry["state"] == "applied"
    assert entry["details"]["source_classification"] == "stable_legacy_install"
    events = _events(tmp_path)
    assert any(row.get("event") == "migration_started" for row in events)
    assert any(row.get("event") == "migration_completed" for row in events)
    backup_dirs = list((tmp_path / "config" / "migration-backups").iterdir())
    assert len(backup_dirs) == 2
    assert any(path.name.startswith(f"{canonical_data_model_v1.MIGRATION_ID}-") for path in backup_dirs)
    assert any(path.name.startswith(f"{job_source_paths_v1.MIGRATION_ID}-") for path in backup_dirs)


def test_partial_test_install_preserves_canonical_ids(tmp_path: Path):
    storage_key, repository_key = _write_canonical_model(tmp_path, settings=True)
    (tmp_path / "config" / "migration-state.json").write_text(json.dumps({
        "schema_version": 2,
        "migrations": {
            "repository_objects_v1": {
                "state": "applied",
                "details": {"runner": "central_migration_registry"},
            },
        },
    }), encoding="utf-8")

    result = run_startup_migrations(_config(tmp_path))

    assert result["results"][canonical_data_model_v1.MIGRATION_ID]["status"] == "applied"
    assert result["results"][job_source_paths_v1.MIGRATION_ID]["status"] == "applied"
    assert read_storage_store(_config(tmp_path))["storages"][0]["storage_key"] == storage_key
    assert read_repository_store(_config(tmp_path))["repositories"][0]["repository_key"] == repository_key
    assert not (tmp_path / "config" / "settings.json").exists()
    details = result["results"][canonical_data_model_v1.MIGRATION_ID]["details"]
    assert details["source_classification"] == "partial_test_install"
    migrated_job = json.loads((tmp_path / "config" / "jobs" / "appdata_local.json").read_text(encoding="utf-8"))
    assert migrated_job["repository_key"] == repository_key
    assert migrated_job["schema_version"] == 3
    assert migrated_job["source_paths"] == ["/mnt/user/appdata"]


def test_published_profile_layout_migrates_all_targets_and_preserves_policy_state(tmp_path: Path):
    jobs = [
        _write_legacy_target_job(
            tmp_path,
            job_key="appdata_local",
            location="local",
            repo_path="/mnt/backup/borg-backup-appdata",
        ),
        _write_legacy_target_job(
            tmp_path,
            job_key="appdata_usb",
            location="usb",
            profile_key="usb-1",
            repo_path="/mnt/disks/USB5TB/borg-backup-appdata",
        ),
        _write_legacy_target_job(
            tmp_path,
            job_key="photos_smb",
            location="smb",
            profile_key="smb-1",
            repo_path="/mnt/remotes/NAS/borg-backup-photos",
        ),
        _write_legacy_target_job(
            tmp_path,
            job_key="appdata_storagebox",
            location="storagebox",
            profile_key="storage-1",
            repo_path="ssh://backup@example.test:23/./backup/borg-backup-appdata",
        ),
    ]
    config_dir = tmp_path / "config"
    (config_dir / "settings.json").write_text(json.dumps({
        "schema_version": 1,
        "usb_profiles": [{"key": "usb-1", "name": "USB-5TB", "mount_path": "/mnt/disks/USB5TB"}],
        "smb_profiles": [{
            "key": "smb-1",
            "name": "NAS",
            "server": "nas.example.test",
            "share": "backup",
            "mount_path": "/mnt/remotes/NAS",
            "username": "backup",
            "password_file": str(tmp_path / "secrets" / ".smb-smb-1.cred"),
        }],
        "storage_profiles": [{
            "key": "storage-1",
            "name": "Offsite",
            "host": "example.test",
            "port": "23",
            "user": "backup",
            "base_path": "./backup",
            "target_type": "storagebox",
            "ssh_key_path": "/root/.ssh/id_rsa",
        }],
    }), encoding="utf-8")
    schedules = config_dir / "schedules.json"
    schedules.write_text('{"appdata_local":{"cron":"0 9 * * *","enabled":true}}\n', encoding="utf-8")
    restore_state = config_dir / "restore-test-scheduler.json"
    restore_state.write_text('{"last_run":"2026-07-10T10:00:00Z"}\n', encoding="utf-8")
    schedules_before, restore_before = schedules.read_bytes(), restore_state.read_bytes()

    result = run_startup_migrations(_config(tmp_path))

    assert result["results"][canonical_data_model_v1.MIGRATION_ID]["status"] == "applied"
    assert result["results"][job_source_paths_v1.MIGRATION_ID]["status"] == "applied"
    storages = read_storage_store(_config(tmp_path))["storages"]
    repositories = read_repository_store(_config(tmp_path))["repositories"]
    assert {row["location"] for row in storages} == {"local", "usb", "smb", "storagebox"}
    assert len(repositories) == 4
    storage_keys = {row["storage_key"] for row in storages}
    assert all(row["storage_key"] in storage_keys for row in repositories)
    assert all(row["encryption"] == "repokey-blake2" for row in repositories)
    assert all(Path(row["passphrase_ref"]).is_file() for row in repositories)
    for path in jobs:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 3
        assert payload["source_paths"] == ["/mnt/user/appdata"]
        assert "paths" not in payload
        assert payload["restore_test_policy"] == {"mode": "scheduled", "interval_days": 30, "level": 3}
        assert payload["repository_key"] in {row["repository_key"] for row in repositories}
    assert schedules.read_bytes() == schedules_before
    assert restore_state.read_bytes() == restore_before


def test_already_canonical_install_is_not_rewritten(tmp_path: Path):
    storage_key, repository_key = _write_canonical_model(tmp_path)
    repo_before = (tmp_path / "config" / "repositories.json").read_bytes()
    storage_before = (tmp_path / "config" / "storages.json").read_bytes()

    result = run_startup_migrations(_config(tmp_path))

    assert result["results"][canonical_data_model_v1.MIGRATION_ID]["status"] == "not_required"
    assert result["results"][job_source_paths_v1.MIGRATION_ID]["status"] == "applied"
    assert (tmp_path / "config" / "repositories.json").read_bytes() == repo_before
    assert (tmp_path / "config" / "storages.json").read_bytes() == storage_before
    assert read_storage_store(_config(tmp_path))["storages"][0]["storage_key"] == storage_key
    assert read_repository_store(_config(tmp_path))["repositories"][0]["repository_key"] == repository_key


def test_failed_validation_rolls_back_all_modified_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    job_file = _write_legacy_job(tmp_path)
    settings = tmp_path / "config" / "settings.json"
    settings.write_text('{"schema_version": 1}\n', encoding="utf-8")
    job_before = job_file.read_bytes()
    settings_before = settings.read_bytes()
    monkeypatch.setattr(canonical_data_model_v1, "_validate", lambda _config: (_ for _ in ()).throw(RuntimeError("forced validation failure")))

    result = canonical_data_model_v1.apply(_config(tmp_path))

    assert result["status"] == "failed"
    assert result["details"]["rollback_status"] == "completed"
    assert job_file.read_bytes() == job_before
    assert settings.read_bytes() == settings_before
    assert not (tmp_path / "config" / "repositories.json").exists()
    assert not (tmp_path / "config" / "storages.json").exists()
    failed = [row for row in _events(tmp_path) if row.get("event") == "migration_failed"]
    assert failed[-1]["rollback_status"] == "completed"
    assert "test-secret" not in json.dumps(failed)


def test_malformed_canonical_storage_path_fails_migration_and_rolls_back(tmp_path: Path):
    _write_canonical_model(tmp_path, settings=True)
    storage_path = tmp_path / "config" / "storages.json"
    settings_path = tmp_path / "config" / "settings.json"
    payload = json.loads(storage_path.read_text(encoding="utf-8"))
    payload["storages"][0]["base_path"] = "/mnt//backup"
    storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    storage_before = storage_path.read_bytes()

    result = canonical_data_model_v1.apply(_config(tmp_path))

    assert result["status"] == "failed"
    assert result["details"]["failed_phase"] == "validation"
    assert result["details"]["rollback_status"] == "completed"
    assert "contains empty path segments" in result["details"]["error"]
    assert storage_path.read_bytes() == storage_before
    assert settings_path.exists()


def test_malformed_legacy_settings_is_audited_and_rolled_back_without_startup_crash(tmp_path: Path):
    job_file = _write_legacy_job(tmp_path)
    job_before = job_file.read_bytes()
    (tmp_path / "config" / "settings.json").write_text("{broken", encoding="utf-8")

    result = run_startup_migrations(_config(tmp_path))

    assert result["status"] == "failed"
    failure = result["results"][canonical_data_model_v1.MIGRATION_ID]
    assert failure["status"] == "failed"
    assert failure["details"]["failed_phase"] == "canonical_storage_profiles_v1"
    assert failure["details"]["error_type"] == "RuntimeError"
    assert failure["details"]["rollback_status"] == "completed"
    assert failure["details"]["run_id"]
    source_failure = result["results"][job_source_paths_v1.MIGRATION_ID]
    assert source_failure["status"] == "failed"
    assert source_failure["details"]["failed_phase"] == "detect"
    assert "canonical data-model migration" in source_failure["details"]["error"]
    assert job_file.read_bytes() == job_before
    assert (tmp_path / "config" / "settings.json").read_text(encoding="utf-8") == "{broken"
