import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from migrations import repository_runtime_v1
from repositories_api import read_repository_store, write_repository_store
from repository_context import resolve_job_repository_context
from storage_objects_api import write_storage_store


def _fixture(tmp_path: Path, *, secret_exists: bool = True, legacy_path: str = "/mnt/backup/borg-backup-appdata"):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    jobs_dir = tmp_path / "config" / "jobs"
    jobs_dir.mkdir(parents=True)
    secret = tmp_path / "secrets" / ".borg-passphrase-repo_appdata"
    secret.parent.mkdir(parents=True)
    if secret_exists:
        secret.write_text("secret\n", encoding="utf-8")
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_appdata_test",
        "display_name": "Appdata",
        "storage_key": "storage_local_test",
        "relative_path": "borg-backup-appdata",
        "path_raw": "/mnt/backup/borg-backup-appdata",
        "repo_conf_key": "REPO_APPDATA_LOCAL",
        "passphrase_ref": str(secret),
        "encryption": "repokey-blake2",
    }]})
    job = {
        "job_key": "appdata_local",
        "name": "Appdata",
        "backup_type": "appdata",
        "location": "local",
        "runner": "scriptless-wizard-runner",
        "repository_key": "repo_appdata_test",
        "repo": {"conf_key": "REPO_APPDATA_LOCAL", "default": legacy_path},
        "passphrase": {
            "conf_key": "BORG_PASSPHRASE_FILE_APPDATA_LOCAL",
            "default": str(secret),
            "mode": "existing_file",
        },
        "encryption": "repokey-blake2",
        "storage_key": "storage_local_test",
        "create_repo_if_missing": False,
        "paths": {"conf_key": "BACKUP_PATHS_APPDATA", "default": "/mnt/user/appdata"},
    }
    job_file = jobs_dir / "appdata_local.json"
    job_file.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    conf = tmp_path / "config" / "backup.conf"
    conf.write_text(
        f"REPO_APPDATA_LOCAL={legacy_path}\n"
        f"BORG_PASSPHRASE_FILE_APPDATA_LOCAL={secret}\n"
        "GLOBAL_LOG_DIR=/mnt/user/logs\n",
        encoding="utf-8",
    )
    return config, job_file, conf


def test_repository_runtime_migration_removes_legacy_job_and_conf_fields(tmp_path: Path):
    config, job_file, conf = _fixture(tmp_path)

    assert repository_runtime_v1.detect(config)["required"] is True
    result = repository_runtime_v1.apply(config)

    assert result["status"] == "applied"
    migrated = json.loads(job_file.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 2
    assert migrated["repository_key"] == "repo_appdata_test"
    for field in repository_runtime_v1.LEGACY_JOB_FIELDS:
        assert field not in migrated
    conf_text = conf.read_text(encoding="utf-8")
    assert "REPO_APPDATA_LOCAL" not in conf_text
    assert "BORG_PASSPHRASE_FILE_APPDATA_LOCAL" not in conf_text
    assert "GLOBAL_LOG_DIR=/mnt/user/logs" in conf_text
    context = resolve_job_repository_context(config, "appdata_local")
    assert context["repository_path"] == "/mnt/backup/borg-backup-appdata"
    assert "repo_conf_key" not in read_repository_store(config)["repositories"][0]
    assert Path(result["details"]["backup_dir"]).is_dir()

    assert repository_runtime_v1.detect(config)["required"] is False
    assert repository_runtime_v1.apply(config)["status"] == "not_required"


def test_repository_runtime_migration_keeps_job_unchanged_when_secret_is_missing(tmp_path: Path):
    config, job_file, conf = _fixture(tmp_path, secret_exists=False)
    before_job = job_file.read_text(encoding="utf-8")
    before_conf = conf.read_text(encoding="utf-8")

    result = repository_runtime_v1.apply(config)

    assert result["status"] == "failed"
    assert "passphrase file" in result["details"]["error"].lower()
    assert job_file.read_text(encoding="utf-8") == before_job
    assert conf.read_text(encoding="utf-8") == before_conf


def test_repository_runtime_migration_rejects_path_drift_without_partial_cleanup(tmp_path: Path):
    config, job_file, conf = _fixture(tmp_path, legacy_path="/mnt/other/borg-backup-appdata")
    before_job = job_file.read_text(encoding="utf-8")

    result = repository_runtime_v1.apply(config)

    assert result["status"] == "failed"
    assert "differs" in result["details"]["error"]
    assert job_file.read_text(encoding="utf-8") == before_job
    assert "REPO_APPDATA_LOCAL" in conf.read_text(encoding="utf-8")


def test_repository_runtime_migration_rejects_passphrase_drift(tmp_path: Path):
    config, job_file, conf = _fixture(tmp_path)
    before_job = job_file.read_text(encoding="utf-8")
    conf.write_text(
        conf.read_text(encoding="utf-8").replace(
            "BORG_PASSPHRASE_FILE_APPDATA_LOCAL=",
            "BORG_PASSPHRASE_FILE_APPDATA_LOCAL=/other/",
        ),
        encoding="utf-8",
    )

    result = repository_runtime_v1.apply(config)

    assert result["status"] == "failed"
    assert "passphrase reference differs" in result["details"]["error"]
    assert job_file.read_text(encoding="utf-8") == before_job


def test_productive_job_runtime_does_not_read_legacy_repository_fields() -> None:
    productive_sources = (
        ROOT / "api" / "wizard_runner.py",
        ROOT / "api" / "wizard_api.py",
        ROOT / "api" / "jobs_api.py",
        ROOT / "api" / "restore_api.py",
        ROOT / "runtime" / "scripts" / "borg_restore_test.py",
    )
    legacy_fields = (
        "repo",
        "passphrase",
        "encryption",
        "storage_key",
        "usb_profile_key",
        "smb_profile_key",
        "storage_profile_key",
        "create_repo_if_missing",
        "remote_init_confirmed",
    )
    for source_path in productive_sources:
        source = source_path.read_text(encoding="utf-8")
        for variable in ("meta", "raw", "job", "job_meta"):
            for field in legacy_fields:
                assert f'{variable}.get("{field}")' not in source, (
                    f"{source_path.relative_to(ROOT)} reads legacy job field {field}"
                )
