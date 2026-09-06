"""Test-only contract oracle for #447; never imported by application code.

There is deliberately no migration/detection implementation here. Future
phases must project their real outputs into this observation format.
"""

from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import re
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "immutable_job_id_v1"
LEGACY_FIELDS = {"job_key", "backup_type", "type_id", "location"}
OBSERVATION_FIELDS = {
    "classification", "execution", "reason_codes", "jobs", "bindings",
    "unassigned", "preserved", "unchanged_files",
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def assert_uuid4(value):
    assert isinstance(value, str), "job_id must be a string"
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise AssertionError("invalid job_id") from exc
    assert parsed.version == 4, "job_id must be UUIDv4"
    assert str(parsed) == value, "job_id must be canonical lowercase UUID"


def assert_safe_relative_path(value):
    assert isinstance(value, str) and value, "empty fixture path"
    path = PurePosixPath(value)
    assert not path.is_absolute() and ".." not in path.parts, "unsafe fixture path"
    assert str(path) == value and "\\" not in value, "noncanonical fixture path"


def load_cases():
    base = read_json(FIXTURES / "base.json")
    matrix = read_json(FIXTURES / "cases.json")
    assert base["schema_version"] == matrix["schema_version"] == 1
    result = []
    for raw in matrix["cases"]:
        case = deepcopy(raw)
        files = deepcopy(base["files"])
        for name, value in case["files"].items():
            assert_safe_relative_path(name)
            if value is None:
                assert name in files, "fixture deletes a nonexistent base file"
                del files[name]
            else:
                files[name] = value
        case["files"] = files
        case["config"] = deepcopy(base["config"])
        case["directories"] = list(base["directories"])
        case["allocation_order"] = list(matrix["allocation_order"])
        result.append(case)
    return result


def source_value(files, reference):
    """Read file#JSON-pointer evidence, including the whole payload with '#'."""
    name, separator, pointer = reference.partition("#")
    assert separator, "source reference needs a JSON pointer"
    assert_safe_relative_path(name)
    value = files[name]["json"]
    assert not pointer or pointer.startswith("/"), "invalid JSON pointer"
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def assert_job_graph(jobs, bindings, unassigned):
    aliases = {}
    for job_id, job in jobs.items():
        assert_uuid4(job_id)
        assert job["job_id"] == job_id, "duplicate or mismatched job ID"
        assert type(job["schema_version"]) is int and job["schema_version"] == 4
        assert not LEGACY_FIELDS.intersection(job), "active legacy identity remains"
        assert isinstance(job["name"], str) and job["name"].strip()
        assert isinstance(job["repository_key"], str) and job["repository_key"]
        prefixes = job["archive_prefixes"]
        assert isinstance(prefixes, list) and prefixes, "current prefix missing"
        assert all(isinstance(p, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", p)
                   and p not in {".", ".."} for p in prefixes), "unsafe prefix"
        assert len(prefixes) == len(set(prefixes)), "duplicate prefix"
        legacy = job["legacy_job_keys"]
        assert isinstance(legacy, list), "aliases must be a list"
        assert all(isinstance(a, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", a)
                   for a in legacy), "invalid alias"
        assert len(legacy) == len(set(legacy)), "duplicate alias in job"
        for alias in legacy:
            assert alias not in aliases, "duplicate alias ownership"
            aliases[alias] = job_id
    for source, job_id in bindings.items():
        if job_id is None:
            assert source in unassigned, "unassigned reference lacks classification"
        else:
            assert job_id in jobs, "dangling canonical reference"
            assert source not in unassigned, "assigned history marked unassigned"
    assert set(unassigned) == {s for s, v in bindings.items() if v is None}
    assert all(isinstance(reason, str) and reason for reason in unassigned.values())


def assert_canonical_job_files(files):
    """Verify actual post-migration metadata, independently of fixture goldens."""
    jobs = {}
    for path, payload in files.items():
        assert_uuid4(payload.get("job_id"))
        job_id = payload["job_id"]
        assert Path(path).name == job_id + ".json", "noncanonical metadata filename"
        assert job_id not in jobs, "duplicate job ID across files"
        jobs[job_id] = payload
    assert_job_graph(jobs, {}, {})


def assert_lifecycle_identity(operation, original, result):
    """Check output from a real create/edit/import action in later phases."""
    assert operation in {"create", "edit", "duplicate", "import_new", "import_update"}
    assert_job_graph({result["job_id"]: result}, {}, {})
    if operation in {"edit", "import_update"}:
        assert result["job_id"] == original["job_id"], "existing identity changed"
        assert result["legacy_job_keys"] == original["legacy_job_keys"], "aliases changed on edit"
    else:
        assert result["legacy_job_keys"] == [], "new job inherited legacy aliases"
        if original is not None:
            assert result["job_id"] != original["job_id"], "new job reused source identity"


def assert_fixture(case):
    assert re.fullmatch(r"[a-z][a-z0-9_]+", case["id"])
    assert case["description"]
    for name, entry in case["files"].items():
        assert_safe_relative_path(name)
        assert isinstance(entry, dict) and set(entry) in ({"json"}, {"text"})
        if "text" in entry:
            assert isinstance(entry["text"], str)
    for path in case["directories"]:
        assert_safe_relative_path(path)
    for job_id in case["allocation_order"]:
        assert_uuid4(job_id)
    assert len(set(case["allocation_order"])) == len(case["allocation_order"])
    expected = case["expected"]
    assert set(expected) == OBSERVATION_FIELDS
    assert expected["classification"] in {"not_applicable", "applicable", "blocked"}
    assert expected["execution"] in {
        "applied_after_confirmation", "resumed_after_confirmation",
        "no_user_data_writes", "pending_no_user_data_writes",
    }
    assert isinstance(expected["reason_codes"], list)
    assert all(isinstance(r, str) and r for r in expected["reason_codes"])
    if expected["classification"] == "blocked":
        assert expected["reason_codes"] and not expected["jobs"]
        assert expected["execution"] == "no_user_data_writes"
    if expected["classification"] == "not_applicable":
        assert expected["execution"] == "no_user_data_writes"
    conditions = case["preconditions"]
    for key in ("administrator_confirmed", "snapshot_verified", "writers_quiescent",
                "source_fingerprints_match"):
        assert type(conditions[key]) is bool
    if expected["execution"] in {"applied_after_confirmation", "resumed_after_confirmation"}:
        assert all(conditions[k] for k in conditions if k != "journal")
    if expected["execution"] == "resumed_after_confirmation":
        assert conditions["journal"]["migration_id"] == "immutable_job_id_v1"
        assert set(conditions["journal"]["id_map"].values()) <= set(expected["jobs"])
    assert_job_graph(expected["jobs"], expected["bindings"], expected["unassigned"])
    for reference in expected["bindings"]:
        source_value(case["files"], reference)
    for reference, value in expected["preserved"].items():
        assert source_value(case["files"], reference) == value, "invalid preservation golden"
    for name in expected["unchanged_files"]:
        assert name in case["files"]


def _relocate(value, root):
    if isinstance(value, str):
        return value.replace("/fixture/", root.as_posix().rstrip("/") + "/")
    if isinstance(value, list):
        return [_relocate(item, root) for item in value]
    if isinstance(value, dict):
        return {key: _relocate(item, root) for key, item in value.items()}
    return value


def materialize(case, root):
    """Write synthetic inputs ONLY inside a new empty repository-local test root.

    Returns a relocated copy, not the original case. OS failure/journal hooks
    in preconditions must be supplied by the future real planner test adapter.
    """
    root = Path(root).resolve()
    assert root.is_relative_to(ROOT), "test data must stay in this repository"
    root.mkdir(parents=True, exist_ok=True)
    assert not any(root.iterdir()), "fixture root must be empty"
    relocated = _relocate(deepcopy(case), root)
    assert_fixture(relocated)
    for directory in relocated["directories"]:
        (root / directory).mkdir(parents=True, exist_ok=True)
    for name, entry in relocated["files"].items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(entry["json"], indent=2, ensure_ascii=True) + "\n"
                if "json" in entry else entry["text"])
        path.write_text(data, encoding="utf-8")
    return relocated


def tree_bytes(root):
    """Exact test-tree snapshot; not a production migration inventory."""
    root = Path(root)
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def assert_observation(case, actual, before, after):
    """Check an independently projected real planner/applier result.

    `preserved` values must be read from their destination by that adapter,
    keyed by original provenance. Merely echoing the input is not verification.
    """
    assert set(actual) == OBSERVATION_FIELDS
    assert_job_graph(actual["jobs"], actual["bindings"], actual["unassigned"])
    assert actual == case["expected"], "migration observation differs from contract"
    if actual["execution"] in {"no_user_data_writes", "pending_no_user_data_writes"}:
        assert before == after, "user data changed without apply permission"
    for name in actual["unchanged_files"]:
        assert name in before and name in after, "preserved file missing"
        assert before[name] == after[name], "excluded/log file bytes changed"
