from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from storagebox_api import (
    _detect_storage_target_type,
    _sanitize_ssh_noise,
    _storagebox_profile,
    _storagebox_ssh_base_cmd,
)


def test_storagebox_profile_preserves_storagebox_base_path():
    profile = _storagebox_profile({
        "STORAGEBOX_HOST": "u123.your-storagebox.de",
        "STORAGEBOX_PORT": "23",
        "STORAGEBOX_USER": "u123",
        "STORAGEBOX_BASE_PATH": "/./backup",
        "BORG_SSH_KEY": "/root/.ssh/id_ed25519",
    })

    assert profile["host"] == "u123.your-storagebox.de"
    assert profile["base_path"] == "/./backup"
    assert profile["ssh_key"] == "/root/.ssh/id_ed25519"


def test_storagebox_profile_normalizes_generic_relative_base_path():
    profile = _storagebox_profile({"STORAGEBOX_BASE_PATH": "volume1/backup"})

    assert profile["base_path"] == "/volume1/backup"


def test_storagebox_ssh_base_cmd_uses_batch_mode_and_key_by_default():
    cmd = _storagebox_ssh_base_cmd({
        "host": "box.example.test",
        "port": "23",
        "user": "u123",
        "ssh_key": "/root/.ssh/key",
    })

    assert cmd[:2] == ["ssh", "-p"]
    assert "BatchMode=yes" in cmd
    assert cmd[-3:] == ["-i", "/root/.ssh/key", "u123@box.example.test"]


def test_storagebox_ssh_base_cmd_password_mode_disables_batch_mode():
    cmd = _storagebox_ssh_base_cmd({
        "host": "box.example.test",
        "port": "22",
        "user": "u123",
        "ssh_key": "",
    }, batch_mode=False, force_tty=True)

    assert "-tt" in cmd
    assert "BatchMode=no" in cmd
    assert "PasswordAuthentication=yes" in cmd
    assert cmd[-1] == "u123@box.example.test"


def test_detect_storage_target_type_storagebox_heuristic():
    result = _detect_storage_target_type({
        "host": "u123.your-storagebox.de",
        "port": "23",
        "base_path": "/./backup",
        "user": "u123",
    })

    assert result["target_type"] == "storagebox"
    assert result["method"] == "heuristic"


def test_detect_storage_target_type_synology_heuristic():
    result = _detect_storage_target_type({
        "host": "nas.synology.me",
        "port": "22",
        "base_path": "/volume1/backup",
        "user": "backup",
    })

    assert result["target_type"] == "synology"
    assert result["method"] == "heuristic"


def test_sanitize_ssh_noise_removes_known_hosts_permission_noise():
    cleaned = _sanitize_ssh_noise(
        "ok\n"
        "hostfile_replace_entries: link /root/.ssh/known_hosts: Operation not permitted\n"
        "update_known_hosts: known hosts update failed: Operation not permitted\n"
        "done\n"
    )

    assert cleaned == "ok\ndone"
