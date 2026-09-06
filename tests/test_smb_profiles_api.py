from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from smb_profiles_api import (
    generate_smb_mount_path,
    mount_startup_smb_profiles,
    normalize_smb_profile_rows,
    run_smb_profile_action,
    test_smb_profiles_status as check_smb_profiles_status,
    validate_smb_profile_usage_before_save,
)
from smb_protocol import build_smb_mount_options, normalize_smb_version
from repositories_api import write_repository_store
from job_model import new_job_defaults
from storage_objects_api import write_storage_store


def test_smb_profile_normalization_derives_key_from_secret_path(tmp_path: Path):
    cred = tmp_path / ".smb-nas-a.cred"
    cred.write_text("username=backup\npassword=secret\n", encoding="utf-8")

    rows = normalize_smb_profile_rows([{
        "name": "NAS A",
        "server": "192.0.2.10",
        "share": "/backup",
        "mount_path": "/mnt/user/borg-backup-ui/remotes/nas-a",
        "username": "backup",
        "password_file": str(cred),
    }])

    assert rows == [{
        "key": "nas-a",
        "name": "NAS A",
        "server": "192.0.2.10",
        "share": "backup",
        "mount_path": "/mnt/user/borg-backup-ui/remotes/nas-a",
        "username": "backup",
        "vers": "auto",
        "sec": "",
        "password_file": str(cred),
        "smb_password": "",
        "password_set": "true",
        "mount_at_start": False,
        "keep_mounted": False,
    }]


def test_smb_profile_generates_managed_mount_path(tmp_path: Path, monkeypatch):
    import smb_profiles_api

    monkeypatch.setattr(smb_profiles_api, "SMB_MANAGED_MOUNT_BASE", tmp_path / "smb")
    monkeypatch.setattr(smb_profiles_api.uuid, "uuid4", lambda: type("Uuid", (), {"hex": "a4f9c2ffeedd"})())

    path = generate_smb_mount_path("Borg VM")

    assert path == str(tmp_path / "smb" / "Borg-VM-smb-a4f9c2")
    assert (tmp_path / "smb").is_dir()


def test_smb_profile_normalization_generates_missing_mount_path(tmp_path: Path, monkeypatch):
    import smb_profiles_api

    monkeypatch.setattr(smb_profiles_api, "SMB_MANAGED_MOUNT_BASE", tmp_path / "smb")
    monkeypatch.setattr(smb_profiles_api.uuid, "uuid4", lambda: type("Uuid", (), {"hex": "112233445566"})())

    rows = normalize_smb_profile_rows([{
        "name": "Borg VM",
        "server": "192.0.2.10",
        "share": "backup",
        "username": "backup",
        "mount_at_start": True,
        "keep_mounted": True,
        "password_set": True,
    }])

    assert rows[0]["mount_path"] == str(tmp_path / "smb" / "Borg-VM-smb-112233")
    assert rows[0]["mount_at_start"] is True
    assert rows[0]["keep_mounted"] is True


def test_smb_protocol_auto_omits_fixed_dialect_and_rejects_smb1():
    assert build_smb_mount_options({"vers": "auto"}, "/secret.cred") == [
        "credentials=/secret.cred",
        "iocharset=utf8",
    ]
    assert "vers=3.0" in build_smb_mount_options({"vers": "3.0"}, "/secret.cred")
    with pytest.raises(ValueError, match="SMB1 is not supported"):
        normalize_smb_version("1.0")


def test_smb_status_reports_actionable_protocol_error_without_secret(tmp_path: Path, monkeypatch):
    credential = tmp_path / ".smb-nas.cred"
    credential.write_text("username=backup\npassword=top-secret\n", encoding="utf-8")
    mount_path = tmp_path / "mount"
    calls = []

    class SocketContext:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("socket.create_connection", lambda *_args, **_kwargs: SocketContext())

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[0] == "findmnt":
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        if command[0] == "mount":
            return type("Result", (), {
                "returncode": 32,
                "stdout": "",
                "stderr": "mount error(22): Invalid argument password=top-secret",
            })()
        raise AssertionError(command)

    monkeypatch.setattr("smb_profiles_api.subprocess.run", fake_run)
    result = check_smb_profiles_status([{
        "key": "nas",
        "name": "NAS",
        "server": "nas.example.test",
        "share": "backup",
        "mount_path": str(mount_path),
        "username": "backup",
        "password_file": str(credential),
        "vers": "auto",
    }])["results"][0]

    mount_command = next(command for command in calls if command[0] == "mount")
    assert "vers=" not in mount_command[-1]
    assert result["failure_code"] == "SMB_PROTOCOL_OR_OPTIONS_FAILED"
    assert "automatic SMB 2/3 negotiation" in result["failure_hint"]
    assert "top-secret" not in result["technical_details"]
    assert "password=***" in result["technical_details"]


def test_manual_smb_mount_uses_same_safe_diagnostics(tmp_path: Path, monkeypatch):
    import smb_profiles_api

    secret = tmp_path / ".smb-nas.cred"
    secret.write_text("username=backup\npassword=top-secret\n", encoding="utf-8")
    profile = {
        "key": "nas",
        "name": "NAS",
        "server": "nas.example.test",
        "share": "backup",
        "mount_path": str(tmp_path / "mount"),
        "username": "backup",
        "password_file": str(secret),
        "vers": "auto",
    }
    monkeypatch.setattr(smb_profiles_api, "get_smb_profiles_with_status", lambda _config: [profile])
    monkeypatch.setattr(smb_profiles_api, "_smb_secret_path", lambda _key: secret)

    def fake_run(command, **_kwargs):
        if command[0] == "findmnt":
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        if command[0] == "mount":
            assert "vers=" not in command[-1]
            return type("Result", (), {
                "returncode": 32,
                "stdout": "",
                "stderr": "mount error(13): Permission denied password=top-secret",
            })()
        raise AssertionError(command)

    monkeypatch.setattr(smb_profiles_api.subprocess, "run", fake_run)
    result = run_smb_profile_action({}, "nas", "mount")

    assert result["ok"] is False
    assert result["failure_code"] == "SMB_AUTH_OR_PERMISSION_FAILED"
    assert "top-secret" not in result["technical_details"]
    assert "password=***" in result["technical_details"]


def test_startup_smb_mounts_only_profiles_marked_for_start(monkeypatch):
    import smb_profiles_api

    actions = []
    monkeypatch.setattr(smb_profiles_api, "get_smb_profiles_with_status", lambda _config: [
        {"key": "nas-a", "mount_at_start": True},
        {"key": "nas-b", "mount_at_start": False},
    ])

    def fake_action(_config, key, action):
        actions.append((key, action))
        return {"ok": True, "message_code": "smb_mount_success"}

    monkeypatch.setattr(smb_profiles_api, "run_smb_profile_action", fake_action)

    result = mount_startup_smb_profiles({})

    assert actions == [("nas-a", "mount")]
    assert result["mounted"] == ["nas-a"]
    assert result["failed"] == []


def test_smb_profile_usage_blocks_delete_when_job_references_profile(tmp_path: Path, monkeypatch):
    import config_api

    job_id = "11111111-1111-4111-8111-111111111111"
    scripts_dir = tmp_path / "scripts"
    data_root = tmp_path / "data"
    meta_dir = data_root / "config" / "jobs"
    meta_dir.mkdir(parents=True)
    (meta_dir / (job_id + ".json")).write_text(
        json.dumps({
            **new_job_defaults(),
            "job_id": job_id,
            "name": "Job 1",
            "repository_key": "repo_job1",
            "source_paths": [str(data_root)],
            "archive_prefixes": ["job1"],
            "legacy_job_keys": ["job1"],
        }) + "\n",
        encoding="utf-8",
    )
    profiles = [{
        "key": "nas-a",
        "name": "NAS A",
        "server": "192.0.2.10",
        "share": "backup",
        "mount_path": "/mnt/user/borg-backup-ui/remotes/nas-a",
        "username": "backup",
        "password_file": "/boot/config/borg-backup/secrets/.smb-nas-a.cred",
    }]

    config = {"BACKUP_SCRIPTS_DIR": str(data_root)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_nas_a",
        "display_name": "NAS A",
        "storage_type": "smb",
        "location": "smb",
        "identity": "smb-profile:nas-a",
        "profile_key": "nas-a",
        "base_path": "/mnt/user/borg-backup-ui/remotes/nas-a",
        "mount_path": "/mnt/user/borg-backup-ui/remotes/nas-a",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_job1",
        "display_name": "Job 1",
        "storage_key": "storage_nas_a",
        "relative_path": "borg-backup-job1",
        "path_raw": "/mnt/user/borg-backup-ui/remotes/nas-a/borg-backup-job1",
        "encryption": "none",
        "job_ids": [job_id],
        "source_job_ids": [job_id],
    }]})
    monkeypatch.setattr(config_api, "get_conf_file", lambda _cfg: scripts_dir / "config" / "backup.conf")
    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {
        "SMB_PROFILES_JSON": json.dumps(profiles),
        "GLOBAL_DATA_DIR": str(data_root),
    })

    before = {path: path.read_bytes() for path in (data_root / "config").rglob("*.json")}
    with pytest.raises(ValueError, match="SMB profile cannot be deleted") as exc_info:
        validate_smb_profile_usage_before_save(config, [])

    assert f"nas-a: Job 1 ({job_id})" in str(exc_info.value)
    assert {path: path.read_bytes() for path in (data_root / "config").rglob("*.json")} == before
