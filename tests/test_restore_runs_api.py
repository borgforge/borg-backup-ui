from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import restore_api  # noqa: E402


def test_list_restore_runs_returns_recent_and_active_runs(tmp_path: Path):
    restore_api._RESTORE_RUNS_LOADED = True
    restore_api._RESTORE_RUNS.clear()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    restore_api._RESTORE_RUNS.update({
        "old-done": {
            "restore_id": "old-done",
            "state": "done",
            "phase": "done",
            "started_at": "2026-06-28T10:00:00",
            "finished_at": "2026-06-28T10:05:00",
            "job_key": "photos_local",
            "archive": "photos-archive",
            "source_path": "photos",
            "target_dir": "/mnt/user/restore",
            "destination_path": "/mnt/user/restore/photos",
            "lines": ["done"],
        },
        "new-running": {
            "restore_id": "new-running",
            "state": "running",
            "phase": "extract",
            "started_at": "2026-06-29T10:00:00",
            "job_key": "appdata_local",
            "archive": "appdata-archive",
            "source_path": "appdata",
            "target_dir": "/mnt/user/restore",
            "lines": ["line1", "line2"],
        },
    })

    data = restore_api.list_restore_runs(config, limit=10)

    assert [row["restore_id"] for row in data["runs"]] == ["new-running"]
    assert [row["restore_id"] for row in data["active"]] == ["new-running"]
    assert data["runs"][0]["lines"] == ["line1", "line2"]


def test_loading_restore_runs_marks_stale_running_runs_aborted(tmp_path: Path):
    restore_api._RESTORE_RUNS_LOADED = False
    restore_api._RESTORE_RUNS.clear()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    fp = tmp_path / "config" / "restore-runs.json"
    fp.parent.mkdir(parents=True)
    fp.write_text(
        """{
  "schema_version": 1,
  "runs": {
    "stale": {
      "restore_id": "stale",
      "state": "running",
      "phase": "extract",
      "started_at": "2026-06-29T09:00:00",
      "job_key": "appdata_local",
      "archive": "appdata-archive",
      "lines": []
    }
  }
}
""",
        encoding="utf-8",
    )

    runs = restore_api.list_restore_runs(config, limit=10)
    history = restore_api.list_restore_history(config, limit=10)

    assert runs["runs"] == []
    assert runs["active"] == []
    assert history["runs"][0]["restore_id"] == "stale"
    assert history["runs"][0]["state"] == "aborted"
    assert history["runs"][0]["phase"] == "aborted"


def test_restore_history_keeps_all_details(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    for idx in range(105):
        restore_api._record_restore_history(config, {
            "restore_id": f"run-{idx}",
            "state": "done",
            "started_at": f"2026-06-29T08:00:00.{idx:03d}",
            "finished_at": f"2026-06-29T08:00:01.{idx:03d}",
            "job_key": "appdata_local",
            "archive": "appdata-archive",
            "lines": [f"line-{idx}"],
        }, "test")

    history = restore_api.list_restore_history(config, limit=200)
    runs_dir = tmp_path / "config" / "restore-history" / "runs"

    assert history["total"] == 105
    assert history["runs"][0]["restore_id"] == "run-104"
    assert (runs_dir / "run-0.json").exists()
    assert (runs_dir / "run-104.json").exists()


def test_restore_history_delete_removes_index_and_detail(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    restore_api._record_restore_history(config, {
        "restore_id": "delete-me",
        "state": "done",
        "started_at": "2026-06-29T08:00:00",
        "finished_at": "2026-06-29T08:00:01",
        "job_key": "appdata_local",
        "archive": "appdata-archive",
        "lines": ["restore done"],
    }, "test")
    runs_dir = tmp_path / "config" / "restore-history" / "runs"

    result = restore_api.delete_restore_history_entry(config, "delete-me")
    history = restore_api.list_restore_history(config, limit=0)

    assert result["deleted"] is True
    assert result["detail_deleted"] is True
    assert history["total"] == 0
    assert not (runs_dir / "delete-me.json").exists()


def test_multi_selection_simulation_survives_async_state_and_history(tmp_path, monkeypatch):
    restore_api._RESTORE_RUNS_LOADED = True
    restore_api._RESTORE_RUNS.clear()
    config = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    paths = ['Backup/Test1', 'Backup/Test2']
    items = [{'path': p, 'destination_path': '/mnt/user/restore/' + p.split('/')[-1], 'skipped': False} for p in paths]
    def simulate(*args, **kwargs):
        assert kwargs['source_paths'] == paths
        assert kwargs['dry_run'] is True
        return {'dry_run': True, 'items': items, 'destination_path': '/mnt/user/restore'}
    class ImmediateThread:
        def __init__(self, target, **kwargs): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(restore_api, 'start_restore', simulate)
    monkeypatch.setattr(restore_api.threading, 'Thread', ImmediateThread)
    result = restore_api.start_restore_async(config, 'job-id', 'archive', '', '/mnt/user/restore', 'skip',
                                            source_paths=paths, dry_run=True)
    state = restore_api.get_restore_state(config, result['restore_id'])
    assert state['state'] == 'done'
    assert state['dry_run'] is True
    assert state['source_paths'] == paths
    assert state['items'] == items
    detail = restore_api.get_restore_history_detail(config, result['restore_id'])
    assert detail['dry_run'] is True
    assert detail['source_paths'] == paths
    assert detail['items'] == items


def test_restore_diagnostics_do_not_write_state_per_line(tmp_path, monkeypatch):
    restore_api._RESTORE_RUNS_LOADED = True
    restore_api._RESTORE_RUNS.clear()
    config = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    writes = []
    real_persist = restore_api._persist_restore_runs
    def persist(config):
        writes.append(1)
        real_persist(config)
    def restore(*args, progress_cb, status_cb, **kwargs):
        status_cb({'phase': 'extract', 'staging_path': '/destination/.bbui-restore-stage-example'})
        for index in range(5000):
            progress_cb(f'diagnostic {index}')
        status_cb({'phase': 'validate'})
        status_cb({'phase': 'publish'})
        return {'counts': {'files': 5000, 'directories': 2, 'symlinks': 0, 'other': 0},
                'counts_complete': True, 'destination_path': '/destination'}
    class ImmediateThread:
        def __init__(self, target, **kwargs): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(restore_api, '_persist_restore_runs', persist)
    monkeypatch.setattr(restore_api, 'start_restore', restore)
    monkeypatch.setattr(restore_api.threading, 'Thread', ImmediateThread)
    result = restore_api.start_restore_async(config, 'job-id', 'archive', 'folder', '/destination', 'skip')
    state = restore_api.get_restore_state(config, result['restore_id'])
    assert state['state'] == 'done'
    assert state['counts']['files'] == 5000
    assert state['staging_path'] == ''
    assert state['counts_complete']
    assert len(state['lines']) <= 80
    assert len(writes) == 6  # start, prepare, extract, validate, publish, finish
    history = restore_api.get_restore_history_detail(config, result['restore_id'])
    assert history['counts'] == state['counts']
    assert history['counts_complete']
    assert len(history['lines']) <= 200


def test_failed_restore_keeps_diagnostics_without_claiming_final_counts(tmp_path, monkeypatch):
    restore_api._RESTORE_RUNS_LOADED = True
    restore_api._RESTORE_RUNS.clear()
    config = {'BACKUP_SCRIPTS_DIR': str(tmp_path)}
    def restore(*args, status_cb, **kwargs):
        status_cb({'phase': 'publish', 'counts': {'files': 1, 'directories': 0},
                   'items': [{'path': 'one', 'restored': True}]})
        raise OSError('Destination is full')
    class ImmediateThread:
        def __init__(self, target, **kwargs): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(restore_api, 'start_restore', restore)
    monkeypatch.setattr(restore_api.threading, 'Thread', ImmediateThread)
    result = restore_api.start_restore_async(config, 'job-id', 'archive', 'folder', '/destination', 'skip')
    state = restore_api.get_restore_state(config, result['restore_id'])
    assert state['state'] == 'error'
    assert state['counts_complete'] is False
    assert state['items'][0]['restored']
    assert state['error'] == 'Destination is full'
    detail = restore_api.get_restore_history_detail(config, result['restore_id'])
    assert detail['counts_complete'] is False
    assert 'Destination is full' in '\n'.join(detail['lines'])
