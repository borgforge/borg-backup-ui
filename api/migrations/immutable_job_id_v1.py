"""Inactive, read-only identity migration planner (#472).

Deliberately not registered, imported by startup, exposed by HTTP, or given an
apply() entry point. Proposed JSON replacements are private planning data;
only the separate snapshot/journal utilities may write a dedicated state dir.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID, uuid4

from . import identity_storage as storage
from .identity_records import project_records, verify_records


MIGRATION_ID = "immutable_job_id_v1"
INTRODUCED_IN = "pending-issue-447"
MAX_JSON_BYTES = 64 * 1024 * 1024
_KEY = re.compile(r"^[A-Za-z0-9_.-]+$")
_TYPE = re.compile(r"^[a-z0-9_]+$")
_LOCATIONS = {"local", "usb", "smb", "storagebox", "custom"}
_LEGACY = {"job_key", "backup_type", "type_id", "location"}


class PlanningError(ValueError):
    def __init__(self, code, source=""):
        self.code, self.source = code, str(source)
        super().__init__(code)  # Never interpolate raw JSON, config or errors.


def _fail(code, source=""):
    raise PlanningError(code, source)


def _uuid(value):
    try:
        parsed = UUID(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    return parsed is not None and parsed.version == 4 and str(parsed) == value


def _path(value):
    if not isinstance(value, (str, Path)):
        _fail("unsafe_path")
    raw = str(value)
    if not raw.startswith("/") or raw != os.path.normpath(raw) or raw.startswith("//"):
        _fail("unsafe_path")
    if any(c in raw for c in ("\x00", "\n", "\r", "$")) or raw == "/":
        _fail("unsafe_path")
    path = Path(raw)
    parts = path.parts
    mount = None
    if len(parts) > 2 and parts[1] == "mnt":
        mount = Path(*parts[:4]) if parts[2] in {"disks", "remotes"} and len(parts) > 3 else Path(*parts[:3])
    elif len(parts) > 1 and parts[1] == "boot":
        mount = Path("/boot")
    if mount is not None and not mount.is_mount():
        _fail("required_mount_unavailable", path)
    return path


def _strict_json(raw, source):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("duplicate_json_member", source)
            result[key] = value
        return result
    if len(raw) > MAX_JSON_BYTES:
        _fail("owned_input_too_large", source)
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: _fail("invalid_json", source))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        _fail("invalid_json", source)


def _read_conf(raw):
    """Same literal decoding/forward-reference semantics as status.load_config.

    No shell, environment expansion or import of lazy runtime helpers. Only
    relevant non-secret values are copied into proposed canonical metadata.
    """
    values = {}
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError:
        _fail("invalid_configuration_encoding")
    for line in lines:
        line = line.strip().removeprefix("readonly ")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value.startswith('"'):
            try:
                decoded, end = json.JSONDecoder().raw_decode(value)
                tail = value[end:].strip()
                if isinstance(decoded, str) and (not tail or tail.startswith("#")):
                    value = decoded
            except json.JSONDecodeError:
                pass
        elif value.startswith("'") and value.rfind("'") > 0:
            end = value.rfind("'")
            tail = value[end + 1:].strip()
            if not tail or tail.startswith("#"):
                value = value[1:end]
        else:
            value = value.split("  #", 1)[0].rstrip()
        if value.startswith("("):
            continue
        values[key] = re.sub(r"\$\{([^}]+)\}", lambda m: values.get(m[1], m[0]), value)
    return values


class Inventory:
    def __init__(self):
        self.inputs, self.groups, self.records, self.raw = {}, [], {}, {}

    def file(self, path, kind=None, **metadata):
        path = _path(path)
        name = str(path)
        fingerprint, raw = storage.read_fingerprinted_file(path)
        previous = self.inputs.get(name)
        if previous is not None and previous != fingerprint:
            _fail("source_fingerprint_changed", path)
        self.inputs[name] = fingerprint
        if raw is None:
            return None
        self.raw[name] = raw
        if kind is not None:
            value = _strict_json(raw, path)
            if not isinstance(value, dict):
                _fail("invalid_job_shape" if kind == "job" else "invalid_store_shape", path)
            old = self.records.get(name)
            if old and old["kind"] != kind:
                _fail("overlapping_owned_stores", path)
            self.records[name] = {"kind": kind, "data": value, **metadata}
            return value
        return raw

    def group(self, directory, suffix, kind, **metadata):
        directory = _path(directory)
        group = storage.inventory_group(directory, [suffix])
        if group not in self.groups:
            self.groups.append(group)
        for name in group["entries"]:
            self.file(directory / name, kind, **metadata)
        return group


def _inventory(config, control_root):
    scan = Inventory()
    data = _path(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup"))
    if data.name == "scripts":
        data = data.parent
    conf = scan.file(data / "config/backup.conf")
    expanded = _read_conf(conf) if conf is not None else {}
    effective = dict(config)
    for key in ("STATUS_DIR", "RESTORE_TEST_STATUS_DIR", "BORG_RESOURCE_LOCK_DIR",
                "RUNTIME_RECOVERY_FILE", "UNRAID_DASHBOARD_WIDGET_FILE"):
        if expanded.get(key):
            effective[key] = expanded[key]
    plugin = _path(effective.get("PLUGIN_DIR") or "/boot/config/plugins/borg-backup-ui")
    jobs_dir = data / "config/jobs"
    scan.group(jobs_dir, ".json", "job")
    # Known lazy-migration locations only; never traverse runtime/vendor/recycle bins.
    scripts = _path(effective.get("BORG_SCRIPTS_DIR") or str(data / "scripts"))
    for legacy in sorted({scripts / "config/jobs", plugin / "runtime/config/jobs"} - {jobs_dir}):
        scan.group(legacy, ".json", "job", legacy_directory=True)
    singleton = {
        "repositories.json": "repositories", "storages.json": "storages",
        "schedules.json": "schedules", "restore-runs.json": "restore_runs",
        "restore-history/index.json": "restore_index",
        "notification-queue.json": "notification_queue",
        "notification-deliveries.json": "notification_deliveries",
        "notification-state.json": "notification_state",
    }
    for filename, kind in singleton.items():
        scan.file(data / "config" / filename, kind)
    scan.file(_path(effective.get("RUNTIME_RECOVERY_FILE") or str(data / "config/runtime-recovery.json")), "runtime_recovery")
    scan.group(data / "config/restore-history/runs", ".json", "restore_detail")
    status_dir = _path(effective.get("STATUS_DIR") or "/mnt/user/backup-status")
    scan.group(status_dir, ".status", "status")
    weekly = _path(effective.get("SNAPSHOT_FILE") or str(status_dir.parent / "weekly-snapshots.json"))
    for candidate in sorted({weekly, status_dir / "weekly-snapshots.json"}):
        scan.file(candidate, "weekly", target_path=str(weekly))
    candidates = []
    if effective.get("RESTORE_TEST_STATUS_DIR"):
        candidates.append(_path(effective["RESTORE_TEST_STATUS_DIR"]))
    candidates += [status_dir.parent / "restore-status", status_dir / "restore-tests"]
    # Scan each known location: hidden stale results are not silently abandoned.
    for directory in dict.fromkeys(candidates):
        scan.group(directory, ".test", "restore_test")
    lock_dir = _path(effective.get("BORG_RESOURCE_LOCK_DIR") or str(data / "locks"))
    scan.group(lock_dir, ".json", "resource_lock")
    # This independent worker lock does not prove quiescence; preserve/capture it.
    scan.file(data / "locks/notification-delivery.lock")
    controls = _path(control_root or "/run/borg-backup-ui/jobs")
    children = storage.inventory_directories(controls)
    scan.groups.append(children)
    for run in children["entries"]:
        group = scan.group(controls / run, ".json", "control")
        for name in group["entries"]:
            path = str(controls / run / name)
            if name == "cancel.request.json":
                scan.records[path]["kind"] = "cancel_request"
            elif name == "context.json":
                scan.records[path]["kind"] = "run_context"
            elif name != "state.json":
                _fail("unknown_control_file", path)
    widget = _path(effective.get("UNRAID_DASHBOARD_WIDGET_FILE") or str(plugin / "widget-status.json"))
    scan.file(widget, "widget_cache")
    return scan, data, jobs_dir, expanded


def _prefixes(meta, legacy, source):
    values = meta.get("archive_prefixes", [])
    if not isinstance(values, list) or any(not isinstance(v, str) or not _KEY.fullmatch(v)
                                         or v in {".", ".."} for v in values):
        _fail("invalid_archive_prefix", source)
    if legacy and any(not re.fullmatch(r"[A-Za-z0-9_.-]+-backup", value) for value in values):
        # The old reader silently ignored these. Adopting them would expand
        # archive/prune ownership; dropping them would discard user data.
        _fail("invalid_archive_prefix", source)
    if not legacy and (not values or len(set(values)) != len(values)):
        _fail("invalid_archive_prefix", source)
    return list(dict.fromkeys(([meta["backup_type"] + "-backup"] if legacy else []) + values))


def _validate_job(meta, source):
    schema = meta.get("schema_version")
    if type(schema) is not int or schema not in {1, 2, 3, 4}:
        _fail("unsupported_schema", source)
    if schema == 4:
        if not _uuid(meta.get("job_id")):
            _fail("invalid_job_id", source)
        if _LEGACY.intersection(meta):
            _fail("mutable_canonical_identity", source)
        if "legacy_job_keys" not in meta:
            _fail("invalid_legacy_alias", source)
    else:
        typ, location, key = meta.get("backup_type"), meta.get("location"), meta.get("job_key")
        if not isinstance(typ, str) or not _TYPE.fullmatch(typ) or location not in _LOCATIONS:
            _fail("conflicting_legacy_identity", source)
        if key != f"{typ}_{location}" or Path(source).stem != key or "job_id" in meta:
            _fail("conflicting_legacy_identity", source)
    aliases = meta.get("legacy_job_keys", [])
    if not isinstance(aliases, list) or any(not isinstance(a, str) or not _KEY.fullmatch(a) for a in aliases):
        _fail("invalid_legacy_alias", source)
    if len(set(aliases)) != len(aliases):
        _fail("duplicate_legacy_alias", source)
    _prefixes(meta, schema != 4, source)
    if not isinstance(meta.get("name"), str) or not meta["name"].strip():
        _fail("invalid_job_name", source)
    if not isinstance(meta.get("repository_key"), str) or not _KEY.fullmatch(meta["repository_key"]):
        _fail("dangling_repository", source)


def _operational_defaults(meta, conf, source):
    result = deepcopy(meta)
    # Existing pure path converter does no writes. Ambiguous old strings may
    # inspect source directories, but never silently split nonexistent paths.
    try:
        from ..job_source_paths import normalize_source_paths, upgrade_job_source_paths
    except ImportError:
        from job_source_paths import normalize_source_paths, upgrade_job_source_paths
    try:
        if meta["schema_version"] in {1, 2}:
            result = upgrade_job_source_paths(result, job_key=meta["job_key"])
        elif normalize_source_paths(meta.get("source_paths")) != meta.get("source_paths"):
            _fail("noncanonical_source_paths", source)
    except ValueError:
        _fail("invalid_source_paths", source)
    if meta["schema_version"] == 4:
        return result
    tu = meta["backup_type"].upper()
    # Preserve the runner's existing cache namespace and check marker. These
    # paths are references, not identities, and are never renamed or deleted.
    cache_dir = conf.get("BORG_CACHE_DIR") or str(
        Path(conf.get("GLOBAL_BORG_CACHE_BASE") or "/mnt/cache/borg-cache")
        / (meta["location"] + "_" + meta["backup_type"])
    )
    if "cache_reference" in result:
        _fail("ambiguous_cache_reference", source)
    result["cache_reference"] = {
        "repository_key": meta["repository_key"],
        "directory": cache_dir,
        "check_flag_file": conf.get("BORG_CHECK_FLAG_FILE") or str(Path(cache_dir) / (".last_check_" + meta["backup_type"])),
    }
    # Env overrides unrelated to job metadata cannot be inferred safely. The
    # startup coordinator must supply the actual expanded backup.conf, captured
    # here, rather than invoking the runner which mutates process environment.
    if not result.get("compression"):
        result["compression"] = conf.get(f"COMPRESSION_{tu}", "lz4")
    retention = result.get("retention", {})
    if not isinstance(retention, dict):
        _fail("invalid_retention", source)
    retention = deepcopy(retention)
    if any(not isinstance(value, str) for value in retention.values()):
        # Numeric zero follows a different truthiness path in the legacy
        # runner. Neither silently filling defaults nor guessing intent is safe.
        _fail("ambiguous_retention_shape", source)
    for key, default in {"daily": "7", "weekly": "4", "monthly": "6", "yearly": "3"}.items():
        if not str(retention.get(key) or "").strip():
            retention[key] = conf.get(f"RETENTION_{tu}_{key.upper()}", default)
    result["retention"] = retention
    for kind in ("docker", "vm"):
        key = kind + "_control"
        if key not in result:
            features = result.get("features", {})
            if not isinstance(features, dict) or type(features.get(kind, False)) is not bool:
                _fail("invalid_runtime_control", source)
            result[key] = {"mode": "all" if features.get(kind) else "none", "selected": [],
                           "ack_appdata_risk" if kind == "docker" else "ack_domains_risk": False}
        elif not isinstance(result[key], dict):
            _fail("invalid_runtime_control", source)
    return result


def _plan_jobs(scan, jobs_dir, conf, allocator, journal):
    jobs, aliases, sources, seen_legacy, canonical_ids = {}, {}, {}, set(), set()
    rows = [(path, row["data"]) for path, row in sorted(scan.records.items()) if row["kind"] == "job"]
    for source, meta in rows:
        _validate_job(meta, source)
        if meta["schema_version"] == 4:
            job_id = meta["job_id"]
            if job_id in canonical_ids:
                _fail("duplicate_job_id", source)
            canonical_ids.add(job_id)
    for source, meta in rows:
        legacy = meta["schema_version"] != 4
        if legacy:
            key = meta["job_key"]
            if any(alias != key for alias in meta.get("legacy_job_keys", [])) and journal is None:
                _fail("unproven_legacy_alias", source)
            if key in seen_legacy:
                _fail("duplicate_legacy_identity", source)
            seen_legacy.add(key)
            proposed = journal.get("id_map", {}).get(key) if journal else None
            if proposed is None:
                try:
                    proposed = str(allocator())
                except Exception:
                    _fail("uuid_allocation_failed", source)
            if not _uuid(proposed) or proposed in jobs or proposed in canonical_ids:
                _fail("duplicate_job_id" if _uuid(proposed) else "invalid_job_id", source)
            job_id = proposed
        else:
            job_id = meta["job_id"]
            if Path(source) != jobs_dir / (job_id + ".json"):
                _fail("noncanonical_metadata_filename", source)
        target = _operational_defaults(meta, conf, source)
        target["archive_prefixes"] = _prefixes(meta, legacy, source)
        target["legacy_job_keys"] = list(dict.fromkeys(([meta["job_key"]] if legacy else []) + meta.get("legacy_job_keys", [])))
        for alias in target["legacy_job_keys"]:
            if alias in aliases:
                _fail("duplicate_legacy_alias", source)
            aliases[alias] = job_id
        for key in _LEGACY:
            target.pop(key, None)
        target.update(schema_version=4, job_id=job_id)
        # Share the target model's validation, but never its creation/write path.
        try:
            try:
                from ..job_model import validate_job
            except ImportError:
                from job_model import validate_job
            validate_job(target, filename=job_id + ".json")
        except ValueError as exc:
            _fail(getattr(exc, "api_code", "invalid_job_settings"), source)
        jobs[job_id], sources[job_id] = target, source
    if seen_legacy and canonical_ids:
        # A mixed on-disk cutover is not a new installation to re-plan. The
        # original persisted mapping/snapshot is required, even if aliases
        # could currently resolve all remaining references.
        _fail("partial_migration_without_journal")
    return jobs, aliases, sources, bool(seen_legacy)


def _check_repositories(scan, jobs, aliases):
    def collection(kind, name, key):
        selected = [r["data"] for r in scan.records.values() if r["kind"] == kind]
        if not selected:
            return {}
        raw = selected[0]
        if type(raw.get("schema_version")) is not int or raw["schema_version"] != 1 or not isinstance(raw.get(name), list):
            _fail("unsupported_store_schema")
        result = {}
        for row in raw[name]:
            if not isinstance(row, dict) or not isinstance(row.get(key), str) or not _KEY.fullmatch(row[key]):
                _fail("invalid_inventory_entry")
            if row[key] in result:
                _fail("duplicate_inventory_key")
            result[row[key]] = row
        return result
    repos = collection("repositories", "repositories", "repository_key")
    storages = collection("storages", "storages", "storage_key")
    for job in jobs.values():
        if job["repository_key"] not in repos:
            _fail("dangling_repository")
    for key, repo in repos.items():
        if repo.get("storage_key") not in storages:
            _fail("dangling_storage")
        expected = {job_id for job_id, job in jobs.items() if job["repository_key"] == key}
        for field in ("used_by", "source_job_keys", "job_ids", "source_job_ids"):
            if field not in repo:
                continue
            values = repo[field]
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                _fail("invalid_repository_assignments")
            mapped = [value if value in jobs else aliases.get(value) for value in values]
            if None in mapped or set(mapped) != expected or len(set(mapped)) != len(mapped):
                _fail("conflicting_repository_assignments")
        for field in ("passphrase_ref", "keyfile_ref"):
            if repo.get(field):
                path = _path(repo[field])
                # Existence/type only; never read secret contents into the plan.
                for parent in [*reversed(path.parents), path]:
                    if parent.is_symlink():
                        _fail("unsafe_secret_reference")
                try:
                    info = path.stat()
                except OSError:
                    _fail("missing_secret_reference")
                if not stat.S_ISREG(info.st_mode):
                    _fail("unsafe_secret_reference")
    # Delimiter overlap also matters (p-* includes p-long-*).
    ownership = []
    for job_id, job in jobs.items():
        for prefix in job["archive_prefixes"]:
            for other_repo, other_prefix, other_id in ownership:
                if other_repo == job["repository_key"] and other_id != job_id and (
                    prefix == other_prefix or prefix.startswith(other_prefix + "-") or other_prefix.startswith(prefix + "-")
                ):
                    _fail("ambiguous_archive_ownership")
            ownership.append((job["repository_key"], prefix, job_id))


def _check_live_owners(scan):
    for source, record in scan.records.items():
        data = record["data"]
        rows = data.get("entries", []) if record["kind"] == "runtime_recovery" else [data]
        if record["kind"] not in {"runtime_recovery", "resource_lock", "control"}:
            continue
        if not isinstance(rows, list):
            _fail("invalid_runtime_state", source)
        for row in rows:
            if not isinstance(row, dict):
                _fail("invalid_runtime_state", source)
            if row.get("finished") is True:
                continue
            pid = row.get("pid")
            if pid is None:
                continue  # Shape/identity validation belongs to the projector.
            if type(pid) is not int or pid <= 0:
                _fail("invalid_runtime_pid", source)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            except (PermissionError, OSError):
                _fail("writers_not_quiescent", source)
            else:
                _fail("writers_not_quiescent", source)


def _changed_active(scan, projected):
    for record in scan.records.values():
        kind, data = record["kind"], record["data"]
        if kind == "schedules" and any(key != "restore_test" and not _uuid(key) for key in data):
            return True
        if kind == "repositories" and any("used_by" in r or "source_job_keys" in r for r in data.get("repositories", [])):
            return True
    if projected.get("required"):
        return True
    for binding in projected["bindings"]:
        if binding["job_id"] is None:
            continue
        record = scan.records[binding["source"]]
        if record["kind"] in {"schedules", "repositories", "notification_state"}:
            continue
        row = record["data"]
        for part in binding["locator"].split("/")[1:]:
            part = part.replace("~1", "/").replace("~0", "~")
            row = row[int(part)] if isinstance(row, list) else row[part]
        if not isinstance(row, dict) or row.get("job_id") != binding["job_id"]:
            return True
        if binding["role"] == "active" and "job_key" in row:
            return True
        if record["kind"] == "restore_test" and Path(binding["source"]).stem != binding["job_id"]:
            return True
    return False


def encode_target_json(value):
    """Frozen planned JSON encoding; the future applier must use these bytes."""
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _resume_check(scan, journal):
    if journal is None:
        return None
    try:
        saved = storage.seal_plan(journal)
        if saved.get("plan_id") != journal.get("plan_id") or saved.get("classification") != "applicable":
            _fail("invalid_migration_journal")
        # Check the COMPLETE saved footprint, not just still-discoverable files.
        # A vanished source is only a valid retirement when its exact canonical
        # replacement is present. JSON-equivalent edits/chmod are not accepted.
        replacements = {a["target"]: a.get("after") for a in saved.get("actions", [])
                        if a.get("kind") in {"write_json", "write_bytes"}}
        retired = {a["source"]: a["target"] for a in saved.get("actions", [])
                   if a.get("kind") in {"retire_source", "retire_auxiliary"}}
        derived = {a["source"] for a in saved.get("actions", [])
                   if a.get("kind") == "rebuild_derived" and a.get("source") == a.get("target")}
        actual_inputs = {path: storage.fingerprint_file(path) for path in saved["inputs"]}
        if set(scan.inputs) - set(saved["inputs"]):
            _fail("source_fingerprint_changed")
        for path, actual in actual_inputs.items():
            if actual == saved["inputs"][path]:
                continue
            if (not actual["exists"] and path in retired
                    and actual_inputs.get(retired[path]) == replacements.get(retired[path])
                    and replacements.get(retired[path]) is not None):
                continue
            if path in replacements and actual == replacements[path]:
                continue
            if path in derived and not actual["exists"]:
                continue
            _fail("source_fingerprint_changed", path)
        current_groups = {g["path"]: g for g in scan.groups}
        if set(current_groups) != {g["path"] for g in saved["inventory_groups"]}:
            _fail("source_fingerprint_changed")
        for group in saved["inventory_groups"]:
            current = current_groups[group["path"]]
            if group.get("kind") == "directories":
                if current != group:
                    _fail("source_fingerprint_changed", group["path"])
                continue
            # The explicit apply engine may publish a previously absent jobs
            # directory from a legacy-only metadata location. Its private
            # directory receipts verify the original/new filesystem identity;
            # this read-only check additionally requires exact planned members.
            created_target_group = (not group["exists"] and current["exists"]
                                    and any(str(Path(path).parent) == group["path"]
                                            for path in replacements))
            if (not created_target_group
                    and {k: v for k, v in current.items() if k != "entries"}
                    != {k: v for k, v in group.items() if k != "entries"}):
                _fail("source_fingerprint_changed", group["path"])
            expected_names = {Path(path).name for path, fp in actual_inputs.items()
                              if str(Path(path).parent) == group["path"] and fp["exists"]
                              and Path(path).name.endswith(tuple(group["suffixes"]))}
            if set(current["entries"]) != expected_names:
                _fail("source_fingerprint_changed", group["path"])
        return saved
    except storage.IdentityStorageError:
        _fail("invalid_migration_journal")


def build_plan(config, *, uuid_factory=uuid4, journal_plan=None, control_root=None, cron_text=None):
    """Return a proposed complete mapping without changing any installation file.

    Pass a plan loaded/validated from the private journal to reuse allocated
    IDs. Fresh dry runs propose IDs; only persist_plan makes that mapping
    durable. No caller-supplied boolean can authorize application here.
    """
    scan = None
    try:
        scan, data, jobs_dir, conf = _inventory(config, control_root)
        journal = _resume_check(scan, journal_plan)
        if journal is not None:
            # Secret contents are not migration inputs, but their referenced
            # existence/type must still be checked on a resumed plan.
            _check_repositories(scan, journal["jobs"], journal["aliases"])
            _check_live_owners(scan)
            # Keep the original plan ID, complete original snapshot footprint,
            # and UUID map. Do not re-plan from half-converted stores or produce
            # a new snapshot of already converted data after an interruption.
            return journal
        jobs, aliases, sources, legacy = _plan_jobs(scan, jobs_dir, conf, uuid_factory, journal)
        _check_repositories(scan, jobs, aliases)
        _check_live_owners(scan)
        records = {p: deepcopy(r) for p, r in scan.records.items() if r["kind"] not in {"job", "storages"}}
        for path, row in records.items():
            if row["kind"] == "restore_test":
                key = Path(path).stem
                row["legacy_key"] = key
                job_id = key if key in jobs else aliases.get(key)
                if job_id:
                    row["target_path"] = str(Path(path).with_name(job_id + ".test"))
        projected = project_records(records, jobs, aliases)
        reasons = projected.get("reasons", [])
        fatal = [r for r in reasons if r.get("severity") != "warning" and r["code"] != "weekly_value_conflict_preserved"]
        if fatal:
            return _blocked(fatal, scan)
        mutable_active = _changed_active(scan, projected)
        if jobs and not legacy and mutable_active:
            _fail("partial_migration_without_journal")
        required = legacy or mutable_active or bool(journal)
        actions = []
        destinations = {}
        def write(source, target, payload):
            target = str(target)
            existing = destinations.get(target)
            if existing is not None and existing != payload:
                _fail("conflicting_destination", target)
            destinations[target] = payload
            scan.file(target)
            if source != target and scan.inputs[target]["exists"]:
                if target not in scan.records or scan.records[target]["data"] != payload:
                    _fail("destination_already_exists", target)
            if source == target and source in scan.records and scan.records[source]["data"] == payload:
                return
            encoded = encode_target_json(payload)
            mode = scan.inputs[target].get("mode", scan.inputs[source].get("mode", 0o600))
            after = {"exists": True, "size": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest(), "mode": mode}
            actions.append({"kind": "write_json", "source": source, "target": target,
                            "data": payload, "after": after})
        if required:
            for job_id, job in jobs.items():
                source = sources[job_id]
                target = str(jobs_dir / (job_id + ".json"))
                write(source, target, job)
                if source != target:
                    actions.append({"kind": "retire_source", "source": source, "target": target})
            for target, row in projected["records"].items():
                origins = row.get("sources", [target])
                # Projector retains explicit source metadata on renamed records.
                source = target if target in origins else row.get("source", origins[0])
                if source not in scan.inputs:
                    source = next((p for p, r in records.items() if r.get("target_path") == target), target)
                if row["kind"] == "widget_cache":
                    actions.append({"kind": "rebuild_derived", "source": source, "target": target})
                    continue
                write(source, target, row["data"])
                for old in origins:
                    if old != target and old in scan.inputs:
                        actions.append({"kind": "retire_source", "source": old, "target": target})
                if source != target and source not in origins:
                    actions.append({"kind": "retire_source", "source": source, "target": target})
            # Derived caches deliberately have no projected payload: rebuilding
            # must use the final verified graph, not copy old display keys.
            for path, row in records.items():
                if row["kind"] == "widget_cache" and path not in projected["records"]:
                    actions.append({"kind": "rebuild_derived", "source": path, "target": path})
        for action in actions:
            action["id"] = hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()
        plan = {
            "schema_version": 1, "migration_id": MIGRATION_ID,
            "classification": "applicable" if required else "not_applicable",
            "status": "pending" if required else "not_applicable", "required": bool(required),
            "jobs": jobs, "aliases": aliases, "id_map": aliases, "job_sources": sources,
            "inputs": scan.inputs, "inventory_groups": scan.groups,
            "actions": actions, "records": projected["records"],
            "bindings": projected.get("bindings", []), "unassigned": projected.get("unassigned", []),
            "reasons": reasons + ([{"code": "resume_existing_mapping", "severity": "warning", "source": "", "locator": ""}] if journal else []),
            "prerequisites": {"managed_cron_captured": isinstance(cron_text, str)},
            "external_inputs": {"managed_cron": {"kind": "crontab", "text": cron_text}} if isinstance(cron_text, str) else {},
            "activation_allowed": False,
        }
        # End-of-scan revalidation catches concurrent edits/additions, including
        # destinations that were previously absent. Still no writer permission.
        plan = storage.seal_plan(plan)
        storage.verify_inputs(plan)
        return plan
    except PlanningError as exc:
        return _blocked([{"code": exc.code, "source": exc.source, "locator": ""}], scan)
    except storage.IdentityStorageError as exc:
        return _blocked([{"code": exc.code, "source": "", "locator": ""}], scan)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return _blocked([{"code": "invalid_owned_state", "source": "", "locator": ""}], scan)


def _blocked(reasons, scan=None):
    return {"migration_id": MIGRATION_ID, "required": True, "classification": "blocked",
            "status": "blocked", "jobs": {}, "aliases": {}, "id_map": {}, "actions": [],
            "records": {}, "bindings": [], "unassigned": [], "reasons": reasons,
            "activation_allowed": False}


def detect(config, *, control_root=None):
    """Runner-shaped read-only summary. Blocked never means required=False."""
    plan = build_plan(config, control_root=control_root)
    return {key: plan[key] for key in ("migration_id", "required", "classification", "status", "reasons")}


def verify_target(config, *, control_root=None):
    """Read actual target files, never authorize services from a proposed plan."""
    return _verify_target(config, control_root=control_root, allow_derived_rebuild=False)


def verify_active_target(config, *, control_root=None):
    """Verify actual startup identity references, permitting widget recreation.

    Only the derived ``widget_rebuild_required`` warning is allowed beyond the
    strict cutover check. The startup coordinator still owns writer admission
    and the gated widget refresh; this read-only result never enables either.
    """
    return _verify_target(config, control_root=control_root, allow_derived_rebuild=True)


def _verify_target(config, *, control_root, allow_derived_rebuild):
    plan = build_plan(config, control_root=control_root)
    reasons = list(plan.get("reasons", []))
    if plan["classification"] != "not_applicable":
        reasons.append({"code": "identity_cutover_incomplete", "source": "", "locator": ""})
    else:
        try:
            # Verify source records, not replacements that could conceal a
            # stale FK. Both scans must represent the same complete graph.
            scan, _, _, _ = _inventory(config, control_root)
            if scan.inputs != plan["inputs"] or scan.groups != plan["inventory_groups"]:
                _fail("source_fingerprint_changed")
            records = {p: r for p, r in scan.records.items() if r["kind"] not in {"job", "storages"}}
            for path, row in records.items():
                if row["kind"] == "restore_test":
                    row["legacy_key"] = Path(path).stem
            reasons.extend(verify_records(records, plan["jobs"], plan["aliases"]))
            storage.verify_inputs(plan)
        except PlanningError as exc:
            reasons.append({"code": exc.code, "source": exc.source, "locator": ""})
        except storage.IdentityStorageError as exc:
            reasons.append({"code": exc.code, "source": "", "locator": ""})
        except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
            reasons.append({"code": "invalid_owned_state", "source": "", "locator": ""})
    fatal = [r for r in reasons if r.get("severity") != "warning"
             or r["code"] == "widget_rebuild_required" and not allow_derived_rebuild]
    return {"valid": not fatal, "reasons": reasons, "writable_services_allowed": False,
            "activation_allowed": False, "migration_id": MIGRATION_ID}
