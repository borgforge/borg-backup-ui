"""#472 inactive, exact-file snapshot/plan/journal primitives."""

from copy import deepcopy
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import traceback

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from migrations import identity_storage as storage

ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def installation():
    parent = ROOT / ".release-tmp"
    parent.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="identity-storage-472-", dir=parent) as temporary:
        root = Path(temporary)
        jobs = root / "data" / "config" / "jobs"
        jobs.mkdir(parents=True)
        source = jobs / "documents_local.json"
        source.write_bytes(b'{"name":"Synthetic documents","schema_version":3}\n')
        source.chmod(0o640)
        destination = jobs / (ID + ".json")
        conf = jobs.parent / "backup.conf"
        conf.write_bytes(b"SYNTHETIC_SETTING=not-a-credential\n")
        groups = [storage.inventory_group(jobs, [".json"])]
        plan = storage.seal_plan({
            "schema_version": 1, "migration_id": storage.MIGRATION_ID,
            "classification": "applicable", "status": "pending", "required": True,
            "prerequisites": {"managed_cron_captured": True},
            "external_inputs": {"managed_cron": {"kind": "crontab", "text": ""}},
            "id_map": {"documents_local": ID},
            "inputs": {str(path): storage.fingerprint_file(path) for path in (source, destination, conf)},
            "inventory_groups": groups,
            "actions": [{"id": "write_job_1", "kind": "write_json", "source": str(source),
                         "target": str(destination), "data": {"job_id": ID, "schema_version": 4}}],
        })
        yield {"root": root, "source": source, "destination": destination,
               "config": conf, "jobs": jobs, "plan": plan, "state": root / "migration-state"}


def reseal(plan):
    plan.pop("plan_id", None)
    return storage.seal_plan(plan)


def expect_error(code, callback):
    with pytest.raises(storage.IdentityStorageError) as error:
        callback()
    assert error.value.code == code
    assert str(error.value) == code


def confirmation(plan, snapshot):
    return {"approved": True, "independent_backup_acknowledged": True,
            "plan_id": plan["plan_id"], "snapshot_digest": snapshot["digest"]}


def test_secure_fingerprint_and_read_share_exact_bytes(installation):
    source = installation["source"]
    expected = source.read_bytes()
    fingerprint, raw = storage.read_fingerprinted_file(source)
    assert raw == storage.read_file(source) == expected
    assert fingerprint == {"exists": True, "size": len(expected),
                           "mode": 0o640, "sha256": hashlib.sha256(expected).hexdigest()}
    assert storage.fingerprint_file(installation["destination"]) == {"exists": False}
    assert storage.read_fingerprinted_file(installation["root"] / "absent" / "nested") == ({"exists": False}, None)
    expect_error("storage_unavailable", lambda: storage.read_file(installation["destination"]))


@pytest.mark.parametrize("kind", ["file", "ancestor", "fifo", "directory"])
def test_no_symlinks_or_nonregular_source_files(installation, kind):
    root = installation["root"]
    source = root / "unsafe"
    if kind == "file":
        source.symlink_to(installation["source"])
    elif kind == "ancestor":
        source.symlink_to(installation["jobs"], target_is_directory=True)
        source = source / installation["source"].name
    elif kind == "fifo":
        os.mkfifo(source)
    else:
        source.mkdir()
    expect_error("unsafe_path", lambda: storage.fingerprint_file(source))


@pytest.mark.parametrize("path", ["relative", "/a/../b", "/a//b", "//a", "/a/./b", "/a/", "/a\x00b"])
def test_noncanonical_paths_rejected(path):
    expect_error("unsafe_path", lambda: storage.fingerprint_file(path))


def test_seal_hash_binds_every_field_and_allows_multiple_evidenced_aliases(installation):
    plan = deepcopy(installation["plan"])
    original_hash = plan["plan_id"]
    plan["id_map"]["config_local"] = ID
    expect_error("invalid_plan", lambda: storage.seal_plan(plan))
    plan = reseal(plan)
    assert plan["plan_id"] != original_hash
    assert len(set(plan["id_map"].values())) == 1
    plan["actions"][0]["data"]["unexpected"] = "must be included in digest"
    expect_error("invalid_plan", lambda: storage.seal_plan(plan))


def test_unknown_destination_cannot_be_excluded_from_snapshot(installation):
    plan = deepcopy(installation["plan"])
    del plan["inputs"][str(installation["destination"])]
    expect_error("invalid_plan", lambda: reseal(plan))


@pytest.mark.parametrize("mutate", [
    lambda plan: plan["id_map"].update({"documents_local": "not-a-uuid"}),
    lambda plan: plan.update(schema_version=True),
    lambda plan: plan["inputs"].update({"relative": {"exists": False}}),
    lambda plan: plan["actions"].append(deepcopy(plan["actions"][0])),
    lambda plan: plan["inputs"].update({"/missing": {"exists": False, "sha256": "ignored"}}),
])
def test_bad_plan_structures_fail_closed(installation, mutate):
    plan = deepcopy(installation["plan"])
    mutate(plan)
    with pytest.raises(storage.IdentityStorageError):
        reseal(plan)


def test_persist_once_loads_identical_ids_and_never_replaces_a_different_plan(installation):
    plan, state = installation["plan"], installation["state"]
    assert storage.persist_plan(plan, state) == plan
    assert storage.load_plan(state) == plan
    assert storage.persist_plan(deepcopy(plan), state) == plan
    changed = deepcopy(plan)
    changed["id_map"]["documents_local"] = "22222222-2222-4222-8222-222222222222"
    expect_error("state_conflict", lambda: storage.persist_plan(reseal(changed), state))
    assert storage.load_plan(state) == plan
    assert state.stat().st_mode & 0o777 == 0o700
    assert (state / "plan.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("position", ["source_parent", "ancestor", "symlink", "world_readable"])
def test_state_must_be_private_and_disjoint_from_sources(installation, position):
    plan = installation["plan"]
    state = installation["state"]
    if position == "source_parent":
        state = installation["jobs"] / "migration"
    elif position == "ancestor":
        state = installation["root"] / "data"
    elif position == "symlink":
        other = installation["root"] / "other-state"
        other.mkdir(mode=0o700)
        state.symlink_to(other)
    else:
        state.mkdir(mode=0o755)
    expect_error("unsafe_path", lambda: storage.persist_plan(plan, state))
    assert not (installation["jobs"] / "plan.json").exists()


def test_snapshot_exact_originals_absence_permissions_and_idempotence(installation):
    plan, state = installation["plan"], installation["state"]
    before = {path: Path(path).read_bytes() for path, value in plan["inputs"].items() if value["exists"]}
    snapshot = storage.create_snapshot(plan, state)
    manifest = storage.verify_snapshot(plan, snapshot)
    assert set(manifest["entries"]) == set(plan["inputs"])
    absent = manifest["entries"][str(installation["destination"])]
    assert absent == {"artifact_kind": "file", "original": {"exists": False}, "blob": None}
    for path, raw in before.items():
        blob = state / "snapshot" / "files" / manifest["entries"][path]["blob"]
        assert blob.read_bytes() == raw
        assert blob.stat().st_mode & 0o777 == 0o600
        assert Path(path).read_bytes() == raw
    assert storage.create_snapshot(plan, state) == snapshot
    assert not installation["destination"].exists()


@pytest.mark.parametrize("mutation", ["content", "permission", "removed", "destination_created", "new_member"])
def test_source_changes_invalidate_snapshot_reuse(installation, mutation):
    plan, state = installation["plan"], installation["state"]
    snapshot = storage.create_snapshot(plan, state)
    source = installation["source"]
    if mutation == "content":
        source.write_bytes(b"changed")
    elif mutation == "permission":
        source.chmod(0o600)
    elif mutation == "removed":
        source.unlink()
    elif mutation == "destination_created":
        installation["destination"].write_text("{}")
    else:
        (installation["jobs"] / "new_job.json").write_text("{}")
    code = "inventory_changed" if mutation == "new_member" else "input_changed"
    expect_error(code, lambda: storage.create_snapshot(plan, state))
    # An intact old snapshot stays readable even when source data changes.
    storage.verify_snapshot(plan, snapshot)


def test_missing_inventory_directory_becoming_present_invalidates_plan(installation):
    path = installation["root"] / "new-status"
    group = storage.inventory_group(path, [".status"])
    assert group == {"path": str(path), "suffixes": [".status"], "exists": False, "entries": []}
    plan = deepcopy(installation["plan"])
    plan["inventory_groups"].append(group)
    plan = reseal(plan)
    path.mkdir()
    expect_error("inventory_changed", lambda: storage.verify_inputs(plan))


def test_control_directory_membership_is_bounded_and_revalidated(installation):
    control = installation["root"] / "control"
    assert storage.inventory_directories(control)["exists"] is False
    control.mkdir()
    (control / "run1").mkdir()
    plan = deepcopy(installation["plan"])
    plan["inventory_groups"].append(storage.inventory_directories(control))
    plan = reseal(plan)
    assert storage.verify_inputs(plan)
    (control / "run2").mkdir()
    expect_error("inventory_changed", lambda: storage.verify_inputs(plan))
    (control / "unknown.lock").write_text("anything")
    expect_error("unsafe_path", lambda: storage.inventory_directories(control))


def test_same_entries_in_replaced_inventory_root_do_not_match(installation):
    jobs = installation["jobs"]
    old = jobs.with_name("old-jobs")
    jobs.rename(old)
    jobs.mkdir()
    source = installation["source"]
    source.write_bytes((old / source.name).read_bytes())
    source.chmod(0o640)
    expect_error("inventory_changed", lambda: storage.verify_inputs(installation["plan"]))


@pytest.mark.parametrize("mutation", ["blob", "missing_blob", "extra_blob", "manifest", "private_mode", "symlink_blob"])
def test_tampered_or_incomplete_snapshot_is_not_retrusted(installation, mutation):
    plan, state = installation["plan"], installation["state"]
    snapshot = storage.create_snapshot(plan, state)
    manifest = storage.verify_snapshot(plan, snapshot)
    blob = state / "snapshot" / "files" / manifest["entries"][str(installation["source"])]["blob"]
    if mutation == "blob":
        blob.write_bytes(b"forged")
    elif mutation == "missing_blob":
        blob.unlink()
    elif mutation == "extra_blob":
        blob.with_name("unplanned.bin").write_bytes(b"unplanned")
    elif mutation == "private_mode":
        blob.chmod(0o644)
    elif mutation == "symlink_blob":
        blob.unlink()
        blob.symlink_to(installation["source"])
    else:
        del manifest["entries"][str(installation["config"])]
        (state / "snapshot" / "manifest.json").write_text(json.dumps(manifest))
        snapshot["digest"] = storage._digest(manifest)
    with pytest.raises(storage.IdentityStorageError):
        storage.verify_snapshot(plan, snapshot)


def test_existing_corrupt_blob_is_not_overwritten_by_retry(installation):
    plan, state = installation["plan"], installation["state"]
    snapshot = storage.create_snapshot(plan, state)
    manifest = storage.verify_snapshot(plan, snapshot)
    blob = state / "snapshot" / "files" / manifest["entries"][str(installation["source"])]["blob"]
    blob.write_bytes(b"corruption must remain visible")
    expect_error("state_conflict", lambda: storage.create_snapshot(plan, state))
    assert blob.read_bytes() == b"corruption must remain visible"


def test_snapshot_manifest_does_not_accept_boolean_integer_substitution(installation):
    plan, state = installation["plan"], installation["state"]
    snapshot = storage.create_snapshot(plan, state)
    manifest = storage.verify_snapshot(plan, snapshot)
    manifest["schema_version"] = True
    (state / "snapshot" / "manifest.json").write_text(json.dumps(manifest))
    snapshot["digest"] = storage._digest(manifest)
    expect_error("invalid_snapshot", lambda: storage.verify_snapshot(plan, snapshot))


def test_private_state_cannot_alias_other_files_through_a_hard_link(installation):
    plan, state = installation["plan"], installation["state"]
    storage.persist_plan(plan, state)
    os.link(state / "plan.json", installation["root"] / "other-link")
    expect_error("unsafe_path", lambda: storage.load_plan(state))


def test_duplicate_json_fields_in_persisted_plan_are_not_ignored(installation):
    plan, state = installation["plan"], installation["state"]
    storage.persist_plan(plan, state)
    path = state / "plan.json"
    path.write_bytes(b'{"schema_version":999,' + path.read_bytes()[1:])
    expect_error("state_conflict", lambda: storage.load_plan(state))


def test_interrupted_snapshot_can_resume_original_uuid_allocation(installation, monkeypatch):
    plan, state = installation["plan"], installation["state"]
    publish = storage._publish_once
    calls = []
    def interrupt(path, content):
        if path.suffix == ".bin":
            calls.append(path)
            if len(calls) == 2:
                raise storage.IdentityStorageError("interrupted")
        return publish(path, content)
    monkeypatch.setattr(storage, "_publish_once", interrupt)
    expect_error("interrupted", lambda: storage.create_snapshot(plan, state))
    assert storage.load_plan(state)["id_map"] == plan["id_map"]
    assert not (state / "snapshot" / "manifest.json").exists()
    metadata_before = (state / "snapshot" / "metadata.json").read_bytes()
    monkeypatch.setattr(storage, "_publish_once", publish)
    snapshot = storage.create_snapshot(storage.load_plan(state), state)
    storage.verify_snapshot(plan, snapshot)
    assert (state / "snapshot" / "metadata.json").read_bytes() == metadata_before
    assert not installation["destination"].exists()


def test_snapshot_manifest_records_stable_timestamp_allocation_actions_and_artifact_types(installation):
    plan, state = installation["plan"], installation["state"]
    snapshot = storage.create_snapshot(plan, state)
    manifest = storage.verify_snapshot(plan, snapshot)
    metadata = json.loads((state / "snapshot" / "metadata.json").read_text())
    timestamp = datetime.fromisoformat(manifest["created_at"])
    assert timestamp.tzinfo == timezone.utc
    assert manifest["created_at"] == metadata["created_at"]
    assert manifest["id_map"] == plan["id_map"]
    assert manifest["actions"] == [{key: value for key, value in action.items() if key != "data"}
                                    for action in plan["actions"]]
    assert all(entry["artifact_kind"] == "file" for entry in manifest["entries"].values())
    assert all(entry["artifact_kind"] == "external" for entry in manifest["external_inputs"].values())
    assert "data" not in manifest["actions"][0]
    assert storage.create_snapshot(plan, state) == snapshot
    assert storage.verify_snapshot(plan, snapshot)["created_at"] == manifest["created_at"]
    assert storage.load_plan(state) == plan


@pytest.mark.parametrize("timestamp", [None, True, "", "invalid", "2026-09-05T12:00:00", "2026-09-05T12:00:00+02:00"])
def test_corrupt_snapshot_creation_timestamp_blocks_verification_and_retry(installation, timestamp):
    plan, state = installation["plan"], installation["state"]
    snapshot = storage.create_snapshot(plan, state)
    path = state / "snapshot" / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata["created_at"] = timestamp
    path.write_text(json.dumps(metadata))
    expect_error("invalid_snapshot", lambda: storage.verify_snapshot(plan, snapshot))
    expect_error("invalid_snapshot", lambda: storage.create_snapshot(plan, state))


def test_missing_snapshot_creation_evidence_is_not_regenerated(installation):
    plan, state = installation["plan"], installation["state"]
    snapshot = storage.create_snapshot(plan, state)
    path = state / "snapshot" / "metadata.json"
    path.unlink()
    expect_error("snapshot_incomplete", lambda: storage.verify_snapshot(plan, snapshot))
    expect_error("snapshot_incomplete", lambda: storage.create_snapshot(plan, state))
    assert not path.exists()


@pytest.mark.parametrize("field", ["created_at", "actions", "id_map", "artifact_kind"])
def test_snapshot_manifest_metadata_is_bound_to_private_metadata_and_plan(installation, field):
    plan, state = installation["plan"], installation["state"]
    snapshot = storage.create_snapshot(plan, state)
    manifest = storage.verify_snapshot(plan, snapshot)
    if field == "created_at":
        manifest[field] = "2000-01-01T00:00:00+00:00"
    elif field == "actions":
        manifest[field] = []
    elif field == "id_map":
        manifest[field] = {}
    else:
        manifest["entries"][str(installation["source"])][field] = "unknown"
    (state / "snapshot" / "manifest.json").write_text(json.dumps(manifest))
    snapshot["digest"] = storage._digest(manifest)
    expect_error("invalid_snapshot", lambda: storage.verify_snapshot(plan, snapshot))


def test_unsupported_state_filesystem_does_not_fall_back_to_insecure_copy(installation, monkeypatch):
    def unsupported(*args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, "do-not-log-this-sensitive-path")
    monkeypatch.setattr(storage.os, "link", unsupported)
    expect_error("state_filesystem_unsupported", lambda: storage.persist_plan(installation["plan"], installation["state"]))
    assert not (installation["state"] / "plan.json").exists()


def test_masked_io_error_suppresses_sensitive_exception_chain(installation, monkeypatch):
    def denied(*args, **kwargs):
        raise OSError(errno.EACCES, "sensitive-context-must-not-escape")
    monkeypatch.setattr(storage.os, "open", denied)
    with pytest.raises(storage.IdentityStorageError) as error:
        storage.fingerprint_file(installation["source"])
    rendered = "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert "sensitive-context-must-not-escape" not in rendered
    assert error.value.code == "storage_unavailable"


def test_disk_full_is_sanitized_and_never_changes_user_data(installation, monkeypatch):
    class Full:
        f_bavail = 0
        f_frsize = 4096
    monkeypatch.setattr(storage.os, "fstatvfs", lambda fd: Full())
    before = installation["source"].read_bytes()
    expect_error("insufficient_space", lambda: storage.create_snapshot(installation["plan"], installation["state"]))
    assert installation["source"].read_bytes() == before
    assert not installation["destination"].exists()


@pytest.mark.parametrize("bad", [None, {}, {"approved": False}, {"approved": 1}])
def test_preconditions_deny_without_explicit_bound_acknowledgement(installation, bad):
    plan = installation["plan"]
    snapshot = storage.create_snapshot(plan, installation["state"])
    expect_error("approval_required", lambda: storage.verify_preconditions(plan, snapshot, bad))


@pytest.mark.parametrize("field", ["independent_backup_acknowledged", "plan_id", "snapshot_digest"])
def test_confirmation_cannot_be_reused_for_other_plan_snapshot(installation, field):
    plan = installation["plan"]
    snapshot = storage.create_snapshot(plan, installation["state"])
    approved = confirmation(plan, snapshot)
    approved[field] = False if field.endswith("acknowledged") else "wrong"
    expect_error("approval_required", lambda: storage.verify_preconditions(plan, snapshot, approved, quiescence_check=lambda: True))


@pytest.mark.parametrize("check", [None, lambda: False, lambda: 1])
def test_confirmation_does_not_replace_independent_quiescence_check(installation, check):
    plan = installation["plan"]
    snapshot = storage.create_snapshot(plan, installation["state"])
    expect_error("writers_active", lambda: storage.verify_preconditions(plan, snapshot, confirmation(plan, snapshot), quiescence_check=check))


def test_confirmed_snapshot_gate_is_read_only_and_rechecks_changed_inputs(installation):
    plan = installation["plan"]
    snapshot = storage.create_snapshot(plan, installation["state"])
    approved = confirmation(plan, snapshot)
    assert storage.verify_preconditions(plan, snapshot, approved, quiescence_check=lambda: True,
                                        external_input_check=lambda: deepcopy(plan["external_inputs"]))
    assert not installation["destination"].exists()
    installation["source"].write_text("changed after confirmation")
    expect_error("input_changed", lambda: storage.verify_preconditions(plan, snapshot, approved, quiescence_check=lambda: True))


def test_cron_is_explicitly_captured_private_and_revalidated(installation):
    plan = deepcopy(installation["plan"])
    plan["prerequisites"] = {"managed_cron_captured": True}
    plan["external_inputs"] = {"managed_cron": {"kind": "crontab", "text": "# unrelated synthetic cron\n* * * * * synthetic\n"}}
    plan = reseal(plan)
    snapshot = storage.create_snapshot(plan, installation["state"])
    manifest = storage.verify_snapshot(plan, snapshot)
    entry = manifest["external_inputs"]["managed_cron"]
    blob = Path(snapshot["path"]) / "files" / entry["blob"]
    assert blob.read_text() == plan["external_inputs"]["managed_cron"]["text"]
    approved = confirmation(plan, snapshot)
    expect_error("input_changed", lambda: storage.verify_preconditions(plan, snapshot, approved, quiescence_check=lambda: True))
    assert storage.verify_preconditions(plan, snapshot, approved, quiescence_check=lambda: True,
                                        external_input_check=lambda: deepcopy(plan["external_inputs"]))
    expect_error("input_changed", lambda: storage.verify_preconditions(plan, snapshot, approved, quiescence_check=lambda: True, external_input_check=lambda: {}))


@pytest.mark.parametrize("captured", [False, True])
def test_incomplete_cron_prerequisite_blocks_snapshot_before_state_writes(installation, captured):
    plan = deepcopy(installation["plan"])
    plan["prerequisites"] = {"managed_cron_captured": captured}
    plan.pop("external_inputs")
    plan = reseal(plan)
    expect_error("snapshot_incomplete", lambda: storage.create_snapshot(plan, installation["state"]))
    assert not installation["state"].exists()


@pytest.mark.parametrize("field", ["classification", "required", "status", "prerequisites"])
def test_gate_does_not_infer_missing_eligibility_fields(installation, field):
    plan = deepcopy(installation["plan"])
    plan.pop(field)
    plan = reseal(plan)
    snapshot = storage.create_snapshot(plan, installation["state"])
    expected = "snapshot_incomplete" if field == "prerequisites" else "invalid_plan"
    expect_error(expected, lambda: storage.verify_preconditions(
        plan, snapshot, confirmation(plan, snapshot), quiescence_check=lambda: True,
        external_input_check=lambda: deepcopy(plan["external_inputs"])))


def test_journal_is_durable_hash_linked_private_and_only_accepts_safe_fields(installation):
    plan, state = installation["plan"], installation["state"]
    storage.persist_plan(plan, state)
    first = storage.append_journal(state, plan, "pending", "plan")
    second = storage.append_journal(state, plan, "blocked", "verify", reason_code="input_changed", action_ids=["write_job_1"])
    assert first["sequence"] == 1
    assert second["previous"] == first["digest"]
    assert storage.read_journal(state) == [first, second]
    path = state / "journal.jsonl"
    assert path.stat().st_mode & 0o777 == 0o600
    text = path.read_text()
    assert "Synthetic documents" not in text
    assert str(installation["source"]) not in text
    expect_error("invalid_journal", lambda: storage.append_journal(state, plan, "failed", "verify", reason_code="sensitive raw exception"))
    assert storage.read_journal(state) == [first, second]


@pytest.mark.parametrize("mutation", ["partial", "changed", "wrong_plan", "unknown_field", "bad_type"])
def test_torn_or_forged_journal_is_not_silently_repaired(installation, mutation):
    plan, state = installation["plan"], installation["state"]
    storage.persist_plan(plan, state)
    event = storage.append_journal(state, plan, "pending", "plan")
    path = state / "journal.jsonl"
    if mutation == "partial":
        path.write_bytes(path.read_bytes()[:-1])
    else:
        if mutation == "changed":
            event["status"] = "applied"
        elif mutation == "wrong_plan":
            event["plan_id"] = "different"
        elif mutation == "bad_type":
            event["status"] = []
        else:
            event["secret"] = "not-allowed"
        path.write_text(json.dumps(event) + "\n")
    before = path.read_bytes()
    expect_error("invalid_journal", lambda: storage.append_journal(state, plan, "pending", "resume"))
    assert path.read_bytes() == before
