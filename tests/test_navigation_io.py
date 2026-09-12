"""Restore navigation must not write storage probes (#497)."""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "api", ROOT / "runtime", ROOT / "runtime/lib"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import config_api
import restore_api
from borg_backup_ui import BackupUIHandler


READ_REQUESTS = [
    ("_get_restore_archives", "job=example", "list_archives_with_context", ("example",), {"archives": []}),
    ("_get_restore_files", "job=example&archive=backup&path=docs", "list_files", ("example", "backup", "docs"), []),
    ("_get_repo_stats", "job=example", "get_repo_stats", ("example",), {"size": 123}),
    ("_get_restore_target_dirs", "prefix=%2Fmnt%2Fuser&limit=12", "list_target_dirs_with_config", ("/mnt/user", 12), []),
    ("_get_restore_state", "restore_id=example", "get_restore_state", ("example",), {"status": "idle"}),
]


@pytest.fixture
def handler_and_data(tmp_path):
    config = {
        "BACKUP_SCRIPTS_DIR": str(tmp_path / "config-root"),
        "BACKUP_CONF_SCHEMA_FILE": str(ROOT / "runtime/config/backup.conf.example"),
    }
    data = tmp_path / "data"
    config_api.write_conf(config, {"GLOBAL_DATA_DIR": str(data)})
    config_api.ensure_data_dirs(str(data))
    handler = object.__new__(BackupUIHandler)
    handler.config = config
    return handler, data


@pytest.mark.parametrize("method,query,dependency,args,result", READ_REQUESTS)
def test_restore_navigation_reads_without_changing_data_directories(
    handler_and_data, monkeypatch, method, query, dependency, args, result
):
    handler, data = handler_and_data
    downstream = Mock(return_value=result)
    monkeypatch.setattr(restore_api, dependency, downstream)
    monkeypatch.setattr(restore_api, "list_allowed_target_roots", lambda _config: ["/mnt/user"])
    paths = [data, *data.rglob("*")]
    before = {p: (p.stat().st_mtime_ns, p.stat().st_ctime_ns) for p in paths}
    original_write = Path.write_text

    def no_probe(path, *a, **kw):
        assert path.name != ".borg-ui-write-test", "Navigation attempted a storage write"
        return original_write(path, *a, **kw)

    monkeypatch.setattr(Path, "write_text", no_probe)
    expected = {"files": result} if method == "_get_restore_files" else result
    if method == "_get_restore_target_dirs":
        expected = {"dirs": result, "allowed_roots": ["/mnt/user"]}
    for _ in range(3):
        assert getattr(handler, method)(query) == expected
    downstream.assert_called_with(handler.config, *args)
    assert set(data.rglob("*")) == set(paths) - {data}
    assert {p: (p.stat().st_mtime_ns, p.stat().st_ctime_ns) for p in paths} == before


@pytest.mark.parametrize("method,query,dependency,args,result", READ_REQUESTS)
@pytest.mark.parametrize("problem", ["missing", "unwritable", "unmounted"])
def test_restore_navigation_rejects_unavailable_storage_without_repair(
    handler_and_data, monkeypatch, method, query, dependency, args, result, problem
):
    handler, data = handler_and_data
    if problem == "missing":
        (data / "status").rmdir()
    elif problem == "unwritable":
        monkeypatch.setattr(config_api.os, "access", lambda *_: False)
    else:
        config_api.write_conf(handler.config, {"GLOBAL_DATA_DIR": "/mnt/user/unavailable"})
        monkeypatch.setattr(config_api, "_is_required_storage_mount_available", lambda _: False)
    downstream = Mock(side_effect=AssertionError("Unavailable storage must block the operation"))
    monkeypatch.setattr(restore_api, dependency, downstream)
    with pytest.raises(RuntimeError):
        getattr(handler, method)(query)
    downstream.assert_not_called()
    if problem == "missing":
        assert not (data / "status").exists()


@pytest.mark.parametrize("method", [
    "_post_run_job", "_post_run_check", "_post_restore_start", "_post_restore_precheck",
    "_start_restore_test_from_body", "_handle_restore_download",
])
def test_actual_actions_still_fail_when_storage_write_probe_fails(handler_and_data, monkeypatch, method):
    handler, _data = handler_and_data
    original_write = Path.write_text

    def fail_probe(path, *args, **kwargs):
        if path.name == ".borg-ui-write-test":
            raise OSError("simulated storage write failure")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_probe)
    if method == "_handle_restore_download":
        handler.send_error = Mock()
        handler._handle_restore_download(None)
        handler.send_error.assert_called_once_with(500, "simulated storage write failure")
    else:
        with pytest.raises(OSError, match="simulated storage write failure"):
            args = ({},) if method == "_start_restore_test_from_body" else ()
            getattr(handler, method)(*args)
