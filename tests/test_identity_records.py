"""Pure store-projection regressions for inactive migration phase #472."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from migrations.identity_records import project_records, verify_records


JOB = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
JOBS = {JOB: {"schema_version": 4, "job_id": JOB, "repository_key": "repo",
              "legacy_job_keys": ["config_local"], "name": "Current name"}}
ALIASES = {"config_local": JOB}


def rec(kind, data, **metadata):
    return {"kind": kind, "data": data, **metadata}


def project(kind, data, **metadata):
    return project_records({"/fixture/input": rec(kind, data, **metadata)}, JOBS, ALIASES)


def codes(result):
    return {reason["code"] for reason in result["reasons"] if reason["severity"] != "warning"}


def output(result):
    return next(iter(result["records"].values()))["data"]


def test_schedules_preserve_disabled_and_system_entries_and_are_pure():
    data = {"config_local": {"cron": "0 8 * * *", "enabled": False, "future": {"x": 1}},
            "restore_test": {"cron": "0 9 * * 0", "enabled": True}}
    before = deepcopy(data)
    result = project("schedules", data)
    assert not codes(result)
    assert result["required"]
    assert output(result) == {JOB: data["config_local"], "restore_test": data["restore_test"]}
    assert data == before
    assert verify_records(result["records"], JOBS, ALIASES) == []


def test_unknown_disabled_schedule_is_not_discarded_or_inferred_from_name():
    result = project("schedules", {"old_config_local": {"cron": "0 8 * * *", "enabled": False}})
    assert codes(result) == {"orphan_active_schedule"}


def test_verifier_rejects_active_alias_even_when_projector_could_resolve_it():
    records = {"/fixture/schedules": rec("schedules", {"config_local": {"cron": "0 8 * * *"}})}
    assert {r["code"] for r in verify_records(records, JOBS, ALIASES)} == {"mutable_active_reference"}


def test_duplicate_schedule_aliases_cannot_overwrite_one_another():
    result = project("schedules", {"config_local": {"cron": "0 8 * * *"}, JOB: {"cron": "0 9 * * *"}})
    assert "duplicate_schedule_identity" in codes(result)


def test_repository_links_convert_both_fields_but_preserve_repository_identity():
    row = {"repository_key": "repo", "used_by": ["config_local"], "source_job_keys": ["config_local"],
           "storage_key": "storage", "passphrase_ref": "secrets/unchanged.ref", "metadata": {"x": 1}}
    result = project("repositories", {"schema_version": 1, "repositories": [row]})
    target = output(result)["repositories"][0]
    assert not codes(result)
    assert target["job_ids"] == target["source_job_ids"] == [JOB]
    assert "used_by" not in target and "source_job_keys" not in target
    assert target["passphrase_ref"] == row["passphrase_ref"]
    assert target["metadata"] == row["metadata"]
    assert len(result["bindings"]) == 2
    assert verify_records(result["records"], JOBS, ALIASES) == []


@pytest.mark.parametrize("changes", [
    {"used_by": []}, {"used_by": ["unknown_local"]}, {"used_by": ["config_local", "config_local"]},
    {"job_ids": [JOB]}, {"source_job_keys": "config_local"},
])
def test_repository_reverse_conflicts_block(changes):
    row = {"repository_key": "repo", "used_by": ["config_local"], "source_job_keys": ["config_local"], **changes}
    assert codes(project("repositories", {"schema_version": 1, "repositories": [row]}))


def test_status_enrichment_preserves_original_history_and_never_invents_snapshots():
    data = {"backup_type": "config", "location": "local", "timestamp": "2026-08-31 08:00:00",
            "archive_name": "config-backup-example", "log_file": "/fixture/logs/old.log",
            "borg_exit_code": 0}
    result = project("status", data)
    target = output(result)
    assert not codes(result)
    assert target == {**data, "schema_version": 1, "job_id": JOB}
    for unknown in ("run_id", "job_name", "repository_key"):
        assert unknown not in target
    assert verify_records(result["records"], JOBS, ALIASES) == []


def test_already_canonical_status_is_not_changed():
    data = {"schema_version": 1, "job_id": JOB, "backup_type": "config", "location": "local"}
    result = project("status", data)
    assert output(result) == data
    assert not result["required"]


def test_status_filename_disagreement_is_unassigned_not_wrong_job():
    path = "/fixture/status/2026-08-31_08-00-00_photos_local.status"
    result = project_records({path: rec("status", {"backup_type": "config", "location": "local"})}, JOBS, ALIASES)
    assert not codes(result)
    assert result["bindings"][0]["job_id"] is None
    assert result["unassigned"][0]["reason"] == "conflicting_identity_evidence"
    assert "job_id" not in output(result)


def test_underscore_legacy_identity_uses_full_exact_key():
    data = {"backup_type": "server_config_old", "location": "local"}
    result = project_records({"/fixture/status/2026-08-31_08-00-00_server_config_old_local.status": rec("status", data)},
                             JOBS, {"server_config_old_local": JOB})
    assert output(result)["job_id"] == JOB


def test_orphan_and_explicitly_unassigned_history_never_creates_a_job():
    data = {"backup_type": "deleted", "location": "local", "log_file": "/fixture/logs/deleted.log"}
    result = project("status", data)
    assert not codes(result)
    assert not result["required"]
    assert output(result)["identity_state"] == "unassigned"
    assert result["unassigned"][0]["data"] == data
    rerun = project_records(result["records"], JOBS, {**ALIASES, "deleted_local": JOB})
    assert output(rerun) == output(result)
    assert rerun["bindings"][0]["job_id"] is None


def test_restore_test_filename_move_keeps_tested_scope():
    data = {"test_date": "2026-08-31 08:10:00", "test_result": "PASS", "tested_archive": "old-prefix-archive",
            "repository": "/fixture/previous-repository", "tested_entries": ["old-name"]}
    result = project("restore_test", data, legacy_key="config_local", target_path=f"/fixture/tests/{JOB}.test")
    assert not codes(result)
    assert list(result["records"]) == [f"/fixture/tests/{JOB}.test"]
    assert all(output(result)[key] == value for key, value in data.items())


def test_restore_history_and_active_runs_keep_independent_restore_ids():
    row = {"restore_id": "restore-example", "state": "done", "job_key": "config_local", "archive": "old-archive"}
    records = {"/fixture/index": rec("restore_index", {"schema_version": 1, "runs": [row]}),
               "/fixture/restore-example.json": rec("restore_detail", {"schema_version": 1, **row}),
               "/fixture/runs": rec("restore_runs", {"schema_version": 1, "runs": {}})}
    result = project_records(records, JOBS, ALIASES)
    assert not codes(result)
    assert result["records"]["/fixture/restore-example.json"]["data"]["job_key"] == "config_local"
    assert result["records"]["/fixture/restore-example.json"]["data"]["restore_id"] == "restore-example"
    assert {r["job_id"] for r in result["bindings"]} == {JOB}
    assert verify_records(result["records"], JOBS, ALIASES) == []
    active = project("restore_runs", {"schema_version": 1, "runs": {
        "restore-example": {**row, "state": "running"}}})
    assert output(active)["runs"]["restore-example"]["legacy_job_key"] == "config_local"
    assert "job_key" not in output(active)["runs"]["restore-example"]


def test_restore_cross_store_mismatch_blocks():
    jobs = {**JOBS, OTHER: {"job_id": OTHER, "repository_key": "other"}}
    records = {"/fixture/index": rec("restore_index", {"schema_version": 1, "runs": [
        {"restore_id": "restore-example", "state": "done", "job_id": JOB}]}),
        "/fixture/restore-example.json": rec("restore_detail", {"restore_id": "restore-example", "state": "done", "job_id": OTHER})}
    assert "restore_identity_mismatch" in codes(project_records(records, jobs, ALIASES))


def test_notification_queue_preserves_retry_state_and_does_not_dispatch():
    row = {"id": "event-1", "job_key": "config_local", "attempts_made": 2, "next_attempt_at": 1788163380,
           "body": "Original message", "source": "backup_job", "event_type": "backup_success"}
    result = project("notification_queue", {"schema_version": 1, "queue": [row]})
    target = output(result)["queue"][0]
    assert not codes(result)
    assert target["job_id"] == JOB and target["legacy_job_key"] == "config_local"
    assert "job_key" not in target
    for key in ("id", "attempts_made", "next_attempt_at", "body"):
        assert target[key] == row[key]
    assert verify_records(result["records"], JOBS, ALIASES) == []


def test_orphan_queue_blocks_but_delivery_is_retained_unassigned():
    row = {"id": "event-1", "job_key": "deleted_local", "source": "backup_job"}
    assert codes(project("notification_queue", {"schema_version": 1, "queue": [row]})) == {"orphan_active_notification"}
    result = project("notification_deliveries", {"schema_version": 1, "deliveries": [row]})
    assert not codes(result)
    assert output(result)["deliveries"][0]["job_key"] == row["job_key"]
    assert result["unassigned"][0]["reason"] == "no_configured_job"


def test_explicit_system_event_does_not_receive_fabricated_id():
    row = {"id": "event-1", "job_key": "restore_test", "source": "restore_test"}
    result = project("notification_queue", {"schema_version": 1, "queue": [row]})
    assert not codes(result)
    assert output(result)["queue"] == [row]
    assert result["bindings"][0]["role"] == "system"
    bad = {**row, "source": "backup_job"}
    assert codes(project("notification_queue", {"schema_version": 1, "queue": [bad]}))


def test_reminder_due_marker_with_colons_and_timestamp_survive():
    key = "backup_overdue:config_local:2026-08-31T08:00:00"
    result = project("notification_state", {"schema_version": 1, "last_sent": {key: 1788163200}})
    assert not codes(result)
    assert output(result)["last_sent"] == {f"backup_overdue:{JOB}:2026-08-31T08:00:00": 1788163200}
    assert result["bindings"][0]["locator"] == "/last_sent/" + key
    assert verify_records(result["records"], JOBS, ALIASES) == []


def test_unknown_reminders_retained_with_provenance_not_deleted():
    key = "backup_overdue:deleted_local:current"
    result = project("notification_state", {"schema_version": 1, "last_sent": {key: 10}})
    assert output(result)["last_sent"] == {}
    assert output(result)["unassigned"] == [{"key": key, "value": 10, "source": "/fixture/input", "locator": "/last_sent/" + key}]


def test_pending_recovery_keeps_targets_and_never_marks_restarted():
    row = {"id": "recovery-1", "state": "pending_restart", "backup_type": "config", "backup_location": "local",
           "pid": 999999, "targets": [{"id": "container-id", "name": "original-container"}],
           "stopped_at": "2026-08-31T08:00:00Z", "restarted_at": ""}
    result = project("runtime_recovery", {"schema_version": 1, "entries": [row]})
    assert not codes(result)
    target = output(result)["entries"][0]
    assert target == {**row, "schema_version": 1, "job_id": JOB}


@pytest.mark.parametrize("kind", ["control", "cancel_request", "resource_lock"])
def test_runtime_owner_reference_uses_id_without_changing_run(kind):
    row = {"job_key": "config_local", "run_id": "original-run", "pid": 999999, "resource": "repository:repo"}
    result = project(kind, row)
    assert not codes(result)
    assert output(result)["job_id"] == JOB
    assert output(result)["run_id"] == "original-run"
    assert output(result)["pid"] == 999999


@pytest.mark.parametrize("second_size, count, conflict", [(100, 1, False), (101, 2, True)])
def test_both_weekly_stores_deduplicate_equal_values_and_preserve_conflicts(second_size, count, conflict):
    sources = {"/fixture/current-weekly": rec("weekly", {"config_local": [{"week": "2026-08-31", "size": 100}]},
                                            target_path="/fixture/current-weekly"),
               "/fixture/legacy-weekly": rec("weekly", {"config_local": [{"week": "2026-08-31", "size": second_size}]},
                                           target_path="/fixture/current-weekly")}
    result = project_records(sources, JOBS, ALIASES)
    assert not codes(result)
    rows = output(result)["observations"]
    assert len(rows) == count
    assert {row["size"] for row in rows} == {100, second_size}
    assert sum(len(row["source_records"]) for row in rows) == 2
    assert all(bool(row.get("conflict")) == conflict for row in rows)
    assert next(iter(result["records"].values()))["sources"] == sorted(sources)
    again = project_records(result["records"], JOBS, ALIASES)
    assert output(again) == output(result)


@pytest.mark.parametrize("kind,data", [
    ("status", []), ("status", {}), ("status", {"schema_version": 99}),
    ("notification_queue", {"schema_version": 1, "queue": {}}),
    ("notification_queue", {"schema_version": 1, "queue": [None]}),
    ("notification_state", {"schema_version": 1, "last_sent": {"invalid": 1}}),
    ("runtime_recovery", {"schema_version": 1, "entries": [{"state": "recovered"}]}),
    ("unknown_kind", {}), ("widget_cache", {"schema_version": 99}),
])
def test_unknown_owned_shapes_fail_closed(kind, data):
    assert codes(project(kind, data))


def test_widget_is_explicit_rebuild_gate_not_silently_projected():
    result = project("widget_cache", {"schema_version": 1, "jobs": [{"job_key": "config_local"}]})
    assert not codes(result)
    assert not result["records"]
    assert result["reasons"] == [{"code": "widget_rebuild_required", "source": "/fixture/input", "locator": "", "severity": "warning"}]


def test_verifier_detects_lost_weekly_conflict_marker():
    records = {"/fixture/weekly": rec("weekly", {"schema_version": 1, "identity_schema_version": 1,
        "observations": [{"job_id": JOB, "legacy_job_key": "config_local", "week": "2026-08-31", "size": size,
                          "source_records": [{"source": f"/fixture/source-{size}", "locator": "/config_local/0"}]}
                         for size in (100, 101)]})}
    assert "weekly_projection_mismatch" in {reason["code"] for reason in verify_records(records, JOBS, ALIASES)}


def test_verifier_detects_unassigned_restore_index_with_assigned_detail():
    common = {"restore_id": "restore-example", "state": "done", "job_key": "config_local"}
    records = {"/fixture/index": rec("restore_index", {"schema_version": 1, "runs": [
        {**common, "identity_state": "unassigned"}]}),
        "/fixture/restore-example.json": rec("restore_detail", {**common, "job_id": JOB})}
    assert "restore_identity_mismatch" in {reason["code"] for reason in verify_records(records, JOBS, ALIASES)}


def test_conflicting_active_explicit_id_and_legacy_key_blocks():
    jobs = {**JOBS, OTHER: {"job_id": OTHER, "repository_key": "other"}}
    result = project_records({"/fixture/control": rec("control", {"job_key": "config_local", "job_id": OTHER})},
                             jobs, ALIASES)
    assert "conflicting_active_identity" in codes(result)


def test_former_prefix_only_yields_diagnostic_not_an_alias():
    jobs = {JOB: {**JOBS[JOB], "archive_prefixes": ["pfsense-backup", "config-backup"], "legacy_job_keys": ["pfsense_local"]}}
    result = project_records({"/fixture/status": rec("status", {"backup_type": "config", "location": "local"})},
                             jobs, {"pfsense_local": JOB})
    assert result["bindings"][0]["job_id"] is None
    assert result["unassigned"][0]["reason"] == "no_authoritative_alias"


@pytest.mark.parametrize("targets", [[None], [{"name": "only-name"}], [{"id": "a", "name": "A"}, {"id": "a", "name": "B"}]])
def test_invalid_pending_recovery_targets_block(targets):
    data = {"schema_version": 1, "entries": [{"state": "pending_restart", "backup_type": "config",
        "backup_location": "local", "targets": targets}]}
    assert "invalid_recovery_targets" in codes(project("runtime_recovery", data))


def restore_pair():
    row = {"restore_id": "restore-example", "state": "done", "job_key": "config_local", "archive": "old-archive",
           "source_path": "source.txt", "target_dir": "/fixture/output"}
    return {"/fixture/index.json": rec("restore_index", {"schema_version": 1, "runs": [deepcopy(row)]}),
            "/fixture/runs/restore-example.json": rec("restore_detail", {"schema_version": 1, **deepcopy(row)})}


@pytest.mark.parametrize("missing,code", [
    ("/fixture/index.json", "missing_restore_index_entry"),
    ("/fixture/runs/restore-example.json", "missing_restore_detail"),
])
def test_restore_history_requires_both_owned_records(missing, code):
    records = restore_pair()
    del records[missing]
    assert code in codes(project_records(records, JOBS, ALIASES))


@pytest.mark.parametrize("kind", ["index", "detail"])
def test_duplicate_restore_history_ids_block(kind):
    records = restore_pair()
    if kind == "index":
        rows = records["/fixture/index.json"]["data"]["runs"]
        rows.append(deepcopy(rows[0]))
    else:
        records["/fixture/other/restore-example.json"] = deepcopy(records["/fixture/runs/restore-example.json"])
    assert "duplicate_restore_id" in codes(project_records(records, JOBS, ALIASES))


@pytest.mark.parametrize("field,value", [
    ("state", "error"), ("archive", "different-archive"), ("source_path", "different.txt"),
    ("target_dir", "/fixture/other-output"), ("repository_key", "other-repository"),
    ("location_snapshot", "usb"), ("archive_prefixes_snapshot", ["other-prefix"]),
    ("run_id", "33333333-3333-4333-8333-333333333333"),
])
def test_restore_summary_detail_snapshot_disagreement_blocks(field, value):
    records = restore_pair()
    records["/fixture/runs/restore-example.json"]["data"][field] = value
    assert "restore_snapshot_mismatch" in codes(project_records(records, JOBS, ALIASES))


def test_restore_detail_filename_is_exact_restore_id_not_display_name():
    records = restore_pair()
    records["/fixture/runs/other-name.json"] = records.pop("/fixture/runs/restore-example.json")
    assert "restore_detail_filename_mismatch" in codes(project_records(records, JOBS, ALIASES))


def test_active_restore_must_not_collide_with_terminal_history():
    records = restore_pair()
    row = {**records["/fixture/index.json"]["data"]["runs"][0], "state": "running"}
    records["/fixture/restore-runs.json"] = rec("restore_runs", {"schema_version": 1, "runs": {"restore-example": row}})
    assert "restore_active_history_collision" in codes(project_records(records, JOBS, ALIASES))


def test_deleted_job_restore_history_pair_is_retained_without_inventing_identity():
    records = restore_pair()
    records["/fixture/index.json"]["data"]["runs"][0]["job_key"] = "deleted_local"
    records["/fixture/runs/restore-example.json"]["data"]["job_key"] = "deleted_local"
    result = project_records(records, JOBS, ALIASES)
    assert not codes(result)
    assert all(binding["job_id"] is None for binding in result["bindings"])
    assert verify_records(result["records"], JOBS, ALIASES) == []
    broken = deepcopy(result["records"])
    broken.pop("/fixture/index.json")
    assert "missing_restore_index_entry" in {r["code"] for r in verify_records(broken, JOBS, ALIASES)}


@pytest.mark.parametrize("filename", ["config_local.test", f"{OTHER}.test", "display-name.test"])
def test_verifier_rejects_mapped_restore_proof_under_wrong_filename(filename):
    records = {"/fixture/tests/" + filename: rec("restore_test", {"schema_version": 1, "job_id": JOB,
        "tested_archive": "old-archive", "test_result": "PASS"}, legacy_key=filename[:-5])}
    assert "restore_test_filename_mismatch" in {r["code"] for r in verify_records(records, JOBS, ALIASES)}


def test_verifier_accepts_canonical_restore_test_and_unassigned_legacy_proof():
    records = {f"/fixture/tests/{JOB}.test": rec("restore_test", {"schema_version": 1, "job_id": JOB,
        "tested_archive": "old-archive", "test_result": "PASS"}, legacy_key=JOB),
        "/fixture/tests/deleted_local.test": rec("restore_test", {"identity_schema_version": 1,
        "identity_state": "unassigned", "identity_reason": "no_configured_job", "tested_archive": "deleted-archive"},
        legacy_key="deleted_local")}
    assert verify_records(records, JOBS, ALIASES) == []


def test_conflicting_canonical_proof_cannot_pass_by_becoming_unassigned_in_verifier():
    records = {f"/fixture/tests/{OTHER}.test": rec("restore_test", {"schema_version": 1, "job_id": JOB},
                                                        legacy_key=OTHER)}
    jobs = {**JOBS, OTHER: {"job_id": OTHER, "repository_key": "other"}}
    reasons = {reason["code"] for reason in verify_records(records, jobs, ALIASES)}
    assert reasons == {"conflicting_canonical_identity", "restore_test_filename_mismatch"}


@pytest.mark.parametrize("kind,field", [("status", None), ("notification_deliveries", "deliveries")])
def test_deleted_job_historical_record_keeps_its_former_immutable_id(kind, field):
    row = {"schema_version": 1, "job_id": OTHER, "job_key": "deleted_local", "archive": "old-archive"}
    data = {"schema_version": 1, field: [row]} if field else row
    result = project(kind, data)
    assert not codes(result)
    target = output(result)[field][0] if field else output(result)
    assert target["job_id"] == OTHER
    assert target["job_key"] == "deleted_local"
    assert target["identity_state"] == "unassigned"
    assert target["identity_reason"] == "deleted_job"
    assert result["bindings"][0]["job_id"] is None
    assert result["unassigned"][0]["data"] == row
    assert verify_records(result["records"], JOBS, ALIASES) == []
    # Reading older canonical history without the new diagnostic does not
    # require a current configured owner or resurrect a job.
    assert verify_records({"/fixture/input": rec(kind, data)}, JOBS, ALIASES) == []


def test_deleted_job_restore_history_keeps_former_id_in_both_peers():
    records = restore_pair()
    summary = records["/fixture/index.json"]["data"]["runs"][0]
    detail = records["/fixture/runs/restore-example.json"]["data"]
    for row in (summary, detail):
        row["job_id"] = OTHER
        row["job_key"] = "deleted_local"
    result = project_records(records, JOBS, ALIASES)
    assert not codes(result)
    assert result["records"]["/fixture/index.json"]["data"]["runs"][0]["job_id"] == OTHER
    assert result["records"]["/fixture/runs/restore-example.json"]["data"]["job_id"] == OTHER
    assert all(binding["job_id"] is None for binding in result["bindings"])
    assert verify_records(result["records"], JOBS, ALIASES) == []


def test_deleted_job_weekly_observation_never_loses_former_uuid():
    row = {"job_id": OTHER, "legacy_job_key": "deleted_local", "week": "2026-08-31", "size": 100,
           "source_records": [{"source": "/fixture/old-weekly", "locator": "/deleted_local/0"}]}
    data = {"schema_version": 1, "identity_schema_version": 1, "observations": [row]}
    result = project("weekly", data)
    assert not codes(result)
    target = output(result)["observations"][0]
    assert target["job_id"] == OTHER
    assert target["identity_state"] == "unassigned"
    assert target["identity_reason"] == "deleted_job"
    assert target["source_records"] == row["source_records"]
    assert result["bindings"][0]["job_id"] is None
    assert result["unassigned"][0]["data"] == row
    assert verify_records(result["records"], JOBS, ALIASES) == []
    assert verify_records({"/fixture/input": rec("weekly", data)}, JOBS, ALIASES) == []
    assert output(project_records(result["records"], JOBS, ALIASES)) == output(result)


@pytest.mark.parametrize("kind,field", [("control", None), ("notification_queue", "queue")])
def test_former_uuid_never_authorizes_active_dangling_reference(kind, field):
    row = {"schema_version": 1, "job_id": OTHER, "legacy_job_key": "deleted_local"}
    data = {"schema_version": 1, field: [row]} if field else row
    result = project(kind, data)
    assert codes(result)
    assert verify_records({"/fixture/input": rec(kind, data)}, JOBS, ALIASES)


def test_conflicting_canonical_history_blocks_plan_without_overwriting_original_id():
    row = {"schema_version": 1, "job_id": OTHER, "job_key": "config_local"}
    result = project("status", row)
    assert "conflicting_canonical_identity" in codes(result)
    assert output(result)["job_id"] == OTHER
    assert output(result)["job_key"] == "config_local"


def test_conflicting_canonical_weekly_identity_blocks_without_reassigning_uuid():
    row = {"job_id": OTHER, "legacy_job_key": "config_local", "week": "2026-08-31", "size": 100,
           "source_records": [{"source": "/fixture/old-weekly", "locator": "/config_local/0"}]}
    result = project("weekly", {"schema_version": 1, "identity_schema_version": 1, "observations": [row]})
    assert "conflicting_canonical_identity" in codes(result)
    assert output(result)["observations"][0]["job_id"] == OTHER
