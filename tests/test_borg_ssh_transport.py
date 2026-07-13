import shlex
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from borg_ssh import (  # noqa: E402
    SSH_INTERRUPTION_CODE,
    build_borg_rsh,
    configure_borg_ssh,
    is_ssh_connection_interruption,
)


def _ssh_options(command: str) -> dict[str, str]:
    tokens = shlex.split(command)
    options = {}
    for index, token in enumerate(tokens):
        if token == "-o" and index + 1 < len(tokens):
            key, _, value = tokens[index + 1].partition("=")
            options[key] = value
    return options


def test_borg_ssh_keeps_custom_options_and_applies_managed_keepalives():
    command = build_borg_rsh(
        "ssh -o ProxyJump=backup-gateway -o ServerAliveCountMax=3",
        "/root/.ssh/storage box",
    )
    tokens = shlex.split(command)
    options = _ssh_options(command)

    assert tokens[0] == "ssh"
    assert tokens[tokens.index("-i") + 1] == "/root/.ssh/storage box"
    assert options["ProxyJump"] == "backup-gateway"
    assert options["ServerAliveInterval"] == "30"
    assert options["ServerAliveCountMax"] == "10"
    assert options["TCPKeepAlive"] == "yes"
    assert options["ControlPersist"] == "600"
    assert options["WarnWeakCrypto"] == "no"
    assert "ServerAliveCountMax=3" not in tokens


def test_borg_ssh_is_only_configured_for_ssh_targets():
    local_env = {"BORG_RSH": "custom-command"}
    configure_borg_ssh(local_env, {"storage_type": "local"}, "/mnt/backup/repo")
    assert local_env["BORG_RSH"] == "custom-command"

    ssh_env = {}
    configure_borg_ssh(
        ssh_env,
        {"storage_type": "ssh", "ssh_key_path": "/root/.ssh/id_storage"},
        "ssh://backup@example.test/./repo",
    )
    assert _ssh_options(ssh_env["BORG_RSH"])["ServerAliveCountMax"] == "10"
    assert "/root/.ssh/id_storage" in shlex.split(ssh_env["BORG_RSH"])


def test_borg_ssh_connection_interruption_matches_real_world_output():
    output = """Remote: Read from remote host storage.example.test: Connection reset by peer
Remote: client_loop: send disconnect: Broken pipe
Connection closed by remote host.
"""

    assert is_ssh_connection_interruption(output) is True
    assert is_ssh_connection_interruption("Permission denied (publickey).") is False
    assert SSH_INTERRUPTION_CODE == "borg_ssh_connection_interrupted"
