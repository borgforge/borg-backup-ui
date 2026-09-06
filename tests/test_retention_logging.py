"""Readable combined-prune diagnostics without changing archive selection (#447)."""
from datetime import datetime, timedelta
import json
import logging
from types import SimpleNamespace

import pytest

from test_combined_retention import archive, inventory, mock_lists
from lib.retention import prune_union


POLICY = {"daily": 7, "weekly": 4, "monthly": 6, "yearly": 3}
SCOPE = ["new", "old"]
REPOSITORY = "/synthetic/retention-repository"


def retention_inventory():
    rows = [archive("new-latest.checkpoint", "2026-09-16T12:00:00", 1)]
    rules = {rows[0].name: ("checkpoint", 1)}
    dates = {
        "daily": [(datetime(2026, 9, 15, 12) - timedelta(days=offset)).isoformat() for offset in range(7)],
        "weekly": ["2026-09-01T12:00:00", "2026-08-25T12:00:00", "2026-08-18T12:00:00", "2026-08-11T12:00:00"],
        "monthly": [f"2026-{month:02d}-01T12:00:00" for month in range(7, 1, -1)],
        "yearly": [f"{year}-01-01T12:00:00" for year in range(2025, 2022, -1)],
    }
    for period, timestamps in dates.items():
        for index, timestamp in enumerate(timestamps, 1):
            name = f"{SCOPE[index % 2]}-{period}-{index}"
            rows.append(archive(name, timestamp, len(rows) + 1))
            rules[name] = (period, index)
    discard = [archive("old-same-day", "2026-09-15T10:00:00", 90),
               archive("new-older.checkpoint.1", "2026-09-14T10:00:00", 91)]
    foreign = [archive("foreign-newest", "2026-09-17T12:00:00", 92),
               archive("foreign-newest.checkpoint", "2026-09-18T12:00:00", 93),
               archive("newer-near-prefix", "2026-09-19T12:00:00", 94)]
    return rows + discard + foreign, rules, discard, foreign


def run_with_inventory(monkeypatch, rows, *, result=0, second=None, controller=None, before_delete=None):
    output = json.dumps(inventory(rows))
    outputs = [(0, output), (0, json.dumps(inventory(second)) if second is not None else output)]
    mock_lists(monkeypatch, outputs)
    commands = []
    monkeypatch.setattr("lib.borg_runner._run_borg", lambda command, _controller: commands.append(command) or result)
    code = prune_union(REPOSITORY, SCOPE, POLICY, process_controller=controller, before_delete=before_delete)
    return code, commands


def messages(caplog):
    return [record.getMessage() for record in caplog.records if record.name == "lib.retention"]


def assert_no_success(caplog):
    assert not any("Borg prune succeeded" in message for message in messages(caplog))


def assert_archive_evidence(line, item):
    assert item.name in line and f"[{item.id}]" in line
    assert item.timestamp.astimezone().strftime("%Y-%m-%d") in line
    assert item.timestamp.astimezone().strftime("%H:%M:%S") in line


def test_completed_prune_logs_exact_planned_candidates_and_final_success(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="lib.retention")
    rows, rules, discard, foreign = retention_inventory()
    code, commands = run_with_inventory(monkeypatch, rows)
    assert code == 0
    assert commands == [["borg", "delete", "--lock-wait", "30", "--list", "--show-rc", "--",
                         REPOSITORY, *[item.name for item in discard]]]
    lines = messages(caplog)
    assert "Borg prune: applying combined retention only to archives matching new-*, old-* (keep: 7d/4w/6m/3y)" in lines
    assert "Repository contains 23 normal archives and 3 checkpoint archives." in lines
    assert "Applying rules to the matching 21 archives and 2 checkpoints..." in lines
    assert "Keeping 20 archives and 1 checkpoints, pruning 1 archives and 1 checkpoints." in lines
    assert any(line.startswith("Borg prune succeeded (exit 0)") for line in lines)
    kept = [line for line in lines if line.startswith("Keeping archive (rule:")]
    assert len(kept) == len(rules)
    for name, (period, index) in rules.items():
        matches = [line for line in kept if f": {name} " in line]
        assert len(matches) == 1
        rule = "latest checkpoint" if period == "checkpoint" else f"{period} #{index}"
        assert matches[0].startswith(f"Keeping archive (rule: {rule}):")
        assert_archive_evidence(matches[0], next(item for item in rows if item.name == name))
    planned = [line for line in lines if line.startswith("Selected for pruning")]
    assert len(planned) == len(discard)
    for index, (item, line) in enumerate(zip(discard, planned), 1):
        assert line.startswith(f"Selected for pruning ({index}/{len(discard)})")
        assert_archive_evidence(line, item)
    for item in foreign:
        assert not any(item.name in line for line in lines)


@pytest.mark.parametrize("rows", [[], [archive("new-only", "2026-09-15T12:00:00", 1)]])
def test_no_pruning_candidates_still_logs_success_without_delete(monkeypatch, caplog, rows):
    caplog.set_level(logging.INFO, logger="lib.retention")
    mock_lists(monkeypatch, [(0, json.dumps(inventory(rows)))])
    monkeypatch.setattr("lib.borg_runner._run_borg", lambda *args: pytest.fail("No empty or repository delete"))
    assert prune_union(REPOSITORY, SCOPE, POLICY) == 0
    assert any(line.startswith("Borg prune succeeded (exit 0)") for line in messages(caplog))
    assert not any(line.startswith("Selected for pruning") for line in messages(caplog))


def test_oldest_fallback_is_explained_once_without_changing_keep_set(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="lib.retention")
    rows = [archive("new-first", "2026-09-15T12:00:00", 1),
            archive("old-last", "2026-09-15T11:00:00", 2)]
    mock_lists(monkeypatch, [(0, json.dumps(inventory(rows)))])
    monkeypatch.setattr("lib.borg_runner._run_borg", lambda *args: pytest.fail("Oldest fallback keeps both archives"))
    assert prune_union(REPOSITORY, SCOPE, POLICY) == 0
    kept = [line for line in messages(caplog) if line.startswith("Keeping archive (rule:")]
    assert len(kept) == 2
    fallback = next(line for line in kept if ": old-last " in line)
    assert "daily[oldest]" in fallback
    assert_archive_evidence(fallback, rows[1])


@pytest.mark.parametrize("exit_code", [1, 2, 130])
def test_failed_borg_delete_never_logs_success(monkeypatch, caplog, exit_code):
    caplog.set_level(logging.INFO, logger="lib.retention")
    rows, _, discard, _ = retention_inventory()
    code, commands = run_with_inventory(monkeypatch, rows, result=exit_code)
    assert code == exit_code and len(commands) == 1
    assert commands[0][-len(discard):] == [item.name for item in discard]
    assert any(f"exit {exit_code}" in line for line in messages(caplog))
    assert_no_success(caplog)


@pytest.mark.parametrize("candidate_state", ["with_candidates", "empty", "all_kept"])
def test_cancelled_retention_never_deletes_or_claims_success(monkeypatch, caplog, candidate_state):
    caplog.set_level(logging.INFO, logger="lib.retention")
    rows, _, _, _ = retention_inventory()
    if candidate_state == "empty":
        rows = []
    elif candidate_state == "all_kept":
        rows = [archive("new-only", "2026-09-15T12:00:00", 1)]
    controller = SimpleNamespace(attach_process=lambda _process: None, detach_process=lambda: None,
                                 is_cancel_requested=lambda: True)
    code, commands = run_with_inventory(monkeypatch, rows, controller=controller)
    assert code == 130 and not commands
    assert_no_success(caplog)


@pytest.mark.parametrize("change", ["archive_id", "archive_name", "ownership", "inventory_failed"])
def test_changed_or_failed_plan_never_deletes_or_claims_success(monkeypatch, caplog, change):
    caplog.set_level(logging.INFO, logger="lib.retention")
    rows, _, _, _ = retention_inventory()
    changed = inventory(rows)
    if change == "archive_id":
        changed["archives"][0]["id"] = "f" * 64
    elif change == "archive_name":
        changed["archives"][0]["name"] = "foreign-renamed"
    mock_lists(monkeypatch, [(0, json.dumps(inventory(rows))),
                             (2 if change == "inventory_failed" else 0, json.dumps(changed))])
    monkeypatch.setattr("lib.borg_runner._run_borg", lambda *args: pytest.fail("No delete after invalidated plan"))
    with pytest.raises(ValueError):
        prune_union(REPOSITORY, SCOPE, POLICY, before_delete=(lambda: False) if change == "ownership" else None)
    assert_no_success(caplog)
