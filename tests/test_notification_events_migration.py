from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from migrations import notification_events_v1  # noqa: E402


def test_notification_events_migration_adds_missing_keys_and_warning_alias(tmp_path):
    base = tmp_path / "borg"
    config_dir = base / "config"
    config_dir.mkdir(parents=True)
    conf = config_dir / "backup.conf"
    conf.write_text('NTFY_EVENTS="backup_success,backup_failed,backup_skipped"\n', encoding="utf-8")

    cfg = {"BACKUP_SCRIPTS_DIR": str(base)}
    detected = notification_events_v1.detect(cfg)
    assert detected["required"] is True

    result = notification_events_v1.apply(cfg)
    assert result["status"] == "applied"

    out = conf.read_text(encoding="utf-8")
    assert "NOTIFY_EMAIL_EVENTS=backup_failed" in out
    assert "NOTIFY_UNRAID_EVENTS=backup_success,backup_warning,backup_failed,backup_skipped" in out
    assert "NOTIFY_REMINDER_INTERVAL_HOURS=24" in out
    assert "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS=6" in out
    assert "NTFY_EVENTS=backup_success,backup_failed,backup_skipped,backup_warning" in out
