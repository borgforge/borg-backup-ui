"""
api/smtp_api.py - SMTP-Testmail fuer die Einstellungen.
"""
from __future__ import annotations


def send_test_email(ui_config: dict, recipient: str = "") -> dict:
    """Sendet eine Test-E-Mail mit den aktuellen SMTP-Einstellungen."""
    import smtplib
    import ssl
    from email.message import EmailMessage

    from config_api import _DEFAULTS, read_raw_conf

    # raw_conf nutzen damit Sonderzeichen im Passwort nicht durch Bash-Expansion verfälscht werden
    conf = read_raw_conf(ui_config)
    defaults = _DEFAULTS
    host = (conf.get("GLOBAL_SMTP_HOST") or defaults.get("GLOBAL_SMTP_HOST", "")).strip()
    port = int((conf.get("GLOBAL_SMTP_PORT") or defaults.get("GLOBAL_SMTP_PORT", "587")).strip() or 587)
    user = (conf.get("GLOBAL_SMTP_USER") or defaults.get("GLOBAL_SMTP_USER", "")).strip()
    password = (conf.get("GLOBAL_SMTP_PASSWORD") or defaults.get("GLOBAL_SMTP_PASSWORD", "")).strip()
    use_tls = (conf.get("GLOBAL_SMTP_USE_TLS") or defaults.get("GLOBAL_SMTP_USE_TLS", "true")).strip().lower() == "true"
    sender = (conf.get("GLOBAL_MAIL_SENDER") or defaults.get("GLOBAL_MAIL_SENDER", "")).strip() or user
    to_addr = recipient.strip() or (conf.get("GLOBAL_MAIL_RECIPIENT") or defaults.get("GLOBAL_MAIL_RECIPIENT", "")).strip()

    if not host:
        return {"success": False, "message": "GLOBAL_SMTP_HOST ist nicht konfiguriert."}
    if not to_addr:
        return {"success": False, "message": "Kein Empfänger angegeben (GLOBAL_MAIL_RECIPIENT)."}
    if not sender:
        return {"success": False, "message": "Kein Absender konfiguriert (GLOBAL_MAIL_SENDER oder GLOBAL_SMTP_USER)."}

    diag = f"[Host={host}:{port}, TLS={use_tls}, User={'✓' if user else '✗ (leer)'}, Pass={'✓' if password else '✗ (leer)'}]"

    msg = EmailMessage()
    msg["Subject"] = "Borg Backup UI – Test-E-Mail"
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(
        "Das ist eine Test-E-Mail von Borg Backup UI.\n\n"
        "Die SMTP-Konfiguration ist korrekt."
    )

    def _login_if_needed(smtp_obj):
        if not user:
            return "kein SMTP-Benutzer konfiguriert – Login übersprungen"
        try:
            smtp_obj.login(user, password)
            return None
        except smtplib.SMTPNotSupportedError:
            return None

    try:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ctx) as smtp:
                smtp.ehlo()
                _login_if_needed(smtp)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                if use_tls or smtp.has_extn("starttls"):
                    smtp.starttls(context=ctx)
                    smtp.ehlo()
                _login_if_needed(smtp)
                smtp.send_message(msg)
        return {"success": True, "message": f"Test-E-Mail erfolgreich gesendet an {to_addr}."}
    except smtplib.SMTPAuthenticationError as e:
        err = e.smtp_error.decode(errors="replace") if isinstance(e.smtp_error, bytes) else str(e)
        return {"success": False, "message": f"Authentifizierungsfehler: {err} {diag}"}
    except smtplib.SMTPException as e:
        return {"success": False, "message": f"SMTP-Fehler: {e} {diag}"}
    except OSError as e:
        return {"success": False, "message": f"Verbindungsfehler: {e} {diag}"}
    except Exception as e:
        return {"success": False, "message": f"Fehler: {e} {diag}"}
