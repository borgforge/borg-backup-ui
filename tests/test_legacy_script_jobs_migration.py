from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from jobs_api import discover_jobs  # noqa: E402
from migrations import legacy_script_jobs_v1  # noqa: E402
from migrations.registry import MIGRATIONS  # noqa: E402


def _write_legacy_script(path: Path, *, repo: str = "/mnt/backup/borg-backup-appdata", paths: str = "/mnt/user/appdata") -> None:
    path.write_text(
        f'''#!/usr/bin/env python3
import os

_DEFAULT_REPO = "{repo}"
_DEFAULT_PATHS = "{paths}"

def _load_env() -> dict:
    env = dict(os.environ)
    env.setdefault("JOB_NAME", "Appdata")
    env.setdefault("BORG_REPO", env.get("REPO_APPDATA_LOCAL", _DEFAULT_REPO))
    env.setdefault("BACKUP_PATHS", env.get("BACKUP_PATHS_APPDATA", _DEFAULT_PATHS))
    passphrase_file = env.get("BORG_PASSPHRASE_FILE_APPDATA_LOCAL", "/boot/config/borg-backup/secrets/.borg-passphrase-appdata_local")
    return env
''',
        encoding="utf-8",
    )


def test_legacy_script_jobs_are_migrated_to_metadata_before_discovery(tmp_path: Path) -> None:
    data_root = tmp_path / "borg-backup"
    scripts_dir = data_root / "scripts"
    scripts_dir.mkdir(parents=True)
    _write_legacy_script(scripts_dir / "borg_backup_appdata.py")
    config = {"BACKUP_SCRIPTS_DIR": str(data_root)}

    assert discover_jobs(scripts_dir, data_root) == []

    detected = legacy_script_jobs_v1.detect(config)
    assert detected["required"] is True
    assert detected["pending_count"] == 1

    result = legacy_script_jobs_v1.apply(config)
    assert result["status"] == "applied"
    assert result["details"]["migrated_count"] == 1

    meta_path = data_root / "config" / "jobs" / "appdata_local.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["standard"] == "wizard"
    assert metadata["runner"] == "scriptless-wizard-runner"
    assert metadata["repo"]["default"] == "/mnt/backup/borg-backup-appdata"
    assert metadata["paths"]["default"] == "/mnt/user/appdata"
    assert metadata["features"]["docker"] is True

    jobs = discover_jobs(scripts_dir, data_root)
    assert [job.key for job in jobs] == ["appdata_local"]
    assert jobs[0].standard == "wizard"
    assert jobs[0].script_path is None


def test_legacy_script_migration_disables_incomplete_imports(tmp_path: Path) -> None:
    data_root = tmp_path / "borg-backup"
    scripts_dir = data_root / "scripts"
    scripts_dir.mkdir(parents=True)
    _write_legacy_script(scripts_dir / "borg_backup_appdata.py", repo="", paths="")
    config = {"BACKUP_SCRIPTS_DIR": str(data_root)}

    result = legacy_script_jobs_v1.apply(config)

    assert result["status"] == "applied"
    migrated = result["details"]["migrated_jobs"][0]
    assert migrated["enabled"] is False
    assert "repository default missing" in migrated["review_reasons"]
    assert "source paths missing" in migrated["review_reasons"]

    metadata = json.loads((data_root / "config" / "jobs" / "appdata_local.json").read_text(encoding="utf-8"))
    assert metadata["enabled"] is False
    assert "Review and save the job before enabling it." in metadata["description"]


def test_legacy_script_migration_is_registered_before_other_startup_migrations() -> None:
    assert MIGRATIONS[0] is legacy_script_jobs_v1
