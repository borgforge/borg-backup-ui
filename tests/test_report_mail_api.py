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
from status_view_fixture_support import job_id_for, write_job, status_identity


REPORT_NOW = datetime(2026, 6, 12, 12, 0, 0)


def _write_status(status_dir: Path, name: str, data: dict) -> None:
    path = status_dir / name
    label = data.get('backup_type', 'unknown') + '_' + data.get('location', 'local')
    if not (status_dir.parent / 'config/jobs' / (job_id_for(label) + '.json')).exists():
        write_job(status_dir.parent, label, name=data.get('backup_type', ''), location=data.get('location', 'local'))
    path.write_text(json.dumps({**status_identity(status_dir.parent,label,name=data.get('backup_type', ''),location=data.get('location','local')), **data}), encoding='utf-8')


def _write_job_meta(root: Path, key: str, *, name: str, backup_type: str, location: str) -> None:
    write_job(root, key, name=name, location=location)


def _write_schedules(root: Path, schedules: dict) -> None:
    root = root.parent if root.name == "scripts" else root
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "schedules.json").write_text(json.dumps({job_id_for(key):value for key,value in schedules.items()}), encoding="utf-8")


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
    assert "Period: 2026-06-06 00:00 to 2026-06-12 12:00" in html
    assert "Total repository size" in html
    assert "Total duration" in html
    assert "Weekly Activity" in html
    assert "Job Details" in html
    assert ">Local<" in html
    assert "Appdata Lokal" in html
    assert "appdata_local" not in html
    assert "Key: appdata_local" not in html
    assert "appdata-backup-2026-06-11_23-00-00" in html
    assert "Growth 7d" in html
    assert "Runs 7d" not in html
    assert "Success 7d" not in html
    assert "Exit</th>" not in html
    assert "No issues detected" in html


def test_weekly_report_renders_planned_activity_matrix_and_manual_jobs(tmp_path: Path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()

    _write_job_meta(tmp_path, "appdata_local", name="Appdata Lokal", backup_type="appdata", location="local")
    _write_job_meta(tmp_path, "photos_local", name="Fotos Lokal", backup_type="photos", location="local")
    _write_job_meta(tmp_path, "vms_local", name="VMs Lokal", backup_type="vms", location="local")
    _write_schedules(tmp_path / "scripts", {
        "appdata_local": {"enabled": True, "cron": "0 9 * * *"},
        "vms_local": {"enabled": True, "cron": "0 6 * * 1"},
    })
    _write_status(status_dir, "2026-06-12_09-04-00_appdata_local.status", {
        "backup_type": "appdata",
        "location": "local",
        "timestamp": "2026-06-12 09:04:00",
        "status": "success",
    })
    _write_status(status_dir, "2026-06-11_20-00-00_photos_local.status", {
        "backup_type": "photos",
        "location": "local",
        "timestamp": "2026-06-11 20:00:00",
        "status": "success",
    })

    html = _build_html_report({
        "STATUS_DIR": str(status_dir),
        "BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts"),
    }, now=REPORT_NOW)

    assert "Weekly Activity" in html
    assert "Planned jobs" in html
    assert "Manual jobs" in html
    assert "Appdata Lokal" in html
    assert "VMs Lokal" in html
    assert "Fotos Lokal" in html
    assert "Expected but not run" in html
    assert "expected run missing" in html
    assert "Manual" in html


def test_weekly_report_treats_unsupported_cron_as_manual_activity(tmp_path: Path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()

    _write_job_meta(tmp_path, "custom_local", name="Custom Lokal", backup_type="custom", location="local")
    _write_schedules(tmp_path / "scripts", {
        "custom_local": {"enabled": True, "cron": "*/15 * * * *"},
    })
    _write_status(status_dir, "2026-06-12_10-00-00_custom_local.status", {
        "backup_type": "custom",
        "location": "local",
        "timestamp": "2026-06-12 10:00:00",
        "status": "success",
    })

    html = _build_html_report({
        "STATUS_DIR": str(status_dir),
        "BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts"),
    }, now=REPORT_NOW)

    assert "Custom Lokal" in html
    assert "Custom schedule" in html
    assert "expected run missing" not in html


def test_weekly_report_job_details_show_repository_growth(tmp_path: Path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()

    _write_status(status_dir, "2026-06-05_22-00-00_appdata_storagebox.status", {
        "backup_type": "appdata",
        "location": "storagebox",
        "timestamp": "2026-06-05 22:00:00",
        "status": "success",
        "repository_size": 1024 ** 3,
    })
    _write_status(status_dir, "2026-06-11_22-00-00_appdata_storagebox.status", {
        "backup_type": "appdata",
        "location": "storagebox",
        "timestamp": "2026-06-11 22:00:00",
        "status": "success",
        "repository_size": 2 * 1024 ** 3,
    })

    html = _build_html_report({"STATUS_DIR": str(status_dir), "BACKUP_SCRIPTS_DIR": str(tmp_path)}, now=REPORT_NOW)

    assert "Growth 7d" in html
    assert "+1.0 GB" in html
    assert "Success 7d" not in html


def test_weekly_report_surfaces_issues_and_log_hints(tmp_path: Path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    _write_schedules(tmp_path / "scripts", {
        "flash_storagebox": {"enabled": True, "cron": "0 22 * * *"},
    })
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

    html = _build_html_report({
        "STATUS_DIR": str(status_dir),
        "BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts"),
    }, now=REPORT_NOW)

    assert "Issues" in html
    assert "Repository nicht erreichbar" in html
    assert "Repository check is overdue" in html
    assert "Log Details" in html
    assert "Borg compact fehlgeschlagen" in html


def test_weekly_report_does_not_flag_manual_old_runs_as_issues(tmp_path: Path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()

    _write_job_meta(tmp_path, "vms_local", name="VMs Lokal", backup_type="vms", location="local")
    _write_status(status_dir, "2026-05-20_03-00-00_vms_local.status", {
        "backup_type": "vms",
        "location": "local",
        "timestamp": "2026-05-20 03:00:00",
        "status": "success",
    })

    html = _build_html_report({
        "STATUS_DIR": str(status_dir),
        "BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts"),
    }, now=REPORT_NOW)

    assert "Manual jobs" in html
    assert "VMs Lokal" in html
    assert "No issues detected" in html
    assert "No run in this report period" not in html


def test_weekly_report_flags_planned_old_runs_as_issues(tmp_path: Path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()

    _write_job_meta(tmp_path, "vms_local", name="VMs Lokal", backup_type="vms", location="local")
    _write_schedules(tmp_path / "scripts", {
        "vms_local": {"enabled": True, "cron": "0 3 * * 1"},
    })
    _write_status(status_dir, "2026-05-20_03-00-00_vms_local.status", {
        "backup_type": "vms",
        "location": "local",
        "timestamp": "2026-05-20 03:00:00",
        "status": "success",
    })

    html = _build_html_report({
        "STATUS_DIR": str(status_dir),
        "BACKUP_SCRIPTS_DIR": str(tmp_path / "scripts"),
    }, now=REPORT_NOW)

    assert "Issues" in html
    assert "No run in this report period" in html


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

    _write_job_meta(tmp_path, "photos_local", name="Photos - Local", backup_type="photos", location="local")
    _write_job_meta(tmp_path, "flash_usb", name="Flash - USB", backup_type="flash", location="usb")
    _write_job_meta(tmp_path, "appdata_storagebox", name="Appdata - Storagebox", backup_type="appdata", location="storagebox")
    html = _build_html_report({"STATUS_DIR": str(status_dir), "BACKUP_SCRIPTS_DIR": str(tmp_path)}, now=REPORT_NOW)

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

    html = _build_html_report({"STATUS_DIR": str(status_dir), "BACKUP_SCRIPTS_DIR": str(tmp_path)}, now=REPORT_NOW)

    assert "Log Details" not in html
    assert "Kein Mail-Versand" not in html
