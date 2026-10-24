"""Sequential Docker backups: planning, archive names and series pruning."""

from pathlib import Path
import json
import os
import platform
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / "api", ROOT / "runtime"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from lib import docker_sequence  # noqa: E402
from lib.borg_runner import BorgConfig, BorgRunner  # noqa: E402
from lib.docker_sequence import (  # noqa: E402
    archive_glob,
    archive_name,
    canonical_share_path,
    plan_sequence,
    series_glob,
    series_key,
    series_keys,
)

BORG_BINARY = ROOT / "runtime" / "bin" / "borg" / "borg-linux-glibc231-x86_64-1.4.5"


def _plan(sources, mounts, *, targets=None, excludes=(), missing=()):
    targets = targets or [(name, f"id-{name}") for name in mounts]
    return plan_sequence(sources, targets, mounts, excludes, path_exists=lambda path: path not in missing)


def test_each_container_gets_its_own_group_and_the_rest_stays_in_the_main_archive():
    plan = _plan(["/mnt/user/appdata"], {
        "mariadb": ["/mnt/user/appdata/mariadb", "/mnt/user/media"],
        "nextcloud": ["/mnt/user/appdata/nextcloud", "/mnt/user/appdata/nextcloud-data"],
        "whoami": [],
    })

    assert [(group.key, group.containers, group.paths) for group in plan.groups] == [
        ("mariadb", ["mariadb"], ["/mnt/user/appdata/mariadb"]),
        ("nextcloud", ["nextcloud"], ["/mnt/user/appdata/nextcloud", "/mnt/user/appdata/nextcloud-data"]),
    ]
    assert plan.groups[1].container_ids == ["id-nextcloud"]
    assert plan.idle_containers == ["whoami"]
    assert plan.main_paths == ["/mnt/user/appdata"]
    assert plan.main_excludes == [
        "/mnt/user/appdata/mariadb", "/mnt/user/appdata/nextcloud", "/mnt/user/appdata/nextcloud-data",
    ]


def test_unraid_pool_and_disk_views_match_user_share_sources_in_job_spelling():
    assert canonical_share_path("/mnt/cache/appdata/plex/") == "/mnt/user/appdata/plex"
    assert canonical_share_path("/mnt/disk1/appdata") == "/mnt/user/appdata"
    assert canonical_share_path("/mnt/user0/appdata") == "/mnt/user/appdata"
    assert canonical_share_path("/mnt/disks/usb/appdata") == "/mnt/disks/usb/appdata"
    assert canonical_share_path("/mnt/remotes/nas/appdata") == "/mnt/remotes/nas/appdata"

    plan = _plan(["/mnt/user/appdata"], {"plex": ["/mnt/cache/appdata/plex"]})
    assert plan.groups[0].paths == ["/mnt/user/appdata/plex"]
    plan = _plan(["/mnt/cache/appdata"], {"plex": ["/mnt/user/appdata/plex"]})
    assert plan.groups[0].paths == ["/mnt/cache/appdata/plex"]


def test_overlapping_writers_are_stopped_together():
    plan = _plan(["/mnt/user/appdata"], {
        "radarr": ["/mnt/user/appdata/radarr", "/mnt/user/appdata/shared"],
        "sonarr": ["/mnt/user/appdata/sonarr", "/mnt/user/appdata/shared/sonarr"],
        "plex": ["/mnt/user/appdata/plex"],
    }, targets=[("plex", "p"), ("radarr", "r"), ("sonarr", "s")])

    assert [(group.key, group.containers) for group in plan.groups] == [
        ("plex", ["plex"]), ("radarr+sonarr", ["radarr", "sonarr"]),
    ]
    assert plan.groups[1].paths == [
        "/mnt/user/appdata/radarr", "/mnt/user/appdata/shared", "/mnt/user/appdata/sonarr",
    ]


def test_mount_containing_a_source_claims_the_whole_source_and_joins_all_writers():
    # A file manager with /mnt/user can write everywhere, so nothing may run beside it.
    plan = _plan(["/mnt/user/appdata"], {
        "krusader": ["/mnt/user"],
        "nextcloud": ["/mnt/user/appdata/nextcloud"],
    })

    assert [group.containers for group in plan.groups] == [["krusader", "nextcloud"]]
    assert plan.groups[0].paths == ["/mnt/user/appdata"]
    assert plan.main_paths == []
    assert plan.main_excludes == []


def test_source_below_a_container_mount_belongs_to_that_container():
    plan = _plan(["/mnt/user/appdata/nextcloud/data", "/mnt/user/documents"], {
        "nextcloud": ["/mnt/user/appdata/nextcloud"],
    })

    assert plan.groups[0].paths == ["/mnt/user/appdata/nextcloud/data"]
    assert plan.main_paths == ["/mnt/user/documents"]


def test_excluded_and_missing_paths_are_skipped_and_reported():
    plan = _plan(["/mnt/user/appdata"], {
        "plex": ["/mnt/user/appdata/plex/cache", "/mnt/user/appdata/plex"],
        "old": ["/mnt/user/appdata/old"],
    }, excludes=["/mnt/user/appdata/plex/cache"], missing={"/mnt/user/appdata/old"})

    assert [group.containers for group in plan.groups] == [["plex"]]
    assert plan.groups[0].paths == ["/mnt/user/appdata/plex"]
    assert plan.idle_containers == ["old"]
    assert sorted(plan.skipped_paths) == [
        ("old", "/mnt/user/appdata/old", "missing"),
        ("plex", "/mnt/user/appdata/plex/cache", "excluded"),
    ]


def test_series_keys_are_stable_short_and_never_contain_the_separator():
    assert series_key(["sonarr", "Radarr", "sonarr"]) == "Radarr+sonarr"
    long_names = [f"container-with-a-very-long-name-{index:02d}" for index in range(10)]
    key = series_key(long_names)
    assert len(key) <= 100
    assert key.startswith("container-with-a-very-long-name-00+9-")
    assert key == series_key(reversed(long_names))
    assert "@" not in series_key(["a@b"])


def test_archive_names_and_globs_select_exactly_one_series():
    assert archive_name("appdata", "nextcloud", "2026-10-24_03-00-00") == "appdata@nextcloud-2026-10-24_03-00-00"
    assert archive_glob("appdata") == "appdata@*"
    with pytest.raises(ValueError, match="255"):
        archive_name("p" * 240, "nextcloud", "2026-10-24_03-00-00")

    names = [
        "appdata-2026-10-24_03-00-00",
        "appdata@sonarr-2026-10-24_03-00-00",
        "appdata@sonarr-2026-10-24_03-00-00.checkpoint",
        "appdata@sonarr-4k-2026-10-24_03-00-00",
        "appdata@radarr+sonarr-2026-10-24_03-00-00",
        "appdata@manual-copy",
        "other@sonarr-2026-10-24_03-00-00",
    ]
    assert series_keys("appdata", names) == ["radarr+sonarr", "sonarr", "sonarr-4k"]
    assert series_glob("appdata", "sonarr") == (
        "appdata@sonarr-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9]-[0-9][0-9]-[0-9][0-9]*"
    )
    # A container literally named like another series plus a timestamp keeps both apart.
    shadow = "sonarr-2026-10-24_03-00-00"
    assert series_glob("appdata", "sonarr", ["sonarr", shadow]).endswith("[0-9][0-9]")


def test_prune_runs_once_per_container_series_and_sums_counters(monkeypatch):
    commands = []

    class Controller:
        details = {}

        def is_cancel_requested(self):
            return False

        def get_borg_details(self):
            return dict(self.details)

        def update_borg_details(self, values):
            self.details.update(values)

    controller = Controller()

    def fake_run_borg(cmd, _controller):
        commands.append(cmd)
        controller.details = {"kept_archives": 2, "pruned_archives": 1}
        return 0

    def fake_list(cmd, **_kwargs):
        assert cmd[:5] == ["borg", "list", "--short", "--glob-archives", "appdata@*"]
        return subprocess.CompletedProcess(cmd, 0, "\n".join([
            "appdata@nextcloud-2026-10-23_03-00-00",
            "appdata@nextcloud-2026-10-24_03-00-00",
            "appdata@mariadb-2026-10-24_03-00-00",
        ]), "")

    monkeypatch.setattr("lib.borg_runner._run_borg", fake_run_borg)
    monkeypatch.setattr("lib.borg_runner.subprocess.run", fake_list)
    config = BorgConfig(repo="/repo", retention_policy={"mode": "last", "last": "2"})
    config.prune_container_series = True
    runner = BorgRunner(config, process_controller=controller, phase_callback=lambda _phase: controller.details.clear())

    assert runner.prune("appdata") == 0
    globs = [cmd[cmd.index("--glob-archives") + 1] for cmd in commands]
    assert globs == ["appdata-*", series_glob("appdata", "mariadb"), series_glob("appdata", "nextcloud")]
    assert runner.steps["prune"]["details"] == {"kept_archives": 6, "pruned_archives": 3}


def test_normal_prune_and_failed_series_listing(monkeypatch):
    commands = []
    monkeypatch.setattr("lib.borg_runner._run_borg", lambda cmd, _controller: commands.append(cmd) or 0)
    runner = BorgRunner(BorgConfig(repo="/repo", retention_policy={"mode": "last", "last": "2"}))
    assert runner.prune("appdata") == 0
    assert len(commands) == 1 and "appdata-*" in commands[0]

    monkeypatch.setattr("lib.borg_runner.subprocess.run",
                        lambda cmd, **_kwargs: subprocess.CompletedProcess(cmd, 2, "", "Repository locked"))
    runner.config.prune_container_series = True
    assert runner.prune("appdata") == 2
    assert len(commands) == 2


@pytest.mark.skipif(
    sys.platform != "linux" or platform.machine() != "x86_64" or not BORG_BINARY.is_file(),
    reason="bundled Borg binary runs on Linux x86_64 only",
)
def test_bundled_borg_prunes_container_series_independently(tmp_path, monkeypatch):
    borg_dir = tmp_path / "bin"
    borg_dir.mkdir()
    shutil.copy2(BORG_BINARY, borg_dir / "borg")
    (borg_dir / "borg").chmod(0o755)
    monkeypatch.setenv("PATH", f"{borg_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("BORG_BASE_DIR", str(tmp_path / "borg-home"))
    monkeypatch.setenv("BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK", "yes")
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    data.mkdir()
    (data / "file").write_text("demo", encoding="utf-8")
    subprocess.run(["borg", "init", "-e", "none", str(repo)], check=True, capture_output=True)
    names = [
        "appdata-2026-10-20_03-00-00", "appdata-2026-10-21_03-00-00",
        *[f"appdata@{key}-2026-10-2{day}_03-00-00" for key in ("sonarr", "sonarr-4k", "mariadb") for day in (0, 1, 2)],
    ]
    for name in names:
        subprocess.run(["borg", "create", f"{repo}::{name}", str(data)], check=True, capture_output=True)

    config = BorgConfig(repo=str(repo), retention_policy={"mode": "last", "last": "1"})
    config.prune_container_series = True
    assert BorgRunner(config).prune("appdata") == 0

    remaining = subprocess.run(["borg", "list", "--short", str(repo)], check=True, capture_output=True, text=True)
    assert sorted(remaining.stdout.split()) == sorted([
        "appdata-2026-10-21_03-00-00",
        "appdata@mariadb-2026-10-22_03-00-00",
        "appdata@sonarr-2026-10-22_03-00-00",
        "appdata@sonarr-4k-2026-10-22_03-00-00",
    ])
    listed = subprocess.run(["borg", "list", "--json", "--glob-archives", "appdata-*", str(repo)],
                            check=True, capture_output=True, text=True)
    assert [row["name"] for row in json.loads(listed.stdout)["archives"]] == ["appdata-2026-10-21_03-00-00"]


def test_docker_manager_reads_only_writable_bind_mounts(monkeypatch):
    from lib import docker_manager

    def fake_run(cmd, **_kwargs):
        assert cmd[:3] == ["docker", "inspect", "--format"]
        return subprocess.CompletedProcess(cmd, 0, "\n".join([
            "/nextcloud\t" + json.dumps([
                {"Type": "bind", "Source": "/mnt/user/appdata/nextcloud", "RW": True},
                {"Type": "bind", "Source": "/mnt/user/media", "RW": False},
                {"Type": "volume", "Source": "/var/lib/docker/volumes/x/_data", "RW": True},
            ]),
            "/whoami\tnull",
        ]), "")

    monkeypatch.setattr(docker_manager.subprocess, "run", fake_run)
    manager = docker_manager.DockerManager()
    assert manager.writable_bind_mounts(["id-nc", "id-who"]) == {
        "nextcloud": ["/mnt/user/appdata/nextcloud"], "whoami": [],
    }

    monkeypatch.setattr(docker_manager.subprocess, "run",
                        lambda cmd, **_kwargs: subprocess.CompletedProcess(cmd, 1, "", "error"))
    with pytest.raises(RuntimeError, match="volume mappings"):
        manager.writable_bind_mounts(["id-nc"])


@pytest.mark.parametrize("mode,selected,expected", [
    ("all", [], ["mariadb", "Nextcloud", "whoami"]),
    ("selected", ["whoami", "missing"], ["whoami"]),
    ("except_selected", ["whoami"], ["mariadb", "Nextcloud"]),
])
def test_running_targets_follow_the_job_scope_without_stopping(monkeypatch, mode, selected, expected):
    from lib import docker_manager

    monkeypatch.setattr(docker_manager, "docker_available", lambda: True)
    monkeypatch.setattr(docker_manager, "_get_running_name_id_map",
                        lambda: {"whoami": "w", "Nextcloud": "n", "mariadb": "m"})
    targets = docker_manager.DockerManager().running_targets(mode, selected)
    assert [name for name, _cid in targets] == expected

    monkeypatch.setattr(docker_manager, "docker_available", lambda: False)
    assert docker_manager.DockerManager().running_targets(mode, selected) is None


def test_wizard_stores_sequential_mode_only_with_docker_control():
    from wizard_api import _runtime_control_from_meta, _runtime_control_from_params

    control = _runtime_control_from_params({"docker_control": {"mode": "all", "sequential": True}}, "docker")
    assert control == {"mode": "all", "selected": [], "ack_appdata_risk": False, "sequential": True}
    assert _runtime_control_from_params({"docker_control": {"mode": "none", "sequential": True}}, "docker")[
        "sequential"] is False
    assert _runtime_control_from_meta({"docker_control": {"mode": "selected", "selected": ["a"]}}, "docker")[
        "sequential"] is False
    assert "sequential" not in _runtime_control_from_params({"vm_control": {"mode": "all"}}, "vm")


@pytest.mark.parametrize("available", [True, False])
def test_flow_preview_lists_planned_groups_or_runtime_planning(monkeypatch, tmp_path, available):
    import runtime.lib.docker_manager as live_docker
    from wizard_api import generate_flow_preview

    appdata = tmp_path / "appdata"
    for name in ("mariadb", "nextcloud"):
        (appdata / name).mkdir(parents=True)

    class Docker:
        def running_targets(self, mode, selected):
            assert (mode, selected) == ("except_selected", ["plex"])
            return [("mariadb", "m"), ("nextcloud", "n"), ("whoami", "w")] if available else None

        def writable_bind_mounts(self, ids):
            return {"mariadb": [str(appdata / "mariadb")], "nextcloud": [str(appdata / "nextcloud")], "whoami": []}

    monkeypatch.setattr(live_docker, "DockerManager", Docker)
    flow = generate_flow_preview({
        "location": "local", "source_paths": [str(appdata)], "archive_prefix": "appdata",
        "docker_control": {"mode": "except_selected", "selected": ["plex"], "sequential": True},
        "vm_control": {"mode": "all"}, "retention_mode": "last", "keep_last": 2,
    }, {"BACKUP_SCRIPTS_DIR": str(tmp_path)}, tmp_path)

    codes = [item["code"] for item in flow["step_codes"]]
    assert flow["summary"]["docker_sequential"] is True
    assert not {"dockerStop", "dockerStart", "borgCreate", "borgMaintenance"} & set(codes)
    assert codes.index("borgCreateMain") < codes.index("borgMaintenanceSeries")
    if available:
        groups = [item["params"] for item in flow["step_codes"] if item["code"] == "dockerSequenceGroup"]
        assert [(group["containers"], group["archive"]) for group in groups] == [
            ("mariadb", "appdata@mariadb"), ("nextcloud", "appdata@nextcloud"),
        ]
        assert codes[codes.index("dockerSequence"):codes.index("vmStop")] == [
            "dockerSequence", "dockerSequenceGroup", "dockerSequenceGroup", "dockerSequenceIdle",
        ]
        main = next(item["params"] for item in flow["step_codes"] if item["code"] == "borgCreateMain")
        assert main == {"count": 1, "exclusions": 2}
    else:
        assert "dockerSequenceRuntime" in codes and "dockerSequence" not in codes


def test_restore_lists_container_archives_only_for_sequential_jobs():
    import restore_api

    job = {"archive_prefix": "appdata", "archive_prefixes": ["appdata", "old"]}
    assert [row["filter"] for row in restore_api._archive_filter_rows_for_restore_job("x", {"job": job})] == [
        "appdata-*", "old-*",
    ]
    rows = restore_api._archive_filter_rows_for_restore_job(
        "x", {"job": {**job, "docker_control": {"mode": "all", "sequential": True}}})
    assert [(row["filter"], row["current"]) for row in rows] == [
        ("appdata-*", True), ("appdata@*", True), ("old-*", False), ("old@*", False),
    ]
    assert restore_api._archive_prefixes_for_restore_job(
        "x", {"job": {**job, "docker_control": {"sequential": True}}}) == ["appdata", "old"]


def test_job_card_and_wizard_render_sequential_mode():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    subprocess.run([node, "tests/docker_sequence_ui.cjs"], cwd=ROOT, check=True)


def test_module_documents_the_archive_scheme():
    assert docker_sequence.ARCHIVE_SEPARATOR == "@"
    assert "<prefix>@<key>-<timestamp>" in (docker_sequence.__doc__ or "")
