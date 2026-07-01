from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import config_api  # noqa: E402
from security_utils import mask_secrets  # noqa: E402


def test_mask_secrets_handles_common_formats():
    raw = (
        "password=plain token: abc Authorization: Bearer tok "
        "ssh://user:secret@example.test/repo "
        "https://example.test/path?token=abc&x=1 "
        "BORG_PASSCOMMAND=cat /boot/config/borg-backup/secrets/.borg-passphrase-appdata "
        "/boot/config/borg-backup/secrets/.smb-nas.cred"
    )

    masked = mask_secrets(raw)

    assert "plain" not in masked
    assert "Bearer tok" not in masked
    assert "user:secret@" not in masked
    assert "token=abc" not in masked
    assert ".borg-passphrase-appdata" not in masked
    assert ".smb-nas.cred" not in masked
    assert "password=***" in masked
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

    result = config_api.test_repository("ssh://user:secret@example.test/repo", {"BACKUP_SCRIPTS_DIR": str(tmp_path)})

    assert result["success"] is False
    assert "Bearer abc" not in result["output"]
    assert "user:secret@" not in result["output"]
    assert ".borg-passphrase-appdata" not in result["output"]
    assert "Bearer ***" in result["output"]
