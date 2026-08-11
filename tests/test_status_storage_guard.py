import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LIB = ROOT / "runtime" / "lib"
if str(RUNTIME_LIB) not in sys.path:
    sys.path.insert(0, str(RUNTIME_LIB))

import status  # noqa: E402
import borg_backup_ui  # noqa: E402


@pytest.mark.parametrize(
    ("configured_path", "expected_mount"),
    [
        ("/mnt/user/borg-backup-ui/status", "/mnt/user"),
        ("/mnt/cache/borg-backup-ui/status", "/mnt/cache"),
        ("/mnt/datapool2/borg-backup-ui/status", "/mnt/datapool2"),
        ("/mnt/disk12/borg-backup-ui/status", "/mnt/disk12"),
        ("/mnt/disks/USB-A/borg-backup-ui/status", "/mnt/disks/USB-A"),
        ("/mnt/remotes/NAS/borg-backup-ui/status", "/mnt/remotes/NAS"),
        ("/boot/config/borg-backup-ui", None),
    ],
)
def test_required_storage_mount_variants(configured_path, expected_mount):
    mount = status.required_storage_mount(Path(configured_path))

    assert mount == (Path(expected_mount) if expected_mount else None)


def test_unmounted_user_share_status_directory_is_not_created(monkeypatch):
    monkeypatch.setattr(status, "storage_mount_is_mounted", lambda _path: False)

    with patch.object(Path, "mkdir") as mkdir_mock:
        with pytest.raises(status.StatusStorageUnavailableError, match="/mnt/user is not mounted"):
            status.ensure_status_storage_directory(Path("/mnt/user/borg_backup_ui/status"))

    mkdir_mock.assert_not_called()


def test_non_user_share_status_directory_is_created(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(status, "storage_mount_is_mounted", lambda _path: False)
    target = tmp_path / "status"

    status.ensure_status_storage_directory(target)

    assert target.is_dir()


def test_status_store_logs_unavailable_user_share_only_once(monkeypatch, caplog):
    monkeypatch.setattr(status, "storage_mount_is_mounted", lambda _path: False)
    status._unavailable_status_paths_logged.clear()
    store = status.StatusStore(Path("/mnt/user/borg_backup_ui/status"))

    with caplog.at_level(logging.WARNING):
        assert store.load() == []
        assert store.load() == []

    messages = [
        record.getMessage()
        for record in caplog.records
        if "Status storage is not available yet" in record.getMessage()
    ]
    assert messages == [
        "Status storage is not available yet because /mnt/user is not mounted: "
        "/mnt/user/borg_backup_ui/status"
    ]


def test_backup_status_save_refuses_unmounted_user_share(monkeypatch):
    monkeypatch.setattr(status, "storage_mount_is_mounted", lambda _path: False)
    backup_status = status.BackupStatus(backup_type="flash", location="local")

    with patch.object(Path, "mkdir") as mkdir_mock:
        with pytest.raises(status.StatusStorageUnavailableError):
            backup_status.save(Path("/mnt/user/borg_backup_ui/status"))

    mkdir_mock.assert_not_called()


def test_restore_test_writer_uses_guarded_status_directory():
    source = (ROOT / "runtime" / "scripts" / "borg_restore_test.py").read_text(
        encoding="utf-8"
    )

    assert "_ensure_status_storage_directory(self.status_dir)" in source


def test_startup_waits_for_configured_storage_mount(monkeypatch):
    checks = iter([False, False, True])
    messages = []
    monkeypatch.setattr(
        status,
        "storage_mount_is_mounted",
        lambda _path: next(checks),
    )
    monkeypatch.setattr(borg_backup_ui, "_log", messages.append)

    ready = borg_backup_ui._wait_for_configured_data_storage(
        {
            "GLOBAL_DATA_DIR": "/mnt/user/borg_backup_ui",
            "STATUS_DIR": "/mnt/user/borg_backup_ui/status",
        },
        wait_seconds=9,
        step_seconds=3,
        sleep_fn=lambda _seconds: None,
    )

    assert ready is True
    assert messages[0].startswith("Runtime storage is not available yet")
    assert messages[-1] == "Runtime storage became available after 6s: /mnt/user"


def test_startup_stops_when_configured_storage_mount_stays_unavailable(monkeypatch):
    messages = []
    monkeypatch.setattr(status, "storage_mount_is_mounted", lambda _path: False)
    monkeypatch.setattr(borg_backup_ui, "_log", messages.append)

    ready = borg_backup_ui._wait_for_configured_data_storage(
        {"GLOBAL_DATA_DIR": "/mnt/disks/USB-A/borg-backup-ui"},
        wait_seconds=6,
        step_seconds=3,
        sleep_fn=lambda _seconds: None,
    )

    assert ready is False
    assert "/mnt/disks/USB-A" in messages[-1]
    assert "was not started" in messages[-1]


def test_initial_setup_does_not_start_runtime_writers(monkeypatch):
    calls = []
    messages = []
    monkeypatch.setattr(borg_backup_ui, "_log", messages.append)

    started = borg_backup_ui._start_configured_runtime_writers(
        {"STATUS_DIR": "/mnt/user/backup-status"},
        True,
        app_version="test",
        widget_startup_writer=lambda *_args, **_kwargs: calls.append("widget-startup"),
        widget_loop_starter=lambda *_args, **_kwargs: calls.append("widget-loop"),
        runtime_activator=lambda *_args, **_kwargs: calls.append("runtime"),
    )

    assert started is False
    assert calls == []
    assert messages == [
        "Initial setup pending: GLOBAL_DATA_DIR is not configured yet; "
        "runtime write services are disabled until the setup wizard completes."
    ]


def test_configured_setup_starts_runtime_writers(monkeypatch):
    calls = []
    monkeypatch.setattr(borg_backup_ui, "_log", lambda _message: None)

    started = borg_backup_ui._start_configured_runtime_writers(
        {
            "GLOBAL_DATA_DIR": "/mnt/user/borg_backup_ui",
            "STATUS_DIR": "/mnt/user/borg_backup_ui/status",
        },
        True,
        app_version="test",
        widget_startup_writer=lambda *_args, **_kwargs: calls.append("widget-startup"),
        widget_loop_starter=lambda *_args, **_kwargs: calls.append("widget-loop"),
        runtime_activator=lambda *_args, **_kwargs: calls.append("runtime"),
    )

    assert started is True
    assert calls == ["widget-startup", "widget-loop", "runtime"]


def test_main_waits_for_storage_before_migrations_and_runtime_services():
    source = (ROOT / "borg_backup_ui.py").read_text(encoding="utf-8")
    main_source = source[source.index("def main():") :]

    first_wait = main_source.index(
        "_wait_for_configured_data_storage(config, include_runtime_paths=False)"
    )
    migrations = main_source.index("_evaluate_startup_migrations(config)")
    final_wait = main_source.index("_wait_for_configured_data_storage(config):")
    runtime_services = main_source.index("_start_configured_runtime_writers(config, startup_ready)")

    assert first_wait < migrations < final_wait < runtime_services
