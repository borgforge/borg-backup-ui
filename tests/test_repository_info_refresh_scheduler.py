import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from repositories_api import (  # noqa: E402
    _compute_repository_info_next_run,
    get_repository_info_refresh_status,
    repository_info_refresh_settings,
    write_repository_store,
)


def _config(tmp_path: Path) -> dict:
    return {
        "BACKUP_SCRIPTS_DIR": str(tmp_path),
        "BACKUP_CONF_SCHEMA_FILE": str(ROOT / "runtime" / "config" / "backup.conf.example"),
    }


def _write_conf(tmp_path: Path, lines: str) -> None:
    conf_dir = tmp_path / "config"
    conf_dir.mkdir(parents=True, exist_ok=True)
    (conf_dir / "backup.conf").write_text(lines, encoding="utf-8")


def test_repository_info_refresh_settings_are_read_from_backup_conf(tmp_path: Path):
    config = _config(tmp_path)
    _write_conf(tmp_path, "\n".join([
        'GLOBAL_DATA_DIR="/mnt/user/borg-backup-ui"',
        'REPOSITORY_INFO_REFRESH_ENABLED="false"',
        'REPOSITORY_INFO_REFRESH_INTERVAL_HOURS="168"',
        'REPOSITORY_INFO_REFRESH_RETRY_HOURS="6"',
    ]))

    settings = repository_info_refresh_settings(config)

    assert settings == {"enabled": False, "interval_hours": 168, "retry_hours": 6}


def test_repository_info_refresh_status_does_not_run_borg(tmp_path: Path, monkeypatch):
    config = _config(tmp_path)
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_appdata",
        "display_name": "Appdata",
        "repository_name": "appdata",
        "storage_key": "storage_disk1",
        "relative_path": "appdata",
        "storage_name": "Disk 1",
        "last_info_refresh_at": "2026-07-24T07:00:00Z",
        "last_info_refresh_status": "success",
        "repository_stats": {"archives_count": 7},
    }]})

    def fail_borg(*_args, **_kwargs):
        raise AssertionError("settings status must not execute borg")

    monkeypatch.setattr(subprocess, "run", fail_borg)

    status = get_repository_info_refresh_status(config)

    assert status["repository_count"] == 1
    assert status["details"][0]["display_name"] == "Appdata"
    assert status["counts"]["success"] == 1


def test_next_global_repository_info_refresh_uses_latest_cached_info(tmp_path: Path):
    config = _config(tmp_path)
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_flash",
        "display_name": "Flash",
        "storage_key": "storage_local",
        "relative_path": "flash",
        "last_info_refresh_at": "2026-07-24T07:00:00Z",
        "last_info_refresh_status": "success",
        "repository_stats": {"archives_count": 3},
    }]})
    now = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)

    next_run = _compute_repository_info_next_run(
        config,
        {"enabled": True, "interval_hours": 24, "retry_hours": 1},
        {},
        now,
    )

    assert next_run and next_run.isoformat() == "2026-07-25T07:00:00+00:00"


def test_next_global_repository_info_refresh_is_due_when_stats_are_missing(tmp_path: Path):
    config = _config(tmp_path)
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_new",
        "display_name": "New",
        "storage_key": "storage_local",
        "relative_path": "new",
        "last_info_refresh_at": "",
        "last_info_refresh_status": "",
        "repository_stats": {},
    }]})
    now = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)

    next_run = _compute_repository_info_next_run(
        config,
        {"enabled": True, "interval_hours": 24, "retry_hours": 1},
        {},
        now,
    )

    assert next_run == now


def test_next_global_repository_info_refresh_uses_retry_after_failed_run(tmp_path: Path):
    config = _config(tmp_path)
    now = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)

    next_run = _compute_repository_info_next_run(
        config,
        {"enabled": True, "interval_hours": 24, "retry_hours": 6},
        {
            "last_run_at": "2026-07-24T07:00:00Z",
            "last_result": {"checked": 3, "refreshed": 2, "failed": 1, "deferred": 0},
        },
        now,
    )

    assert next_run and next_run.isoformat() == "2026-07-24T13:00:00+00:00"
