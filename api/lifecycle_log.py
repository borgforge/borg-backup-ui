"""Compact lifecycle summary logging for support diagnostics."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .security_utils import mask_secrets
except ImportError:  # Runtime scripts import api modules directly from sys.path.
    from security_utils import mask_secrets


_SAFE_VALUE_RX = re.compile(r"^[A-Za-z0-9_./:@+=,-]+$")
_SECRET_FIELD_RX = re.compile(r"(?i)(password|passphrase|token|secret)")


def _main_log_path() -> Path | None:
    configured = str(os.environ.get("BORG_UI_MAIN_LOG") or "").strip()
    if configured:
        return Path(configured)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    return Path("/var/log/borg_backup_ui.log")


def _clean_value(value: Any, *, max_len: int = 300) -> str:
    text = mask_secrets(str(value or "").replace("\r", " ").replace("\n", " ").strip())
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        cleaned = [_clean_value(item, max_len=120) for item in value if _clean_value(item, max_len=120)]
        return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    text = _clean_value(value)
    if text and _SAFE_VALUE_RX.fullmatch(text):
        return text
    return json.dumps(text, ensure_ascii=False)


def emit_lifecycle(component: str, stage: str, **fields: Any) -> None:
    """Append one masked key-value lifecycle line to the main application log."""
    comp = _clean_value(component, max_len=40).upper()
    stage_text = _clean_value(stage, max_len=60)
    if not comp or not stage_text:
        return
    parts = [comp, stage_text]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, set)) and not value:
            continue
        safe_key = re.sub(r"[^A-Za-z0-9_]", "_", str(key or "").strip())
        if not safe_key:
            continue
        if _SECRET_FIELD_RX.search(safe_key):
            parts.append(f"{safe_key}=***")
            continue
        parts.append(f"{safe_key}={_format_value(value)}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {' '.join(parts)}\n"
    try:
        path = _main_log_path()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return
