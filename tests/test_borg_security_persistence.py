"""Issue #498: durable security state and the first backup after reboot."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "api"), str(ROOT / "runtime/lib"), str(ROOT / "tests")]

from borg_environment import (UNKNOWN_UNENCRYPTED, apply_borg_environment,
                              borg_security_dir, legacy_security_dir)
from migrations import borg_security_v1 as migration, registry
from repositories_api import _repo_env, write_repository_store
from restore_api import _repository_borg_env
from storage_objects_api import write_storage_store
from job_fixtures import identified_job, job_id


@pytest.fixture
def setup(tmp_path, monkeypatch):
    source = tmp_path / "volatile" / "security"
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "plugin")}
    monkeypatch.setenv("BORG_SECURITY_DIR", str(source))
    monkeypatch.setattr(registry, "MIGRATIONS", [migration])
    return config, source, borg_security_dir(config)


def records(directory, repo_id="a" * 64):
    values = {"key-type": b"3", "location": b"/repo", "manifest-timestamp": b"2026-09-17T10:00:00",
              "nonce": b"0000000010000000"}
    directory = directory / repo_id
    directory.mkdir(parents=True)
    for name, content in values.items():
        (directory / name).write_bytes(content)
    return {str(Path(repo_id) / name): value for name, value in values.items()}


def test_adoption_snapshot_audit_and_repeat_preserve_all_state(setup):
    config, source, target = setup
    original = records(source)
    original.update(records(source, "b" * 64))
    assert migration.detect(config) == {"required": True}
    first = registry.run_startup_migrations(config)
    assert first["status"] == "ok"
    result = first["results"][migration.MIGRATION_ID]
    snapshot = Path(result["details"]["backup_directory"])
    for name, content in original.items():
        assert (source / name).read_bytes() == (target / name).read_bytes() == content
        assert (snapshot / "source" / name).read_bytes() == content
    assert json.loads((snapshot / "manifest.json").read_text())["status"] == "applied"
    # Subsequent Borg use has newer nonce/manifest state; restarting must not
    # import stale RAM files again or change their mtime.
    updated = target / ("a" * 64) / "nonce"
    updated.write_bytes(b"0000000020000000")
    before = updated.stat().st_mtime_ns
    assert migration.detect(config) == {"required": False}
    assert migration.apply(config)["status"] == "not_required"
    assert registry.run_startup_migrations(config)["status"] == "ok"
    assert updated.read_bytes() == b"0000000020000000"
    assert updated.stat().st_mtime_ns == before
    events = [json.loads(line) for line in (Path(config["BACKUP_SCRIPTS_DIR"]) / "config/migrations.log.jsonl").read_text().splitlines()]
    assert sum(e.get("event") == "migration_applied" for e in events) == 1


@pytest.mark.parametrize("conflict", [False, True])
def test_existing_target_is_never_overwritten(setup, conflict):
    config, source, target = setup
    records(source)
    original = records(target)
    if conflict:
        (target / ("a" * 64) / "nonce").write_bytes(b"0000000030000000")
    before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}
    outcome = registry.run_startup_migrations(config)
    assert outcome["status"] == ("failed" if conflict else "ok")
    assert before == {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert (source / ("a" * 64) / "nonce").read_bytes() == original[("a" * 64) + "/nonce"]
    if conflict:
        assert "Conflicting Borg security record" in outcome["results"][migration.MIGRATION_ID]["details"]["error"]


def test_interrupted_copy_resumes_from_snapshot_after_source_disappears(setup, monkeypatch):
    config, source, target = setup
    original = records(source)
    real = migration.atomic_write_bytes
    count = 0

    def interrupted(path, content, **kwargs):
        nonlocal count
        if target in path.parents:
            count += 1
            if count == 2:
                raise OSError("simulated interruption")
        return real(path, content, **kwargs)

    monkeypatch.setattr(migration, "atomic_write_bytes", interrupted)
    assert registry.run_startup_migrations(config)["status"] == "failed"
    assert migration.detect(config)["required"]
    plan = json.loads(migration._journal(config).read_text())
    shutil.rmtree(source)
    monkeypatch.setattr(migration, "atomic_write_bytes", real)
    assert registry.run_startup_migrations(config)["status"] == "ok"
    assert json.loads(migration._journal(config).read_text())["backup_directory"] == plan["backup_directory"]
    assert all((target / name).read_bytes() == content for name, content in original.items())


def test_unavailable_destination_fails_without_volatile_fallback(setup, monkeypatch):
    config, source, target = setup
    records(source)
    import status
    monkeypatch.setattr(status, "status_storage_unavailable_reason", lambda path: "test storage is not mounted")
    assert registry.run_startup_migrations(config)["status"] == "failed"
    with pytest.raises(OSError, match="storage unavailable"):
        apply_borg_environment({}, config, encryption="none")
    assert not target.exists()
    assert source.is_dir()


def test_unrecognized_or_symlink_source_is_reported(setup):
    config, source, target = setup
    records(source)
    (source / ("b" * 64)).symlink_to(source / ("a" * 64), target_is_directory=True)
    assert registry.run_startup_migrations(config)["status"] == "failed"
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("changed", ["source", "snapshot"])
def test_changed_input_during_pending_migration_is_not_adopted(setup, changed):
    config, source, target = setup
    records(source)
    target.mkdir(parents=True)
    plan = migration._plan(config, target)
    directory = source if changed == "source" else Path(plan["backup_directory"]) / "source"
    (directory / ("a" * 64) / "nonce").write_bytes(b"0000000040000000")
    assert registry.run_startup_migrations(config)["status"] == "failed"
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("encryption", ["none", "repokey-blake2", "keyfile", ""])
def test_all_operation_environments_use_canonical_path(setup, monkeypatch, encryption):
    config, source, target = setup
    monkeypatch.setenv(UNKNOWN_UNENCRYPTED, "yes")
    from test_restore_test_runner_profiles import _load_restore_runner
    runner = _load_restore_runner()
    instance = object.__new__(runner.RestoreTest)
    instance.conf = config
    envs = [
        _repo_env({}, None, config, encryption=encryption),
        _repo_env({}, None, config, encryption=encryption, persistent_keys=False),
        _repository_borg_env(config, {"repo": "/repo", "passphrase_file": None, "encryption": encryption}),
        instance._env(None, {}, "/repo", encryption=encryption),
    ]
    for env in envs:
        assert env["BORG_SECURITY_DIR"] == str(target)
        assert (env.get(UNKNOWN_UNENCRYPTED) == "yes") == (encryption == "none")
    assert borg_security_dir({"BACKUP_SCRIPTS_DIR": str(target.parent / "scripts")}) == target
    assert not source.exists()


def test_legacy_location_respects_borg_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("BORG_SECURITY_DIR", raising=False)
    monkeypatch.delenv("BORG_CONFIG_DIR", raising=False)
    monkeypatch.delenv("BORG_BASE_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert legacy_security_dir() == tmp_path / "xdg/borg/security"
    monkeypatch.setenv("BORG_BASE_DIR", str(tmp_path / "base"))
    assert legacy_security_dir() == tmp_path / "base/.config/borg/security"
    monkeypatch.setenv("BORG_CONFIG_DIR", str(tmp_path / "conf"))
    assert legacy_security_dir() == tmp_path / "conf/security"


def test_standalone_restore_worker_uses_configured_inventory_root(tmp_path):
    script = """
import importlib.util, os, sys
from pathlib import Path
root, data = map(Path, sys.argv[1:])
os.environ['BORG_UI_DATA_ROOT'] = str(data)
spec = importlib.util.spec_from_file_location('restore_worker', root / 'runtime/scripts/borg_restore_test.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
instance = object.__new__(module.RestoreTest)
instance.conf = {}
env = instance._env(None, {}, '/repo', encryption='none')
assert env['BORG_SECURITY_DIR'] == str(data / 'borg-security')
assert env['BORG_KEYS_DIR'] == str(data / 'secrets/borg-keys')
"""
    result = subprocess.run([sys.executable, "-I", "-c", script, str(ROOT), str(tmp_path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def _managed_job(config, repo, encryption, pass_file, source):
    key = job_id("security_local")
    write_storage_store(config, {"storages": [{"storage_key": "storage_test", "display_name": "Local",
        "storage_type": "local", "location": "local", "base_path": str(repo.parent)}]})
    write_repository_store(config, {"repositories": [{"repository_key": "repo_test", "display_name": "Test",
        "storage_key": "storage_test", "relative_path": repo.name, "path_raw": str(repo),
        "encryption": encryption, "passphrase_ref": str(pass_file) if pass_file else ""}]})
    root = Path(config["BACKUP_SCRIPTS_DIR"])
    jobs = root / "config/jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    (jobs / f"{key}.json").write_text(json.dumps(identified_job({"job_key": key, "name": "Security test", "backup_type": "security",
        "location": "local", "repository_key": "repo_test", "source_paths": [str(source)],
        "compression": "lz4", "retention": {"daily": "7", "weekly": "4", "monthly": "6", "yearly": "3"}})))
    (root / "config/backup.conf").write_text(f'GLOBAL_BORG_CACHE_BASE="{root}/cache"\n')
    return key


@pytest.mark.parametrize("encryption,missing", [("none", False), ("none", True), ("repokey", False), ("keyfile-blake2", False)])
def test_real_borg_backup_after_reboot(setup, tmp_path, monkeypatch, encryption, missing):
    borg = shutil.which("borg")
    if not borg:
        pytest.skip("Real Borg executable required")
    config, volatile, target = setup
    # The backup worker deliberately updates its process environment. Isolate
    # that behavior so later tests never inherit a temporary security path.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    for key in list(os.environ):
        if key.startswith("BORG_") and key != "BORG_SECURITY_DIR":
            os.environ.pop(key)
    root = Path(config["BACKUP_SCRIPTS_DIR"])
    root.mkdir()
    repo = tmp_path / "repository"
    source = tmp_path / "data.txt"
    source.write_text("Content survives the simulated reboot.\n")
    pass_file = root / "passphrase" if encryption != "none" else None
    if pass_file:
        pass_file.write_text("test-only-passphrase")
    key = _managed_job(config, repo, encryption, pass_file, source)
    import wizard_runner
    env, _ = wizard_runner._load_env_from_job(key, root / "scripts", root)
    before = dict(os.environ, BORG_SECURITY_DIR=str(volatile))
    before["BORG_CACHE_DIR"] = env["BORG_CACHE_DIR"]

    def run(args, environment, expected=0):
        result = subprocess.run([borg, *args], env=environment, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == expected, result.stderr
        return result

    run(["init", "--encryption", encryption, str(repo)], before)
    run(["create", f"{repo}::before", str(source)], before)
    old = migration._records(volatile)
    if missing:
        shutil.rmtree(volatile)
        rejected = {k: v for k, v in before.items() if k != UNKNOWN_UNENCRYPTED}
        assert "unknown unencrypted repository" in run(["create", f"{repo}::rejected", str(source)], rejected, 2).stderr
    monkeypatch.setenv("BORG_SECURITY_DIR", str(volatile))
    assert registry.run_startup_migrations(config)["status"] == "ok"
    if not missing:
        assert migration._records(target) == old
    if volatile.exists():
        shutil.rmtree(volatile)
    # No repository-info refresh: directly execute the next managed backup.
    env, _ = wizard_runner._load_env_from_job(key, root / "scripts", root)
    after = dict(os.environ)
    assert env["BORG_SECURITY_DIR"] == after["BORG_SECURITY_DIR"] == str(target)
    run(["create", f"{repo}::after", str(source)], after)
    after.pop(UNKNOWN_UNENCRYPTED, None)
    run(["create", f"{repo}::another-reboot", str(source)], after)
    assert "after" in run(["list", "--short", str(repo)], after).stdout
    assert run(["extract", "--stdout", f"{repo}::after", str(source).lstrip("/")], after).stdout == source.read_text()
    assert migration._records(target)
    assert not volatile.exists()
    if encryption != "none":
        # Persistent replay detection still applies with an empty cache.
        timestamp = next(target.glob("*/manifest-timestamp"))
        timestamp.write_text("2999-01-01T00:00:00.000000")
        after["BORG_CACHE_DIR"] = str(tmp_path / "empty-cache")
        rejected = run(["info", str(repo)], after, 2)
        assert "newer than repository" in rejected.stderr
