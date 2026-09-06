from __future__ import annotations

import json
import pytest
from status_view_fixture_support import job_id_for, write_job, status_identity
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT, ROOT / "api", ROOT / "runtime" / "lib"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))
if str(ROOT / "runtime") not in sys.path:
    sys.path.insert(0, str(ROOT / "runtime"))

import jobs_api
from api.auth_store import (
    homepage_widget_token_status,
    read_homepage_widget_token,
    revoke_homepage_widget_token,
    rotate_homepage_widget_token,
)
import api.homepage_widget_api as homepage_widget_api
import api.unraid_dashboard_widget as unraid_dashboard_widget
from borg_backup_ui import BackupUIHandler


@pytest.fixture(autouse=True)
def canonical_status_fixtures(monkeypatch, tmp_path):
    original = unraid_dashboard_widget._read_status_file_data
    def read(config):
        config.setdefault('BACKUP_SCRIPTS_DIR', str(tmp_path))
        for path in Path(config.get('STATUS_DIR', tmp_path / 'status')).glob('*.status'):
            raw = json.loads(path.read_text())
            if 'backup_type' in raw and 'location' in raw:
                label = raw['backup_type'] + '_' + raw['location']
                write_job(tmp_path, label, name=raw['backup_type'], location=raw['location'])
        return original(config)
    monkeypatch.setattr(unraid_dashboard_widget, '_read_status_file_data', read)
    monkeypatch.setattr('config_api.read_expanded_conf', lambda cfg: {})
    monkeypatch.setattr('jobs_api.get_all_runtime_states', lambda cfg: {})


def _handler(config: dict, headers: dict | None = None) -> BackupUIHandler:
    handler = BackupUIHandler.__new__(BackupUIHandler)
    handler.config = config
    handler.headers = headers or {}
    handler.command = "GET"
    return handler


def test_homepage_widget_token_lifecycle_uses_restricted_permissions(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    assert homepage_widget_token_status(config) == {"configured": False}
    first = rotate_homepage_widget_token(config)
    token_file = tmp_path / "config" / ".homepage-widget-token"

    assert len(first) == 64
    assert read_homepage_widget_token(config) == first
    assert homepage_widget_token_status(config) == {"configured": True}
    assert os.stat(token_file).st_mode & 0o777 == 0o600

    second = rotate_homepage_widget_token(config)
    assert second != first
    assert read_homepage_widget_token(config) == second
    assert revoke_homepage_widget_token(config) is True
    assert revoke_homepage_widget_token(config) is False
    assert homepage_widget_token_status(config) == {"configured": False}


def test_homepage_widget_token_is_scoped_to_widget_endpoint(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    token = rotate_homepage_widget_token(config)
    handler = _handler(config, {"X-Borg-Widget-Token": token})
    handler._auth_store_failure = lambda: ""
    handler._ui_auth_enabled = lambda: False
    handler._is_ui_session_valid = lambda: False
    handler._get_api_token = lambda: "general-api-token"
    handler._get_current_role = lambda: "viewer"
    errors = []
    handler._send_api_error = lambda status, code, message, *, request_id: errors.append(
        (status, code, message, request_id)
    )

    assert handler._authorize_api_request("/api/widget/summary", "req-widget") is True
    assert handler._authorize_api_request("/api/status", "req-status") is False
    assert errors[-1][0:2] == (401, "unauthorized")


def test_general_api_token_cannot_replace_widget_token(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    rotate_homepage_widget_token(config)
    handler = _handler(config, {"X-API-Token": "general-api-token"})
    handler._auth_store_failure = lambda: ""
    handler._ui_auth_enabled = lambda: False
    handler._is_ui_session_valid = lambda: False
    errors = []
    handler._send_api_error = lambda status, code, message, *, request_id: errors.append(
        (status, code, message, request_id)
    )

    assert handler._authorize_api_request("/api/widget/summary", "req-widget") is False
    assert errors[-1][0:2] == (401, "widget_unauthorized")


def test_homepage_widget_summary_is_stable_and_redacted(monkeypatch):
    jobs = [
        {"job_id": "ee05893e-0b67-4d45-b92d-53fa70884fbf", "name": "Flash", "display_name": "Flash - Local", "enabled": True},
        {"job_id": "52d54416-94ee-47c4-aee0-e91a3ecca853", "name": "Appdata", "display_name": "Appdata - USB", "enabled": True},
        {"job_id": "9a664f74-bee4-4c4f-b4fc-337fd9516f9d", "name": "Photos", "display_name": "Photos - Local", "enabled": False},
    ]
    latest = [
        {"job_id": "ee05893e-0b67-4d45-b92d-53fa70884fbf", "status": "success", "timestamp": "2026-07-14 09:00:00"},
        {"job_id": "52d54416-94ee-47c4-aee0-e91a3ecca853", "status": "warning", "timestamp": "2026-07-14 10:00:00"},
    ]
    from status_read_model import summarize
    rows = [{**job, **next((row for row in latest if row['job_id'] == job['job_id']), {}),
             'running':index == 0, 'backup_overdue':index == 1} for index,job in enumerate(jobs)]
    monkeypatch.setattr('status_api.get_status_data', lambda *_args, **_kwargs: {'backups':rows,'summary':summarize(rows)})
    monkeypatch.setattr('config_api.read_expanded_conf', lambda _config: {})
    monkeypatch.setattr(
        homepage_widget_api,
        "_restore_summary",
        lambda *_args: {"configured": 2, "verified": 1, "failed": 0, "overdue": 1, "never": 0},
    )
    monkeypatch.setattr(
        jobs_api,
        "get_all_runtime_states",
        lambda _config: {"ee05893e-0b67-4d45-b92d-53fa70884fbf": {"running": True, "log_file": "/secret/job.log"}},
    )

    result = homepage_widget_api.build_homepage_widget_summary(
        {}, now=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    )

    assert result == {
        "schema_version": 1,
        "generated_at": "2026-07-14T12:00:00Z",
        "status": {"state": "active", "label": "Backup running", "severity": 1},
        "display": {
            "backups": "0/2 successful",
            "restore_tests": "1/2 verified",
            "attention": "2",
            "active": "Flash",
        },
        "backups": {
            "total": 3,
            "enabled": 2,
            "disabled": 1,
            "successful": 0,
            "warning": 1,
            "failed": 0,
            "skipped": 0,
            "never": 0,
            "unknown": 0,
            "overdue": 1,
        },
        "restore_tests": {"configured": 2, "verified": 1, "failed": 0, "overdue": 1, "never": 0},
        "active": {"count": 1, "jobs": ["Flash"], "job_ids": [job_id_for("flash_local")]},
    }

    serialized = json.dumps(result).lower()
    for forbidden in (
        "/mnt/",
        "ssh://",
        "passphrase",
        "secret",
        "log_file",
        "error_message",
        "repository_path",
        "username",
    ):
        assert forbidden not in serialized


def test_homepage_widget_module_does_not_start_external_processes():
    source = (ROOT / "api" / "homepage_widget_api.py").read_text(encoding="utf-8")

    assert "subprocess" not in source
    assert "Popen" not in source
    assert "borg info" not in source.lower()


def test_unraid_dashboard_widget_cache_is_flash_safe_and_redacted(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    config = {"UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file)}
    status = {
        "summary": {"success": 1, "warning": 1, "skipped": 0, "error": 0},
        "backups": [
            {
                "job_id": "e60e4849-060b-4d3d-9130-d85bbd9827c4",
                "backup_type": "appdata",
                "location": "local",
                "status": "success",
                "timestamp": "2026-08-08 09:00:00",
                "time_ago": "vor 2 Stunden",
                "duration_formatted": "3 Min.",
                "repo_path": "/mnt/user/private",
                "error_message": "secret details",
                "restore_verification_status": "verified",
            }
        ],
    }
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_read_jobs",
        lambda _config, _backups: [
            {
                "job_id": "e60e4849-060b-4d3d-9130-d85bbd9827c4",
                "display_name": "Appdata - Lokal",
                "enabled": True,
                "running": False,
                "restore_verification_status": "verified",
            }
        ],
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_repository_summary",
        lambda _config: {"online": 2, "total": 3},
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_next_backups",
        lambda *_args: [{"name": "Appdata - Lokal", "time": "Today 09:00"}],
    )

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_cache(
        config,
        status,
        app_version="2026.08.09.1200",
        now=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert cache_file.exists()
    assert os.stat(cache_file).st_mode & 0o777 == 0o600
    assert result["schema_version"] == 1
    assert result["app_version"] == "2026.08.09.1200"
    assert result["jobs"]["successful"] == 1
    assert result["jobs"]["warnings"] == 0
    assert result["jobs"]["items"] == [
        {
            "job_id": "e60e4849-060b-4d3d-9130-d85bbd9827c4",
            "name": "Appdata - Lokal",
            "enabled": True,
            "running": False,
            "run_id": "",
            "legacy_status": False,
            "last_status": "success",
            "last_timestamp": "2026-08-08 09:00:00",
            "backup_overdue": False,
            "backup_overdue_state": "",
            "backup_overdue_after": "",
            "backup_overdue_expected_run": "",
            "backup_overdue_next_run": "",
            "restore_verification_status": "verified",
            "restore_verification_reason": "",
            "restore_verification_valid_until": "",
            "restore_verification_is_overdue": False,
        }
    ]
    assert result["repositories"] == {"online": 2, "total": 3}
    assert result["latest_backup"]["name"] == "Appdata - Lokal"
    assert result["restore_proof"] == {
        "configured": 1,
        "verified": 1,
        "failed": 0,
        "overdue": 0,
        "open": 0,
    }

    serialized = cache_file.read_text(encoding="utf-8").lower()
    for forbidden in ("/mnt/", "secret", "repo_path", "error_message", "passphrase"):
        assert forbidden not in serialized


def test_unraid_dashboard_widget_status_file_cache_marks_overdue_jobs(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    snapshot_file = tmp_path / "weekly-snapshots.json"
    config = {
        "UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file),
        "STATUS_DIR": str(status_dir),
        "SNAPSHOT_FILE": str(snapshot_file),
        "NOTIFY_BACKUP_OVERDUE_TOLERANCE_HOURS": "1",
    }
    (status_dir / "2026-08-09_12-00-00_flash_local.status").write_text(
        json.dumps({
            "backup_type": "flash",
            "job_id": job_id_for("flash_local"),
            "location": "local",
            "timestamp": "2026-08-09 12:00:00",
            "duration_seconds": 33,
            "status": "success",
            "exit_code": 0,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr("schedule_api.get_schedules", lambda _config: {
        "ee05893e-0b67-4d45-b92d-53fa70884fbf": {"enabled": True, "cron": "0 12 * * *"},
    })
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_read_jobs",
        lambda _config, _backups: [
            {
                "job_id": "ee05893e-0b67-4d45-b92d-53fa70884fbf",
                "display_name": "Flash - Lokal",
                "enabled": True,
                "running": False,
                "restore_verification_status": "verified",
            }
        ],
    )
    monkeypatch.setattr(
        "jobs_api.list_jobs",
        lambda _config, _context: [
            {
                "job_id": "ee05893e-0b67-4d45-b92d-53fa70884fbf",
                "display_name": "Flash - Lokal",
                "enabled": True,
            }
        ],
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_repository_summary",
        lambda _config: {"online": 1, "total": 1},
    )
    monkeypatch.setattr(unraid_dashboard_widget, "_next_backups", lambda *_args: [])

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_status_file_cache(
        config,
        app_version="2026.08.09.1300",
        now=datetime(2026, 8, 10, 13, 1, tzinfo=timezone.utc),
    )

    assert result["cache_state"] == "fresh"
    assert result["jobs"]["enabled"] == 1
    assert result["jobs"]["successful"] == 0
    assert result["jobs"]["warnings"] == 1
    assert result["status"]["state"] == "warning"
    assert result["jobs"]["items"][0]["backup_overdue"] is True
    assert result["jobs"]["items"][0]["backup_overdue_after"]
    assert result["latest_backup"]["name"] == "Flash - Lokal"
    assert result["latest_backup"]["status"] == "ok"
    assert cache_file.exists()
    assert not snapshot_file.exists()


def test_unraid_dashboard_widget_restore_proof_matches_dashboard_backup_rows(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    config = {"UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file)}
    status = {
        "summary": {"success": 14, "warning": 0, "skipped": 0, "error": 0},
        "backups": [
            {"job_id": "7692c3ad-3540-4b80-bc02-0b3aee66cd88", "status": "success", "restore_verification_status": "verified"},
            {"job_id": "3fc4ccfe-7458-40e2-80d9-9f71f30ff065", "status": "success", "restore_verification_status": "verified"},
            {"job_id": "8b5b9db0-c13d-4242-96c8-29aa364aa90c", "status": "success", "restore_verification_status": "verified"},
            {"job_id": "04efaf08-0f5a-4e74-a1c2-9d1ca6a48569", "status": "success", "restore_verification_status": "verified"},
            {"job_id": "2e22df35-67b5-4065-8aac-d5e5ee7675ff", "status": "success", "restore_verification_status": "not_required"},
        ],
    }
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_read_jobs",
        lambda _config, _backups: [
            {"job_id": "7692c3ad-3540-4b80-bc02-0b3aee66cd88", "display_name": "One", "enabled": True, "restore_verification_status": "verified"},
            {"job_id": "3fc4ccfe-7458-40e2-80d9-9f71f30ff065", "display_name": "Two", "enabled": True, "restore_verification_status": "verified"},
            {"job_id": "8b5b9db0-c13d-4242-96c8-29aa364aa90c", "display_name": "Three", "enabled": True, "restore_verification_status": "verified"},
            {"job_id": "04efaf08-0f5a-4e74-a1c2-9d1ca6a48569", "display_name": "Four", "enabled": True, "restore_verification_status": "verified"},
            {"job_id": "2e22df35-67b5-4065-8aac-d5e5ee7675ff", "display_name": "Not planned", "enabled": True, "restore_verification_status": "never"},
        ],
    )
    monkeypatch.setattr(unraid_dashboard_widget, "_repository_summary", lambda _config: {"online": 1, "total": 1})
    monkeypatch.setattr(unraid_dashboard_widget, "_next_backups", lambda *_args: [])

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_cache(
        config,
        status,
        app_version="2026.08.29.2235",
        now=datetime(2026, 8, 29, 22, 35, tzinfo=timezone.utc),
    )

    assert result["restore_proof"] == {
        "configured": 4,
        "verified": 4,
        "failed": 0,
        "overdue": 0,
        "open": 0,
    }
    assert result["jobs"]["items"][-1]["restore_verification_status"] == "not_required"


def test_restore_widgets_distinguish_open_target_proof_from_expired_validity(monkeypatch):
    proof_cases = [
        {'status':'stale', 'reason':'target_unknown', 'is_overdue':True},
        {'status':'stale', 'reason':'target_changed', 'is_overdue':False},
        {'status':'stale', 'reason':'test_date_unknown', 'is_overdue':False},
        {'status':'stale', 'reason':'validity_expired', 'is_overdue':True},
        {'status':'verified', 'reason':'within_validity', 'is_overdue':False},
    ]
    verification = {job_id_for('proof_'+str(i)):proof for i,proof in enumerate(proof_cases)}
    monkeypatch.setattr('restore_tests_api.build_restore_verification_map', lambda *a: verification)
    homepage = homepage_widget_api._restore_summary({}, [])
    assert homepage == {'configured':5, 'verified':1, 'failed':0, 'overdue':1, 'never':3}
    rows = [{'job_id':job_id, **{'restore_verification_'+key:value for key,value in proof.items()}}
            for job_id,proof in verification.items()]
    items = unraid_dashboard_widget._job_cache_items(rows, {row['job_id']:row for row in rows})
    assert [item['restore_verification_reason'] for item in items] == [proof['reason'] for proof in proof_cases]
    assert unraid_dashboard_widget._restore_proof_summary(items) == {
        'configured':5, 'verified':1, 'failed':0, 'overdue':1, 'open':3}


def test_unraid_dashboard_widget_repository_summary_counts_not_known_offline_as_online(monkeypatch):
    monkeypatch.setattr(
        "repositories_api.get_repository_info_refresh_status",
        lambda _config: {
            "repository_count": 13,
            "counts": {
                "success": 9,
                "warning": 2,
                "error": 0,
                "busy": 1,
                "pending": 1,
            },
        },
    )

    assert unraid_dashboard_widget._repository_summary({}) == {"online": 13, "total": 13}


def test_unraid_dashboard_widget_status_file_cache_keeps_live_owner_after_status_write(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    config = {
        "UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file),
        "STATUS_DIR": str(status_dir),
    }
    (status_dir / "2026-08-29_22-20-06_sonstiges_usb.status").write_text(
        json.dumps({
            "backup_type": "sonstiges",
            "job_id": job_id_for("sonstiges_usb"),
            "location": "usb",
            "timestamp": "2026-08-29 22:20:06",
            "duration_seconds": 183,
            "status": "success",
            "exit_code": 0,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_read_jobs",
        lambda _config, _backups: [
            {
                "job_id": "aa439b75-9a27-4c69-9c43-9275a1c43d14",
                "display_name": "Sonstiges - USB",
                "enabled": True,
                "running": True,
                "run_start_time": "2026-08-29 22:17:00",
                "restore_verification_status": "not_required",
            }
        ],
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_repository_summary",
        lambda _config: {"online": 1, "total": 1},
    )
    monkeypatch.setattr(unraid_dashboard_widget, "_next_backups", lambda *_args: [])

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_status_file_cache(
        config,
        app_version="2026.08.29.2210",
        now=datetime(2026, 8, 29, 22, 20, 7, tzinfo=timezone.utc),
    )

    assert result["status"]["state"] == "running"
    assert result["jobs"]["successful"] == 0
    assert result["jobs"]["running"] == 1
    assert result["jobs"]["items"][0]["running"] is True
    assert result["latest_backup"]["name"] == "Sonstiges - USB"
    assert result["latest_backup"]["status"] == "ok"


def test_unraid_dashboard_widget_status_file_cache_keeps_newer_running_job(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    config = {
        "UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file),
        "STATUS_DIR": str(status_dir),
    }
    (status_dir / "2026-08-29_22-20-06_sonstiges_usb.status").write_text(
        json.dumps({
            "backup_type": "sonstiges",
            "job_id": job_id_for("sonstiges_usb"),
            "location": "usb",
            "timestamp": "2026-08-29 22:20:06",
            "duration_seconds": 183,
            "status": "success",
            "exit_code": 0,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_read_jobs",
        lambda _config, _backups: [
            {
                "job_id": "aa439b75-9a27-4c69-9c43-9275a1c43d14",
                "display_name": "Sonstiges - USB",
                "enabled": True,
                "running": True,
                "run_start_time": "2026-08-29 22:25:00",
                "restore_verification_status": "not_required",
            }
        ],
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_repository_summary",
        lambda _config: {"online": 1, "total": 1},
    )
    monkeypatch.setattr(unraid_dashboard_widget, "_next_backups", lambda *_args: [])

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_status_file_cache(
        config,
        app_version="2026.08.29.2210",
        now=datetime(2026, 8, 29, 22, 25, 30, tzinfo=timezone.utc),
    )

    assert result["status"]["state"] == "running"
    assert result["jobs"]["successful"] == 0
    assert result["jobs"]["running"] == 1
    assert result["jobs"]["items"][0]["running"] is True


def test_unraid_dashboard_widget_startup_cache_is_written_without_backup_status(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    config = {"UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file), "BACKUP_SCRIPTS_DIR": str(tmp_path)}

    monkeypatch.setattr(jobs_api, "resolve_data_root", lambda _config: tmp_path)
    monkeypatch.setattr(jobs_api, "resolve_scripts_dir", lambda _config: scripts_dir)
    monkeypatch.setattr(
        jobs_api,
        "discover_jobs",
        lambda _scripts_dir, _data_root: [
            SimpleNamespace(
                job_id="ee05893e-0b67-4d45-b92d-53fa70884fbf",
                name="Flash",
                display_name="Flash - Lokal",
                enabled=True,
                is_utility=False,
            )
        ],
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_repository_summary",
        lambda _config, *, skip_if_array_root=False: {"online": 1, "total": 1},
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_next_backups",
        lambda *_args: [{"name": "Flash - Lokal", "time": "Today 09:00"}],
    )

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_startup_cache(
        config,
        app_version="2026.08.09.1300",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
    )

    assert cache_file.exists()
    assert os.stat(cache_file).st_mode & 0o777 == 0o600
    assert result["cache_state"] == "initial"
    assert result["jobs"]["enabled"] == 1
    assert result["jobs"]["successful"] == 0
    assert result["latest_backup"]["status"] == "unknown"
    assert result["jobs"]["items"][0]["last_status"] == ""
    assert result["next_backups"] == [{"name": "Flash - Lokal", "time": "Today 09:00"}]

    serialized = cache_file.read_text(encoding="utf-8").lower()
    for forbidden in ("/mnt/", "secret", "repo_path", "error_message", "passphrase"):
        assert forbidden not in serialized


def test_unraid_dashboard_widget_startup_cache_preserves_existing_fresh_cache(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    config = {
        "UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file),
        "BACKUP_SCRIPTS_DIR": "/mnt/user/borg-backup-ui",
    }
    existing = {
        "schema_version": 1, "identity_schema_version": 1,
        "cache_state": "fresh",
        "generated_at": "2026-08-09T12:00:00Z",
        "jobs": {
            "enabled": 1,
            "successful": 1,
            "warnings": 0,
            "failed": 0,
            "running": 0,
            "items": [{"job_id": "ee05893e-0b67-4d45-b92d-53fa70884fbf", "last_status": "success"}],
        },
    }
    cache_file.write_text(json.dumps(existing), encoding="utf-8")
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "build_unraid_dashboard_widget_startup_cache",
        lambda *_args, **_kwargs: {"cache_state": "initial"},
    )

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_startup_cache(
        config,
        app_version="2026.08.09.1300",
        now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
    )

    assert result == existing
    assert json.loads(cache_file.read_text(encoding="utf-8")) == existing


def test_unraid_dashboard_widget_startup_cache_rebuilds_running_only_fresh_cache(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    config = {
        "UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file),
        "STATUS_DIR": str(status_dir),
    }
    cache_file.write_text(
        json.dumps({
            "schema_version": 1, "identity_schema_version": 1,
            "cache_state": "fresh",
            "generated_at": "2026-08-28T08:00:00Z",
            "status": {"state": "running"},
            "jobs": {
                "enabled": 1,
                "successful": 0,
                "warnings": 0,
                "failed": 0,
                "running": 1,
                "items": [
                    {
                        "job_id": "ee05893e-0b67-4d45-b92d-53fa70884fbf",
                        "enabled": True,
                        "last_status": "",
                        "last_timestamp": "",
                    }
                ],
            },
        }),
        encoding="utf-8",
    )
    (status_dir / "2026-08-28_12-30-00_flash_local.status").write_text(
        json.dumps({
            "backup_type": "flash",
            "job_id": job_id_for("flash_local"),
            "location": "local",
            "timestamp": "2026-08-28 12:30:00",
            "duration_seconds": 33,
            "status": "success",
            "exit_code": 0,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_read_jobs",
        lambda _config, _backups: [
            {
                "job_id": "ee05893e-0b67-4d45-b92d-53fa70884fbf",
                "display_name": "Flash - Lokal",
                "enabled": True,
                "running": False,
                "restore_verification_status": "verified",
            }
        ],
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "_repository_summary",
        lambda *_args, **_kwargs: {"online": 1, "total": 1},
    )
    monkeypatch.setattr(unraid_dashboard_widget, "_next_backups", lambda *_args: [])

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_startup_cache(
        config,
        app_version="2026.08.28.1913",
        now=datetime(2026, 8, 28, 12, 31, tzinfo=timezone.utc),
    )

    assert result["cache_state"] == "fresh"
    assert result["status"]["state"] == "ok"
    assert result["jobs"]["running"] == 0
    assert result["jobs"]["successful"] == 1
    assert result["latest_backup"]["name"] == "Flash - Lokal"
    assert result["latest_backup"]["status"] == "ok"
    assert result["generated_at"] == "2026-08-28T12:31:00Z"
    assert json.loads(cache_file.read_text(encoding="utf-8")) == result


def test_unraid_dashboard_widget_startup_cache_keeps_canonical_never_run_jobs(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    config = {
        "UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file),
        "STATUS_DIR": str(status_dir),
    }
    cache_file.write_text(
        json.dumps({
            "schema_version": 1, "identity_schema_version": 1,
            "cache_state": "fresh",
            "generated_at": "2026-08-09T12:00:00Z",
            "jobs": {
                "enabled": 1,
                "successful": 0,
                "warnings": 0,
                "failed": 0,
                "running": 0,
                "items": [{"job_id": "ee05893e-0b67-4d45-b92d-53fa70884fbf", "enabled": True, "last_status": "", "last_timestamp": ""}],
            },
            "status": {"state": "ok"},
        }),
        encoding="utf-8",
    )
    job = {
        "job_id": "ee05893e-0b67-4d45-b92d-53fa70884fbf",
        "display_name": "Flash - Lokal",
        "enabled": True,
        "running": False,
        "restore_verification_status": "verified",
    }
    monkeypatch.setattr(unraid_dashboard_widget, "_read_jobs", lambda _config, _backups: [job])
    monkeypatch.setattr(jobs_api, "resolve_data_root", lambda _config: tmp_path)
    monkeypatch.setattr(jobs_api, "resolve_scripts_dir", lambda _config: scripts_dir)
    monkeypatch.setattr(
        jobs_api,
        "discover_jobs",
        lambda _scripts_dir, _data_root: [
            SimpleNamespace(
                job_id="ee05893e-0b67-4d45-b92d-53fa70884fbf",
                name="Flash",
                display_name="Flash - Lokal",
                enabled=True,
                is_utility=False,
            )
        ],
    )
    monkeypatch.setattr(unraid_dashboard_widget, "_repository_summary", lambda *_args, **_kwargs: {"online": 0, "total": 0})
    monkeypatch.setattr(unraid_dashboard_widget, "_next_backups", lambda *_args: [])

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_startup_cache(
        config,
        app_version="2026.08.27.2000",
        now=datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc),
    )

    assert result["cache_state"] == "fresh"
    assert result["status"]["state"] == "unknown"
    assert result[unraid_dashboard_widget.STARTUP_IMPORT_KEY]["state"] == "applied"
    assert result[unraid_dashboard_widget.STARTUP_IMPORT_KEY]["reason"] == "canonical_status"
    assert json.loads(cache_file.read_text(encoding="utf-8")) == result


def test_unraid_dashboard_widget_startup_cache_import_is_one_time(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    config = {
        "UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file),
        "STATUS_DIR": str(tmp_path / "status"),
    }
    existing = {
        "schema_version": 1, "identity_schema_version": 1,
        "cache_state": "initial",
        "generated_at": "2026-08-09T12:00:00Z",
        unraid_dashboard_widget.STARTUP_IMPORT_KEY: {
            "schema_version": 1, "identity_schema_version": 1,
            "state": "skipped",
            "reason": "no_backup_status_rows",
        },
        "jobs": {"enabled": 1, "items": [{"job_id": "ee05893e-0b67-4d45-b92d-53fa70884fbf"}]},
    }
    cache_file.write_text(json.dumps(existing), encoding="utf-8")
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "write_unraid_dashboard_widget_status_file_cache",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("startup import must not repeat")),
    )

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_startup_cache(
        config,
        app_version="2026.08.27.2000",
        now=datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc),
    )

    assert result == existing


def test_unraid_dashboard_widget_startup_cache_builds_fresh_cache_when_missing(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    config = {
        "UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file),
        "STATUS_DIR": str(tmp_path / "status"),
    }
    built = {
        "schema_version": 1, "identity_schema_version": 1,
        "cache_state": "fresh",
        "generated_at": "2026-08-10T12:00:00Z",
        "jobs": {"items": []},
    }
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "write_unraid_dashboard_widget_status_file_cache",
        lambda *_args, **_kwargs: built,
    )
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "build_unraid_dashboard_widget_startup_cache",
        lambda *_args, **_kwargs: {"cache_state": "initial"},
    )

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_startup_cache(
        config,
        app_version="2026.08.09.1300",
        now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
    )

    assert result == built


def test_unraid_dashboard_widget_startup_cache_rebuilds_old_fresh_cache_without_job_items(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    config = {
        "UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file),
        "STATUS_DIR": str(tmp_path / "status"),
    }
    cache_file.write_text(
        json.dumps({
            "schema_version": 1, "identity_schema_version": 1,
            "cache_state": "fresh",
            "generated_at": "2026-08-09T12:00:00Z",
            "jobs": {"enabled": 1, "successful": 1},
        }),
        encoding="utf-8",
    )
    rebuilt = {
        "schema_version": 1, "identity_schema_version": 1,
        "cache_state": "fresh",
        "generated_at": "2026-08-10T12:00:00Z",
        "jobs": {"items": [{"job_id": "ee05893e-0b67-4d45-b92d-53fa70884fbf"}]},
    }
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "write_unraid_dashboard_widget_status_file_cache",
        lambda *_args, **_kwargs: rebuilt,
    )

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_startup_cache(
        config,
        app_version="2026.08.09.1300",
        now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
    )

    assert result == rebuilt


def test_unraid_dashboard_widget_does_not_start_periodic_status_scans():
    source = (ROOT / "borg_backup_ui.py").read_text(encoding="utf-8")
    widget_source = (ROOT / "api" / "unraid_dashboard_widget.py").read_text(encoding="utf-8")
    runner_source = (ROOT / "api" / "wizard_runner.py").read_text(encoding="utf-8")
    page = (ROOT / "plugin" / "borg-backup-ui-dashboard.page").read_text(encoding="utf-8")

    assert "_start_unraid_dashboard_widget_cache_loop" not in source
    assert "UNRAID_DASHBOARD_WIDGET_REFRESH_SECONDS" not in source
    assert "backup job finished" not in runner_source
    assert "get_status_data(config, write_snapshots=False)" in widget_source
    assert "Based on:" in page
    assert "adjustedJobCounts" in page
    assert "function jobStatusEvidence(data)" in page
    assert "cacheState !== 'fresh' || counts.never || (counts.total && !hasEvidence)" in page


def test_api_status_does_not_refresh_unraid_dashboard_widget_cache(tmp_path: Path, monkeypatch):
    handler = _handler({"STATUS_DIR": str(tmp_path / "status")})
    status_payload = {"summary": {"success": 1}, "backups": []}
    calls = []

    monkeypatch.setattr("status_api.get_status_data", lambda _config: status_payload)
    monkeypatch.setattr(
        unraid_dashboard_widget,
        "write_unraid_dashboard_widget_cache",
        lambda *_args, **_kwargs: calls.append("widget-cache"),
    )

    assert handler._get_status() == status_payload
    assert calls == []


def test_unraid_dashboard_widget_startup_cache_skips_array_backed_metadata(tmp_path: Path, monkeypatch):
    cache_file = tmp_path / "widget-status.json"
    config = {"UNRAID_DASHBOARD_WIDGET_FILE": str(cache_file), "BACKUP_SCRIPTS_DIR": "/mnt/user/borg-backup-ui"}

    monkeypatch.setattr(jobs_api, "resolve_data_root", lambda _config: Path("/mnt/user/borg-backup-ui"))
    monkeypatch.setattr(
        jobs_api,
        "discover_jobs",
        lambda *_args: (_ for _ in ()).throw(AssertionError("array metadata should not be read")),
    )

    result = unraid_dashboard_widget.write_unraid_dashboard_widget_startup_cache(
        config,
        now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
    )

    assert result["cache_state"] == "initial"
    assert result["jobs"]["enabled"] == 0
    assert result["repositories"] == {"online": 0, "total": 0}


def test_unraid_dashboard_widget_page_and_assets_are_packaged():
    build = (ROOT / "plugin" / "build.sh").read_text(encoding="utf-8")
    page = (ROOT / "plugin" / "borg-backup-ui-dashboard.page").read_text(encoding="utf-8")

    assert 'Menu="Dashboard:0"' in page
    assert "$mytiles[$pluginname]['column1']" in page
    assert "/plugins/borg-backup-ui/app-icon.png" in page
    assert "{bbui_dash_h(" not in page
    assert "bbui-widget-strip" in page
    assert "font-size:20px" not in page
    assert "widget-status.php" in page
    assert "Successful" in page
    assert "Warnings" in page
    assert "Latest backup" in page
    assert "Next backups" in page
    assert "Restore proof" in page
    assert "Erfolgreich" not in page
    assert "Warnungen" not in page
    assert "Letztes Backup" not in page
    assert "Statusdatei" not in page
    assert '${SCRIPT_DIR}/${NAME}-dashboard.page' in build
    assert '${SCRIPT_DIR}/widget-status.php' in build
    assert 'ui/assets/app-icon.png' in build
    assert '"${EMHTTP_DST}/app-icon.png"' in build


def test_settings_javascript_contains_homepage_custom_api_configuration():
    source = (ROOT / "ui" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")

    assert "type: customapi" in source
    assert "X-Borg-Widget-Token" in source
    assert "/api/widget/summary" in source
    assert "refreshInterval: 60000" in source


def test_settings_javascript_has_clipboard_fallback_for_plain_http():
    source = (ROOT / "ui" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")

    assert "window.isSecureContext" in source
    assert "copyHomepageWidgetFieldFallback" in source
    assert "document.execCommand('copy')" in source
