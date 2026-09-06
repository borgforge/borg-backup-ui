from canonical_wizard_support import canonical_fixture
import pytest
import io
import json
import logging
import pytest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
RUNTIME_ROOT = ROOT / "runtime"
for path in (ROOT, API_ROOT, RUNTIME_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from repositories_api import write_repository_store  # noqa: E402
from runtime.lib.borg_runner import BorgConfig, BorgRunner  # noqa: E402
from storage_objects_api import write_storage_store  # noqa: E402
from wizard_api import generate_flow_preview, load_job_for_wizard, save_job  # noqa: E402
import wizard_runner  # noqa: E402


def _capture_create_command(monkeypatch, tmp_path: Path, *, enabled: bool) -> list[str]:
    captured: dict[str, list[str]] = {}

    class Process:
        def __init__(self, command, **_kwargs):
            captured["command"] = command
            self.stdout = io.StringIO("A mnt/user/new-file.txt\nM mnt/user/changed-file.txt\n")
            self.returncode = 0

        def wait(self):
            return self.returncode

    monkeypatch.setattr("runtime.lib.borg_runner.subprocess.Popen", Process)
    runner = BorgRunner(BorgConfig(
        repo=str(tmp_path / "repo"),
        file_activity=enabled,
        max_runtime_hours=0,
    ))
    return_code = runner.create([tmp_path / "source"], "test-backup")
    assert return_code == 0
    return captured["command"]


def _local_repository_config(tmp_path: Path) -> dict:
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local_test",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": f"local:{tmp_path / 'repository-root'}",
        "base_path": str(tmp_path / "repository-root"),
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_files_test",
        "display_name": "Files",
        "storage_key": "storage_local_test",
        "relative_path": "borg-backup-files",
        "encryption": "none",
    }]})
    return config


def test_borg_create_adds_only_list_filter_when_file_activity_is_enabled(
    monkeypatch,
    tmp_path: Path,
    caplog,
) -> None:
    caplog.set_level(logging.INFO)
    command = _capture_create_command(monkeypatch, tmp_path, enabled=True)

    assert "--list" in command
    assert "--filter=AME" in command
    assert "--progress" not in command
    assert "A mnt/user/new-file.txt" in caplog.text
    assert "M mnt/user/changed-file.txt" in caplog.text


def test_borg_create_keeps_file_activity_disabled_by_default(monkeypatch, tmp_path: Path) -> None:
    command = _capture_create_command(monkeypatch, tmp_path, enabled=False)

    assert "--list" not in command
    assert not any(argument.startswith("--filter") for argument in command)
    assert "--progress" not in command
    assert BorgConfig.from_config({}).file_activity is False
    assert BorgConfig.from_config({"BORG_FILE_ACTIVITY": "true"}).file_activity is True


def test_borg_create_preserves_item_errors_and_failure_result(
    monkeypatch,
    tmp_path: Path,
    caplog,
) -> None:
    class Process:
        def __init__(self, _command, **_kwargs):
            self.stdout = io.StringIO("E mnt/user/unreadable-file.txt\nArchive creation failed\n")
            self.returncode = 2

        def wait(self):
            return self.returncode

    monkeypatch.setattr("runtime.lib.borg_runner.subprocess.Popen", Process)
    caplog.set_level(logging.INFO)
    runner = BorgRunner(BorgConfig(
        repo=str(tmp_path / "repo"),
        file_activity=True,
        max_runtime_hours=0,
    ))

    assert runner.create([tmp_path / "source"], "test-backup") == 2
    assert "E mnt/user/unreadable-file.txt" in caplog.text
    assert "Archive creation failed" in caplog.text
    assert "Borg create failed (exit 2)" in caplog.text


def test_job_metadata_round_trip(tmp_path: Path, monkeypatch) -> None:
    config = _local_repository_config(tmp_path)
    scripts_dir = tmp_path / "scripts"
    source = tmp_path / "source"
    source.mkdir()
    params = {
        "archive_prefix": "files-backup",
        "job_name": "Files",
        "location": "local",
        "source_paths": [str(source)],
        "repository_key": "repo_files_test",
        "file_activity": True,
    }

    canonical_fixture(config)
    result = save_job(params, scripts_dir, tmp_path, config)
    metadata = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))
    assert metadata["file_activity"] is True

    monkeypatch.setattr("config_api.read_expanded_conf", lambda _config: {})
    loaded = load_job_for_wizard(result["job_id"], scripts_dir, config)
    assert loaded["file_activity"] is True


def test_missing_job_field_is_disabled_and_preview_exposes_setting(tmp_path: Path, monkeypatch) -> None:
    config = _local_repository_config(tmp_path)
    scripts_dir = tmp_path / "scripts"
    jobs_dir = tmp_path / "config" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "files_local.json").write_text(json.dumps({
        "schema_version": 3,
        "job_key": "files_local",
        "name": "Files",
        "backup_type": "files",
        "location": "local",
        "repository_key": "repo_files_test",
        "source_paths": [str(tmp_path / "source")],
        "retention": {"daily": "7", "weekly": "4", "monthly": "6", "yearly": "3"},
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr("config_api.read_expanded_conf", lambda _config: {})

    ids = canonical_fixture(config)
    loaded = load_job_for_wizard(ids["files_local"], scripts_dir, config)
    preview = generate_flow_preview({
        "archive_prefix": "files-backup",
        "location": "local",
        "source_paths": [str(tmp_path / "source")],
        "repository_key": "repo_files_test",
        "file_activity": True,
    }, config, scripts_dir)

    assert loaded["file_activity"] is False
    assert preview["summary"]["file_activity"] is True


@pytest.mark.parametrize("file_activity, expected", [(True, "1"), (False, "0"), (None, "0")])
def test_legacy_runner_file_activity_environment(tmp_path: Path, monkeypatch, file_activity, expected):
    # The actual UUID runner cutover and end-to-end wiring belong to #475.
    # Keep the existing runner regression independently of canonical wizard tests.
    _local_repository_config(tmp_path)
    jobs = tmp_path / "config" / "jobs"
    jobs.mkdir()
    meta = {
        "schema_version": 3, "job_key": "files_local", "backup_type": "files", "location": "local",
        "repository_key": "repo_files_test", "source_paths": [str(tmp_path / "source")],
    }
    if file_activity is not None:
        meta["file_activity"] = file_activity
    (jobs / "files_local.json").write_text(json.dumps(meta))
    monkeypatch.setenv("BORG_FILE_ACTIVITY", "1")
    env, _ = wizard_runner._load_env_from_job("files_local", tmp_path / "scripts", tmp_path)
    assert env["BORG_FILE_ACTIVITY"] == expected


def test_wizard_and_manuals_explain_file_activity_and_privacy() -> None:
    index = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "ui" / "js" / "pages" / "wizard.js").read_text(encoding="utf-8")
    styles = (ROOT / "ui" / "style.css").read_text(encoding="utf-8")
    de = json.loads((ROOT / "ui" / "i18n" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "ui" / "i18n" / "en.json").read_text(encoding="utf-8"))
    manual_de = (ROOT / "docs" / "user-manual" / "de" / "user-manual.md").read_text(encoding="utf-8")
    manual_en = (ROOT / "docs" / "user-manual" / "en" / "user-manual.md").read_text(encoding="utf-8")

    assert 'id="wiz-file-activity"' in index
    assert 'data-i18n="wizard.fileActivityPrivacy"' in index
    basics = index[index.index('id="wizard-step-1"'):index.index('id="wizard-step-2"')]
    sources_target = index[index.index('id="wizard-step-2"'):index.index('id="wizard-step-3"')]
    assert 'id="wiz-file-activity"' in basics
    assert 'id="wiz-file-activity"' not in sources_target
    assert 'wizard-feature-box wizard-file-activity' in basics
    assert 'wizard-file-activity-status-codes' in basics
    assert 'anzeigen</span><br><span class="wizard-file-activity-status-codes">(A/M/E)</span>' in basics
    assert ".wizard-file-activity-status-codes" in styles
    assert "white-space: nowrap" in styles
    assert "#wizard-modal .modal-wizard" in styles
    assert "max-height: calc(100vh - 32px)" in styles
    assert "flex: 1 1 448px" in styles
    assert "file_activity: !!document.getElementById('wiz-file-activity').checked" in script
    assert "wizard.previewFileActivity" in script
    assert "Support-Paketen" in de["wizard"]["fileActivityPrivacy"]
    assert "support bundles" in en["wizard"]["fileActivityPrivacy"]
    assert "`--list --filter=AME`" in manual_de
    assert "`--list --filter=AME`" in manual_en
    assert "vollständige Liste des Archivinhalts" in manual_de
    assert "not anonymous" in manual_en


@pytest.mark.parametrize('started_enabled', [False, True])
def test_managed_run_preserves_start_time_option_and_capture_path(tmp_path, monkeypatch, started_enabled):
    _local_repository_config(tmp_path)
    jobs = tmp_path / 'config' / 'jobs'
    jobs.mkdir()
    meta = {
        'schema_version': 3, 'job_key': 'files_local', 'backup_type': 'files', 'location': 'local',
        'repository_key': 'repo_files_test', 'source_paths': [str(tmp_path / 'source')],
        'file_activity': not started_enabled,
    }
    (jobs / 'files_local.json').write_text(json.dumps(meta))
    capture = tmp_path / 'logs' / 'Borg-Backup_files_local--activity-test.log'
    monkeypatch.setenv('BORG_UI_FILE_ACTIVITY_RUN', '1' if started_enabled else '0')
    monkeypatch.setenv('BORG_UI_CAPTURE_LOG', str(capture))
    env, _ = wizard_runner._load_env_from_job('files_local', tmp_path / 'scripts', tmp_path)
    assert env['BORG_FILE_ACTIVITY'] == ('1' if started_enabled else '0')
    assert (env['LOG_FILE'] == str(capture)) == started_enabled
