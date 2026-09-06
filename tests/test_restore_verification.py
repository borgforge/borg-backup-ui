import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from restore_identity_support import JOB_ID

from api.restore_tests_api import build_restore_verification_map


class RestoreVerificationTests(unittest.TestCase):
    def _cfg(self, base: Path) -> dict:
        return {
            "STATUS_DIR": str(base / "status"),
            "RESTORE_TEST_STATUS_DIR": str(base / "restore-status"),
            "RESTORE_TEST_INTERVAL_DAYS": "30",
        }

    def _write_test(self, base: Path, job_key: str, result: str, test_date: datetime, extra: dict | None = None) -> None:
        d = base / "restore-status"
        d.mkdir(parents=True, exist_ok=True)
        payload = {
            "job_id": JOB_ID, "repository_snapshot": "/repo", "archive_prefix_snapshot": "prefix",
            "test_result": result,
            "test_level": 2,
            "test_duration_seconds": 12,
            "test_date": test_date.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if extra:
            payload.update(extra)
        (d / f"{job_key}.test").write_text(json.dumps(payload), encoding="utf-8")

    def test_policy_off_returns_not_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            jobs = [{"job_id": JOB_ID, "repo_path": "/repo", "archive_prefixes": ["prefix"], "location": "local", "restore_test_policy": {"mode": "off"}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("not_required", out[JOB_ID]["status"])

    def test_missing_report_returns_never(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            jobs = [{"job_id": JOB_ID, "repo_path": "/repo", "archive_prefixes": ["prefix"], "location": "local", "restore_test_policy": {"mode": "scheduled", "validity_days": 30}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("never", out[JOB_ID]["status"])

    def test_success_within_validity_is_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_test(base, JOB_ID, "success", datetime.now() - timedelta(days=2))
            jobs = [{"job_id": JOB_ID, "repo_path": "/repo", "archive_prefixes": ["prefix"], "location": "local", "restore_test_policy": {"mode": "scheduled", "validity_days": 10}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("verified", out[JOB_ID]["status"])

    def test_success_expired_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_test(base, JOB_ID, "success", datetime.now() - timedelta(days=15))
            jobs = [{"job_id": JOB_ID, "repo_path": "/repo", "archive_prefixes": ["prefix"], "location": "local", "restore_test_policy": {"mode": "scheduled", "validity_days": 10}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("stale", out[JOB_ID]["status"])
            self.assertTrue(out[JOB_ID]["is_overdue"])

    def test_failed_report_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_test(base, JOB_ID, "failed", datetime.now())
            jobs = [{"job_id": JOB_ID, "repo_path": "/repo", "archive_prefixes": ["prefix"], "location": "local", "restore_test_policy": {"mode": "scheduled", "validity_days": 30}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("failed", out[JOB_ID]["status"])

    def test_failed_report_exposes_failure_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_test(base, JOB_ID, "failed", datetime.now(), {
                "failure_code": "RT_NETWORK_ERROR",
                "failure_hint": "Network error or SSH connection failed",
                "error_analysis": {"error_category": "network"},
            })
            jobs = [{"job_id": JOB_ID, "repo_path": "/repo", "archive_prefixes": ["prefix"], "location": "storagebox", "restore_test_policy": {"mode": "scheduled", "validity_days": 30}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("failed", out[JOB_ID]["status"])
            self.assertEqual("RT_NETWORK_ERROR", out[JOB_ID]["failure_code"])
            self.assertEqual("Network error or SSH connection failed", out[JOB_ID]["failure_hint"])
            self.assertEqual("network", out[JOB_ID]["failure_category"])

    def test_manual_only_success_stays_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_test(base, JOB_ID, "success", datetime.now() - timedelta(days=120))
            jobs = [{"job_id": JOB_ID, "repo_path": "/repo", "archive_prefixes": ["prefix"], "location": "local", "restore_test_policy": {"mode": "manual_only", "validity_days": 10}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("verified", out[JOB_ID]["status"])
            self.assertFalse(out[JOB_ID]["is_overdue"])


if __name__ == "__main__":
    unittest.main()
