"""Keep configured cache restore roots consistent across settings and runtime."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "api", ROOT / "runtime" / "lib"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import config_api
import restore_api


def test_restore_root_rules_match_in_settings_config_and_runtime():
    cases = {
        "/mnt/cache": True, "/mnt/cache/": True, "/mnt/cache/appdata": True,
        "/mnt/cache/appdata/": True, "/mnt/user": True, "/mnt/user/appdata": True,
        "/mnt/data": True, "/mnt/disk1": True, "/mnt/disks/USB": True,
        "/mnt/remotes/NAS": True, "/mnt/cache-other": False, "/mnt/cache2": False,
        "mnt/cache": False, "/": False, "/mnt": False, "/boot": False,
        "/mnt/disks": False, "/mnt/remotes": False,
    }
    for path, expected in cases.items():
        assert config_api._is_safe_restore_root_value(path) is expected, path
        assert restore_api._is_safe_restore_root_text(path) is expected, path
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for settings UI validation")
    script = """
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const context = vm.createContext({window: {addEventListener() {}}, locationIcon: () => ''});
vm.runInContext(fs.readFileSync('ui/js/pages/settings.js', 'utf8'), context);
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
for (const [path, expected] of Object.entries(cases)) {
  assert.equal(context.isSafeRestoreRoot(path), expected, path);
}
assert.equal(context.parseRestoreAllowedRoots('/mnt/user,/mnt/cache/').join(','), '/mnt/user,/mnt/cache');
assert.equal(context.parseRestoreAllowedRoots('').join(','), '/mnt/user');
"""
    subprocess.run([node, "-e", script], input=json.dumps(cases), text=True, cwd=ROOT, check=True)


def test_cache_root_round_trip_is_opt_in(tmp_path):
    config = {"BACKUP_SCRIPTS_DIR": str(tmp_path),
              "BACKUP_CONF_SCHEMA_FILE": str(ROOT / "runtime/config/backup.conf.example")}
    assert restore_api.list_allowed_target_roots(config) == ["/mnt/user"]
    roots = "/mnt/user,/mnt/cache/"
    config_api.write_conf(config, {"RESTORE_ALLOWED_ROOTS": roots})
    assert config_api.read_expanded_conf(config)["RESTORE_ALLOWED_ROOTS"] == roots
    assert restore_api.list_allowed_target_roots(config) == ["/mnt/user", "/mnt/cache"]
    warnings = config_api.validate_runtime_config(config)["warnings"]
    assert not any(item["key"] == "RESTORE_ALLOWED_ROOTS" for item in warnings)


def test_cache_target_keeps_access_and_containment_checks(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    appdata = cache / "appdata"
    appdata.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (cache / "escape").symlink_to(outside, target_is_directory=True)
    (cache / "file").write_text("not a directory")

    # Map the Unraid pool into this test's directory, preserving real symlink resolution.
    resolve = Path.resolve

    def resolve_cache(path, *args, **kwargs):
        if path == Path("/mnt/cache") or Path("/mnt/cache") in path.parents:
            path = cache / path.relative_to("/mnt/cache")
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_cache)
    conf = {"RESTORE_ALLOWED_ROOTS": "/mnt/user"}
    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: conf)
    with pytest.raises(ValueError, match="outside"):
        restore_api._validate_target_dir("/mnt/cache/appdata", {})
    conf["RESTORE_ALLOWED_ROOTS"] = "/mnt/cache"
    assert restore_api._validate_target_dir("/mnt/cache/", {}) == cache
    assert restore_api._validate_target_dir("/mnt/cache/appdata", {}) == appdata
    for path, error in (("escape", "outside"), ("../outside", "outside"),
                        ("missing", "does not exist"), ("file", "not a directory")):
        with pytest.raises(ValueError, match=error):
            restore_api._validate_target_dir(f"/mnt/cache/{path}", {})
    monkeypatch.setattr(restore_api.os, "access", lambda *_args: False)
    with pytest.raises(ValueError, match="not writable"):
        restore_api._validate_target_dir("/mnt/cache/appdata", {})
