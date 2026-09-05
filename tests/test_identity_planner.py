"""#472: exercise the inactive planner against real synthetic files.

The phase-1 execution goldens describe the eventual phase-9 cutover. Planning
never performs that cutover, even when a fixture models future confirmation.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID

import pytest

from identity_contract_support import ROOT, load_cases, materialize, source_value, tree_bytes

API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from migrations import immutable_job_id_v1 as migration  # noqa: E402
from migrations import identity_storage as storage  # noqa: E402
from migrations import registry  # noqa: E402


CASES = load_cases()
BY_ID = {case["id"]: case for case in CASES}
# These hooks did not supply real OS/snapshot/journal bytes in phase 1.
# Their safety boundaries are tested separately, not pretended to be inputs
# from which an initial read-only scan could infer administrator consent.
GATE_ONLY_CASES = {
    "live_writer", "source_changed_after_plan", "snapshot_unverified",
    "interrupted_with_journal",
}


@pytest.fixture
def identity_root():
    parent = ROOT / ".release-tmp"
    parent.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="identity-472-planner-", dir=parent) as directory:
        yield Path(directory)


def installation(case, root):
    installed = root / "installation"
    relocated = materialize(case, installed)
    # Never inspect the host's live control/widget paths from a synthetic case.
    relocated["config"]["PLUGIN_DIR"] = str(installed / "plugin")
    return installed, relocated


def plan_for(case, installed):
    values = iter(case["allocation_order"])
    return migration.build_plan(
        case["config"], uuid_factory=lambda: UUID(next(values)),
        control_root=installed / "run",
    )


def reason_codes(result):
    return {item["code"] if isinstance(item, dict) else item
            for item in result.get("reasons", [])}


def binding_projection(plan, installed):
    result = {}
    for item in plan.get("bindings", []):
        source = Path(item["source"]).relative_to(installed).as_posix()
        reference = source + "#" + item["locator"]
        assert reference not in result, "multiple contradictory binding outcomes"
        result[reference] = item["job_id"]
    return result


def _pointer(value, pointer):
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _planned_value(plan, installed, reference):
    """Read a destination object independently; never echo a source golden."""
    name, _, pointer = reference.partition("#")
    source = str(installed / name)
    targets = [record for target, record in plan["records"].items()
               if source == str(target) or source in record.get("sources", [])]
    assert len(targets) == 1, f"source lacks one destination: {name}"
    data = targets[0]["data"]
    if "observations" in data and "weekly" in name:
        parts = pointer.split("/")
        row_pointer = "/".join(parts[:3])
        observations = [row for row in data["observations"]
                        if {"source": source, "locator": row_pointer}
                        in row["source_records"]]
        assert len(observations) == 1
        return _pointer(observations[0], "/" + "/".join(parts[3:])) if len(parts) > 3 else observations[0]
    if name == "data/config/schedules.json":
        prefix = pointer.split("/", 2)[1]
        matching = [binding for binding in plan["bindings"]
                    if binding["source"] == source and binding["locator"] == "/" + prefix]
        if matching:
            pointer = "/" + matching[0]["job_id"] + pointer[len(prefix) + 1:]
    if name == "data/config/notification-state.json" and pointer.startswith("/last_sent/"):
        matching = [binding for binding in plan["bindings"]
                    if binding["source"] == source and binding["locator"] == pointer]
        if matching and matching[0]["job_id"]:
            event, old_key, due = pointer.removeprefix("/last_sent/").split(":", 2)
            pointer = f"/last_sent/{event}:{matching[0]['job_id']}:{due}"
    return _pointer(data, pointer)


def _assert_contains_original(actual, expected):
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for key, value in expected.items():
            assert key in actual, f"preserved member removed: {key}"
            _assert_contains_original(actual[key], value)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected)
        for observed, value in zip(actual, expected):
            _assert_contains_original(observed, value)
    else:
        assert actual == expected


@pytest.mark.parametrize("case", [c for c in CASES if c["id"] not in GATE_ONLY_CASES],
                         ids=lambda c: c["id"])
def test_read_only_planner_matches_phase1_identity_and_binding_goldens(case, identity_root):
    installed, relocated = installation(case, identity_root)
    before = tree_bytes(installed)
    plan = plan_for(relocated, installed)
    assert tree_bytes(installed) == before, "planning wrote installation data"
    expected = relocated["expected"]
    assert plan["classification"] == expected["classification"]
    assert plan["jobs"] == expected["jobs"]
    assert type(plan["required"]) is bool
    assert plan["required"] is (plan["classification"] != "not_applicable")
    assert plan["status"] == {
        "applicable": "pending", "blocked": "blocked",
        "not_applicable": "not_applicable",
    }[plan["classification"]]
    assert set(expected["reason_codes"]) <= reason_codes(plan)
    if plan["classification"] != "blocked":
        assert binding_projection(plan, installed) == expected["bindings"]
        for reference, value in expected["preserved"].items():
            _assert_contains_original(_planned_value(plan, installed, reference), value)
        for reference, value in expected["bindings"].items():
            if value is None:
                _assert_contains_original(_planned_value(plan, installed, reference),
                                          source_value(relocated["files"], reference))
        unassigned = {
            Path(row["source"]).relative_to(installed).as_posix() + "#" + row["locator"]:
                row["reason"] for row in plan["unassigned"]
        }
        assert unassigned == expected["unassigned"]


@pytest.mark.parametrize("case_id", ["source_changed_after_plan", "snapshot_unverified"])
def test_fixture_gate_booleans_are_not_misrepresented_as_initial_detection(case_id, identity_root):
    installed, relocated = installation(BY_ID[case_id], identity_root)
    before = tree_bytes(installed)
    plan = plan_for(relocated, installed)
    # Both fixtures have the same eligible input bytes as the base case.
    # The separate pre-apply verifier must enforce the changed/unverified
    # conditions using an actual plan/snapshot, not invisible fixture metadata.
    assert plan["classification"] == "applicable"
    assert plan["status"] == "pending"
    assert tree_bytes(installed) == before


def test_planner_not_registered_and_has_no_user_data_apply_entry_point():
    assert migration not in registry.MIGRATIONS
    assert all(getattr(item, "MIGRATION_ID", "") != "immutable_job_id_v1"
               for item in registry.MIGRATIONS)
    assert not hasattr(migration, "apply")


@pytest.mark.parametrize("replacement", [
    {"schema_version": True},
    {"schema_version": "3"},
    {"schema_version": 99},
    {"archive_prefixes": [""]},
    {"archive_prefixes": ["config-backup", 2]},
    {"archive_prefixes": ["config-backup", " "]},
    {"archive_prefixes": ["config-backup", "other*"]},
])
def test_unknown_or_unsafe_owned_metadata_blocks_without_writes(replacement, identity_root):
    case = deepcopy(BY_ID["legacy_without_prefixes"])
    case["files"]["data/config/jobs/config_local.json"]["json"].update(replacement)
    installed, relocated = installation(case, identity_root)
    before = tree_bytes(installed)
    plan = plan_for(relocated, installed)
    assert plan["classification"] == "blocked"
    assert plan["required"] is True
    assert not plan["jobs"]
    assert tree_bytes(installed) == before


@pytest.mark.parametrize("path", [
    "data/config/repositories.json", "data/config/storages.json",
    "data/config/schedules.json", "data/config/notification-queue.json",
    "data/config/notification-deliveries.json", "data/config/notification-state.json",
    "data/config/runtime-recovery.json", "data/config/restore-runs.json",
    "status/2026-08-31_08-00-00_config_local.status",
    "restore_tests/config_local.test", "weekly-snapshots.json",
    "status/weekly-snapshots.json",
])
def test_corrupt_owned_store_is_not_an_empty_or_ignored_store(path, identity_root):
    installed, relocated = installation(BY_ID["legacy_without_prefixes"], identity_root)
    changed = installed / path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("{invalid JSON", encoding="utf-8")
    before = tree_bytes(installed)
    plan = plan_for(relocated, installed)
    assert plan["classification"] == "blocked"
    assert plan["required"] is True
    assert tree_bytes(installed) == before


def test_duplicate_json_member_cannot_silently_choose_identity(identity_root):
    case = deepcopy(BY_ID["legacy_without_prefixes"])
    job = case["files"]["data/config/jobs/config_local.json"]["json"]
    encoded = json.dumps(job)
    case["files"]["data/config/jobs/config_local.json"] = {
        "text": encoded[:-1] + ', "job_key": "config_local"}',
    }
    installed, relocated = installation(case, identity_root)
    before = tree_bytes(installed)
    plan = plan_for(relocated, installed)
    assert plan["classification"] == "blocked"
    assert tree_bytes(installed) == before


@pytest.mark.parametrize("path", [
    "data/config/jobs/config_local.json",
    "status/2026-08-31_08-00-00_config_local.status",
])
def test_owned_symlink_is_not_followed(path, identity_root):
    installed, relocated = installation(BY_ID["legacy_without_prefixes"], identity_root)
    source = installed / path
    outside = identity_root / "outside-owned-root.json"
    source.rename(outside)
    source.symlink_to(outside)
    before = outside.read_bytes()
    plan = plan_for(relocated, installed)
    assert plan["classification"] == "blocked"
    assert source.is_symlink()
    assert outside.read_bytes() == before


def test_symlinked_owned_directory_is_not_followed(identity_root):
    installed, relocated = installation(BY_ID["legacy_without_prefixes"], identity_root)
    source = installed / "data/config/jobs"
    outside = identity_root / "outside-owned-jobs"
    source.rename(outside)
    source.symlink_to(outside, target_is_directory=True)
    before = tree_bytes(outside)
    plan = plan_for(relocated, installed)
    assert plan["classification"] == "blocked"
    assert source.is_symlink()
    assert tree_bytes(outside) == before


def test_allocator_cannot_reuse_an_id_for_distinct_jobs(identity_root):
    installed, relocated = installation(BY_ID["shared_repository_distinct_prefixes"], identity_root)
    before = tree_bytes(installed)
    duplicate = UUID(relocated["allocation_order"][0])
    plan = migration.build_plan(relocated["config"], uuid_factory=lambda: duplicate,
                                control_root=installed / "run")
    assert plan["classification"] == "blocked"
    assert not plan["jobs"]
    assert tree_bytes(installed) == before


@pytest.mark.parametrize("kind", ["resource", "control", "recovery"])
def test_real_live_owner_blocks_even_when_fixture_claims_quiescence(kind, identity_root):
    case = deepcopy(BY_ID["legacy_without_prefixes"])
    if kind == "resource":
        case["files"]["locks/fixture.lock.json"] = {"json": {
            "schema_version": 1, "job_key": "config_local", "pid": os.getpid(),
            "resource": "repo:fixture", "operation": "backup",
            "run_id": "fixture-live-run", "started_at": "2026-08-31T08:00:00Z",
            "updated_at": "2026-08-31T08:00:00Z",
        }}
    elif kind == "control":
        case["files"]["run/fixture-live-run/state.json"] = {"json": {
            "schema_version": 1, "job_key": "config_local", "pid": os.getpid(),
            "run_id": "fixture-live-run", "phase": "backup", "finished": False,
        }}
    else:
        case["files"]["data/config/runtime-recovery.json"] = deepcopy(
            BY_ID["pending_runtime_recovery"]["files"]["data/config/runtime-recovery.json"]
        )
        case["files"]["data/config/runtime-recovery.json"]["json"]["entries"][0]["pid"] = os.getpid()
    installed, relocated = installation(case, identity_root)
    before = tree_bytes(installed)
    plan = plan_for(relocated, installed)
    assert plan["classification"] == "blocked"
    assert tree_bytes(installed) == before


def test_invalid_resource_lock_is_not_assumed_inactive(identity_root):
    case = deepcopy(BY_ID["legacy_without_prefixes"])
    case["files"]["locks/fixture.lock.json"] = {"text": "{not readable lock JSON"}
    installed, relocated = installation(case, identity_root)
    before = tree_bytes(installed)
    plan = plan_for(relocated, installed)
    assert plan["classification"] == "blocked"
    assert tree_bytes(installed) == before


def test_owned_fifo_is_rejected_without_reading_or_writing_it(identity_root):
    installed, relocated = installation(BY_ID["legacy_without_prefixes"], identity_root)
    path = installed / "data/config/jobs/other_local.json"
    os.mkfifo(path)
    original = (installed / "data/config/jobs/config_local.json").read_bytes()
    plan = plan_for(relocated, installed)
    assert plan["classification"] == "blocked"
    assert (installed / "data/config/jobs/config_local.json").read_bytes() == original
    assert path.stat().st_size == 0


@pytest.mark.parametrize("case_id,valid", [
    ("already_migrated", True),
    ("partial_without_journal", False),
    ("legacy_without_prefixes", False),
])
def test_target_verifier_reads_actual_files_and_never_activates_writers(case_id, valid, identity_root):
    installed, relocated = installation(BY_ID[case_id], identity_root)
    before = tree_bytes(installed)
    result = migration.verify_target(relocated["config"], control_root=installed / "run")
    assert result["valid"] is valid
    assert result["writable_services_allowed"] is False
    assert tree_bytes(installed) == before


def test_ambiguous_numeric_zero_retention_is_blocked_not_silently_reinterpreted(identity_root):
    installed, relocated = installation(BY_ID["legacy_without_prefixes"], identity_root)
    source = installed / "data/config/jobs/config_local.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    data["retention"] = {"daily": 0, "weekly": 4, "monthly": 0, "yearly": 0}
    source.write_text(json.dumps(data), encoding="utf-8")
    before = tree_bytes(installed)
    plan = plan_for(relocated, installed)
    # The legacy runner treats numeric 0 as missing but string "0" as a
    # disabled tier. Neither guessing user intent nor silently inserting its
    # fallback is a safe migration of this ambiguous, non-wizard shape.
    assert plan["classification"] == "blocked"
    assert not plan["jobs"]
    assert tree_bytes(installed) == before


def test_resume_cannot_ignore_disappeared_restore_proof_without_canonical_replacement(identity_root):
    installed, relocated = installation(BY_ID["restore_result_and_history"], identity_root)
    plan = plan_for(relocated, installed)
    assert plan["classification"] == "applicable"
    persisted = storage.persist_plan(plan, identity_root / "migration-state")
    (installed / "restore_tests/config_local.test").unlink()
    before = tree_bytes(installed)
    resumed = migration.build_plan(relocated["config"], journal_plan=persisted,
                                   control_root=installed / "run")
    assert resumed["classification"] == "blocked"
    assert tree_bytes(installed) == before


def test_legacy_extra_alias_does_not_authorize_repair_of_reported_orphan_schedule(identity_root):
    installed, relocated = installation(BY_ID["reported_config_to_pfsense_orphan_schedule"], identity_root)
    source = installed / "data/config/jobs/pfsense_local.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    # The old product never recorded this field as a migration identity proof.
    # A stray field is not a reviewed repair map or a validated saved journal.
    data["legacy_job_keys"] = ["config_local"]
    source.write_text(json.dumps(data), encoding="utf-8")
    before = tree_bytes(installed)
    plan = plan_for(relocated, installed)
    assert plan["classification"] == "blocked"
    assert tree_bytes(installed) == before


def test_canonical_recovery_descriptors_are_not_active_mutable_identity(identity_root):
    installed, relocated = installation(BY_ID["already_migrated"], identity_root)
    payload = deepcopy(BY_ID["pending_runtime_recovery"]["files"]["data/config/runtime-recovery.json"]["json"])
    entry = payload["entries"][0]
    entry["job_id"] = relocated["allocation_order"][0]
    entry["log_file"] = str(installed / "logs/Borg-Backup_config--2026-08-31_08-00-00.log")
    source = installed / "data/config/runtime-recovery.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    before = tree_bytes(installed)
    result = migration.verify_target(relocated["config"], control_root=installed / "run")
    assert result["valid"] is True
    assert result["writable_services_allowed"] is False
    assert tree_bytes(installed) == before


@pytest.mark.parametrize("kind", ["status", "weekly"])
def test_canonical_inventory_cannot_hide_unconverted_known_job_history_as_orphan(kind, identity_root):
    installed, relocated = installation(BY_ID["already_migrated"], identity_root)
    if kind == "status":
        path = installed / "status/2026-08-31_08-00-00_config_local.status"
        payload = json.loads(path.read_text(encoding="utf-8"))
        del payload["job_id"]
        del payload["schema_version"]
    else:
        path = installed / "weekly-snapshots.json"
        payload = {"config_local": [{"week": "2026-08-31", "size": 100}]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = tree_bytes(installed)
    result = migration.verify_target(relocated["config"], control_root=installed / "run")
    assert result["valid"] is False
    assert result["writable_services_allowed"] is False
    assert tree_bytes(installed) == before


def _persisted_partial_job_plan(identity_root):
    """Simulate a future applier boundary on fixture files, not plugin data."""
    installed, relocated = installation(BY_ID["legacy_without_prefixes"], identity_root)
    original = plan_for(relocated, installed)
    state_dir = identity_root / "migration-state"
    persisted = storage.persist_plan(original, state_dir)
    source = str(installed / "data/config/jobs/config_local.json")
    write = next(action for action in persisted["actions"]
                 if action["kind"] == "write_json" and action["source"] == source)
    retirement = next(action for action in persisted["actions"]
                      if action["kind"] == "retire_source" and action["source"] == source)
    storage.append_journal(state_dir, persisted, "pending", "apply", action_ids=[write["id"]])
    target = Path(write["target"])
    target.write_bytes(migration.encode_target_json(write["data"]))
    target.chmod(write["after"]["mode"])
    storage.append_journal(state_dir, persisted, "applied", "apply", action_ids=[write["id"]])
    storage.append_journal(state_dir, persisted, "pending", "apply", action_ids=[retirement["id"]])
    Path(source).unlink()
    storage.append_journal(state_dir, persisted, "applied", "apply", action_ids=[retirement["id"]])
    assert len(storage.read_journal(state_dir)) == 4
    return installed, relocated, state_dir, persisted, target


def test_partial_plan_reuses_persisted_identity_and_original_snapshot_footprint(identity_root):
    installed, relocated, state_dir, persisted, target = _persisted_partial_job_plan(identity_root)
    before = tree_bytes(installed)

    def forbidden_allocator():
        raise AssertionError("resume allocated a second identity")

    resumed = migration.build_plan(relocated["config"],
                                   uuid_factory=forbidden_allocator,
                                   journal_plan=storage.load_plan(state_dir),
                                   control_root=installed / "run")
    assert resumed == persisted
    assert target.name == relocated["allocation_order"][0] + ".json"
    assert resumed["status"] == "pending"
    assert tree_bytes(installed) == before


@pytest.mark.parametrize("change", ["different_json_encoding", "permissions"])
def test_resume_rejects_unexplained_target_bytes_or_mode_changes(change, identity_root):
    installed, relocated, state_dir, persisted, target = _persisted_partial_job_plan(identity_root)
    if change == "different_json_encoding":
        value = json.loads(target.read_text(encoding="utf-8"))
        target.write_text(json.dumps(value), encoding="utf-8")
    else:
        target.chmod(0o777)
    before = tree_bytes(installed)
    resumed = migration.build_plan(relocated["config"], journal_plan=storage.load_plan(state_dir),
                                   control_root=installed / "run")
    assert resumed["classification"] == "blocked"
    assert tree_bytes(installed) == before


def test_real_planner_snapshot_requires_cron_capture_and_bound_confirmation(identity_root):
    installed, relocated = installation(BY_ID["legacy_without_prefixes"], identity_root)
    missing_cron = plan_for(relocated, installed)
    with pytest.raises(storage.IdentityStorageError):
        storage.create_snapshot(missing_cron, identity_root / "missing-cron-state")
    before = tree_bytes(installed)
    values = iter(relocated["allocation_order"])
    cron = "# Synthetic unrelated cron entry\n0 4 * * * /fixture/maintenance\n"
    plan = migration.build_plan(relocated["config"], uuid_factory=lambda: UUID(next(values)),
                                control_root=installed / "run", cron_text=cron)
    snapshot = storage.create_snapshot(plan, identity_root / "migration-state")
    storage.verify_snapshot(plan, snapshot)
    with pytest.raises(storage.IdentityStorageError):
        storage.verify_preconditions(plan, snapshot, quiescence_check=lambda: True)
    confirmation = {
        "approved": True, "independent_backup_acknowledged": True,
        "plan_id": plan["plan_id"], "snapshot_digest": snapshot["digest"],
    }
    with pytest.raises(storage.IdentityStorageError):
        storage.verify_preconditions(plan, snapshot, confirmation)
    assert storage.verify_preconditions(
        plan, snapshot, confirmation, quiescence_check=lambda: True,
        external_input_check=lambda: {"managed_cron": {"kind": "crontab", "text": cron}},
    ) is True
    # Successful library precondition verification is still not an apply API.
    assert plan["activation_allowed"] is False
    assert tree_bytes(installed) == before


def test_actual_source_change_invalidates_real_planner_snapshot_and_confirmation(identity_root):
    installed, relocated = installation(BY_ID["legacy_without_prefixes"], identity_root)
    plan = migration.build_plan(relocated["config"], control_root=installed / "run", cron_text="")
    snapshot = storage.create_snapshot(plan, identity_root / "migration-state")
    confirmation = {
        "approved": True, "independent_backup_acknowledged": True,
        "plan_id": plan["plan_id"], "snapshot_digest": snapshot["digest"],
    }
    source = installed / "data/config/jobs/config_local.json"
    source.write_bytes(source.read_bytes() + b"\n")
    before = tree_bytes(installed)
    with pytest.raises(storage.IdentityStorageError):
        storage.verify_preconditions(
            plan, snapshot, confirmation, quiescence_check=lambda: True,
            external_input_check=lambda: {"managed_cron": {"kind": "crontab", "text": ""}},
        )
    assert tree_bytes(installed) == before


@pytest.mark.parametrize("case_id", [
    "fresh", "already_migrated", "legacy_without_prefixes", "future_schema",
])
def test_repeated_detect_is_idempotent_and_never_changes_data_or_config(case_id, identity_root):
    installed, relocated = installation(BY_ID[case_id], identity_root)
    config_before = deepcopy(relocated["config"])
    before = tree_bytes(installed)
    first = migration.detect(relocated["config"], control_root=installed / "run")
    second = migration.detect(relocated["config"], control_root=installed / "run")
    assert first == second
    assert first["classification"] == relocated["expected"]["classification"]
    assert first["required"] is (first["classification"] != "not_applicable")
    assert first["status"] != "applied"
    assert tree_bytes(installed) == before
    assert relocated["config"] == config_before


def test_missing_canonical_alias_list_is_not_blessed_by_proposal_defaults(identity_root):
    installed, relocated = installation(BY_ID["already_migrated"], identity_root)
    path = installed / "data/config/jobs" / (relocated["allocation_order"][0] + ".json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["legacy_job_keys"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = tree_bytes(installed)
    result = migration.verify_target(relocated["config"], control_root=installed / "run")
    assert result["valid"] is False
    assert tree_bytes(installed) == before


def test_target_verifier_rejects_job_change_between_its_inventory_reads(identity_root, monkeypatch):
    installed, relocated = installation(BY_ID["already_migrated"], identity_root)
    path = installed / "data/config/jobs" / (relocated["allocation_order"][0] + ".json")
    original_inventory = migration._inventory
    calls = 0

    def changing_inventory(config, control_root):
        nonlocal calls
        calls += 1
        if calls == 2:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["job_id"] = relocated["allocation_order"][1]
            path.write_text(json.dumps(payload), encoding="utf-8")
        return original_inventory(config, control_root)

    monkeypatch.setattr(migration, "_inventory", changing_inventory)
    result = migration.verify_target(relocated["config"], control_root=installed / "run")
    assert calls == 2, "test must exercise the independent verification read"
    assert result["valid"] is False
    assert result["writable_services_allowed"] is False


def test_legacy_safe_text_prefix_without_old_suffix_does_not_gain_archive_ownership(identity_root):
    installed, relocated = installation(BY_ID["legacy_without_prefixes"], identity_root)
    path = installed / "data/config/jobs/config_local.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    # The legacy reader ignored safe-looking entries without its -backup
    # suffix. Treating this as a newly active prefix could claim other archives.
    payload["archive_prefixes"] = ["config-backup", "other-safe-prefix"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = tree_bytes(installed)
    result = plan_for(relocated, installed)
    assert result["classification"] == "blocked"
    assert not result["jobs"]
    assert tree_bytes(installed) == before


def test_existing_widget_cache_requires_explicit_deferred_rebuild_action(identity_root):
    installed, relocated = installation(BY_ID["legacy_without_prefixes"], identity_root)
    path = installed / "plugin/widget-status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 1, "generated_at": "2026-08-31T08:01:00Z",
        "jobs": {"total": 1, "running": 0, "successful": 1},
    }), encoding="utf-8")
    before = tree_bytes(installed)
    result = plan_for(relocated, installed)
    assert result["classification"] == "applicable"
    actions = [action for action in result["actions"]
               if action["kind"] == "rebuild_derived" and action["source"] == str(path)]
    assert len(actions) == 1, "warning-only omission does not plan cache invalidation"
    assert actions[0]["target"] == str(path)
    assert result["inputs"][str(path)]["exists"] is True
    assert result["activation_allowed"] is False
    assert tree_bytes(installed) == before


@pytest.mark.parametrize("error", [
    OSError("SYNTHETIC_SECRET_NOT_FOR_DIAGNOSTICS"),
    storage.IdentityStorageError("unsafe_path"),
])
def test_target_verifier_masks_second_scan_failures_and_returns_invalid(error, identity_root, monkeypatch):
    installed, relocated = installation(BY_ID["already_migrated"], identity_root)
    before = tree_bytes(installed)
    original_inventory = migration._inventory
    calls = 0

    def failing_inventory(config, control_root):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error
        return original_inventory(config, control_root)

    monkeypatch.setattr(migration, "_inventory", failing_inventory)
    result = migration.verify_target(relocated["config"], control_root=installed / "run")
    assert calls == 2
    assert result["valid"] is False
    assert result["writable_services_allowed"] is False
    assert result["reasons"]
    assert "SYNTHETIC_SECRET_NOT_FOR_DIAGNOSTICS" not in json.dumps(result)
    assert tree_bytes(installed) == before


def test_mixed_legacy_and_canonical_jobs_require_the_original_migration_plan(identity_root):
    installed, relocated = installation(BY_ID["shared_repository_distinct_prefixes"], identity_root)
    job_id = relocated["allocation_order"][1]
    canonical = relocated["expected"]["jobs"][job_id]
    directory = installed / "data/config/jobs"
    (directory / (job_id + ".json")).write_bytes(migration.encode_target_json(canonical))
    (directory / "photos_local.json").unlink()
    # The remaining legacy job and both repository references are otherwise
    # consistent. Their presence does not legitimize a partially converted job.
    before = tree_bytes(installed)
    result = plan_for(relocated, installed)
    assert result["classification"] == "blocked"
    assert "partial_migration_without_journal" in reason_codes(result)
    assert tree_bytes(installed) == before


@pytest.mark.parametrize("change", ["missing", "symlink"])
def test_resume_revalidates_secret_reference_without_copying_its_contents(change, identity_root, monkeypatch):
    installed, relocated = installation(BY_ID["legacy_without_prefixes"], identity_root)
    secret = installed / "data/secrets/repository.passphrase"
    secret.parent.mkdir(parents=True)
    secret.write_text("SYNTHETIC_PRIVATE_SECRET_CONTENT", encoding="utf-8")
    repository_file = installed / "data/config/repositories.json"
    repositories = json.loads(repository_file.read_text(encoding="utf-8"))
    repositories["repositories"][0].update(encryption="repokey", passphrase_ref=str(secret))
    repository_file.write_text(json.dumps(repositories), encoding="utf-8")
    other = identity_root / "another-secret-file"
    actual_read = storage._read_file

    def reject_secret_content_read(path, **kwargs):
        assert Path(path) not in {secret, other}, "planner read secret content"
        return actual_read(path, **kwargs)

    monkeypatch.setattr(storage, "_read_file", reject_secret_content_read)
    original = plan_for(relocated, installed)
    assert original["classification"] == "applicable"
    assert str(secret) not in original["inputs"]
    assert "SYNTHETIC_PRIVATE_SECRET_CONTENT" not in json.dumps(original)
    persisted = storage.persist_plan(original, identity_root / "migration-state")
    secret.unlink()
    if change == "symlink":
        other.write_text("OTHER_SYNTHETIC_PRIVATE_CONTENT", encoding="utf-8")
        secret.symlink_to(other)
    before = tree_bytes(installed)
    result = migration.build_plan(relocated["config"], journal_plan=persisted,
                                  control_root=installed / "run")
    assert result["classification"] == "blocked"
    assert "SYNTHETIC_PRIVATE_SECRET_CONTENT" not in json.dumps(result)
    assert "OTHER_SYNTHETIC_PRIVATE_CONTENT" not in json.dumps(result)
    assert tree_bytes(installed) == before
