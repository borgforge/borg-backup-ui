"""Pure dependent-record projection for the inactive #447 identity migration.

No file, process, Borg, scheduler or application helpers are called here. The
scanner supplies owned records as ``path -> {kind, data, ...}``; ``target_path``
may be supplied for restore tests and a shared weekly destination. Results are
plans, never permission to write. ``sources`` identifies exact consumed files.

Existing store schema versions are retained. ``identity_schema_version = 1``
marks new enriched collections; canonical schema-1 records are also accepted.
Weekly observations have their own version-1 envelope with source provenance.
Historical descriptors are preserved, while active ``job_key`` references move
to ``legacy_job_key``. Later phases must implement readers for these shapes.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any
from uuid import UUID


_TERMINAL = {"done", "error", "aborted"}
_COLLECTIONS = {
    "notification_queue": ("queue", True),
    "notification_deliveries": ("deliveries", False),
    "runtime_recovery": ("entries", True),
    "restore_index": ("runs", False),
}
_DIRECT = {"status", "restore_test", "restore_detail", "control", "cancel_request", "resource_lock", "run_context"}
_STATUS_FILENAME = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(.+)\.status$")
_RESTORE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_RESTORE_SHARED_FIELDS = (
    "state", "archive", "started_at", "finished_at", "source_path", "target_dir",
    "destination_path", "conflict_mode", "preserve_owner", "repository_key",
    "repository_snapshot", "job_name_snapshot", "archive_prefix_snapshot",
)


def _pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
        return str(parsed) == value and parsed.version == 4 and parsed.variant == "specified in RFC 4122"
    except ValueError:
        return False


def _json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


class _Projection:
    def __init__(self, records: dict, jobs: dict, aliases: dict, *, verify: bool = False):
        self.input = records
        self.jobs = jobs
        self.aliases = aliases
        self.verify = verify
        self.records: dict = {}
        self.bindings: list = []
        self.unassigned: list = []
        self.reasons: list = []
        self.restore_links: dict = {}
        self.required = False

    def reason(self, code: str, source: str, locator: str = "", *, severity: str = "error") -> None:
        item = {"code": code, "source": source, "locator": locator, "severity": severity}
        if item not in self.reasons:
            self.reasons.append(item)

    def schema(self, data: Any, source: str, locator: str = "") -> bool:
        if not isinstance(data, dict):
            self.reason("invalid_owned_record", source, locator)
            return False
        for field in ("schema_version", "identity_schema_version"):
            if field in data and (type(data[field]) is not int or data[field] != 1):
                self.reason("unsupported_record_schema", source, locator)
                return False
        return True

    def resolve(self, raw: Any, source: str, locator: str, *, active: bool,
                code: str = "orphan_active_reference") -> str | None:
        if not isinstance(raw, str) or not raw:
            self.reason("invalid_identity_reference", source, locator)
            return None
        if raw in self.jobs and _uuid(raw):
            return raw
        if raw in self.aliases and self.aliases[raw] in self.jobs:
            if active:
                self.required = True
            if self.verify and active:
                self.reason("mutable_active_reference", source, locator)
                return None
            return self.aliases[raw]
        if active:
            self.reason(code, source, locator)
        return None

    def bind(self, source: str, locator: str, job_id: str | None, legacy: str,
             role: str, original: Any, reason: str = "no_configured_job") -> None:
        self.bindings.append({"source": source, "locator": locator, "job_id": job_id,
                              "legacy_key": legacy, "role": role})
        if job_id is None and role != "system":
            self.unassigned.append({"source": source, "locator": locator,
                                    "reason": reason, "data": deepcopy(original)})

    def restore_link(self, source: str, locator: str, job_id: str | None,
                     legacy: str, kind: str, row: dict) -> None:
        restore_id = row.get("restore_id")
        if (not isinstance(restore_id, str) or not _RESTORE_ID.fullmatch(restore_id)
                or restore_id in {".", ".."}):
            self.reason("invalid_restore_id", source, locator)
            return
        if kind == "restore_detail" and source.rsplit("/", 1)[-1] != restore_id + ".json":
            self.reason("restore_detail_filename_mismatch", source, locator)
        self.restore_links.setdefault(restore_id, []).append(
            (source, locator, job_id, legacy, kind, row))

    def row(self, data: Any, source: str, locator: str, kind: str,
            *, active: bool = False, legacy: str = "") -> Any:
        if not self.schema(data, source, locator):
            return deepcopy(data)
        original = deepcopy(data)
        row = deepcopy(data)
        if kind == "run_context":
            try:
                from job_runs import validate_run_context
                validate_run_context(row, row.get("job_id"), row.get("run_id"))
                if source.rsplit("/", 2)[-2] != row["run_id"]:
                    raise ValueError("Run directory does not match the payload")
            except (ValueError, OSError, TypeError, KeyError, AttributeError):
                self.reason("invalid_run_context", source, locator)
                return row
        if kind.startswith("restore_") and kind != "restore_test":
            state = row.get("state")
            if not isinstance(state, str) or state not in _TERMINAL | {"running"}:
                self.reason("invalid_restore_state", source, locator)
            active = state not in _TERMINAL
            if kind in {"restore_index", "restore_detail"} and state not in _TERMINAL:
                self.reason("nonterminal_restore_history", source, locator)
            if kind == "restore_runs" and state in _TERMINAL:
                self.reason("terminal_restore_in_active_store", source, locator)
        if kind == "runtime_recovery":
            if row.get("state") not in {"pending_restart", "restart_failed"}:
                self.reason("unknown_recovery_state", source, locator)
            if not isinstance(row.get("targets"), list) or not row["targets"]:
                self.reason("invalid_recovery_targets", source, locator)
            else:
                target_ids = []
                for target in row["targets"]:
                    if (not isinstance(target, dict) or not isinstance(target.get("id"), str)
                            or not target["id"] or not isinstance(target.get("name"), str) or not target["name"]):
                        self.reason("invalid_recovery_targets", source, locator)
                    else:
                        target_ids.append(target["id"])
                if len(set(target_ids)) != len(target_ids):
                    self.reason("invalid_recovery_targets", source, locator)
        if kind in {"control", "cancel_request", "resource_lock"}:
            active = kind != "control" or row.get("finished") is not True
            if ("run_id" in row and (not isinstance(row["run_id"], str) or not row["run_id"])):
                self.reason("invalid_run_id", source, locator)
            if "pid" in row and (type(row["pid"]) is not int or row["pid"] < 0):
                self.reason("invalid_owner_pid", source, locator)
        raw_key = row.get("job_key", row.get("legacy_job_key", ""))
        if raw_key and not isinstance(raw_key, str):
            self.reason("invalid_identity_reference", source, locator)
            return row
        payload_key = ""
        type_field = "backup_type"
        location_field = "backup_location" if kind == "runtime_recovery" else "location"
        if type_field in row or location_field in row:
            backup_type, location = row.get(type_field), row.get(location_field)
            if not isinstance(backup_type, str) or not backup_type or not isinstance(location, str) or not location:
                self.reason("invalid_identity_descriptor", source, locator)
                return row
            payload_key = backup_type + "_" + location
        candidates = [value for value in (raw_key, payload_key, legacy) if value]
        is_system = (kind in {"notification_queue", "notification_deliveries"}
                     and not row.get("job_id")
                     and ((raw_key == "restore_test" and row.get("source") == "restore_test")
                          or (not raw_key and row.get("source") == "system")))
        if kind in {"notification_queue", "notification_deliveries"} and not row.get("job_id") and not raw_key:
            is_system = row.get("service") in {"restore_test", "system"}
        if kind == "resource_lock" and not row.get("job_id") and row.get("service") == "restore":
            is_system = row.get("operation") == "restore"
        if kind == "resource_lock" and not row.get("job_id") and raw_key == "restore_test":
            is_system = row.get("operation") == "restore_test"
        if is_system:
            self.bind(source, locator, None, raw_key, "system", original)
            return row
        if not active and row.get("identity_state") == "unassigned":
            self.bind(source, locator, None, raw_key or legacy, "history", original,
                      row.get("identity_reason", "no_configured_job"))
            if kind in {"restore_runs", "restore_index", "restore_detail"}:
                self.restore_link(source, locator, None, raw_key or legacy, kind, row)
            return row
        if kind == "status" and not payload_key and not row.get("job_id"):
            self.reason("invalid_status_identity", source, locator)
            return row
        conflict = len(set(candidates)) > 1
        resolved = {self.aliases.get(value, value if value in self.jobs else None) for value in candidates}
        if conflict and len(resolved) == 1 and None not in resolved:
            conflict = False
        supplied_id = row.get("job_id")
        if supplied_id is not None and not _uuid(supplied_id):
            self.reason("invalid_job_id", source, locator)
            return row
        if supplied_id and any(value is not None and value != supplied_id for value in resolved):
            conflict = True
        key = candidates[0] if candidates else ""
        code = {"notification_queue": "orphan_active_notification",
                "runtime_recovery": "orphan_runtime_recovery",
                "restore_runs": "orphan_active_restore"}.get(kind, "orphan_active_reference")
        if conflict:
            if active:
                self.reason("conflicting_active_identity", source, locator)
            elif self.verify or supplied_id:
                self.reason("conflicting_canonical_identity", source, locator)
            job_id = None
        elif supplied_id:
            job_id = self.resolve(supplied_id, source, locator, active=active, code=code)
            if self.verify and active and "job_key" in row:
                self.reason("mutable_active_reference", source, locator)
        elif key:
            job_id = self.resolve(key, source, locator, active=active, code=code)
            if self.verify and job_id is not None:
                self.reason("missing_canonical_job_id", source, locator)
        else:
            if active:
                self.reason(code, source, locator)
            job_id = None
        historical_reason = "conflicting_identity_evidence" if conflict else "no_configured_job"
        if not active and supplied_id and job_id is None and not conflict:
            historical_reason = "deleted_job"
        elif not active and job_id is None and not conflict and payload_key:
            # A former prefix can explain the diagnostic, never establish an
            # alias. Keep the historical record unassigned even with one hint.
            former_prefix = str(row.get("backup_type")) + "-backup"
            if any(former_prefix in job.get("archive_prefixes", []) for job in self.jobs.values()):
                historical_reason = "no_authoritative_alias"
        self.bind(source, locator, job_id, key, "active" if active else "history", original, historical_reason)
        if job_id is not None:
            row["job_id"] = job_id
            if not supplied_id:
                row.setdefault("schema_version", 1)
            if active and "job_key" in row:
                if "legacy_job_key" in row and row["legacy_job_key"] != row["job_key"]:
                    self.reason("conflicting_active_identity", source, locator)
                row["legacy_job_key"] = row.pop("job_key")
        else:
            # Keep unknown historical IDs/descriptors, but never imply a live job.
            row["identity_state"] = "unassigned"
            row["identity_reason"] = historical_reason
            row.setdefault("identity_schema_version", 1)
        if kind in {"restore_runs", "restore_index", "restore_detail"}:
            self.restore_link(source, locator, job_id, key, kind, row)
        return row

    def emit(self, source: str, record: dict, data: Any, *, sources: list | None = None) -> None:
        target = record.get("target_path", source)
        if not isinstance(target, str) or not target.startswith("/"):
            self.reason("invalid_target_path", source)
            return
        if target in self.records:
            self.reason("target_collision", source)
            return
        self.records[target] = {**deepcopy(record), "data": data,
                                "sources": sources or [source], "target_path": target}

    def schedules(self, source: str, record: dict) -> None:
        data = record["data"]
        if not isinstance(data, dict):
            self.reason("invalid_owned_record", source)
            return
        result = {}
        for key, row in data.items():
            locator = "/" + _pointer(key)
            if (not isinstance(row, dict) or not isinstance(row.get("cron"), str)
                    or ("enabled" in row and type(row["enabled"]) is not bool)):
                self.reason("invalid_schedule", source, locator)
                continue
            cron = row["cron"]
            if ((cron and (len(cron.split()) != 5 or any(not re.fullmatch(r"[\d*/,\-]+", part) for part in cron.split())))
                    or (not cron and row.get("enabled", True))):
                self.reason("invalid_schedule", source, locator)
                continue
            if key == "restore_test":
                result[key] = deepcopy(row)
                continue
            job_id = self.resolve(key, source, locator, active=True, code="orphan_active_schedule")
            if job_id is None:
                continue
            self.bind(source, locator, job_id, key, "active", row)
            if job_id in result:
                self.reason("duplicate_schedule_identity", source, locator)
            else:
                result[job_id] = deepcopy(row)
        self.emit(source, record, result)

    def repositories(self, source: str, record: dict) -> None:
        data = deepcopy(record["data"])
        if not self.schema(data, source) or not isinstance(data.get("repositories"), list):
            self.reason("invalid_repository_store", source)
            return
        seen = set()
        for index, row in enumerate(data["repositories"]):
            locator = f"/repositories/{index}"
            if not isinstance(row, dict) or not isinstance(row.get("repository_key"), str):
                self.reason("invalid_repository", source, locator)
                continue
            repo = row["repository_key"]
            if repo in seen:
                self.reason("duplicate_repository_key", source, locator)
            seen.add(repo)
            expected = {job_id for job_id, job in self.jobs.items() if job.get("repository_key") == repo}
            for old, new in (("used_by", "job_ids"), ("source_job_keys", "source_job_ids")):
                if old in row and new in row:
                    self.reason("mixed_repository_identity", source, locator)
                    continue
                field = old if old in row else new
                if field == old:
                    self.required = True
                values = row.get(field, [])
                if not isinstance(values, list):
                    self.reason("invalid_repository_references", source, locator + "/" + field)
                    continue
                converted = []
                for i, value in enumerate(values):
                    pointer = locator + f"/{field}/{i}"
                    if self.verify and field == old:
                        self.reason("mutable_active_reference", source, pointer)
                    job_id = self.resolve(value, source, pointer, active=True, code="orphan_repository_reference")
                    if job_id is not None:
                        self.bind(source, pointer, job_id, value, "active", value)
                        converted.append(job_id)
                if len(set(converted)) != len(converted) or set(converted) != expected:
                    self.reason("repository_assignment_mismatch", source, locator + "/" + field)
                row.pop(old, None)
                row[new] = converted
        self.emit(source, record, data)

    def reminders(self, source: str, record: dict) -> None:
        data = deepcopy(record["data"])
        if not self.schema(data, source) or not isinstance(data.get("last_sent"), dict):
            self.reason("invalid_reminder_store", source)
            return
        converted = {}
        unassigned = deepcopy(data.get("unassigned", []))
        if not isinstance(unassigned, list):
            self.reason("invalid_reminder_store", source)
            return
        for key, value in data["last_sent"].items():
            locator = "/last_sent/" + _pointer(key)
            parts = key.split(":", 2)
            if (len(parts) != 3 or not all(parts) or type(value) not in (int, float)
                    or value < 0):
                self.reason("invalid_reminder_record", source, locator)
                continue
            event, job_key, due = parts
            job_id = self.resolve(job_key, source, locator, active=False)
            self.bind(source, locator, job_id, job_key, "history", value)
            if job_id is None:
                unassigned.append({"key": key, "value": value, "source": source, "locator": locator})
                continue
            if self.verify and job_key != job_id:
                self.reason("mutable_active_reference", source, locator)
            if job_key != job_id:
                self.required = True
            new_key = f"{event}:{job_id}:{due}"
            if new_key in converted and converted[new_key] != value:
                self.reason("reminder_identity_collision", source, locator)
            converted[new_key] = value
        data["last_sent"] = converted
        if unassigned:
            data["unassigned"] = unassigned
        self.emit(source, record, data)

    def weekly(self, sources: list[tuple[str, dict]]) -> None:
        groups: dict = {}
        targets = {record.get("target_path", source) for source, record in sources}
        if len(targets) != 1:
            self.reason("weekly_destination_mismatch", sources[0][0])
            return
        canonical = all(isinstance(record["data"], dict) and "observations" in record["data"]
                        for _, record in sources)
        if self.verify and (not canonical or len(sources) != 1):
            self.reason("legacy_weekly_store", sources[0][0])
        for source, record in sources:
            data = record["data"]
            if not isinstance(data, dict):
                self.reason("invalid_weekly_store", source)
                continue
            if "observations" in data:
                if not self.schema(data, source) or not isinstance(data["observations"], list):
                    self.reason("invalid_weekly_store", source)
                    continue
                entries = [(row.get("job_id") or row.get("legacy_job_key", ""), row,
                            f"/observations/{i}") for i, row in enumerate(data["observations"]) if isinstance(row, dict)]
                if len(entries) != len(data["observations"]):
                    self.reason("invalid_weekly_record", source)
            else:
                entries = []
                for key, rows in data.items():
                    if not isinstance(rows, list):
                        self.reason("invalid_weekly_store", source, "/" + _pointer(key))
                        continue
                    entries.extend((key, row, f"/{_pointer(key)}/{i}") for i, row in enumerate(rows))
            for key, original, locator in entries:
                if (not isinstance(original, dict) or not isinstance(original.get("week"), str)
                        or type(original.get("size")) is not int or original["size"] < 0):
                    self.reason("invalid_weekly_record", source, locator)
                    continue
                supplied_id = original.get("job_id")
                if supplied_id is not None and not _uuid(supplied_id):
                    self.reason("invalid_job_id", source, locator)
                    continue
                legacy_id = self.aliases.get(original.get("legacy_job_key", ""))
                if (supplied_id and legacy_id is not None and supplied_id != legacy_id
                        and original.get("identity_state") != "unassigned"):
                    self.reason("conflicting_canonical_identity", source, locator)
                job_id = (None if original.get("identity_state") == "unassigned"
                          else self.resolve(key, source, locator, active=False))
                history_reason = "deleted_job" if supplied_id and job_id is None else "no_configured_job"
                if original.get("identity_state") == "unassigned":
                    history_reason = original.get("identity_reason") or history_reason
                self.bind(source, locator, job_id, key, "history", original, history_reason)
                if self.verify and job_id and key != job_id:
                    self.reason("mutable_active_reference", source, locator)
                row = deepcopy(original)
                # A deleted job is absent from the active graph, not stripped
                # of its former immutable identity in retained history.
                row["job_id"] = supplied_id or job_id
                if not canonical:
                    row["legacy_job_key"] = key
                if job_id is None and (not self.verify or not supplied_id or "identity_state" in original):
                    row["identity_state"] = "unassigned"
                    if supplied_id:
                        row["identity_reason"] = history_reason
                provenance = row.pop("source_records", [{"source": source, "locator": locator}])
                row.pop("conflict", None)
                if not isinstance(provenance, list) or not provenance:
                    self.reason("invalid_weekly_provenance", source, locator)
                    continue
                identity = _json_key(row)
                if identity not in groups:
                    groups[identity] = {**row, "source_records": []}
                for evidence in provenance:
                    if (not isinstance(evidence, dict) or not isinstance(evidence.get("source"), str)
                            or not isinstance(evidence.get("locator"), str)):
                        self.reason("invalid_weekly_provenance", source, locator)
                    elif evidence not in groups[identity]["source_records"]:
                        groups[identity]["source_records"].append(evidence)
        observations = list(groups.values())
        by_week: dict = {}
        for row in observations:
            owner = row.get("job_id") or row.get("legacy_job_key")
            by_week.setdefault((owner, row["week"]), set()).add(row["size"])
        for row in observations:
            owner = row.get("job_id") or row.get("legacy_job_key")
            if len(by_week[(owner, row["week"])]) > 1:
                row["conflict"] = True
                self.reason("weekly_value_conflict_preserved", sources[0][0], severity="warning")
        payload = (deepcopy(sources[0][1]["data"]) if canonical and len(sources) == 1 else {})
        payload.update({"schema_version": 1, "identity_schema_version": 1, "observations": observations})
        source, record = sources[0]
        if self.verify and canonical and len(sources) == 1 and payload != record["data"]:
            self.reason("weekly_projection_mismatch", source)
        self.emit(source, record, payload, sources=[path for path, _ in sources])

    def run(self) -> dict:
        weekly = []
        for source, record in sorted(self.input.items()):
            if (not isinstance(source, str) or not source.startswith("/") or not isinstance(record, dict)
                    or "data" not in record or not isinstance(record.get("kind"), str)):
                self.reason("invalid_owned_record", str(source))
                continue
            kind, data = record["kind"], record["data"]
            if kind == "weekly":
                weekly.append((source, record))
            elif kind == "schedules":
                self.schedules(source, record)
            elif kind == "repositories":
                self.repositories(source, record)
            elif kind == "notification_state":
                self.reminders(source, record)
            elif kind in _DIRECT:
                legacy = record.get("legacy_key", "")
                if kind == "status" and isinstance(data, dict) and not data.get("job_id"):
                    match = _STATUS_FILENAME.fullmatch(source.rsplit("/", 1)[-1])
                    legacy = match.group(1) if match else legacy
                output = self.row(data, source, "", kind, legacy=legacy)
                proof = data if self.verify else output
                if (kind == "restore_test" and isinstance(proof, dict)
                        and proof.get("identity_state") != "unassigned" and _uuid(proof.get("job_id"))):
                    target = source if self.verify else record.get("target_path", source)
                    if isinstance(target, str) and target.rsplit("/", 1)[-1] != proof["job_id"] + ".test":
                        self.reason("restore_test_filename_mismatch", source)
                self.emit(source, record, output)
            elif kind in _COLLECTIONS:
                field, active = _COLLECTIONS[kind]
                if not self.schema(data, source) or not isinstance(data.get(field), list):
                    self.reason("invalid_owned_collection", source)
                    continue
                output = deepcopy(data)
                output[field] = [self.row(row, source, f"/{field}/{index}", kind, active=active)
                                 for index, row in enumerate(data[field])]
                self.emit(source, record, output)
            elif kind == "restore_runs":
                if not self.schema(data, source) or not isinstance(data.get("runs"), dict):
                    self.reason("invalid_owned_collection", source)
                    continue
                output = deepcopy(data)
                for restore_id, row in data["runs"].items():
                    locator = "/runs/" + _pointer(restore_id)
                    if not isinstance(row, dict) or row.get("restore_id") != restore_id:
                        self.reason("restore_id_mismatch", source, locator)
                    output["runs"][restore_id] = self.row(row, source, locator, kind, active=True)
                self.emit(source, record, output)
            elif kind == "storages":
                if self.schema(data, source) and isinstance(data.get("storages"), list):
                    self.emit(source, record, deepcopy(data))
                else:
                    self.reason("invalid_storage_store", source)
            elif kind == "widget_cache":
                # Derived caches cannot survive cutover as active legacy joins.
                # Rebuild is owned by #476/#479 under the startup writer gate.
                if self.schema(data, source):
                    self.reason("widget_rebuild_required", source, severity="warning")
            else:
                self.reason("unsupported_record_kind", source)
        if weekly:
            self.weekly(weekly)
        for links in self.restore_links.values():
            assigned = {(entry[2], entry[5].get("job_id") or entry[3]) if entry[2] is None
                        else (entry[2], "") for entry in links}
            if len(assigned) > 1:
                for source, locator, *_ in links:
                    self.reason("restore_identity_mismatch", source, locator)
            by_kind = {kind: [entry for entry in links if entry[4] == kind]
                       for kind in ("restore_index", "restore_detail", "restore_runs")}
            for entries in by_kind.values():
                if len(entries) > 1:
                    for source, locator, *_ in entries:
                        self.reason("duplicate_restore_id", source, locator)
            index, detail, active = (by_kind[kind] for kind in ("restore_index", "restore_detail", "restore_runs"))
            if (index or detail) and active:
                for source, locator, *_ in links:
                    self.reason("restore_active_history_collision", source, locator)
            if index and not detail:
                for source, locator, *_ in index:
                    self.reason("missing_restore_detail", source, locator)
            if detail and not index:
                for source, locator, *_ in detail:
                    self.reason("missing_restore_index_entry", source, locator)
            if len(index) == len(detail) == 1:
                summary, body = index[0][5], detail[0][5]
                if any((field in summary) != (field in body) or summary.get(field) != body.get(field)
                       for field in _RESTORE_SHARED_FIELDS):
                    for source, locator, *_ in index + detail:
                        self.reason("restore_snapshot_mismatch", source, locator)
        return {"records": self.records, "bindings": self.bindings,
                "unassigned": self.unassigned, "reasons": self.reasons,
                "required": self.required}


def project_records(records: dict, jobs: dict, aliases: dict) -> dict:
    """Project validated owned stores without touching input objects or disk."""
    return _Projection(records, jobs, aliases).run()


def verify_records(records: dict, jobs: dict, aliases: dict | None = None) -> list[dict]:
    """Check actual target records; active aliases are errors, never repaired.

    This is referential verification only. The scanner/journal verifier must
    independently enforce filenames, ownership, completeness and exact bytes.
    """
    return _Projection(records, jobs, aliases or {}, verify=True).run()["reasons"]
