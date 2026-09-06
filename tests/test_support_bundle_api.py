from pathlib import Path
import base64
import json
import sys
import zipfile
from io import BytesIO
import pytest

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
        "GLOBAL_MAIL_RECIPIENT": "admin@example.test",
        "GLOBAL_SMTP_HOST": "smtp.example.test",
        "GLOBAL_SMTP_USER": "admin@example.test",
        "NTFY_SERVER_URL": "https://ntfy.example.test/topic",
        "STORAGEBOX_HOST": "u123.your-storagebox.de",
        "STORAGEBOX_USER": "u123",
        "BORG_SSH_KEY": "/root/.ssh/id_rsa",
        "nested": {"api_token": "abc", "name": "ok"},
        "exclude_paths": ["/data/cache"],
        "exclusion_rules": {"patterns": ["*.tmp"]},
        "repo": "ssh://backup-user@example.invalid:23/./backup/repo",
    }) == {
        "GLOBAL_SMTP_PASSWORD": "[MASKED]",
        "GLOBAL_MAIL_RECIPIENT": "[MASKED]",
        "GLOBAL_SMTP_HOST": "[MASKED]",
        "GLOBAL_SMTP_USER": "[MASKED]",
        "NTFY_SERVER_URL": "[MASKED]",
        "STORAGEBOX_HOST": "[MASKED]",
        "STORAGEBOX_USER": "[MASKED]",
        "BORG_SSH_KEY": "[MASKED]",
        "nested": {"api_token": "[MASKED]", "name": "ok"},
        "exclude_paths": ["/data/cache"],
        "exclusion_rules": {"patterns": ["*.tmp"]},
        "repo": "ssh://[MASKED_SSH_REMOTE]",
    }
    assert "hunter2" not in sanitize_text("password=hunter2\nnormal=ok")
    assert sanitize_text("api_key=PRIVATE-KEY-ONE\napikey PRIVATE-KEY-TWO\napi-key=PRIVATE-KEY-THREE") == (
        "api_key=[MASKED]\napikey [MASKED]\napi-key=[MASKED]")
    sensitive_text = (
        "GLOBAL_MAIL_RECIPIENT=admin@example.test\n"
        "GLOBAL_SMTP_HOST=smtp.example.test\n"
        "GLOBAL_SMTP_USER=admin@example.test\n"
        "NTFY_SERVER_URL=https://ntfy.example.test/topic\n"
        "STORAGEBOX_HOST=u123.your-storagebox.de\n"
        "STORAGEBOX_USER=u123\n"
        "BORG_SSH_KEY=/root/.ssh/id_rsa\n"
    )
    sensitive_sanitized = sanitize_text(sensitive_text)
    assert "admin@example.test" not in sensitive_sanitized
    assert "smtp.example.test" not in sensitive_sanitized
    assert "ntfy.example.test" not in sensitive_sanitized
    assert "u123.your-storagebox.de" not in sensitive_sanitized
    assert "/root/.ssh/id_rsa" not in sensitive_sanitized
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
    key_dir = root / "secrets" / "borg-keys"
    key_dir.mkdir(parents=True)
    (key_dir / "repo-key").write_text("BORG_KEY " + "a" * 64 + "\nPRIVATE-BORG-KEY-DATA\n", encoding="utf-8")
    (scripts_config_dir / "backup.conf").write_text(
        'GLOBAL_SMTP_PASSWORD="supersecret"\nGLOBAL_DATA_DIR="/mnt/user/borg"\n',
        encoding="utf-8",
    )
    (config_dir / "storages.json").write_text(json.dumps({
        "schema_version": 1,
        "storages": [{
            "storage_key": "storage_remote",
            "display_name": "Remote",
            "host": "u123.your-storagebox.de",
            "user": "u123",
            "base_path": "./backup",
        }],
    }) + "\n", encoding="utf-8")
    (config_dir / "repositories.json").write_text(json.dumps({
        "schema_version": 1,
        "repositories": [{
            "repository_key": "repo_job1",
            "storage_key": "storage_remote",
            "relative_path": "job1",
            "passphrase_ref": "/boot/config/borg-backup/secrets/.borg-passphrase-job1",
        }],
    }) + "\n", encoding="utf-8")
    (config_dir / "apprise-profiles.json").write_text(json.dumps({
        "schema_version": 1,
        "profiles": [{
            "id": "alerts-main",
            "name": "Alerts",
            "provider": "ntfy",
            "selected_events": ["backup_failed"],
        }],
    }) + "\n", encoding="utf-8")
    (config_dir / "notification-deliveries.json").write_text(json.dumps({
        "schema_version": 1,
        "deliveries": [{
            "id": "delivery-1",
            "status": "failed",
            "profile_id": "alerts-main",
            "profile_name": "Alerts",
            "provider": "ntfy",
            "event_type": "backup_failed",
            "message": "https://ntfy.example.test rejected token abc123",
        }],
    }) + "\n", encoding="utf-8")
    (root / "secrets" / ".apprise-profile-alerts-main.url").write_text(
        "ntfy://token@example.test/borg\n",
        encoding="utf-8",
    )
    (config_dir / "migration-state.json").write_text(json.dumps({
        "schema_version": 2,
        "migrations": {"beta_upgrade_v1": {"state": "applied"}},
    }) + "\n", encoding="utf-8")
    (config_dir / "migrations.log.jsonl").write_text(json.dumps({
        "event": "migration_completed",
        "migration_id": "beta_upgrade_v1",
        "host": "u123.your-storagebox.de",
    }) + "\n", encoding="utf-8")
    job = {
        "job_id": "11111111-1111-4111-8111-111111111111",
        "name": "A full diagnostic job name " * 10,
        "description": "A complete description with source and policy context. " * 20,
        "source_paths": ["/mnt/user/photos", "/mnt/user/Prüfdaten"],
        "exclude_paths": ["/mnt/user/photos/cache"],
        "exclude_patterns": ["*.tmp"],
        "archive_prefixes": ["photos-backup", "former-name-backup"],
        "restore_test_policy": {"mode": "scheduled", "interval_days": 30},
        "retention": {"keep_daily": 7, "keep_weekly": 4},
        "unknown_config": "SUPPORTED-UNRECOGNIZED-JOB-SETTING",
        "integration": {"api_key": "PRIVATE-API-KEY-ONE", "apikey": "PRIVATE-API-KEY-TWO",
                        "api-key": "PRIVATE-API-KEY-THREE", "name": "diagnostic-context"},
        "passphrase": {"default": "secret-passphrase"},
        "repository": "ssh://u123@u123.your-storagebox.de:23/./backup/job1",
    }
    (jobs_dir / "job1.json").write_text(
        json.dumps(job) + "\n",
        encoding="utf-8",
    )
    (status_dir / "job1.status").write_text(
        json.dumps({"phase": "done", "password": "hunter2", "repository_check_status": "ok",
                    "repo": "ssh://u123@u123.your-storagebox.de:23/./backup/job1"}),
        encoding="utf-8",
    )
    (restore_status_dir / "restore.state").write_text("restore=ok\n", encoding="utf-8")
    (restore_status_dir / "job1.test").write_text(
        json.dumps({"result": "failed", "error": "ssh://u123@u123.your-storagebox.de:23/./backup/job1"}),
        encoding="utf-8",
    )
    plugin_log = log_dir / "borg_backup_ui.log"
    plugin_log.write_text("started\nTOKEN=abc123\n", encoding="utf-8")

    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {
        "GLOBAL_SMTP_PASSWORD": "supersecret",
        "GLOBAL_BORG_CHECK_INTERVAL_DAYS": "30",
        "GLOBAL_COMPRESSION": "zstd,3",
        "GLOBAL_EXCLUDE_PATTERNS": "*.tmp",
        "GLOBAL_MAIL_RECIPIENT": "admin@example.test",
        "GLOBAL_SMTP_HOST": "smtp.example.test",
        "GLOBAL_SMTP_USER": "admin@example.test",
        "NTFY_SERVER_URL": "https://ntfy.example.test/topic",
        "STORAGEBOX_HOST": "u123.your-storagebox.de",
        "STORAGEBOX_USER": "u123",
        "GLOBAL_LOG_DIR": str(log_dir),
        "STATUS_DIR": str(status_dir),
        "RESTORE_TEST_STATUS_DIR": str(restore_status_dir),
        "PLUGIN_LOG_FILE": str(plugin_log),
    })
    monkeypatch.setattr(system_health_api, "get_system_health_data", lambda _cfg: {"checks": {"ok": True}})

    bundle = create_support_bundle({"BACKUP_SCRIPTS_DIR": str(scripts)}, app_version="test-version")
    payload = base64.b64decode(bundle["payload_b64"])

    with zipfile.ZipFile(BytesIO(payload), "r") as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "support/sanitizing-report.json" in names
        assert "config/backup.conf.sanitized.json" in names
        assert "config/settings.sanitized.json" not in names
        assert "config/storages.sanitized.json" in names
        assert "config/repositories.sanitized.json" in names
        assert "config/apprise-profiles.sanitized.json" in names
        assert "config/notification-deliveries.sanitized.json" in names
        assert "config/migration-state.sanitized.json" in names
        assert "config/migrations.log.sanitized.jsonl" in names
        assert "jobs/job1.json" in names
        assert "status/status/job1.status" in names
        assert "status/restore-status/restore.state" in names
        assert "status/restore-status/job1.test" in names
        assert any(name.startswith("logs/plugin/") and name.endswith("borg_backup_ui.log") for name in names)
        assert not any("borg-keys" in name or name.endswith("repo-key") for name in names)
        exported_job = json.loads(zf.read("jobs/job1.json"))
        assert set(exported_job) == set(job)
        for field in ("name", "description", "source_paths", "exclude_paths", "exclude_patterns",
                      "archive_prefixes", "restore_test_policy", "retention", "unknown_config"):
            assert exported_job[field] == job[field]
        assert exported_job["passphrase"] == "[MASKED]"
        assert exported_job["integration"] == {
            "api_key": "[MASKED]", "apikey": "[MASKED]", "api-key": "[MASKED]", "name": "diagnostic-context"}
        for name in ("config/expanded-conf.sanitized.json", "config/backup.conf.sanitized.json"):
            exported_settings = json.loads(zf.read(name))
            assert exported_settings["GLOBAL_BORG_CHECK_INTERVAL_DAYS"] == "30"
            assert exported_settings["GLOBAL_COMPRESSION"] == "zstd,3"
            assert exported_settings["GLOBAL_EXCLUDE_PATTERNS"] == "*.tmp"
            assert exported_settings["GLOBAL_SMTP_PASSWORD"] == "[MASKED]"
        assert json.loads(zf.read("status/status/job1.status"))["repository_check_status"] == "ok"
        assert json.loads(zf.read("status/restore-status/job1.test"))["result"] == "failed"
        all_text = "\n".join(
            zf.read(name).decode("utf-8", errors="replace")
            for name in zf.namelist()
        )

    assert "test-version" in all_text
    assert "SUPPORTED-UNRECOGNIZED-JOB-SETTING" in all_text
    assert "supersecret" not in all_text
    assert "secret-passphrase" not in all_text
    assert "PRIVATE-API-KEY" not in all_text
    assert "PRIVATE-BORG-KEY-DATA" not in all_text
    assert "hunter2" not in all_text
    assert "abc123" not in all_text
    assert "admin@example.test" not in all_text
    assert "smtp.example.test" not in all_text
    assert "u123" not in all_text
    assert "your-storagebox.de" not in all_text
    assert "ntfy.example.test" not in all_text
    assert "ntfy://token@example.test" not in all_text
    assert "/./backup/job1" not in all_text
    assert "alerts-main" in all_text
    assert "ssh://[MASKED_SSH_REMOTE]" in all_text
    assert "[MASKED]" in all_text


@pytest.fixture
def diagnostic_tree(tmp_path, monkeypatch):
    import config_api
    import identity_lifecycle
    import startup_state
    import support_bundle_api
    import system_health_api

    root = tmp_path / "data"
    status = root / "status"
    reports = root / "restore-status"
    logs = root / "logs"
    for directory in (status, reports, logs):
        directory.mkdir(parents=True)
    config = {"BACKUP_SCRIPTS_DIR": str(root)}
    monkeypatch.setattr(startup_state, "is_maintenance_mode", lambda _cfg: False)
    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {
        "STATUS_DIR": str(status), "RESTORE_TEST_STATUS_DIR": str(reports),
        "GLOBAL_LOG_DIR": str(logs),
    })
    monkeypatch.setattr(system_health_api, "get_system_health_data", lambda _cfg: {})
    monkeypatch.setattr(identity_lifecycle, "identity_health", lambda _cfg: {})
    monkeypatch.setattr(support_bundle_api, "_plugin_log_candidates", lambda _cfg: [])
    return config, root, status, reports, logs


@pytest.mark.parametrize("suffix", [".status", ".test"])
def test_large_structured_status_is_complete_masked_json_and_preserves_source(diagnostic_tree, suffix):
    config, _, status, reports, _ = diagnostic_tree
    directory = reports if suffix == ".test" else status
    original = {"job_id": "11111111-1111-4111-8111-111111111111", "test_result": "success",
                "tested_entries": [f"/synthetic/Prüfdaten/photo-{index:05d}.jpg" for index in range(40000)],
                "diagnostics": {"passphrase": "PRIVATE-LARGE-REPORT-PASSPHRASE", "result": "completed"}}
    path = directory / ("complete" + suffix)
    source = json.dumps(original, ensure_ascii=False).encode("utf-8")
    assert len(source) > 1024 * 1024
    path.write_bytes(source)

    bundle = create_support_bundle(config)
    with zipfile.ZipFile(BytesIO(base64.b64decode(bundle["payload_b64"]))) as archive:
        exported = json.loads(archive.read(f"status/{directory.name}/{path.name}"))
    assert exported == {**original, "diagnostics": {"passphrase": "[MASKED]", "result": "completed"}}
    assert path.read_bytes() == source


def test_structured_omissions_are_explicit_without_fake_original_files(diagnostic_tree, monkeypatch):
    import support_bundle_api

    config, root, status, reports, _ = diagnostic_tree
    monkeypatch.setattr(support_bundle_api, "MAX_STRUCTURED_STATUS_BYTES", 256)
    oversized = reports / "oversized.test"
    oversized.write_text(json.dumps({"details": "x" * 300}))
    malformed = status / "invalid.status"
    malformed.write_text('{"password": "PRIVATE-BROKEN-JSON"')
    linked = status / "linked.test"
    recovery = root / ".identity-migration" / "recovery.json"
    recovery.parent.mkdir()
    recovery.write_text('{"data":"PRIVATE-RECOVERY-ARTIFACT"}')
    linked.symlink_to(recovery)
    raw_before = {path: path.read_bytes() for path in (oversized, malformed, recovery)}

    bundle = create_support_bundle(config)
    with zipfile.ZipFile(BytesIO(base64.b64decode(bundle["payload_b64"]))) as archive:
        names = archive.namelist()
        omissions = json.loads(archive.read("support/sanitizing-report.json"))["skipped"]
        for path, reason in ((oversized, "structured_file_too_large"),
                             (malformed, "invalid_json"), (linked, "not_regular_file")):
            assert f"status/{path.parent.name}/{path.name}" not in names
            item = next(item for item in omissions if item["path"] == str(path))
            assert item["reason"] == reason and item["size_bytes"] == path.lstat().st_size
        contents = b"\n".join(archive.read(name) for name in names)
        assert b"PRIVATE-BROKEN-JSON" not in contents
        assert b"PRIVATE-RECOVERY-ARTIFACT" not in contents
        assert not any("recovery.json" in name for name in names)
    assert all(path.read_bytes() == before for path, before in raw_before.items())


def test_structured_budget_skips_whole_files_and_keeps_plaintext_log_tails(diagnostic_tree, monkeypatch):
    import support_bundle_api

    config, _, status, reports, logs = diagnostic_tree
    data = {"details": "complete-structured-record" * 5}
    source = json.dumps(data).encode()
    encoded_size = len((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())
    monkeypatch.setattr(support_bundle_api, "MAX_STRUCTURED_STATUS_TOTAL_BYTES", encoded_size)
    first = status / "first.status"
    second = reports / "second.test"
    first.write_bytes(source)
    second.write_bytes(source)
    plain = reports / "restore.state"
    plain.write_text("state=completed\n")
    log = logs / "backup.log"
    log.write_text("discarded-start\n" + "x" * 70000 + "\npassword=PRIVATE-LOG-PASSWORD\nend\n")

    bundle = create_support_bundle(config)
    with zipfile.ZipFile(BytesIO(base64.b64decode(bundle["payload_b64"]))) as archive:
        assert json.loads(archive.read("status/status/first.status")) == data
        assert "status/restore-status/second.test" not in archive.namelist()
        omissions = json.loads(archive.read("support/sanitizing-report.json"))["skipped"]
        item = next(item for item in omissions if item["path"] == str(second))
        assert item["reason"] == "structured_budget_exceeded" and item["size_bytes"] == len(source)
        assert archive.read("status/restore-status/restore.state") == b"state=completed\n"
        text = archive.read("logs/backup.log").decode()
        assert text.startswith("[truncated to last 65536 bytes]\n") and text.endswith("end\n")
        assert "discarded-start" not in text and "PRIVATE-LOG-PASSWORD" not in text
    assert first.read_bytes() == second.read_bytes() == source
