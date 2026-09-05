"""#473: real schema-v4 metadata lifecycle, no startup migration or Borg."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from inventory_store import atomic_write_json
from job_model import (JobValidationError, apply_wizard_changes, archive_name_preview,
                       validate_archive_prefix, validate_job, validate_job_id)
from job_store import job_revision, read_job, read_json, read_jobs
from storage_objects_api import write_storage_store
from wizard_api import generate_flow_preview, load_job_for_wizard, save_job, validate_params


@pytest.fixture
def setup(tmp_path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path)}
    source = tmp_path / "source"
    source.mkdir()
    write_storage_store(config, {"storages": [
        {"storage_key": "local", "storage_type": "local", "location": "local", "base_path": str(tmp_path / "repos")},
        {"storage_key": "remote", "storage_type": "ssh", "location": "storagebox", "base_path": "./backup",
         "host": "example.invalid", "user": "synthetic", "port": "23", "profile_key": "synthetic"},
    ]})
    repos = {"schema_version": 1, "unknown_store_setting": {"preserve": True}, "repositories": [
        {"repository_key": key, "storage_key": storage, "relative_path": key, "encryption": "none",
         "job_ids": [], "source_job_ids": [], "unknown_repo_setting": [1, 2]}
        for key, storage in [("repo_a", "local"), ("repo_b", "remote")]
    ]}
    atomic_write_json(tmp_path / "config" / "repositories.json", repos)
    params = {"job_name": "Synthetic job", "archive_prefix": "Exact.Prefix_1", "repository_key": "repo_a",
              "source_paths": [str(source)]}
    return config, params, tmp_path / "scripts", tmp_path


def create(setup, **changes):
    config, params, scripts, root = setup
    result = save_job({**params, **changes}, scripts, root, config)
    return result, read_json(Path(result["metadata_path"]))


def edit(setup, job_id, **changes):
    config, _, scripts, root = setup
    return save_job({"_wizard_mode": "edit", "job_id": job_id, **changes}, scripts, root, config)


def test_create_and_read_exact_identity_and_prefix_without_suffix(setup, monkeypatch):
    config, params, scripts, root = setup
    calls = []
    fixed = UUID("11111111-1111-4111-8111-111111111111")
    monkeypatch.setattr("uuid.uuid4", lambda: calls.append(1) or fixed)
    validate_params(deepcopy(params), scripts, root, ui_config=config)
    assert generate_flow_preview(params)["archive_name_preview"] == "Exact.Prefix_1-YYYY-MM-DD_HH-mm-ss"
    assert calls == []
    result, meta = create(setup)
    assert calls == [1]
    assert result["job_id"] == str(fixed)
    assert Path(result["metadata_path"]).name == str(fixed) + ".json"
    assert meta["archive_prefixes"] == ["Exact.Prefix_1"]
    assert meta["legacy_job_keys"] == []
    assert not {"job_key", "type_id", "backup_type", "location", "passphrase", "repo", "encryption"}.intersection(meta)
    before = Path(result["metadata_path"]).read_bytes()
    loaded = load_job_for_wizard(result["job_id"], scripts, config)
    assert loaded["location"] == "local"
    assert loaded["archive_prefix"] == "Exact.Prefix_1"
    assert loaded["revision"] == job_revision(meta)
    assert Path(result["metadata_path"]).read_bytes() == before
    assert calls == [1]


def test_rename_preserves_every_operational_setting_and_alias(setup):
    result, original = create(setup)
    original.update(enabled=False, legacy_job_keys=["config_local"], file_activity=True,
                    mount_before_run=False, unmount_after_run=False, compression="auto,zstd,10",
                    restore_test_policy={"mode": "scheduled", "level": 3}, future_setting={"list": [1, False, None]})
    original["features"]["future_feature"] = {"enabled": True}
    original["docker_control"]["future_option"] = ["preserve"]
    original["retention"].update(daily="0", future_tier="31")
    atomic_write_json(Path(result["metadata_path"]), original)
    edit(setup, result["job_id"], job_name="Renamed without identity changes")
    after = read_json(Path(result["metadata_path"]))
    expected = deepcopy(original)
    expected.update(name=after["name"], updated_at=after["updated_at"])
    assert after == expected
    assert len(list((setup[3] / "config" / "jobs").glob("*.json"))) == 1


def test_prefix_history_keeps_order_and_exact_current_prefix(setup):
    result, _ = create(setup)
    for prefix in ["other", "third", "other"]:
        response = edit(setup, result["job_id"], archive_prefix=prefix)
        assert response["job_id"] == result["job_id"]
    assert read_json(Path(result["metadata_path"]))["archive_prefixes"] == ["other", "third", "Exact.Prefix_1"]


def test_repository_change_preserves_identity_and_updates_only_assignments(setup):
    result, before = create(setup)
    root = setup[3]
    store_before = read_json(root / "config" / "repositories.json")
    edit(setup, result["job_id"], repository_key="repo_b")
    after = read_json(Path(result["metadata_path"]))
    expected = deepcopy(before)
    expected.update(repository_key="repo_b", updated_at=after["updated_at"])
    assert after == expected
    store_after = read_json(root / "config" / "repositories.json")
    assert store_after["unknown_store_setting"] == store_before["unknown_store_setting"]
    for repo in store_after["repositories"]:
        expected_ids = [result["job_id"]] if repo["repository_key"] == "repo_b" else []
        assert repo["job_ids"] == repo["source_job_ids"] == expected_ids
        assert repo["unknown_repo_setting"] == [1, 2]
    loaded = load_job_for_wizard(result["job_id"], setup[2], setup[0])
    assert loaded["location"] == "storagebox"
    assert loaded["repo_path"] == "ssh://synthetic@example.invalid:23/./backup/repo_b"


def test_duplicate_gets_new_id_no_aliases_or_old_archive_ownership(setup):
    result, meta = create(setup)
    meta.update(legacy_job_keys=["config_local"], future_setting={"keep": True})
    atomic_write_json(Path(result["metadata_path"]), meta)
    duplicate, copied = create(setup, _wizard_mode="duplicate", job_id=result["job_id"],
                               job_name="Copy", archive_prefix="IndependentCopy")
    assert duplicate["job_id"] != result["job_id"]
    assert copied["legacy_job_keys"] == []
    assert copied["archive_prefixes"] == ["IndependentCopy"]
    assert copied["future_setting"] == {"keep": True}
    assert read_json(Path(result["metadata_path"])) == meta


@pytest.mark.parametrize("prefix", ["", ".", "..", "a b", " leading", "trailing ", "a/b", "a\\b", "a::*", "a*", "a?", "a[0]", "a\n", "\x00", None, 17])
def test_invalid_prefixes_are_rejected_without_writes(setup, prefix):
    with pytest.raises(JobValidationError):
        create(setup, archive_prefix=prefix)
    assert not (setup[3] / "config" / "jobs").exists()


@pytest.mark.parametrize("prefix", ["simple", "Case-Sensitive_1.2", "--still-a-prefix", "already-backup"])
def test_valid_prefix_preview_is_exact(prefix):
    assert validate_archive_prefix(prefix) == prefix
    assert archive_name_preview(prefix) == prefix + "-YYYY-MM-DD_HH-mm-ss"


@pytest.mark.parametrize("value", [None, "", "config_local", "../secret", "11111111111141118111111111111111",
                                  "11111111-1111-1111-8111-111111111111", "11111111-1111-4111-7111-111111111111",
                                  "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"])
def test_invalid_ids_never_become_paths_or_new_jobs(setup, value):
    with pytest.raises(JobValidationError):
        edit(setup, value, job_name="Cannot create this way")


@pytest.mark.parametrize("field", ["type_id", "job_key", "backup_type", "existing_job_key", "legacy_job_keys", "archive_prefixes"])
def test_legacy_and_client_owned_history_arguments_rejected(setup, field):
    with pytest.raises(JobValidationError, match="requests must use"):
        create(setup, **{field: "arbitrary"})


def test_unknown_edit_id_and_client_generated_create_id_rejected(setup):
    job_id = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(JobValidationError, match="Unknown job_id"):
        edit(setup, job_id)
    with pytest.raises(JobValidationError, match="assigned by the server"):
        create(setup, job_id=job_id)


def test_optimistic_revision_prevents_stale_editor_overwrite(setup):
    result, meta = create(setup)
    edit(setup, result["job_id"], job_name="Changed meanwhile")
    with pytest.raises(JobValidationError, match="changed since"):
        edit(setup, result["job_id"], expected_revision=job_revision(meta), job_name="Stale edit")
    assert read_json(Path(result["metadata_path"]))["name"] == "Changed meanwhile"


@pytest.mark.parametrize("prefix", ["Exact.Prefix_1", "Exact.Prefix_1-more", "Exact.Prefix_1-more-backup"])
def test_shared_repository_ownership_checks_history_and_delimiters(setup, prefix):
    result, _ = create(setup)
    edit(setup, result["job_id"], archive_prefix="current")
    with pytest.raises(JobValidationError, match="overlap"):
        create(setup, archive_prefix=prefix)
    # The same prefix in an independent repository does not overlap.
    create(setup, archive_prefix=prefix, repository_key="repo_b")


@pytest.mark.parametrize("change", ["schema", "id", "filename", "json", "duplicate-member", "legacy"])
def test_invalid_existing_metadata_is_not_repaired_or_overwritten(setup, change):
    result, meta = create(setup)
    path = Path(result["metadata_path"])
    if change == "schema":
        meta["schema_version"] = 99
    elif change == "id":
        meta.pop("job_id")
    elif change == "legacy":
        meta["job_key"] = "old_local"
    if change == "filename":
        path = path.rename(path.with_name("wrong.json"))
    else:
        raw = '{"token":"not-to-be-exposed",' if change == "json" else json.dumps(meta)
        if change == "duplicate-member":
            raw = raw[:-1] + ',"name":"duplicate"}'
        path.write_text(raw)
    before = path.read_bytes()
    with pytest.raises(JobValidationError) as error:
        edit(setup, result["job_id"], job_name="No")
    assert "not-to-be-exposed" not in str(error.value)
    assert path.read_bytes() == before


def test_partial_write_failure_restores_original_bytes(setup, monkeypatch):
    import job_store
    result, _ = create(setup)
    path = Path(result["metadata_path"])
    repo_path = setup[3] / "config" / "repositories.json"
    before = path.read_bytes(), repo_path.read_bytes()
    write = job_store.atomic_write_json

    def fail_repository(target, data):
        if target == repo_path:
            raise OSError("synthetic I/O failure")
        write(target, data)

    monkeypatch.setattr(job_store, "atomic_write_json", fail_repository)
    with pytest.raises(OSError, match="synthetic"):
        edit(setup, result["job_id"], repository_key="repo_b")
    assert (path.read_bytes(), repo_path.read_bytes()) == before


def test_missing_or_mismatching_reverse_links_block_before_writes(setup):
    result, _ = create(setup)
    path = setup[3] / "config" / "repositories.json"
    store = read_json(path)
    store["repositories"][0]["job_ids"] = []
    atomic_write_json(path, store)
    before = Path(result["metadata_path"]).read_bytes()
    with pytest.raises(JobValidationError, match="assignments"):
        edit(setup, result["job_id"], job_name="No silent reconciliation")
    assert Path(result["metadata_path"]).read_bytes() == before


def test_duplicate_aliases_block_and_equal_names_are_not_identity(setup):
    first, one = create(setup)
    second, two = create(setup, archive_prefix="Independent")
    assert one["name"] == two["name"]
    assert first["job_id"] != second["job_id"]
    for result, meta in ((first, one), (second, two)):
        meta["legacy_job_keys"] = ["same_legacy_key"]
        atomic_write_json(Path(result["metadata_path"]), meta)
    with pytest.raises(JobValidationError, match="conflicting owners"):
        read_jobs(setup[3] / "config" / "jobs")


def test_symlink_metadata_is_not_followed(setup):
    from migrations.identity_storage import IdentityStorageError
    result, _ = create(setup)
    path = Path(result["metadata_path"])
    moved = path.rename(setup[3] / "synthetic-original.json")
    path.symlink_to(moved)
    before = moved.read_bytes()
    with pytest.raises(IdentityStorageError):
        edit(setup, result["job_id"], job_name="Do not follow a link")
    assert moved.read_bytes() == before


def test_concurrent_same_prefix_creates_cannot_take_over_each_other(setup):
    from concurrent.futures import ThreadPoolExecutor

    def attempt(_):
        try:
            return create(setup)[0]["job_id"]
        except JobValidationError as exc:
            return exc.api_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert results.count("ambiguous_archive_ownership") == 1
    assert len(read_jobs(setup[3] / "config" / "jobs")) == 1


def test_identity_mutation_is_rejected_by_pure_model(setup):
    _, meta = create(setup)
    with pytest.raises(JobValidationError, match="cannot change"):
        apply_wizard_changes({}, existing=meta, job_id="22222222-2222-4222-8222-222222222222", now="synthetic")


@pytest.mark.parametrize("field,value", [
    ("file_activity", "false"), ("enabled", 0), ("retention", {"daily": 0}),
    ("docker_control", {"mode": "unknown"}), ("vm_control", None),
])
def test_unsupported_existing_operational_values_block_instead_of_being_reset(setup, field, value):
    result, meta = create(setup)
    meta[field] = value
    path = Path(result["metadata_path"])
    atomic_write_json(path, meta)
    before = path.read_bytes()
    with pytest.raises(JobValidationError):
        edit(setup, result["job_id"], job_name="Must not reset settings")
    assert path.read_bytes() == before


def test_wizard_http_handlers_use_ids_and_do_not_allocate_on_preview(setup, monkeypatch):
    sys.path.insert(0, str(ROOT))
    import borg_backup_ui

    config, params, _, root = setup
    handler = borg_backup_ui.BackupUIHandler.__new__(borg_backup_ui.BackupUIHandler)
    handler.config = config
    handler._read_json_body = lambda: deepcopy(params)
    assert handler._post_wizard_preview()["flow"]["job_id"] is None
    assert not (root / "config" / "jobs").exists()
    result = handler._post_wizard_save()
    loaded = handler._get_wizard_job("job_id=" + result["job_id"])["job"]
    assert loaded["job_id"] == result["job_id"]
    for query in ("job_key=config_local", "", "job_id=" + result["job_id"] + "&job_id=" + result["job_id"]):
        with pytest.raises(ValueError):
            handler._get_wizard_job(query)
    handler._read_json_body = lambda: {
        "_wizard_mode": "edit", "job_id": result["job_id"], "expected_revision": result["revision"],
        "job_name": "Renamed through HTTP boundary", "archive_prefix": "RenamedPrefix",
    }
    updated = handler._post_wizard_save()
    assert updated["job_id"] == result["job_id"]
    assert updated["archive_name_preview"] == "RenamedPrefix-YYYY-MM-DD_HH-mm-ss"


def test_planner_target_jobs_can_be_opened_without_startup_registration(tmp_path):
    from identity_contract_support import load_cases, materialize
    from migrations.immutable_job_id_v1 import build_plan
    from migrations.registry import MIGRATIONS

    case = next(c for c in load_cases() if c["id"] == "legacy_without_prefixes")
    root = tmp_path / "installation"
    fixture = materialize(case, root)
    fixture["config"]["PLUGIN_DIR"] = str(root / "plugin")
    plan = build_plan(fixture["config"], control_root=root / "run")
    assert plan["classification"] == "applicable"
    # Explicit synthetic target setup, not a production apply engine.
    for path, record in plan["records"].items():
        if record["kind"] in {"job", "repositories", "schedules"}:
            atomic_write_json(Path(path), record["data"])
            for source in record.get("sources", []):
                if record["kind"] == "job" and source != path:
                    Path(source).unlink()
    for path, record in plan["records"].items():
        if record["kind"] == "job":
            job = record["data"]
            validate_job(job, filename=Path(path).name)
            opened = load_job_for_wizard(job["job_id"], root / "data" / "scripts", fixture["config"])
            assert opened["archive_prefix"] == "config-backup"
    assert all(getattr(m, "MIGRATION_ID", "") != "immutable_job_id_v1" for m in MIGRATIONS)
