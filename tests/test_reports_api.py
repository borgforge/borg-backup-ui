from job_fixtures import identified_job, job_id, write_job
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from reports_api import get_report_data, get_report_jobs  # noqa: E402


def _write_status(path: Path, **overrides) -> None:
    payload = {
        "timestamp": "2026-08-28 09:00:00",
        "status": "success",
        "duration_seconds": 42,
        "original_size": 1000,
        "compressed_size": 700,
        "deduplicated_size": 500,
        "repository_size": 2000,
        "files_count": 10,
    }
    payload.update(overrides)
    write_job(path.parent.parent, payload["backup_type"] + "_" + payload["location"])
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_reports_parse_status_files_for_multi_underscore_job_keys(tmp_path: Path) -> None:
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    _write_status(
        status_dir / "2026-08-28_09-00-00_borg_backup_taeglich_backuppf1_local.status",
        job_id=job_id("borg_backup_taeglich_backuppf1_local"), backup_type="borg_backup_taeglich_backuppf1", location="local"
    )

    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "STATUS_DIR": str(status_dir)}

    jobs = get_report_jobs(config)
    assert [job["key"] for job in jobs] == [job_id("borg_backup_taeglich_backuppf1_local")]
    assert jobs[0]["backup_type"] == "borg_backup_taeglich_backuppf1"
    assert jobs[0]["location"] == "local"

    data = get_report_data(config, job_id("borg_backup_taeglich_backuppf1_local"))
    assert data["run_count"] == 1
    assert data["success_count"] == 1
    assert data["monthly_status"] == [
        {"month": "2026-08", "success": 1, "warning": 0, "error": 0}
    ]


def test_reports_parse_smb_status_files(tmp_path: Path) -> None:
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    _write_status(
        status_dir / "2026-08-28_09-00-00_methusalix_backup_taeglich_smb.status",
        job_id=job_id("methusalix_backup_taeglich_smb"), backup_type="methusalix_backup_taeglich", location="smb"
    )

    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "STATUS_DIR": str(status_dir)}

    jobs = get_report_jobs(config)
    assert [job["key"] for job in jobs] == [job_id("methusalix_backup_taeglich_smb")]
    assert jobs[0]["backup_type"] == "methusalix_backup_taeglich"
    assert jobs[0]["location"] == "smb"

    data = get_report_data(config, job_id("methusalix_backup_taeglich_smb"))
    assert data["run_count"] == 1
    assert data["success_count"] == 1
