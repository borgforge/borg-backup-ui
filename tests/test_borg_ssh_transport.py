import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


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
    assert options["IgnoreUnknown"] == "WarnWeakCrypto"
    assert options["WarnWeakCrypto"] == "no"
    assert tokens.index("IgnoreUnknown=WarnWeakCrypto") < tokens.index("WarnWeakCrypto=no")
    assert "ServerAliveCountMax=3" not in tokens


@pytest.mark.parametrize("existing", [
    "ssh -o WarnWeakCrypto=yes",
    "ssh -oWarnWeakCrypto=yes -oIgnoreUnknown=WarnWeakCrypto",
    "ssh -o 'WarnWeakCrypto yes' -o 'IgnoreUnknown WarnWeakCrypto'",
    "ssh -o warnweakcrypto=yes -o ignoreunknown=warnweakcrypto",
])
def test_borg_ssh_normalization_keeps_one_ordered_compatibility_pair(existing):
    command = build_borg_rsh(existing, "/root/.ssh/storage key")
    tokens = shlex.split(command)
    options = _ssh_options(command)

    assert options["IgnoreUnknown"].lower() == "warnweakcrypto"
    assert options["WarnWeakCrypto"] == "no"
    assert sum(token.lower().startswith("ignoreunknown=") for token in tokens) == 1
    assert sum(token.lower().startswith("warnweakcrypto=") for token in tokens) == 1
    assert tokens.index("IgnoreUnknown=" + options["IgnoreUnknown"]) < tokens.index("WarnWeakCrypto=no")
    assert build_borg_rsh(command, "/root/.ssh/storage key") == command


@pytest.mark.parametrize("option", [
    "-o IgnoreUnknown=BBUIOptionalTestOption",
    "-oIgnoreUnknown=BBUIOptionalTestOption",
    "-o 'IgnoreUnknown BBUIOptionalTestOption'",
])
def test_borg_ssh_preserves_existing_ignore_list_and_its_position(option):
    command = build_borg_rsh(
        f"ssh {option} -o BBUIOptionalTestOption=yes "
        "-o IgnoreUnknown=UnusedLaterList -o ProxyJump=gateway -i /old/key",
        "/new/key",
    )
    tokens = shlex.split(command)
    options = _ssh_options(command)

    assert options["IgnoreUnknown"] == "BBUIOptionalTestOption,WarnWeakCrypto"
    assert tokens.index("IgnoreUnknown=" + options["IgnoreUnknown"]) < tokens.index("BBUIOptionalTestOption=yes")
    assert options["ProxyJump"] == "gateway"
    assert "IgnoreUnknown=UnusedLaterList" not in tokens
    assert "/old/key" not in tokens
    assert tokens[tokens.index("-i") + 1] == "/new/key"
    assert build_borg_rsh(command, "/new/key") == command


@pytest.mark.skipif(shutil.which("ssh") is None, reason="OpenSSH client is unavailable")
@pytest.mark.parametrize("existing", [
    "ssh",
    "ssh -o IgnoreUnknown=BBUIOptionalTestOption -o BBUIOptionalTestOption=yes",
])
def test_borg_ssh_options_are_accepted_by_real_client_without_connecting(existing):
    result = subprocess.run(
        shlex.split(build_borg_rsh(existing)) + ["-F", "/dev/null", "-G", "127.0.0.1"],
        capture_output=True, text=True, timeout=10,
    )

    assert result.returncode == 0, result.stderr
    effective = dict(line.split(" ", 1) for line in result.stdout.splitlines() if " " in line)
    assert effective["serveraliveinterval"] == "30"
    assert effective["serveralivecountmax"] == "10"
    # New clients expose the setting; older clients must accept its absence.
    if "warnweakcrypto" in effective:
        assert effective["warnweakcrypto"] == "no"


@pytest.mark.skipif(shutil.which("ssh") is None, reason="OpenSSH client is unavailable")
def test_borg_ssh_does_not_ignore_unrelated_unknown_options():
    result = subprocess.run(
        shlex.split(build_borg_rsh())
        + ["-F", "/dev/null", "-G", "-o", "BBUIUnsupportedTestOption=yes", "127.0.0.1"],
        capture_output=True, text=True, timeout=10,
    )

    assert result.returncode != 0
    assert "bad configuration option: bbuiunsupportedtestoption" in result.stderr.lower()


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
