"""Canonical, immutable job metadata contract (#447, #473).

Pure validation and edit operations. Legacy conversion belongs exclusively to
the explicit migration boundary, never to a read or an ordinary wizard save.
"""

from copy import deepcopy
import re
from uuid import UUID

from job_source_paths import normalize_source_paths


JOB_SCHEMA_VERSION = 4
MUTABLE_IDENTITY_FIELDS = {"job_key", "backup_type", "type_id", "location"}
ARCHIVE_TIMESTAMP_PATTERN = "YYYY-MM-DD_HH-mm-ss"
_SAFE = re.compile(r"[A-Za-z0-9_.-]+")


class JobValidationError(ValueError):
    def __init__(self, code, message):
        self.api_code = code
        super().__init__(message)


def validate_job_id(value):
    try:
        parsed = UUID(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.version != 4 or str(parsed) != value:
        raise JobValidationError("invalid_job_id", "A canonical UUIDv4 job_id is required")
    return value


def validate_archive_prefix(value):
    if not isinstance(value, str) or not _SAFE.fullmatch(value) or value in {".", ".."}:
        raise JobValidationError("invalid_archive_prefix", "Archive prefix must use letters, digits, dots, underscores or hyphens; '.' and '..' are not allowed")
    return value


def archive_name_preview(prefix):
    return validate_archive_prefix(prefix) + "-" + ARCHIVE_TIMESTAMP_PATTERN


def updated_archive_prefixes(prefix, previous):
    validate_archive_prefix(prefix)
    if not isinstance(previous, list):
        raise JobValidationError("invalid_archive_prefix", "Archive prefix history must be a list")
    for value in previous:
        validate_archive_prefix(value)
    return list(dict.fromkeys([prefix, *previous]))


def validate_job(meta, *, filename=None):
    """Validate without repairing, allocating an ID, or discarding fields."""
    if not isinstance(meta, dict) or type(meta.get("schema_version")) is not int or meta["schema_version"] != JOB_SCHEMA_VERSION:
        raise JobValidationError("job_migration_required", "Job metadata requires the explicit identity migration")
    job_id = validate_job_id(meta.get("job_id"))
    if filename is not None and filename != job_id + ".json":
        raise JobValidationError("invalid_job_filename", "Job filename does not match job_id")
    if MUTABLE_IDENTITY_FIELDS.intersection(meta):
        raise JobValidationError("mutable_job_identity", "Canonical metadata must not contain mutable identity fields")
    if not isinstance(meta.get("name"), str) or not meta["name"].strip():
        raise JobValidationError("invalid_job_name", "Job name must not be empty")
    repo = meta.get("repository_key")
    if not isinstance(repo, str) or not _SAFE.fullmatch(repo):
        raise JobValidationError("invalid_job_repository", "A repository_key is required")
    prefixes = meta.get("archive_prefixes")
    if not isinstance(prefixes, list) or not prefixes or updated_archive_prefixes(prefixes[0], prefixes) != prefixes:
        raise JobValidationError("invalid_archive_prefix", "Archive prefixes must be nonempty, ordered and unique")
    aliases = meta.get("legacy_job_keys")
    if not isinstance(aliases, list) or any(not isinstance(a, str) or not _SAFE.fullmatch(a) for a in aliases) or len(set(aliases)) != len(aliases):
        raise JobValidationError("invalid_job_aliases", "Legacy aliases must be an ordered list of unique exact identifiers")
    if normalize_source_paths(meta.get("source_paths")) != meta.get("source_paths"):
        raise JobValidationError("invalid_source_paths", "Source paths must be canonical")
    for field in ("enabled", "file_activity", "mount_before_run", "unmount_after_run"):
        if field in meta and type(meta[field]) is not bool:
            raise JobValidationError("invalid_job_settings", "A boolean job setting has an unsupported value")
    if "compression" in meta and (not isinstance(meta["compression"], str) or not meta["compression"].strip()):
        raise JobValidationError("invalid_job_settings", "Compression must be a nonempty string")
    features = meta.get("features", {})
    if not isinstance(features, dict) or any(type(features.get(kind, False)) is not bool for kind in ("docker", "vm")):
        raise JobValidationError("invalid_runtime_control", "Unsupported job feature settings")
    for kind in ("docker", "vm"):
        control = meta.get(kind + "_control")
        if control is None and kind + "_control" not in meta:
            continue
        modes = {"all", "selected", "none"} | ({"except_selected"} if kind == "docker" else set())
        if not isinstance(control, dict) or not isinstance(control.get("mode"), str) or control["mode"] not in modes:
            raise JobValidationError("invalid_runtime_control", "Unsupported runtime control mode")
        selected = control.get("selected", [])
        if not isinstance(selected, list) or any(not isinstance(v, str) or not v.strip() for v in selected):
            raise JobValidationError("invalid_runtime_control", "Invalid runtime selection")
        ack = "ack_appdata_risk" if kind == "docker" else "ack_domains_risk"
        if ack in control and type(control[ack]) is not bool:
            raise JobValidationError("invalid_runtime_control", "Invalid runtime acknowledgement")
    if "retention" in meta:
        retention = meta["retention"]
        if not isinstance(retention, dict) or any(
            key in retention and (not isinstance(retention[key], str) or not re.fullmatch(r"[0-9]+", retention[key]))
            for key in ("daily", "weekly", "monthly", "yearly")
        ):
            raise JobValidationError("invalid_retention", "Unsupported retention settings")
    return meta


def validate_job_inventory(jobs):
    """Reject alias collisions and shared-repository prefix ownership overlap."""
    aliases, ownership = {}, []
    for job_id, job in jobs.items():
        validate_job(job, filename=job_id + ".json")
        for alias in job["legacy_job_keys"]:
            if alias in aliases or (alias in jobs and alias != job_id):
                raise JobValidationError("ambiguous_job_alias", "A legacy alias has conflicting owners")
            aliases[alias] = job_id
        for prefix in job["archive_prefixes"]:
            for other_repo, other_prefix, other_id in ownership:
                if other_repo == job["repository_key"] and other_id != job_id and (
                    prefix == other_prefix or prefix.startswith(other_prefix + "-") or other_prefix.startswith(prefix + "-")
                ):
                    raise JobValidationError("ambiguous_archive_ownership", "Archive prefixes overlap with another job in the selected repository")
            ownership.append((job["repository_key"], prefix, job_id))


def new_job_defaults():
    return {
        "schema_version": JOB_SCHEMA_VERSION, "legacy_job_keys": [],
        "description": "", "icon": "sonstiges", "icon_color": "", "enabled": True,
        "standard": "wizard", "runner": "scriptless-wizard-runner", "script": "",
        "mount_before_run": True, "unmount_after_run": True,
        "exclude_paths": [], "compression": "lz4", "file_activity": False,
        "features": {"docker": False, "vm": False},
        "docker_control": {"mode": "none", "selected": [], "ack_appdata_risk": False},
        "vm_control": {"mode": "none", "selected": [], "ack_domains_risk": False},
        "retention": {"daily": "7", "weekly": "4", "monthly": "6", "yearly": "3"},
    }


def job_to_params(meta):
    """Only expose wizard-owned fields, not unknown settings or secrets."""
    result = {key: deepcopy(meta[key]) for key in (
        "description", "icon", "icon_color", "source_paths", "exclude_paths",
        "repository_key", "mount_before_run", "unmount_after_run", "compression",
        "file_activity", "docker_control", "vm_control",
    ) if key in meta}
    result.update(job_name=meta.get("name", ""), archive_prefix=(meta.get("archive_prefixes") or [""])[0])
    for key, value in meta.get("retention", {}).items():
        if key in {"daily", "weekly", "monthly", "yearly"}:
            result["keep_" + key] = value
    return result


def apply_wizard_changes(params, *, existing=None, job_id, now, duplicate=False):
    """Patch exposed fields; retain every other existing setting verbatim."""
    if existing is not None:
        validate_job(existing)
        if not duplicate and job_id != existing["job_id"]:
            raise JobValidationError("immutable_job_id", "Editing cannot change job_id")
    result = deepcopy(existing) if existing is not None else new_job_defaults()
    fresh = existing is None or duplicate
    result.update(schema_version=JOB_SCHEMA_VERSION, job_id=validate_job_id(job_id), updated_at=now)
    if fresh:
        result.update(created_at=now, legacy_job_keys=[])
    if "job_name" in params:
        result["name"] = params["job_name"].strip()
    prefix = params.get("archive_prefix", (result.get("archive_prefixes") or [""])[0])
    result["archive_prefixes"] = updated_archive_prefixes(prefix, [] if fresh else result.get("archive_prefixes", []))
    for key in (
        "description", "icon", "icon_color", "repository_key", "source_paths", "exclude_paths",
        "compression", "file_activity", "mount_before_run", "unmount_after_run",
    ):
        if key in params:
            result[key] = deepcopy(params[key])
    for kind in ("docker", "vm"):
        key = kind + "_control"
        if key in params:
            result.setdefault(key, {}).update(deepcopy(params[key]))
            result.setdefault("features", {})[kind] = result[key]["mode"] != "none"
    for period in ("daily", "weekly", "monthly", "yearly"):
        if "keep_" + period in params:
            result.setdefault("retention", {})[period] = params["keep_" + period]
    validate_job(result)
    return result
