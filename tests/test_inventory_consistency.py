from __future__ import annotations

import sys
import threading
import multiprocessing
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

import inventory_store  # noqa: E402
import repositories_api  # noqa: E402
from inventory_store import InventoryCorruptError  # noqa: E402
from repositories_api import (  # noqa: E402
    read_repository_store,
    read_repository_store_for_api,
    repositories_file,
    update_repository_store,
    write_repository_store,
)
from storage_objects_api import read_storage_store, storages_file, write_storage_store  # noqa: E402
from storage_objects_api import replace_all_profile_storages  # noqa: E402


def _config(tmp_path: Path) -> dict:
    return {"BACKUP_SCRIPTS_DIR": str(tmp_path)}


def _repository(key: str) -> dict:
    return {
        "repository_key": key,
        "display_name": key,
        "location": "local",
        "storage_type": "local",
        "storage_key": "storage_local",
        "relative_path": key,
        "path_raw": f"/mnt/backup/{key}",
    }


def _process_repository_update(root: str, key: str, ready, start) -> None:
    config = {"BACKUP_SCRIPTS_DIR": root}
    ready.put(key)
    start.wait(timeout=10)

    def update(store):
        time.sleep(0.1)
        return {"repositories": [*store["repositories"], _repository(key)]}

    update_repository_store(config, update)


@pytest.mark.parametrize(
    ("filename", "reader"),
    [("repositories.json", read_repository_store), ("storages.json", read_storage_store)],
)
def test_existing_malformed_inventory_is_not_treated_as_empty(tmp_path: Path, filename: str, reader) -> None:
    config = _config(tmp_path)
    path = tmp_path / "config" / filename
    path.parent.mkdir(parents=True)
    path.write_text('{"broken":', encoding="utf-8")
    with pytest.raises(InventoryCorruptError, match="malformed JSON"):
        reader(config)


def test_interrupted_replace_preserves_previous_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    write_repository_store(config, {"repositories": [_repository("repo_old")]})
    path = repositories_file(config)
    original = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(inventory_store.os, "replace", fail_replace)
    with pytest.raises(inventory_store.InventoryAccessError):
        write_repository_store(config, {"repositories": [_repository("repo_new")]})
    assert path.read_bytes() == original
    assert not list(path.parent.glob(".repositories.json.*.tmp"))


def test_inventory_files_keep_restrictive_permissions(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_repository_store(config, {"repositories": []})
    write_storage_store(config, {"storages": []})
    assert repositories_file(config).stat().st_mode & 0o777 == 0o600
    assert storages_file(config).stat().st_mode & 0o777 == 0o600


def test_repository_inventory_cache_avoids_reparse_and_detects_external_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    path = repositories_file(config)
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"schema_version":1,"updated_at":"first","repositories":[]}',
        encoding="utf-8",
    )
    original_reader = repositories_api.read_inventory
    reads: list[Path] = []

    def counted_reader(source, **kwargs):
        reads.append(Path(source))
        return original_reader(source, **kwargs)

    monkeypatch.setattr(repositories_api, "read_inventory", counted_reader)

    assert read_repository_store(config)["updated_at"] == "first"
    assert read_repository_store(config)["updated_at"] == "first"
    assert reads == [path]

    path.write_text(
        '{"schema_version":1,"updated_at":"externally-updated","repositories":[]}',
        encoding="utf-8",
    )
    assert read_repository_store(config)["updated_at"] == "externally-updated"
    assert reads == [path, path]

    path.write_text('{"broken":', encoding="utf-8")
    with pytest.raises(InventoryCorruptError, match="malformed JSON"):
        read_repository_store(config)


def test_concurrent_repository_updates_do_not_lose_rows(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_repository_store(config, {"repositories": []})
    barrier = threading.Barrier(8)
    errors: list[Exception] = []

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            update_repository_store(
                config,
                lambda store: {"repositories": [*store["repositories"], _repository(f"repo_{index}")]},
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert errors == []
    assert {row["repository_key"] for row in read_repository_store(config)["repositories"]} == {
        f"repo_{index}" for index in range(8)
    }


def test_separate_process_repository_updates_do_not_corrupt_or_lose_rows(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_repository_store(config, {"repositories": []})
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    processes = [
        context.Process(target=_process_repository_update, args=(str(tmp_path), f"repo_process_{index}", ready, start))
        for index in range(2)
    ]
    for process in processes:
        process.start()
    assert {ready.get(timeout=10) for _ in processes} == {"repo_process_0", "repo_process_1"}
    start.set()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    payload = read_repository_store(config)
    assert {row["repository_key"] for row in payload["repositories"]} == {
        "repo_process_0",
        "repo_process_1",
    }


def test_job_link_transaction_rolls_back_when_job_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    repository = _repository("repo_target")
    write_repository_store(config, {"repositories": [repository]})
    metadata_path = tmp_path / "config" / "jobs" / "appdata_local.json"

    def fail_job_write(_path, _payload, **_kwargs):
        raise inventory_store.InventoryAccessError("injected job write failure")

    monkeypatch.setattr(repositories_api, "atomic_write_json", fail_job_write)
    with pytest.raises(inventory_store.InventoryAccessError):
        repositories_api.save_job_repository_transaction(
            config,
            metadata_path,
            {"job_key": "appdata_local", "repository_key": "repo_target"},
            "repo_target",
            "appdata_local",
        )
    assert not metadata_path.exists()
    restored = read_repository_store(config)["repositories"][0]
    assert restored["used_by"] == []
    assert restored["source_job_keys"] == []


def test_repository_path_is_derived_from_current_storage_target(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_pool",
        "display_name": "Pool",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    repository = {**_repository("repo_target"), "storage_key": "storage_pool", "relative_path": "repo_target"}
    write_repository_store(config, {"repositories": [repository]})
    assert read_repository_store_for_api(config)["repositories"][0]["path_raw"] == "/mnt/backup/repo_target"

    write_storage_store(config, {"storages": [{
        "storage_key": "storage_pool",
        "display_name": "Moved Pool",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/new-pool",
        "base_path": "/mnt/new-pool",
    }]})
    current = read_repository_store_for_api(config)["repositories"][0]
    assert current["path_raw"] == "/mnt/new-pool/repo_target"
    assert current["storage_name"] == "Moved Pool"


def test_repository_inventory_persists_only_canonical_path_contract(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_pool",
        "display_name": "Pool",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [{
        **_repository("repo_target"),
        "storage_key": "storage_pool",
        "relative_path": "borg-backup-target",
        "repo_path": "/mnt/legacy/borg-backup-target",
        "repo_uri": "ssh://legacy.invalid/./borg-backup-target",
        "path_raw": "/mnt/legacy/borg-backup-target",
        "path_display": "/mnt/legacy/borg-backup-target",
        "repo_conf_key": "REPO_TARGET",
        "usb_profile_key": "usb-legacy",
    }]})

    persisted = read_repository_store(config)["repositories"][0]
    for legacy_field in (
        "repo_path",
        "repo_uri",
        "path_raw",
        "path_display",
        "repo_conf_key",
        "usb_profile_key",
    ):
        assert legacy_field not in persisted
    assert persisted["storage_key"] == "storage_pool"
    assert persisted["relative_path"] == "borg-backup-target"
    api_row = read_repository_store_for_api(config)["repositories"][0]
    assert api_row["path_raw"] == "/mnt/backup/borg-backup-target"


def test_multi_profile_update_rolls_back_on_later_validation_error(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local",
        "display_name": "Original",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    original = storages_file(config).read_bytes()
    with pytest.raises(ValueError, match="SSH host"):
        replace_all_profile_storages(config, {
            "local_profiles": [{"name": "Changed", "base_path": "/mnt/new-pool"}],
            "usb_profiles": [],
            "smb_profiles": [],
            "storage_profiles": [{"key": "broken", "name": "Broken", "host": "", "user": "", "base_path": ""}],
        })
    assert storages_file(config).read_bytes() == original


def test_job_delete_transaction_rolls_back_when_metadata_delete_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    repository = {**_repository("repo_target"), "used_by": ["appdata_local"], "source_job_keys": ["appdata_local"]}
    write_repository_store(config, {"repositories": [repository]})
    metadata_path = tmp_path / "config" / "jobs" / "appdata_local.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text('{"job_key":"appdata_local","repository_key":"repo_target"}\n', encoding="utf-8")
    original_unlink = Path.unlink

    def fail_metadata_unlink(path: Path, *args, **kwargs):
        if path == metadata_path:
            raise OSError("injected metadata delete failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_metadata_unlink)
    with pytest.raises(OSError, match="injected"):
        repositories_api.delete_job_metadata_transaction(config, [metadata_path], "appdata_local")
    assert metadata_path.exists()
    restored = read_repository_store(config)["repositories"][0]
    assert restored["used_by"] == ["appdata_local"]
    assert restored["source_job_keys"] == ["appdata_local"]


def test_repository_usage_is_rebuilt_from_authoritative_job_assignments(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_storage_store(config, {"storages": [{
        "storage_key": "storage_local",
        "display_name": "Local",
        "storage_type": "local",
        "location": "local",
        "identity": "local:/mnt/backup",
        "base_path": "/mnt/backup",
    }]})
    write_repository_store(config, {"repositories": [{
        **_repository("repo_target"),
        "used_by": ["stale_job"],
        "source_job_keys": ["stale_job"],
    }]})
    metadata_path = tmp_path / "config" / "jobs" / "appdata_local.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        '{"schema_version":2,"job_key":"appdata_local","repository_key":"repo_target"}\n',
        encoding="utf-8",
    )

    before = repositories_api.repository_assignment_report(config)
    assert before["ok"] is False
    assert before["usage_mismatches"][0]["expected_job_keys"] == ["appdata_local"]

    after = repositories_api.reconcile_repository_usage(config)
    assert after["ok"] is True
    assert after["reconciled_repository_keys"] == ["repo_target"]
    repository = read_repository_store(config)["repositories"][0]
    assert repository["used_by"] == ["appdata_local"]
    assert repository["source_job_keys"] == ["appdata_local"]


def test_repository_assignment_report_guides_job_wizard_repair(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_storage_store(config, {"storages": []})
    write_repository_store(config, {"repositories": []})
    metadata_path = tmp_path / "config" / "jobs" / "photos_smb.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        '{"schema_version":2,"job_key":"photos_smb","repository_key":"repo_missing"}\n',
        encoding="utf-8",
    )

    report = repositories_api.repository_assignment_report(config)

    assert report["ok"] is False
    error = report["errors"][0]
    assert error["code"] == "job_repository_not_found"
    assert error["job_key"] == "photos_smb"
    assert "Job Wizard" in error["message"]
