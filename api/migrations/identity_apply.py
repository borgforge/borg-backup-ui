"""Explicit, crash-consistent identity cutover (#479).

The coordinator owns authentication and holds writer exclusion for this entire
call. Neither importing this module nor reading its recovery state applies
anything. The original sealed plan and verified snapshot remain authoritative;
retries never allocate identities or capture already converted originals.
"""

from __future__ import annotations

from contextlib import contextmanager
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import stat

from . import identity_storage as storage
from . import immutable_job_id_v1 as planner


_BEGIN = "# --- BORG-BACKUP-UI BEGIN ---"
_END = "# --- BORG-BACKUP-UI END ---"
_WRITES = {"write_json", "write_bytes"}
_RETIRES = {"retire_source", "retire_auxiliary"}


def _fail(code):
    raise storage.IdentityStorageError(code) from None


def _cron_parts(text):
    if not isinstance(text, str):
        _fail("invalid_plan")
    if _BEGIN not in text and _END not in text:
        return text, "", False
    if text.count(_BEGIN) != 1 or text.count(_END) != 1:
        _fail("invalid_plan")
    begin, end = text.find(_BEGIN), text.find(_END)
    if (end < begin or begin and text[begin - 1] != "\n"
            or end and text[end - 1] != "\n"):
        _fail("invalid_plan")
    end += len(_END)
    if end < len(text):
        if text[end] != "\n":
            _fail("invalid_plan")
        end += 1
    if text[begin + len(_BEGIN):begin + len(_BEGIN) + 1] != "\n":
        _fail("invalid_plan")
    return text[:begin], text[end:], True


def replace_managed_cron(original, lines):
    """Replace only the plugin block, retaining unrelated bytes verbatim."""
    if (not isinstance(lines, list) or any(not isinstance(line, str) or "\n" in line
                                         or "\r" in line for line in lines)):
        _fail("invalid_plan")
    before, after, present = _cron_parts(original)
    block = _BEGIN + "\n" + "\n".join(lines) + "\n" + _END + "\n" if lines else ""
    # Prepending avoids changing a user's final line without a line terminator.
    return before + block + after if present else block + original


def snapshot_handle(state_dir, plan, digest):
    return {"path": str(Path(state_dir) / "snapshot"),
            "plan_id": plan["plan_id"], "digest": digest}


def _content(action):
    try:
        if action["kind"] == "write_json":
            raw = planner.encode_target_json(action["data"])
        else:
            if not isinstance(action.get("text"), str):
                _fail("invalid_plan")
            raw = action["text"].encode("utf-8")
        after = action["after"]
        storage._valid_fingerprint(after)
        if (not after["exists"] or after["size"] != len(raw)
                or after["sha256"] != hashlib.sha256(raw).hexdigest()):
            _fail("invalid_plan")
        return raw
    except (KeyError, ValueError, TypeError, UnicodeError):
        _fail("invalid_plan")


def _actions(plan):
    writes, retirements, derived = [], [], []
    targets, removed = {}, set()
    for action in plan["actions"]:
        kind = action.get("kind")
        if kind not in _WRITES | _RETIRES | {"rebuild_derived"}:
            _fail("invalid_plan")
        if action.get("source") not in plan["inputs"] or action.get("target") not in plan["inputs"]:
            _fail("invalid_plan")
        if kind in _WRITES:
            _content(action)
            if action["target"] in targets:
                _fail("invalid_plan")
            targets[action["target"]] = action
            writes.append(action)
        else:
            if action["source"] in removed:
                _fail("invalid_plan")
            removed.add(action["source"])
            if kind == "rebuild_derived":
                if action["source"] != action["target"]:
                    _fail("invalid_plan")
                derived.append(action)
            else:
                if action["source"] == action["target"]:
                    _fail("invalid_plan")
                retirements.append(action)
    if removed.intersection(targets):
        _fail("invalid_plan")
    for action in retirements:
        if action["target"] not in targets:
            _fail("invalid_plan")
    return writes + retirements + derived, targets


def _quiescent(callback):
    try:
        quiet = callback() if callback else False
    except Exception:
        _fail("writers_active")
    if quiet is not True:
        _fail("writers_active")


@contextmanager
def _operation_lock(state_dir):
    """The immutable plan inode is also the duplicate-operation lock."""
    with storage._directory(state_dir) as directory:
        fd = os.open("plan.json", os.O_RDONLY | storage._NOFOLLOW, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_uid != os.getuid() or info.st_nlink != 1):
                _fail("unsafe_path")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                _fail("writers_active")
            yield
        finally:
            os.close(fd)


def _directory_identity(path, *, missing_ok=False):
    with storage._directory(path, missing_ok=missing_ok) as directory:
        if directory is None:
            return None
        info = os.fstat(directory)
        return {"device": info.st_dev, "inode": info.st_ino,
                "mode": stat.S_IMODE(info.st_mode), "owner": info.st_uid}


def _roots(plan, state_dir, *, started):
    """Persist filesystem anchors before creating any destination directory."""
    path = Path(state_dir) / "apply-roots.json"
    if storage.fingerprint_file(path)["exists"]:
        value = storage._read_json(path)
        if (not isinstance(value, dict) or set(value) != {"plan_id", "anchors", "create"}
                or value["plan_id"] != plan["plan_id"]
                or not isinstance(value["anchors"], dict) or not isinstance(value["create"], list)):
            _fail("state_conflict")
        return value
    if started:
        _fail("state_conflict")
    anchors, missing = {}, set()
    for filename in plan["inputs"]:
        parent = Path(filename).parent
        while True:
            identity = _directory_identity(parent, missing_ok=True)
            if identity is not None:
                anchors[str(parent)] = identity
                break
            missing.add(str(parent))
            parent = parent.parent
    value = {"plan_id": plan["plan_id"], "anchors": anchors,
             "create": sorted(missing, key=lambda item: (len(Path(item).parts), item))}
    storage._publish_once(path, storage._canonical(value))
    return value


def _directory_receipt(state_dir, path):
    name = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    return Path(state_dir) / ("directory-" + name + ".json")


def _verify_roots(roots, state_dir, plan):
    for path, expected in roots["anchors"].items():
        planner._path(path)  # Recheck required /mnt and /boot mounts too.
        if _directory_identity(path, missing_ok=True) != expected:
            _fail("inventory_changed")
    for path in roots["create"]:
        receipt = _directory_receipt(state_dir, path)
        actual = _directory_identity(path, missing_ok=True)
        if storage.fingerprint_file(receipt)["exists"]:
            saved = storage._read_json(receipt)
            if (not isinstance(saved, dict) or set(saved) != {"plan_id", "path", "identity"}
                    or saved["plan_id"] != plan["plan_id"] or saved["path"] != path):
                _fail("state_conflict")
            if actual is not None and actual != saved["identity"]:
                _fail("inventory_changed")
        elif actual is not None:
            _fail("inventory_changed")


def _ensure_parent(path, roots, state_dir, plan):
    needed = {str(p) for p in Path(path).parents}
    for name in roots["create"]:
        if name not in needed:
            continue
        directory = Path(name)
        receipt = _directory_receipt(state_dir, name)
        saved = storage._read_json(receipt) if storage.fingerprint_file(receipt)["exists"] else None
        actual = _directory_identity(directory, missing_ok=True)
        if actual is not None:
            if saved is None or actual != saved["identity"]:
                _fail("inventory_changed")
            continue
        # Persist the staged directory's inode BEFORE publication. This makes
        # both sides of its rename independently verifiable after a crash.
        stage = ".identity-dir-" + hashlib.sha256((plan["plan_id"] + name).encode()).hexdigest()[:32]
        with storage._directory(directory.parent) as parent:
            parent_mode = stat.S_IMODE(os.fstat(parent).st_mode)
            try:
                os.mkdir(stage, 0o700, dir_fd=parent)
                os.fsync(parent)
            except FileExistsError:
                pass
            identity = _directory_identity(directory.parent / stage)
            with storage._directory(directory.parent / stage) as staged:
                # The destination can be the Unraid FAT data filesystem, whose
                # mount-defined mode cannot honor mkdir(0700). It may retain
                # that existing parent's observed mode. This exception NEVER
                # applies to the separate private recovery/snapshot directory.
                if (identity["mode"] not in {0o700, parent_mode} or identity["owner"] != os.getuid()
                        or os.listdir(staged)):
                    _fail("state_conflict")
            expected = {"plan_id": plan["plan_id"], "path": name, "identity": identity}
            if saved is not None and saved != expected:
                _fail("state_conflict")
            storage._publish_once(receipt, storage._canonical(expected))
            # Destination absence was checked under the coordinator's writer
            # lock. No unrelated files/directories may be replaced here.
            if _directory_identity(directory, missing_ok=True) is not None:
                _fail("inventory_changed")
            os.rename(stage, directory.name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        if _directory_identity(directory) != expected["identity"]:
            _fail("verification_failed")


def _journal_state(records):
    started, completed = set(), set()
    for record in records:
        if record["phase"] == "apply":
            if record["status"] in {"pending", "applied"}:
                started.update(record["action_ids"])
            if record["status"] == "applied":
                completed.update(record["action_ids"])
    return started, completed


def _verify_footprint(config, plan, records, control_root):
    started, completed = _journal_state(records)
    actions, targets = _actions(plan)
    removed = {a["source"]: a for a in actions if a["kind"] not in _WRITES}
    actual = {path: storage.fingerprint_file(path) for path in plan["inputs"]}
    for path, original in plan["inputs"].items():
        replacement, retirement = targets.get(path), removed.get(path)
        if replacement and replacement["id"] in completed and actual[path] != replacement["after"]:
            _fail("input_changed")
        if retirement and retirement["id"] in completed and actual[path]["exists"]:
            _fail("input_changed")
        if actual[path] == original:
            continue
        if replacement and replacement["id"] in started and actual[path] == replacement["after"]:
            continue
        if retirement and retirement["id"] in started and not actual[path]["exists"]:
            if (retirement["kind"] == "rebuild_derived"
                    or actual[retirement["target"]] == targets[retirement["target"]]["after"]):
                continue
        _fail("input_changed")
    # The domain planner checks mounts, inventory membership, live owners and
    # repository/secret references using the original saved allocation.
    checked = planner.build_plan(config, journal_plan=plan, control_root=control_root)
    if checked != plan:
        _fail("inventory_changed")


def _publish_replacement(action, plan):
    path = Path(action["target"])
    content = _content(action)
    temporary = ".identity-" + plan["plan_id"][:16] + "-" + hashlib.sha256(action["id"].encode()).hexdigest()[:24] + ".stage"
    with storage._directory(path.parent) as directory:
        fd = os.open(temporary, os.O_RDONLY | os.O_CREAT | storage._NOFOLLOW | os.O_NONBLOCK,
                     0o600, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) not in {0o600, action["after"]["mode"]}):
                _fail("unsafe_path")
            existing = b""
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                existing += chunk
            # Only an exact prefix of this journaled action is a recoverable
            # interrupted staging write. Unexpected bytes remain untouched.
            if len(existing) > len(content) or not content.startswith(existing):
                _fail("state_conflict")
            # A crash after fchmod may leave an otherwise complete read-only
            # stage. Restore owner access on this verified private inode only.
            os.fchmod(fd, 0o600)
            writable = os.open(temporary, os.O_RDWR | storage._NOFOLLOW | os.O_NONBLOCK,
                               dir_fd=directory)
            reopened = os.fstat(writable)
            if (info.st_dev, info.st_ino) != (reopened.st_dev, reopened.st_ino):
                os.close(writable)
                _fail("state_conflict")
            os.close(fd)
            fd = writable
            free = os.fstatvfs(fd)
            if free.f_bavail * free.f_frsize < len(content) - len(existing) + 4096:
                _fail("insufficient_space")
            os.lseek(fd, 0, os.SEEK_SET)
            view = memoryview(content)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    _fail("storage_unavailable")
                view = view[count:]
            os.ftruncate(fd, len(content))
            os.fchmod(fd, action["after"]["mode"])
            os.fsync(fd)
        finally:
            os.close(fd)
        if storage.fingerprint_file(path.parent / temporary) != action["after"]:
            _fail("verification_failed")
        actual = storage.fingerprint_file(path)
        if actual not in (plan["inputs"][str(path)], action["after"]):
            _fail("input_changed")
        os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    if storage.fingerprint_file(path) != action["after"]:
        _fail("verification_failed")


def _retire(action, plan, targets):
    path = Path(action["source"])
    if action["kind"] in _RETIRES:
        target = targets[action["target"]]
        if storage.fingerprint_file(target["target"]) != target["after"]:
            _fail("verification_failed")
    current = storage.fingerprint_file(path)
    if not current["exists"]:
        return
    if current != plan["inputs"][str(path)]:
        _fail("input_changed")
    with storage._directory(path.parent) as directory:
        os.unlink(path.name, dir_fd=directory)
        os.fsync(directory)
    if storage.fingerprint_file(path)["exists"]:
        _fail("verification_failed")


def _read_cron(callback):
    try:
        text = callback()
        if not isinstance(text, str):
            _fail("input_changed")
        text.encode("utf-8")
        return text
    except Exception:
        _fail("input_changed")


def _cron_target(plan, state_dir, render_cron, *, started):
    original = plan["external_inputs"]["managed_cron"]["text"]
    path = Path(state_dir) / "apply-cron.json"
    if storage.fingerprint_file(path)["exists"]:
        value = storage._read_json(path)
        if (not isinstance(value, dict) or set(value) != {"plan_id", "original", "target"}
                or value["plan_id"] != plan["plan_id"] or value["original"] != original):
            _fail("state_conflict")
    else:
        if started:
            _fail("state_conflict")
        try:
            target = render_cron(original, plan)
        except Exception:
            _fail("invalid_plan")
        value = {"plan_id": plan["plan_id"], "original": original, "target": target}
    before, after, _ = _cron_parts(original)
    new_before, new_after, _ = _cron_parts(value["target"])
    if before + after != new_before + new_after:
        _fail("input_changed")
    storage._publish_once(path, storage._canonical(value))
    return value["target"]


def apply_plan(config, state_dir, *, approval, quiescence_callback, read_cron,
               write_cron, render_cron, control_root=None):
    """Apply/resume only after an explicit authenticated, bound authorization.

    ``quiescence_callback`` must return exactly True while the caller holds
    writer exclusion. ``read_cron()`` returns the actual full crontab text;
    ``write_cron(text)`` installs it; ``render_cron(original, plan)`` is pure.
    Filesystem and callback errors expose stable masked reason codes only.
    """
    plan = None
    active = []
    try:
        plan = storage.load_plan(state_dir)
        actions, targets = _actions(plan)
        snapshot = snapshot_handle(state_dir, plan, approval.get("snapshot_digest") if isinstance(approval, dict) else None)
        if (plan.get("classification") != "applicable" or plan.get("required") is not True
                or plan.get("status") != "pending"):
            _fail("invalid_plan")
        if (not isinstance(approval, dict) or approval.get("approved") is not True
                or approval.get("independent_backup_acknowledged") is not True
                or approval.get("plan_id") != plan["plan_id"]):
            _fail("approval_required")
        with _operation_lock(state_dir):
            _quiescent(quiescence_callback)
            storage.verify_snapshot(plan, snapshot)
            records = storage.read_journal(state_dir)
            started = any(r["phase"] in {"apply", "commit"} and r["status"] in {"pending", "applied"} for r in records)
            if not started:
                storage.verify_preconditions(plan, snapshot, approval,
                    quiescence_check=quiescence_callback,
                    external_input_check=lambda: {"managed_cron": {"kind": "crontab", "text": _read_cron(read_cron)}})
            roots = _roots(plan, state_dir, started=started)
            _verify_roots(roots, state_dir, plan)
            _verify_footprint(config, plan, records, control_root)
            cron = _cron_target(plan, state_dir, render_cron, started=started)
            original_cron = plan["external_inputs"]["managed_cron"]["text"]
            commit_started = any(r["phase"] == "commit" and r["status"] in {"pending", "applied"} for r in records)
            if _read_cron(read_cron) not in ({original_cron, cron} if commit_started else {original_cron}):
                _fail("input_changed")
            already_applied = any(r["phase"] == "commit" and r["status"] == "applied" for r in records)
            if not already_applied:
                storage.append_journal(state_dir, plan, "pending", "resume" if started else "apply")
                _, completed = _journal_state(records)
                for action in actions:
                    if action["id"] in completed:
                        continue
                    active = [action["id"]]
                    _quiescent(quiescence_callback)
                    _verify_roots(roots, state_dir, plan)
                    # Writer exclusion spans the transaction. Check the file
                    # about to change here; scan the complete graph at entry
                    # and the final boundary, not once per historical record.
                    if action["kind"] in _WRITES and action["source"] != action["target"]:
                        if storage.fingerprint_file(action["source"]) != plan["inputs"][action["source"]]:
                            _fail("input_changed")
                    storage.append_journal(state_dir, plan, "pending", "apply", action_ids=active)
                    if action["kind"] in _WRITES:
                        _ensure_parent(action["target"], roots, state_dir, plan)
                        if storage.fingerprint_file(action["target"]) != action["after"]:
                            _publish_replacement(action, plan)
                    else:
                        _retire(action, plan, targets)
                    storage.append_journal(state_dir, plan, "applied", "apply", action_ids=active)
                active = []
            _quiescent(quiescence_callback)
            _verify_roots(roots, state_dir, plan)
            _verify_footprint(config, plan, storage.read_journal(state_dir), control_root)
            if planner.verify_target(config, control_root=control_root).get("valid") is not True:
                _fail("verification_failed")
            if not already_applied:
                storage.append_journal(state_dir, plan, "pending", "commit")
                if _read_cron(read_cron) not in {original_cron, cron}:
                    _fail("input_changed")
                if _read_cron(read_cron) != cron:
                    write_cron(cron)
            if _read_cron(read_cron) != cron:
                _fail("verification_failed")
            _quiescent(quiescence_callback)
            if planner.verify_target(config, control_root=control_root).get("valid") is not True:
                _fail("verification_failed")
            if not already_applied:
                storage.append_journal(state_dir, plan, "applied", "commit")
            return {"migration_id": storage.MIGRATION_ID, "status": "applied",
                    "plan_id": plan["plan_id"], "snapshot_digest": snapshot["digest"],
                    "actions_completed": len(actions), "already_applied": already_applied}
    except Exception as exc:
        code = exc.code if isinstance(exc, storage.IdentityStorageError) else (
            "insufficient_space" if isinstance(exc, OSError) and exc.errno == errno.ENOSPC
            else "storage_unavailable" if isinstance(exc, OSError) else "verification_failed")
        if plan is not None and code not in {"approval_required", "writers_active", "invalid_journal"}:
            try:
                storage.append_journal(state_dir, plan, "failed", "apply", reason_code=code, action_ids=active)
            except Exception:
                pass  # Preserve the original masked failure and all evidence.
        _fail(code)
