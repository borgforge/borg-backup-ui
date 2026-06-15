import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from api.restore_tests_api import build_restore_verification_map


class RestoreVerificationTests(unittest.TestCase):
    def _cfg(self, base: Path) -> dict:
        return {
            "STATUS_DIR": str(base / "status"),
            "RESTORE_TEST_STATUS_DIR": str(base / "restore-status"),
            "RESTORE_TEST_INTERVAL_DAYS": "30",
        }

    def _write_test(self, base: Path, job_key: str, result: str, test_date: datetime) -> None:
        d = base / "restore-status"
        d.mkdir(parents=True, exist_ok=True)
        payload = {
            "test_result": result,
            "test_level": 2,
            "test_duration_seconds": 12,
            "test_date": test_date.strftime("%Y-%m-%d %H:%M:%S"),
        }
        (d / f"{job_key}.test").write_text(json.dumps(payload), encoding="utf-8")

    def test_policy_off_returns_not_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            jobs = [{"key": "a_local", "location": "local", "restore_test_policy": {"mode": "off"}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("not_required", out["a_local"]["status"])

    def test_missing_report_returns_never(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            jobs = [{"key": "b_local", "location": "local", "restore_test_policy": {"mode": "scheduled", "validity_days": 30}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("never", out["b_local"]["status"])

    def test_success_within_validity_is_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_test(base, "c_local", "success", datetime.now() - timedelta(days=2))
            jobs = [{"key": "c_local", "location": "local", "restore_test_policy": {"mode": "scheduled", "validity_days": 10}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("verified", out["c_local"]["status"])

    def test_success_expired_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_test(base, "d_local", "success", datetime.now() - timedelta(days=15))
            jobs = [{"key": "d_local", "location": "local", "restore_test_policy": {"mode": "scheduled", "validity_days": 10}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("stale", out["d_local"]["status"])
            self.assertTrue(out["d_local"]["is_overdue"])

    def test_failed_report_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_test(base, "e_local", "failed", datetime.now())
            jobs = [{"key": "e_local", "location": "local", "restore_test_policy": {"mode": "scheduled", "validity_days": 30}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("failed", out["e_local"]["status"])

    def test_manual_only_success_stays_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_test(base, "f_local", "success", datetime.now() - timedelta(days=120))
            jobs = [{"key": "f_local", "location": "local", "restore_test_policy": {"mode": "manual_only", "validity_days": 10}}]
            out = build_restore_verification_map(self._cfg(base), jobs)
            self.assertEqual("verified", out["f_local"]["status"])
            self.assertFalse(out["f_local"]["is_overdue"])


if __name__ == "__main__":
    unittest.main()

