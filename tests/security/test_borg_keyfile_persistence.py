from __future__ import annotations

import base64
import json
import os
import shutil
import shlex
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from borg_key_store import (  # noqa: E402
    apply_borg_key_environment,
    borg_keys_dir,
    import_default_key_if_present,
    remove_repository_key,
)
import repositories_api  # noqa: E402
from repositories_api import create_or_import_repository, refresh_repository_info, write_repository_store  # noqa: E402
import settings_transfer_api as transfer  # noqa: E402
from settings_transfer_api import export_jobs_bundle, export_jobs_bundle_encrypted, import_jobs_bundle_encrypted  # noqa: E402
from storage_objects_api import write_storage_store  # noqa: E402


REPOSITORY_ID = "a" * 64


def _key_content(repository_id: str = REPOSITORY_ID) -> bytes:
    return f"BORG_KEY {repository_id}\nZmFrZS1lbmNyeXB0ZWQta2V5\n".encode()


def test_persistent_key_environment_and_permissions(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "borg-backup")}

    env = apply_borg_key_environment({"PATH": "/usr/bin"}, config)

    directory = Path(env["BORG_KEYS_DIR"])
    assert directory == borg_keys_dir(config)
    assert directory.is_dir()
    assert directory.stat().st_mode & 0o777 == 0o700


def test_legacy_key_copy_is_exact_and_does_not_overwrite(tmp_path: Path, monkeypatch):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "borg-backup")}
    home = tmp_path / "home"
    legacy = home / ".config" / "borg" / "keys"
    legacy.mkdir(parents=True)
    (legacy / "wanted").write_bytes(_key_content())
    (legacy / "unrelated").write_bytes(_key_content("b" * 64))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    copied = import_default_key_if_present(config, REPOSITORY_ID)

    assert copied is not None
    assert copied.read_bytes() == _key_content()
    assert copied.stat().st_mode & 0o777 == 0o600
    assert not (borg_keys_dir(config) / "unrelated").exists()
    copied.write_bytes(_key_content() + b"local-change\n")
    assert import_default_key_if_present(config, REPOSITORY_ID) == copied
    assert copied.read_bytes().endswith(b"local-change\n")


def test_key_removal_is_scoped_and_respects_remaining_references(tmp_path: Path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "borg-backup")}
    key_dir = borg_keys_dir(config)
    key_dir.mkdir(parents=True)
    target = key_dir / "target"
    unrelated = key_dir / "unrelated"
    target.write_bytes(_key_content())
    unrelated.write_bytes(_key_content("b" * 64))

    assert remove_repository_key(config, REPOSITORY_ID, [REPOSITORY_ID]) is False
    assert target.exists()
    assert remove_repository_key(config, REPOSITORY_ID, []) is True
    assert not target.exists()
    assert unrelated.exists()


def test_plain_job_export_contains_only_keyfile_metadata(tmp_path: Path):
    root = tmp_path / "borg-backup"
    config = {"BACKUP_SCRIPTS_DIR": str(root)}
    jobs = root / "config" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "flash_local.json").write_text(json.dumps({
        "schema_version": 3,
        "job_key": "flash_local",
        "name": "Flash",
        "repository_key": "repo_flash",
        "source_paths": ["/boot"],
    }), encoding="utf-8")
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [{
        "repository_key": "repo_flash",
        "display_name": "Flash",
        "storage_key": "storage_local",
        "relative_path": "borg-backup-flash",
        "path_raw": "/mnt/backup/borg-backup-flash",
        "encryption": "keyfile-blake2",
        "borg_repository_id": REPOSITORY_ID,
    }]})
    key_dir = borg_keys_dir(config)
    key_dir.mkdir(parents=True)
    (key_dir / "flash").write_bytes(_key_content())

    result = export_jobs_bundle(config)
    metadata = result["bundle"]["keyfile_meta"]["repo_flash"]

    assert metadata["exists"] is True
    assert metadata["size"] > 0
    assert "content_b64" not in metadata
    assert "ZmFrZS1lbmNyeXB0ZWQta2V5" not in result["bundle_text"]


def test_encrypted_job_transfer_restores_keyfile_to_target_store(tmp_path: Path):
    source = tmp_path / "source"
    source_config = {"BACKUP_SCRIPTS_DIR": str(source)}
    jobs = source / "config" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "flash_local.json").write_text(json.dumps({
        "schema_version": 3,
        "job_key": "flash_local",
        "name": "Flash",
        "repository_key": "repo_flash",
        "source_paths": ["/boot"],
    }), encoding="utf-8")
    write_storage_store(source_config, {"storages": [{
        "storage_key": "storage_local",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(source_config, {"repositories": [{
        "repository_key": "repo_flash",
        "display_name": "Flash",
        "storage_key": "storage_local",
        "relative_path": "borg-backup-flash",
        "path_raw": "/mnt/backup/borg-backup-flash",
        "encryption": "keyfile-blake2",
        "borg_repository_id": REPOSITORY_ID,
    }]})
    source_key_dir = borg_keys_dir(source_config)
    source_key_dir.mkdir(parents=True)
    (source_key_dir / "flash").write_bytes(_key_content())
    exported = export_jobs_bundle_encrypted(source_config, "transfer-password-190")
    target_config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "target")}

    result = import_jobs_bundle_encrypted(
        target_config,
        "transfer-password-190",
        exported["payload_b64"],
        dry_run=False,
        settings_mode="ignore",
    )

    assert exported["keyfile_count"] == 1
    assert result["restored_keyfiles"] == 1
    restored = list(borg_keys_dir(target_config).glob("*"))
    assert len(restored) == 1
    assert restored[0].read_bytes() == _key_content()


def test_encrypted_job_transfer_excludes_repository_key_exports(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    config = {"BACKUP_SCRIPTS_DIR": str(source)}
    jobs = source / "config" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "flash_local.json").write_text(json.dumps({
        "schema_version": 3,
        "job_key": "flash_local",
        "name": "Flash",
        "repository_key": "repo_flash",
        "source_paths": ["/boot"],
    }), encoding="utf-8")
    (jobs / "appdata_local.json").write_text(json.dumps({
        "schema_version": 3,
        "job_key": "appdata_local",
        "name": "Appdata",
        "repository_key": "repo_appdata",
        "source_paths": ["/mnt/user/appdata"],
    }), encoding="utf-8")
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [
        {
            "repository_key": "repo_flash",
            "display_name": "Flash",
            "storage_key": "storage_local",
            "relative_path": "borg-backup-flash",
            "path_raw": "/mnt/backup/borg-backup-flash",
            "encryption": "keyfile-blake2",
            "borg_repository_id": REPOSITORY_ID,
        },
        {
            "repository_key": "repo_appdata",
            "display_name": "Appdata",
            "storage_key": "storage_local",
            "relative_path": "borg-backup-appdata",
            "path_raw": "/mnt/backup/borg-backup-appdata",
            "encryption": "repokey-blake2",
            "borg_repository_id": "b" * 64,
        },
    ]})
    calls = []

    def fake_export_repository_key(config_arg, repository_key, **kwargs):
        calls.append(repository_key)
        return {
            "repository_id": "b" * 64,
            "key_data": _key_content("b" * 64).decode("utf-8"),
        }

    monkeypatch.setattr(repositories_api, "export_repository_key", fake_export_repository_key)

    exported = export_jobs_bundle_encrypted(config, "transfer-password-190")
    plaintext, _fmt = transfer._decrypt_encrypted_export(
        base64.b64decode(exported["payload_b64"], validate=True),
        "transfer-password-190",
    )
    payload = json.loads(plaintext.decode("utf-8"))

    assert calls == []
    assert exported["borg_key_export_count"] == 0
    assert exported["borg_key_export_failed_count"] == 0
    assert "borg_key_exports" not in payload


def test_repository_key_backup_exports_and_imports_matching_repository_key(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    source_config = {"BACKUP_SCRIPTS_DIR": str(source)}
    write_storage_store(source_config, {"storages": [{
        "storage_key": "storage_local",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(source_config, {"repositories": [{
        "repository_key": "repo_appdata",
        "display_name": "Appdata",
        "storage_key": "storage_local",
        "relative_path": "borg-backup-appdata",
        "path_raw": "/mnt/backup/borg-backup-appdata",
        "encryption": "repokey-blake2",
        "borg_repository_id": "b" * 64,
    }]})
    key_data = _key_content("b" * 64).decode("utf-8")
    monkeypatch.setattr(repositories_api, "export_repository_key", lambda config, repository_key, **kwargs: {
        "repository_id": "b" * 64,
        "key_data": key_data,
    })
    exported = transfer.export_repository_keys_backup(source_config, "transfer-password-190")
    plaintext, _fmt = transfer._decrypt_encrypted_export(
        base64.b64decode(exported["payload_b64"], validate=True),
        "transfer-password-190",
    )
    payload = json.loads(plaintext.decode("utf-8"))

    assert exported["repository_key_count"] == 1
    assert payload["format"] == "bbui-repository-keys-v1"
    assert payload["key_exports"]["repo_appdata"]["repository_id"] == "b" * 64

    target_config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "target")}
    write_storage_store(target_config, {"storages": [{
        "storage_key": "storage_local",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(target_config, {"repositories": [{
        "repository_key": "repo_appdata",
        "display_name": "Appdata",
        "storage_key": "storage_local",
        "relative_path": "borg-backup-appdata",
        "path_raw": "/mnt/backup/borg-backup-appdata",
        "encryption": "repokey-blake2",
        "borg_repository_id": "b" * 64,
    }]})
    calls = []

    def fake_import_repository_key(config_arg, repository_key, imported_key_data, **kwargs):
        calls.append((repository_key, imported_key_data))
        return {"ok": True}

    monkeypatch.setattr(repositories_api, "import_repository_key", fake_import_repository_key)

    preview = transfer.preview_repository_keys_backup_for_repository(
        target_config,
        "repo_appdata",
        "transfer-password-190",
        exported["payload_b64"],
    )

    assert preview["matching_key"]["exists"] is True
    assert preview["repository_id"] == "b" * 64

    result = transfer.import_repository_keys_backup_for_repository(
        target_config,
        "repo_appdata",
        "transfer-password-190",
        exported["payload_b64"],
    )

    assert calls == [("repo_appdata", key_data)]
    assert result["repository_id"] == "b" * 64


@pytest.mark.skipif(shutil.which("borg") is None, reason="borg is not installed")
def test_keyfile_repository_survives_fresh_process_environment(tmp_path: Path, monkeypatch):
    root = tmp_path / "borg-backup"
    repository_root = tmp_path / "repositories"
    config = {"BACKUP_SCRIPTS_DIR": str(root)}
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": f"local:{repository_root}",
        "base_path": str(repository_root),
    }]})

    created = create_or_import_repository(config, {
        "action": "create",
        "storage_key": "storage_local",
        "display_name": "Keyfile test",
        "repository_name": "keyfile-test",
        "relative_path": "keyfile-test",
        "encryption": "keyfile-blake2",
        "passphrase": "test-passphrase-190",
        "make_parent_dirs": True,
    })
    repository = created["repository"]
    keyfile = Path(repository["keyfile_ref"])

    assert keyfile.is_file()
    assert keyfile.parent == borg_keys_dir(config)
    assert keyfile.stat().st_mode & 0o777 == 0o600
    monkeypatch.delenv("BORG_KEYS_DIR", raising=False)
    monkeypatch.delenv("BORG_KEY_FILE", raising=False)
    refreshed = refresh_repository_info(config, repository["repository_key"])
    assert refreshed["ok"] is True


@pytest.mark.skipif(shutil.which("borg") is None, reason="borg is not installed")
def test_existing_keyfile_repository_can_import_exported_key(tmp_path: Path):
    source_root = tmp_path / "source"
    repository_root = tmp_path / "repositories"
    source_config = {"BACKUP_SCRIPTS_DIR": str(source_root)}
    storage = {
        "storage_key": "storage_local",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": f"local:{repository_root}",
        "base_path": str(repository_root),
    }
    write_storage_store(source_config, {"storages": [storage]})
    created = create_or_import_repository(source_config, {
        "action": "create",
        "storage_key": "storage_local",
        "display_name": "Imported keyfile test",
        "repository_name": "keyfile-import-test",
        "relative_path": "keyfile-import-test",
        "encryption": "keyfile-blake2",
        "passphrase": "test-passphrase-190",
        "make_parent_dirs": True,
    })["repository"]
    exported_key = tmp_path / "borg-key-export"
    env = apply_borg_key_environment(os.environ.copy(), source_config)
    env["BORG_PASSCOMMAND"] = f"cat {shlex.quote(created['passphrase_ref'])}"
    subprocess.run(
        ["borg", "key", "export", created["path_raw"], str(exported_key)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    target_config = {"BACKUP_SCRIPTS_DIR": str(tmp_path / "target")}
    write_storage_store(target_config, {"storages": [storage]})
    imported = create_or_import_repository(target_config, {
        "action": "import",
        "storage_key": "storage_local",
        "display_name": "Imported keyfile test",
        "repository_name": "keyfile-import-test",
        "relative_path": "keyfile-import-test",
        "passphrase": "test-passphrase-190",
        "key_data": exported_key.read_text(encoding="utf-8"),
    })["repository"]

    assert imported["encryption"] == "keyfile-blake2"
    assert Path(imported["keyfile_ref"]).is_file()
    assert Path(imported["keyfile_ref"]).parent == borg_keys_dir(target_config)
