from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from config_api import read_raw_conf  # noqa: E402
from migrations import ntfy_apprise_cutover_v1  # noqa: E402


def _config(root: Path) -> dict:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    schema_file = root / "plugin-backup.conf.example"
    schema_file.write_text(
        'NOTIFY_EMAIL_EVENTS="backup_failed"\n'
        'NOTIFY_UNRAID_EVENTS="backup_success,backup_warning,backup_failed,backup_skipped"\n'
        'NOTIFY_REMINDER_INTERVAL_HOURS="24"\n'
        'NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS="6"\n',
        encoding="utf-8",
    )
    return {"BACKUP_SCRIPTS_DIR": str(root), "BACKUP_CONF_SCHEMA_FILE": str(schema_file)}


def test_ntfy_cutover_migrates_enabled_native_profile_and_removes_keys(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    token = tmp_path / "secrets" / ".ntfy-token"
    token.parent.mkdir(parents=True)
    token.write_text("tk_secret", encoding="utf-8")
    conf = tmp_path / "config" / "backup.conf"
    conf.write_text(
        'NOTIFY_EMAIL_EVENTS="backup_failed"\n'
        'NOTIFY_UNRAID_EVENTS="backup_success,backup_warning,backup_failed,backup_skipped"\n'
        'NOTIFY_REMINDER_INTERVAL_HOURS="24"\n'
        'NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS="6"\n'
        'NTFY_ENABLED="true"\n'
        'NTFY_PROFILE_NAME="Server Alerts"\n'
        'NTFY_SERVER_URL="https://ntfy.example.test"\n'
        'NTFY_TOPIC="borg"\n'
        f'NTFY_ACCESS_TOKEN_FILE="{token}"\n'
        'NTFY_PRIORITY="urgent"\n'
        'NTFY_TAGS="borg,backup"\n'
        'NTFY_CLICK_URL="https://unraid.example.test"\n'
        'NTFY_EVENTS="backup_success,backup_failed,backup_skipped,restore_test_failed"\n'
        'NTFY_TIMEOUT_SECONDS="25"\n',
        encoding="utf-8",
    )

    detected = ntfy_apprise_cutover_v1.detect(cfg)
    result = ntfy_apprise_cutover_v1.apply(cfg)

    assert detected["required"] is True
    assert result["status"] == "applied"
    assert result["details"]["profile_id"] == "ntfy-migrated"
    assert result["details"]["secret_written"] is True
    assert not any(key.startswith("NTFY_") for key in read_raw_conf(cfg))

    store_text = (tmp_path / "config" / "apprise-profiles.json").read_text(encoding="utf-8")
    assert "tk_secret" not in store_text
    profile = json.loads(store_text)["profiles"][0]
    assert profile["id"] == "ntfy-migrated"
    assert profile["name"] == "Server Alerts"
    assert profile["enabled"] is True
    assert profile["provider"] == "ntfy"
    assert profile["default"] is True
    assert profile["timeout_seconds"] == 25
    assert profile["url_template"] == "{schema}://{token}@{host}/{targets}"
    assert profile["url_fields"] == {"host": "ntfy.example.test", "targets": "borg"}
    assert profile["migration"]["source"] == "native_ntfy"
    assert "backup_warning" in profile["selected_events"]

    secret = (tmp_path / "secrets" / ".apprise-profile-ntfy-migrated.url").read_text(encoding="utf-8").strip()
    parsed = urlsplit(secret)
    assert parsed.scheme == "ntfys"
    assert parsed.username == "tk_secret"
    assert parsed.hostname == "ntfy.example.test"
    assert parsed.path == "/borg"
    query = parse_qs(parsed.query)
    assert query["auth"] == ["token"]
    assert query["priority"] == ["max"]
    assert query["xtags"] == ["borg,backup"]
    assert query["click"] == ["https://unraid.example.test"]

    assert ntfy_apprise_cutover_v1.detect(cfg)["required"] is False
    assert ntfy_apprise_cutover_v1.apply(cfg)["status"] == "not_required"


def test_ntfy_cutover_keeps_incomplete_native_settings_as_disabled_profile(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    conf = tmp_path / "config" / "backup.conf"
    conf.write_text(
        'NOTIFY_EMAIL_EVENTS="backup_failed"\n'
        'NTFY_ENABLED="true"\n'
        'NTFY_PROFILE_NAME="Incomplete ntfy"\n'
        'NTFY_TOPIC=""\n',
        encoding="utf-8",
    )

    result = ntfy_apprise_cutover_v1.apply(cfg)

    assert result["status"] == "applied"
    assert result["details"]["secret_written"] is False
    assert not any(key.startswith("NTFY_") for key in read_raw_conf(cfg))
    profile = json.loads((tmp_path / "config" / "apprise-profiles.json").read_text(encoding="utf-8"))["profiles"][0]
    assert profile["name"] == "Incomplete ntfy"
    assert profile["enabled"] is False
    assert profile["url_set"] is False
    assert not (tmp_path / "secrets" / ".apprise-profile-ntfy-migrated.url").exists()
