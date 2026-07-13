from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
for candidate in (ROOT, API_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from inventory_store import InventoryAccessError  # noqa: E402
from job_source_paths import (  # noqa: E402
    SourcePathValidationError,
    convert_legacy_source_paths,
)
from migrations import job_source_paths_v1, registry  # noqa: E402
from settings_transfer_api import _canonical_import_jobs  # noqa: E402


def _config(root: Path) -> dict:
    return {"BACKUP_SCRIPTS_DIR": str(root)}


def _write_legacy_job(root: Path, job_key: str, value: str) -> Path:
    jobs_dir = root / "config" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    path = jobs_dir / f"{job_key}.json"
    path.write_text(
        json.dumps({
            "schema_version": 2,
            "job_key": job_key,
            "name": job_key,
            "repository_key": f"repo_{job_key}",
            "paths": {"default": value},
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _read_events(root: Path) -> list[dict]:
    path = root / "config" / "migrations.log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_migration_preserves_one_existing_source_path_with_spaces(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "Intel UHD Graphics 630 - Treiber"
    source.mkdir()
    job_file = _write_legacy_job(tmp_path, "drivers_local", str(source))
    monkeypatch.setattr(registry, "MIGRATIONS", [job_source_paths_v1])

    result = registry.run_startup_migrations(_config(tmp_path))
    job = json.loads(job_file.read_text(encoding="utf-8"))
    state = json.loads((tmp_path / "config" / "migration-state.json").read_text(encoding="utf-8"))
    backups = list((tmp_path / "config" / "migration-backups").glob("job_source_paths_v1-*"))

    assert result["applied"] == ["job_source_paths_v1"]
    assert job["schema_version"] == 3
    assert job["source_paths"] == [str(source)]
    assert "paths" not in job
    assert state["migrations"]["job_source_paths_v1"]["state"] == "applied"
    assert len(backups) == 1
    assert (backups[0] / job_file.name).is_file()
    assert (backups[0] / "manifest.json").is_file()
    assert [event["event"] for event in _read_events(tmp_path) if event.get("migration_id") == "job_source_paths_v1"] == [
        "migration_started",
        "migration_completed",
    ]


def test_migration_preserves_multiple_existing_paths_with_spaces(tmp_path: Path) -> None:
    first = tmp_path / "First source"
    second = tmp_path / "Second source"
    first.mkdir()
    second.mkdir()
    job_file = _write_legacy_job(tmp_path, "data_local", f"{first} {second}")

    result = job_source_paths_v1.apply(_config(tmp_path))
    job = json.loads(job_file.read_text(encoding="utf-8"))

    assert result["status"] == "applied"
    assert job["source_paths"] == [str(first), str(second)]


def test_migration_is_idempotent_after_registry_final_state(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_legacy_job(tmp_path, "data_local", str(source))
    monkeypatch.setattr(registry, "MIGRATIONS", [job_source_paths_v1])

    first = registry.run_startup_migrations(_config(tmp_path))
    backup_count = len(list((tmp_path / "config" / "migration-backups").glob("job_source_paths_v1-*")))
    second = registry.run_startup_migrations(_config(tmp_path))

    assert first["applied"] == ["job_source_paths_v1"]
    assert second["results"]["job_source_paths_v1"]["status"] == "skipped"
    assert second["results"]["job_source_paths_v1"]["previous_state"] == "applied"
    assert len(list((tmp_path / "config" / "migration-backups").glob("job_source_paths_v1-*"))) == backup_count


def test_ambiguous_legacy_paths_fail_without_changing_any_job(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "first"
    first.mkdir()
    missing = tmp_path / "missing"
    job_file = _write_legacy_job(tmp_path, "data_local", f"{first} {missing}")
    original = job_file.read_bytes()
    monkeypatch.setattr(registry, "MIGRATIONS", [job_source_paths_v1])

    result = registry.run_startup_migrations(_config(tmp_path))
    state = json.loads((tmp_path / "config" / "migration-state.json").read_text(encoding="utf-8"))
    failure = result["results"]["job_source_paths_v1"]["details"]

    assert result["failed"] == ["job_source_paths_v1"]
    assert job_file.read_bytes() == original
    assert not (tmp_path / "config" / "migration-backups").exists()
    assert state["migrations"]["job_source_paths_v1"]["state"] == "failed"
    assert "cannot be migrated unambiguously" in failure["error"]
    assert "data_local.json" == failure["failed_jobs"][0]["job_file"]
    assert failure["rollback_status"] == "not_required"
    assert _read_events(tmp_path)[0]["event"] == "migration_failed"


def test_write_failure_restores_original_job(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    job_file = _write_legacy_job(tmp_path, "data_local", str(source))
    original = job_file.read_bytes()
    real_write = job_source_paths_v1.atomic_write_bytes
    failed_once = False

    def fail_canonical_job_write(path: Path, content: bytes, **kwargs) -> None:
        nonlocal failed_once
        if path == job_file and b'"source_paths"' in content and not failed_once:
            failed_once = True
            raise InventoryAccessError("simulated job write failure")
        real_write(path, content, **kwargs)

    monkeypatch.setattr(job_source_paths_v1, "atomic_write_bytes", fail_canonical_job_write)

    result = job_source_paths_v1.apply(_config(tmp_path))

    assert result["status"] == "failed"
    assert result["details"]["rollback_status"] == "completed"
    assert job_file.read_bytes() == original


def test_old_job_bundle_is_upgraded_only_at_import_boundary(tmp_path: Path) -> None:
    source = tmp_path / "Source with spaces"
    source.mkdir()
    jobs = [{
        "schema_version": 2,
        "job_key": "data_local",
        "paths": {"default": str(source)},
    }]

    upgraded = _canonical_import_jobs(jobs)

    assert upgraded[0]["schema_version"] == 3
    assert upgraded[0]["source_paths"] == [str(source)]
    assert "paths" not in upgraded[0]
    assert "paths" in jobs[0]


def test_old_job_bundle_reports_ambiguous_paths_clearly(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    jobs = [{
        "schema_version": 2,
        "job_key": "data_local",
        "paths": {"default": f"{existing} {tmp_path / 'missing'}"},
    }]

    with pytest.raises(ValueError, match="Imported job 'data_local'.*cannot be migrated unambiguously"):
        _canonical_import_jobs(jobs)


def test_single_missing_path_with_spaces_is_structurally_unambiguous(tmp_path: Path) -> None:
    missing = tmp_path / "Missing source with spaces"

    assert convert_legacy_source_paths(str(missing), job_key="data_local") == [str(missing)]
    with pytest.raises(SourcePathValidationError, match="must be stored as a JSON array"):
        from job_source_paths import normalize_source_paths
        normalize_source_paths(str(missing))
