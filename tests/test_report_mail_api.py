import json
from datetime import datetime
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


REPORT_NOW = datetime(2026, 6, 12, 12, 0, 0)


def _write_status(status_dir: Path, name: str, data: dict) -> None:
    path = status_dir / name
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_job_meta(root: Path, key: str, *, name: str, backup_type: str, location: str) -> None:
    scripts_dir = root / "scripts"
    jobs_dir = root / "config" / "jobs"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / f"{key}.json").write_text(json.dumps({
        "schema_version": 3,
        "job_key": key,
        "name": name,
        "backup_type": backup_type,
        "location": location,
        "repository_key": f"repo_{key}",
        "source_paths": ["/mnt/user/appdata"],
    }), encoding="utf-8")


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

    _write_job_meta(tmp_path, "appdata_local", name="Appdata Lokal", backup_type="appdata", location="local")

    html = _build_html_report({
        "STATUS_DIR": str(status_dir),
        "BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts"),
        "HOSTNAME": "Tower",
    }, now=REPORT_NOW)

    assert "Weekly Report" in html
    assert "data:image/png;base64" in html
    assert "Server: Tower" in html
    assert "Total repository size" in html
    assert "Total duration" in html
    assert "Job Overview" in html
    assert ">Local<" in html
    assert "Appdata Lokal" in html
    assert "appdata_local" not in html
    assert "Key: appdata_local" not in html
    assert "appdata-backup-2026-06-11_23-00-00" in html
    assert "Runs 7d" in html
    assert "Success 7d" in html
    assert "Exit</th>" not in html
    assert "No issues detected" in html


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

    html = _build_html_report({"STATUS_DIR": str(status_dir)}, now=REPORT_NOW)

    assert "Success 7d" in html
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

    html = _build_html_report({"STATUS_DIR": str(status_dir)}, now=REPORT_NOW)

    assert "Issues" in html
    assert "Repository nicht erreichbar" in html
    assert "Repository check is overdue" in html
    assert "Log Details" in html
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

    html = _build_html_report({"STATUS_DIR": str(status_dir)}, now=REPORT_NOW)

    assert html.index(">Local<") < html.index(">USB<")
    assert html.index(">USB<") < html.index(">Storagebox<")
    assert html.index("Photos - Local") < html.index("Flash - USB")
    assert html.index("Flash - USB") < html.index("Appdata - Storagebox")


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

    html = _build_html_report({"STATUS_DIR": str(status_dir)}, now=REPORT_NOW)

    assert "Log Details" not in html
    assert "Kein Mail-Versand" not in html
