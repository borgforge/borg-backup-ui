"""Main-format data preservation and interrupted job-ID conversion (#486)."""

import copy
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT / "api", ROOT / "runtime", ROOT / "runtime/lib"):
    sys.path.insert(0, str(folder))

from migrations import job_ids_v1 as migration
from job_identity import validate_job_id


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def main_fixture(tmp_path):
    root = tmp_path / "plugin"
    status = tmp_path / "array/status"
    restore = tmp_path / "array/restore-status"
    status.mkdir(parents=True)
    restore.mkdir(parents=True)
    config = {"BACKUP_SCRIPTS_DIR": str(root), "BORG_SCRIPTS_DIR": str(ROOT / "runtime/scripts"),
              "STATUS_DIR": str(status), "RESTORE_TEST_STATUS_DIR": str(restore)}
    cfg = root / "config"
    jobs = []
    for key, name in [("custom_type_local", "Zulu"), ("other_local", "Alpha")]:
        job = {"schema_version": 3, "job_key": key, "backup_type": key.removesuffix("_local"),
               "location": "local", "name": name, "repository_key": "shared",
               "archive_prefixes": [key.removesuffix("_local") + "-backup", name + "-prior-backup"],
               "source_paths": [str(tmp_path / "source")], "icon": "", "icon_color": "",
               "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-02-01T00:00:00Z",
               "retention": {"daily": "7", "weekly": "4", "monthly": "6", "yearly": "3"},
               "restore_test_policy": {"mode": "scheduled", "validity_days": 30, "level": 3},
               "extension": {"must_survive": [1, "example"]}}
        jobs.append(job)
        write(cfg / "jobs" / (key + ".json"), job)
        write(status / f"2026-09-01_12-00-00_{key}.status", {
            "backup_type": job["backup_type"], "location": "local", "timestamp": "2026-09-01 12:00:00",
            "status": "success", "repository_check_status": "ok", "repository_check_date": "2026-08-30",
            "archive_name": job["archive_prefixes"][0] + "-2026-09-01_12-00-00",
            "original_size": 1048576, "log_file": "/example/logs/old.log", "unknown": {"x": 1},
        })
        write(restore / (key + ".test"), {"type": job["backup_type"], "location": "local",
              "test_date": "2026-08-30 10:00:00", "test_result": "success", "steps": [{"evidence": 1}],
              "report_id": "keep-independent-report-id"})
    cfg.joinpath("backup.conf").write_text(f'STATUS_DIR="{status}"\nRESTORE_TEST_STATUS_DIR="{restore}"\n')
    with cfg.joinpath("backup.conf").open("a") as handle:
        handle.write(f'GLOBAL_BORG_CACHE_BASE="{tmp_path / "cache"}"\n')
    keys = [j["job_key"] for j in jobs]
    write(cfg / "repositories.json", {"schema_version": 1, "repositories": [
        {"repository_key": "shared", "used_by": keys, "source_job_keys": keys, "keep": {"stats": 3}},
    ]})
    write(cfg / "schedules.json", {keys[0]: {"cron": "0 9 * * *", "enabled": True},
          keys[1]: {"cron": "0 10 * * *", "enabled": False}, "restore_test": {"cron": "0 8 * * *"}})
    for path, week in [(status.parent / "weekly-snapshots.json", "2026-W36"),
                       (status / "weekly-snapshots.json", "2026-W30")]:
        write(path, {keys[0]: [{"week": week, "size": 1234}], "deleted_usb": [{"week": week, "size": 50}]})
    run = {"restore_id": "keep-run-id", "job_key": keys[0], "state": "completed", "evidence": {"x": 1}}
    write(cfg / "restore-runs.json", {"runs": {"keep-run-id": run}})
    write(cfg / "restore-history/index.json", {"runs": [run]})
    write(cfg / "restore-history/runs/keep-run-id.json", run)
    write(cfg / "notification-queue.json", {"queue": [{"id": "event-id", "job_key": keys[0], "attempts": 2}]})
    write(cfg / "notification-deliveries.json", {"deliveries": [
        {"job_key": keys[1], "id": "delivered"}, {"job_key": "deleted_usb", "id": "historical"}]})
    write(cfg / "notification-state.json", {"last_sent": {f"backup_overdue:{keys[0]}:2026-09-01 10:00:00": 1234}})
    write(cfg / "runtime-recovery.json", {"entries": [
        {"id": "recovery-id", "backup_type": jobs[0]["backup_type"], "backup_location": "local", "state": "recovered"}]})
    return config, jobs


def json_files(root):
    return {str(p): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and p.suffix in (".json", ".status", ".test")}


def test_preserves_main_payloads_and_references_and_repeats_without_changes(tmp_path):
    config, jobs = main_fixture(tmp_path)
    before = json_files(tmp_path)
    mtimes = {path: Path(path).stat().st_mtime_ns for path in before}
    assert migration.detect(config)["required"] is True
    result = migration.apply(config)
    assert result["status"] == "applied"
    plan = json.loads(migration._journal(config).read_text())
    assignment = plan["assignment"]
    assert len(set(assignment.values())) == 2
    for job in jobs:
        job_id = validate_job_id(assignment[job["job_key"]])
        source = Path(config["BACKUP_SCRIPTS_DIR"]) / "config/jobs" / (job["job_key"] + ".json")
        target = source.with_name(job_id + ".json")
        actual = json.loads(target.read_text())
        expected = {**job, "job_id": job_id, "job_key": job_id, "schema_version": 4,
                    "cache_subdir": "local_" + job["backup_type"],
                    "check_flag_name": ".last_check_" + job["backup_type"],
                    "archive_prefix": job["backup_type"] + "-backup"}
        assert actual == expected
        assert not source.exists()
    for op in plan["operations"]:
        assert Path(op["before"]).read_bytes() == before[op["source"]]
        assert Path(op["target"]).stat().st_mtime_ns == mtimes[op["source"]]
        old, new = json.loads(before[op["source"]]), json.loads(Path(op["target"]).read_bytes())
        if op["source"].endswith((".status", ".test")):
            assert {k: v for k, v in new.items() if k != "job_id"} == old
        if op["source"].endswith("weekly-snapshots.json"):
            assert new == {assignment.get(k, k): v for k, v in old.items()}
    cfg = Path(config["BACKUP_SCRIPTS_DIR"]) / "config"
    assert json.loads((cfg / "notification-deliveries.json").read_text())["deliveries"][1]["job_key"] == "deleted_usb"
    assert json.loads((cfg / "schedules.json").read_text())["restore_test"] == {"cron": "0 8 * * *"}
    assert json.loads((cfg / "restore-runs.json").read_text())["runs"]["keep-run-id"]["job_key"] == assignment[jobs[0]["job_key"]]
    after = json_files(tmp_path)
    assert migration.detect(config)["required"] is False
    assert migration.apply(config)["status"] == "not_required"
    assert json_files(tmp_path) == after


def test_interrupted_write_reuses_saved_ids_and_originals(monkeypatch, tmp_path):
    config, _ = main_fixture(tmp_path)
    original = migration._apply_operation
    count = 0

    def interrupt(op):
        nonlocal count
        original(op)
        count += 1
        if count == 2:
            raise OSError("simulated interruption after two converted files")

    monkeypatch.setattr(migration, "_apply_operation", interrupt)
    with pytest.raises(OSError):
        migration.apply(config)
    plan = json.loads(migration._journal(config).read_text())
    assert migration.detect(config)["required"] is True
    monkeypatch.setattr(migration, "_apply_operation", original)
    assert migration.apply(config)["status"] == "applied"
    assert json.loads(migration._journal(config).read_text())["assignment"] == plan["assignment"]


def test_refuses_changed_source_on_retry(monkeypatch, tmp_path):
    config, _ = main_fixture(tmp_path)
    original = migration._apply_operation
    monkeypatch.setattr(migration, "_apply_operation", lambda op: (_ for _ in ()).throw(OSError("interrupt")))
    with pytest.raises(OSError):
        migration.apply(config)
    plan = json.loads(migration._journal(config).read_text())
    source = Path(plan["operations"][0]["source"])
    changed = json.loads(source.read_text())
    changed["name"] = "Edited outside migration"
    write(source, changed)
    monkeypatch.setattr(migration, "_apply_operation", original)
    with pytest.raises(ValueError, match="changed data"):
        migration.apply(config)
    assert json.loads(source.read_text()) == changed


def test_active_reference_conflict_changes_no_job_files(tmp_path):
    config, _ = main_fixture(tmp_path)
    schedules = Path(config["BACKUP_SCRIPTS_DIR"]) / "config/schedules.json"
    write(schedules, {"missing_job": {"cron": "0 9 * * *"}})
    before = json_files(tmp_path)
    with pytest.raises(ValueError, match="Unresolved active"):
        migration.apply(config)
    assert json_files(tmp_path) == before


def test_storage_unavailable_and_live_worker_block_before_writes(monkeypatch, tmp_path):
    import jobs_api
    import status
    config, _ = main_fixture(tmp_path)
    before = json_files(tmp_path)
    monkeypatch.setattr(status, "status_storage_unavailable_reason", lambda path: "array not mounted")
    with pytest.raises(RuntimeError, match="storage unavailable"):
        migration.apply(config)
    assert json_files(tmp_path) == before
    monkeypatch.setattr(status, "status_storage_unavailable_reason", lambda path: "")
    monkeypatch.setattr(jobs_api, "active_resource_locks", lambda config: [{"pid": os.getpid()}])
    with pytest.raises(RuntimeError, match="workers to finish"):
        migration.apply(config)
    assert json_files(tmp_path) == before


def test_conflicting_history_is_retained_without_claiming_an_owner(tmp_path):
    config, jobs = main_fixture(tmp_path)
    path = Path(config['STATUS_DIR']) / '2026-09-02_12-00-00_conflict.status'
    payload = {'job_key': jobs[0]['job_key'], 'backup_type': jobs[1]['backup_type'],
               'location': 'local', 'timestamp': '2026-09-02 12:00:00', 'status': 'success'}
    write(path, payload)
    restore = Path(config['RESTORE_TEST_STATUS_DIR']) / (jobs[0]['job_key'] + '.test')
    proof = json.loads(restore.read_text())
    proof['type'] = jobs[1]['backup_type']
    write(restore, proof)
    result = migration.apply(config)
    assert json.loads(path.read_text()) == payload
    assert json.loads(restore.read_text()) == proof
    assert len([r for r in result['details']['unresolved_history']
                if r['code'] == 'conflicting_historical_identity']) == 2


def test_retry_finishes_rename_interrupted_between_new_file_and_old_file_removal(tmp_path, monkeypatch):
    config, _ = main_fixture(tmp_path)
    original = migration._apply_operation
    def interrupted(op):
        migration.atomic_write_bytes(Path(op['target']), Path(op['after']).read_bytes())
        raise OSError('interrupted before source unlink')
    monkeypatch.setattr(migration, '_apply_operation', interrupted)
    with pytest.raises(OSError):
        migration.apply(config)
    plan = json.loads(migration._journal(config).read_text())
    assert Path(plan['operations'][0]['source']).exists()
    assert Path(plan['operations'][0]['target']).exists()
    assert migration.detect(config)['required'] is True
    monkeypatch.setattr(migration, '_apply_operation', original)
    assert migration.apply(config)['status'] == 'applied'
    assert not Path(plan['operations'][0]['source']).exists()


def test_migration_rejects_repository_reference_conflict_before_changes(tmp_path):
    config, _ = main_fixture(tmp_path)
    path = Path(config['BACKUP_SCRIPTS_DIR']) / 'config/repositories.json'
    data = json.loads(path.read_text())
    data['repositories'].append({'repository_key': 'another', 'used_by': ['custom_type_local']})
    write(path, data)
    before = json_files(tmp_path)
    with pytest.raises(ValueError, match='Conflicting active repository'):
        migration.apply(config)
    assert json_files(tmp_path) == before
