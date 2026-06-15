import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
RUNTIME_LIB = ROOT / "runtime" / "lib"
if str(RUNTIME_LIB) not in sys.path:
    sys.path.insert(0, str(RUNTIME_LIB))

from report_mail_api import _build_html_report


def _write_status(status_dir: Path, name: str, data: dict) -> None:
    path = status_dir / name
    path.write_text(json.dumps(data), encoding="utf-8")


def test_weekly_report_contains_summary_and_extended_job_table(tmp_path: Path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()

    _write_status(status_dir, "2026-06-11_23-00-00_appdata_local.status", {
        "backup_type": "appdata",
        "location": "local",
        "timestamp": "2026-06-11 23:00:00",
        "duration_seconds": 744,
        "exit_code": 0,
        "status": "success",
        "archive_name": "appdata-backup-2026-06-11_23-00-00",
        "repository_size": 1024 ** 3,
        "files_count": 1234,
        "repository_check_status": "ok",
    })

    html = _build_html_report({"STATUS_DIR": str(status_dir), "HOSTNAME": "Tower"})

    assert "Wochenbericht" in html
    assert "data:image/png;base64" in html
    assert "Server: Tower" in html
    assert "Repo gesamt" in html
    assert "Dauer gesamt" in html
    assert "Job-Übersicht" in html
    assert "appdata_local" in html
    assert "appdata-backup-2026-06-11_23-00-00" in html
    assert "Läufe 7T" in html
    assert "Erfolg 7T" in html
    assert "Exit</th>" not in html
    assert "Keine Auffälligkeiten erkannt" in html


def test_weekly_report_success_rate_uses_recent_runs(tmp_path: Path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()

    _write_status(status_dir, "2026-05-01_22-00-00_appdata_storagebox.status", {
        "backup_type": "appdata",
        "location": "storagebox",
        "timestamp": "2026-05-01 22:00:00",
        "status": "error",
    })
    _write_status(status_dir, "2026-06-11_22-00-00_appdata_storagebox.status", {
        "backup_type": "appdata",
        "location": "storagebox",
        "timestamp": "2026-06-11 22:00:00",
        "status": "success",
    })

    html = _build_html_report({"STATUS_DIR": str(status_dir)})

    assert "Erfolg 7T" in html
    assert "100%" in html
    assert "50%" not in html


def test_weekly_report_surfaces_issues_and_log_hints(tmp_path: Path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    log_file = tmp_path / "backup.log"
    log_file.write_text(
        "2026-06-11 INFO Start\n"
        "2026-06-11 WARNING WARNUNG: Borg compact fehlgeschlagen\n"
        "2026-06-11 ERROR FEHLER: Repository nicht erreichbar\n",
        encoding="utf-8",
    )

    _write_status(status_dir, "2026-06-11_22-00-00_flash_storagebox.status", {
        "backup_type": "flash",
        "location": "storagebox",
        "timestamp": "2026-06-11 22:00:00",
        "duration_seconds": 20,
        "exit_code": 2,
        "status": "error",
        "error_message": "Repository nicht erreichbar",
        "log_file": str(log_file),
        "repository_size": 5 * 1024 ** 3,
        "files_count": 42,
        "repository_check_status": "overdue",
    })

    html = _build_html_report({"STATUS_DIR": str(status_dir)})

    assert "Auffälligkeiten" in html
    assert "Repository nicht erreichbar" in html
    assert "Repository-Prüfung ist überfällig" in html
    assert "Log-Hinweise" in html
    assert "Borg compact fehlgeschlagen" in html


def test_weekly_report_sorts_jobs_by_location(tmp_path: Path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()

    _write_status(status_dir, "2026-06-11_22-00-00_flash_usb.status", {
        "backup_type": "flash",
        "location": "usb",
        "timestamp": "2026-06-11 22:00:00",
        "status": "success",
    })
    _write_status(status_dir, "2026-06-11_22-00-00_photos_local.status", {
        "backup_type": "photos",
        "location": "local",
        "timestamp": "2026-06-11 22:00:00",
        "status": "success",
    })
    _write_status(status_dir, "2026-06-11_22-00-00_appdata_storagebox.status", {
        "backup_type": "appdata",
        "location": "storagebox",
        "timestamp": "2026-06-11 22:00:00",
        "status": "success",
    })

    html = _build_html_report({"STATUS_DIR": str(status_dir)})

    assert html.index("photos_local") < html.index("appdata_storagebox")
    assert html.index("appdata_storagebox") < html.index("flash_usb")


def test_weekly_report_ignores_non_error_log_hints(tmp_path: Path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    log_file = tmp_path / "backup.log"
    log_file.write_text(
        "2026-06-11 09:00:01 INFO Mail: thorsten.steinberg@gmx.de (bei Fehler)\n"
        "2026-06-11 09:12:49 INFO Kein Mail-Versand (Erfolg/Warnung wird in Weekly Summary berichtet)\n",
        encoding="utf-8",
    )

    _write_status(status_dir, "2026-06-11_22-00-00_appdata_local.status", {
        "backup_type": "appdata",
        "location": "local",
        "timestamp": "2026-06-11 22:00:00",
        "status": "success",
        "log_file": str(log_file),
    })

    html = _build_html_report({"STATUS_DIR": str(status_dir)})

    assert "Log-Hinweise" not in html
    assert "Kein Mail-Versand" not in html
