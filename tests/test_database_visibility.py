"""Database job markers and content-free export logging (#689)."""
import json
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest

from test_database_backups import backup, profiles, config, profile, fake_export
from job_fixtures import write_job


def test_export_logs_start_before_output_and_local_completion(config, profile, monkeypatch, caplog):
    fake_export(monkeypatch, profile)
    caplog.set_level(logging.INFO)
    def export(_config, _profile, _cid, _action, database, output, cancelled):
        assert 'Database profile export started' in caplog.text
        assert f'database="{database}"' in caplog.text
        assert 'Database export started' in caplog.text
        assert 'completed locally' not in caplog.text
        output.write(b'private SQL payload')
    monkeypatch.setattr(backup, '_operation', export)
    results = backup.export_profiles(config, [profile], 'job', 'run')
    try:
        assert 'Database export completed locally' in caplog.text
        assert 'Database profile export completed locally' in caplog.text
        assert 'exported=19 bytes' in caplog.text
        assert 'not yet verified in a Borg archive' in caplog.text
        assert 'private SQL payload' not in caplog.text
        assert not results[0]['archived']
    finally:
        backup.close_results(results)


@pytest.mark.parametrize('reason', ['cancelled', 'timeout', 'credentials', 'export_failed', 'unresolved_export'])
def test_failed_export_logs_safe_context_without_success(config, profile, monkeypatch, caplog, reason):
    fake_export(monkeypatch, profile, reason)
    caplog.set_level(logging.INFO)
    profile.update(name='DB\npassword=private-password', password='credential-value')
    results = []
    try:
        with pytest.raises(profiles.DatabaseError, match=reason):
            backup.export_profiles(config, [profile], 'job', 'run', results=results)
        assert f'reason={reason}' in caplog.text
        assert 'database="app"' in caplog.text
        assert ('export cancelled' if reason == 'cancelled' else 'export failed') in caplog.text
        assert 'completed locally' not in caplog.text
        assert 'private-password' not in caplog.text and 'credential-value' not in caplog.text
        assert 'partial' not in caplog.text
        assert all('\n' not in record.getMessage() for record in caplog.records)
        assert results[0]['status'] == 'failed'
    finally:
        backup.close_results(results)


def test_staging_failure_has_context_without_raw_exception(config, profile, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(backup, 'open_staging', Mock(side_effect=OSError('private storage details')))
    with pytest.raises(OSError):
        backup.export_profiles(config, [profile], 'job', 'run')
    assert 'profile="DB"' in caplog.text and 'reason=export_failed' in caplog.text
    assert 'private storage details' not in caplog.text
    assert 'completed locally' not in caplog.text


def test_streaming_progress_is_bounded_and_check_only_stays_silent(config, profile, monkeypatch, caplog):
    fake_export(monkeypatch, profile)
    caplog.set_level(logging.INFO)
    clock = [0.0]
    monkeypatch.setattr(backup.time, 'monotonic', lambda: clock[0])
    def export(_config, _profile, _cid, _action, _database, output, cancelled):
        for tick in (0, 1, 29, 30, 31, 59, 60, 61):
            clock[0] = tick
            output.write(b'private SQL payload')
    monkeypatch.setattr(backup, '_operation', export)
    results = backup.export_profiles(config, [profile], 'job', 'run')
    try:
        progress = [r.getMessage() for r in caplog.records if 'Database export running:' in r.getMessage()]
        assert len(progress) == 2
        assert 'elapsed=30.0s' in progress[0] and 'elapsed=60.0s' in progress[1]
        assert all('current export=' in line and 'private SQL' not in line for line in progress)
    finally:
        backup.close_results(results)
    caplog.clear()
    monkeypatch.setattr(backup, 'utc_now', lambda: '2026-10-25T10:00:00+00:00')
    checked = backup.export_profiles(config, [profile], 'job', 'check', check_only=True)
    try:
        assert checked[0]['status'] == 'checked'
        assert 'Database export' not in caplog.text and 'Database profile export' not in caplog.text
    finally:
        backup.close_results(checked)


@pytest.mark.parametrize('selected', [[], ['db-aaaaaaaaaaaa']])
def test_job_api_reports_current_database_assignments_without_docker(tmp_path, selected):
    import jobs_api
    job = write_job(tmp_path, 'database_local', database_profile_ids=selected, source_paths=[])
    cfg = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    jobs_api.invalidate_job_discovery_cache()
    rows = jobs_api.list_jobs(cfg, {})
    row = next(r for r in rows if r['key'] == job['job_id'])
    assert row['has_database'] is bool(selected)
    assert not row['has_docker'] and not row['has_vm']
    # Configuration refresh must remove the badge even if old run results remain.
    path = tmp_path / 'config/jobs' / (job['job_id'] + '.json')
    job['database_profile_ids'] = []
    path.write_text(json.dumps(job))
    jobs_api.invalidate_job_discovery_cache()
    row = next(r for r in jobs_api.list_jobs(cfg, {}) if r['key'] == job['job_id'])
    assert row['has_database'] is False
