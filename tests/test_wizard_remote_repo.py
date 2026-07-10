from pathlib import Path
import json
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from repositories_api import write_repository_store
from storage_objects_api import write_storage_store
from wizard_api import generate_flow_preview, load_job_for_wizard, save_job


def _storagebox_params(repo: str = "ssh://u123@u123.your-storagebox.de:23/./backup/borg-backup-flash") -> dict:
    return {
        "type_id": "flash",
        "job_name": "Flash",
        "location": "storagebox",
        "storage_profile_key": "storage-1",
        "repo_path": repo,
        "source_paths": "/boot",
        "encryption": "none",
    }


class _RunResult:
    def __init__(self, returncode: int):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = "not found" if returncode else ""


def test_wizard_preview_does_not_initialize_unmanaged_storagebox_repository():
    flow = generate_flow_preview(_storagebox_params(), {}, Path("/tmp/scripts"))

    assert flow["remote_repo"]["checked"] is False
    assert flow["remote_repo"]["exists"] is False
    assert flow["remote_repo"]["needs_init_confirm"] is False


def test_wizard_preview_does_not_rebuild_repository_from_profile():
    params = _storagebox_params("ssh://u123@u123.your-storagebox.de:23./backup/borg-backup-flash")

    flow = generate_flow_preview(params, {}, Path("/tmp/scripts"))

    assert flow["summary"]["repo"] == params["repo_path"]


def test_wizard_preview_exposes_stable_step_codes_and_english_fallbacks(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _RunResult(0))
    params = _storagebox_params()
    params["source_paths"] = "/boot /mnt/user/appdata"

    flow = generate_flow_preview(params, {}, Path("/tmp/scripts"))

    assert [step["code"] for step in flow["step_codes"]] == [
        "prechecks",
        "resourceLocksAcquire",
        "borgCreate",
        "borgMaintenance",
        "statusNotification",
        "resourceLocksRelease",
    ]
    assert flow["step_codes"][2]["params"] == {"count": 2}
    fallback = "\n".join(flow["steps"])
    assert "Pfade" not in fallback
    assert "Quelle(n)" not in fallback
    assert "Wartung" not in fallback
    assert "Benachrichtigung" not in fallback


def test_save_storagebox_job_uses_existing_repository_object(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "data")}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_storagebox_test",
        "display_name": "Storagebox",
        "storage_type": "ssh",
        "location": "storagebox",
        "identity": "storagebox-profile:storage-1",
        "profile_key": "storage-1",
        "host": "u123.your-storagebox.de",
        "port": "23",
        "user": "u123",
        "base_path": "./backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_flash_storagebox_test",
        "display_name": "Flash Storagebox",
        "repository_name": "borg-backup-flash",
        "location": "storagebox",
        "storage_type": "ssh",
        "storage_key": "storage_storagebox_test",
        "storage_profile_key": "storage-1",
        "repo_uri": _storagebox_params()["repo_path"],
        "path_raw": _storagebox_params()["repo_path"],
        "path_display": _storagebox_params()["repo_path"],
        "encryption": "none",
    }]})
    params = _storagebox_params()
    params["repository_key"] = "repo_flash_storagebox_test"
    result = save_job(params, tmp_path / "scripts", tmp_path / "data", config)
    metadata = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))

    assert metadata["repository_key"] == "repo_flash_storagebox_test"
    assert "remote_init_confirmed" not in metadata
    assert "create_repo_if_missing" not in metadata
    assert "repo" not in metadata
    assert "passphrase" not in metadata


def test_save_storagebox_job_without_repository_object_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="Selected repository object was not found"):
        save_job(_storagebox_params(), tmp_path / "scripts", tmp_path / "data", {})


def test_edit_wizard_resolves_canonical_repository_object(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "borg-backup"
    scripts_dir = data_root / "scripts"
    jobs_dir = data_root / "config" / "jobs"
    scripts_dir.mkdir(parents=True)
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "vms_local.json").write_text(
        json.dumps({
            "schema_version": 2,
            "job_key": "vms_local",
            "backup_type": "vms",
            "location": "local",
            "name": "VMs",
            "enabled": True,
            "runner": "scriptless-wizard-runner",
            "repository_key": "repo_vms_local_test",
            "paths": {
                "conf_key": "BACKUP_PATHS_VMS",
                "default": "/mnt/user/domains",
            },
        }),
        encoding="utf-8",
    )
    config = {"BACKUP_SCRIPTS_DIR": str(data_root)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/remotes/192.168.1.5_raid_backup",
        "base_path": "/mnt/remotes/192.168.1.5_raid_backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_vms_local_test",
        "display_name": "VMs",
        "storage_key": "storage_local_test",
        "relative_path": "borg-backup-vms",
        "path_raw": "/mnt/remotes/192.168.1.5_raid_backup/borg-backup-vms",
        "encryption": "none",
    }]})

    monkeypatch.setattr(
        "config_api.read_expanded_conf",
        lambda _cfg: {
            "BACKUP_PATHS_VMS": "/mnt/legacy/domains",
        },
    )

    loaded = load_job_for_wizard(
        "vms_local",
        scripts_dir,
        config,
    )

    assert loaded["repo_path"] == "/mnt/remotes/192.168.1.5_raid_backup/borg-backup-vms"
    assert loaded["source_paths"] == "/mnt/user/domains"
