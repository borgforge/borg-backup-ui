"""#471: fixture/contract validation, NOT an implemented migration test suite."""

from copy import deepcopy
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import pytest

from identity_contract_support import (
    ROOT, assert_canonical_job_files, assert_fixture, assert_job_graph, assert_lifecycle_identity,
    assert_observation, assert_safe_relative_path, assert_uuid4,
    load_cases, materialize, read_json, tree_bytes,
)


CASES = load_cases()
BY_ID = {case["id"]: case for case in CASES}


@pytest.fixture
def identity_root():
    # Also stays repository-local under the preflight's plain `pytest -q`.
    parent = ROOT / ".release-tmp"
    parent.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="identity-471-", dir=parent) as directory:
        yield Path(directory)


def test_fixture_ids_and_required_classifications():
    assert len(CASES) == len(BY_ID)
    assert {c["expected"]["classification"] for c in CASES} == {
        "applicable", "blocked", "not_applicable",
    }
    assert {"fresh", "legacy_without_prefixes", "different_storage_types",
            "reported_config_to_pfsense_orphan_schedule", "disabled_schedule_and_reminder",
            "restore_result_and_history", "orphan_history_and_excluded_archives",
            "ambiguous_aliases", "corrupt_job_json", "interrupted_with_journal"} <= BY_ID.keys()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_fixture_schema_and_expected_graph(case):
    assert_fixture(case)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_fixture_materialization_is_synthetic_and_preserves_source_bytes(case, identity_root):
    relocated = materialize(case, identity_root / "installation")
    before = tree_bytes(identity_root / "installation")
    assert set(before) == set(case["files"])
    for name, entry in relocated["files"].items():
        if "json" in entry:
            assert json.loads(before[name]) == entry["json"]
        else:
            assert before[name].decode("utf-8") == entry["text"]
    # Oracle self-check only: this is NOT a real planner/applier result.
    assert_observation(relocated, deepcopy(relocated["expected"]), before, before)


def test_fixtures_have_no_credentials_or_production_paths():
    def inspect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert key.lower() not in {
                    "password", "passphrase", "token", "gh_token", "private_key",
                    "api_key", "secret", "apprise_url",
                }, "do not commit credential-bearing fixtures"
                if key == "host":
                    assert item.endswith(".invalid")
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)
        elif isinstance(value, str):
            assert not re.search(r"\b(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_]{12,}", value)
            assert "PRIVATE KEY-----" not in value
            assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", value)
            assert not any(p in value for p in ("/home/", "/boot/", "/mnt/", "@hetzner"))
            if value.startswith("/"):
                assert value.startswith("/fixture/")
    for case in CASES:
        inspect(case)


@pytest.mark.parametrize("value", [
    None, "", "config_local", "11111111", "11111111111141118111111111111111",
    "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", "11111111-1111-5111-8111-111111111111",
    "11111111-1111-4111-0111-111111111111",
])
def test_noncanonical_or_non_v4_ids_rejected(value):
    with pytest.raises(AssertionError):
        assert_uuid4(value)


@pytest.mark.parametrize("path", ["/etc/file", "../file", "a/../../file", "a\\file", "a//file", ""])
def test_fixture_paths_cannot_escape_root(path):
    with pytest.raises(AssertionError):
        assert_safe_relative_path(path)


def test_duplicate_alias_and_uuid_assertions():
    jobs = deepcopy(BY_ID["shared_repository_distinct_prefixes"]["expected"]["jobs"])
    first, second = jobs
    jobs[second]["legacy_job_keys"] = jobs[first]["legacy_job_keys"]
    with pytest.raises(AssertionError, match="alias ownership"):
        assert_job_graph(jobs, {}, {})
    with pytest.raises(AssertionError, match="noncanonical metadata filename"):
        assert_canonical_job_files({"wrong.json": jobs[first]})
    with pytest.raises(AssertionError, match="duplicate job ID"):
        assert_canonical_job_files({f"one/{first}.json": jobs[first], f"two/{first}.json": jobs[first]})


def test_canonical_metadata_and_full_explicit_prefix():
    jobs = deepcopy(BY_ID["legacy_without_prefixes"]["expected"]["jobs"])
    job_id = next(iter(jobs))
    jobs[job_id]["archive_prefixes"] = ["complete-user-prefix"]
    assert_canonical_job_files({f"jobs/{job_id}.json": jobs[job_id]})
    jobs[job_id]["job_key"] = "should_not_survive"
    with pytest.raises(AssertionError, match="active legacy identity"):
        assert_job_graph(jobs, {}, {})


def test_dangling_reference_and_unassigned_classification_assertions():
    expected = deepcopy(BY_ID["legacy_without_prefixes"]["expected"])
    with pytest.raises(AssertionError, match="dangling"):
        assert_job_graph(expected["jobs"], {"record": "22222222-2222-4222-8222-222222222222"}, {})
    with pytest.raises(AssertionError, match="lacks classification"):
        assert_job_graph(expected["jobs"], {"record": None}, {})
    with pytest.raises(AssertionError, match="assigned history marked unassigned"):
        assert_job_graph(expected["jobs"], {"record": next(iter(expected["jobs"]))}, {"record": "orphan"})


@pytest.mark.parametrize("operation", ["create", "duplicate", "import_new", "edit", "import_update"])
def test_lifecycle_identity_oracle(operation):
    original = deepcopy(next(iter(BY_ID["legacy_without_prefixes"]["expected"]["jobs"].values())))
    result = deepcopy(original)
    result["name"] = "Synthetic renamed job"
    result["archive_prefixes"] = ["explicit-new-prefix", "config-backup"]
    result["repository_key"] = "repo_other"
    if operation in {"create", "duplicate", "import_new"}:
        result["job_id"] = "22222222-2222-4222-8222-222222222222"
        result["legacy_job_keys"] = []
    assert_lifecycle_identity(operation, original, result)
    if operation in {"edit", "import_update"}:
        result["job_id"] = "22222222-2222-4222-8222-222222222222"
    else:
        result["legacy_job_keys"] = ["config_local"]
    with pytest.raises(AssertionError):
        assert_lifecycle_identity(operation, original, result)


def test_reported_rename_is_blocking_and_not_repaired_by_prefix_history():
    case = BY_ID["reported_config_to_pfsense_orphan_schedule"]
    assert "config_local" in case["files"]["data/config/schedules.json"]["json"]
    assert "data/config/jobs/config_local.json" not in case["files"]
    assert case["files"]["data/config/jobs/pfsense_local.json"]["json"]["archive_prefixes"] == [
        "pfsense-backup", "config-backup",
    ]
    assert case["expected"]["reason_codes"] == ["orphan_active_schedule"]
    assert case["expected"]["classification"] == "blocked"


def test_current_prefix_is_derived_before_deduplicated_history():
    case = BY_ID["current_prefix_precedes_stored_history"]
    assert case["files"]["data/config/jobs/config_local.json"]["json"]["archive_prefixes"][0] == "old-backup"
    assert next(iter(case["expected"]["jobs"].values()))["archive_prefixes"] == ["config-backup", "old-backup"]


def test_oracle_rejects_lost_history_and_unauthorized_writes():
    case = BY_ID["orphan_history_and_excluded_archives"]
    actual = deepcopy(case["expected"])
    actual["unassigned"] = {}
    with pytest.raises(AssertionError):
        assert_observation(case, actual, {}, {})
    blocked = BY_ID["reported_config_to_pfsense_orphan_schedule"]
    with pytest.raises(AssertionError, match="without apply permission"):
        assert_observation(blocked, deepcopy(blocked["expected"]), {"job": b"old"}, {"job": b"new"})
    with pytest.raises(AssertionError, match="bytes changed"):
        before = {p: b"old" for p in case["expected"]["unchanged_files"]}
        after = {p: b"new" for p in before}
        assert_observation(case, deepcopy(case["expected"]), before, after)


def test_dependency_inventory_covers_current_source_scan():
    inventory = read_json(ROOT / "docs/maintainer/identity-dependencies.json")
    pattern = re.compile(inventory["scan"]["pattern"])
    extensions = set(inventory["scan"]["extensions"])
    indexed = set()
    for group in inventory["groups"]:
        assert group["owner_issue"] in range(472, 480)
        assert all(issue in range(472, 480) for issue in group["also"])
        assert group["target"]
        for entry in group["files"]:
            path = ROOT / entry["path"]
            assert path.is_file(), entry["path"]
            assert entry["anchor"] in path.read_text(encoding="utf-8"), entry["path"]
            assert entry["role"] and entry["path"] not in indexed
            indexed.add(entry["path"])
    scanned = set()
    for name in inventory["scan"]["roots"]:
        root = ROOT / name
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if path.suffix in extensions and path.is_file():
                if pattern.search(path.read_text(encoding="utf-8")):
                    scanned.add(path.relative_to(ROOT).as_posix())
    assert scanned <= indexed, f"Mutable identity dependencies need owners: {sorted(scanned - indexed)}"


def test_fixture_helpers_are_not_production_migration_imports():
    for name in ("api/migrations/registry.py", "borg_backup_ui.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "identity_contract_support" not in text
        assert "immutable_job_id_v1" not in text
