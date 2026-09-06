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


from restore_identity_support import JOB_ID


def _make_job(root: Path) -> None:
    from job_model import new_job_defaults
    directory = root / 'config' / 'jobs'; directory.mkdir(parents=True)
    job = {**new_job_defaults(), 'job_id': JOB_ID, 'name': 'Flash', 'archive_prefixes': ['flash'],
           'legacy_job_keys': [], 'repository_key': 'repo_flash', 'source_paths': [str(root)],
           'restore_test_policy': {'mode': 'scheduled', 'interval_days': 30, 'level': 2}}
    (directory / f'{JOB_ID}.json').write_text(json.dumps(job))
    (directory.parent/'repositories.json').write_text(json.dumps({'schema_version':1,'repositories':[
        {'repository_key':'repo_flash','storage_key':'local','relative_path':'flash','encryption':'none', 'job_ids':[JOB_ID], 'source_job_ids':[JOB_ID]}]}))
    (directory.parent/'storages.json').write_text(json.dumps({'schema_version':1,'storages':[
        {'storage_key':'local','storage_type':'local','location':'local','base_path':str(root/'repos')}]}))


def test_policy_contract_rejects_bad_interval(tmp_path: Path):
    _make_job(tmp_path)
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "RESTORE_TEST_INTERVAL_DAYS": "30"}
    with pytest.raises(ValueError, match="interval_days"):
        update_restore_test_policy(cfg, JOB_ID, {"mode": "scheduled", "interval_days": 0, "level": 2})


def test_policy_contract_rejects_bad_level(tmp_path: Path):
    _make_job(tmp_path)
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "RESTORE_TEST_INTERVAL_DAYS": "30"}
    with pytest.raises(ValueError, match="level"):
        update_restore_test_policy(cfg, JOB_ID, {"mode": "scheduled", "interval_days": 7, "level": 9})


def test_policy_contract_accepts_valid_payload(tmp_path: Path):
    _make_job(tmp_path)
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "RESTORE_TEST_INTERVAL_DAYS": "30"}
    out = update_restore_test_policy(cfg, JOB_ID, {"mode": "manual_only", "interval_days": 7, "level": 1})
    assert out["saved"] is True
    assert out["policy"]["mode"] == "manual_only"
    assert out["policy"]["interval_days"] == 7
    assert out["policy"]["level"] == 1


def test_scheduled_plan_keeps_failed_manual_result_due(tmp_path: Path):
    _make_job(tmp_path)
    restore_dir = tmp_path / "restore-status"
    restore_dir.mkdir(parents=True)
    recent = datetime.now() - timedelta(hours=2)
    (restore_dir / f"{JOB_ID}.test").write_text(json.dumps({
        "job_id": JOB_ID,
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

    assert row["job_id"] == JOB_ID
    assert row["last_test_result"] == "failed"
    assert row["is_overdue"] is True
    assert row["next_due_at"] == recent.strftime("%Y-%m-%d %H:%M:%S")
    assert plan["summary"]["overdue"] == 1
