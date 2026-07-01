"""Security-related formatting helpers shared by API modules."""

from __future__ import annotations

import re


_KEY_VALUE_SECRET_RX = re.compile(
    r"(?i)\b(password|passphrase|token|secret)\b(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_RX = re.compile(r"(?i)\b(authorization\s*:\s*bearer\s+)([^\s,;]+)")
_URL_USERINFO_RX = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@")
_QUERY_SECRET_RX = re.compile(r"(?i)([?&](?:password|passphrase|token|secret|key)=)([^&#\s]+)")
_SECRET_PATH_RX = re.compile(r"(/boot/config/borg-backup/secrets/)[^\s,;\"']+")
_BORG_PASSCOMMAND_RX = re.compile(r"(?i)\b(BORG_PASSCOMMAND\s*=\s*cat\s+)([^\s,;]+)")


def mask_secrets(text: str) -> str:
    """Mask common secret formats before text reaches logs, UI, or API output."""
    out = str(text or "")
    out = _BEARER_RX.sub(lambda m: f"{m.group(1)}***", out)
    out = _KEY_VALUE_SECRET_RX.sub(lambda m: f"{m.group(1)}{m.group(2)}***", out)
    out = _URL_USERINFO_RX.sub(lambda m: f"{m.group(1)}{m.group(2)}:***@", out)
    out = _QUERY_SECRET_RX.sub(lambda m: f"{m.group(1)}***", out)
    out = _SECRET_PATH_RX.sub(lambda m: f"{m.group(1)}***", out)
    out = _BORG_PASSCOMMAND_RX.sub(lambda m: f"{m.group(1)}***", out)
    return out
