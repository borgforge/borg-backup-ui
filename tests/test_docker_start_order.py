"""Per-job Docker start order: reverse sequential stop and ordered restart."""

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / "api", ROOT / "runtime"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from lib import docker_manager  # noqa: E402


@pytest.fixture
def docker(monkeypatch):
    """Simulate a Docker daemon that records stop/start calls and sleeps."""
    state = {"running": {"id-db", "id-app", "id-web", "id-tool"}, "calls": [], "priority": {}}
    names = {"id-db": "mariadb", "id-app": "nextcloud", "id-web": "plex", "id-tool": "whoami"}

    def fake_run(cmd, **_kwargs):
        if cmd[:3] == ["docker", "stop", "-t"]:
            state["calls"].append(("stop", [names[cid] for cid in cmd[4:]]))
            state["running"].difference_update(cmd[4:])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["docker", "ps", "--format"]:
            rows = "".join(f"{names[cid]}|{cid}\n" for cid in sorted(state["running"]))
            return subprocess.CompletedProcess(cmd, 0, rows, "")
        raise AssertionError(cmd)

    def fake_start(cid):
        state["calls"].append(("start", names[cid]))
        state["running"].add(cid)

    monkeypatch.setattr(docker_manager, "docker_available", lambda: True)
    monkeypatch.setattr(docker_manager.subprocess, "run", fake_run)
    monkeypatch.setattr(docker_manager.time, "sleep", lambda seconds: state["calls"].append(("sleep", seconds)))
    monkeypatch.setattr(docker_manager, "_get_running_ids", lambda: sorted(state["running"]))
    monkeypatch.setattr(docker_manager, "_get_running_name_id_map",
                        lambda: {names[cid]: cid for cid in sorted(state["running"])})
    monkeypatch.setattr(docker_manager, "_get_container_name", lambda cid: names[cid])
    monkeypatch.setattr(docker_manager, "_docker_start", fake_start)
    monkeypatch.setattr(docker_manager, "_get_container_priority", lambda cid: state["priority"].get(cid, 3))
    return state


def _manager(order):
    config = docker_manager.DockerConfig(stop_wait=0, start_wait=1, priority_wait=7)
    config.start_order = order
    return docker_manager.DockerManager(config)


def test_split_keeps_configured_order_and_the_rest_unchanged():
    ids = ["a", "b", "c", "d"]
    names = ["plex", "mariadb", "/whoami", "nextcloud"]
    assert docker_manager._split_by_start_order(ids, names, ["mariadb", "nextcloud", "gone"]) == (
        ["b", "d"], ["a", "c"])
    assert docker_manager._split_by_start_order(ids, names, []) == ([], ids)


def test_custom_order_stops_one_by_one_in_reverse_and_unlisted_first(docker):
    result = _manager(["mariadb", "nextcloud", "plex"]).stop_all("/tmp/backup.log")

    assert result.success is True
    stops = [names for kind, names in docker["calls"] if kind == "stop"]
    assert stops == [["whoami"], ["plex"], ["nextcloud"], ["mariadb"]]


def test_without_order_all_containers_stop_with_one_call(docker):
    _manager([]).stop_selected(["mariadb", "plex"], "/tmp/backup.log")

    assert [names for kind, names in docker["calls"] if kind == "stop"] == [["mariadb", "plex"]]


def test_custom_order_starts_first_then_label_priorities(docker):
    manager = _manager(["mariadb", "nextcloud"])
    stopped = manager.stop_all("/tmp/backup.log")
    docker["calls"].clear()
    docker["priority"] = {"id-tool": 1}

    result = manager.start_all(stopped)

    assert result.success is True
    assert docker["calls"] == [
        ("start", "mariadb"), ("start", "nextcloud"), ("sleep", 1), ("sleep", 7),
        ("start", "whoami"), ("sleep", 1), ("sleep", 7),
        ("start", "plex"), ("sleep", 1),
    ]


def test_without_order_restart_keeps_priority_groups(docker):
    manager = _manager([])
    stopped = manager.stop_all("/tmp/backup.log")
    docker["calls"].clear()
    docker["priority"] = {"id-db": 1, "id-app": 2}

    manager.start_all(stopped)

    starts = [entry for entry in docker["calls"] if entry[0] in {"start", "sleep"}]
    assert starts[:5] == [("start", "mariadb"), ("sleep", 1), ("sleep", 7), ("start", "nextcloud"), ("sleep", 1)]
    assert {name for kind, name in starts[5:] if kind == "start"} == {"plex", "whoami"}


def test_inventory_reports_the_restart_priority_label(monkeypatch):
    output = "plex|id1|img|running|Up|\nmariadb|id2|img|running|Up|1\nold|id3|img|exited|Exited|9\n"
    monkeypatch.setattr(docker_manager.subprocess, "run",
                        lambda cmd, **_kwargs: subprocess.CompletedProcess(cmd, 0, output, ""))

    rows = docker_manager.list_containers()

    assert [(row["name"], row["priority"]) for row in rows] == [("mariadb", 1), ("old", 3), ("plex", 3)]


def test_job_settings_keep_the_order_only_with_docker_control():
    from jobs_api import _runtime_control_from_meta as jobs_control
    from wizard_api import _runtime_control_from_meta, _runtime_control_from_params
    import wizard_runner

    control = {"mode": "all", "order": ["mariadb", " nextcloud ", "mariadb", ""]}
    assert _runtime_control_from_params({"docker_control": control}, "docker")["order"] == ["mariadb", "nextcloud"]
    assert _runtime_control_from_meta({"docker_control": control}, "docker")["order"] == ["mariadb", "nextcloud"]
    assert jobs_control({"docker_control": control}, "docker")["order"] == ["mariadb", "nextcloud"]
    assert wizard_runner._runtime_control({"docker_control": control}, "docker")["order"] == ["mariadb", "nextcloud"]
    disabled = {"docker_control": {"mode": "none", "order": ["mariadb"]}}
    assert _runtime_control_from_params(disabled, "docker")["order"] == []
    assert wizard_runner._runtime_control(disabled, "docker")["order"] == []
    assert "order" not in _runtime_control_from_params({"vm_control": {"mode": "all"}}, "vm")


@pytest.mark.parametrize("order", [["mariadb", "nextcloud", "plex"], []])
def test_flow_preview_shows_the_configured_order(tmp_path, order):
    from wizard_api import generate_flow_preview

    flow = generate_flow_preview({
        "location": "local", "source_paths": [str(tmp_path)],
        "docker_control": {"mode": "all", "order": order}, "vm_control": {"mode": "none"},
    }, {"BACKUP_SCRIPTS_DIR": str(tmp_path)}, tmp_path)

    codes = [item["code"] for item in flow["step_codes"]]
    assert flow["summary"]["docker_order"] == order
    if order:
        stop = next(item for item in flow["step_codes"] if item["code"] == "dockerStopOrder")
        start = next(item for item in flow["step_codes"] if item["code"] == "dockerStartOrdered")
        assert stop["params"] == {"order": "plex -> nextcloud -> mariadb"}
        assert start["params"] == {"order": "mariadb -> nextcloud -> plex"}
        assert codes.index("dockerStop") < codes.index("dockerStopOrder") < codes.index("borgCreate")
        assert codes.index("borgCreate") < codes.index("dockerStartOrdered") and "dockerStart" not in codes
    else:
        assert "dockerStart" in codes and "dockerStopOrder" not in codes


def test_wizard_order_list_and_payload():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    subprocess.run([node, "tests/docker_order_ui.cjs"], cwd=ROOT, check=True)
