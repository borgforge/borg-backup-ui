"""Explicit packaging targets; this is not an Unraid 8 runtime adapter (#671)."""
import re

PLATFORMS = ("unraid-legacy", "unraid-8")
CHANNELS = ("testing", "stable")
BASE_URL = "https://raw.githubusercontent.com/borgforge/borg-backup-ui"


def target(platform: str, channel: str) -> dict[str, str]:
    """Return enabled legacy channel metadata or fail before producing files.

    Unraid 8 has no implemented package/SDK contract. Both of its channels fail
    closed instead of falling back to a legacy package or inventing feed URLs.
    """
    if platform not in PLATFORMS or channel not in CHANNELS:
        raise ValueError("Unknown platform or channel")
    if platform == "unraid-8":
        raise ValueError("Unraid 8 target is blocked: SDK and target-system validation required (#549)")
    ref = "test-channel" if channel == "testing" else "main"
    name = "borg-backup-ui-test.plg" if channel == "testing" else "borg-backup-ui.plg"
    return {"platform": platform, "channel": channel, "ref": ref,
            "manifest": name, "plugin_url": f"{BASE_URL}/{ref}/{name}",
            "package_url": f"{BASE_URL}/{ref}/releases/borg-backup-ui-{{version}}.txz"}


def validate_version(version: str) -> str:
    """Validate the existing sortable plugin version schema; do not allocate one."""
    from datetime import datetime
    if not re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]{4}", version):
        raise ValueError("Version must be YYYY.MM.DD.HHMM")
    datetime.strptime(version, "%Y.%m.%d.%H%M")
    return version


def require_host_generation(platform: str, unraid_version: str) -> None:
    """Reject cross-generation selection; does not certify OS/SDK compatibility.

    For future adapter/install gates only; no existing host config is modified.
    Unknown/malformed versions fail closed. Legacy means major version below 8.
    """
    if platform not in PLATFORMS or not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:[-.][A-Za-z0-9.-]+)?", unraid_version):
        raise ValueError("Unknown platform or malformed Unraid version")
    major = int(unraid_version.split(".")[0])
    if major < 6 or (platform == "unraid-legacy") != (major < 8):
        raise ValueError("Unraid version does not match the selected plugin generation")
