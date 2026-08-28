import io
import json
import logging
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
RUNTIME_ROOT = ROOT / "runtime"
for path in (ROOT, API_ROOT, RUNTIME_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from runtime.lib.backup_job import BackupJobConfig
from runtime.lib.borg_runner import BorgConfig, BorgRunner
from wizard_api import _validate_exclude_paths


def test_exclusion_must_exist_below_a_source(tmp_path: Path):
    source = tmp_path / "source"
    excluded = source / "cache"
    outside = tmp_path / "outside"
    excluded.mkdir(parents=True)
    outside.mkdir()

    assert _validate_exclude_paths([str(excluded)], [str(source)]) == [str(excluded)]
    with pytest.raises(ValueError, match="below a selected source"):
        _validate_exclude_paths([str(outside)], [str(source)])
    with pytest.raises(ValueError, match="does not exist"):
        _validate_exclude_paths([str(source / "missing")], [str(source)])


def test_backup_job_config_reads_exclusions_as_json(tmp_path: Path):
    cfg = BackupJobConfig.from_config({
        "BACKUP_PATHS_JSON": json.dumps([str(tmp_path / "source")]),
        "BACKUP_EXCLUDE_PATHS_JSON": json.dumps([str(tmp_path / "source" / "cache")]),
    })

    assert cfg.exclude_paths == [tmp_path / "source" / "cache"]


def test_backup_job_config_preserves_multiple_source_paths_with_spaces(tmp_path: Path):
    first = tmp_path / "Intel UHD Graphics 630 - Treiber"
    second = tmp_path / "Second source"

    cfg = BackupJobConfig.from_config({
        "BACKUP_PATHS_JSON": json.dumps([str(first), str(second)]),
        "BACKUP_EXCLUDE_PATHS_JSON": "[]",
    })

    assert cfg.backup_paths == [first, second]


def test_borg_create_uses_safe_path_prefix_patterns(monkeypatch, tmp_path: Path):
    captured = {}

    class Process:
        def __init__(self, command, **kwargs):
            captured["command"] = command
            self.stdout = io.StringIO("")
            self.returncode = 0

        def wait(self):
            return self.returncode

    monkeypatch.setattr("runtime.lib.borg_runner.subprocess.Popen", Process)
    runner = BorgRunner(BorgConfig(repo=str(tmp_path / "repo"), max_runtime_hours=0))

    result = runner.create(
        [tmp_path / "source"],
        "test-backup",
        exclude_paths=[tmp_path / "source" / "cache"],
    )

    assert result == 0
    command = captured["command"]
    index = command.index("--exclude")
    assert command[index + 1] == f"pp:{str(tmp_path / 'source' / 'cache').lstrip('/')}"
    assert index < next(i for i, arg in enumerate(command) if "::test-backup-" in arg)


def test_borg_prune_scopes_retention_to_archive_prefix(monkeypatch, tmp_path: Path, caplog):
    captured = {}

    class Process:
        def __init__(self, command, **kwargs):
            captured["command"] = command
            self.stdout = io.StringIO("")
            self.returncode = 0

        def wait(self):
            return self.returncode

    monkeypatch.setattr("runtime.lib.borg_runner.subprocess.Popen", Process)
    runner = BorgRunner(BorgConfig(repo=str(tmp_path / "repo"), max_runtime_hours=0))
    caplog.set_level(logging.INFO)

    result = runner.prune("nas-backup")

    assert result == 0
    command = captured["command"]
    assert command[0:4] == ["borg", "prune", "--verbose", "--list"]
    index = command.index("--glob-archives")
    assert command[index + 1] == "nas-backup-*"
    assert index < command.index("--keep-daily")
    assert command[-1] == str(tmp_path / "repo")
    assert (
        "Borg prune: applying retention only to archives matching nas-backup-* "
        "(keep: 7d/4w/6m/2y)"
    ) in caplog.text


def test_borg_prune_logs_unfiltered_fallback(monkeypatch, tmp_path: Path, caplog):
    class Process:
        def __init__(self, command, **kwargs):
            self.stdout = io.StringIO("")
            self.returncode = 0

        def wait(self):
            return self.returncode

    monkeypatch.setattr("runtime.lib.borg_runner.subprocess.Popen", Process)
    runner = BorgRunner(BorgConfig(repo=str(tmp_path / "repo"), max_runtime_hours=0))
    caplog.set_level(logging.INFO)

    assert runner.prune() == 0
    assert (
        "Borg prune: applying retention to all repository archives "
        "(keep: 7d/4w/6m/2y)"
    ) in caplog.text
