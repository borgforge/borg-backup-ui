from pathlib import Path
import json
import shlex
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
        "schema_version": 3,
        "job_key": "appdata_local",
        "name": "Appdata",
        "backup_type": "appdata",
        "location": "local",
        "repository_key": "repo_appdata_test",
        "source_paths": ["/mnt/user/appdata"],
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
    assert json.loads(env["BACKUP_PATHS_JSON"]) == ["/mnt/user/appdata"]
    assert "BACKUP_PATHS" not in env
    assert "repo" not in metadata
    assert "passphrase" not in metadata
    assert "BORG_PASSCOMMAND" not in env
    assert wizard_runner.os.environ["BORG_PASSCOMMAND"] == f"cat {secret}"


def test_wizard_runner_keeps_ssh_identity_and_keepalive_options(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    jobs_dir = tmp_path / "config" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "appdata_storagebox.json").write_text(json.dumps({
        "schema_version": 3,
        "job_key": "appdata_storagebox",
        "name": "Appdata",
        "backup_type": "appdata",
        "location": "storagebox",
        "repository_key": "repo_appdata_storagebox",
        "source_paths": ["/mnt/user/appdata"],
        "compression": "lz4",
        "retention": {"daily": "7", "weekly": "4", "monthly": "6", "yearly": "3"},
    }) + "\n", encoding="utf-8")
    secret = tmp_path / "secrets" / ".borg-passphrase-repo_appdata_storagebox"
    secret.parent.mkdir()
    secret.write_text("secret\n", encoding="utf-8")
    key_path = tmp_path / "keys" / "storage box"
    key_path.parent.mkdir()
    key_path.write_text("private-key", encoding="utf-8")
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_ssh_test",
        "display_name": "Storagebox",
        "storage_type": "ssh",
        "location": "storagebox",
        "endpoint": "backup@example.test:23",
        "host": "example.test",
        "port": "23",
        "user": "backup",
        "base_path": "./backup",
        "ssh_key_path": str(key_path),
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_appdata_storagebox",
        "display_name": "Appdata",
        "storage_key": "storage_ssh_test",
        "relative_path": "borg-backup-appdata",
        "passphrase_ref": str(secret),
        "encryption": "repokey-blake2",
    }]})
    (tmp_path / "config" / "backup.conf").write_text(
        "GLOBAL_LOG_DIR=/mnt/user/logs\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("BORG_RSH", raising=False)

    env, _metadata = wizard_runner._load_env_from_job("appdata_storagebox", tmp_path / "scripts", tmp_path)

    tokens = shlex.split(env["BORG_RSH"])
    assert tokens[tokens.index("-i") + 1] == str(key_path)
    assert "ServerAliveInterval=30" in tokens
    assert "ServerAliveCountMax=10" in tokens
    assert "TCPKeepAlive=yes" in tokens


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
        assert "SMB_PROFILES_JSON" not in source, f"{path.name} still depends on legacy SMB profile transport"


def test_wizard_runner_mounts_smb_from_resolved_storage_object(tmp_path: Path, monkeypatch) -> None:
    mount_path = tmp_path / "smb-mount"
    secret = tmp_path / ".smb-nas.cred"
    secret.write_text("username=backup\npassword=secret\n", encoding="utf-8")
    metadata = {
        "location": "smb",
        "mount_before_run": True,
        "unmount_after_run": True,
        "_resolved_storage": {
            "storage_key": "storage_smb_nas",
            "profile_key": "smb-nas",
            "server": "nas.example.test",
            "share": "backup",
            "mount_path": str(mount_path),
            "username": "backup",
            "password_file": str(secret),
            "vers": "3.0",
        },
    }
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "findmnt":
            return type("FindmntResult", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        return Result()

    monkeypatch.setattr(wizard_runner.subprocess, "run", fake_run)

    session = wizard_runner._ensure_smb_mount({}, metadata)

    assert session.mounted_by_runner is True
    mount_command = next(command for command in calls if command[0] == "mount")
    assert mount_command[:5] == ["mount", "-t", "cifs", "//nas.example.test/backup", str(mount_path)]
    assert all("SMB_PROFILES_JSON" not in str(value) for value in mount_command)
