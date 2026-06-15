from pathlib import Path
import base64
import json
import sys
import zipfile
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from support_bundle_api import create_support_bundle, sanitize_data, sanitize_text


def test_support_bundle_sanitizes_secret_keys_and_text():
    assert sanitize_data({
        "GLOBAL_SMTP_PASSWORD": "secret",
        "nested": {"api_token": "abc", "name": "ok"},
        "repo": "ssh://backup-user@example.invalid:23/./backup/repo",
    }) == {
        "GLOBAL_SMTP_PASSWORD": "[MASKED]",
        "nested": {"api_token": "[MASKED]", "name": "ok"},
        "repo": "ssh://[MASKED_SSH_REMOTE]",
    }
    assert "hunter2" not in sanitize_text("password=hunter2\nnormal=ok")
    sanitized = sanitize_text('BORG_REPO="ssh://u123@u123.your-storagebox.de:23/./backup/repo"\n')
    assert "u123" not in sanitized
    assert "your-storagebox.de" not in sanitized
    assert "/./backup/repo" not in sanitized
    assert "ssh://[MASKED_SSH_REMOTE]" in sanitized


def test_support_bundle_contains_sanitized_config_and_jobs(tmp_path: Path, monkeypatch):
    import config_api
    import system_health_api

    root = tmp_path / "borg-backup"
    scripts = root / "scripts"
    config_dir = root / "config"
    scripts_config_dir = scripts / "config"
    jobs_dir = config_dir / "jobs"
    status_dir = root / "status"
    restore_status_dir = root / "restore-status"
    log_dir = root / "logs"
    config_dir.mkdir(parents=True)
    scripts_config_dir.mkdir(parents=True)
    jobs_dir.mkdir(parents=True)
    status_dir.mkdir(parents=True)
    restore_status_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    (scripts_config_dir / "backup.conf").write_text(
        'GLOBAL_SMTP_PASSWORD="supersecret"\nGLOBAL_DATA_DIR="/mnt/user/borg"\n',
        encoding="utf-8",
    )
    (config_dir / "settings.json").write_text(
        json.dumps({"schema_version": 1, "smb_profiles": [], "storage_profiles": [], "usb_profiles": []}) + "\n",
        encoding="utf-8",
    )
    (jobs_dir / "job1.json").write_text(
        json.dumps({
            "job_key": "job1",
            "passphrase": {"default": "secret-passphrase"},
            "repository": "ssh://u123@u123.your-storagebox.de:23/./backup/job1",
        }) + "\n",
        encoding="utf-8",
    )
    (status_dir / "job1.status").write_text(
        "phase=done\npassword=hunter2\nrepo=ssh://u123@u123.your-storagebox.de:23/./backup/job1\n",
        encoding="utf-8",
    )
    (restore_status_dir / "restore.state").write_text("restore=ok\n", encoding="utf-8")
    plugin_log = log_dir / "borg_backup_ui.log"
    plugin_log.write_text("started\nTOKEN=abc123\n", encoding="utf-8")

    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {
        "GLOBAL_SMTP_PASSWORD": "supersecret",
        "GLOBAL_LOG_DIR": str(log_dir),
        "STATUS_DIR": str(status_dir),
        "RESTORE_TEST_STATUS_DIR": str(restore_status_dir),
        "PLUGIN_LOG_FILE": str(plugin_log),
    })
    monkeypatch.setattr(config_api, "read_settings_payload", lambda _cfg: {
        "schema_version": 1,
        "smb_profiles": [],
        "storage_profiles": [],
        "usb_profiles": [],
    })
    monkeypatch.setattr(system_health_api, "get_system_health_data", lambda _cfg: {"checks": {"ok": True}})

    bundle = create_support_bundle({"BACKUP_SCRIPTS_DIR": str(scripts)}, app_version="test-version")
    payload = base64.b64decode(bundle["payload_b64"])

    with zipfile.ZipFile(BytesIO(payload), "r") as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "support/sanitizing-report.json" in names
        assert "config/backup.conf.sanitized.txt" in names
        assert "jobs/job1.json" in names
        assert "status/status/job1.status" in names
        assert "status/restore-status/restore.state" in names
        assert any(name.startswith("logs/plugin/") and name.endswith("borg_backup_ui.log") for name in names)
        all_text = "\n".join(
            zf.read(name).decode("utf-8", errors="replace")
            for name in zf.namelist()
        )

    assert "test-version" in all_text
    assert "supersecret" not in all_text
    assert "secret-passphrase" not in all_text
    assert "hunter2" not in all_text
    assert "abc123" not in all_text
    assert "u123" not in all_text
    assert "your-storagebox.de" not in all_text
    assert "/./backup/job1" not in all_text
    assert "ssh://[MASKED_SSH_REMOTE]" in all_text
    assert "[MASKED]" in all_text
