"""#479: actual file/cron cutover and explicit recovery at durable boundaries."""

from copy import deepcopy
import errno
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID

import pytest

from identity_contract_support import ROOT, load_cases, materialize, source_value, tree_bytes
from test_identity_planner import _assert_contains_original, _planned_value, binding_projection

sys.path.insert(0, str(ROOT / "api"))
from migrations import identity_apply as engine
from migrations import identity_storage as storage
from migrations import immutable_job_id_v1 as planner


CASES = {case["id"]: case for case in load_cases()}


@pytest.fixture
def install():
    parent = ROOT / ".release-tmp"
    parent.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="identity-479-apply-", dir=parent) as temporary:
        root = Path(temporary)
        installed = root / "installation"
        case = materialize(CASES["legacy_without_prefixes"], installed)
        case["config"]["PLUGIN_DIR"] = str(installed / "plugin")
        yield {"root": root, "installed": installed, "case": case,
               "config": case["config"], "control": installed / "run",
               "state": root / "private-state"}


def prepare(install):
    values = iter(install["case"]["allocation_order"])
    original = "# unrelated\n17 2 * * * printf unrelated\n\n" + engine._BEGIN + "\nold-job\n" + engine._END + "\n# retained trailing comment\n"
    plan = planner.build_plan(install["config"], control_root=install["control"],
                              uuid_factory=lambda: UUID(next(values)), cron_text=original)
    assert plan["classification"] == "applicable", plan.get("reasons")
    return save(install, plan)


def save(install, plan):
    snapshot = storage.create_snapshot(plan, install["state"])
    approval = {"approved": True, "independent_backup_acknowledged": True,
                "plan_id": plan["plan_id"], "snapshot_digest": snapshot["digest"]}
    install.update(plan=plan, snapshot=snapshot, approval=approval,
                   cron=[plan["external_inputs"]["managed_cron"]["text"]], cron_writes=[])
    return install


def run(install, **overrides):
    def write_cron(text):
        install["cron_writes"].append(text)
        install["cron"][0] = text
    options = {"approval": install["approval"], "quiescence_callback": lambda: True,
               "read_cron": lambda: install["cron"][0], "write_cron": write_cron,
               "render_cron": lambda original, plan: engine.replace_managed_cron(
                   original, ["0 8 * * * uuid=" + identity for identity in sorted(plan["jobs"])]),
               "control_root": install["control"]}
    options.update(overrides)
    return engine.apply_plan(install["config"], install["state"], **options)


def error(code, callback):
    with pytest.raises(storage.IdentityStorageError) as caught:
        callback()
    assert caught.value.code == code
    assert str(caught.value) == code


def test_real_cutover_verifies_graph_preserves_originals_and_is_idempotent(install):
    prepare(install)
    original_logs = tree_bytes(install["installed"] / "logs")
    original_plan = (install["state"] / "plan.json").read_bytes()
    result = run(install)
    assert result["status"] == "applied" and result["already_applied"] is False
    assert planner.verify_target(install["config"], control_root=install["control"])["valid"]
    for action in install["plan"]["actions"]:
        if action["kind"] == "write_json":
            assert storage.fingerprint_file(action["target"]) == action["after"]
        elif action["kind"] == "retire_source":
            assert not Path(action["source"]).exists()
    assert tree_bytes(install["installed"] / "logs") == original_logs
    assert (install["state"] / "plan.json").read_bytes() == original_plan
    storage.verify_snapshot(install["plan"], install["snapshot"])
    assert len(install["cron_writes"]) == 1
    journal = storage.read_journal(install["state"])
    assert journal[-1]["phase"] == "commit" and journal[-1]["status"] == "applied"
    assert run(install)["already_applied"] is True
    assert storage.read_journal(install["state"]) == journal
    assert len(install["cron_writes"]) == 1


@pytest.mark.parametrize("original", ["", "no-final-newline", "# keep\n\n* * * * * other\n",
    "# before\n" + engine._BEGIN + "\nold\n" + engine._END + "\n\n# after"])
@pytest.mark.parametrize("lines", [[], ["0 8 * * * backup uuid"]])
def test_managed_cron_replacement_preserves_unrelated_bytes(original, lines):
    result = engine.replace_managed_cron(original, lines)
    before, after, _ = engine._cron_parts(original)
    new_before, new_after, _ = engine._cron_parts(result)
    assert before + after == new_before + new_after
    assert (engine._BEGIN in result) is bool(lines)


@pytest.mark.parametrize("change", ["approval", "acknowledgement", "plan", "digest", "writer", "cron", "source"])
def test_preconditions_block_without_installation_rewrite(install, change):
    prepare(install)
    options = {}
    if change == "approval":
        install["approval"]["approved"] = False
    elif change == "acknowledgement":
        install["approval"]["independent_backup_acknowledged"] = False
    elif change == "plan":
        install["approval"]["plan_id"] = "wrong"
    elif change == "digest":
        install["approval"]["snapshot_digest"] = "wrong"
    elif change == "writer":
        options["quiescence_callback"] = lambda: False
    elif change == "cron":
        install["cron"][0] += "# external edit\n"
    else:
        source = Path(next(iter(install["plan"]["job_sources"].values())))
        source.write_bytes(source.read_bytes() + b"\n")
    before = tree_bytes(install["installed"])
    with pytest.raises(storage.IdentityStorageError):
        run(install, **options)
    assert tree_bytes(install["installed"]) == before
    assert install["cron_writes"] == []


class PowerLoss(BaseException):
    pass


@pytest.mark.parametrize("boundary", ["before_write", "after_write", "after_retire", "before_commit", "after_cron", "after_commit"])
def test_explicit_resume_at_each_file_and_commit_boundary_reuses_plan(install, monkeypatch, boundary):
    prepare(install)
    original_ids = install["plan"]["id_map"]
    append = storage.append_journal
    publish, retire = engine._publish_replacement, engine._retire
    fired = []
    def interrupt_once():
        if not fired:
            fired.append(True)
            raise PowerLoss()
    def writing(action, plan):
        if boundary == "before_write":
            interrupt_once()
        publish(action, plan)
        if boundary == "after_write":
            interrupt_once()
    def retiring(action, plan, targets):
        retire(action, plan, targets)
        if boundary == "after_retire":
            interrupt_once()
    def journaling(state, plan, status, phase, **kwargs):
        if boundary == "before_commit" and phase == "commit" and status == "pending":
            interrupt_once()
        if boundary == "after_cron" and phase == "commit" and status == "applied":
            interrupt_once()
        result = append(state, plan, status, phase, **kwargs)
        if boundary == "after_commit" and phase == "commit" and status == "applied":
            interrupt_once()
        return result
    monkeypatch.setattr(engine, "_publish_replacement", writing)
    monkeypatch.setattr(engine, "_retire", retiring)
    monkeypatch.setattr(storage, "append_journal", journaling)
    with pytest.raises(PowerLoss):
        run(install)
    before_retry = tree_bytes(install["installed"])
    assert storage.load_plan(install["state"])["id_map"] == original_ids
    storage.verify_snapshot(install["plan"], install["snapshot"])
    assert tree_bytes(install["installed"]) == before_retry, "reading recovery state must not apply"
    result = run(install)
    assert result["status"] == "applied"
    assert storage.load_plan(install["state"])["id_map"] == original_ids
    assert len(install["cron_writes"]) == 1


def test_unexplained_edit_after_interruption_is_not_overwritten(install, monkeypatch):
    prepare(install)
    publish = engine._publish_replacement
    def interrupt(action, plan):
        publish(action, plan)
        raise PowerLoss()
    monkeypatch.setattr(engine, "_publish_replacement", interrupt)
    with pytest.raises(PowerLoss):
        run(install)
    target = next(a["target"] for a in install["plan"]["actions"] if a["kind"] == "write_json")
    Path(target).write_bytes(Path(target).read_bytes() + b"\n")
    before = tree_bytes(install["installed"])
    error("input_changed", lambda: run(install))
    assert tree_bytes(install["installed"]) == before


def test_exact_target_without_journaled_write_intent_is_not_resume_authority(install):
    prepare(install)
    action = next(a for a in install["plan"]["actions"] if a["kind"] == "write_json")
    Path(action["target"]).write_bytes(planner.encode_target_json(action["data"]))
    Path(action["target"]).chmod(action["after"]["mode"])
    error("input_changed", lambda: run(install))
    assert Path(action["source"]).exists()


def test_derived_cache_is_retired_only_after_snapshot_and_then_final_graph_verifies(install):
    widget = install["installed"] / "plugin" / "widget-status.json"
    widget.parent.mkdir()
    widget.write_text(json.dumps({"schema_version": 1, "jobs": [{"job_key": "config_local"}]}))
    prepare(install)
    assert any(a["kind"] == "rebuild_derived" for a in install["plan"]["actions"])
    run(install)
    assert not widget.exists()
    manifest = storage.verify_snapshot(install["plan"], install["snapshot"])
    assert manifest["entries"][str(widget)]["original"]["exists"]


def test_missing_canonical_jobs_directory_is_published_and_receipted(install):
    jobs = install["installed"] / "data" / "config" / "jobs"
    legacy = install["installed"] / "data" / "scripts" / "config" / "jobs"
    legacy.parent.mkdir(parents=True)
    jobs.rename(legacy)
    prepare(install)
    run(install)
    assert jobs.is_dir() and len(list(jobs.glob("*.json"))) == 1
    assert list(install["state"].glob("directory-*.json"))
    assert run(install)["already_applied"]


def test_canonical_config_bytes_and_obsolete_schema_are_in_same_snapshot_transaction(install):
    # The assistant augments the domain plan with the version-owned pure
    # configuration projection before persistence/consent, never afterwards.
    values = iter(install["case"]["allocation_order"])
    plan = planner.build_plan(install["config"], control_root=install["control"],
                              uuid_factory=lambda: UUID(next(values)), cron_text="")
    config_file = install["installed"] / "data/config/backup.conf"
    schema_file = config_file.with_name("backup.conf.example")
    schema_file.write_bytes(b"# old version-owned schema\n")
    text = config_file.read_text() + "# canonical config\n"
    plan["inputs"][str(schema_file)] = storage.fingerprint_file(schema_file)
    action = {"kind": "write_bytes", "source": str(config_file), "target": str(config_file),
              "text": text, "after": {"exists": True, "size": len(text.encode()),
              "sha256": hashlib.sha256(text.encode()).hexdigest(), "mode": config_file.stat().st_mode & 0o7777}}
    action["id"] = hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()
    retire = {"kind": "retire_auxiliary", "source": str(schema_file), "target": str(config_file)}
    retire["id"] = hashlib.sha256(json.dumps(retire, sort_keys=True).encode()).hexdigest()
    plan["actions"] += [action, retire]
    plan.pop("plan_id")
    plan = storage.seal_plan(plan)
    save(install, plan)
    run(install)
    assert config_file.read_text() == text and not schema_file.exists()
    storage.verify_snapshot(plan, install["snapshot"])


def test_disk_full_after_intent_preserves_source_and_sanitizes_failure(install, monkeypatch):
    prepare(install)
    before = tree_bytes(install["installed"])
    def full(*args):
        raise OSError(errno.ENOSPC, "do not expose confidential content")
    monkeypatch.setattr(engine, "_publish_replacement", full)
    error("insufficient_space", lambda: run(install))
    assert tree_bytes(install["installed"]) == before
    assert storage.read_journal(install["state"])[-1]["reason_code"] == "insufficient_space"


def test_final_integrity_failure_never_installs_cron_or_commits(install, monkeypatch):
    prepare(install)
    monkeypatch.setattr(planner, "verify_target", lambda *args, **kwargs: {"valid": False})
    error("verification_failed", lambda: run(install))
    assert install["cron_writes"] == []
    assert not any(r["status"] == "applied" and r["phase"] == "commit"
                   for r in storage.read_journal(install["state"]))


def test_renderer_cannot_replace_unrelated_cron_content(install):
    prepare(install)
    before = tree_bytes(install["installed"])
    error("input_changed", lambda: run(install, render_cron=lambda *args: "* * * * * erased-other-jobs\n"))
    assert tree_bytes(install["installed"]) == before


def test_partial_unknown_staging_content_is_retained_and_blocked(install, monkeypatch):
    prepare(install)
    publish = engine._publish_replacement
    def interrupt(action, plan):
        temporary = ".identity-" + plan["plan_id"][:16] + "-" + hashlib.sha256(action["id"].encode()).hexdigest()[:24] + ".stage"
        staged = Path(action["target"]).parent / temporary
        staged.write_bytes(b"unexplained-content")
        staged.chmod(0o600)
        raise PowerLoss()
    monkeypatch.setattr(engine, "_publish_replacement", interrupt)
    with pytest.raises(PowerLoss):
        run(install)
    monkeypatch.setattr(engine, "_publish_replacement", publish)
    before = tree_bytes(install["installed"])
    error("state_conflict", lambda: run(install))
    assert tree_bytes(install["installed"]) == before


@pytest.mark.parametrize("case_id", [name for name in CASES if name not in {
    "live_writer", "source_changed_after_plan", "snapshot_unverified", "interrupted_with_journal",
}], ids=str)
def test_phase1_matrix_actual_snapshot_cutover_and_golden_destinations(install, case_id):
    installed = install["root"] / "matrix-installation"
    case = materialize(CASES[case_id], installed)
    case["config"]["PLUGIN_DIR"] = str(installed / "plugin")
    install.update(installed=installed, case=case, config=case["config"], control=installed / "run")
    expected = case["expected"]
    before = tree_bytes(installed)
    values = iter(case["allocation_order"])
    plan = planner.build_plan(install["config"], control_root=install["control"],
                              uuid_factory=lambda: UUID(next(values)), cron_text="# unrelated\n")
    assert plan["classification"] == expected["classification"]
    assert tree_bytes(installed) == before
    if plan["classification"] != "applicable":
        assert not install["state"].exists()
        return
    save(install, plan)
    assert tree_bytes(installed) == before
    assert run(install)["status"] == "applied"
    assert planner.verify_target(install["config"], control_root=install["control"])["valid"]
    actual_jobs = {path.stem: json.loads(path.read_text())
                   for path in (installed / "data/config/jobs").glob("*.json")}
    assert actual_jobs == expected["jobs"]
    # Reuse the phase-1 provenance/JSON-pointer adapter, but replace EVERY
    # proposed payload by freshly read destination bytes before observing it.
    observed = deepcopy(plan)
    for target, row in observed["records"].items():
        actual = json.loads(Path(target).read_bytes())
        assert actual == row["data"]
        row["data"] = actual
    assert binding_projection(observed, installed) == expected["bindings"]
    for reference, preserved in expected["preserved"].items():
        _assert_contains_original(_planned_value(observed, installed, reference), preserved)
    for reference, identity in expected["bindings"].items():
        if identity is None:
            _assert_contains_original(_planned_value(observed, installed, reference),
                                      source_value(case["files"], reference))
    for path in expected["unchanged_files"]:
        assert (installed / path).read_bytes() == before[path]
    storage.verify_snapshot(plan, install["snapshot"])


@pytest.mark.parametrize("boundary", ["before_receipt", "before_rename", "after_rename"])
def test_resume_missing_directory_publication_boundaries(install, monkeypatch, boundary):
    jobs = install["installed"] / "data/config/jobs"
    legacy = install["installed"] / "data/scripts/config/jobs"
    legacy.parent.mkdir(parents=True)
    jobs.rename(legacy)
    prepare(install)
    publish, rename = storage._publish_once, engine.os.rename
    fired = []
    def once():
        if not fired:
            fired.append(True)
            raise PowerLoss()
    def publishing(path, content):
        if boundary == "before_receipt" and path.name.startswith("directory-"):
            once()
        return publish(path, content)
    def renaming(*args, **kwargs):
        if boundary == "before_rename":
            once()
        result = rename(*args, **kwargs)
        if boundary == "after_rename":
            once()
        return result
    monkeypatch.setattr(storage, "_publish_once", publishing)
    monkeypatch.setattr(engine.os, "rename", renaming)
    with pytest.raises(PowerLoss):
        run(install)
    assert run(install)["status"] == "applied"


def test_exact_partial_staging_prefix_can_resume_without_changing_identity(install, monkeypatch):
    prepare(install)
    publish = engine._publish_replacement
    def interrupt(action, plan):
        temporary = ".identity-" + plan["plan_id"][:16] + "-" + hashlib.sha256(action["id"].encode()).hexdigest()[:24] + ".stage"
        staged = Path(action["target"]).parent / temporary
        staged.write_bytes(planner.encode_target_json(action["data"])[:20])
        staged.chmod(0o600)
        raise PowerLoss()
    monkeypatch.setattr(engine, "_publish_replacement", interrupt)
    with pytest.raises(PowerLoss):
        run(install)
    monkeypatch.setattr(engine, "_publish_replacement", publish)
    assert run(install)["status"] == "applied"
    assert storage.load_plan(install["state"])["id_map"] == install["plan"]["id_map"]


def test_duplicate_apply_is_rejected_while_original_operation_holds_plan_lock(install, monkeypatch):
    prepare(install)
    publish = engine._publish_replacement
    observed = []
    def publishing(action, plan):
        error("writers_active", lambda: run(install))
        observed.append(action["id"])
        return publish(action, plan)
    monkeypatch.setattr(engine, "_publish_replacement", publishing)
    assert run(install)["status"] == "applied"
    assert observed


def test_completed_read_only_stage_can_resume_after_permission_flush(install, monkeypatch):
    source = install["installed"] / "data/config/jobs/config_local.json"
    source.chmod(0o444)
    prepare(install)
    replace = engine.os.replace
    def interrupt(*args, **kwargs):
        raise PowerLoss()
    monkeypatch.setattr(engine.os, "replace", interrupt)
    with pytest.raises(PowerLoss):
        run(install)
    monkeypatch.setattr(engine.os, "replace", replace)
    assert run(install)["status"] == "applied"
    target = Path(next(a["target"] for a in install["plan"]["actions"] if a["kind"] == "write_json"))
    assert target.stat().st_mode & 0o777 == 0o444


def test_destination_directory_may_preserve_mount_defined_parent_mode(install, monkeypatch):
    jobs = install["installed"] / "data/config/jobs"
    legacy = install["installed"] / "data/scripts/config/jobs"
    legacy.parent.mkdir(parents=True)
    jobs.rename(legacy)
    prepare(install)
    mkdir = engine.os.mkdir
    def mount_defined_mode(path, mode=0o777, *, dir_fd=None):
        if str(path).startswith(".identity-dir-"):
            mode = engine.stat.S_IMODE(os.fstat(dir_fd).st_mode)
        return mkdir(path, mode, dir_fd=dir_fd)
    monkeypatch.setattr(engine.os, "mkdir", mount_defined_mode)
    assert run(install)["status"] == "applied"
    assert jobs.stat().st_mode & 0o777 == jobs.parent.stat().st_mode & 0o777
    assert install["state"].stat().st_mode & 0o777 == 0o700
    assert (install["state"] / "snapshot").stat().st_mode & 0o777 == 0o700


def test_destination_directory_does_not_accept_unrelated_permission_change(install, monkeypatch):
    jobs = install["installed"] / "data/config/jobs"
    legacy = install["installed"] / "data/scripts/config/jobs"
    legacy.parent.mkdir(parents=True)
    jobs.rename(legacy)
    prepare(install)
    mkdir = engine.os.mkdir
    def unexpected_mode(path, mode=0o777, *, dir_fd=None):
        result = mkdir(path, mode, dir_fd=dir_fd)
        if str(path).startswith(".identity-dir-"):
            os.chmod(path, 0o707, dir_fd=dir_fd)
        return result
    monkeypatch.setattr(engine.os, "mkdir", unexpected_mode)
    error("state_conflict", lambda: run(install))
    assert not jobs.exists()
    assert (legacy / "config_local.json").exists()
