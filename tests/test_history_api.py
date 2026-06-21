import json
from pathlib import Path

from api.history_api import get_history_data


def _write_status(root: Path, timestamp: str, backup_type: str, location: str, status: str = "success") -> None:
    date, time = timestamp.split(" ")
    path = root / f"{date}_{time.replace(':', '-')}_{backup_type}_{location}.status"
    path.write_text(json.dumps({
        "timestamp": timestamp,
        "backup_type": backup_type,
        "location": location,
        "status": status,
    }), encoding="utf-8")


def test_location_counts_cover_filtered_history_before_pagination(tmp_path: Path) -> None:
    _write_status(tmp_path, "2026-06-21 12:00:00", "appdata", "storagebox")
    _write_status(tmp_path, "2026-06-21 11:00:00", "photos", "usb")
    _write_status(tmp_path, "2026-06-21 10:00:00", "flash", "usb")
    _write_status(tmp_path, "2026-06-21 09:00:00", "appdata", "local")
    _write_status(tmp_path, "2026-06-21 08:00:00", "photos", "smb")

    result = get_history_data({"STATUS_DIR": str(tmp_path)}, {"page": 1, "per_page": 1})

    assert len(result["entries"]) == 1
    assert result["total"] == 5
    assert result["location_total"] == 5
    assert result["location_counts"] == {"storagebox": 1, "usb": 2, "smb": 1, "local": 1}


def test_location_filter_keeps_complete_sidebar_counts(tmp_path: Path) -> None:
    _write_status(tmp_path, "2026-06-21 12:00:00", "appdata", "storagebox")
    _write_status(tmp_path, "2026-06-21 11:00:00", "appdata", "usb")
    _write_status(tmp_path, "2026-06-21 10:00:00", "appdata", "local")

    result = get_history_data({"STATUS_DIR": str(tmp_path)}, {
        "type": "appdata",
        "location": "usb",
        "page": 1,
        "per_page": 20,
    })

    assert result["total"] == 1
    assert result["location_total"] == 3
    assert result["location_counts"] == {"storagebox": 1, "usb": 1, "smb": 0, "local": 1}
