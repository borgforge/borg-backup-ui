"""UUID recovery snapshots are classified without changing migration data (#519)."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from migration_api import cleanup_migration_backups, plan_migration_backup_cleanup


JOURNALS = {"job_ids_v1": "job-id-migration.json", "job_settings_v1": "job-settings-migration.json"}
RUN_ID = "143db583-d8d0-4119-b290-10d51a69e28e"


def uuid_fixture(tmp_path, migration_id="job_ids_v1", **changes):
    root = tmp_path / "plugin"
    cfg = {"BACKUP_SCRIPTS_DIR": str(root)}
    snapshot = root / "config/migration-backups" / f"{migration_id}-{RUN_ID}"
    snapshot.mkdir(parents=True)
    (snapshot / "0.before").write_bytes(b"original recovery data\n")
    (snapshot / "0.after").write_bytes(b"migrated recovery data\n")
    data = {"migration_id": migration_id, "run_id": RUN_ID, "status": "applied",
            "timestamp": "2026-09-07T10:00:00Z", "backup_directory": str(snapshot),
            "operations": [], **changes}
    journal = root / "config" / JOURNALS[migration_id]
    journal.write_text(json.dumps(data))
    return cfg, snapshot, journal


def fingerprint(paths):
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}


@pytest.mark.parametrize("migration_id", JOURNALS)
@pytest.mark.parametrize("scripts_suffix", [False, True])
def test_uuid_snapshots_are_retained_without_changing_originals(tmp_path, migration_id, scripts_suffix):
    cfg, snapshot, journal = uuid_fixture(tmp_path, migration_id)
    if scripts_suffix:
        cfg["BACKUP_SCRIPTS_DIR"] += "/scripts"
    before = fingerprint([journal, *snapshot.iterdir()])
    plan = cleanup_migration_backups(cfg)
    assert plan["applied"] is False
    assert plan["summary"] == {"total": 1, "keep": 1, "delete": 0, "skipped": 0, "delete_size_bytes": 0}
    row = plan["keep"][0]
    assert row["migration_id"] == migration_id
    assert row["timestamp"] == "20260907T100000000000Z"
    assert row["status"] == "applied"
    assert row["reason"] == "latest_active_snapshot"
    assert fingerprint(before) == before
    cleanup_migration_backups(cfg, dry_run=False)
    assert fingerprint(before) == before


@pytest.mark.parametrize("status", ["pending", "failed", "blocked", "unknown", "not_required", "", None, {}])
def test_incomplete_or_unknown_uuid_status_is_protected_even_when_inactive(tmp_path, monkeypatch, status):
    cfg, snapshot, _ = uuid_fixture(tmp_path, status=status)
    monkeypatch.setattr("migration_api._active_migration_ids", lambda: set())
    state = snapshot.parent.parent / "migration-state.json"
    state.write_text(json.dumps({"migrations": {"job_ids_v1": {"state": "applied"}}}))
    result = cleanup_migration_backups(cfg, dry_run=False)
    assert result["deleted_count"] == 0
    assert result["skipped"][0]["reason"].startswith("protected_status:")
    assert snapshot.exists()


@pytest.mark.parametrize("fault,reason", [
    ("missing", "missing_journal"), ("json", "invalid_journal"), ("utf8", "invalid_journal"),
    ("array", "invalid_journal"), ("unreadable", "invalid_journal"),
    ("migration_id", "journal_mismatch"), ("run_id", "journal_mismatch"),
    ("backup_directory", "journal_mismatch"), ("relative_directory", "journal_mismatch"),
    ("missing_directory", "invalid_journal"), ("timestamp", "invalid_journal"),
    ("naive_timestamp", "invalid_journal"), ("missing_timestamp", "invalid_journal"),
    ("journal_symlink", "invalid_journal"),
])
def test_bad_journals_preserve_snapshots_and_report_the_reason(tmp_path, monkeypatch, fault, reason):
    cfg, snapshot, journal = uuid_fixture(tmp_path)
    data = json.loads(journal.read_text())
    if fault == "missing":
        journal.unlink()
    elif fault == "json":
        journal.write_text("{")
    elif fault == "utf8":
        journal.write_bytes(b"\xff")
    elif fault == "array":
        journal.write_text("[]")
    elif fault == "unreadable":
        read = Path.read_text
        def denied(path, *args, **kwargs):
            if path == journal:
                raise PermissionError("denied")
            return read(path, *args, **kwargs)
        monkeypatch.setattr(Path, "read_text", denied)
    elif fault == "journal_symlink":
        target = journal.with_suffix(".original")
        journal.rename(target)
        journal.symlink_to(target)
    else:
        if fault in ("migration_id", "run_id"):
            data[fault] = "another-run"
        elif fault == "backup_directory":
            elsewhere = tmp_path / "elsewhere" / snapshot.name
            elsewhere.mkdir(parents=True)
            data[fault] = str(elsewhere)
        elif fault == "relative_directory":
            data["backup_directory"] = snapshot.name
        elif fault == "missing_directory":
            del data["backup_directory"]
        elif fault == "missing_timestamp":
            del data["timestamp"]
        else:
            data["timestamp"] = "2026-09-07T10:00:00" if fault == "naive_timestamp" else "not-a-date"
        journal.write_text(json.dumps(data))
    before = fingerprint(snapshot.iterdir())
    result = cleanup_migration_backups(cfg, dry_run=False)
    assert result["deleted_count"] == 0
    assert result["skipped"][0]["reason"] == reason
    assert result["skipped"][0]["migration_id"] == "job_ids_v1"
    assert fingerprint(before) == before


def test_unmatched_old_run_does_not_borrow_current_journal_status(tmp_path):
    cfg, snapshot, _ = uuid_fixture(tmp_path)
    other = snapshot.with_name("job_ids_v1-243db583-d8d0-4119-b290-10d51a69e28e")
    other.mkdir()
    result = cleanup_migration_backups(cfg, dry_run=False, keep_per_active_id=1)
    assert result["deleted_count"] == 0
    assert result["keep"][0]["name"] == snapshot.name
    assert result["skipped"][0]["name"] == other.name
    assert result["skipped"][0]["reason"] == "journal_mismatch"


def test_uuid_and_timestamp_snapshots_share_chronological_retention(tmp_path):
    cfg, snapshot, journal = uuid_fixture(tmp_path, timestamp="2026-09-07T12:00:00+02:00")
    # Same second: the UUID journal's timestamp is older than the fractional snapshot.
    newer = snapshot.with_name("job_ids_v1-20260907T100000100000Z-abcdef12")
    newer.mkdir()
    (newer / "manifest.json").write_text('{"status":"applied"}')
    before = fingerprint([journal, *snapshot.iterdir()])
    plan = cleanup_migration_backups(cfg, keep_per_active_id=1)
    assert [row["name"] for row in plan["delete"]] == [snapshot.name]
    assert [row["name"] for row in plan["keep"]] == [newer.name]
    assert fingerprint(before) == before
    result = cleanup_migration_backups(cfg, dry_run=False, keep_per_active_id=1)
    assert result["deleted_count"] == 1
    assert not snapshot.exists()
    assert newer.exists()
    assert fingerprint([journal]) == {journal: before[journal]}


def test_symlink_snapshot_is_not_deleted_or_followed(tmp_path):
    cfg, snapshot, _ = uuid_fixture(tmp_path)
    linked = snapshot.with_name("storage_objects_v1-20260701T120000Z-abcd1234")
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "keep.txt"
    protected.write_text("keep")
    linked.symlink_to(outside, target_is_directory=True)
    result = cleanup_migration_backups(cfg, dry_run=False)
    assert result["deleted_count"] == 0
    assert result["skipped"][0]["reason"] == "unsafe_snapshot_path"
    assert linked.is_symlink()
    assert protected.read_text() == "keep"


def test_real_job_migrations_are_recognized_and_never_rerun_by_cleanup(tmp_path, monkeypatch):
    from test_job_id_migration import main_fixture
    from migrations import job_ids_v1, job_settings_v1
    cfg, _ = main_fixture(tmp_path)
    job_ids_v1.apply(cfg)
    job_settings_v1.apply(cfg)
    before = fingerprint(p for p in tmp_path.rglob("*") if p.is_file())
    def unexpected(*args):
        pytest.fail("Cleanup must not detect or apply migrations")
    for migration in (job_ids_v1, job_settings_v1):
        monkeypatch.setattr(migration, "apply", unexpected)
        monkeypatch.setattr(migration, "detect", unexpected)
    result = cleanup_migration_backups(cfg)
    assert {row["migration_id"] for row in result["keep"]} == set(JOURNALS)
    assert result["summary"]["delete"] == result["summary"]["skipped"] == 0
    assert fingerprint(before) == before
