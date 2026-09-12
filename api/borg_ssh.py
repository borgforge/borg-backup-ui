"""Shared SSH transport configuration and disconnect classification for Borg."""

from __future__ import annotations

import shlex
from typing import Mapping, MutableMapping


SSH_INTERRUPTION_CODE = "borg_ssh_connection_interrupted"
SSH_INTERRUPTION_MESSAGE = (
    "The SSH connection to the storage target was interrupted. The Borg operation "
    "is incomplete; this does not necessarily indicate repository damage. Check "
    "the network connection and retry the operation."
)

_SSH_OPTIONS = (
    ("Compression", "no"),
    ("ServerAliveInterval", "30"),
    ("ServerAliveCountMax", "10"),
    ("TCPKeepAlive", "yes"),
    ("Ciphers", "aes128-gcm@openssh.com,chacha20-poly1305@openssh.com"),
    ("ControlMaster", "auto"),
    ("ControlPath", "/tmp/ssh-borg-%r@%h:%p"),
    ("ControlPersist", "600"),
    ("LogLevel", "ERROR"),
    ("WarnWeakCrypto", "no"),
)
_MANAGED_OPTION_NAMES = {name.lower() for name, _ in _SSH_OPTIONS} | {"ignoreunknown"}
_SSH_INTERRUPTION_MARKERS = (
    "connection reset by peer",
    "broken pipe",
    "connection closed by remote host",
    "client_loop: send disconnect",
    "packet_write_wait",
    "write failed",
    "connection timed out",
)


def _option_name(value: str) -> str:
    parts = str(value or "").replace("=", " ", 1).split(maxsplit=1)
    return parts[0].lower() if parts else ""


def build_borg_rsh(existing: str = "", identity_file: str = "") -> str:
    """Return one SSH command with the managed Borg transport options applied."""
    try:
        tokens = shlex.split(str(existing or "").strip())
    except ValueError:
        tokens = []
    if not tokens:
        tokens = ["ssh"]

    identity = str(identity_file or "").strip()
    cleaned: list[str] = []
    ignore_unknown_seen = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        option = None
        option_length = 1
        if token == "-o" and index + 1 < len(tokens):
            option = tokens[index + 1]
            option_length = 2
        elif token.startswith("-o") and len(token) > 2:
            option = token[2:]
        if option is not None:
            name = _option_name(option)
            if name == "ignoreunknown" and not ignore_unknown_seen:
                # SSH uses the first list. Extend it in place so any custom
                # options following it still have their original exemption.
                parts = option.replace("=", " ", 1).split(maxsplit=1)
                patterns = parts[1].split(",") if len(parts) > 1 else []
                if "warnweakcrypto" not in {pattern.lower() for pattern in patterns}:
                    patterns.append("WarnWeakCrypto")
                cleaned.extend(("-o", "IgnoreUnknown=" + ",".join(patterns)))
                ignore_unknown_seen = True
            elif name not in _MANAGED_OPTION_NAMES:
                cleaned.extend(tokens[index:index + option_length])
            index += option_length
            continue
        if identity and token == "-i" and index + 1 < len(tokens):
            index += 2
            continue
        if identity and token.startswith("-i") and len(token) > 2:
            index += 1
            continue
        cleaned.append(token)
        index += 1

    # Older clients must see this exemption before WarnWeakCrypto is parsed.
    if not ignore_unknown_seen:
        cleaned.extend(("-o", "IgnoreUnknown=WarnWeakCrypto"))
    if identity:
        cleaned.extend(("-i", identity))
    for name, value in _SSH_OPTIONS:
        cleaned.extend(("-o", f"{name}={value}"))
    return shlex.join(cleaned)


def is_ssh_storage(storage: Mapping[str, object] | None, repository: str = "") -> bool:
    row = storage or {}
    storage_type = str(row.get("storage_type") or "").strip().lower()
    location = str(row.get("location") or "").strip().lower()
    return storage_type == "ssh" or location == "storagebox" or str(repository or "").strip().startswith("ssh://")


def configure_borg_ssh(
    env: MutableMapping[str, str],
    storage: Mapping[str, object] | None = None,
    repository: str = "",
) -> MutableMapping[str, str]:
    """Apply the shared transport to the SSH process started by Borg."""
    if not is_ssh_storage(storage, repository):
        return env
    row = storage or {}
    identity = str(row.get("ssh_key_path") or "").strip()
    env["BORG_RSH"] = build_borg_rsh(str(env.get("BORG_RSH") or ""), identity)
    return env


def is_ssh_connection_interruption(output: object) -> bool:
    text = str(output or "").lower()
    return any(marker in text for marker in _SSH_INTERRUPTION_MARKERS)
