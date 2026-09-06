"""Explicit, durable administrator workflow for immutable job identity (#479).

Only this coordinator starts preparation and application. GET/startup never
allocate persistent IDs, snapshot data, acknowledge, or resume conversion.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import re
import stat
from pathlib import Path
import subprocess
import tarfile
import threading
import uuid

from migrations import identity_storage as storage
from migrations import immutable_job_id_v1 as identity
from migrations.identity_reasons import PLANNING_REASON_CODES

MIGRATION_ID = identity.MIGRATION_ID
_ASSISTANTS = {}
_ASSISTANTS_LOCK = threading.RLock()
REASONS = storage.REASON_CODES | PLANNING_REASON_CODES | {
    "cron_unavailable", "cron_write_failed", "persistent_private_storage_required",
    "migration_operation_failed", "invalid_migration_location", "invalid_assistant_state",
    "incomplete_preparation", "invalid_completion_evidence", "identity_cutover_incomplete",
    "explicit_continuation_required", "restart_required", "original_migration_location_required",
    "existing_preparation_must_be_preserved", "migration_not_applicable", "prepare_required",
    "operation_in_progress", "verified_backup_pause_required", "independent_backup_ack_required",
    "final_verification_failed", "startup_gate_failed", "writers_running", "legacy_workers_running",
    "migration_maintenance", "gate_storage_unavailable", "unsafe_gate_path", "unsafe_gate_state",
    "invalid_gate_state", "startup_validation_required", "migration_in_progress", "unsupported_managed_cron",
}
META_KEYS = {"migration_id", "status", "stage", "reason_codes", "acknowledged", "updated_at", "plan_id", "snapshot_digest"}
STAGES = {"required", "waiting", "preparing", "backup_ready", "acknowledged", "applying", "verifying", "interrupted", "complete"}


class MigrationRequestError(ValueError):
    api_status = 409
    api_code = "identity_migration_blocked"


def _fail(code):
    raise MigrationRequestError(code)


def _root(config):
    path = storage._absolute(config.get("BACKUP_SCRIPTS_DIR") or "/boot/config/borg-backup")
    return path.parent if path.name == "scripts" else path


def _control_root(config):
    return config.get("BORG_UI_CONTROL_ROOT") or os.environ.get("BORG_UI_CONTROL_ROOT") or "/run/borg-backup-ui/jobs"


def _read_cron():
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1 and not result.stdout and (not result.stderr.strip() or "no crontab for" in result.stderr.lower()):
        return ""
    _fail("cron_unavailable")


def _write_cron(text):
    result = subprocess.run(["crontab", "-"], input=text, capture_output=True, text=True, timeout=10)
    if result.returncode:
        _fail("cron_write_failed")


def _render_cron(config, original, plan):
    from migrations.identity_apply import replace_managed_cron
    from schedule_api import schedule_lines
    schedules = next((row["data"] for row in plan["records"].values() if row["kind"] == "schedules"), {})
    return replace_managed_cron(original, schedule_lines(config, schedules, plan["jobs"]))


def _validate_cron_admission(text):
    from migrations.identity_apply import _cron_parts, _BEGIN, _END
    _cron_parts(text)  # Also reject duplicate, malformed or reversed markers.
    if _BEGIN not in text:
        return
    block = text.split(_BEGIN + "\n", 1)[1].split(_END, 1)[0]
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # Previous shipped schedules call the guarded localhost HTTP boundary.
        # Direct legacy scripts cannot be made safe by observing current PIDs.
        if ("curl " not in line or not re.search(r"http://127\.0\.0\.1:[0-9]+/api/(jobs/run|restore-tests/run)", line)
                or any(name in line for name in ("wizard_runner.py", "borg_backup_", "borg_restore_test.sh"))):
            _fail("unsupported_managed_cron")


def _canonical_plan(config, plan):
    """Include earlier automatic config rewrites in the approved byte snapshot."""
    from config_api import canonical_backup_conf_plan, get_backup_conf_schema_file
    # The schema is a version-owned input; changing installed code invalidates consent.
    plan = json.loads(json.dumps(plan))
    plan.pop("plan_id", None)
    source = str(_root(config) / "config/backup.conf")
    schema = str(get_backup_conf_schema_file(config))
    obsolete = str(_root(config) / "config/backup.conf.example")
    source_fingerprint, source_raw = storage.read_fingerprinted_file(source)
    if source_fingerprint != plan["inputs"][source]:
        _fail("input_changed")
    for path in (schema, obsolete):
        fingerprint = storage.fingerprint_file(path)
        if path in plan["inputs"] and plan["inputs"][path] != fingerprint:
            _fail("input_changed")
        plan["inputs"][path] = fingerprint
    canonical = canonical_backup_conf_plan(config, source_content=(source_raw or b"").decode("utf-8"))
    for path in (source, schema, obsolete):
        if storage.fingerprint_file(path) != plan["inputs"][path]:
            _fail("input_changed")
    if canonical["changed"] or plan["inputs"][obsolete]["exists"]:
        raw = canonical["content"].encode("utf-8")
        action = {"kind": "write_bytes", "source": source, "target": source,
                  "text": canonical["content"], "after": {"exists": True, "size": len(raw),
                  "sha256": hashlib.sha256(raw).hexdigest(), "mode": plan["inputs"][source].get("mode", 0o600)}}
        action["id"] = hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()
        plan["actions"].append(action)
        if plan["inputs"][obsolete]["exists"]:
            action = {"kind": "retire_auxiliary", "source": obsolete, "target": source}
            action["id"] = hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()
            plan["actions"].append(action)
    return storage.seal_plan(plan)


def _safe_code(exc):
    # Never include exception messages, paths, config values or subprocess stderr.
    code = getattr(exc, "code", "") or getattr(exc, "reason", "")
    if isinstance(exc, MigrationRequestError):
        code = str(exc)
    return code if isinstance(code, str) and code in REASONS else "migration_operation_failed"


def _write_meta(path, value):
    """Private atomic replacement, anchored to the already validated directory."""
    storage._private_directory(path.parent)
    storage._read_file(path, private=True)
    raw = storage._canonical(value)
    with storage._directory(path.parent) as parent:
        name = ".assistant-" + uuid.uuid4().hex
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(name, dir_fd=parent)
            except FileNotFoundError:
                pass


class IdentityMigrationAssistant:
    def __init__(self, config, *, read_cron=None, write_cron=None, activate=None):
        self.config = config
        self.read_cron = read_cron or _read_cron
        self.write_cron = write_cron or _write_cron
        self.activate = activate
        self._operation = threading.Lock()
        self._view_lock = threading.RLock()
        self._busy = False
        self._failed_here = False
        self._view = {"status": "pending", "stage": "required", "reason_codes": []}
        self._snapshot_view = None
        self._snapshot_signature = None

    @property
    def selector(self):
        return _root(self.config) / ".identity-migration-location.json"

    def _state_dir(self):
        fingerprint, raw = storage.read_fingerprinted_file(self.selector)
        if not fingerprint["exists"]:
            return None
        try:
            value = json.loads(raw, object_pairs_hook=storage._unique_json_pairs)
            if set(value) != {"migration_id", "state_dir"} or value["migration_id"] != MIGRATION_ID:
                _fail("invalid_migration_location")
            return self._validate_location(value["state_dir"])
        except (TypeError, ValueError):
            _fail("invalid_migration_location")

    def _validate_location(self, value):
        path = storage._absolute(value)
        # Recovery is persistent, never /run, /tmp, /boot FAT, or a symlink.
        if len(path.parts) < 2 or path.parts[1] in {"tmp", "run", "dev", "proc", "sys", "boot"}:
            _fail("persistent_private_storage_required")
        identity._path(str(path))  # mounted /mnt roots and all existing ancestors
        with storage._directory(path.parent):
            pass
        return path

    def _validate_state_layout(self, state):
        allowed = {"assistant.json", "plan.json", "journal.jsonl", "snapshot", ".capability-probe"}
        names = set(p.name for p in state.iterdir())
        extra = names - allowed
        if extra:
            if not storage.fingerprint_file(state / "plan.json")["exists"]:
                _fail("invalid_assistant_state")
            journal = storage.read_journal(state)
            started = any(row["phase"] in {"apply", "commit"} for row in journal)
            meta = self._meta(state)
            authorized_preflight = bool(meta and meta.get("acknowledged") and meta["stage"] in {"applying", "verifying", "interrupted"}
                                        and any(row["phase"] == "confirm" and row["status"] == "applied" for row in journal))
            if not started and (not authorized_preflight or extra - {"apply-roots.json", "apply-cron.json"}):
                _fail("invalid_assistant_state")
            if any(name not in {"apply-roots.json", "apply-cron.json"} and not re.fullmatch(r"directory-[0-9a-f]{64}\.json", name) for name in extra):
                _fail("invalid_assistant_state")
        for name in names - {"snapshot"}:
            storage._read_file(state / name, private=True)

    def _meta(self, state):
        fp, raw = storage._read_file(state / "assistant.json", private=True)
        if not fp["exists"]:
            return None
        try:
            meta = json.loads(raw, object_pairs_hook=storage._unique_json_pairs)
            if (not isinstance(meta, dict) or meta.get("migration_id") != MIGRATION_ID
                    or meta.get("stage") not in STAGES
                    or meta.get("status") not in {"pending", "blocked", "failed", "applied"}
                    or type(meta.get("acknowledged")) is not bool
                    or not isinstance(meta.get("reason_codes"), list)):
                _fail("invalid_assistant_state")
            if (set(meta) - META_KEYS or any(not isinstance(code, str) or code not in REASONS for code in meta["reason_codes"])
                    or not isinstance(meta.get("updated_at"), str)):
                _fail("invalid_assistant_state")
            datetime.fromisoformat(meta["updated_at"])
            for key in ("plan_id", "snapshot_digest"):
                if key in meta and (not isinstance(meta[key], str) or not re.fullmatch(r"[0-9a-f]{64}", meta[key])):
                    _fail("invalid_assistant_state")
            if meta["acknowledged"] and not all(key in meta for key in ("plan_id", "snapshot_digest")):
                _fail("invalid_assistant_state")
            return meta
        except (ValueError, TypeError):
            _fail("invalid_assistant_state")

    def _save(self, state, **changes):
        meta = self._meta(state) or {"migration_id": MIGRATION_ID, "status": "pending", "stage": "required",
                                  "reason_codes": [], "acknowledged": False}
        meta.update(changes)
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_meta(state / "assistant.json", meta)
        with self._view_lock:
            self._view = dict(meta)
        return meta

    def _snapshot(self, state, plan):
        manifest = storage._read_json(state / "snapshot/manifest.json")
        handle = {"path": str(state / "snapshot"), "plan_id": plan["plan_id"], "digest": storage._digest(manifest)}
        return handle, storage.verify_snapshot(plan, handle)

    def _snapshot_stat_signature(self, state, manifest):
        # A cheap change detector avoids rehashing every blob on each UI poll.
        # Full verification is still mandatory for every exported/approved copy.
        blobs = state / "snapshot/files"
        names = {e["blob"] for e in manifest["entries"].values() if e["blob"]}
        names.update(e["blob"] for e in manifest["external_inputs"].values())
        with storage._directory(blobs) as directory:
            if set(os.listdir(directory)) != names:
                _fail("snapshot_changed")
        paths = [state / "plan.json", state / "snapshot/metadata.json", state / "snapshot/manifest.json"]
        paths.extend(blobs / name for name in sorted(names))
        result = []
        for path in paths:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                _fail("unsafe_path")
            result.append((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode))
        return result

    def startup_detection(self):
        """Read only, including on failed/interrupted attempts; never resumes."""
        try:
            state = self._state_dir()
            if state:
                self._validate_state_layout(state)
                if not storage.fingerprint_file(state / "plan.json")["exists"]:
                    if set(p.name for p in state.iterdir()) - {"assistant.json", ".capability-probe"}:
                        _fail("invalid_assistant_state")
                    self._view = {"status": "pending", "stage": "interrupted", "reason_codes": ["incomplete_preparation"]}
                    return {"required": True, "status": "pending", "reasons": ["incomplete_preparation"]}
                plan = storage.load_plan(state)
                journal = storage.read_journal(state)
                meta = self._meta(state)
                if meta is None:
                    self._view = {"status": "pending", "stage": "interrupted", "reason_codes": ["incomplete_preparation"]}
                    return {"required": True, "status": "pending", "reasons": ["incomplete_preparation"]}
                if meta.get("stage") == "complete":
                    if not journal or journal[-1]["phase"] != "commit" or journal[-1]["status"] != "applied":
                        _fail("invalid_completion_evidence")
                    result = identity.verify_active_target(self.config, control_root=_control_root(self.config))
                    if result.get("valid") is not True:
                        _fail(next((row["code"] for row in result.get("reasons", []) if row.get("code") in REASONS), "identity_cutover_incomplete"))
                    self._view = {**meta, "status": "applied", "stage": "complete"}
                    return {"required": False, "status": "applied", "reasons": []}
                self._view = dict(meta)
                if meta["stage"] in {"preparing", "applying", "verifying"} or meta["status"] == "failed":
                    self._view.update(stage="interrupted", status="pending", reason_codes=["explicit_continuation_required"])
                return {"required": True, "status": self._view["status"], "reasons": self._view.get("reason_codes", [])}
            detected = identity.detect(self.config, control_root=_control_root(self.config))
            if not detected["required"]:
                verified = identity.verify_active_target(self.config, control_root=_control_root(self.config))
                if verified.get("valid") is not True:
                    _fail("identity_cutover_incomplete")
            self._view = {"status": detected["status"], "stage": "required" if detected["required"] else "complete",
                          "reason_codes": [r["code"] for r in detected["reasons"]]}
            return detected
        except Exception as exc:
            code = _safe_code(exc)
            self._view = {"status": "blocked", "stage": "waiting" if code in {"writers_not_quiescent", "writers_active", "storage_unavailable"} else "required", "reason_codes": [code]}
            return {"required": True, "status": "blocked", "reasons": [code]}

    def status(self):
        with self._view_lock:
            result = dict(self._view)
        result.update(migration_id=MIGRATION_ID, busy=self._busy, restart_required=self._failed_here,
                      can_resume=False, can_prepare=not self._busy and not self._failed_here, suggested_state_dir=str(_root(self.config) / ".identity-migration-v1"))
        try:
            state = self._state_dir()
            if state:
                result["state_dir"] = str(state)
                if not storage.fingerprint_file(state / "plan.json")["exists"]:
                    return result
                plan = storage.load_plan(state)
                result["plan_id"] = plan["plan_id"]
                journal = storage.read_journal(state)
                completed = {a for row in journal if row["phase"] == "apply" and row["status"] == "applied" for a in row["action_ids"]}
                result["progress"] = {"completed": len(completed), "total": len(plan["actions"])}
                if (state / "snapshot/manifest.json").exists():
                    if (self._snapshot_view is None or self._snapshot_stat_signature(state, self._snapshot_view[1]) != self._snapshot_signature):
                        self._snapshot_view = self._snapshot(state, plan)
                        self._snapshot_signature = self._snapshot_stat_signature(state, self._snapshot_view[1])
                    snapshot, manifest = self._snapshot_view
                    result["snapshot_digest"] = snapshot["digest"]
                    result["snapshot"] = {"path": snapshot["path"], "created_at": manifest["created_at"],
                        "size_bytes": sum(e["original"].get("size", 0) for e in manifest["entries"].values())
                            + sum(e["size"] for e in manifest["external_inputs"].values()), "verified": True}
                    meta = self._meta(state)
                    result["can_prepare"] = bool(not self._busy and not self._failed_here and meta
                        and not meta.get("acknowledged") and meta["stage"] in {"preparing", "interrupted", "required", "waiting"})
                    result["can_resume"] = bool(not self._busy and not self._failed_here and meta
                        and meta.get("acknowledged") is True and result["stage"] == "interrupted")
        except Exception as exc:
            result.update(status="blocked", reason_codes=[_safe_code(exc)], can_resume=False, can_prepare=False)
        return result

    def _launch(self, fn, *, background=True):
        if not self._operation.acquire(blocking=False):
            return self.status()
        self._busy = True
        def run():
            try:
                fn()
            finally:
                self._busy = False
                self._operation.release()
        if background:
            threading.Thread(target=run, name="identity-migration", daemon=True).start()
        else:
            run()
        return self.status()

    def prepare(self, body, *, background=True):
        if self._failed_here:
            _fail("restart_required")
        requested = body.get("state_dir") or str(_root(self.config) / ".identity-migration-v1")
        state = self._state_dir()
        if state and str(state) != requested:
            _fail("original_migration_location_required")
        if state:
            meta = self._meta(state)
            if meta and (meta.get("acknowledged") or meta["stage"] in {"backup_ready", "complete"}):
                _fail("existing_preparation_must_be_preserved")
        return self._launch(lambda: self._prepare(requested), background=background)

    def _prepare(self, requested):
        from migration_barrier import block_writers, exclusive_migration
        state = None
        try:
            block_writers(self.config)
            with exclusive_migration(self.config):
                existing = self._state_dir()
                initial_plan = None
                if existing is None:
                    cron_text = self.read_cron()
                    _validate_cron_admission(cron_text)
                    initial_plan = identity.build_plan(self.config, control_root=_control_root(self.config), cron_text=cron_text)
                    if initial_plan["classification"] != "applicable":
                        _fail("migration_not_applicable" if not initial_plan["required"] else next((row["code"] for row in initial_plan.get("reasons", []) if row.get("code") in REASONS), "invalid_plan"))
                state = self._validate_location(requested)
                storage._private_directory(state, create=True)
                self._validate_state_layout(state)
                # Verify private durable publication semantics before allocating UUIDs.
                probe = state / ".capability-probe"
                storage._publish_once(probe, b"identity-migration-storage-v1\n")
                with storage._directory(state) as directory:
                    os.unlink(probe.name, dir_fd=directory)
                    os.fsync(directory)
                existing = self._state_dir()
                if existing is None:
                    # The nonsensitive fixed selector is persisted BEFORE the ID map.
                    with storage._directory(self.selector.parent) as parent:
                        fd = os.open(self.selector.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                        with os.fdopen(fd, "wb") as handle:
                            handle.write(storage._canonical({"migration_id": MIGRATION_ID, "state_dir": str(state)}))
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.fsync(parent)
                elif existing != state:
                    _fail("original_migration_location_required")
                meta = self._meta(state)
                if meta and meta["stage"] in {"backup_ready", "acknowledged", "applying", "verifying", "complete"}:
                    _fail("existing_preparation_must_be_preserved")
                self._save(state, stage="preparing", status="pending", reason_codes=[], acknowledged=False)
                if storage.fingerprint_file(state / "plan.json")["exists"]:
                    plan = storage.load_plan(state)
                    if any(row["phase"] in {"apply", "commit"} for row in storage.read_journal(state)):
                        _fail("explicit_continuation_required")
                    storage.verify_inputs(plan)
                    if self.read_cron() != plan["external_inputs"]["managed_cron"]["text"]:
                        _fail("input_changed")
                else:
                    if initial_plan is None:
                        cron_text = self.read_cron()
                        _validate_cron_admission(cron_text)
                        initial_plan = identity.build_plan(self.config, control_root=_control_root(self.config), cron_text=cron_text)
                    plan = initial_plan
                    if plan["classification"] != "applicable":
                        _fail(plan.get("reasons", [{}])[0].get("code", "migration_not_applicable") if plan.get("reasons") else "migration_not_applicable")
                    plan = _canonical_plan(self.config, plan)
                    storage.persist_plan(plan, state)
                    storage.append_journal(state, plan, "pending", "plan")
                snapshot = storage.create_snapshot(plan, state)
                self._snapshot_view = self._snapshot(state, plan)
                self._snapshot_signature = self._snapshot_stat_signature(state, self._snapshot_view[1])
                storage.append_journal(state, plan, "applied", "snapshot")
                self._save(state, stage="backup_ready", plan_id=plan["plan_id"], snapshot_digest=snapshot["digest"], reason_codes=[])
        except Exception as exc:
            code = _safe_code(exc)
            self._view = {"status": "blocked", "stage": "waiting" if code in {"writers_active", "writers_running", "legacy_workers_running"} else "required", "reason_codes": [code]}
            if state and (state / "assistant.json").is_file():
                self._save(state, **self._view)

    def _binding(self, body):
        state = self._state_dir()
        if state is None:
            _fail("prepare_required")
        plan = storage.load_plan(state)
        try:
            snapshot, manifest = self._snapshot(state, plan)
        except Exception as exc:
            self._snapshot_view = None
            self._view.update(status="blocked", reason_codes=[_safe_code(exc)])
            raise
        if body.get("plan_id") != plan["plan_id"] or body.get("snapshot_digest") != snapshot["digest"]:
            _fail("approval_required")
        return state, plan, snapshot, manifest

    def acknowledge(self, body):
        from migration_barrier import exclusive_migration
        if not self._operation.acquire(blocking=False):
            _fail("operation_in_progress")
        try:
            with exclusive_migration(self.config):
                return self._acknowledge(body)
        finally:
            self._operation.release()

    def _acknowledge(self, body):
        if self._busy:
            _fail("operation_in_progress")
        state, plan, snapshot, _ = self._binding(body)
        meta = self._meta(state)
        if not meta or meta["stage"] not in {"backup_ready", "acknowledged"}:
            _fail("verified_backup_pause_required")
        if body.get("independent_backup_ack") is not True:
            _fail("independent_backup_ack_required")
        storage.verify_inputs(plan)
        if self.read_cron() != plan["external_inputs"]["managed_cron"]["text"]:
            _fail("input_changed")
        storage.append_journal(state, plan, "applied", "confirm")
        self._save(state, stage="acknowledged", acknowledged=True)
        return self.status()

    def apply(self, body, *, background=True):
        if self._failed_here:
            _fail("restart_required")
        if self._busy:
            return self.status()
        state, plan, snapshot, _ = self._binding(body)
        meta = self._meta(state)
        if not meta or meta.get("acknowledged") is not True or meta["stage"] not in {"acknowledged", "applying", "verifying", "interrupted"}:
            _fail("independent_backup_ack_required")
        approval = {"approved": True, "independent_backup_acknowledged": True,
                    "plan_id": plan["plan_id"], "snapshot_digest": snapshot["digest"]}
        return self._launch(lambda: self._apply(state, approval), background=background)

    def _apply(self, state, approval):
        from migration_barrier import exclusive_migration, clear_block, quiescence_held, block_writers
        from migrations.identity_apply import apply_plan
        try:
            with exclusive_migration(self.config):
                meta = self._meta(state)
                if not meta or not meta.get("acknowledged") or meta.get("plan_id") != approval["plan_id"] or meta.get("snapshot_digest") != approval["snapshot_digest"]:
                    _fail("approval_required")
                self._save(state, stage="applying", status="pending", reason_codes=[])
                result = apply_plan(self.config, state, approval=approval, quiescence_callback=lambda: quiescence_held(self.config),
                    read_cron=self.read_cron, write_cron=self.write_cron,
                    render_cron=lambda original, plan: _render_cron(self.config, original, plan),
                    control_root=_control_root(self.config))
                if result.get("status") != "applied":
                    _fail("final_verification_failed")
                self._save(state, stage="verifying")
                # The registry still validates all remaining migrations before release.
                from migrations.registry import run_startup_migrations
                self._save(state, stage="complete", status="applied")
                summary = run_startup_migrations(self.config)
                if summary.get("status") != "ok":
                    _fail("startup_gate_failed")
                from startup_state import set_startup_state, normal_startup_state
                set_startup_state(self.config, normal_startup_state(summary))
                clear_block(self.config)
            if self.activate:
                self.activate(self.config)
        except Exception as exc:
            self._failed_here = True
            block_writers(self.config)
            meta = self._meta(state) or {}
            self._save(state, status="failed", stage="complete" if meta.get("stage") == "complete" else "interrupted", reason_codes=[_safe_code(exc)])
            from startup_state import set_startup_state, migration_maintenance_state
            set_startup_state(self.config, migration_maintenance_state({"failed": [MIGRATION_ID]}))

    @contextmanager
    def snapshot_files(self, body):
        """Exact protected export set; caller streams it without public staging."""
        state, plan, snapshot, manifest = self._binding(body)
        files = [("plan.json", state / "plan.json"), ("snapshot/metadata.json", state / "snapshot/metadata.json"),
                 ("snapshot/manifest.json", state / "snapshot/manifest.json")]
        names = {e["blob"] for e in manifest["entries"].values() if e["blob"]}
        names.update(e["blob"] for e in manifest["external_inputs"].values())
        files.extend(("snapshot/files/" + name, state / "snapshot/files" / name) for name in sorted(names))
        # Fixed short ASCII member names permit a deterministic USTAR stream.
        def expected_bytes(raw):
            return {"exists": True, "size": len(raw), "mode": 0o600, "sha256": hashlib.sha256(raw).hexdigest()}
        metadata = {key: manifest[key] for key in ("schema_version", "migration_id", "plan_id", "created_at")}
        expected = {"plan.json": expected_bytes(storage._canonical(plan)),
                    "snapshot/metadata.json": expected_bytes(storage._canonical(metadata)),
                    "snapshot/manifest.json": expected_bytes(storage._canonical(manifest))}
        for entry in manifest["entries"].values():
            if entry["blob"]:
                expected["snapshot/files/" + entry["blob"]] = {**entry["original"], "mode": 0o600}
        for entry in manifest["external_inputs"].values():
            expected["snapshot/files/" + entry["blob"]] = {"exists": True, "mode": 0o600, "size": entry["size"], "sha256": entry["sha256"]}
        members = [(name, path, expected[name]) for name, path in files]
        size = sum(512 + ((fp["size"] + 511) // 512) * 512 for _, _, fp in members) + 1024
        size = ((size + tarfile.RECORDSIZE - 1) // tarfile.RECORDSIZE) * tarfile.RECORDSIZE
        yield {"members": members, "size_bytes": size}


def get_assistant(config):
    key = str(_root(config))
    with _ASSISTANTS_LOCK:
        if key not in _ASSISTANTS:
            _ASSISTANTS[key] = IdentityMigrationAssistant(config)
        return _ASSISTANTS[key]
