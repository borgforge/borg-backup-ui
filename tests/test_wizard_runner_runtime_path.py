from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import wizard_runner  # noqa: E402
from repositories_api import write_repository_store  # noqa: E402
from storage_objects_api import write_storage_store  # noqa: E402


def test_wizard_runner_prefers_plugin_runtime_before_data_root(tmp_path: Path):
    plugin_runtime = wizard_runner.ROOT_DIR / "runtime"
    data_root = tmp_path / "borg-backup"
    data_root.mkdir()

    original = list(sys.path)
    try:
        for path in (str(plugin_runtime), str(data_root)):
            while path in sys.path:
                sys.path.remove(path)

        wizard_runner._ensure_runtime_import_paths(data_root)

        assert sys.path.index(str(plugin_runtime)) < sys.path.index(str(data_root))
    finally:
        sys.path[:] = original


def test_wizard_runner_resolves_repository_and_secret_from_repository_object(
    tmp_path: Path,
    monkeypatch,
):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    jobs_dir = tmp_path / "config" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "appdata_local.json").write_text(json.dumps({
        "schema_version": 2,
        "job_key": "appdata_local",
        "name": "Appdata",
        "backup_type": "appdata",
        "location": "local",
        "repository_key": "repo_appdata_test",
        "paths": {"default": "/mnt/user/appdata"},
        "compression": "lz4",
        "retention": {"daily": "7", "weekly": "4", "monthly": "6", "yearly": "3"},
    }) + "\n", encoding="utf-8")
    secret = tmp_path / "secrets" / ".borg-passphrase-repo_appdata_test"
    secret.parent.mkdir()
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
        "passphrase_ref": str(secret),
        "encryption": "repokey-blake2",
    }]})
    (tmp_path / "config" / "backup.conf").write_text(
        "GLOBAL_LOG_DIR=/mnt/user/logs\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("BORG_PASSCOMMAND", raising=False)

    env, metadata = wizard_runner._load_env_from_job("appdata_local", tmp_path / "scripts", tmp_path)

    assert env["BORG_REPO"] == "/mnt/backup/borg-backup-appdata"
    assert metadata["repository_key"] == "repo_appdata_test"
    assert metadata["_resolved_repository"]["passphrase_ref"] == str(secret)
    assert "repo" not in metadata
    assert "passphrase" not in metadata
    assert "BORG_PASSCOMMAND" not in env
    assert wizard_runner.os.environ["BORG_PASSCOMMAND"] == f"cat {secret}"


def test_runtime_repository_resolution_does_not_read_legacy_job_fields():
    runtime_files = [
        ROOT / "api" / "wizard_runner.py",
        ROOT / "api" / "wizard_api.py",
        ROOT / "api" / "restore_api.py",
        ROOT / "api" / "system_health_api.py",
        ROOT / "api" / "smb_mount.py",
        ROOT / "runtime" / "scripts" / "borg_restore_test.py",
    ]
    forbidden = (
        '.get("repo")',
        ".get('repo')",
        '.get("passphrase")',
        ".get('passphrase')",
        '.get("create_repo_if_missing")',
        '.get("remote_init_confirmed")',
    )

    for path in runtime_files:
        source = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, f"{path.name} still reads legacy job metadata: {marker}"
