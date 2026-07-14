"""Shared SMB protocol policy and mount diagnostics."""

from __future__ import annotations

import re
from typing import Any


SMB_VERSION_AUTO = "auto"
SMB_SUPPORTED_VERSIONS = ("3.1.1", "3.0", "2.1", "2.0")


def normalize_smb_version(value: Any, *, default: str = SMB_VERSION_AUTO) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        raw = str(default or SMB_VERSION_AUTO).strip().lower()
    if raw in {"auto", "automatic", "default"}:
        return SMB_VERSION_AUTO
    if raw in {"1", "1.0", "nt1", "cifs"}:
        raise ValueError("SMB1 is not supported. Use automatic SMB 2/3 negotiation.")
    if raw not in SMB_SUPPORTED_VERSIONS:
        supported = ", ".join((SMB_VERSION_AUTO, *SMB_SUPPORTED_VERSIONS))
        raise ValueError(f"Unsupported SMB version '{raw}'. Supported values: {supported}.")
    return raw


def smb_version_options(value: Any) -> list[str]:
    version = normalize_smb_version(value)
    return [] if version == SMB_VERSION_AUTO else [f"vers={version}"]


def sanitize_smb_error(message: Any) -> str:
    text = str(message or "").strip()
    text = re.sub(r"(?i)(password\s*=\s*)[^,\s]+", r"\1***", text)
    text = re.sub(r"(?i)(credentials\s*=\s*)[^,\s]+", r"\1***", text)
    return text[:2000]


def classify_smb_mount_error(message: Any) -> tuple[str, str]:
    technical = sanitize_smb_error(message)
    low = technical.lower()
    if any(marker in low for marker in (
        "mount error(13)", "permission denied", "access denied", "logon failure",
    )):
        return (
            "SMB_AUTH_OR_PERMISSION_FAILED",
            "Authentication or share permissions were rejected. Check the username, password and share permissions.",
        )
    if any(marker in low for marker in (
        "mount error(2)", "mount error(6)", "no such file", "no such device or address",
        "bad network name", "object name not found",
    )):
        return (
            "SMB_SHARE_NOT_FOUND",
            "The SMB share was not found. Check the server and share name.",
        )
    if any(marker in low for marker in (
        "mount error(22)", "invalid argument", "protocol not supported", "operation not supported",
        "unsupported dialect", "no dialect specified",
    )):
        return (
            "SMB_PROTOCOL_OR_OPTIONS_FAILED",
            "The SMB protocol or mount options were rejected. Use automatic SMB 2/3 negotiation or select a supported SMB 2/3 version.",
        )
    if any(marker in low for marker in (
        "connection timed out", "host is down", "no route to host", "connection refused",
        "network is unreachable", "could not resolve", "name or service not known",
    )):
        return (
            "SMB_NETWORK_UNREACHABLE",
            "The SMB server is not reachable. Check the server address, network and TCP port 445.",
        )
    return (
        "SMB_MOUNT_FAILED",
        "The SMB share could not be mounted. Review the technical details and the server configuration.",
    )


def build_smb_mount_options(profile: dict[str, Any], credentials_file: Any) -> list[str]:
    credentials = str(credentials_file or "").strip()
    if not credentials:
        raise ValueError("SMB credentials file is required")
    options = [f"credentials={credentials}", "iocharset=utf8"]
    options.extend(smb_version_options(profile.get("vers")))
    sec = str(profile.get("sec") or "").strip()
    if sec:
        if not re.fullmatch(r"[A-Za-z0-9_+.-]+", sec):
            raise ValueError("Invalid SMB security option")
        options.append(f"sec={sec}")
    for key in ("uid", "gid", "file_mode", "dir_mode"):
        raw = str(profile.get(key) or "").strip()
        if not raw:
            continue
        if not re.fullmatch(r"[\w.:/+@-]+", raw):
            raise ValueError(f"Invalid SMB option value: {key}")
        options.append(f"{key}={raw}")
    return options
