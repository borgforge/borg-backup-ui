"""
lib/notifications.py - Unraid Notify + E-Mail Benachrichtigungen
Version: 1.0.0

Ersetzt notify() und send_mail() aus lib/borg-common.sh.

Verbesserungen gegenüber Bash:
- send_mail() nutzt smtplib statt ssmtp (kein externes Tool)
- Mail-Versand ist best-effort: Fehler werden geloggt, Backup-Exit-Code bleibt unberührt
- Unraid-Notify per subprocess (kein Shell-Escaping nötig)
- Level-Normalisierung als Dict statt case-Statement

Nur Python Standard-Library: smtplib, email, subprocess, logging, pathlib
"""

from __future__ import annotations

import base64
import logging
import smtplib
import subprocess
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

logger = logging.getLogger(__name__)

# Unraid notify binary
_NOTIFY_BIN = "/usr/local/emhttp/webGui/scripts/notify"

# Level-Normalisierung (entspricht case-Statement in borg-common.sh notify())
_LEVEL_MAP: dict[str, str] = {
    "info": "normal",
    "ok": "normal",
    "normal": "normal",
    "": "normal",
    "warn": "warning",
    "warning": "warning",
    "warnung": "warning",
    "err": "alert",
    "error": "alert",
    "fehler": "alert",
    "alert": "alert",
}

# Unraid -m flag Werte (unterschiedlich von -i icon)
_IMPORTANCE_MAP: dict[str, str] = {
    "normal": "normal",
    "warning": "warning",
    "alert": "alert",
}


# ---------------------------------------------------------------------------
# Dataclass für Mail-Konfiguration
# ---------------------------------------------------------------------------

@dataclass
class MailConfig:
    """
    Mail-Konfiguration – Werte kommen aus backup.conf, nicht von hier.

    Diese Defaults werden nie direkt verwendet.
    Immer via MailConfig.from_config(load_config(...)) befüllen.
    """

    # Konfiguration erfolgt in config/backup.conf (GLOBAL_MAIL_* / GLOBAL_SMTP_*)
    recipient: str = ""
    sender: str = ""
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False

    @classmethod
    def from_config(cls, config: Dict[str, str]) -> "MailConfig":
        """
        Erstellt MailConfig aus einem backup.conf Dict (von load_config() aus status.py).

        Liest folgende Schlüssel:
            GLOBAL_MAIL_RECIPIENT, GLOBAL_MAIL_SENDER,
            GLOBAL_SMTP_HOST, GLOBAL_SMTP_PORT,
            GLOBAL_SMTP_USER, GLOBAL_SMTP_PASSWORD, GLOBAL_SMTP_USE_TLS

        Beispiel:
            from lib.status import load_config
            from lib.notifications import MailConfig
            cfg = load_config(Path("config/backup.conf"))
            mail = MailConfig.from_config(cfg)
        """
        use_tls_raw = config.get("GLOBAL_SMTP_USE_TLS", "false").lower()
        use_tls = use_tls_raw in ("true", "yes", "1")

        port_raw = config.get("GLOBAL_SMTP_PORT", "25")
        try:
            port = int(port_raw)
        except ValueError:
            logger.warning("Invalid GLOBAL_SMTP_PORT ('%s'); using 25", port_raw)
            port = 25

        return cls(
            recipient=config.get("GLOBAL_MAIL_RECIPIENT", ""),
            sender=config.get("GLOBAL_MAIL_SENDER", ""),
            smtp_host=config.get("GLOBAL_SMTP_HOST", "localhost"),
            smtp_port=port,
            smtp_user=config.get("GLOBAL_SMTP_USER", ""),
            smtp_password=config.get("GLOBAL_SMTP_PASSWORD", ""),
            smtp_use_tls=use_tls,
        )


@dataclass
class NtfyConfig:
    enabled: bool = False
    name: str = "ntfy"
    server_url: str = ""
    topic: str = ""
    username: str = ""
    password: str = ""
    access_token: str = ""
    priority: str = ""
    tags: str = ""
    click_url: str = ""
    events: set[str] = field(default_factory=set)
    timeout_seconds: int = 15

    @classmethod
    def from_config(cls, config: Dict[str, str]) -> "NtfyConfig":
        def _flag(value: str) -> bool:
            return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

        def _read_secret(path_value: str) -> str:
            path = str(path_value or "").strip()
            if not path:
                return ""
            try:
                p = Path(path)
                if p.is_file():
                    return p.read_text(encoding="utf-8", errors="replace").strip()
            except OSError as exc:
                logger.warning("Could not read ntfy secret file %s: %s", path, exc)
            return ""

        events_raw = str(config.get("NTFY_EVENTS", "backup_success,backup_failed,backup_skipped") or "")
        events = {item.strip() for item in events_raw.split(",") if item.strip()}
        timeout = 15
        try:
            timeout = max(1, int(str(config.get("NTFY_TIMEOUT_SECONDS", "15") or "15").strip()))
        except ValueError:
            logger.warning("Invalid NTFY_TIMEOUT_SECONDS; using 15")

        return cls(
            enabled=_flag(config.get("NTFY_ENABLED", "false")),
            name=str(config.get("NTFY_PROFILE_NAME", "ntfy") or "ntfy").strip() or "ntfy",
            server_url=str(config.get("NTFY_SERVER_URL", "") or "").strip(),
            topic=str(config.get("NTFY_TOPIC", "") or "").strip().strip("/"),
            username=str(config.get("NTFY_USERNAME", "") or "").strip(),
            password=_read_secret(config.get("NTFY_PASSWORD_FILE", "")),
            access_token=_read_secret(config.get("NTFY_ACCESS_TOKEN_FILE", "")),
            priority=str(config.get("NTFY_PRIORITY", "") or "").strip(),
            tags=str(config.get("NTFY_TAGS", "") or "").strip(),
            click_url=str(config.get("NTFY_CLICK_URL", "") or "").strip(),
            events=events,
            timeout_seconds=timeout,
        )


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def notify(
    level: str,
    subject: str,
    description: str,
    job_name: str,
    icon: Optional[str] = None,
) -> bool:
    """
    Sendet eine Unraid-Systembenachrichtigung.

    Entspricht notify() in borg-common.sh.

    Args:
        level:       Severity – "info"/"ok"/"warn"/"warning"/"err"/"error"/"alert"
        subject:     Kurze Überschrift der Benachrichtigung
        description: Ausführlicher Text
        job_name:    Anzeigename der Quelle (entspricht $JOB_NAME, Unraid -e Flag)
        icon:        Optionaler Icon-Override; wird sonst aus level abgeleitet

    Returns:
        True wenn Notify erfolgreich, False bei Fehler (best-effort)
    """
    normalised = _LEVEL_MAP.get(level.lower(), "normal")
    importance = _IMPORTANCE_MAP.get(normalised, "normal")
    effective_icon = icon if icon else normalised

    if not Path(_NOTIFY_BIN).exists():
        logger.warning("Unraid notify binary not found: %s", _NOTIFY_BIN)
        return False

    cmd = [
        _NOTIFY_BIN,
        "-e", job_name,
        "-s", subject,
        "-d", description,
        "-i", effective_icon,
        "-m", importance,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.warning(
                "notify exit %d: %s", result.returncode, result.stderr.strip()
            )
            return False
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("notify failed: %s", exc)
        return False


def send_mail(
    config: MailConfig,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
) -> bool:
    """
    Sendet eine E-Mail (Best-Effort – darf Backup-Exit-Code nicht beeinflussen).

    Ersetzt send_mail() aus borg-common.sh (ssmtp → smtplib).

    Args:
        config:     MailConfig-Instanz mit SMTP-Einstellungen
        subject:    E-Mail Betreff
        body_text:  Plaintext-Inhalt (immer erforderlich)
        body_html:  Optionaler HTML-Inhalt; wenn vorhanden wird multipart/alternative gesendet

    Returns:
        True wenn Versand erfolgreich, False bei Fehler
    """
    if not config.recipient:
        logger.warning("No mail recipient configured; skipping mail delivery")
        return False

    try:
        msg = _build_message(config, subject, body_text, body_html)
        _send_smtp(config, msg)
        logger.info("Mail delivery succeeded -> %s", config.recipient)
        return True
    except Exception as exc:  # noqa: BLE001  # best-effort: alle Fehler abfangen
        logger.warning("Mail delivery failed: %s", exc)
        return False


def send_backup_log_mail(
    config: MailConfig,
    backup_type: str,
    date_tag: str,
    exit_code: int,
    duration_seconds: int,
    log_file: Optional[Path] = None,
) -> bool:
    """
    Sendet die klassische Backup-Log-Mail (entspricht send_mail() in borg-common.sh).

    Args:
        config:           MailConfig
        backup_type:      z.B. "appdata", "flash"
        date_tag:         Datum-String für Betreff, z.B. "2026-03-21"
        exit_code:        Borg Exit-Code
        duration_seconds: Backup-Dauer in Sekunden
        log_file:         Optionaler Pfad zur Log-Datei (Inhalt wird angehängt)

    Returns:
        True wenn Versand erfolgreich, False bei Fehler
    """
    duration_str = _format_duration(duration_seconds)
    subject = f"Borg Backup Summary ({backup_type}) - {date_tag}"

    header_lines = [
        f"Backup duration: {duration_str}",
        f"Exit code:       {exit_code}",
        "=" * 42,
        "",
    ]

    log_content = ""
    if log_file and Path(log_file).exists():
        try:
            log_content = Path(log_file).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Log file is not readable (%s): %s", log_file, exc)

    body_text = "\n".join(header_lines) + log_content

    return send_mail(config, subject, body_text)


def send_ntfy(
    config: NtfyConfig,
    event_type: str,
    title: str,
    message: str,
) -> bool:
    """
    Sends an ntfy push notification. Best-effort: failures are logged but do not
    influence backup results.
    """
    if not config.enabled:
        return False
    if event_type and config.events and event_type not in config.events:
        logger.info("ntfy event skipped by configuration: %s", event_type)
        return False
    if not config.server_url or not config.topic:
        logger.warning("ntfy is enabled but server URL or topic is missing")
        return False

    try:
        _send_ntfy_request(config, title, message)
        logger.info("ntfy delivery succeeded (profile=%s event=%s server=%s topic=%s)",
                    config.name, event_type, _safe_ntfy_server(config.server_url), config.topic)
        return True
    except Exception as exc:  # noqa: BLE001 - best-effort notification path
        logger.warning("ntfy delivery failed (profile=%s event=%s server=%s topic=%s): %s",
                       config.name, event_type, _safe_ntfy_server(config.server_url), config.topic, exc)
        return False


def send_ntfy_test(config: NtfyConfig) -> tuple[bool, str]:
    if not config.server_url:
        return False, "NTFY_SERVER_URL is not configured."
    if not config.topic:
        return False, "NTFY_TOPIC is not configured."
    try:
        _send_ntfy_request(
            config,
            "Borg Backup UI",
            "This is a test notification from Borg Backup UI.",
        )
        return True, f"Test notification sent to {config.topic}."
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        return False, f"ntfy HTTP {exc.code}: {detail or exc.reason}"
    except (urlerror.URLError, TimeoutError, OSError) as exc:
        return False, f"ntfy connection failed: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"ntfy request failed: {exc}"


# ---------------------------------------------------------------------------
# Hilfsfunktionen (intern)
# ---------------------------------------------------------------------------

def _build_message(
    config: MailConfig,
    subject: str,
    body_text: str,
    body_html: Optional[str],
) -> MIMEMultipart:
    if body_html:
        msg: MIMEMultipart = MIMEMultipart("alternative")
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
    else:
        msg = MIMEMultipart()
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

    msg["Subject"] = subject
    msg["From"] = config.sender or config.recipient
    msg["To"] = config.recipient
    return msg


def _send_smtp(config: MailConfig, msg: MIMEMultipart) -> None:
    if config.smtp_use_tls:
        smtp_cls = smtplib.SMTP_SSL
    else:
        smtp_cls = smtplib.SMTP

    with smtp_cls(config.smtp_host, config.smtp_port, timeout=30) as smtp:
        if not config.smtp_use_tls and config.smtp_user:
            smtp.starttls()
        if config.smtp_user:
            smtp.login(config.smtp_user, config.smtp_password)
        smtp.send_message(msg)


def _safe_ntfy_server(server_url: str) -> str:
    text = str(server_url or "").strip()
    if "@" in text:
        # Avoid logging embedded credentials if a user accidentally provides them.
        scheme, rest = text.split("://", 1) if "://" in text else ("", text)
        rest = rest.split("@", 1)[1]
        return f"{scheme}://{rest}" if scheme else rest
    return text


def _ntfy_endpoint(config: NtfyConfig) -> str:
    base = config.server_url.strip().rstrip("/")
    topic = config.topic.strip().strip("/")
    if not base.startswith(("http://", "https://")):
        raise ValueError("ntfy server URL must start with http:// or https://")
    if not topic:
        raise ValueError("ntfy topic is missing")
    return f"{base}/{topic}"


def _send_ntfy_request(config: NtfyConfig, title: str, message: str) -> None:
    headers = {
        "Title": str(title or "Borg Backup UI"),
        "User-Agent": "Borg-Backup-UI",
    }
    if config.priority and config.priority.lower() != "default":
        headers["Priority"] = str(config.priority)
    if config.tags:
        headers["Tags"] = str(config.tags)
    if config.click_url:
        headers["Click"] = str(config.click_url)
    if config.access_token:
        headers["Authorization"] = f"Bearer {config.access_token}"
    elif config.username:
        token = base64.b64encode(f"{config.username}:{config.password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"

    req = urlrequest.Request(
        _ntfy_endpoint(config),
        data=str(message or "").encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=config.timeout_seconds) as resp:
        if int(getattr(resp, "status", 200)) >= 400:
            raise RuntimeError(f"ntfy HTTP {resp.status}")


def build_backup_ntfy_message(
    *,
    job_name: str,
    status: str,
    timestamp: str,
    duration_seconds: int,
    repository: str,
    error_message: str = "",
) -> str:
    lines = [
        f"Job: {job_name}",
        f"Status: {status}",
        f"Time: {timestamp}",
        f"Duration: {_format_duration(duration_seconds)}",
    ]
    if repository:
        lines.append(f"Repository: {repository}")
    if error_message:
        lines.append(f"Error: {error_message}")
    return "\n".join(lines)


def build_restore_test_ntfy_message(
    *,
    job_name: str,
    status: str,
    timestamp: str,
    duration_seconds: int = 0,
    repository: str = "",
    level: int = 0,
    coverage: str = "",
    error_message: str = "",
) -> str:
    lines = [
        f"Job: {job_name}",
        f"Status: {status}",
        f"Time: {timestamp}",
    ]
    if duration_seconds > 0:
        lines.append(f"Duration: {_format_duration(duration_seconds)}")
    if repository:
        lines.append(f"Repository: {repository}")
    if level > 0:
        lines.append(f"Level: L{level}")
    if coverage:
        lines.append(f"Coverage: {coverage}")
    if error_message:
        lines.append(f"Error: {error_message}")
    return "\n".join(lines)


def _format_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
