"""Calendar triggers and repository exclusion for #493."""
import json
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import schedule_api
import restore_tests_api
from borg_backup_ui import BackupUIHandler
from job_fixtures import job_id
from test_restore_tests_policy_contract import _make_job
from test_restore_test_runner_profiles import _load_restore_runner
from wizard_runner import ResourceLockSet


@pytest.fixture
def scheduled_config(tmp_path, monkeypatch):
    _make_job(tmp_path)
    cfg = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "RESTORE_TEST_STATUS_DIR": str(tmp_path / "reports")}
    cron = {"text": "# keep me\n15 1 * * * /usr/local/bin/unrelated\n"}
    def run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 0, cron["text"], "")
        assert cmd == ["crontab", "-"]
        cron["text"] = kwargs["input"]
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(schedule_api.subprocess, "run", run)
    return cfg, cron


def test_calendar_policy_installs_preserves_reapplies_and_disables(scheduled_config):
    cfg, crontab = scheduled_config
    key = job_id('flash_local')
    before = restore_tests_api.list_restore_test_plan(cfg)["jobs"][0]
    assert before['scheduler_state'] == 'needs_schedule'
    assert before['next_run_at'] == ''
    result = restore_tests_api.update_restore_test_policy(cfg, key, {
        'mode': 'scheduled', 'cron': '0 14 * * 0', 'level': 3, 'validity_days': 10,
    })
    assert result['saved']
    assert '/api/restore-tests/run-job' in crontab['text']
    assert '"scheduled":true' in crontab['text']
    assert '/usr/local/bin/unrelated' in crontab['text']
    before = crontab['text']
    schedule_api.apply_all_schedules(cfg)
    assert crontab['text'] == before
    row = restore_tests_api.list_restore_test_plan(cfg)['jobs'][0]
    assert row['policy']['cron'] == '0 14 * * 0'
    assert row['policy']['validity_days'] == 10
    assert row['scheduler_state'] == 'active'
    assert datetime.fromisoformat(row['next_run_at']).weekday() == 6
    restore_tests_api.update_restore_test_policy(cfg, key, {'mode': 'manual_only'})
    assert '/api/restore-tests/run-job' not in crontab['text']
    assert '/usr/local/bin/unrelated' in crontab['text']
    row = restore_tests_api.list_restore_test_plan(cfg)['jobs'][0]
    assert row['scheduler_state'] == 'off'
    assert row['policy']['cron'] == '0 14 * * 0'


def test_existing_global_trigger_and_interval_are_preserved(scheduled_config):
    cfg, crontab = scheduled_config
    schedule_api.save_schedule(cfg, 'restore_test', '20 6 * * 1', True)
    row = restore_tests_api.list_restore_test_plan(cfg)['jobs'][0]
    assert row['scheduler_state'] == 'legacy'
    assert row['policy']['interval_days'] == 30
    assert row['policy']['cron'] == ''
    assert crontab['text'].count('/api/restore-tests/run') == 1


@pytest.mark.parametrize('cron', ['70 14 * * 0', '0 25 * * 0', '0 2 32 * *', '0 2 * * 8', '0 2 * * 0;touch x'])
def test_invalid_calendar_schedule_does_not_change_metadata(scheduled_config, cron):
    cfg, _ = scheduled_config
    path = Path(cfg['BACKUP_SCRIPTS_DIR']) / 'config/jobs' / f'{job_id("flash_local")}.json'
    original = path.read_bytes()
    with pytest.raises(ValueError):
        restore_tests_api.update_restore_test_policy(cfg, job_id('flash_local'), {'cron': cron})
    assert path.read_bytes() == original


def test_cron_failure_is_visible_and_can_be_retried(scheduled_config, monkeypatch):
    cfg, crontab = scheduled_config
    original = schedule_api._update_crontab
    monkeypatch.setattr(schedule_api, '_update_crontab', lambda _lines: (_ for _ in ()).throw(RuntimeError('denied')))
    with pytest.raises(RuntimeError, match='saved but cron could not be applied'):
        restore_tests_api.update_restore_test_policy(cfg, job_id('flash_local'), {'cron': '0 14 * * 0'})
    assert restore_tests_api.list_restore_test_plan(cfg)['jobs'][0]['scheduler_state'] == 'not_installed'
    monkeypatch.setattr(schedule_api, '_update_crontab', original)
    schedule_api.apply_all_schedules(cfg)
    assert restore_tests_api.list_restore_test_plan(cfg)['jobs'][0]['scheduler_state'] == 'active'


def test_disabled_jobs_do_not_install_restore_trigger(scheduled_config):
    cfg, crontab = scheduled_config
    path = Path(cfg['BACKUP_SCRIPTS_DIR']) / 'config/jobs' / f'{job_id("flash_local")}.json'
    job = json.loads(path.read_text())
    job['enabled'] = False
    job['restore_test_policy']['cron'] = '0 14 * * 0'
    path.write_text(json.dumps(job))
    schedule_api.apply_all_schedules(cfg)
    assert '/api/restore-tests/run-job' not in crontab['text']


def _tester(tmp_path, monkeypatch):
    runner = _load_restore_runner()
    monkeypatch.setattr(runner, 'emit_lifecycle', lambda *_a, **_k: None)
    monkeypatch.setattr(runner, '_refresh_unraid_dashboard_widget_cache', lambda *_a: None)
    args = SimpleNamespace(level=2, force=False, scheduled=True, dry_run=False)
    conf = {'BACKUP_SCRIPTS_DIR': str(tmp_path), 'BORG_RESOURCE_LOCK_DIR': str(tmp_path / 'locks'),
            'GLOBAL_LOG_DIR': str(tmp_path / 'logs'), 'RESTORE_TEST_STATUS_DIR': str(tmp_path / 'reports')}
    monkeypatch.setattr(runner.RestoreTest, '_load_notification_config', lambda _s: {})
    tester = runner.RestoreTest(conf, args)
    monkeypatch.setattr(tester, '_notify_event', lambda *_a: None)
    repo = {'job_key': job_id('flash_local'), 'path': str(tmp_path / 'repository'), 'location': 'local',
            'restore_test_policy': {'mode': 'scheduled', 'cron': '0 14 * * 0', 'level': 3}}
    return tester, repo


def test_backup_blocks_test_without_overwriting_previous_evidence(tmp_path, monkeypatch):
    tester, repo = _tester(tmp_path, monkeypatch)
    tester.status_dir.mkdir(parents=True)
    evidence = tester.status_dir / f'{repo["job_key"]}.test'
    evidence.write_text(json.dumps({'test_result':'success', 'test_date':datetime.now().strftime('%Y-%m-%d %H:%M:%S')}))
    original = evidence.read_bytes()
    lock = ResourceLockSet(tmp_path / 'locks', 'another-backup-job')
    assert lock.acquire([f'repo:{repo["path"]}'])[0]
    monkeypatch.setattr(tester, '_test_repo_locked', lambda _r: pytest.fail('Must not call Borg'))
    try:
        assert tester.test_repo(repo) == 2
        assert evidence.read_bytes() == original
        report = json.loads((tester.status_dir / f'{repo["job_key"]}.skip.test').read_text())
        assert report['test_result'] == 'skipped'
        assert report['failure_code'] == 'RT_REPO_BUSY'
        assert 'another-backup-job' in report['reason']
    finally:
        lock.release()
        tester.close()


def test_test_blocks_only_same_repository_and_releases_after_failure(tmp_path, monkeypatch):
    tester, repo = _tester(tmp_path, monkeypatch)
    backup = ResourceLockSet(tmp_path / 'locks', 'backup')
    other = ResourceLockSet(tmp_path / 'locks', 'other-backup')
    def probe(_repo):
        assert tester.test_level == 3
        assert not backup.acquire([f'repo:{repo["path"]}'])[0]
        assert other.acquire(['repo:/somewhere-else'])[0]
        other.release()
        raise RuntimeError('simulated Borg error')
    monkeypatch.setattr(tester, '_test_repo_locked', probe)
    try:
        with pytest.raises(RuntimeError, match='simulated Borg error'):
            tester.test_repo(repo)
        assert backup.acquire([f'repo:{repo["path"]}'])[0]
    finally:
        backup.release()
        tester.close()


def test_calendar_start_ignores_old_global_interval_but_legacy_uses_job_interval(tmp_path, monkeypatch):
    tester, repo = _tester(tmp_path, monkeypatch)
    tester.status_dir.mkdir(parents=True)
    (tester.status_dir / f'{repo["job_key"]}.test').write_text(json.dumps({
        'test_result':'success', 'test_date':datetime.now().strftime('%Y-%m-%d %H:%M:%S')}))
    monkeypatch.setattr(tester, '_test_repo_locked', lambda _r: 0)
    try:
        assert tester.test_repo(repo) == 0
        repo['restore_test_policy'] = {'mode':'scheduled', 'interval_days':7, 'level':1}
        assert tester.test_repo(repo) == 2
        assert tester.test_interval == 7
        assert tester.test_level == 1
    finally:
        tester.close()


def test_simultaneous_lock_acquisition_has_one_winner(tmp_path):
    start = threading.Barrier(8)
    finish = threading.Barrier(8)
    results = []
    def contender(n):
        lock = ResourceLockSet(tmp_path, str(n))
        start.wait()
        results.append(lock.acquire(['repo:/shared'])[0])
        finish.wait()
        lock.release()
    threads = [threading.Thread(target=contender, args=(n,)) for n in range(8)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert sum(results) == 1


def test_cron_endpoint_uses_job_level_and_distinct_run_keys(tmp_path, monkeypatch):
    import jobs_api
    import config_api
    import lifecycle_log
    keys = [job_id('flash_local'), job_id('photos_local')]
    rows = [{'key': key, 'enabled': True, 'restore_test_policy': {'mode':'scheduled', 'cron':'0 14 * * 0', 'level':level}}
            for key, level in zip(keys, [1, 3])]
    script = tmp_path / 'borg_restore_test.py'
    script.write_text('# test runner')
    calls = []
    class Manager:
        def start(self, key, cmd, cwd, extra_env):
            calls.append((key, cmd, extra_env))
            return True, None
        def get_state(self, _key): return {'run_id':'test-run'}
    monkeypatch.setattr(jobs_api.JobManager, 'get', classmethod(lambda _c: Manager()))
    monkeypatch.setattr(jobs_api, 'list_jobs', lambda *_a: rows)
    monkeypatch.setattr(jobs_api, 'resolve_scripts_dir', lambda _c: tmp_path)
    monkeypatch.setattr(config_api, 'read_expanded_conf', lambda _c: {})
    monkeypatch.setattr(lifecycle_log, 'emit_lifecycle', lambda *_a, **_k: None)
    handler = object.__new__(BackupUIHandler)
    handler.config = {'BACKUP_SCRIPTS_DIR':str(tmp_path)}
    handler._require_data_dir_ready = lambda: None
    handler._get_current_session_meta = lambda: {}
    handler._has_valid_api_token_header = lambda: True
    for key in keys:
        handler._read_json_body = lambda: {'job_key':key, 'scheduled':True}
        result = handler._post_run_restore_test_job()
        assert result['started'] and result['scheduled']
        assert result['run_key'] == f'restore_test_{key}'
    assert calls[0][0] != calls[1][0]
    assert [command[command.index('--level') + 1] for _, command, _ in calls] == ['1', '3']
    assert all('--scheduled' in command and '--force' not in command for _, command, _ in calls)
    rows[1]['enabled'] = False
    assert handler._post_run_restore_test_job()['reason'] == 'schedule_disabled'
    assert len(calls) == 2


def test_resource_conflict_backup_is_persisted_as_skipped(tmp_path, monkeypatch):
    from test_job_file_names import make_config
    from lib.backup_job import BackupJob
    cfg = make_config(tmp_path, job_id('flash_local'), 'Flash')
    job = BackupJob(cfg)
    monkeypatch.setattr(job, '_send_notification_event', lambda *_a, **_k: None)
    monkeypatch.setattr(job, '_emit_lifecycle_finished', lambda **_k: None)
    monkeypatch.setattr(job, '_refresh_unraid_dashboard_widget_cache', lambda *_a: None)
    job.record_prestart_skip('resource locked by restore_test run-123 (repo:/backup)')
    result = json.loads(next(cfg.status_dir.glob('*.status')).read_text())
    assert result['status'] == 'skipped'
    assert result['skip_reason_code'] == 'resource_lock_unavailable'
    assert result['duration_seconds'] <= 1
    assert 'restore_test' in result['skip_reason_text']
    assert not cfg.lock_file.exists()


def test_simultaneous_same_job_starts_do_not_replace_active_process(tmp_path, monkeypatch):
    import jobs_api
    manager = jobs_api.JobManager()
    launched = []
    def spawn(*args, **kwargs):
        launched.append(args)
        return SimpleNamespace(pid=1234)
    monkeypatch.setattr(jobs_api.subprocess, 'Popen', spawn)
    monkeypatch.setattr(manager, '_reader', lambda *_a: None)
    barrier = threading.Barrier(4)
    results = []
    def start():
        barrier.wait()
        results.append(manager.start('restore_test_example', ['fake-borg'], tmp_path)[0])
    threads = [threading.Thread(target=start) for _ in range(4)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=5)
    assert sum(results) == len(launched) == 1
    assert manager.get_state('restore_test_example')['running']


@pytest.mark.parametrize("old_interval", [1, 30])
@pytest.mark.parametrize("seconds_after_expiry, overdue", [(-1, False), (0, True), (1, True)])
def test_calendar_reminder_due_date_matches_evidence_validity(scheduled_config, monkeypatch, seconds_after_expiry, overdue, old_interval):
    cfg, _ = scheduled_config
    key = job_id("flash_local")
    now = datetime(2026, 9, 17, 12, 0, 0)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)
    monkeypatch.setattr(restore_tests_api, "datetime", Clock)
    restore_tests_api.update_restore_test_policy(cfg, key, {
        "mode": "scheduled", "cron": "0 20 1 * *", "validity_days": 7, "interval_days": old_interval,
    })
    last = now - timedelta(days=7, seconds=seconds_after_expiry)
    reports = Path(cfg["RESTORE_TEST_STATUS_DIR"])
    reports.mkdir()
    (reports / f"{key}.test").write_text(json.dumps({
        "test_result": "success", "test_date": last.strftime("%Y-%m-%d %H:%M:%S"),
    }))
    row = restore_tests_api.list_restore_test_plan(cfg)["jobs"][0]
    assert row["next_due_at"] == (last + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    assert row["is_overdue"] is overdue
    assert row["next_run_at"] == "2026-10-01 20:00:00"
    assert row["verification_status"] == ("stale" if overdue else "verified")


def test_calendar_overdue_reminder_survives_skip_is_throttled_and_stops_after_success(scheduled_config, monkeypatch):
    import notification_reminder_api
    cfg, _ = scheduled_config
    cfg.update(NOTIFY_UNRAID_EVENTS="restore_test_overdue", NOTIFY_EMAIL_EVENTS="",
               NOTIFY_APPRISE_EVENTS="", NOTIFY_REMINDER_INTERVAL_HOURS="24")
    key = job_id("flash_local")
    restore_tests_api.update_restore_test_policy(cfg, key, {
        "mode": "scheduled", "cron": "0 20 1 * *", "validity_days": 7, "interval_days": 30,
    })
    reports = Path(cfg["RESTORE_TEST_STATUS_DIR"])
    reports.mkdir()
    report = reports / f"{key}.test"
    last = datetime.now() - timedelta(days=8)
    report.write_text(json.dumps({"test_result": "success", "test_date": last.strftime("%Y-%m-%d %H:%M:%S")}))
    (reports / f"{key}.skip.test").write_text(json.dumps({
        "test_result": "skipped", "failure_code": "RT_REPO_BUSY", "test_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }))
    calls = []
    monkeypatch.setattr("lib.notification_events.notify", lambda **kwargs: calls.append(kwargs["subject"]) or True)
    first = notification_reminder_api.run_due_notification_reminders(cfg)
    assert first["sent"] == 1
    assert calls == ["Borg Backup UI: Restore test overdue"]
    diagnostic = notification_reminder_api.get_notification_reminder_diagnostics(cfg)["restore_test_overdue"]["items"][0]
    assert diagnostic["next_due_at"] == (last + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    assert diagnostic["state"] == "overdue_waiting"
    assert diagnostic["next_run_at"] == restore_tests_api.list_restore_test_plan(cfg)["jobs"][0]["next_run_at"]
    assert diagnostic["next_run_at"] != diagnostic["next_due_at"]
    assert notification_reminder_api.run_due_notification_reminders(cfg)["sent"] == 0
    report.write_text(json.dumps({"test_result": "success", "test_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}))
    assert notification_reminder_api.run_due_notification_reminders(cfg)["checked"] == 0
    assert len(calls) == 1


@pytest.mark.parametrize("result", ["failed", "unavailable"])
def test_calendar_failure_keeps_existing_reminder_eligibility(scheduled_config, result):
    cfg, _ = scheduled_config
    key = job_id("flash_local")
    restore_tests_api.update_restore_test_policy(cfg, key, {"cron": "0 20 1 * *", "validity_days": 30})
    reports = Path(cfg["RESTORE_TEST_STATUS_DIR"])
    reports.mkdir()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (reports / f"{key}.test").write_text(json.dumps({"test_result": result, "test_date": stamp}))
    row = restore_tests_api.list_restore_test_plan(cfg)["jobs"][0]
    assert row["is_overdue"] is True
    assert row["next_due_at"] == stamp
