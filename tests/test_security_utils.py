from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import config_api  # noqa: E402
from repositories_api import write_repository_store  # noqa: E402
from security_utils import mask_secrets  # noqa: E402
from storage_objects_api import write_storage_store  # noqa: E402


def test_mask_secrets_handles_common_formats():
    raw = (
        "password=plain token: abc secret='quoted-value' Authorization: Bearer tok "
        "ssh://user:secret@example.test/repo "
        "https://example.test/path?token=abc&x=1&password=hunter2 "
        "BORG_PASSCOMMAND=cat /boot/config/borg-backup/secrets/.borg-passphrase-appdata "
        "/boot/config/borg-backup/secrets/.smb-nas.cred"
    )

    masked = mask_secrets(raw)

    assert "plain" not in masked
    assert "quoted-value" not in masked
    assert "hunter2" not in masked
    assert "Bearer tok" not in masked
    assert "user:secret@" not in masked
    assert "token=abc" not in masked
    assert "password=hunter2" not in masked
    assert ".borg-passphrase-appdata" not in masked
    assert ".smb-nas.cred" not in masked
    assert "password=***" in masked
    assert "secret=***" in masked
    assert "Authorization: Bearer ***" in masked
    assert "ssh://user:***@example.test/repo" in masked


def test_repository_test_output_is_sanitized(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config_api, "read_raw_conf", lambda _cfg: {})
    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {})

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            2,
            "",
            (
                "Authorization: Bearer abc\n"
                "Repository ssh://user:secret@example.test/repo failed\n"
                "passphrase=/boot/config/borg-backup/secrets/.borg-passphrase-appdata\n"
            ),
        )

    monkeypatch.setattr(config_api.subprocess, "run", fake_run)
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_ssh_test",
        "display_name": "Remote",
        "storage_type": "ssh",
        "location": "storagebox",
        "identity": "storagebox-profile:test",
        "profile_key": "test",
        "user": "user",
        "host": "example.test",
        "port": "22",
        "base_path": "/",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_test",
        "display_name": "Test",
        "storage_key": "storage_ssh_test",
        "relative_path": "repo",
        "path_raw": "ssh://user@example.test:22/repo",
        "encryption": "none",
    }]})

    result = config_api.test_repository(config, "repo_test")

    assert result["success"] is False
    assert "Bearer abc" not in result["output"]
    assert "user:secret@" not in result["output"]
    assert ".borg-passphrase-appdata" not in result["output"]
    assert "Bearer ***" in result["output"]
