from __future__ import annotations

import sys
from pathlib import Path

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
from settings_transfer_api import _canonical_import_jobs  # noqa: E402


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
        normalize_source_paths(str(missing))
