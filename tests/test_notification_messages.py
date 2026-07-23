from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "runtime"
RUNTIME_LIB = ROOT / "runtime" / "lib"
for path in (ROOT, RUNTIME_ROOT, RUNTIME_LIB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from lib import notifications  # noqa: E402


def test_build_backup_notification_message_is_english():
    msg = notifications.build_backup_notification_message(
        job_name="appdata_daily",
        status="Error",
        timestamp="2026-06-28 10:00:00",
        duration_seconds=65,
        repository="usb_backup_01",
        backup_location="usb",
        error_message="Repository could not be opened",
    )

    assert "Job: appdata_daily" in msg
    assert "Result: Error" in msg
    assert "Duration: 00:01:05" in msg
    assert "Target: USB / usb_backup_01" in msg
    assert "Repository: usb_backup_01" in msg
    assert "Error: Repository could not be opened" in msg
    assert "Action: Review the backup log and storage connection." in msg


def test_build_backup_notification_success_message_is_compact():
    msg = notifications.build_backup_notification_message(
        job_name="Flash",
        status="Successful",
        timestamp="2026-07-01 08:05:30",
        duration_seconds=19,
        repository="ssh://u525674@u525674.your-storagebox.de:23/./backup/borg-backup-flash",
        backup_location="storagebox",
        archive_name="flash-backup-2026-07-01_08-05-11",
    )

    assert msg.splitlines() == [
        "Job: Flash",
        "Result: Successful",
        "Duration: 19 sec",
        "Finished: 2026-07-01 08:05",
        "Target: Storagebox / borg-backup-flash",
        "Archive: flash-backup-2026-07-01_08-05-11",
    ]
    assert "Repository:" not in msg


def test_build_restore_test_notification_message_is_english():
    msg = notifications.build_restore_test_notification_message(
        job_name="appdata_local",
        status="Failed",
        timestamp="2026-06-28 11:00:00",
        duration_seconds=125,
        repository="/mnt/backup/borg-backup-appdata",
        level=3,
        coverage="partial",
        error_message="Archive could not be read",
    )

    assert "Job: appdata_local" in msg
    assert "Status: Failed" in msg
    assert "Duration: 00:02:05" in msg
    assert "Repository: /mnt/backup/borg-backup-appdata" in msg
    assert "Level: L3" in msg
    assert "Coverage: partial" in msg
    assert "Error: Archive could not be read" in msg
