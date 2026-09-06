import hashlib
import io
import json
import os
import sys
import time
import tracemalloc
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for root in (ROOT, ROOT / "api"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import activity_log
import activity_log_capture
import jobs_api
from borg_backup_ui import BackupUIHandler
from wizard_runner import ResourceLockSet


@pytest.fixture
def activity(tmp_path, monkeypatch):
    monkeypatch.setattr(activity_log_capture, "CAPTURE_ROOT", tmp_path / "ram")
    manager = jobs_api.JobManager()
    monkeypatch.setattr(jobs_api.JobManager, "get", classmethod(lambda cls: manager))
    monkeypatch.setattr("job_control.read_control_state", lambda _run: {})
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path), "GLOBAL_LOG_DIR": str(tmp_path / "logs")}
    path = activity_log.activity_log_path(tmp_path / "logs", "files_local", "20260905T120000Z-abcdef123456")
    path.parent.mkdir()
    path.write_bytes(b"")
    params = {"job": ["files_local"], "run": ["20260905T120000Z-abcdef123456"]}
    return config, path, params, manager


def test_million_lines_round_trip_with_bounded_memory(activity):
    config, path, params, _manager = activity
    expected = hashlib.sha256()
    with path.open("wb") as handle:
        for i in range(1000):
            block = "".join(f"A /mnt/user/STLs/Größe-{i * 1000 + j:07d}-模型.stl\n" for j in range(1000)).encode()
            handle.write(block)
            expected.update(block)
    tracemalloc.start()
    actual = hashlib.sha256()
    cursor = lines = calls = 0
    while True:
        result = activity_log.get_activity_window(config, {**params, "start": [str(cursor)]})
        data = result["text"].encode()
        assert len(data) <= activity_log.WINDOW_BYTES + 4
        assert data.startswith(b"A ") and data.endswith(b"\n")
        assert result["start"] == cursor
        actual.update(data)
        lines += data.count(b"\n")
        calls += 1
        cursor = result["end"]
        if cursor == result["size"]:
            break
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert actual.digest() == expected.digest()
    assert lines == 1_000_000
    assert calls > 100
    assert peak < 4 * 1024 * 1024


def test_reverse_windows_recover_every_utf8_byte_and_long_line(activity):
    config, path, params, _manager = activity
    content = ("🌍" * 50000 + "\nE /mnt/unreadable\n" + "ä" * 50000).encode()
    path.write_bytes(content)
    parts = []
    cursor = len(content)
    while cursor:
        result = activity_log.get_activity_window(config, {**params, "before": [str(cursor)]})
        assert result["end"] == cursor
        assert result["start"] < cursor
        parts.insert(0, result["text"].encode())
        cursor = result["start"]
    assert b"".join(parts) == content


def test_growing_utf8_character_is_retried_without_loss():
    partial = io.BytesIO(b"A " + "🌍".encode()[:2])
    result = activity_log.read_window(partial, 0, 4, running=True)
    assert result == {"start": 0, "end": 2, "text": "A "}
    complete = io.BytesIO(b"A " + "🌍".encode() + b"\n")
    result = activity_log.read_window(complete, result["end"], 7, running=True)
    assert result["text"] == "🌍\n"
    assert result["end"] == 7


def test_search_crosses_blocks_and_searches_beyond_visible_tail(activity):
    config, path, params, _manager = activity
    needle = "Druck/Größe.stl"
    prefix = b"A" * (activity_log.SEARCH_BYTES - 3)
    path.write_bytes(prefix + needle.encode() + b"\n" + b"Z" * activity_log.SEARCH_BYTES * 2)
    result = activity_log.get_activity_window(config, {**params, "search": [needle]})
    assert result["match"] == len(prefix)
    assert needle in result["text"]
    assert result["next"] == len(prefix) + len(needle.encode())
    result = activity_log.get_activity_window(config, {**params, "search": ["missing"]})
    assert result["match"] is None
    assert result["search_done"] is False
    assert result["next"] == activity_log.SEARCH_BYTES


def test_status_requests_do_not_read_file_contents(activity, monkeypatch):
    config, path, params, _manager = activity
    path.write_text("A file\n")
    monkeypatch.setattr(activity_log, "read_window", lambda *args, **kwargs: pytest.fail("status read the log"))
    result = activity_log.get_activity_window(config, {**params, "status": ["1"]})
    assert result["size"] == 7
    assert "text" not in result


@pytest.mark.parametrize("params", [
    {"job": ["../../etc/passwd"]}, {"run": ["../../etc/passwd"]},
    {"start": ["-1"]}, {"before": ["99999"]}, {"start": ["1.1"]},
    {"start": ["9" * 50]}, {"search": [""]}, {"search": ["a" * 257]},
    {"file_id": ["replaced-file"]},
])
def test_invalid_identity_and_cursors_are_rejected(activity, params):
    config, _path, base, _manager = activity
    with pytest.raises(ValueError):
        activity_log.get_activity_window(config, {**base, **params})


def test_symlinks_and_nonregular_files_are_rejected(activity):
    config, path, params, _manager = activity
    path.unlink()
    path.symlink_to(ROOT / "borg_backup_ui.conf.example")
    with pytest.raises(OSError):
        activity_log.get_activity_window(config, params)
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(ValueError, match="regular file"):
        activity_log.get_activity_window(config, params)


@pytest.mark.parametrize("enabled", [False, True])
def test_real_process_capture_only_uses_file_when_enabled(activity, enabled):
    config, path, _params, manager = activity
    env = {"BORG_UI_FILE_ACTIVITY_RUN": "1" if enabled else "0", "BORG_UI_ACTIVITY_LOG_DIR": str(path.parent)}
    script = "import sys; sys.stdout.write('A changed.stl\\n' * 10000); sys.stderr.write('E unreadable'); sys.exit(1)"
    assert manager.start("files_local", [sys.executable, "-c", script], path.parent, env) == (True, None)
    state = manager._states["files_local"]
    deadline = time.monotonic() + 10
    while not state.finished and time.monotonic() < deadline:
        time.sleep(0.01)
    assert state.finished
    assert manager.get_state("files_local")["exit_code"] == 1
    if enabled:
        assert state.lines == []
        assert state.proc.stdout is None
        text = state.log_file.read_text()
        assert text.count("A changed.stl\n") == 10000
        assert text.endswith("E unreadable")
        assert state.log_file.stat().st_mode & 0o777 == 0o600
        state.snapshot = lambda: pytest.fail("activity status copied an in-memory log")
        assert manager.get_state("files_local")["file_activity"] is True
        assert manager.get_state("files_local")["line_count"] == 10001
        stream = manager.stream_output("files_local")
        assert sum(1 for item in stream if item.startswith("data:")) == 10001
    else:
        assert state.log_file is None
        assert len(state.lines) == 10001
        assert "file_activity" not in manager.get_state("files_local")


def test_restart_recovers_active_run_mode_and_completed_exit(activity, monkeypatch):
    config, path, params, _manager = activity
    lock_dir = Path(config["BACKUP_SCRIPTS_DIR"]) / "locks"
    lock_dir.mkdir()
    locks = ResourceLockSet(lock_dir, "files_local", log_file=str(path), run_id=params["run"][0], file_activity=True)
    lock = lock_dir / "repo.lock.json"
    lock.write_text(json.dumps(locks._payload("repo:test")))
    result = activity_log.get_activity_window(config, {"job": ["files_local"]})
    assert result["running"] is True
    assert result["run_id"] == params["run"][0]
    lock.unlink()
    monkeypatch.setattr("job_control.read_control_state", lambda _run: {"job_key": "files_local", "finished": True, "exit_code": 130, "phase": "cancelled"})
    result = activity_log.get_activity_window(config, params)
    assert result["running"] is False
    assert result["exit_code"] == 130


def test_download_includes_complete_log_without_large_writes(activity):
    _config, path, params, _manager = activity
    content = b"A test\n" * 100000
    path.write_bytes(content)
    handler = BackupUIHandler.__new__(BackupUIHandler)
    handler.config = _config
    handler._current_request_id = "test"
    headers = {}
    handler.send_response = lambda code: headers.update(status=code)
    handler.send_header = lambda key, value: headers.update({key: value})
    handler.end_headers = lambda: None
    handler._send_refreshed_session_header = lambda: None
    chunks = []
    class Sink:
        def write(self, data):
            assert len(data) <= 65536
            chunks.append(data)
    handler.wfile = Sink()
    handler._download_activity_log(f"job=files_local&run={params['run'][0]}")
    assert headers["status"] == 200
    assert int(headers["Content-Length"]) == len(content)
    assert b"".join(chunks) == content


@pytest.mark.parametrize('enabled', [False, True])
def test_runner_logging_writes_each_line_once(activity, enabled):
    _config, path, _params, manager = activity
    env = {
        'BORG_UI_FILE_ACTIVITY_RUN': '1' if enabled else '0',
        'BORG_UI_ACTIVITY_LOG_DIR': str(path.parent),
        'PYTHONPATH': str(ROOT / 'api'),
    }
    script = '''import logging, os
from pathlib import Path
from wizard_runner import _setup_stdout_logging, _setup_full_logging
_setup_stdout_logging()
logging.info('bootstrap message')
log_file = Path(os.environ.get('BORG_UI_CAPTURE_LOG', 'normal.log'))
_setup_full_logging(log_file)
logging.info('A changed file.stl')
logging.warning('warning remains visible')
'''
    assert manager.start('files_local', [sys.executable, '-c', script], path.parent, env)[0]
    state = manager._states['files_local']
    deadline = time.monotonic() + 10
    while not state.finished and time.monotonic() < deadline:
        time.sleep(0.01)
    assert state.finished and state.exit_code == 0
    if enabled:
        text = state.log_file.read_text()
        assert text.count('bootstrap message') == 1
    else:
        text = (path.parent / 'normal.log').read_text()
        assert any('bootstrap message' in line for line in state.lines)
        assert any('A changed file.stl' in line for line in state.lines)
    assert text.count('A changed file.stl') == 1
    assert text.count('warning remains visible') == 1


@pytest.mark.parametrize('exit_code', [0, 1, 2, 130, 137])
def test_ram_log_is_retained_after_runner_exit_without_api_reader(activity, monkeypatch, exit_code):
    config, path, _params, manager = activity
    # The supervisor must retain the file without an API-owned reader thread.
    monkeypatch.setattr(manager, '_reader', lambda *_args: None)
    ready, release = path.parent / 'ready', path.parent / 'release'
    script = '''import os, sys, time
from pathlib import Path
print('A changed-Größe.stl\\n' * 10000, end='', flush=True)
Path('ready').touch()
while not Path('release').exists(): time.sleep(0.01)
print('INFO Docker recovery finished', flush=True)
sys.stderr.write('INFO final unterminated line')
sys.stderr.flush()
code = int(sys.argv[1])
if code == 137: os.kill(os.getpid(), 9)
sys.exit(code)
'''
    env = {'BORG_UI_FILE_ACTIVITY_RUN': '1', 'BORG_UI_ACTIVITY_LOG_DIR': str(path.parent)}
    assert manager.start('files_local', [sys.executable, '-c', script, str(exit_code)], path.parent, env)[0]
    state = manager._states['files_local']
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        record = activity_log_capture.read_record(state.capture_record_file)
        retained = Path(record['retained_file'])
        assert not retained.exists(), 'the active log must not change the backed-up log directory'
        assert state.log_file.is_relative_to(activity_log_capture.CAPTURE_ROOT)
        # Drop API state entirely. Resource-lock-independent recovery sees the
        # supervisor and the live file; no parent thread is needed for saving.
        manager._states.clear()
        recovered = jobs_api.durable_running_states(config)['files_local']
        assert recovered['run_id'] == state.run_id and recovered['file_activity']
        params = {'job': ['files_local'], 'run': [state.run_id]}
        before = activity_log.get_activity_window(config, params)
        assert before['running'] is True and 'changed-Größe.stl' in before['text']
        release.touch()
        assert state.proc.wait(timeout=10) == exit_code
        after = activity_log.get_activity_window(config, {**params, 'start': [str(before['end'])], 'file_id': [before['file_id']]})
        assert after['file_id'] == before['file_id']
        assert after['text'] == 'INFO Docker recovery finished\nINFO final unterminated line'
        assert after['running'] is False and after['exit_code'] == exit_code
        assert not state.log_file.exists(), 'the full RAM allocation must be released'
        assert retained.read_text() == 'A changed-Größe.stl\n' * 10000 + after['text']
        assert 'files_local' not in jobs_api.durable_running_states(config)
    finally:
        release.touch()
        state.proc.wait(timeout=10)


def test_failed_retention_preserves_complete_ram_log_and_existing_destination(activity):
    config, path, params, _manager = activity
    active, record_path = activity_log_capture.prepare_capture('files_local', params['run'][0], path.parent)
    content = 'A changed-Größe.stl\n' * 10000
    active.write_text(content)
    path.write_text('existing log must not be overwritten')
    assert activity_log_capture.retain_capture(record_path, 0) is False
    assert path.read_text() == 'existing log must not be overwritten'
    assert active.read_text() == content
    result = activity_log.get_activity_window(config, params)
    assert result['log_persistence_failed'] is True
    assert 'changed-Größe.stl' in result['text']
    assert result['exit_code'] == 0


def test_partial_copy_failure_keeps_ram_and_removes_incomplete_destination(activity, monkeypatch):
    config, path, params, _manager = activity
    path.unlink()
    active, record_path = activity_log_capture.prepare_capture('files_local', params['run'][0], path.parent)
    content = b'A changed.stl\n' * 10000
    active.write_bytes(content)
    def fail_copy(source, target, length):
        assert length == 65536
        target.write(source.read(10))
        raise OSError('simulated full destination')
    monkeypatch.setattr(activity_log_capture.shutil, 'copyfileobj', fail_copy)
    assert activity_log_capture.retain_capture(record_path, 2) is False
    assert not path.exists()
    assert active.read_bytes() == content
    result = activity_log.get_activity_window(config, params)
    assert result['log_persistence_failed'] is True and result['exit_code'] == 2


def test_open_retries_ram_to_retained_transition_and_rejects_replacement(activity, monkeypatch):
    config, path, params, _manager = activity
    path.unlink()
    active, record_path = activity_log_capture.prepare_capture('files_local', params['run'][0], path.parent)
    active.write_text('A first.stl\nA second.stl\n')
    before = activity_log.get_activity_window(config, params)
    original_open = activity_log.open_activity_file
    def finish_before_open(candidate):
        if candidate == active:
            monkeypatch.setattr(activity_log, 'open_activity_file', original_open)
            assert activity_log_capture.retain_capture(record_path, 0)
        return original_open(candidate)
    monkeypatch.setattr(activity_log, 'open_activity_file', finish_before_open)
    result = activity_log.get_activity_window(config, {**params, 'file_id': [before['file_id']]})
    assert result['text'] == before['text']
    assert result['file_id'] == before['file_id']
    replacement = path.with_suffix('.replacement')
    replacement.write_text('different file')
    replacement.replace(path)
    with pytest.raises(ValueError, match='replaced'):
        activity_log.get_activity_window(config, {**params, 'file_id': [before['file_id']]})


def test_saved_history_references_retained_log_while_active_reads_use_ram(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'runtime'))
    from runtime.lib.backup_job import BackupJob, BackupJobConfig
    active = tmp_path / 'ram' / 'active.log'
    retained = tmp_path / 'logs' / 'saved.log'
    active.parent.mkdir()
    active.write_text('WARNING source changed\n')
    cfg = BackupJobConfig(
        job_name='Files', backup_type='files', backup_location='local',
        lock_file=tmp_path / 'job.lock', log_dir=retained.parent, log_file=active,
        backup_paths=[tmp_path], borg_cache_dir=tmp_path / 'cache', date_tag='2026-09-06',
        status_dir=tmp_path / 'status', retained_log_file=retained,
    )
    job = BackupJob(cfg)
    job.set_result(1)
    saved = job._save_status(10)
    status = json.loads(saved.read_text())
    assert status['log_file'] == str(retained)
    assert status['status'] == 'warning'
    assert 'source changed' in status['error_message']
    assert not retained.exists()
