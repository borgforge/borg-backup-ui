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

import logging
import smtplib
import ssl
import subprocess
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlsplit

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

        If GLOBAL_MAIL_RECIPIENT is empty, WEEKLY_REPORT_RECIPIENT is used as
        a fallback. This keeps event e-mails working for installations that
        already configured a weekly-report recipient but left the global
        recipient empty.

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

        recipient = (
            str(config.get("GLOBAL_MAIL_RECIPIENT", "") or "").strip()
            or str(config.get("WEEKLY_REPORT_RECIPIENT", "") or "").strip()
        )

        return cls(
            recipient=recipient,
            sender=config.get("GLOBAL_MAIL_SENDER", ""),
            smtp_host=config.get("GLOBAL_SMTP_HOST", "localhost"),
            smtp_port=port,
            smtp_user=config.get("GLOBAL_SMTP_USER", ""),
            smtp_password=config.get("GLOBAL_SMTP_PASSWORD", ""),
            smtp_use_tls=use_tls,
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
    context = ssl.create_default_context()
    if int(config.smtp_port) == 465:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30, context=context) as smtp:
            smtp.ehlo()
            _login_if_needed(smtp, config)
            smtp.send_message(msg)
        return

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        if config.smtp_use_tls or smtp.has_extn("starttls"):
            smtp.starttls(context=context)
            smtp.ehlo()
        _login_if_needed(smtp, config)
        smtp.send_message(msg)


def _login_if_needed(smtp_obj, config: MailConfig) -> None:
    if not config.smtp_user:
        return
    try:
        smtp_obj.login(config.smtp_user, config.smtp_password)
    except smtplib.SMTPNotSupportedError:
        return


def build_backup_notification_message(
    *,
    job_name: str,
    status: str,
    timestamp: str,
    duration_seconds: int,
    repository: str,
    backup_location: str = "",
    archive_name: str = "",
    error_message: str = "",
) -> str:
    target = _format_backup_target(repository, backup_location)
    if str(status or "").strip().lower() == "successful":
        lines = [
            f"Job: {job_name}",
            "Result: Successful",
            f"Duration: {_format_duration_short(duration_seconds)}",
            f"Finished: {_format_notification_timestamp(timestamp)}",
        ]
        if target:
            lines.append(f"Target: {target}")
        if archive_name and archive_name != "unknown":
            lines.append(f"Archive: {archive_name}")
        return "\n".join(lines)

    lines = [
        f"Job: {job_name}",
        f"Result: {status}",
        f"Finished: {_format_notification_timestamp(timestamp)}",
        f"Duration: {_format_duration(duration_seconds)}",
    ]
    if target:
        lines.append(f"Target: {target}")
    if repository:
        lines.append(f"Repository: {repository}")
    if error_message:
        lines.append(f"Error: {error_message}")
        lines.append("Action: Review the backup log and storage connection.")
    return "\n".join(lines)


def build_restore_test_notification_message(
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


def _format_duration_short(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    parts: list[str] = []
    if h:
        parts.append(f"{h} h")
    if m:
        parts.append(f"{m} min")
    if s or not parts:
        parts.append(f"{s} sec")
    return " ".join(parts)


def _format_notification_timestamp(timestamp: str) -> str:
    text = str(timestamp or "").strip()
    if len(text) >= 16 and text[4:5] == "-" and text[13:14] == ":":
        return text[:16]
    return text


def _format_backup_target(repository: str, backup_location: str = "") -> str:
    repo_name = _repository_display_name(repository)
    location = _location_display_name(backup_location)
    if location and repo_name:
        return f"{location} / {repo_name}"
    return repo_name or location


def _repository_display_name(repository: str) -> str:
    text = str(repository or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
        path = parsed.path if parsed.scheme else text
    except ValueError:
        path = text
    if "::" in path:
        path = path.split("::", 1)[0]
    clean = path.rstrip("/").split("/")[-1].strip()
    return clean or text


def _location_display_name(location: str) -> str:
    normalized = str(location or "").strip().lower()
    return {
        "local": "Local",
        "lokal": "Local",
        "usb": "USB",
        "smb": "SMB",
        "ssh": "SSH",
        "storagebox": "Storagebox",
    }.get(normalized, str(location or "").strip())
