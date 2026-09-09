"""Exercise the service launcher with an isolated payload and RAM-cache path (#497)."""

import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def _launcher(tmp_path):
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    cache = tmp_path / "ram/pycache"
    (plugin / "bbui_cache_example.py").write_text("VALUE = 497\n")
    (plugin / "borg_backup_ui.py").write_text('''
import json, os, pathlib, subprocess, sys
import bbui_cache_example
root = pathlib.Path(__file__).parent
child = subprocess.check_output([
    sys.executable, "-c",
    "import bbui_cache_example, json, sys; print(json.dumps({'prefix': sys.pycache_prefix, 'value': bbui_cache_example.VALUE}))"
], cwd=root, text=True)
report = {'prefix': sys.pycache_prefix, 'cached': bbui_cache_example.__cached__,
          'child': json.loads(child), 'value': bbui_cache_example.VALUE}
temporary = root / 'result.tmp'
temporary.write_text(json.dumps(report))
temporary.replace(root / 'result.json')
''')
    script = (ROOT / "plugin/rc.borg_backup_ui").read_text()
    replacements = {
        "/boot/config/plugins/borg-backup-ui": str(plugin),
        "/run/borg-backup-ui/pycache": str(cache),
        "/var/run/borg_backup_ui.pid": str(tmp_path / "service.pid"),
        "/var/run/borg_backup_ui_start_wait.pid": str(tmp_path / "wait.pid"),
        "/var/log/borg_backup_ui.log": str(tmp_path / "service.log"),
    }
    for original, replacement in replacements.items():
        assert original in script
        script = script.replace(original, replacement)
    launcher = tmp_path / "rc.borg_backup_ui"
    launcher.write_text(script)
    return launcher, plugin, cache


def _start(launcher, plugin, tmp_path):
    report = plugin / "result.json"
    report.unlink(missing_ok=True)
    # Isolate the launcher from developer Python settings and an earlier exited
    # test payload's PID. The production stop/start lifecycle is unchanged.
    (tmp_path / "service.pid").unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPYCACHEPREFIX"] = str(tmp_path / "wrong-cache")
    run = subprocess.run(["bash", str(launcher), "start"], env=env, capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    deadline = time.monotonic() + 10
    while not report.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert report.exists(), (tmp_path / "service.log").read_text()
    return json.loads(report.read_text())


def test_service_and_child_processes_reuse_cache_outside_plugin(tmp_path):
    launcher, plugin, cache = _launcher(tmp_path)
    first = _start(launcher, plugin, tmp_path)
    cached = Path(first["cached"])
    assert first["prefix"] == str(cache)
    assert first["child"] == {"prefix": str(cache), "value": 497}
    assert cached.is_relative_to(cache) and cached.is_file()
    assert cache.stat().st_mode & 0o777 == 0o700
    before = (cached.stat().st_ino, cached.stat().st_mtime_ns)
    second = _start(launcher, plugin, tmp_path)
    assert second == first
    assert (cached.stat().st_ino, cached.stat().st_mtime_ns) == before
    assert not list(plugin.rglob("*.pyc"))
    assert not (tmp_path / "wrong-cache").exists()


def test_unavailable_optional_cache_does_not_block_service_or_write_to_plugin(tmp_path):
    launcher, plugin, cache = _launcher(tmp_path)
    cache.parent.mkdir()
    cache.write_text("not a directory")
    report = _start(launcher, plugin, tmp_path)
    assert report["value"] == report["child"]["value"] == 497
    assert report["prefix"] == report["child"]["prefix"] == str(cache)
    assert not list(plugin.rglob("*.pyc"))
    assert not (tmp_path / "wrong-cache").exists()
    assert cache.read_text() == "not a directory"
    assert "bytecode writes are disabled" in (tmp_path / "service.log").read_text()
