from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LIB = ROOT / "runtime" / "lib"
if str(RUNTIME_LIB) not in sys.path:
    sys.path.insert(0, str(RUNTIME_LIB))

import docker_manager  # noqa: E402


def test_stop_selected_stops_only_selected_running_containers(monkeypatch):
    running = {"id-paperless", "id-plex"}
    stop_calls = []

    def fake_run(cmd, **_kwargs):
        if cmd[:3] == ["docker", "stop", "-t"]:
            stop_calls.append(cmd)
            for cid in cmd[4:]:
                running.discard(cid)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["docker", "ps", "--format"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                "paperless-ngx|id-paperless\nplex|id-plex\n",
                "",
            )
        raise AssertionError(cmd)

    monkeypatch.setattr(docker_manager, "docker_available", lambda: True)
    monkeypatch.setattr(docker_manager.subprocess, "run", fake_run)
    monkeypatch.setattr(docker_manager.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        docker_manager,
        "_get_running_name_id_map",
        lambda: {"paperless-ngx": "id-paperless", "plex": "id-plex"},
    )
    monkeypatch.setattr(docker_manager, "_get_running_ids", lambda: sorted(running))
    monkeypatch.setattr(
        docker_manager,
        "_get_container_name",
        lambda cid: {"id-paperless": "paperless-ngx", "id-plex": "plex"}[cid],
    )

    result = docker_manager.DockerManager(docker_manager.DockerConfig(stop_wait=0)).stop_selected(
        ["paperless-ngx"],
        "/tmp/backup.log",
    )

    assert result.success is True
    assert result.container_ids == ["id-paperless"]
    assert result.container_names == ["paperless-ngx"]
    assert stop_calls == [["docker", "stop", "-t", "30", "id-paperless"]]
    assert running == {"id-plex"}


def test_start_all_restarts_only_previously_stopped_containers(monkeypatch):
    started = []

    monkeypatch.setattr(docker_manager, "_get_container_priority", lambda _cid: 3)
    monkeypatch.setattr(docker_manager, "_get_container_name", lambda cid: cid)
    monkeypatch.setattr(docker_manager, "_docker_start", lambda cid: started.append(cid))
    monkeypatch.setattr(docker_manager, "_is_running", lambda _cid: True)
    monkeypatch.setattr(docker_manager, "_get_running_ids", lambda: ["id-paperless", "id-plex"])
    monkeypatch.setattr(docker_manager.time, "sleep", lambda _seconds: None)

    stop_result = docker_manager.DockerStopResult(
        available=True,
        container_ids=["id-paperless"],
        container_names=["paperless-ngx"],
        count_before=1,
        success=True,
    )

    result = docker_manager.DockerManager(docker_manager.DockerConfig(start_wait=0)).start_all(stop_result)

    assert result.success is True
    assert started == ["id-paperless"]
