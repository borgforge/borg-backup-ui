import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import storage_objects_api  # noqa: E402
import check_api  # noqa: E402
import repositories_api  # noqa: E402
from check_api import CheckManager  # noqa: E402
from job_actions import delete_job_configuration
from job_model import new_job_defaults
from job_runs import read_run_context
from repositories_api import RepositoryLifecycleConflict, apply_repository_lifecycle, prepare_repository_lifecycle, read_repository_store, write_repository_store  # noqa: E402
from storage_objects_api import create_storage_target, read_storage_store, test_storage_target as run_storage_target_test, write_storage_store  # noqa: E402


def test_repository_import_compatibility_notice_is_import_only():
    index = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    storage_js = (ROOT / "ui" / "js" / "pages" / "storage.js").read_text(encoding="utf-8")

    assert 'id="repository-manager-import-compatibility-notice"' in index
    assert 'class="status-message info hidden"' in index
    assert "storage.repositoryImportCompatibilityNotice" in storage_js
    assert "storage.repositoryImportCompatibilityNoticeGeneric" in storage_js
    assert "document.getElementById('repository-manager-import-compatibility-notice')" in storage_js
    assert "if (importCompatibilityNotice)" in storage_js
    assert "action !== 'import'" in storage_js
    assert "storageBorgVersionLabel" in storage_js


def test_repository_key_recovery_controls_are_available_in_management_tab():
    storage_js = (ROOT / "ui" / "js" / "pages" / "storage.js").read_text(encoding="utf-8")
    bindings_js = (ROOT / "ui" / "js" / "components" / "app-bindings.js").read_text(encoding="utf-8")
    de = json.loads((ROOT / "ui" / "i18n" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "ui" / "i18n" / "en.json").read_text(encoding="utf-8"))

    assert "storage.repositoryKeyRecovery" in storage_js
    assert "data-storage-action=\"repository-key-import-select\"" in storage_js
    assert "/api/repositories/key-backup-import" in storage_js
    assert "data-storage-action=\"repository-key-export\"" not in storage_js
    assert "/api/repositories/key-export" not in storage_js
    assert "storageRepositoryNeedsExternalKeyBackup" in storage_js
    assert "data-storage-action=\"open-repository-key-export-settings\"" in storage_js
    assert "openRepositoryKeyExportSettings" in storage_js
    assert "settingsState.activeTab = 'transfer'" in storage_js
    assert "data-settings-action=\"export-repository-keys\"" in storage_js
    assert "onStorageContentChange" in bindings_js
    assert de["storage"]["repositoryKeyRecovery"]
    assert de["storage"]["repositoryKeyBackupMissing"] == "Borg-Key-Export fehlt"
    assert en["storage"]["repositoryKeyRecovery"]
    assert en["storage"]["repositoryKeyBackupMissing"] == "Borg key export missing"


def test_create_local_storage_target_is_stable_and_testable(tmp_path: Path, monkeypatch):
    base = tmp_path / "backup"
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    monkeypatch.setattr(storage_objects_api, "_safe_local_storage_path", lambda *_args, **_kwargs: str(base))

    first = create_storage_target(config, {
        "storage_type": "local",
        "display_name": "Local backup",
        "base_path": str(base),
    })
    second = create_storage_target(config, {
        "storage_type": "local",
        "display_name": "Duplicate",
        "base_path": str(base),
    })

    assert first["created"] is True
    assert second["created"] is False
    assert first["storage"]["storage_key"] == second["storage"]["storage_key"]
    assert base.is_dir()
    assert run_storage_target_test(config, first["storage"]["storage_key"])["ok"] is True
    assert len(read_storage_store(config)["storages"]) == 1


def test_create_usb_storage_target_updates_canonical_inventory_only(tmp_path: Path, monkeypatch):
    mount = tmp_path / "usb"
    mount.mkdir()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    monkeypatch.setattr(storage_objects_api, "_safe_local_storage_path", lambda *_args, **_kwargs: str(mount))

    result = create_storage_target(config, {
        "storage_type": "usb",
        "display_name": "USB archive",
        "mount_path": str(mount),
    })

    assert result["storage"]["display_name"] == "USB archive"
    assert result["storage"]["profile_key"].startswith("usb-")
    assert result["storage"]["mount_path"] == str(mount)
    assert not (tmp_path / "config" / "settings.json").exists()


JOB_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(autouse=True)
def isolate_control_and_cron(tmp_path, monkeypatch):
    monkeypatch.setenv("BORG_UI_CONTROL_ROOT", str(tmp_path / "controls"))
    monkeypatch.setattr("schedule_api._update_crontab", lambda lines: None)
    monkeypatch.setattr("config_api.read_expanded_conf", lambda config: {
        "GLOBAL_DATA_DIR": str(tmp_path / "data"), "GLOBAL_LOG_DIR": str(tmp_path / "logs")})


def _canonical_job(tmp_path, job_id, repository_key, name="Photos", prefixes=None, retention=None):
    job = {**new_job_defaults(), "job_id": job_id, "name": name,
           "repository_key": repository_key, "source_paths": [str(tmp_path / "source")],
           "archive_prefixes": prefixes or [name.lower() + "-backup"]}
    if retention is not None:
        job["retention"] = retention
    path = tmp_path / "config/jobs" / (job_id + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(job), encoding="utf-8")
    return job


def _maintenance_inventory(tmp_path, jobs):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{"storage_key": "local", "storage_type": "local",
                         "location": "local", "base_path": str(tmp_path / "backup")}]})
    repositories = {}
    for job in jobs:
        key = job["repository_key"]
        row = repositories.setdefault(key, {"repository_key": key, "storage_key": "local",
                        "relative_path": key, "encryption": "none", "job_ids": [], "source_job_ids": []})
        row["job_ids"].append(job["job_id"])
        row["source_job_ids"].append(job["job_id"])
    write_repository_store(config, {"repositories": list(repositories.values())})
    return config, repositories


def _prune_snapshot(tmp_path, config, repository, *, job_id=""):
    target = str(tmp_path / "backup" / repository["relative_path"])
    command = CheckManager()._repository_command(config, repository, target, "prune", "quick", job_id=job_id)
    assert command[:2] == [sys.executable, str(API_ROOT / "retention_runner.py")]
    assert command[4] == str(tmp_path)
    snapshot = read_run_context(command[2], command[3])
    assert snapshot["repository_snapshot"] == target
    assert snapshot["repository_key_snapshot"] == repository["repository_key"]
    return snapshot


def test_repository_maintenance_commands_use_repository_and_job_retention(tmp_path: Path):
    job = _canonical_job(tmp_path, JOB_ID, "repo_photos")
    config, repositories = _maintenance_inventory(tmp_path, [job])
    repository = repositories["repo_photos"]
    manager = CheckManager()
    assert manager._repository_command(config, repository, "/mnt/backup/photos", "check", "quick") == [
        "borg", "check", "--lock-wait", "30", "--progress", "/mnt/backup/photos"]
    assert manager._repository_command(config, repository, "/mnt/backup/photos", "check", "verify_data") == [
        "borg", "check", "--lock-wait", "30", "--progress", "--verbose", "--verify-data", "/mnt/backup/photos"]
    assert manager._repository_command(config, repository, "/mnt/backup/photos", "compact", "quick") == [
        "borg", "compact", "--lock-wait", "30", "--progress", "/mnt/backup/photos"]
    snapshot = _prune_snapshot(tmp_path, config, repository)
    assert snapshot["job_id"] == JOB_ID
    assert snapshot["archive_prefixes_snapshot"] == ["photos-backup"]
    assert snapshot["context"]["job"]["retention"] == {"daily": "7", "weekly": "4", "monthly": "6", "yearly": "3"}


def test_repository_prune_preserves_literal_prefixes_with_underscores(tmp_path: Path):
    prefixes = ["borg_backup_taeglich", "photos_smb", "appdata_storagebox"]
    job = _canonical_job(tmp_path, JOB_ID, "repo_photos", name="An unrelated display name", prefixes=prefixes)
    config, repositories = _maintenance_inventory(tmp_path, [job])
    snapshot = _prune_snapshot(tmp_path, config, repositories["repo_photos"])
    assert snapshot["archive_prefixes_snapshot"] == prefixes
    assert snapshot["archive_prefix_snapshot"] == "borg_backup_taeglich"
    assert snapshot["job_name_snapshot"] == "An unrelated display name"


def test_repository_prune_requires_explicit_retention_source_for_shared_repository(tmp_path: Path):
    jobs = [_canonical_job(tmp_path, JOB_ID, "repo_shared"),
            _canonical_job(tmp_path, OTHER_ID, "repo_shared", name="Appdata")]
    config, repositories = _maintenance_inventory(tmp_path, jobs)
    with pytest.raises(ValueError, match="Select one backup job as the retention source"):
        _prune_snapshot(tmp_path, config, repositories["repo_shared"])


def test_repository_prune_uses_selected_job_retention_source(tmp_path: Path):
    retention = {"daily": "14", "weekly": "8", "monthly": "3", "yearly": "1"}
    jobs = [_canonical_job(tmp_path, JOB_ID, "repo_shared"),
            _canonical_job(tmp_path, OTHER_ID, "repo_shared", name="Appdata", retention=retention)]
    config, repositories = _maintenance_inventory(tmp_path, jobs)
    snapshot = _prune_snapshot(tmp_path, config, repositories["repo_shared"], job_id=OTHER_ID)
    assert snapshot["job_id"] == OTHER_ID
    assert snapshot["context"]["job"]["retention"] == retention
    assert snapshot["archive_prefixes_snapshot"] == ["appdata-backup"]


def test_repository_prune_rejects_retention_source_from_other_repository(tmp_path: Path):
    jobs = [_canonical_job(tmp_path, JOB_ID, "repo_photos"),
            _canonical_job(tmp_path, OTHER_ID, "repo_appdata", name="Appdata")]
    config, repositories = _maintenance_inventory(tmp_path, jobs)
    with pytest.raises(ValueError, match="does not use this repository"):
        _prune_snapshot(tmp_path, config, repositories["repo_photos"], job_id=OTHER_ID)


def test_repository_maintenance_uses_repository_secret_without_shell(tmp_path: Path, monkeypatch):
    secret = tmp_path / "secrets" / ".borg-passphrase-repo_test"
    secret.parent.mkdir(parents=True)
    secret.write_text("secret", encoding="utf-8")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_test",
        "job_ids": [], "source_job_ids": [],
        "display_name": "Test",
        "repository_name": "test",
        "storage_key": "storage_local_test",
        "location": "local",
        "relative_path": "test",
        "path_raw": "/mnt/backup/test",
        "passphrase_ref": str(secret),
    }]})
    captured = {}

    class Process:
        stdout = None

        def wait(self):
            return 0

        returncode = 0

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("threading.Thread.start", lambda _self: None)

    from migration_gate_support import ready_gate
    ready_gate(config, monkeypatch, tmp_path / "writer-gate")
    manager = CheckManager()
    ok, error = manager.start_repository(config, "repo_test", "check", "quick")

    assert ok is True and error is None
    assert captured["cmd"] == [
        "borg", "check", "--lock-wait", "30", "--progress", "/mnt/backup/test",
    ]
    assert "shell" not in captured["kwargs"]
    assert captured["kwargs"]["env"]["BORG_PASSCOMMAND"].endswith(str(secret))
    manager._reader(manager._state)


def test_repository_environment_combines_ssh_key_and_keepalives(tmp_path: Path):
    key_path = tmp_path / "storage key"
    key_path.write_text("private-key", encoding="utf-8")

    env = repositories_api._repo_env({
        "storage_type": "ssh",
        "location": "storagebox",
        "ssh_key_path": str(key_path),
    }, None, {"BACKUP_SCRIPTS_DIR": str(tmp_path)})

    assert f"-i '{key_path}'" in env["BORG_RSH"]
    assert "ServerAliveInterval=30" in env["BORG_RSH"]
    assert "ServerAliveCountMax=10" in env["BORG_RSH"]
    assert "TCPKeepAlive=yes" in env["BORG_RSH"]


def test_repository_environment_confirms_only_explicit_unencrypted_repositories(
    tmp_path: Path, monkeypatch,
):
    monkeypatch.setenv("BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK", "yes")
    monkeypatch.setenv("BORG_RELOCATED_REPO_ACCESS_IS_OK", "no")
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}

    unencrypted = repositories_api._repo_env({}, None, config, encryption="none")
    encrypted = repositories_api._repo_env({}, None, config, encryption="repokey-blake2")
    unspecified = repositories_api._repo_env({}, None, config)

    assert unencrypted["BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK"] == "yes"
    assert "BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK" not in encrypted
    assert "BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK" not in unspecified
    assert unencrypted["BORG_RELOCATED_REPO_ACCESS_IS_OK"] == "yes"
    assert encrypted["BORG_RELOCATED_REPO_ACCESS_IS_OK"] == "yes"
    assert unspecified["BORG_RELOCATED_REPO_ACCESS_IS_OK"] == "yes"


def test_relocated_repository_warning_becomes_api_conflict() -> None:
    with pytest.raises(ValueError) as error:
        repositories_api._raise_borg_command_error(
            "Warning: The repository at location /mnt/new/repo was previously located at /mnt/old/repo",
            "borg info failed",
        )

    assert getattr(error.value, "api_code") == "repository_relocated"
    assert getattr(error.value, "api_status") == 409


def test_repository_maintenance_persists_structured_prune_and_compact_results(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    repository = {
        "repository_key": "repo_test",
        "job_ids": [], "source_job_ids": [],
        "display_name": "Test",
        "storage_key": "storage_local_test",
        "relative_path": "test",
    }
    write_repository_store(config, {"repositories": [repository]})

    class Process:
        returncode = 0

    prune = check_api._CheckState(
        Process(),
        "repo_test",
        "quick",
        datetime.now() - timedelta(seconds=4),
        action="prune",
        config=config,
        repository=repository,
    )
    prune.append_line("Pruning archive (1/2): test-2026-06-01")
    prune.append_line("Pruning archive (2/2): test-2026-06-02")
    prune_result = CheckManager._persist_repository_result(prune)

    compact = check_api._CheckState(
        Process(),
        "repo_test",
        "quick",
        datetime.now() - timedelta(seconds=2),
        action="compact",
        config=config,
        repository=repository,
    )
    compact.append_line("Repository compaction freed about 12.6 GB repository space.")
    compact_result = CheckManager._persist_repository_result(compact)

    stored = read_repository_store(config)["repositories"][0]["maintenance_results"]
    assert prune_result["status"] == "success"
    assert prune_result["duration_seconds"] >= 4
    assert prune_result["deleted_archives_count"] == 2
    assert stored["prune"]["deleted_archives"] == ["test-2026-06-01", "test-2026-06-02"]
    assert compact_result["freed_space"] == "12.6 GB"
    assert compact_result["duration_seconds"] >= 2
    assert stored["compact"]["freed_space"] == "12.6 GB"


@pytest.mark.parametrize('date_label', ['Mon, 2026-09-07 10:11:12', '2026-09-07 10:11:12', 'Mo, 2026-09-07 10:11:12 +0200'])
@pytest.mark.parametrize('log_format', [
    '%(message)s', '%(levelname)s %(message)s', '%(asctime)s %(levelname)s %(message)s',
    '[%(asctime)s] %(levelname)s %(message)s', '[%(asctime)s] %(message)s',
])
def test_repository_maintenance_reads_borg_delete_names_without_metadata(date_label, log_format):
    class Process:
        returncode = 0

    state = check_api._CheckState(Process(), 'repo_test', 'quick', datetime.now(), action='prune')
    formatter = logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S')

    def append_output(message):
        record = logging.makeLogRecord({'msg': message, 'levelname': 'INFO'})
        state.append_line(formatter.format(record))

    names = ['old prefix with spaces-2026-06-01', 'name  with  double spaces (2/8)',
             'name Mon, 2026-08-31 00:00:00']
    for index, name in enumerate(names, 1):
        line = f'Deleting archive: {name:<60} {date_label} [{index:064x}] ({index}/{len(names)})'
        append_output(line)
        append_output(line)  # Repeated output frames count only once.
    append_output(f'Pruning archive (1/1): {names[0]:<60} {date_label} [{1:064x}]')
    result = CheckManager._maintenance_result(state)
    assert result['status'] == 'success'
    assert result['deleted_archives_count'] == len(names)
    assert result['deleted_archives'] == names


@pytest.mark.parametrize('prefix', ['', 'INFO ', '2026-09-07 12:34:56 INFO '])
def test_repository_maintenance_ignores_retention_plans_dry_runs_and_keep_lines(prefix):
    class Process:
        returncode = 0

    state = check_api._CheckState(Process(), 'repo_test', 'quick', datetime.now(), action='prune')
    formatted = f'archive with spaces Mon, 2026-09-07 10:11:12 [{1:064x}]'
    for line in [
        f'Selected for pruning (1/1): {formatted}',
        f'Would delete archive: {formatted} (1/1)',
        f'Would prune: {formatted}',
        f'Keeping archive (rule: daily #1): {formatted}',
        f'Keeping checkpoint archive: {formatted}',
        f'[Info] Selected for pruning: Deleting archive: {formatted} (1/1)',
        'Deleting archive: archive with spaces',
        'Deleting archive: archive with spaces Mon, 2026-09-07 10:11:12 [invalid-id] (1/1)',
    ]:
        state.append_line(prefix + line)
    result = CheckManager._maintenance_result(state)
    assert result['deleted_archives_count'] == 0 and result['deleted_archives'] == []


@pytest.mark.parametrize('exit_code', [1, 2, 130, -15])
@pytest.mark.parametrize('prefix', ['', 'INFO ', '2026-09-07 12:34:56 INFO '])
@pytest.mark.parametrize('output', [
    'Pruning archive (1/1): old archive with spaces',
    f'Pruning archive (1/1): old archive with spaces Mon, 2026-09-07 10:11:12 [{1:064x}]',
    f'Deleting archive: old archive with spaces Mon, 2026-09-07 10:11:12 [{1:064x}] (1/1)',
])
def test_repository_maintenance_does_not_confirm_deletions_after_failure(exit_code, output, prefix):
    class Process:
        returncode = exit_code

    state = check_api._CheckState(Process(), 'repo_test', 'quick', datetime.now(), action='prune')
    state.append_line(prefix + output)
    state.append_line('Repository commit failed')
    result = CheckManager._maintenance_result(state)
    assert result['exit_code'] == exit_code and result['status'] != 'success'
    assert result['deleted_archives_count'] == 0 and result['deleted_archives'] == []
    assert 'Repository commit failed' in result['details']


def test_repository_maintenance_masks_error_details(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    repository = {
        "repository_key": "repo_test",
        "job_ids": [], "source_job_ids": [],
        "display_name": "Test",
        "storage_key": "storage_local_test",
        "relative_path": "test",
    }
    write_repository_store(config, {"repositories": [repository]})

    class Process:
        returncode = 2

    state = check_api._CheckState(
        Process(),
        "repo_test",
        "quick",
        datetime.now() - timedelta(seconds=1),
        action="check",
        config=config,
        repository=repository,
    )
    state.append_line("Connection failed: password=hunter2 token=secret-token")

    result = CheckManager._persist_repository_result(state)

    assert result["status"] == "error"
    assert result["details"] == ["Connection failed: password=*** token=***"]
    stored = read_repository_store(config)["repositories"][0]["maintenance_results"]["check"]
    assert "hunter2" not in json.dumps(stored)
    assert "secret-token" not in json.dumps(stored)


def test_repository_maintenance_classifies_interrupted_ssh_connection(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_ssh_test",
        "display_name": "Storagebox",
        "storage_type": "ssh",
        "location": "storagebox",
        "endpoint": "backup@example.test:23",
        "base_path": "./backup",
    }]})
    repository = {
        "repository_key": "repo_test",
        "job_ids": [], "source_job_ids": [],
        "display_name": "Test",
        "storage_key": "storage_ssh_test",
        "relative_path": "test",
    }
    write_repository_store(config, {"repositories": [repository]})

    class Process:
        returncode = 2

    state = check_api._CheckState(
        Process(),
        "repo_test",
        "verify_data",
        datetime.now() - timedelta(seconds=2),
        action="check",
        config=config,
        repository=repository,
    )
    state.append_line("Remote: Read from remote host backup.example.test: Connection reset by peer")
    state.append_line("Remote: client_loop: send disconnect: Broken pipe")
    state.append_line("Connection closed by remote host.")

    result = CheckManager._persist_repository_result(state)

    assert result["status"] == "error"
    assert result["error_category"] == "network"
    assert result["failure_code"] == "borg_ssh_connection_interrupted"
    assert "does not necessarily indicate repository damage" in result["failure_hint"]
    stored = read_repository_store(config)["repositories"][0]["maintenance_results"]["verify_data"]
    assert stored["failure_code"] == "borg_ssh_connection_interrupted"


def test_repository_maintenance_stream_exposes_completion_not_raw_output():
    class Process:
        returncode = 2

    state = check_api._CheckState(Process(), "repo_test", "quick", datetime.now(), action="check")
    state.append_line("password=hunter2")
    state.finished = True
    state.exit_code = 2
    manager = CheckManager()
    manager._state = state

    stream = "".join(manager.stream_output())

    assert "event: done" in stream
    assert "data: 2" in stream
    assert "hunter2" not in stream


def _write_lifecycle_repository(tmp_path: Path, *, job_ids=None) -> tuple[dict, Path, Path]:
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    base = tmp_path / "backup"
    repository_path = base / "photos"
    repository_path.mkdir(parents=True)
    secret = tmp_path / "secrets" / ".borg-passphrase-repo_photos"
    secret.parent.mkdir(parents=True)
    secret.write_text("secret", encoding="utf-8")
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": f"local:{base}",
        "base_path": str(base),
    }]})
    for job_id in job_ids or []:
        _canonical_job(tmp_path, job_id, "repo_photos")
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_photos",
        "display_name": "Photos",
        "repository_name": "photos",
        "storage_key": "storage_local_test",
        "storage_name": "Local",
        "location": "local",
        "relative_path": "photos",
        "path_raw": str(repository_path),
        "path_display": str(repository_path),
        "passphrase_ref": str(secret),
        "encryption": "repokey-blake2",
        "borg_repository_id": "repo-id-123",
        "repository_stats": {"archives_count": 3, "unique_csize": 1024},
        "job_ids": list(job_ids or []),
        "source_job_ids": list(job_ids or []),
    }]})
    return config, repository_path, secret


def test_repository_remove_from_inventory_keeps_data_and_secret(tmp_path: Path):
    config, repository_path, secret = _write_lifecycle_repository(tmp_path)

    preview = prepare_repository_lifecycle(config, "repo_photos", "remove")
    result = apply_repository_lifecycle(
        config,
        {
            "repository_key": "repo_photos",
            "mode": "remove",
            "confirmation_name": "Photos",
        },
        audit_context={
            "actor": "testadmin",
            "actor_role": "admin",
            "auth_method": "session",
            "request_id": "request-123",
        },
    )

    assert preview["allowed"] is True
    assert result["repository_deleted"] is False
    assert read_repository_store(config)["repositories"] == []
    assert repository_path.is_dir()
    assert secret.is_file()
    audit = json.loads(
        (tmp_path / "config" / "repository-lifecycle.log.jsonl").read_text(encoding="utf-8").strip()
    )
    assert audit["action"] == "remove_from_inventory"
    assert audit["actor"] == "testadmin"
    assert audit["actor_role"] == "admin"
    assert audit["auth_method"] == "session"
    assert audit["request_id"] == "request-123"


def test_repository_lifecycle_blocks_live_job_reference(tmp_path: Path):
    config, repository_path, _secret = _write_lifecycle_repository(tmp_path, job_ids=[JOB_ID])

    preview = prepare_repository_lifecycle(config, "repo_photos", "remove")

    assert preview["allowed"] is False
    assert preview["job_ids"] == [JOB_ID]
    assert "jobs_linked" in preview["blockers"]
    with pytest.raises(RepositoryLifecycleConflict, match="jobs or operations"):
        apply_repository_lifecycle(config, {
            "repository_key": "repo_photos",
            "mode": "remove",
            "confirmation_name": "Photos",
        })
    assert repository_path.is_dir()


def test_deleted_job_is_unlinked_from_repository_inventory(tmp_path: Path):
    config, _repository_path, _secret = _write_lifecycle_repository(tmp_path, job_ids=[JOB_ID])

    delete_job_configuration(config, JOB_ID)

    repository = read_repository_store(config)["repositories"][0]
    assert repository["job_ids"] == []
    assert repository["source_job_ids"] == []
    assert not (tmp_path / "config/jobs" / (JOB_ID + ".json")).exists()


def test_permanent_repository_delete_revalidates_identity_and_uses_borg(tmp_path: Path, monkeypatch):
    config, repository_path, secret = _write_lifecycle_repository(tmp_path)
    monkeypatch.setattr(repositories_api, "_borg_info", lambda *_args: {
        "repository": {"id": "repo-id-123"},
        "encryption": {"mode": "repokey-blake2"},
        "cache": {"stats": {"unique_csize": 1024}},
    })
    monkeypatch.setattr(repositories_api, "_borg_list", lambda *_args: {
        "archives": [{"name": "one"}, {"name": "two"}, {"name": "three"}],
    })
    captured = {}

    class Result:
        returncode = 0
        stdout = "Repository deleted."
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr(repositories_api.subprocess, "run", fake_run)
    preview = prepare_repository_lifecycle(config, "repo_photos", "delete")
    result = apply_repository_lifecycle(config, {
        "repository_key": "repo_photos",
        "mode": "delete",
        "confirmation_name": "Photos",
        "confirmation_phrase": "DELETE",
        "expected_repository_id": preview["repository_id"],
        "expected_repository_path": preview["repository_path"],
        "expected_archive_count": preview["archive_count"],
    })

    assert captured["command"] == ["borg", "delete", "--lock-wait", "30", str(repository_path)]
    assert "shell" not in captured["kwargs"]
    assert captured["kwargs"]["env"]["BORG_DELETE_I_KNOW_WHAT_I_AM_DOING"] == "YES"
    assert result["repository_deleted"] is True
    assert result["secret_deleted"] is True
    assert read_repository_store(config)["repositories"] == []
    assert not secret.exists()


def test_permanent_repository_delete_requires_name_and_delete_phrase(tmp_path: Path):
    config, repository_path, secret = _write_lifecycle_repository(tmp_path)

    with pytest.raises(ValueError, match="display name confirmation"):
        apply_repository_lifecycle(config, {
            "repository_key": "repo_photos",
            "mode": "delete",
            "confirmation_name": "wrong",
            "confirmation_phrase": "DELETE",
        })
    with pytest.raises(ValueError, match="requires DELETE"):
        apply_repository_lifecycle(config, {
            "repository_key": "repo_photos",
            "mode": "delete",
            "confirmation_name": "Photos",
            "confirmation_phrase": "delete",
        })
    assert repository_path.is_dir()
    assert secret.is_file()
    assert len(read_repository_store(config)["repositories"]) == 1


def test_permanent_repository_delete_rejects_changed_identity(tmp_path: Path, monkeypatch):
    config, _repository_path, _secret = _write_lifecycle_repository(tmp_path)
    ids = iter(["repo-id-123", "different-id"])
    monkeypatch.setattr(repositories_api, "_borg_info", lambda *_args: {
        "repository": {"id": next(ids)},
        "encryption": {"mode": "repokey-blake2"},
        "cache": {"stats": {"unique_csize": 1024}},
    })
    monkeypatch.setattr(repositories_api, "_borg_list", lambda *_args: {"archives": []})
    preview = prepare_repository_lifecycle(config, "repo_photos", "delete")

    with pytest.raises(RepositoryLifecycleConflict, match="identity or archive count changed"):
        apply_repository_lifecycle(config, {
            "repository_key": "repo_photos",
            "mode": "delete",
            "confirmation_name": "Photos",
            "confirmation_phrase": "DELETE",
            "expected_repository_id": preview["repository_id"],
            "expected_repository_path": preview["repository_path"],
            "expected_archive_count": preview["archive_count"],
        })
    assert len(read_repository_store(config)["repositories"]) == 1


def test_repository_management_ui_is_separate_and_double_confirmed():
    script = (ROOT / "ui" / "js" / "pages" / "storage.js").read_text(encoding="utf-8")
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    de = json.loads((ROOT / "ui" / "i18n" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "ui" / "i18n" / "en.json").read_text(encoding="utf-8"))

    assert "repositoryTabManagement" in script
    assert "data-lifecycle-mode=\"remove\"" in script
    assert "data-lifecycle-mode=\"delete\"" in script
    assert "confirmation_phrase" in script
    assert "phrase === 'DELETE'" in script
    assert "repository-lifecycle-modal" in html
    assert de["storage"]["repositoryTabManagement"] == "Verwaltung"
    assert en["storage"]["repositoryTabManagement"] == "Management"


def test_repository_import_has_storage_scoped_directory_browser():
    script = (ROOT / "ui" / "js" / "pages" / "storage.js").read_text(encoding="utf-8")
    bindings = (ROOT / "ui" / "js" / "components" / "app-bindings.js").read_text(encoding="utf-8")
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")

    assert 'id="repository-manager-browser"' in html
    assert 'id="repository-manager-browser-list"' in html
    assert 'id="repository-manager-browser-btn"' in html
    assert 'id="repository-manager-import-compatibility-notice"' in html
    assert "/api/repositories/browse?storage_key=" in script
    assert "row.managed" in script
    assert "row.borg_repository" in script
    assert "repositoryBrowseBorgRepository" in script
    assert "selectDisabled = managed || !supported" in script
    assert "openDisabled = managed || !supported || borgRepository" in script
    assert "repository-manager-browser-row-managed" in script
    assert "repository-manager-browser-row-repository" in script
    assert "selectClass = importableBorg ? 'btn btn-primary' : 'btn btn-secondary'" in script
    assert "repositoryManagerBrowserClick" in bindings
    assert "repositoryManagerOpenBrowser" in bindings


def test_repository_import_browser_marks_borg_repositories_as_terminal_choices(tmp_path: Path):
    base = tmp_path / "storage"
    base.mkdir()
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "data")}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Backup-Lokal",
        "storage_type": "local",
        "location": "local",
        "identity": f"local:{base}",
        "base_path": str(base),
    }]})
    borg_repo = base / "k8s-master"
    borg_repo.mkdir()
    (borg_repo / "config").write_text("[repository]\nid = abcdef0123456789\n", encoding="utf-8")
    (borg_repo / "data").mkdir()
    (base / "ordinary-folder").mkdir()

    root = repositories_api.browse_repository_directories(config, "storage_local_test", "")
    rows = {row["name"]: row for row in root["directories"]}

    assert rows["k8s-master"]["borg_repository"] is True
    assert rows["k8s-master"]["managed"] is False
    assert rows["k8s-master"]["supported"] is True
    assert rows["ordinary-folder"]["borg_repository"] is False

    nested = repositories_api.browse_repository_directories(config, "storage_local_test", "k8s-master")
    assert nested["directories"] == []
