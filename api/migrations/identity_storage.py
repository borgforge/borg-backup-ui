"""Private, inactive planning/snapshot primitives for #472.

Nothing in this module rewrites installation data, invokes Borg, registers a
migration, or starts workers. The caller must supply an exact allowlisted plan
and a dedicated state directory on a persistent filesystem supporting private
0700/0600 permissions and hard links (normally not the Unraid FAT /boot USB).
A verified snapshot is not an apply engine,
a downloadable support bundle, or proof of an independent external backup.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Callable
import uuid


MIGRATION_ID = "immutable_job_id_v1"
STATUSES = frozenset({"pending", "applied", "skipped", "failed", "blocked", "not_applicable"})
PHASES = frozenset({"detect", "plan", "snapshot", "verify", "confirm", "apply", "resume", "commit"})
REASON_CODES = frozenset({
    "approval_required", "input_changed", "inventory_changed", "invalid_plan",
    "invalid_snapshot", "snapshot_incomplete", "snapshot_changed", "unsafe_path",
    "state_conflict", "invalid_journal", "storage_unavailable", "insufficient_space",
    "writers_active", "verification_failed", "interrupted", "not_applicable",
    "state_filesystem_unsupported",
})
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class IdentityStorageError(RuntimeError):
    """Stable error codes only: never expose filesystem exception/secret text."""

    def __init__(self, code: str):
        self.code = code if isinstance(code, str) and code in REASON_CODES else "verification_failed"
        super().__init__(self.code)


def _fail(code: str):
    raise IdentityStorageError(code) from None


def _canonical(value) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        _fail("invalid_plan")


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _absolute(path) -> Path:
    try:
        raw = os.fspath(path)
    except TypeError:
        _fail("unsafe_path")
    if not isinstance(raw, str) or not raw.startswith("/") or "\x00" in raw:
        _fail("unsafe_path")
    if raw != os.path.normpath(raw) or raw.startswith("//"):
        _fail("unsafe_path")
    try:
        raw.encode("utf-8")
    except UnicodeError:
        _fail("unsafe_path")
    return Path(raw)


def _os_error(exc: OSError):
    _fail("insufficient_space" if exc.errno == errno.ENOSPC else
          "unsafe_path" if exc.errno in {errno.ELOOP, errno.ENOTDIR} else "storage_unavailable")


@contextmanager
def _directory(path, *, missing_ok=False):
    """Walk using directory FDs; never follow even an intermediate symlink."""
    path = _absolute(path)
    fd = None
    try:
        fd = os.open("/", os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
        for component in path.parts[1:]:
            try:
                child = os.open(component, os.O_RDONLY | _DIRECTORY | _NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if missing_ok:
                    os.close(fd)
                    fd = None
                    yield None
                    return
                raise
            os.close(fd)
            fd = child
        yield fd
    except IdentityStorageError:
        raise
    except OSError as exc:
        _os_error(exc)
    finally:
        if fd is not None:
            os.close(fd)


def _read_file(path, *, private=False):
    path = _absolute(path)
    with _directory(path.parent, missing_ok=True) as directory:
        if directory is None:
            return {"exists": False}, None
        fd = None
        try:
            try:
                fd = os.open(path.name, os.O_RDONLY | _NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            except FileNotFoundError:
                return {"exists": False}, None
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                _fail("unsafe_path")
            if private and (stat.S_IMODE(before.st_mode) != 0o600
                            or before.st_uid != os.getuid() or before.st_nlink != 1):
                _fail("unsafe_path")
            chunks = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(fd)
            identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                                     info.st_mtime_ns, info.st_ctime_ns, info.st_mode)
            if identity(before) != identity(after):
                _fail("input_changed")
            content = b"".join(chunks)
            if len(content) != before.st_size:
                _fail("input_changed")
            return {"exists": True, "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "mode": stat.S_IMODE(before.st_mode)}, content
        except IdentityStorageError:
            raise
        except OSError as exc:
            _os_error(exc)
        finally:
            if fd is not None:
                os.close(fd)


def fingerprint_file(path) -> dict:
    """Read exact regular-file bytes; absent destinations are explicit."""
    return _read_file(path)[0]


def read_fingerprinted_file(path):
    """Return one stable descriptor read: ``(fingerprint, bytes_or_None)``."""
    return _read_file(path)


def read_file(path) -> bytes:
    """Read a required regular file without following any symlink component."""
    fingerprint, content = _read_file(path)
    if not fingerprint["exists"]:
        _fail("storage_unavailable")
    return content


def inventory_group(path, suffixes) -> dict:
    """Capture an immediate allowlist, including an absent directory itself.

    No recursive scan is performed. Matching non-files/symlinks are rejected,
    not silently hidden. Directory identity detects replaced/missing mounts.
    """
    path = _absolute(path)
    if path == Path("/") or not isinstance(suffixes, (list, tuple)) or not suffixes:
        _fail("unsafe_path")
    if any(not isinstance(item, str) or not item.startswith(".")
           or "/" in item or "\\" in item or len(item) > 32 for item in suffixes):
        _fail("unsafe_path")
    suffixes = sorted(set(suffixes))
    with _directory(path, missing_ok=True) as directory:
        if directory is None:
            return {"path": str(path), "suffixes": suffixes, "exists": False, "entries": []}
        before = os.fstat(directory)
        names = sorted(name for name in os.listdir(directory) if name.endswith(tuple(suffixes)))
        for name in names:
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                _fail("unsafe_path")
        after = os.fstat(directory)
        if (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
            _fail("inventory_changed")
        return {"path": str(path), "suffixes": suffixes, "exists": True,
                "device": before.st_dev, "inode": before.st_ino, "entries": names}


def inventory_directories(path) -> dict:
    """Capture a bounded directory-only control root, not a recursive tree.

    Every child must be a real directory. Callers inventory the allowed files
    inside each child separately, so an added run directory invalidates a plan.
    """
    path = _absolute(path)
    if path == Path("/"):
        _fail("unsafe_path")
    with _directory(path, missing_ok=True) as directory:
        if directory is None:
            return {"path": str(path), "kind": "directories", "exists": False, "entries": []}
        before = os.fstat(directory)
        names = sorted(os.listdir(directory))
        for name in names:
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                _fail("unsafe_path")
        after = os.fstat(directory)
        if (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
            _fail("inventory_changed")
        return {"path": str(path), "kind": "directories", "exists": True,
                "device": before.st_dev, "inode": before.st_ino, "entries": names}


def _valid_fingerprint(value):
    if not isinstance(value, dict) or type(value.get("exists")) is not bool:
        _fail("invalid_plan")
    if not value["exists"]:
        if value != {"exists": False}:
            _fail("invalid_plan")
        return
    if set(value) != {"exists", "size", "sha256", "mode"}:
        _fail("invalid_plan")
    if type(value["size"]) is not int or value["size"] < 0:
        _fail("invalid_plan")
    if type(value["mode"]) is not int or not 0 <= value["mode"] <= 0o7777:
        _fail("invalid_plan")
    checksum = value["sha256"]
    if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        _fail("invalid_plan")


def seal_plan(plan: dict) -> dict:
    """Validate structural storage boundaries and hash the complete plan.

    Domain/referential validation belongs to the planner. Multiple aliases may
    deliberately map to the same UUID. No UUID is allocated by this module.
    """
    if not isinstance(plan, dict):
        _fail("invalid_plan")
    result = json.loads(_canonical(plan))
    claimed = result.pop("plan_id", None)
    if type(result.get("schema_version")) is not int or result["schema_version"] != 1:
        _fail("invalid_plan")
    if result.get("migration_id") != MIGRATION_ID or not isinstance(result.get("id_map"), dict):
        _fail("invalid_plan")
    for alias, identity in result["id_map"].items():
        if not isinstance(alias, str) or not alias or not isinstance(identity, str):
            _fail("invalid_plan")
        try:
            value = uuid.UUID(identity)
        except (ValueError, AttributeError):
            _fail("invalid_plan")
        if str(value) != identity or value.version != 4 or value.variant != uuid.RFC_4122:
            _fail("invalid_plan")
    inputs = result.get("inputs")
    if not isinstance(inputs, dict):
        _fail("invalid_plan")
    for path, value in inputs.items():
        _absolute(path)
        _valid_fingerprint(value)
    external = result.get("external_inputs", {})
    if not isinstance(external, dict):
        _fail("invalid_plan")
    for name, item in external.items():
        if (not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name)
                or not isinstance(item, dict) or set(item) != {"text", "kind"}
                or not isinstance(item["text"], str) or item["kind"] != "crontab"):
            _fail("invalid_plan")
        try:
            item["text"].encode("utf-8")
        except UnicodeError:
            _fail("invalid_plan")
    groups = result.get("inventory_groups", [])
    if not isinstance(groups, list):
        _fail("invalid_plan")
    seen_roots = set()
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("entries"), list):
            _fail("invalid_plan")
        path = _absolute(group.get("path"))
        suffixes = group.get("suffixes")
        directory_group = group.get("kind") == "directories"
        if (not directory_group and (not isinstance(suffixes, list) or not suffixes)
                or type(group.get("exists")) is not bool):
            _fail("invalid_plan")
        if str(path) in seen_roots:
            _fail("invalid_plan")
        seen_roots.add(str(path))
        for name in group["entries"]:
            if not isinstance(name, str) or not name or name in {".", ".."} or "/" in name or "\\" in name:
                _fail("invalid_plan")
            if not directory_group and str(path / name) not in inputs:
                _fail("invalid_plan")
    actions = result.get("actions", [])
    if not isinstance(actions, list):
        _fail("invalid_plan")
    action_ids = set()
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("id"), str) or not action["id"]:
            _fail("invalid_plan")
        if action["id"] in action_ids:
            _fail("invalid_plan")
        action_ids.add(action["id"])
        for field in ("source", "target"):
            if action.get(field) is not None and str(_absolute(action[field])) not in inputs:
                _fail("invalid_plan")
    digest = _digest(result)
    if claimed is not None and claimed != digest:
        _fail("invalid_plan")
    result["plan_id"] = digest
    return result


def _check_overlap(plan, state_dir):
    state_dir = _absolute(state_dir)
    for name in plan["inputs"]:
        path = _absolute(name)
        if path == state_dir or state_dir in path.parents or path in state_dir.parents:
            _fail("unsafe_path")
    for group in plan.get("inventory_groups", []):
        path = _absolute(group["path"])
        # A dedicated migration directory can be below config, but never below
        # one of the exact scanned jobs/status/restore-test directories.
        if state_dir == path or path in state_dir.parents or state_dir in path.parents:
            _fail("unsafe_path")


def _private_directory(path, *, create=False):
    path = _absolute(path)
    if create:
        with _directory(path.parent) as parent:
            try:
                os.mkdir(path.name, mode=0o700, dir_fd=parent)
                os.fsync(parent)
            except FileExistsError:
                pass
            except OSError as exc:
                _os_error(exc)
    with _directory(path) as directory:
        info = os.fstat(directory)
        if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid():
            _fail("unsafe_path")
    return path


def _publish_once(path: Path, content: bytes):
    """Durable publication without overwriting an existing pathname."""
    with _directory(path.parent) as directory:
        temporary = ".stage-" + uuid.uuid4().hex
        fd = None
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
                         0o600, dir_fd=directory)
            view = memoryview(content)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    _fail("storage_unavailable")
                view = view[written:]
            os.fsync(fd)
            os.close(fd)
            fd = None
            try:
                os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory,
                        follow_symlinks=False)
            except FileExistsError:
                existing, raw = _read_file(path, private=True)
                if not existing["exists"] or raw != content:
                    _fail("state_conflict")
            except OSError as exc:
                if exc.errno in {errno.EOPNOTSUPP, errno.ENOSYS, errno.EXDEV, errno.EPERM}:
                    _fail("state_filesystem_unsupported")
                raise
            os.unlink(temporary, dir_fd=directory)
            temporary = None
            os.fsync(directory)
        except IdentityStorageError:
            raise
        except OSError as exc:
            _os_error(exc)
        finally:
            if fd is not None:
                os.close(fd)
            if temporary is not None:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except OSError:
                    pass


def _read_json(path):
    exists, raw = _read_file(path, private=True)
    if not exists["exists"]:
        _fail("snapshot_incomplete")
    try:
        return json.loads(raw, object_pairs_hook=_unique_json_pairs)
    except (ValueError, UnicodeError):
        _fail("state_conflict")


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_plan(state_dir) -> dict:
    """Read/validate the persisted allocation before considering a retry."""
    state_dir = _private_directory(state_dir)
    result = seal_plan(_read_json(state_dir / "plan.json"))
    _check_overlap(result, state_dir)
    return result


def persist_plan(plan: dict, state_dir) -> dict:
    plan = seal_plan(plan)
    _check_overlap(plan, state_dir)
    state_dir = _private_directory(state_dir, create=True)
    _publish_once(state_dir / "plan.json", _canonical(plan))
    persisted = load_plan(state_dir)
    if persisted != plan:
        _fail("state_conflict")
    return persisted


def verify_inputs(plan: dict):
    plan = seal_plan(plan)
    for path, expected in plan["inputs"].items():
        if fingerprint_file(path) != expected:
            _fail("input_changed")
    for expected in plan.get("inventory_groups", []):
        current = (inventory_directories(expected["path"]) if expected.get("kind") == "directories"
                   else inventory_group(expected["path"], expected["suffixes"]))
        if current != expected:
            _fail("inventory_changed")
    return True


def _snapshot_metadata(plan, snapshot, *, create=False):
    """Persist creation identity once, including across interrupted copies.

    The timestamp is separate from the pre-existing sealed plan: snapshot
    creation never silently changes that plan's digest or UUID allocation.
    """
    path = snapshot / "metadata.json"
    fingerprint, _ = _read_file(path, private=True)
    if not fingerprint["exists"]:
        if not create:
            _fail("snapshot_incomplete")
        # Once copying/commit has begun, a missing header is lost evidence,
        # not permission to assign a fresh creation time to existing bytes.
        if fingerprint_file(snapshot / "manifest.json")["exists"]:
            _fail("snapshot_incomplete")
        with _directory(snapshot / "files") as directory:
            if os.listdir(directory):
                _fail("snapshot_incomplete")
        metadata = {"schema_version": 1, "migration_id": MIGRATION_ID,
                    "plan_id": plan["plan_id"],
                    "created_at": datetime.now(timezone.utc).isoformat()}
        _publish_once(path, _canonical(metadata))
    metadata = _read_json(path)
    if not isinstance(metadata, dict) or not isinstance(metadata.get("created_at"), str):
        _fail("invalid_snapshot")
    try:
        timestamp = datetime.fromisoformat(metadata["created_at"])
    except (ValueError, TypeError):
        _fail("invalid_snapshot")
    if timestamp.tzinfo != timezone.utc or timestamp.isoformat() != metadata["created_at"]:
        _fail("invalid_snapshot")
    expected = {"schema_version": 1, "migration_id": MIGRATION_ID,
                "plan_id": plan["plan_id"], "created_at": metadata["created_at"]}
    if _canonical(metadata) != _canonical(expected):
        _fail("invalid_snapshot")
    return metadata


def _snapshot_manifest(plan, metadata):
    entries = {}
    for path, expected in plan["inputs"].items():
        entries[path] = {"artifact_kind": "file", "original": expected,
                         "blob": hashlib.sha256(path.encode("utf-8")).hexdigest() + ".bin"
                         if expected["exists"] else None}
    external = {}
    for name, item in plan.get("external_inputs", {}).items():
        raw = item["text"].encode("utf-8")
        external[name] = {"artifact_kind": "external", "kind": item["kind"], "size": len(raw),
                          "sha256": hashlib.sha256(raw).hexdigest(),
                          "blob": "external-" + name + ".bin"}
    return {"schema_version": 1, "migration_id": MIGRATION_ID,
            "plan_id": plan["plan_id"], "entries": entries,
            "created_at": metadata["created_at"], "id_map": plan["id_map"],
            # Deliberately exclude projected `data` and any other action
            # payload: secrets/configuration bytes belong only in private
            # original blobs and the protected plan, never duplicated here.
            "actions": [{key: action[key] for key in ("id", "kind", "source", "target")
                         if key in action} for action in plan.get("actions", [])],
            "external_inputs": external,
            "inventory_groups": plan.get("inventory_groups", [])}


def _snapshot_requirements(plan):
    prerequisites = plan.get("prerequisites", {})
    if not isinstance(prerequisites, dict):
        _fail("invalid_plan")
    if "managed_cron_captured" in prerequisites and prerequisites["managed_cron_captured"] is not True:
        _fail("snapshot_incomplete")
    if prerequisites.get("managed_cron_captured") is True and "managed_cron" not in plan.get("external_inputs", {}):
        _fail("snapshot_incomplete")


def _snapshot_contents(snapshot, *, complete):
    """Unknown interrupted staging files are evidence, never ignored inputs."""
    with _directory(snapshot) as directory:
        names = set(os.listdir(directory))
    expected = {"metadata.json", "manifest.json", "files"}
    if names - expected or complete and names != expected:
        _fail("snapshot_incomplete")


def create_snapshot(plan: dict, state_dir) -> dict:
    """Copy exact original inputs, including existing destination originals.

    A partially copied snapshot can be completed only with the same persisted
    plan, unchanged inputs and already-valid blobs. Corrupt blobs are never
    overwritten. There is deliberately no export or restoration endpoint.
    """
    plan = seal_plan(plan)
    _snapshot_requirements(plan)
    plan = persist_plan(plan, state_dir)
    verify_inputs(plan)
    state_dir = _private_directory(state_dir)
    snapshot = _private_directory(state_dir / "snapshot", create=True)
    blobs = _private_directory(snapshot / "files", create=True)
    _snapshot_contents(snapshot, complete=False)
    with _directory(blobs) as directory:
        free = os.fstatvfs(directory)
        required = sum(item["size"] for item in plan["inputs"].values() if item["exists"])
        required += sum(len(item["text"].encode("utf-8")) for item in plan.get("external_inputs", {}).values())
        if free.f_bavail * free.f_frsize < required + 65536:
            _fail("insufficient_space")
    metadata = _snapshot_metadata(plan, snapshot, create=True)
    manifest = _snapshot_manifest(plan, metadata)
    for path, entry in manifest["entries"].items():
        actual, content = _read_file(path)
        if actual != entry["original"]:
            _fail("input_changed")
        if entry["blob"] is not None:
            _publish_once(blobs / entry["blob"], content)
    for name, entry in manifest["external_inputs"].items():
        _publish_once(blobs / entry["blob"], plan["external_inputs"][name]["text"].encode("utf-8"))
    verify_inputs(plan)
    _publish_once(snapshot / "manifest.json", _canonical(manifest))
    handle = {"path": str(snapshot), "plan_id": plan["plan_id"], "digest": _digest(manifest)}
    verify_snapshot(plan, handle)
    return handle


def verify_snapshot(plan: dict, snapshot: dict) -> dict:
    """Verify completeness, binding and each private stored byte independently."""
    plan = seal_plan(plan)
    _snapshot_requirements(plan)
    if not isinstance(snapshot, dict) or set(snapshot) != {"path", "plan_id", "digest"}:
        _fail("invalid_snapshot")
    path = _absolute(snapshot["path"])
    if path.name != "snapshot" or snapshot["plan_id"] != plan["plan_id"]:
        _fail("invalid_snapshot")
    _private_directory(path)
    _snapshot_contents(path, complete=True)
    if load_plan(path.parent) != plan:
        _fail("invalid_snapshot")
    metadata = _snapshot_metadata(plan, path)
    manifest = _read_json(path / "manifest.json")
    if _canonical(manifest) != _canonical(_snapshot_manifest(plan, metadata)) or _digest(manifest) != snapshot["digest"]:
        _fail("invalid_snapshot")
    blobs = _private_directory(path / "files")
    expected_names = {entry["blob"] for entry in manifest["entries"].values() if entry["blob"]}
    expected_names.update(entry["blob"] for entry in manifest["external_inputs"].values())
    with _directory(blobs) as directory:
        # Interrupted private staging files are not recovery blobs. They carry
        # no authority; committed snapshots must contain exactly their blobs.
        if set(os.listdir(directory)) != expected_names:
            _fail("snapshot_incomplete")
    for entry in manifest["entries"].values():
        if entry["blob"]:
            actual, _ = _read_file(blobs / entry["blob"], private=True)
            original = entry["original"]
            if not actual["exists"] or (actual["size"], actual["sha256"]) != (original["size"], original["sha256"]):
                _fail("snapshot_changed")
    for entry in manifest["external_inputs"].values():
        actual, _ = _read_file(blobs / entry["blob"], private=True)
        if not actual["exists"] or (actual["size"], actual["sha256"]) != (entry["size"], entry["sha256"]):
            _fail("snapshot_changed")
    return manifest


def verify_preconditions(plan: dict, snapshot: dict, confirmation=None, *,
                         quiescence_check: Callable[[], bool] | None = None,
                         external_input_check: Callable[[], dict] | None = None) -> bool:
    """Default-deny *library* gate; this neither applies data nor trusts a UI.

    Phase #479 must supply the real writer/maintenance check and authenticated
    confirmation. Checking immediately here cannot replace locks held across
    the eventual apply transaction. An acknowledgement is not external-copy
    verification, and this function must never be described as such.
    """
    plan = seal_plan(plan)
    if (plan.get("classification") != "applicable" or plan.get("required") is not True
            or plan.get("status") != "pending"):
        _fail("invalid_plan")
    prerequisites = plan.get("prerequisites")
    if not isinstance(prerequisites, dict) or prerequisites.get("managed_cron_captured") is not True:
        _fail("snapshot_incomplete")
    _snapshot_requirements(plan)
    if not isinstance(confirmation, dict) or confirmation.get("approved") is not True:
        _fail("approval_required")
    if (confirmation.get("independent_backup_acknowledged") is not True
            or confirmation.get("plan_id") != plan["plan_id"]
            or not isinstance(snapshot, dict)
            or confirmation.get("snapshot_digest") != snapshot.get("digest")):
        _fail("approval_required")
    if quiescence_check is None:
        _fail("writers_active")
    try:
        quiescent = quiescence_check()
    except Exception:
        _fail("writers_active")
    if quiescent is not True:
        _fail("writers_active")
    verify_snapshot(plan, snapshot)
    verify_inputs(plan)
    if plan.get("external_inputs"):
        if external_input_check is None:
            _fail("input_changed")
        try:
            current = external_input_check()
        except Exception:
            _fail("input_changed")
        if current != plan["external_inputs"]:
            _fail("input_changed")
    return True


def _journal_records(raw, plan):
    records = []
    previous = None
    if raw and not raw.endswith(b"\n"):
        _fail("invalid_journal")
    for line in raw.splitlines():
        try:
            record = json.loads(line, object_pairs_hook=_unique_json_pairs)
        except (ValueError, UnicodeError):
            _fail("invalid_journal")
        if not isinstance(record, dict):
            _fail("invalid_journal")
        expected = {"schema_version", "migration_id", "plan_id", "sequence", "timestamp",
                    "status", "phase", "reason_code", "action_ids", "previous", "digest"}
        if (set(record) != expected or type(record["schema_version"]) is not int
                or record["schema_version"] != 1 or record["migration_id"] != MIGRATION_ID):
            _fail("invalid_journal")
        if (record["plan_id"] != plan["plan_id"] or type(record["sequence"]) is not int
                or record["sequence"] != len(records) + 1):
            _fail("invalid_journal")
        try:
            timestamp = datetime.fromisoformat(record["timestamp"])
            if timestamp.utcoffset() is None:
                _fail("invalid_journal")
        except (ValueError, TypeError):
            _fail("invalid_journal")
        if (not isinstance(record["status"], str) or record["status"] not in STATUSES
                or not isinstance(record["phase"], str) or record["phase"] not in PHASES):
            _fail("invalid_journal")
        if record["reason_code"] is not None and (not isinstance(record["reason_code"], str) or record["reason_code"] not in REASON_CODES):
            _fail("invalid_journal")
        known_actions = {action["id"] for action in plan.get("actions", [])}
        if not isinstance(record["action_ids"], list) or any(not isinstance(item, str) or item not in known_actions for item in record["action_ids"]):
            _fail("invalid_journal")
        if record["previous"] != previous:
            _fail("invalid_journal")
        unsigned = dict(record)
        claimed = unsigned.pop("digest")
        if claimed != _digest(unsigned):
            _fail("invalid_journal")
        previous = claimed
        records.append(record)
    return records


def read_journal(state_dir) -> list:
    state_dir = _private_directory(state_dir)
    plan = load_plan(state_dir)
    # append_journal may need multiple writes for one JSONL record. Status
    # readers share its flock so a live append is never mistaken for corrupt
    # recovery evidence. A genuinely torn record after process exit still
    # fails validation; this does not repair or discard journal bytes.
    with _directory(state_dir) as directory:
        fd = None
        try:
            try:
                fd = os.open("journal.jsonl", os.O_RDONLY | _NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
            except FileNotFoundError:
                return []
            fcntl.flock(fd, fcntl.LOCK_SH)
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_uid != os.getuid() or info.st_nlink != 1):
                _fail("unsafe_path")
            chunks = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return _journal_records(b"".join(chunks), plan)
        except OSError as exc:
            _os_error(exc)
        finally:
            if fd is not None:
                os.close(fd)


def append_journal(state_dir, plan: dict, status: str, phase: str, *,
                   reason_code=None, action_ids=None) -> dict:
    """Append a private, fsynced, hash-linked event without free-form errors."""
    plan = seal_plan(plan)
    if (not isinstance(status, str) or status not in STATUSES
            or not isinstance(phase, str) or phase not in PHASES
            or reason_code is not None and (not isinstance(reason_code, str) or reason_code not in REASON_CODES)):
        _fail("invalid_journal")
    action_ids = [] if action_ids is None else action_ids
    known_actions = {action["id"] for action in plan.get("actions", [])}
    if not isinstance(action_ids, list) or any(not isinstance(item, str) or item not in known_actions for item in action_ids):
        _fail("invalid_journal")
    state_dir = _private_directory(state_dir)
    if load_plan(state_dir) != plan:
        _fail("state_conflict")
    with _directory(state_dir) as directory:
        fd = None
        try:
            fd = os.open("journal.jsonl", os.O_RDWR | os.O_APPEND | os.O_CREAT | _NOFOLLOW,
                         0o600, dir_fd=directory)
            fcntl.flock(fd, fcntl.LOCK_EX)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid() or info.st_nlink != 1:
                _fail("unsafe_path")
            raw = b""
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                raw += chunk
            records = _journal_records(raw, plan)
            record = {"schema_version": 1, "migration_id": MIGRATION_ID,
                      "plan_id": plan["plan_id"], "sequence": len(records) + 1,
                      "timestamp": datetime.now(timezone.utc).isoformat(),
                      "status": status, "phase": phase, "reason_code": reason_code,
                      "action_ids": action_ids,
                      "previous": records[-1]["digest"] if records else None}
            record["digest"] = _digest(record)
            data = memoryview(_canonical(record) + b"\n")
            while data:
                written = os.write(fd, data)
                if written <= 0:
                    _fail("storage_unavailable")
                data = data[written:]
            os.fsync(fd)
            os.fsync(directory)
            return record
        except IdentityStorageError:
            raise
        except OSError as exc:
            _os_error(exc)
        finally:
            if fd is not None:
                os.close(fd)
