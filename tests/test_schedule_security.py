from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import schedule_api  # noqa: E402


def test_save_schedule_rejects_invalid_job_key_before_crontab(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(schedule_api, "_known_job_keys", lambda _cfg: {"appdata_local"})
    monkeypatch.setattr(schedule_api.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(ValueError, match="Invalid job key"):
        schedule_api.save_schedule(
            {"BACKUP_SCRIPTS_DIR": str(tmp_path)},
            "appdata_local'; touch /tmp/pwned; '",
            "0 2 * * *",
            True,
        )

    assert calls == []


def test_save_schedule_rejects_unknown_job_key(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(schedule_api, "_known_job_keys", lambda _cfg: {"appdata_local"})
    monkeypatch.setattr(schedule_api.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(ValueError, match="Unknown job key"):
        schedule_api.save_schedule(
            {"BACKUP_SCRIPTS_DIR": str(tmp_path)},
            "photos_local",
            "0 2 * * *",
            True,
        )

    assert calls == []


def test_apply_all_schedules_writes_quoted_shell_wrapper(monkeypatch, tmp_path: Path):
    written = {}

    def fake_run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 1, "", "")
        if cmd == ["crontab", "-"]:
            written["input"] = kwargs.get("input", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)

    monkeypatch.setattr(schedule_api, "_known_job_keys", lambda _cfg: {"appdata_local"})
    monkeypatch.setattr(schedule_api.subprocess, "run", fake_run)
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "PORT": "8765"}
    schedule_api.write_schedules(cfg, {"appdata_local": {"cron": "0 2 * * *", "enabled": True}})
    schedule_api.apply_all_schedules(cfg)

    cron_text = written["input"]
    assert "/bin/sh -c" in cron_text
    assert "touch /tmp/pwned" not in cron_text
    assert "data-binary" in cron_text
    assert "job_key" in cron_text
    assert "appdata_local" in cron_text
    assert f"token_file={tmp_path}/config/.api-token" in cron_text


def test_restore_test_schedule_is_allowed_without_job_lookup(monkeypatch, tmp_path: Path):
    written = {}

    def fake_run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 1, "", "")
        if cmd == ["crontab", "-"]:
            written["input"] = kwargs.get("input", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)

    monkeypatch.setattr(schedule_api, "_known_job_keys", lambda _cfg: set())
    monkeypatch.setattr(schedule_api.subprocess, "run", fake_run)

    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    schedule_api.save_schedule(cfg, "restore_test", "0 3 * * *", True)

    assert "/api/restore-tests/run" in written["input"]
    assert '{"scheduled":true}' in written["input"]


def test_save_schedule_reports_crontab_install_failure(monkeypatch, tmp_path: Path):
    def fake_run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd == ["crontab", "-"]:
            return subprocess.CompletedProcess(cmd, 1, "", "permission denied")
        raise AssertionError(cmd)

    monkeypatch.setattr(schedule_api, "_known_job_keys", lambda _cfg: {"appdata_local"})
    monkeypatch.setattr(schedule_api.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Schedule saved but could not be applied"):
        schedule_api.save_schedule(
            {"BACKUP_SCRIPTS_DIR": str(tmp_path)},
            "appdata_local",
            "0 2 * * *",
            True,
        )

    assert "appdata_local" in (tmp_path / "config" / "schedules.json").read_text(encoding="utf-8")


def test_apply_all_schedules_reports_crontab_read_failure(monkeypatch, tmp_path: Path):
    def fake_run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 2, "", "crontab unavailable")
        raise AssertionError(cmd)

    monkeypatch.setattr(schedule_api, "_known_job_keys", lambda _cfg: {"appdata_local"})
    monkeypatch.setattr(schedule_api.subprocess, "run", fake_run)

    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    schedule_api.write_schedules(cfg, {"appdata_local": {"cron": "0 2 * * *", "enabled": True}})

    with pytest.raises(RuntimeError, match="Could not read crontab"):
        schedule_api.apply_all_schedules(cfg)
