from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
for candidate in (ROOT, API_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from job_source_paths import (  # noqa: E402
    SourcePathValidationError,
    convert_legacy_source_paths,
    normalize_source_paths,
)
from job_store import read_jobs  # noqa: E402
from legacy_job_transfer import convert_legacy_bundle  # noqa: E402
from migrations.immutable_job_id_v1 import PlanningError  # noqa: E402
from settings_transfer_api import import_jobs_bundle, preview_jobs_bundle  # noqa: E402


def _legacy_bundle(source, *, schema=2):
    return {"format": "bbui-job-bundle-v2", "jobs": [{
        "schema_version": schema, "job_key": "data_local", "backup_type": "data", "location": "local",
        "name": "Source paths", "repository_key": "repo", "paths": {"default": source},
    }], "repositories": [{"repository_key": "repo", "storage_key": "local", "relative_path": "repo",
                           "encryption": "none", "used_by": ["data_local"], "source_job_keys": ["data_local"]}],
        "storages": [{"storage_key": "local", "storage_type": "local", "location": "local",
                      "base_path": "/mnt/synthetic-repository-target"}], "schedules": {}}


@pytest.mark.parametrize("schema", [1, 2])
def test_old_job_bundle_is_upgraded_only_at_import_boundary(tmp_path: Path, monkeypatch, schema) -> None:
    source = tmp_path / "Source with spaces"
    source.mkdir()
    bundle = _legacy_bundle(str(source), schema=schema)
    original = deepcopy(bundle)
    target = tmp_path / "target"
    config = {"BACKUP_SCRIPTS_DIR": str(target)}
    monkeypatch.setattr("schedule_api._update_crontab", lambda lines: None)

    preview = preview_jobs_bundle(config, bundle)
    source_id = preview["legacy_source_ids"]["data_local"]
    assert UUID(source_id).version == 4
    assert preview["legacy_conversion"] is True
    assert not (target / "config/jobs").exists()
    result = import_jobs_bundle(config, bundle, dry_run=False, selected_jobs=[source_id],
                                legacy_source_ids=preview["legacy_source_ids"])
    destination_id = result["id_map"][source_id]
    upgraded = read_jobs(target / "config/jobs")[destination_id]
    assert destination_id != source_id
    assert upgraded["schema_version"] == 4
    assert upgraded["source_paths"] == [str(source)]
    assert "paths" not in upgraded and "job_key" not in upgraded
    assert bundle == original


def test_v3_transfer_preserves_ordered_source_paths_without_reconverting(tmp_path: Path, monkeypatch) -> None:
    paths = [str(tmp_path / "Source with spaces"), str(tmp_path / "Second source")]
    bundle = _legacy_bundle(paths)
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "target")}
    v3, _ = convert_legacy_bundle(config, bundle)
    original = deepcopy(v3)
    assert v3["format"] == "bbui-job-bundle-v3"
    source_id = v3["jobs"][0]["job_id"]
    monkeypatch.setattr("schedule_api._update_crontab", lambda lines: None)
    preview = preview_jobs_bundle(config, v3)
    assert preview["legacy_conversion"] is False
    result = import_jobs_bundle(config, v3, selected_jobs=[source_id], dry_run=False)
    job = read_jobs(tmp_path / "target/config/jobs")[result["id_map"][source_id]]
    assert job["source_paths"] == paths
    assert v3 == original


def test_old_job_bundle_blocks_ambiguous_paths_before_writing(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    ambiguous = f"{existing} {tmp_path / 'missing'}"
    bundle = _legacy_bundle(ambiguous)
    original = deepcopy(bundle)
    target = tmp_path / "target"
    config = {"BACKUP_SCRIPTS_DIR": str(target)}

    for operation in (preview_jobs_bundle, import_jobs_bundle):
        with pytest.raises(PlanningError) as failure:
            operation(config, bundle)
        assert failure.value.code == "invalid_source_paths"
        assert not (target / "config/jobs").exists()
    assert bundle == original
    with pytest.raises(SourcePathValidationError, match="cannot be migrated unambiguously"):
        convert_legacy_source_paths(ambiguous, job_key="data_local")


def test_single_missing_path_with_spaces_is_structurally_unambiguous(tmp_path: Path) -> None:
    missing = tmp_path / "Missing source with spaces"
    assert convert_legacy_source_paths(str(missing), job_key="data_local") == [str(missing)]
    with pytest.raises(SourcePathValidationError, match="must be stored as a JSON array"):
        normalize_source_paths(str(missing))
