"""Real on-disk administrator gates, including independent-backup pause (#479)."""
from pathlib import Path
import json
import sys
import threading
import pytest
from identity_contract_support import ROOT, load_cases, materialize, tree_bytes
sys.path.insert(0, str(ROOT / "api"))
from identity_migration_api import IdentityMigrationAssistant, MigrationRequestError
from migrations import identity_storage as storage
from migrations import registry
from migration_barrier import writer_lease, block_writers, clear_block, exclusive_migration


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setenv("BORG_UI_MIGRATION_GATE_ROOT", str(tmp_path / "gates"))
    # Real tests isolate the installation from unrelated host processes.
    import migration_barrier
    monkeypatch.setattr(migration_barrier, "_legacy_process_blockers", lambda: []) if hasattr(migration_barrier, "_legacy_process_blockers") else None
    case = next(case for case in load_cases() if case["id"] == "legacy_without_prefixes")
    target = tmp_path / "installation"
    fixture = materialize(case, target)
    config = fixture["config"]
    config["PLUGIN_DIR"] = str(target / "plugin")
    config["BORG_UI_CONTROL_ROOT"] = str(target / "run")
    config["BACKUP_CONF_SCHEMA_FILE"] = str(target / "schema.example")
    # Retain all synthetic legacy defaults in the version-owned fixture schema.
    (target / "schema.example").write_bytes((target / "data/config/backup.conf").read_bytes())
    cron = ["MAILTO=synthetic@example.invalid\n"]
    activated = []
    assistant = IdentityMigrationAssistant(config, read_cron=lambda: cron[0], write_cron=lambda value: cron.__setitem__(0, value), activate=lambda cfg: activated.append(True))
    import identity_migration_api
    monkeypatch.setitem(identity_migration_api._ASSISTANTS, str(target / "data"), assistant)
    return target, config, assistant, cron, activated


def binding(status):
    return {"plan_id": status["plan_id"], "snapshot_digest": status["snapshot_digest"]}


def prepare(installation):
    root, config, assistant, cron, _ = installation
    return assistant.prepare({"state_dir": str(root / "migration")}, background=False)


def test_startup_and_get_never_prepare_or_run_earlier_migration(installation):
    root, config, assistant, _, _ = installation
    before = tree_bytes(root)
    result = registry.run_startup_migrations(config)
    assert result["status"] == "pending"
    assert result["results"]["canonical_backup_conf_v1"]["status"] == "blocked"
    assert assistant.status()["stage"] == "required"
    assert before == tree_bytes(root)


def test_verified_snapshot_pause_acknowledgement_and_separate_apply(installation):
    root, config, assistant, cron, activated = installation
    before = tree_bytes(root / "data/config")
    status = prepare(installation)
    assert status["stage"] == "backup_ready", status
    assert status["snapshot"]["verified"]
    assert tree_bytes(root / "data/config") == before
    with assistant.snapshot_files(binding(status)) as export:
        assert "snapshot/manifest.json" in {name for name, path, fp in export["members"]}
    assert tree_bytes(root / "data/config") == before
    with pytest.raises(MigrationRequestError, match="independent_backup_ack_required"):
        assistant.apply(binding(status), background=False)
    status = assistant.acknowledge({**binding(status), "independent_backup_ack": True})
    assert status["stage"] == "acknowledged"
    assert tree_bytes(root / "data/config") == before
    result = assistant.apply(binding(status), background=False)
    assert result["status"] == "applied", result
    assert activated == [True]
    assert cron[0].endswith("MAILTO=synthetic@example.invalid\n")
    with writer_lease(config):
        pass
    ids = sorted(p.name for p in (root / "data/config/jobs").glob("*.json"))
    restarted = IdentityMigrationAssistant(config)
    assert restarted.startup_detection()["required"] is False
    assert ids == sorted(p.name for p in (root / "data/config/jobs").glob("*.json"))


def test_snapshot_pause_survives_browser_and_restart_without_reallocation(installation):
    root, config, assistant, cron, _ = installation
    status = prepare(installation)
    original = storage.load_plan(root / "migration")
    restarted = IdentityMigrationAssistant(config, read_cron=lambda: cron[0])
    assert restarted.startup_detection()["required"]
    again = restarted.status()
    assert again["stage"] == "backup_ready"
    assert binding(again) == binding(status)
    assert storage.load_plan(root / "migration") == original
    with pytest.raises(MigrationRequestError):
        restarted.apply(binding(again), background=False)


@pytest.mark.parametrize("field", ["plan_id", "snapshot_digest"])
def test_unbound_approval_is_rejected(installation, field):
    _, _, assistant, _, _ = installation
    status = prepare(installation)
    bad = {**binding(status), field: "not-the-verified-copy", "independent_backup_ack": True}
    with pytest.raises(MigrationRequestError, match="approval_required"):
        assistant.acknowledge(bad)


@pytest.mark.parametrize("changed", ["source", "cron", "snapshot"])
def test_changes_invalidate_approval_before_conversion(installation, changed):
    root, _, assistant, cron, activated = installation
    status = prepare(installation)
    assistant.acknowledge({**binding(status), "independent_backup_ack": True})
    if changed == "source":
        with (root / "data/config/backup.conf").open("a") as handle:
            handle.write("# external edit\n")
    elif changed == "cron":
        cron[0] += "# external edit\n"
    else:
        next((root / "migration/snapshot/files").iterdir()).write_bytes(b"changed")
    before = tree_bytes(root / "data/config")
    try:
        result = assistant.apply(binding(status), background=False)
    except storage.IdentityStorageError:
        result = assistant.status()
    assert result["status"] in {"blocked", "failed"}
    assert tree_bytes(root / "data/config") == before
    assert activated == []


def test_existing_worker_finishes_before_explicit_preparation_retry(installation):
    root, config, assistant, _, _ = installation
    block_writers(config)
    with exclusive_migration(config):
        clear_block(config)
    with writer_lease(config):
        status = prepare(installation)
        assert status['stage'] == 'waiting', status
        assert not (root / 'migration').exists()
        assert not assistant.selector.exists()
    assert prepare(installation)['stage'] == 'backup_ready'


def test_unavailable_snapshot_mount_does_not_persist_location_or_ids(installation):
    _, _, assistant, _, _ = installation
    status = assistant.prepare({'state_dir':'/mnt/disks/identity-test-unavailable/backup'}, background=False)
    assert status['status'] == 'blocked'
    assert not assistant.selector.exists()


def test_preparing_is_visible_while_read_only_planning_is_running(installation, monkeypatch):
    from migrations import immutable_job_id_v1 as identity
    root, _, assistant, _, _ = installation
    planning = threading.Event()
    finish = threading.Event()
    build = identity.build_plan

    def slow_plan(*args, **kwargs):
        planning.set()
        assert finish.wait(5)
        return build(*args, **kwargs)

    monkeypatch.setattr(identity, "build_plan", slow_plan)
    try:
        result = assistant.prepare({"state_dir": str(root / "migration")})
        assert planning.wait(5)
        assert result["busy"] is True
        assert result["stage"] == "preparing"
        assert assistant.status()["stage"] == "preparing"
        assert not (root / "migration").exists()
        assert not assistant.selector.exists()
    finally:
        finish.set()
        assert assistant._operation.acquire(timeout=5)
        assistant._operation.release()
    assert assistant.status()["stage"] == "backup_ready"


def test_invalid_destination_is_reported_before_plan_or_cron_read(installation):
    root, config, assistant, _, _ = installation
    block_writers(config)
    before = tree_bytes(root)
    assistant.read_cron = lambda: pytest.fail("invalid destination reached planning")
    result = assistant.prepare({"state_dir": "/boot/config/identity-backup"}, background=False)
    assert result["reason_codes"] == ["persistent_private_storage_required"]
    assert result["last_preparation"]["reason_codes"] == result["reason_codes"]
    assert tree_bytes(root) == before


def test_failed_preparation_remains_visible_after_readiness_retry_until_explicit_retry(installation):
    from identity_startup_watch import retry_startup_once
    root, config, assistant, _, _ = installation
    result = assistant.prepare({"state_dir": "/boot/config/identity-backup"}, background=False)
    failure = result["last_preparation"]
    assert failure["status"] == "blocked"
    assert failure["updated_at"]
    assert not assistant.selector.exists()
    before = tree_bytes(root)
    assert retry_startup_once(config, assistant=assistant, storage_ready=lambda _: True,
        activate=lambda _: pytest.fail("preparation failure bypassed migration consent")) == "waiting"
    assert assistant.status()["last_preparation"] == failure
    assert tree_bytes(root) == before
    result = prepare(installation)
    assert result["stage"] == "backup_ready"
    assert "last_preparation" not in result


def test_blocked_plan_retains_safe_failure_without_creating_destination(installation):
    root, config, assistant, _, _ = installation
    block_writers(config)
    source = root / "data/config/jobs/config_local.json"
    record = json.loads(source.read_text())
    record["schema_version"] = 99
    source.write_text(json.dumps(record))
    before = tree_bytes(root)
    result = prepare(installation)
    assert result["last_preparation"]["reason_codes"] == ["unsupported_schema"]
    assert not assistant.selector.exists()
    assert not (root / "migration").exists()
    assert tree_bytes(root) == before


def test_preparation_failure_never_returns_raw_exception_details(installation):
    _, _, assistant, _, _ = installation

    def unavailable_cron():
        raise OSError("synthetic password=must-not-be-returned")

    assistant.read_cron = unavailable_cron
    result = prepare(installation)
    assert result["last_preparation"]["reason_codes"] == ["migration_operation_failed"]
    assert "must-not-be-returned" not in json.dumps(result)


def test_failed_apply_requires_restart_before_original_plan_retry(installation, monkeypatch):
    from migrations import identity_apply
    root, config, assistant, cron, _ = installation
    status = prepare(installation)
    assistant.acknowledge({**binding(status), 'independent_backup_ack':True})
    original = identity_apply._publish_replacement
    monkeypatch.setattr(identity_apply, '_publish_replacement', lambda *args: (_ for _ in ()).throw(OSError('synthetic password=do-not-expose')))
    result = assistant.apply(binding(status), background=False)
    assert result['restart_required'] is True
    assert 'do-not-expose' not in json.dumps(result)
    with pytest.raises(MigrationRequestError, match='restart_required'):
        assistant.apply(binding(status), background=False)
    monkeypatch.setattr(identity_apply, '_publish_replacement', original)
    restarted = IdentityMigrationAssistant(config, read_cron=lambda: cron[0], write_cron=lambda value: cron.__setitem__(0,value))
    import identity_migration_api
    monkeypatch.setitem(identity_migration_api._ASSISTANTS, str(root / 'data'), restarted)
    assert restarted.startup_detection()['required']
    assert restarted.status()['can_resume']
    result = restarted.apply(binding(status), background=False)
    assert result['status'] == 'applied', result
    assert result['plan_id'] == status['plan_id']


def test_maintenance_diagnostics_do_not_create_locks_or_change_snapshot_inputs(installation, monkeypatch):
    root, config, assistant, _, _ = installation
    from startup_state import set_startup_state, migration_maintenance_state
    set_startup_state(config, migration_maintenance_state({'failed':['immutable_job_id_v1']}))
    status = prepare(installation)
    assert status['stage'] == 'backup_ready'
    plan = storage.load_plan(root / 'migration')
    from support_bundle_api import create_support_bundle
    monkeypatch.setattr('system_health_api.get_system_health_data', lambda config: pytest.fail('maintenance called operational health reader'))
    before = tree_bytes(root / 'data')
    bundle = create_support_bundle(config)
    assert bundle['file_count'] == 3
    storage.verify_inputs(plan)
    assert tree_bytes(root / 'data') == before


def test_maintenance_startup_never_writes_widget_even_with_configured_storage(installation):
    _, config, _, _, _ = installation
    config['GLOBAL_DATA_DIR'] = config['BACKUP_SCRIPTS_DIR']
    import borg_backup_ui
    assert borg_backup_ui._start_configured_runtime_writers(config, False,
        widget_startup_writer=lambda *a, **kw: pytest.fail('maintenance widget write'),
        runtime_activator=lambda *a, **kw: pytest.fail('maintenance runtime activation')) is False
