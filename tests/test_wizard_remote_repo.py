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
from wizard_api import generate_flow_preview, load_job_for_wizard, save_job, validate_params


def _storagebox_params() -> dict:
    return {
        "type_id": "flash",
        "job_name": "Flash",
        "location": "storagebox",
        "storage_profile_key": "storage-1",
        "source_paths": ["/boot"],
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


def test_wizard_preview_resolves_only_the_selected_repository_object(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
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
        "storage_key": "storage_storagebox_test",
        "relative_path": "borg-backup-flash",
        "encryption": "none",
    }]})
    params = _storagebox_params()
    params["repository_key"] = "repo_flash_storagebox_test"

    flow = generate_flow_preview(params, config, Path("/tmp/scripts"))

    assert flow["summary"]["repo"] == (
        "ssh://u123@u123.your-storagebox.de:23/./backup/borg-backup-flash"
    )


def test_wizard_preview_ui_deduplicates_repository_status_fallbacks():
    script = (ROOT / "ui" / "js" / "pages" / "wizard.js").read_text(encoding="utf-8")

    assert "function _wizardDistinctApiMessage(payload, fallback)" in script
    assert "value: repoDetail ? `${repoState} (${repoDetail})` : repoState" in script
    assert "repoStatusEl.textContent = repoDetail ? `${repoState} ${repoDetail}` : repoState" in script
    assert "apiMessage(remoteRepo, repoState)})" not in script
    assert "repoStatusEl.textContent = `${repoState} ${apiMessage(remoteRepo, repoState)}`" not in script


def test_wizard_preview_exposes_stable_step_codes_and_english_fallbacks(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _RunResult(0))
    params = _storagebox_params()
    params["source_paths"] = ["/boot", "/mnt/user/appdata"]

    flow = generate_flow_preview(params, {}, Path("/tmp/scripts"))

    assert [step["code"] for step in flow["step_codes"]] == [
        "prechecks",
        "resourceLocksAcquire",
        "borgCreate",
        "borgMaintenance",
        "statusNotification",
        "resourceLocksRelease",
    ]
    assert flow["step_codes"][2]["params"] == {"count": 2, "exclusions": 0}
    fallback = "\n".join(flow["steps"])
    assert "Pfade" not in fallback
    assert "Quelle(n)" not in fallback
    assert "Wartung" not in fallback
    assert "Benachrichtigung" not in fallback


def test_wizard_preview_supports_docker_exclusion_mode(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _RunResult(0))
    params = _storagebox_params()
    params.update({
        "source_paths": ["/mnt/user/appdata"],
        "docker_control": {
            "mode": "except_selected",
            "selected": ["AdGuard-Home"],
            "ack_appdata_risk": True,
        },
    })

    flow = generate_flow_preview(params, {}, Path("/tmp/scripts"))

    assert flow["summary"]["docker"] is True
    assert flow["summary"]["docker_mode"] == "except_selected"
    assert flow["summary"]["docker_selected"] == ["AdGuard-Home"]
    assert "Stop all Docker containers except selected containers (1 kept running)" in flow["steps"]


def test_wizard_preview_validation_defers_appdata_risk_ack_until_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "mnt" / "user" / "appdata"
    source.mkdir(parents=True)
    params = _storagebox_params()
    params.update({
        "source_paths": [str(source)],
        "location": "local",
        "storage_key": "storage_local_test",
        "repository_key": "repo_appdata_local_test",
        "docker_control": {"mode": "none", "selected": [], "ack_appdata_risk": False},
    })

    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "data")}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "path_raw": str(tmp_path / "repo-root"),
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_appdata_local_test",
        "display_name": "Appdata Local",
        "storage_key": "storage_local_test",
        "relative_path": "borg-backup-appdata",
        "encryption": "none",
    }]})
    monkeypatch.setattr(
        "wizard_api._source_matches",
        lambda _sources, prefix: prefix == "/mnt/user/appdata",
    )

    validate_params(
        params,
        tmp_path / "scripts",
        tmp_path / "data",
        ui_config=config,
        require_runtime_ack=False,
    )

    with pytest.raises(ValueError, match="Appdata backup risk must be acknowledged"):
        validate_params(params, tmp_path / "scripts", tmp_path / "data", ui_config=config)


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
        "relative_path": "borg-backup-flash",
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
            "schema_version": 3,
            "job_key": "vms_local",
            "backup_type": "vms",
            "location": "local",
            "name": "VMs",
            "enabled": True,
            "runner": "scriptless-wizard-runner",
            "repository_key": "repo_vms_local_test",
            "source_paths": ["/mnt/user/domains"],
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
    assert loaded["source_paths"] == ["/mnt/user/domains"]


def test_edit_wizard_keeps_broken_assignment_repairable(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "borg-backup"
    scripts_dir = data_root / "scripts"
    jobs_dir = data_root / "config" / "jobs"
    scripts_dir.mkdir(parents=True)
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "photos_smb.json").write_text(json.dumps({
        "schema_version": 3,
        "job_key": "photos_smb",
        "backup_type": "photos",
        "location": "smb",
        "name": "Photos",
        "enabled": True,
        "runner": "scriptless-wizard-runner",
        "repository_key": "repo_missing",
        "source_paths": ["/mnt/user/photos"],
    }), encoding="utf-8")
    config = {"BACKUP_SCRIPTS_DIR": str(data_root)}
    write_storage_store(config, {"storages": []})
    write_repository_store(config, {"repositories": []})
    monkeypatch.setattr("config_api.read_expanded_conf", lambda _cfg: {})

    loaded = load_job_for_wizard("photos_smb", scripts_dir, config)

    assert loaded["repository_key"] == "repo_missing"
    assert loaded["repo_path"] == ""
    assert "Assigned repository was not found" in loaded["repository_assignment_error"]
    assert loaded["source_paths"] == ["/mnt/user/photos"]
