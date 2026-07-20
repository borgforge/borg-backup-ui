from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
for candidate in (ROOT, API_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from config_api import canonical_backup_conf_plan, read_raw_conf  # noqa: E402
from migrations import canonical_backup_conf_v1  # noqa: E402


def _config(root: Path) -> dict:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    schema_file = root / "plugin-backup.conf.example"
    schema_file.write_text(
        "# Canonical global settings\n"
        'GLOBAL_DATA_DIR="/mnt/user/borg_backup_ui"\n'
        'UI_SESSION_TIMEOUT_MINUTES="30"\n'
        'NOTIFY_EMAIL_EVENTS="backup_failed"\n',
        encoding="utf-8",
    )
    return {"BACKUP_SCRIPTS_DIR": str(root), "BACKUP_CONF_SCHEMA_FILE": str(schema_file)}


def _events(root: Path) -> list[dict]:
    path = root / "config" / "migrations.log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_migration_rebuilds_backup_conf_from_canonical_schema(tmp_path: Path) -> None:
    config = _config(tmp_path)
    conf = tmp_path / "config" / "backup.conf"
    legacy_schema = tmp_path / "config" / "backup.conf.example"
    legacy_schema.write_text('STALE_KEY="stale"\n', encoding="utf-8")
    conf.write_text(
        'GLOBAL_DATA_DIR="/mnt/user/custom data"\n'
        'REPO_FLASH_LOCAL="/mnt/backup/borg-backup-flash"\n'
        'STORAGEBOX_HOST="example.invalid"\n',
        encoding="utf-8",
    )

    detection = canonical_backup_conf_v1.detect(config)
    result = canonical_backup_conf_v1.apply(config)

    assert detection["required"] is True
    assert detection["missing_keys"] == ["NOTIFY_EMAIL_EVENTS", "UI_SESSION_TIMEOUT_MINUTES"]
    assert detection["unknown_keys"] == ["REPO_FLASH_LOCAL", "STORAGEBOX_HOST"]
    assert result["status"] == "applied"
    assert result["details"]["added_keys"] == ["NOTIFY_EMAIL_EVENTS", "UI_SESSION_TIMEOUT_MINUTES"]
    assert result["details"]["removed_keys"] == ["REPO_FLASH_LOCAL", "STORAGEBOX_HOST"]
    assert read_raw_conf(config) == {
        "GLOBAL_DATA_DIR": "/mnt/user/custom data",
        "UI_SESSION_TIMEOUT_MINUTES": "30",
        "NOTIFY_EMAIL_EVENTS": "backup_failed",
    }

    backup_dir = Path(result["details"]["backup_directory"])
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["removed_keys"] == ["REPO_FLASH_LOCAL", "STORAGEBOX_HOST"]
    assert (backup_dir / "backup.conf").is_file()
    assert (backup_dir / "legacy-backup.conf.example").is_file()
    assert not legacy_schema.exists()
    assert result["details"]["legacy_schema_removed"] is True
    events = _events(tmp_path)
    assert [event["event"] for event in events] == ["migration_started", "migration_applied"]


def test_migration_is_idempotent_after_success(tmp_path: Path) -> None:
    config = _config(tmp_path)
    conf = tmp_path / "config" / "backup.conf"
    conf.write_text('GLOBAL_DATA_DIR="/mnt/user/custom"\n', encoding="utf-8")

    first = canonical_backup_conf_v1.apply(config)
    content_after_first = conf.read_text(encoding="utf-8")
    second_detection = canonical_backup_conf_v1.detect(config)
    second = canonical_backup_conf_v1.apply(config)

    assert first["status"] == "applied"
    assert second_detection["required"] is False
    assert second["status"] == "not_required"
    assert conf.read_text(encoding="utf-8") == content_after_first
    assert len(list((tmp_path / "config" / "migration-backups").iterdir())) == 1


def test_migration_restores_original_file_when_verification_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    conf = tmp_path / "config" / "backup.conf"
    original_content = (
        'GLOBAL_DATA_DIR="/mnt/user/original"\n'
        'REPO_FLASH_LOCAL="/mnt/backup/borg-backup-flash"\n'
    )
    conf.write_text(original_content, encoding="utf-8")
    legacy_schema = tmp_path / "config" / "backup.conf.example"
    legacy_content = 'STALE_KEY="stale"\n'
    legacy_schema.write_text(legacy_content, encoding="utf-8")
    original_plan = canonical_backup_conf_plan
    calls = 0

    def fail_verification(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("forced verification failure")
        return original_plan(*args, **kwargs)

    monkeypatch.setattr(canonical_backup_conf_v1, "canonical_backup_conf_plan", fail_verification)

    result = canonical_backup_conf_v1.apply(config)

    assert result["status"] == "failed"
    assert result["details"]["rollback_status"] == "restored"
    assert result["details"]["error_type"] == "RuntimeError"
    assert conf.read_text(encoding="utf-8") == original_content
    assert legacy_schema.read_text(encoding="utf-8") == legacy_content
    assert _events(tmp_path)[-1]["event"] == "migration_failed"
