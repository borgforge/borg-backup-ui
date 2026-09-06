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
from job_model import JobValidationError
from test_canonical_job_wizard import setup, create
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
        "job_ids": [], "source_job_ids": [],
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
    with pytest.raises((InventoryCorruptError, JobValidationError)):
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


def test_repository_inventory_reads_detect_external_corruption(tmp_path):
    config = _config(tmp_path)
    path = repositories_file(config)
    inventory_store.atomic_write_json(path, {"schema_version": 1, "updated_at": "first", "repositories": []})
    assert read_repository_store(config)["updated_at"] == "first"
    inventory_store.atomic_write_json(path, {"schema_version": 1, "updated_at": "changed", "repositories": []})
    assert read_repository_store(config)["updated_at"] == "changed"
    path.write_text('{"broken":')
    with pytest.raises(JobValidationError):
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


def test_job_link_transaction_rolls_back_when_job_write_fails(setup, monkeypatch):
    import job_store
    before = (setup[3] / "config/repositories.json").read_bytes()
    def fail_write(_path, _payload, **_kwargs):
        raise inventory_store.InventoryAccessError("injected job write failure")
    monkeypatch.setattr(job_store, "atomic_write_json", fail_write)
    with pytest.raises(inventory_store.InventoryAccessError):
        create(setup)
    assert list((setup[3] / "config/jobs").glob("*.json")) == []
    assert (setup[3] / "config/repositories.json").read_bytes() == before


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


def test_runtime_repository_reads_hide_transitional_fields(tmp_path: Path) -> None:
    config = _config(tmp_path)
    inventory_store.atomic_write_json(repositories_file(config), {
        "schema_version": 1,
        "repositories": [{
            **_repository("repo_target"),
            "relative_path": "repo_target",
            "repo_path": "/mnt/legacy/repo_target",
            "path_display": "/mnt/legacy/repo_target",
            "repo_conf_key": "REPO_TARGET",
            "smb_profile_key": "smb-legacy",
        }],
    })

    runtime_row = read_repository_store(config)["repositories"][0]
    migration_row = read_repository_store(config, preserve_legacy=True)["repositories"][0]

    for field in ("repo_path", "path_raw", "path_display", "repo_conf_key", "smb_profile_key"):
        assert field not in runtime_row
    assert migration_row["repo_path"] == "/mnt/legacy/repo_target"
    assert migration_row["path_display"] == "/mnt/legacy/repo_target"
    assert migration_row["repo_conf_key"] == "REPO_TARGET"
    assert migration_row["smb_profile_key"] == "smb-legacy"


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


def test_job_delete_transaction_rolls_back_when_metadata_delete_fails(setup, monkeypatch):
    from job_actions import delete_job_configuration
    import schedule_api
    result, _ = create(setup)
    path = Path(result["metadata_path"])
    before = path.read_bytes()
    original_unlink = Path.unlink
    monkeypatch.setattr(schedule_api, "_update_crontab", lambda _: pytest.fail("cron must not be invoked"))
    def fail_metadata_unlink(target, *args, **kwargs):
        if target == path:
            raise OSError("injected metadata delete failure")
        return original_unlink(target, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_metadata_unlink)
    with pytest.raises(OSError, match="injected"):
        delete_job_configuration(setup[0], result["job_id"])
    assert path.read_bytes() == before
    assert repositories_api.repository_assignment_report(setup[0])["ok"]


def test_repository_usage_conflicts_are_reported_without_repair(setup):
    from job_store import read_json
    result, _ = create(setup)
    path = setup[3] / "config/repositories.json"
    store = read_json(path)
    store["repositories"][0]["job_ids"] = []
    inventory_store.atomic_write_json(path, store)
    before = path.read_bytes()
    report = repositories_api.reconcile_repository_usage(setup[0])
    assert not report["ok"]
    assert report["usage_mismatches"][0]["expected_job_ids"] == [result["job_id"]]
    assert report["reconciled_repository_keys"] == [] and path.read_bytes() == before


def test_repository_assignment_report_identifies_missing_repository(setup):
    result, meta = create(setup)
    meta["repository_key"] = "missing"
    inventory_store.atomic_write_json(Path(result["metadata_path"]), meta)
    report = repositories_api.repository_assignment_report(setup[0])
    assert not report["ok"]
    assert report["errors"][0] == {"code": "job_repository_not_found", "job_id": result["job_id"], "repository_key": "missing"}
