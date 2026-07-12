import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
for path in (ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import factory_reset_api
import factory_reset_worker
from factory_reset_worker import perform_reset


def _status(tmp_path: Path) -> dict:
    return {
        "ok": True,
        "server_name": "Tower",
        "configuration_root": str(tmp_path / "config-root"),
        "operational_data_root": str(tmp_path / "data-root"),
        "repository_blockers": [],
        "operation_blockers": [],
        "allowed": True,
        "confirmation_phrase": "FACTORY RESET",
    }


def _payload() -> dict:
    return {
        "server_name": "Tower",
        "confirmation_phrase": "FACTORY RESET",
        "ack_configuration": True,
        "ack_operational_data": True,
        "ack_secrets": True,
        "ack_repositories_preserved": True,
    }


def test_factory_reset_requires_every_confirmation(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(factory_reset_api, "factory_reset_status", lambda config: _status(tmp_path))
    payload = _payload()
    payload["ack_secrets"] = False

    with pytest.raises(ValueError, match="risk confirmations"):
        factory_reset_api.validate_factory_reset_request({}, payload)


@pytest.mark.parametrize(
    "path",
    [Path("/mnt"), Path("/mnt/user"), Path("/mnt/cache"), Path("/mnt/disk1"), Path("/mnt/backup")],
)
def test_factory_reset_rejects_broad_operational_roots(path: Path):
    with pytest.raises(factory_reset_api.FactoryResetBlocked):
        factory_reset_api._validate_operational_root(path)


def test_factory_reset_accepts_dedicated_operational_root():
    factory_reset_api._validate_operational_root(Path("/mnt/user/borg-backup-ui"))


def test_factory_reset_blocks_managed_repositories_inside_deleted_roots(tmp_path: Path, monkeypatch):
    status = _status(tmp_path)
    status["repository_blockers"] = [{"display_name": "Appdata", "path": str(tmp_path / "data-root" / "repo")}]
    status["allowed"] = False
    monkeypatch.setattr(factory_reset_api, "factory_reset_status", lambda config: status)

    with pytest.raises(factory_reset_api.FactoryResetBlocked, match="Appdata"):
        factory_reset_api.validate_factory_reset_request({}, _payload())


def test_worker_removes_state_but_recreates_first_install_layout(tmp_path: Path):
    plugin_dir = tmp_path / "plugin"
    example = plugin_dir / "runtime" / "config" / "backup.conf.example"
    example.parent.mkdir(parents=True)
    default_data = tmp_path / "default-data"
    example.write_text(f'GLOBAL_DATA_DIR="{default_data}"\n', encoding="utf-8")
    config_root = tmp_path / "config-root"
    data_root = tmp_path / "data-root"
    (config_root / "config" / "jobs").mkdir(parents=True)
    (config_root / "config" / "jobs" / "old.json").write_text("{}", encoding="utf-8")
    data_root.mkdir()
    (data_root / "old.log").write_text("old", encoding="utf-8")

    result = perform_reset({
        "configuration_root": str(config_root),
        "operational_data_root": str(data_root),
        "plugin_dir": str(plugin_dir),
    }, production=False)

    assert not (config_root / "config" / "jobs" / "old.json").exists()
    assert (config_root / "config" / "backup.conf").is_file()
    assert not (data_root / "old.log").exists()
    assert (default_data / "logs").is_dir()
    assert (default_data / "restore-status").is_dir()
    assert result["initialized_operational_data_root"] == str(default_data)


def test_worker_removes_job_and_weekly_report_cron_blocks(monkeypatch):
    calls = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    existing = """0 1 * * * echo keep
# --- BORG-BACKUP-UI BEGIN ---
0 3 * * * run-job
# --- BORG-BACKUP-UI END ---
# --- BORG-BACKUP-UI WEEKLY-REPORT BEGIN ---
0 9 * * 1 run-report
# --- BORG-BACKUP-UI WEEKLY-REPORT END ---
"""

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return Result(stdout=existing if command == ["crontab", "-l"] else "")

    monkeypatch.setattr(factory_reset_worker.subprocess, "run", run)
    factory_reset_worker.remove_plugin_cron_blocks()

    assert calls[-1][0] == ["crontab", "-"]
    assert calls[-1][1]["input"] == "0 1 * * * echo keep\n"
