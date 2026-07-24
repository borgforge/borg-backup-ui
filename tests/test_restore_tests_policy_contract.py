import json
from datetime import datetime, timedelta
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from api.restore_tests_api import list_restore_test_plan, update_restore_test_policy


def _make_job(root: Path, key: str = "flash_local") -> None:
    jobs_dir = root / "config" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "key": key,
        "job_key": key,
        "name": "Flash",
        "display_name": "Flash",
        "location": "local",
        "backup_type": "flash",
        "repository_key": "repo_flash_local",
        "enabled": True,
        "restore_test_policy": {"mode": "scheduled", "interval_days": 30, "level": 2},
    }
    (jobs_dir / f"{key}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_policy_contract_rejects_bad_interval(tmp_path: Path):
    _make_job(tmp_path)
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "RESTORE_TEST_INTERVAL_DAYS": "30"}
    with pytest.raises(ValueError, match="interval_days"):
        update_restore_test_policy(cfg, "flash_local", {"mode": "scheduled", "interval_days": 0, "level": 2})


def test_policy_contract_rejects_bad_level(tmp_path: Path):
    _make_job(tmp_path)
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "RESTORE_TEST_INTERVAL_DAYS": "30"}
    with pytest.raises(ValueError, match="level"):
        update_restore_test_policy(cfg, "flash_local", {"mode": "scheduled", "interval_days": 7, "level": 9})


def test_policy_contract_accepts_valid_payload(tmp_path: Path):
    _make_job(tmp_path)
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "RESTORE_TEST_INTERVAL_DAYS": "30"}
    out = update_restore_test_policy(cfg, "flash_local", {"mode": "manual_only", "interval_days": 7, "level": 1})
    assert out["saved"] is True
    assert out["policy"]["mode"] == "manual_only"
    assert out["policy"]["interval_days"] == 7
    assert out["policy"]["level"] == 1


def test_scheduled_plan_keeps_failed_manual_result_due(tmp_path: Path):
    _make_job(tmp_path)
    restore_dir = tmp_path / "restore-status"
    restore_dir.mkdir(parents=True)
    recent = datetime.now() - timedelta(hours=2)
    (restore_dir / "flash_local.test").write_text(json.dumps({
        "test_result": "failed",
        "test_date": recent.strftime("%Y-%m-%d %H:%M:%S"),
    }), encoding="utf-8")
    cfg = {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "STATUS_DIR": str(tmp_path / "status"),
        "RESTORE_TEST_STATUS_DIR": str(restore_dir),
        "RESTORE_TEST_INTERVAL_DAYS": "30",
    }

    plan = list_restore_test_plan(cfg)
    row = plan["jobs"][0]

    assert row["job_key"] == "flash_local"
    assert row["last_test_result"] == "failed"
    assert row["is_overdue"] is True
    assert row["next_due_at"] == recent.strftime("%Y-%m-%d %H:%M:%S")
    assert plan["summary"]["overdue"] == 1
