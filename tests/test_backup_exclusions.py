import io
import json
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


def test_backup_job_config_resolves_symlinked_source_root_for_borg(tmp_path: Path):
    real_root = tmp_path / "performance" / "appdata"
    visible_root = tmp_path / "user" / "appdata"
    real_cache = real_root / "cache"
    real_cache.mkdir(parents=True)
    visible_root.parent.mkdir(parents=True)
    visible_root.symlink_to(real_root, target_is_directory=True)

    cfg = BackupJobConfig.from_config({
        "BACKUP_PATHS_JSON": json.dumps([str(visible_root)]),
        "BACKUP_EXCLUDE_PATHS_JSON": json.dumps([str(visible_root / "cache")]),
    })

    assert cfg.backup_paths == [real_root]
    assert cfg.exclude_paths == [real_cache]


def test_backup_job_config_resolves_nested_path_below_symlinked_share_for_borg(tmp_path: Path):
    real_root = tmp_path / "performance" / "appdata"
    visible_root = tmp_path / "user" / "appdata"
    real_adguard = real_root / "adguard"
    real_cache = real_adguard / "cache"
    real_cache.mkdir(parents=True)
    visible_root.parent.mkdir(parents=True)
    visible_root.symlink_to(real_root, target_is_directory=True)

    cfg = BackupJobConfig.from_config({
        "BACKUP_PATHS_JSON": json.dumps([str(visible_root / "adguard")]),
        "BACKUP_EXCLUDE_PATHS_JSON": json.dumps([str(visible_root / "adguard" / "cache")]),
    })

    assert cfg.backup_paths == [real_adguard]
    assert cfg.exclude_paths == [real_cache]


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


def test_borg_prune_scopes_retention_to_archive_prefix(monkeypatch, tmp_path: Path):
    payload = json.dumps({'archives': [
        {'name': name, 'id': f'{index:064x}', 'time': timestamp}
        for index, (name, timestamp) in enumerate([
            ('nas-backup-new', '2026-09-06T12:00:00+00:00'),
            ('nas-backup-old', '2026-09-06T11:00:00+00:00'),
            ('foreign-old', '2026-09-06T10:00:00+00:00'),
        ], 1)
    ]})
    class Process:
        returncode = 0
        def communicate(self): return payload, None
    monkeypatch.setattr('runtime.lib.retention.subprocess.Popen', lambda *a, **kw: Process())
    commands = []
    monkeypatch.setattr('runtime.lib.borg_runner._run_borg', lambda command, *a: commands.append(command) or 0)
    runner = BorgRunner(BorgConfig(repo=str(tmp_path / 'repo'), keep_daily=1,
                                   keep_weekly=0, keep_monthly=0, keep_yearly=0))
    assert runner.prune('nas-backup') == 0
    assert len(commands) == 1
    assert commands[0][-3:] == ['--', str(tmp_path / 'repo'), 'nas-backup-old']


def test_borg_prune_rejects_unfiltered_scope(monkeypatch, tmp_path: Path, caplog):
    monkeypatch.setattr('runtime.lib.retention.subprocess.Popen',
                        lambda *a, **kw: pytest.fail('Empty ownership must not start Borg'))
    runner = BorgRunner(BorgConfig(repo=str(tmp_path / 'repo'), max_runtime_hours=0))
    assert runner.prune() == 2
    assert 'explicit nonempty prefix scope' in caplog.text
