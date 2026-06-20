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
import subprocess
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, Optional

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
    subject = f"Borg Backup Zusammenfassung ({backup_type}) - {date_tag}"

    header_lines = [
        f"Backup-Dauer: {duration_str}",
        f"Exit-Code:    {exit_code}",
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


def _format_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
