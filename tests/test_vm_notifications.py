import json
import logging
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from lib.vm_manager import VmManager  # noqa: E402


def test_notify_send_runs_as_guest_user(monkeypatch):
    manager = VmManager()
    captured = {}

    def fake_guest_exec(vm_name, payload, *, timeout=15):
        captured["vm_name"] = vm_name
        captured["payload"] = json.loads(payload)
        captured["timeout"] = timeout
        return {"ok": True, "detail": ""}

    monkeypatch.setattr(manager, "_guest_exec_and_wait", fake_guest_exec)

    manager._send_notify_send("LinuxMint", "tsteinbe", "1000", "Backup startet")

    args = captured["payload"]["arguments"]
    assert captured["vm_name"] == "LinuxMint"
    assert args["path"] == "/usr/sbin/runuser"
    assert args["arg"] == [
        "-u", "tsteinbe",
        "--",
        "/usr/bin/env",
        "DISPLAY=:0",
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus",
        "/usr/bin/notify-send",
        "--urgency=critical",
        "-t", "120000",
        "Backup-Wartung",
        "Backup startet",
    ]
    assert args["capture-output"] is True


def test_notify_send_failure_is_info_hint(monkeypatch, caplog):
    manager = VmManager()

    def fake_guest_exec(vm_name, payload, *, timeout=15):
        return {"ok": False, "detail": "exit=1 dbus denied"}

    monkeypatch.setattr(manager, "_guest_exec_and_wait", fake_guest_exec)

    with caplog.at_level(logging.INFO, logger="lib.vm_manager"):
        manager._send_notify_send("LinuxMint", "tsteinbe", "1000", "Backup startet")

    assert "Hinweis: Desktop-Benachrichtigung konnte nicht bestätigt werden" in caplog.text
    assert "exit=1 dbus denied" in caplog.text


def test_guest_exec_and_wait_returns_failure_instead_of_raising(monkeypatch):
    manager = VmManager()

    def fake_run(*args, **kwargs):
        raise OSError("virsh unavailable")

    monkeypatch.setattr("lib.vm_manager.subprocess.run", fake_run)

    result = manager._guest_exec_and_wait("LinuxMint", "{}")

    assert result["ok"] is False
    assert result["detail"] == "guest-exec konnte nicht geprüft werden"
