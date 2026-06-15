import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from api.restore_tests_api import update_restore_test_policy


def _make_job(root: Path, key: str = "flash_local") -> None:
    jobs_dir = root / "config" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "job_key": key,
        "name": "Flash",
        "location": "local",
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
