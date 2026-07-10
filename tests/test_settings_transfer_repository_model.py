from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from repositories_api import read_repository_store, write_repository_store  # noqa: E402
from repository_context import resolve_job_repository_context  # noqa: E402
from settings_transfer_api import export_jobs_bundle, import_jobs_bundle  # noqa: E402
from storage_objects_api import read_storage_store, write_storage_store  # noqa: E402


def _canonical_source(root: Path) -> tuple[dict, Path]:
    config = {"BACKUP_SCRIPTS_DIR": str(root)}
    secret = root / "secrets" / ".borg-passphrase-repo_appdata"
    secret.parent.mkdir(parents=True)
    secret.write_text("secret\n", encoding="utf-8")
    jobs_dir = root / "config" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "appdata_local.json").write_text(json.dumps({
        "schema_version": 2,
        "job_key": "appdata_local",
        "name": "Appdata",
        "backup_type": "appdata",
        "location": "local",
        "repository_key": "repo_appdata",
        "paths": {"default": "/mnt/user/appdata"},
    }) + "\n", encoding="utf-8")
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_appdata",
        "display_name": "Appdata",
        "storage_key": "storage_local",
        "relative_path": "borg-backup-appdata",
        "path_raw": "/mnt/backup/borg-backup-appdata",
        "passphrase_ref": str(secret),
        "encryption": "repokey-blake2",
    }]})
    return config, secret


def test_job_export_contains_canonical_repository_inventory(tmp_path: Path):
    config, secret = _canonical_source(tmp_path / "source")

    result = export_jobs_bundle(config)
    bundle = result["bundle"]

    assert bundle["format"] == "bbui-job-bundle-v2"
    assert bundle["jobs"][0]["repository_key"] == "repo_appdata"
    assert "repo" not in bundle["jobs"][0]
    assert bundle["repositories"][0]["storage_key"] == "storage_local"
    assert bundle["storages"][0]["storage_key"] == "storage_local"
    assert bundle["passphrase_meta"]["repo_appdata"]["path"] == str(secret)
    assert "secret\n" not in result["bundle_text"]


def test_job_import_restores_repository_and_storage_before_job(tmp_path: Path):
    source_config, _secret = _canonical_source(tmp_path / "source")
    bundle = export_jobs_bundle(source_config)["bundle"]
    target_config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "target")}

    result = import_jobs_bundle(
        target_config,
        bundle,
        dry_run=False,
        settings_mode="ignore",
    )

    assert result["imported_count"] == 1
    assert result["repository_inventory"] == {"repositories": 1, "storages": 1}
    assert read_repository_store(target_config)["repositories"][0]["repository_key"] == "repo_appdata"
    assert read_storage_store(target_config)["storages"][0]["storage_key"] == "storage_local"
    context = resolve_job_repository_context(
        target_config,
        "appdata_local",
        require_passphrase_file=False,
    )
    assert context["repository_path"] == "/mnt/backup/borg-backup-appdata"
