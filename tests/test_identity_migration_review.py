"""Independent qualification of durable UI state and journal observation (#479)."""

import json
import io
import tarfile
import threading
from urllib.parse import urlencode

import pytest

from test_identity_migration_assistant import installation, prepare, binding
from identity_migration_api import IdentityMigrationAssistant, MigrationRequestError
from migrations import identity_storage as storage
from migrations import identity_apply as engine
from identity_contract_support import tree_bytes


@pytest.mark.parametrize("corruption", [
    {"credentials": {"token": "secret-that-must-not-be-returned"}},
    {"reason_codes": [{"token": "secret-that-must-not-be-returned"}]},
    {"reason_codes": ["secret-that-must-not-be-returned"]},
    {"plan_id": ["invalid-binding"]},
    {"snapshot_digest": True},
])
def test_private_assistant_metadata_is_not_a_public_arbitrary_payload(installation, corruption):
    root, config, _, cron, _ = installation
    prepare(installation)
    path = root / "migration/assistant.json"
    meta = json.loads(path.read_text())
    meta.update(corruption)
    path.write_text(json.dumps(meta))
    restarted = IdentityMigrationAssistant(config, read_cron=lambda: cron[0])
    detected = restarted.startup_detection()
    status = restarted.status()
    assert detected["required"] is True and detected["status"] == "blocked"
    assert status["status"] == "blocked"
    assert "secret-that-must-not-be-returned" not in json.dumps(status)
    assert "credentials" not in status


@pytest.mark.parametrize("field", ["plan_id", "snapshot_digest"])
def test_snapshot_export_requires_the_exact_verified_binding(installation, field):
    _, _, assistant, _, _ = installation
    status = prepare(installation)
    wrong = {**binding(status), field: "different"}
    with pytest.raises(MigrationRequestError, match="approval_required"):
        with assistant.snapshot_files(wrong):
            pytest.fail("unbound protected snapshot was exposed")


def test_snapshot_tampering_invalidates_protected_export(installation):
    root, _, assistant, _, _ = installation
    status = prepare(installation)
    original_binding = binding(status)
    next((root / "migration/snapshot/files").iterdir()).write_bytes(b"tampered")
    with pytest.raises(storage.IdentityStorageError):
        with assistant.snapshot_files(original_binding):
            pytest.fail("tampered protected snapshot was exposed")


def test_reader_waits_for_live_journal_append_and_never_observes_half_record(installation, monkeypatch):
    root, _, _, _, _ = installation
    prepare(installation)
    state = root / "migration"
    plan = storage.load_plan(state)
    write = storage.os.write
    half_written, finish_write, read_finished = threading.Event(), threading.Event(), threading.Event()
    errors, results = [], []
    def split_write(fd, value):
        if threading.current_thread().name == "partial-journal-writer" and not half_written.is_set():
            count = write(fd, value[:len(value) // 2])
            half_written.set()
            assert finish_write.wait(10)
            return count
        return write(fd, value)
    def writer():
        try:
            storage.append_journal(state, plan, "pending", "apply")
        except BaseException as exc:
            errors.append(exc)
    def reader():
        try:
            results.append(storage.read_journal(state))
        except BaseException as exc:
            errors.append(exc)
        finally:
            read_finished.set()
    monkeypatch.setattr(storage.os, "write", split_write)
    writer_thread = threading.Thread(target=writer, name="partial-journal-writer")
    reader_thread = threading.Thread(target=reader)
    writer_thread.start()
    try:
        assert half_written.wait(10)
        reader_thread.start()
        assert not read_finished.wait(0.05), "reader did not share append_journal's lock"
    finally:
        finish_write.set()
        writer_thread.join(timeout=10)
        if reader_thread.ident is not None:
            reader_thread.join(timeout=10)
    assert errors == []
    assert read_finished.is_set()
    assert results[0][-1]["phase"] == "apply"
    assert results[0][-1]["status"] == "pending"


class PowerLoss(BaseException):
    pass


def test_interruption_after_plan_persistence_requires_explicit_preparation_and_reuses_ids(installation, monkeypatch):
    root, config, assistant, cron, _ = installation
    append = storage.append_journal
    def interrupted(state, plan, status, phase, **kwargs):
        if phase == "plan":
            raise PowerLoss()
        return append(state, plan, status, phase, **kwargs)
    monkeypatch.setattr(storage, "append_journal", interrupted)
    with pytest.raises(PowerLoss):
        prepare(installation)
    original = storage.load_plan(root / "migration")
    before = tree_bytes(root)
    restarted = IdentityMigrationAssistant(config, read_cron=lambda: cron[0])
    assert restarted.startup_detection()["required"] is True
    assert restarted.status()["stage"] == "interrupted"
    assert tree_bytes(root) == before
    monkeypatch.setattr(storage, "append_journal", append)
    result = restarted.prepare({"state_dir": str(root / "migration")}, background=False)
    assert result["stage"] == "backup_ready"
    assert storage.load_plan(root / "migration") == original


def test_apply_failure_requires_restart_before_explicit_continuation(installation, monkeypatch):
    root, config, assistant, cron, _ = installation
    status = prepare(installation)
    assistant.acknowledge({**binding(status), "independent_backup_ack": True})
    publish = engine._publish_replacement
    def failed(*args, **kwargs):
        raise storage.IdentityStorageError("interrupted")
    monkeypatch.setattr(engine, "_publish_replacement", failed)
    result = assistant.apply(binding(status), background=False)
    assert result["status"] == "failed" and result["restart_required"]
    with pytest.raises(MigrationRequestError, match="restart_required"):
        assistant.apply(binding(status), background=False)
    before = tree_bytes(root / "data/config")
    restarted = IdentityMigrationAssistant(config, read_cron=lambda: cron[0], write_cron=lambda value: cron.__setitem__(0, value))
    import identity_migration_api
    monkeypatch.setitem(identity_migration_api._ASSISTANTS, str(root / "data"), restarted)
    assert restarted.startup_detection()["required"]
    assert restarted.status()["can_resume"] is True
    assert tree_bytes(root / "data/config") == before
    monkeypatch.setattr(engine, "_publish_replacement", publish)
    assert restarted.apply(binding(status), background=False)["status"] == "applied"


@pytest.mark.parametrize("changed", ["source", "schema", "obsolete"])
def test_external_edit_during_canonical_projection_cannot_replace_captured_inputs(installation, monkeypatch, changed):
    root, _, _, _, _ = installation
    import config_api
    canonical = config_api.canonical_backup_conf_plan
    selected = {"source": root / "data/config/backup.conf", "schema": root / "schema.example",
                "obsolete": root / "data/config/backup.conf.example"}[changed]
    def racing(*args, **kwargs):
        result = canonical(*args, **kwargs)
        with selected.open("a") as handle:
            handle.write("# independent external edit during planning\n")
        return result
    monkeypatch.setattr(config_api, "canonical_backup_conf_plan", racing)
    status = prepare(installation)
    assert status["status"] == "blocked", status
    assert "input_changed" in status["reason_codes"]
    assert not (root / "migration/plan.json").exists()
    assert (root / "data/config/jobs/config_local.json").exists()


@pytest.mark.parametrize("unexpected", ["unrelated.json", ".stage-interrupted", ".assistant-interrupted"])
def test_unknown_initial_private_state_blocks_before_selector_and_uuid_persistence(installation, unexpected):
    root, config, assistant, _, _ = installation
    from migration_barrier import block_writers
    state = root / "migration"
    state.mkdir(mode=0o700)
    (state / unexpected).write_bytes(b"unexplained recovery evidence; preserve these bytes")
    # Real startup has already closed admission before opening the assistant.
    block_writers(config)
    before = tree_bytes(root)
    result = prepare(installation)
    assert result["status"] == "blocked", result
    assert not assistant.selector.exists()
    assert not (state / "plan.json").exists()
    assert tree_bytes(root) == before


@pytest.mark.parametrize("unexpected", ["unexpected.txt", ".stage-interrupted"])
def test_unknown_snapshot_root_members_are_not_ignored_during_verification(installation, unexpected):
    root, _, assistant, _, _ = installation
    status = prepare(installation)
    path = root / "migration/snapshot" / unexpected
    path.write_bytes(b"unexpected protected recovery evidence")
    path.chmod(0o600)
    with pytest.raises(storage.IdentityStorageError, match="snapshot_incomplete"):
        with assistant.snapshot_files(binding(status)):
            pytest.fail("snapshot with unknown members must be blocked")
    assert path.read_bytes() == b"unexpected protected recovery evidence"


IDENTITY_ROUTES = [
    ("GET", "/api/migration/identity/status"),
    ("GET", "/api/migration/identity/snapshot"),
    ("POST", "/api/migration/identity/prepare"),
    ("POST", "/api/migration/identity/acknowledge"),
    ("POST", "/api/migration/identity/apply"),
]


@pytest.mark.parametrize("method,path", IDENTITY_ROUTES)
@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
def test_identity_endpoints_require_admin_even_in_maintenance(method, path, role):
    from test_startup_maintenance_mode import _handler
    from startup_state import set_startup_state, migration_maintenance_state
    config = {}
    set_startup_state(config, migration_maintenance_state())
    handler, errors = _handler(config, method)
    handler._get_current_role = lambda: role
    allowed = handler._authorize_api_request(path, "migration-review")
    assert allowed is (role == "admin")
    if role != "admin":
        assert errors[0][:2] == (403, "forbidden")


@pytest.mark.parametrize("method,path", IDENTITY_ROUTES)
def test_identity_endpoints_are_never_anonymous(method, path):
    from test_startup_maintenance_mode import _handler
    handler, errors = _handler({}, method)
    handler._has_valid_api_token_header = lambda: False
    handler._is_api_authorized = lambda: False
    assert handler._authorize_api_request(path, "migration-review") is False
    assert errors[0][:2] == (401, "unauthorized")


@pytest.mark.parametrize("path", [path for method, path in IDENTITY_ROUTES if method == "POST"])
def test_identity_mutations_keep_same_origin_csrf_gate(path):
    from test_startup_maintenance_mode import _handler
    handler, errors = _handler({}, "POST")
    handler._has_valid_api_token_header = lambda: False
    handler._is_same_origin_request = lambda: False
    assert handler._authorize_api_request(path, "migration-review") is False
    assert errors[0][:2] == (403, "csrf_origin_mismatch")


def _download_handler(assistant):
    from test_startup_maintenance_mode import _handler
    handler, errors = _handler(assistant.config)
    headers, status = {}, []
    handler._identity_assistant = lambda: assistant
    handler._current_request_id = "migration-review"
    handler.wfile = io.BytesIO()
    handler.send_response = status.append
    handler.send_header = lambda name, value: headers.__setitem__(name, value)
    handler.end_headers = lambda: None
    handler._send_refreshed_session_header = lambda: None
    handler.close_connection = False
    return handler, errors, headers, status


def test_protected_http_tar_is_complete_and_has_exact_declared_length(installation):
    _, _, assistant, _, _ = installation
    status = prepare(installation)
    handler, errors, headers, responses = _download_handler(assistant)
    handler._download_identity_snapshot(urlencode(binding(status)))
    raw = handler.wfile.getvalue()
    assert responses == [200] and errors == []
    assert int(headers["Content-Length"]) == len(raw)
    assert headers["Cache-Control"] == "no-store"
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        names = archive.getnames()
        assert {"plan.json", "snapshot/metadata.json", "snapshot/manifest.json"} <= set(names)
        assert all(member.mode == 0o600 for member in archive.getmembers())


def test_midstream_snapshot_change_aborts_with_incomplete_length_and_no_second_response(installation, monkeypatch):
    root, _, assistant, _, _ = installation
    status = prepare(installation)
    handler, errors, headers, responses = _download_handler(assistant)
    sent_headers = []
    handler.end_headers = lambda: sent_headers.append(True)
    blob = next((root / "migration/snapshot/files").iterdir())
    read = storage._read_file
    def changing(path, **kwargs):
        if sent_headers and path == blob:
            blob.write_bytes(b"changed after export verification")
        return read(path, **kwargs)
    monkeypatch.setattr(storage, "_read_file", changing)
    handler._download_identity_snapshot(urlencode(binding(status)))
    assert responses == [200] and errors == []
    assert handler.close_connection is True
    assert len(handler.wfile.getvalue()) < int(headers["Content-Length"])


@pytest.mark.parametrize("mutation,reason", [
    ({"schema_version": 99}, "unsupported_schema"),
    ({"archive_prefixes": ["unsafe*"]}, "invalid_archive_prefix"),
    ({"repository_key": "missing_repository"}, "dangling_repository"),
])
def test_preparation_preserves_safe_actionable_domain_reason(installation, mutation, reason):
    root, _, _, _, _ = installation
    source = root / "data/config/jobs/config_local.json"
    data = json.loads(source.read_text())
    data.update(mutation)
    source.write_text(json.dumps(data))
    result = prepare(installation)
    assert result["status"] == "blocked"
    assert result["reason_codes"] == [reason]
    assert not (root / "migration/plan.json").exists()
