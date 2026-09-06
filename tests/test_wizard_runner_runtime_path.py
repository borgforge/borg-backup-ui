from pathlib import Path
import json
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from test_canonical_job_wizard import setup, create
from job_runs import create_run_context
from inventory_store import atomic_write_json
from storage_objects_api import read_storage_store
import wizard_runner  # noqa: E402
from repositories_api import write_repository_store  # noqa: E402
from storage_objects_api import write_storage_store  # noqa: E402


def test_wizard_runner_prefers_plugin_runtime_before_data_root(tmp_path: Path):
    plugin_runtime = wizard_runner.ROOT_DIR / "runtime"
    data_root = tmp_path / "borg-backup"
    data_root.mkdir()

    original = list(sys.path)
    try:
        for path in (str(plugin_runtime), str(data_root)):
            while path in sys.path:
                sys.path.remove(path)

        wizard_runner._ensure_runtime_import_paths(data_root)

        assert sys.path.index(str(plugin_runtime)) < sys.path.index(str(data_root))
    finally:
        sys.path[:] = original


def test_wizard_runner_preserves_docker_exclusion_runtime_control():
    control = wizard_runner._runtime_control({
        "features": {"docker": True},
        "docker_control": {
            "mode": "except_selected",
            "selected": ["beszel", "beszel-agent", "beszel"],
        },
    }, "docker")

    assert control == {
        "mode": "except_selected",
        "selected": ["beszel", "beszel-agent"],
    }


def test_wizard_runner_passes_exact_prefix_union_to_maintenance() -> None:
    source = (ROOT / "api/wizard_runner.py").read_text()
    assert 'archive_prefix = snapshot["archive_prefix_snapshot"]' in source
    assert 'archive_prefixes=snapshot["archive_prefixes_snapshot"]' in source


def test_wizard_runner_resolves_repository_and_secret_from_repository_object(setup, monkeypatch):
    config, _, scripts, root = setup
    result, _ = create(setup)
    secret = root / 'synthetic.passphrase'
    secret.write_text('synthetic-only')
    repo_file = root / 'config/repositories.json'
    repos = json.loads(repo_file.read_text())
    repos['repositories'][0].update(passphrase_ref=str(secret),encryption='repokey-blake2')
    atomic_write_json(repo_file,repos)
    monkeypatch.setenv('BORG_UI_CONTROL_ROOT',str(root / 'run'))
    monkeypatch.delenv('BORG_PASSCOMMAND',raising=False)
    snapshot = create_run_context(config,result['job_id'])
    monkeypatch.setenv('BORG_UI_RUN_ID',snapshot['run_id'])
    env, metadata = wizard_runner._load_env_from_job(result['job_id'],scripts,root)
    assert env['BORG_REPO'] == str(root / 'repos/repo_a')
    assert metadata['_resolved_repository']['passphrase_ref'] == str(secret)
    assert json.loads(env['BACKUP_PATHS_JSON']) == [str(root / 'source')]
    assert 'repo' not in metadata and 'passphrase' not in metadata
    assert wizard_runner.os.environ['BORG_PASSCOMMAND'] == f'cat {secret}'


def test_wizard_runner_keeps_ssh_identity_and_keepalive_options(setup, monkeypatch):
    config, _, scripts, root = setup
    key_path = root / 'keys/storage box'
    key_path.parent.mkdir()
    key_path.write_text('synthetic-key-fixture')
    storages = read_storage_store(config)
    storages['storages'][1]['ssh_key_path'] = str(key_path)
    write_storage_store(config,storages)
    result, _ = create(setup,repository_key='repo_b')
    monkeypatch.setenv('BORG_UI_CONTROL_ROOT',str(root / 'run'))
    monkeypatch.delenv('BORG_RSH',raising=False)
    snapshot = create_run_context(config,result['job_id'])
    monkeypatch.setenv('BORG_UI_RUN_ID',snapshot['run_id'])
    env, _ = wizard_runner._load_env_from_job(result['job_id'],scripts,root)
    tokens = shlex.split(env['BORG_RSH'])
    assert tokens[tokens.index('-i')+1] == str(key_path)
    assert 'ServerAliveInterval=30' in tokens
    assert 'ServerAliveCountMax=10' in tokens
    assert 'TCPKeepAlive=yes' in tokens


def test_runtime_repository_resolution_does_not_read_legacy_job_fields():
    runtime_files = [
        ROOT / "api" / "wizard_runner.py",
        ROOT / "api" / "wizard_api.py",
        ROOT / "api" / "restore_api.py",
        ROOT / "api" / "system_health_api.py",
        ROOT / "api" / "smb_mount.py",
        ROOT / "runtime" / "scripts" / "borg_restore_test.py",
    ]
    forbidden = (
        '.get("repo")',
        ".get('repo')",
        '.get("passphrase")',
        ".get('passphrase')",
        '.get("create_repo_if_missing")',
        '.get("remote_init_confirmed")',
    )

    for path in runtime_files:
        source = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, f"{path.name} still reads legacy job metadata: {marker}"
        assert "SMB_PROFILES_JSON" not in source, f"{path.name} still depends on legacy SMB profile transport"


def test_wizard_runner_mounts_smb_from_resolved_storage_object(tmp_path: Path, monkeypatch) -> None:
    mount_path = tmp_path / "smb-mount"
    secret = tmp_path / ".smb-nas.cred"
    secret.write_text("username=backup\npassword=secret\n", encoding="utf-8")
    metadata = {
        "_resolved_location": "smb",
        "mount_before_run": True,
        "unmount_after_run": True,
        "_resolved_storage": {
            "storage_key": "storage_smb_nas",
            "profile_key": "smb-nas",
            "server": "nas.example.test",
            "share": "backup",
            "mount_path": str(mount_path),
            "username": "backup",
            "password_file": str(secret),
            "vers": "3.0",
        },
    }
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "findmnt":
            return type("FindmntResult", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        return Result()

    monkeypatch.setattr(wizard_runner.subprocess, "run", fake_run)

    session = wizard_runner._ensure_smb_mount({}, metadata)

    assert session.mounted_by_runner is True
    mount_command = next(command for command in calls if command[0] == "mount")
    assert mount_command[:5] == ["mount", "-t", "cifs", "//nas.example.test/backup", str(mount_path)]
    assert all("SMB_PROFILES_JSON" not in str(value) for value in mount_command)


def test_wizard_runner_auto_smb_mount_does_not_force_protocol(tmp_path: Path, monkeypatch) -> None:
    mount_path = tmp_path / "smb-mount"
    secret = tmp_path / ".smb-nas.cred"
    secret.write_text("username=backup\npassword=secret\n", encoding="utf-8")
    metadata = {
        "_resolved_location": "smb",
        "mount_before_run": True,
        "unmount_after_run": True,
        "_resolved_storage": {
            "storage_key": "storage_smb_nas",
            "profile_key": "smb-nas",
            "server": "nas.example.test",
            "share": "backup",
            "mount_path": str(mount_path),
            "username": "backup",
            "password_file": str(secret),
            "vers": "auto",
        },
    }
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return type("Result", (), {
            "returncode": 1 if command[0] == "findmnt" else 0,
            "stdout": "",
            "stderr": "",
        })()

    monkeypatch.setattr(wizard_runner.subprocess, "run", fake_run)
    session = wizard_runner._ensure_smb_mount({}, metadata)

    assert session.mounted_by_runner is True
    mount_command = next(command for command in calls if command[0] == "mount")
    assert "vers=" not in mount_command[-1]


def test_wizard_runner_respects_keep_mounted_profile_flag(tmp_path: Path, monkeypatch) -> None:
    mount_path = tmp_path / "smb-mount"
    secret = tmp_path / ".smb-nas.cred"
    secret.write_text("username=backup\npassword=secret\n", encoding="utf-8")
    metadata = {
        "_resolved_location": "smb",
        "mount_before_run": True,
        "unmount_after_run": True,
        "_resolved_storage": {
            "storage_key": "storage_smb_nas",
            "profile_key": "smb-nas",
            "server": "nas.example.test",
            "share": "backup",
            "mount_path": str(mount_path),
            "username": "backup",
            "password_file": str(secret),
            "vers": "auto",
            "keep_mounted": True,
        },
    }

    def fake_run(command, **_kwargs):
        return type("Result", (), {
            "returncode": 1 if command[0] == "findmnt" else 0,
            "stdout": "",
            "stderr": "",
        })()

    monkeypatch.setattr(wizard_runner.subprocess, "run", fake_run)
    session = wizard_runner._ensure_smb_mount({}, metadata)

    assert session.mounted_by_runner is True
    assert session.unmount_after_run is False
