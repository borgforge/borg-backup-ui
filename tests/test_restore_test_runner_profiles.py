from job_fixtures import identified_job, job_id
import importlib.util
import json
import pytest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def _load_restore_runner():
    path = ROOT / "runtime" / "scripts" / "borg_restore_test.py"
    spec = importlib.util.spec_from_file_location("borg_restore_test_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_due_restore_run_uses_all_locations_after_selecting_jobs() -> None:
    source = (ROOT / "borg_backup_ui.py").read_text(encoding="utf-8")

    assert 'auto_selected = True\n            location = "all"' in source
    assert 'cmd.append("--scheduled")' in source


def test_restore_runner_supports_scheduled_notifications() -> None:
    source = (ROOT / "runtime" / "scripts" / "borg_restore_test.py").read_text(encoding="utf-8")

    assert 'parser.add_argument("--scheduled"' in source
    assert 'restore_test_success' in source
    assert 'restore_test_failed' in source
    assert 'self._notify_event("restore_test_overdue"' not in source
    assert 'clear_reminder_prefix(self.conf, f"restore_test_overdue:{job_name}:")' in source


def test_restore_runner_discovers_usb_profile_repository(tmp_path, monkeypatch) -> None:
    runner = _load_restore_runner()
    script_dir = tmp_path / "runtime" / "scripts"
    config_dir = tmp_path / "runtime" / "config"
    jobs_dir = config_dir / "jobs"
    jobs_dir.mkdir(parents=True)
    script_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "SCRIPT_DIR", script_dir)
    monkeypatch.setenv("BORG_UI_DATA_ROOT", str(tmp_path / "runtime"))

    (jobs_dir / (job_id('testjob_usb') + ".json")).write_text(
        json.dumps(identified_job({
            "schema_version": 2,
            "enabled": True,
            "runner": "scriptless-wizard-runner",
            "job_key": job_id('testjob_usb'),
            "backup_type": "testjob",
            "location": "usb",
            "repository_key": "repo_testjob_usb",
        })),
        encoding="utf-8",
    )
    (config_dir / "storages.json").write_text(json.dumps({
        "schema_version": 1,
        "storages": [{
            "storage_key": "storage_usb_test",
            "display_name": "USB-5TB",
            "storage_type": "usb",
            "location": "usb",
            "identity": "usb-profile:usb-5tb",
            "profile_key": "usb-5tb",
            "base_path": "/mnt/disks/WCJ54TRQ",
            "mount_path": "/mnt/disks/WCJ54TRQ",
        }],
    }), encoding="utf-8")
    (config_dir / "repositories.json").write_text(json.dumps({
        "schema_version": 1,
        "repositories": [{
            "repository_key": "repo_testjob_usb",
            "display_name": "Testjob",
            "storage_key": "storage_usb_test",
            "relative_path": "borg-backup-testjob",
            "path_raw": "/mnt/disks/WCJ54TRQ/borg-backup-testjob",
            "encryption": "none",
        }],
    }), encoding="utf-8")

    repos = runner.discover_repos({})

    assert [{key: row[key] for key in (
        "job_key", "type", "location", "path", "encryption", "passphrase_file", "profile_key",
        "mount_before_run", "unmount_after_run",
    )} for row in repos] == [{
        "job_key": job_id('testjob_usb'),
        "type": "",
        "location": "usb",
        "path": "/mnt/disks/WCJ54TRQ/borg-backup-testjob",
        "encryption": "none",
        "passphrase_file": "",
        "profile_key": "usb-5tb",
        "mount_before_run": True,
        "unmount_after_run": True,
    }]
    assert repos[0]["storage"]["storage_key"] == "storage_usb_test"


def _restore_test_instance(runner, monkeypatch):
    instance = object.__new__(runner.RestoreTest)
    instance.args = SimpleNamespace(dry_run=False)
    instance.test_level = 1
    instance.conf = {}
    monkeypatch.setattr(instance, "_should_test", lambda _key: True)
    monkeypatch.setattr(instance, "_write", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(instance, "_cleanup_smb_mount", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(instance, "log", lambda *_args, **_kwargs: None)
    return instance


def test_restore_runner_tests_unencrypted_repository_without_passphrase(tmp_path, monkeypatch) -> None:
    runner = _load_restore_runner()
    instance = _restore_test_instance(runner, monkeypatch)
    repository = tmp_path / "borg-backup-unencrypted"
    repository.mkdir()
    passphrases = []

    def fake_env(passphrase, _storage, _repository):
        passphrases.append(passphrase)
        return {}

    def fake_borg(args, _env, timeout=None):
        if args[:3] == ["list", "--short", "--last"]:
            return SimpleNamespace(returncode=0, stdout="archive-1\n", stderr="")
        if args[:2] == ["info", "--json"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"archives": [{"stats": {}}]}), stderr="")
        raise AssertionError(f"Unexpected Borg call: {args}, timeout={timeout}")

    monkeypatch.setattr(instance, "_env", fake_env)
    monkeypatch.setattr(instance, "_borg", fake_borg)
    monkeypatch.setattr(
        instance,
        "_read_passphrase",
        lambda _path: (_ for _ in ()).throw(AssertionError("unencrypted repository requested a passphrase")),
    )

    result = instance.test_repo({
        "job_key": "testdata_local",
        "type": "testdata",
        "location": "local",
        "path": str(repository),
        "encryption": "none",
        "passphrase_file": "",
        "storage": {},
    })

    assert result == 0
    assert passphrases == [None]


def test_restore_runner_removes_inherited_passphrase_for_unencrypted_repository(tmp_path, monkeypatch) -> None:
    runner = _load_restore_runner()
    instance = object.__new__(runner.RestoreTest)
    instance.conf = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "borg-backup" / "scripts")}
    monkeypatch.setenv("BORG_PASSPHRASE", "must-not-leak")
    monkeypatch.setenv("BORG_PASSCOMMAND", "must-not-run")

    env = instance._env(None, {}, str(tmp_path / "repository"))

    assert "BORG_PASSPHRASE" not in env
    assert "BORG_PASSCOMMAND" not in env


def test_restore_runner_keeps_passphrase_requirement_for_encrypted_repository(tmp_path, monkeypatch) -> None:
    runner = _load_restore_runner()
    instance = _restore_test_instance(runner, monkeypatch)
    repository = tmp_path / "borg-backup-encrypted"
    repository.mkdir()
    messages = []
    monkeypatch.setattr(instance, "log", messages.append)

    result = instance.test_repo({
        "job_key": "testdata_local",
        "type": "testdata",
        "location": "local",
        "path": str(repository),
        "encryption": "repokey-blake2",
        "passphrase_file": str(tmp_path / "missing-passphrase"),
        "storage": {},
    })

    assert result == 1
    assert any("Passphrase file not found" in message for message in messages)


def test_restore_runner_discovers_smb_profile_repository(tmp_path, monkeypatch) -> None:
    runner = _load_restore_runner()
    script_dir = tmp_path / "runtime" / "scripts"
    config_dir = tmp_path / "runtime" / "config"
    jobs_dir = config_dir / "jobs"
    jobs_dir.mkdir(parents=True)
    script_dir.mkdir(parents=True)
    monkeypatch.setattr(runner, "SCRIPT_DIR", script_dir)
    monkeypatch.setenv("BORG_UI_DATA_ROOT", str(tmp_path / "runtime"))

    (jobs_dir / (job_id('photos_smb') + ".json")).write_text(
        json.dumps(identified_job({
            "schema_version": 2,
            "enabled": True,
            "runner": "scriptless-wizard-runner",
            "job_key": job_id('photos_smb'),
            "backup_type": "photos",
            "location": "smb",
            "repository_key": "repo_photos_smb",
        })),
        encoding="utf-8",
    )
    (config_dir / "storages.json").write_text(json.dumps({
        "schema_version": 1,
        "storages": [{
            "storage_key": "storage_smb_test",
            "display_name": "NAS A",
            "storage_type": "smb",
            "location": "smb",
            "identity": "smb-profile:nas-a",
            "profile_key": "nas-a",
            "base_path": "/mnt/remotes/nas-a",
            "mount_path": "/mnt/remotes/nas-a",
        }],
    }), encoding="utf-8")
    (config_dir / "repositories.json").write_text(json.dumps({
        "schema_version": 1,
        "repositories": [{
            "repository_key": "repo_photos_smb",
            "display_name": "Photos",
            "storage_key": "storage_smb_test",
            "relative_path": "borg-backup-photos",
            "path_raw": "/mnt/remotes/nas-a/borg-backup-photos",
            "encryption": "none",
        }],
    }), encoding="utf-8")

    repos = runner.discover_repos({})

    assert repos[0]["path"] == "/mnt/remotes/nas-a/borg-backup-photos"
    assert repos[0]["profile_key"] == "nas-a"


def test_restore_runner_auto_smb_mount_does_not_force_protocol(tmp_path, monkeypatch) -> None:
    runner = _load_restore_runner()
    secret = tmp_path / ".smb-nas.cred"
    secret.write_text("username=backup\npassword=secret\n", encoding="utf-8")
    mount_path = tmp_path / "mount"
    instance = object.__new__(runner.RestoreTest)
    instance.args = SimpleNamespace(smb_auto_mount=True)
    monkeypatch.setattr(instance, "_is_smb_mounted", lambda _path: False)

    def fake_run(command, **_kwargs):
        assert command[0] == "mount"
        assert "vers=" not in command[-1]
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    mounted, error = instance._ensure_smb_mount({
        "location": "smb",
        "profile_key": "nas",
        "mount_before_run": True,
        "storage": {
            "server": "nas.example.test",
            "share": "backup",
            "mount_path": str(mount_path),
            "password_file": str(secret),
            "vers": "auto",
        },
    })

    assert mounted is True
    assert error == ""


@pytest.mark.parametrize("size_gb,file_count,directory_count,expected,chunked", [
    (600, 10_000, 5_000, 500, True),
    (600, 100_000, 5_000, 1_000, True),
    (500, 20_000, 25_000, 1_000, True),
    (500, 30, 3_000, 2, True),
    (499, 10_000, 5_000, 10_000, False),
])
def test_restore_probe_uses_size_and_regular_file_limits(tmp_path, monkeypatch, size_gb, file_count, directory_count, expected, chunked):
    runner = _load_restore_runner()
    instance = _restore_test_instance(runner, monkeypatch)
    instance.test_level = 2
    instance.min_coverage = 5
    instance.max_entries = 1000
    instance.dryrun_max_files = 1000
    instance.dryrun_chunk = 100
    instance.dryrun_timeout = 0
    instance.sample_size = 5
    instance.full_dryrun_max_archive_gb = 500
    # An old configuration entry must no longer force sampling below the size threshold.
    instance.conf = {"RESTORE_TEST_FORCE_CHUNK_TYPES": "photos,vms"}
    rows = [{"type": "d", "path": f"folder-{i}"} for i in range(directory_count)]
    rows += [{"type": "-", "path": f"folder-{i % 10}/file-{i}"} for i in range(file_count)]
    rows += [{"type": "l", "path": "symbolic-link"}]
    calls, results = [], []
    def fake_borg(args, _env, timeout=None):
        if args[:3] == ["list", "--short", "--last"]:
            output = "archive-1\n"
        elif args[:2] == ["info", "--json"]:
            output = json.dumps({"archives": [{"stats": {"original_size": size_gb * 1024**3}}]})
        elif args[:2] == ["list", "--json-lines"]:
            output = "\n".join(json.dumps(row) for row in rows)
        elif args[:2] == ["extract", "--dry-run"]:
            calls.append(args)
            output = ""
        else:
            raise AssertionError(args)
        return SimpleNamespace(returncode=0, stdout=output, stderr="")
    monkeypatch.setattr(instance, "_env", lambda *_args: {})
    monkeypatch.setattr(instance, "_borg", fake_borg)
    monkeypatch.setattr(instance, "_write", lambda *args, **kwargs: results.append((args, kwargs)))
    result = instance.test_repo({"job_key": job_id("photos_local"), "type": "photos", "name": "Renamed job",
                                 "location": "local", "path": str(tmp_path), "encryption": "none", "passphrase_file": ""})
    assert result == 0
    args, details = results[-1]
    assert args[4:7] == (expected, 0, expected)
    assert details["test_coverage_pct"] == round(expected / file_count * 100, 1)
    assert args[9]["files_count"] == file_count
    if chunked:
        selected = [path for call in calls for path in call[3:]]
        assert len(selected) == len(set(selected)) == expected
        assert all("/file-" in path for path in selected)
        assert all(0 < len(call[3:]) <= 100 for call in calls)
        assert len(args[10]) == expected
    else:
        assert len(calls) == 1 and len(calls[0]) == 3
