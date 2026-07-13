import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import repositories_api  # noqa: E402
from repositories_api import (  # noqa: E402
    RepositoryTargetConflict,
    create_or_import_repository,
    validate_repository_target,
)
from storage_objects_api import write_storage_store  # noqa: E402
from wizard_api import load_job_for_wizard  # noqa: E402


def _config_with_local_storage(tmp_path: Path) -> tuple[dict, Path]:
    root = tmp_path / "data"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    config = {"BACKUP_SCRIPTS_DIR": str(root)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local test",
        "storage_type": "local",
        "location": "local",
        "identity": f"local:{storage_root}",
        "base_path": str(storage_root),
    }]})
    return config, storage_root


def _payload(relative_path: str, action: str = "create") -> dict:
    return {
        "action": action,
        "storage_key": "storage_local_test",
        "display_name": "Test",
        "repository_name": relative_path.rsplit("/", 1)[-1],
        "relative_path": relative_path,
        "encryption": "repokey-blake2" if action == "create" else "auto",
        "passphrase": "not-logged-secret",
    }


def test_repository_target_validation_accepts_absent_and_empty_targets(tmp_path: Path) -> None:
    config, storage_root = _config_with_local_storage(tmp_path)

    absent = validate_repository_target(config, _payload("absent"))
    (storage_root / "empty").mkdir()
    empty = validate_repository_target(config, _payload("empty"))

    assert absent["state"] == "absent"
    assert empty["state"] == "empty"


def test_repository_target_validation_distinguishes_borg_and_foreign_content(tmp_path: Path) -> None:
    config, storage_root = _config_with_local_storage(tmp_path)
    foreign = storage_root / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("not a repository", encoding="utf-8")
    borg = storage_root / "existing-borg"
    borg.mkdir()
    (borg / "config").write_text("[repository]\nid = aabbccdd\n", encoding="utf-8")

    with pytest.raises(RepositoryTargetConflict) as foreign_error:
        validate_repository_target(config, _payload("foreign"))
    with pytest.raises(RepositoryTargetConflict) as borg_error:
        validate_repository_target(config, _payload("existing-borg"))

    assert foreign_error.value.code == "repository_target_not_empty"
    assert borg_error.value.code == "repository_target_borg_exists"
    assert validate_repository_target(config, _payload("existing-borg", "import"))["state"] == "borg_repository"


def test_repository_create_conflict_does_not_write_passphrase_secret(tmp_path: Path) -> None:
    config, storage_root = _config_with_local_storage(tmp_path)
    target = storage_root / "occupied"
    target.mkdir()
    (target / "data.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(RepositoryTargetConflict):
        create_or_import_repository(config, _payload("occupied"))

    secrets = list((tmp_path / "data" / "secrets").glob("*")) if (tmp_path / "data" / "secrets").exists() else []
    assert secrets == []
    assert (target / "data.txt").read_text(encoding="utf-8") == "keep"


def test_borg_init_race_conflict_removes_new_passphrase_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _storage_root = _config_with_local_storage(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 2, "", "A repository already exists at this location"
        ),
    )

    with pytest.raises(RepositoryTargetConflict) as error:
        create_or_import_repository(config, _payload("race-conflict"))

    assert error.value.code == "repository_target_borg_exists"
    secret_root = tmp_path / "data" / "secrets"
    assert not secret_root.exists() or list(secret_root.glob(".borg-passphrase-*")) == []


def test_edit_wizard_loads_existing_weekly_schedule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "borg-backup"
    scripts_dir = data_root / "scripts"
    jobs_dir = data_root / "config" / "jobs"
    scripts_dir.mkdir(parents=True)
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "flash_local.json").write_text(json.dumps({
        "schema_version": 2,
        "job_key": "flash_local",
        "backup_type": "flash",
        "location": "local",
        "name": "Flash",
        "enabled": True,
        "runner": "scriptless-wizard-runner",
        "repository_key": "repo_flash_local_test",
        "paths": {"default": "/boot"},
    }), encoding="utf-8")
    (data_root / "config" / "schedules.json").write_text(json.dumps({
        "flash_local": {"cron": "10 6 * * 2", "enabled": True},
    }), encoding="utf-8")
    config = {"BACKUP_SCRIPTS_DIR": str(data_root)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    from repositories_api import write_repository_store
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_flash_local_test",
        "display_name": "Flash",
        "storage_key": "storage_local_test",
        "relative_path": "borg-backup-flash",
        "encryption": "repokey-blake2",
    }]})
    monkeypatch.setattr("config_api.read_expanded_conf", lambda _config: {})

    loaded = load_job_for_wizard("flash_local", scripts_dir, config)

    assert loaded["schedule"] == {"cron": "10 6 * * 2", "enabled": True}


@pytest.mark.parametrize(
    ("cron", "enabled"),
    [
        ("5 3 * * *", True),
        ("10 6 * * 2", True),
        ("15 7 12 * *", True),
        ("*/20 1-5 * * 1-5", True),
        ("10 6 * * 2", False),
    ],
)
def test_edit_wizard_preserves_schedule_inventory_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cron: str,
    enabled: bool,
) -> None:
    data_root = tmp_path / "borg-backup"
    scripts_dir = data_root / "scripts"
    jobs_dir = data_root / "config" / "jobs"
    scripts_dir.mkdir(parents=True)
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "flash_local.json").write_text(json.dumps({
        "schema_version": 2,
        "job_key": "flash_local",
        "backup_type": "flash",
        "location": "local",
        "name": "Flash",
        "runner": "scriptless-wizard-runner",
        "repository_key": "repo_flash_local_test",
        "paths": {"default": "/boot"},
    }), encoding="utf-8")
    (data_root / "config" / "schedules.json").write_text(json.dumps({
        "flash_local": {"cron": cron, "enabled": enabled},
    }), encoding="utf-8")
    config = {"BACKUP_SCRIPTS_DIR": str(data_root)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    from repositories_api import write_repository_store
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_flash_local_test",
        "display_name": "Flash",
        "storage_key": "storage_local_test",
        "relative_path": "borg-backup-flash",
        "encryption": "repokey-blake2",
    }]})
    monkeypatch.setattr("config_api.read_expanded_conf", lambda _config: {})

    loaded = load_job_for_wizard("flash_local", scripts_dir, config)

    assert loaded["schedule"] == {"cron": cron, "enabled": enabled}


def test_job_wizard_ui_preloads_schedules_and_surfaces_save_failures() -> None:
    script = (ROOT / "ui" / "js" / "pages" / "wizard.js").read_text(encoding="utf-8")

    assert "function _wizardApplySchedule(schedule)" in script
    assert "frequency = 'weekly'" in script
    assert "wizardSchedState.dow = Number(parts[4])" in script
    assert "frequency = 'monthly'" in script
    assert "scheduleSaveError" in script
    assert "schedule save failure is non-fatal" not in script
    assert "body: JSON.stringify({ job_key: jobKey, cron, enabled: schedEnabled })" in script


def test_only_job_wizard_steps_offer_validated_direct_navigation() -> None:
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "js" / "pages" / "wizard.js").read_text(encoding="utf-8")

    assert 'data-wizard-step="1" onclick="wizardGoToStep(1)"' in html
    assert 'data-wizard-step="9" onclick="wizardGoToStep(9)" disabled' in html
    assert "async function wizardGoToStep(target)" in script
    assert "next > Number(wizardState.unlockedStep || 1)" in script
    assert "while (cursor < next)" in script
    assert "if (!_wizardValidate(cursor))" in script
    assert "wizardState.unlockedStep = 9" in script
    assert "repositoryManagerRenderStep" in (ROOT / "ui" / "js" / "pages" / "storage.js").read_text(encoding="utf-8")
    assert "repositoryManagerGoToStep" not in (ROOT / "ui" / "js" / "pages" / "storage.js").read_text(encoding="utf-8")


def test_repository_submission_reuses_target_validation_and_http_conflicts() -> None:
    server = (ROOT / "borg_backup_ui.py").read_text(encoding="utf-8")

    repository_handler = server.split("def _post_repository(self)", 1)[1].split(
        "def _post_repository_validate", 1
    )[0]
    assert "validate_repository_target(self.config, body)" in repository_handler
    assert "raise ApiConflictError(str(exc), code=exc.code)" in repository_handler
    assert "self._send_api_error(409, exc.code" in server
