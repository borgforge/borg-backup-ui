from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
RUNTIME_ROOT = ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

import config_api
from lib.notifications import MailConfig, send_mail
from smtp_api import send_test_email


def test_send_test_email_requires_smtp_host(monkeypatch):
    monkeypatch.setattr(config_api, "read_raw_conf", lambda _cfg: {})

    result = send_test_email({})

    assert result["success"] is False
    assert "GLOBAL_SMTP_HOST" in result["message"]


def test_send_test_email_requires_recipient(monkeypatch):
    monkeypatch.setattr(config_api, "read_raw_conf", lambda _cfg: {
        "GLOBAL_SMTP_HOST": "mail.example.test",
        "GLOBAL_MAIL_SENDER": "borg@example.test",
    })

    result = send_test_email({})

    assert result["success"] is False
    assert result["message_code"] == "smtp_recipient_missing"
    assert "recipient" in result["message"]


def test_send_test_email_requires_sender(monkeypatch):
    monkeypatch.setattr(config_api, "read_raw_conf", lambda _cfg: {
        "GLOBAL_SMTP_HOST": "mail.example.test",
        "GLOBAL_MAIL_RECIPIENT": "admin@example.test",
    })

    result = send_test_email({})

    assert result["success"] is False
    assert result["message_code"] == "smtp_sender_missing"
    assert "sender" in result["message"]


def test_mail_config_uses_weekly_report_recipient_as_event_fallback():
    config = {
        "GLOBAL_MAIL_RECIPIENT": "",
        "WEEKLY_REPORT_RECIPIENT": "weekly@example.test",
        "GLOBAL_MAIL_SENDER": "borg@example.test",
        "GLOBAL_SMTP_HOST": "mail.example.test",
    }

    mail_config = MailConfig.from_config(config)

    assert mail_config.recipient == "weekly@example.test"


def test_event_mail_uses_starttls_for_port_587(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=0):
            calls.append(("smtp", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ehlo(self):
            calls.append(("ehlo",))

        def has_extn(self, name):
            calls.append(("has_extn", name))
            return True

        def starttls(self, context=None):
            calls.append(("starttls", bool(context)))

        def login(self, user, password):
            calls.append(("login", user, password))

        def send_message(self, msg):
            calls.append(("send_message", msg["To"]))

    def fail_smtp_ssl(*args, **kwargs):
        raise AssertionError("SMTP_SSL must not be used for STARTTLS port 587")

    monkeypatch.setattr("lib.notifications.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("lib.notifications.smtplib.SMTP_SSL", fail_smtp_ssl)
    monkeypatch.setattr("lib.notifications.ssl.create_default_context", lambda: object())

    ok = send_mail(
        MailConfig(
            recipient="admin@example.test",
            sender="borg@example.test",
            smtp_host="smtp.example.test",
            smtp_port=587,
            smtp_user="user",
            smtp_password="secret",
            smtp_use_tls=True,
        ),
        "Subject",
        "Body",
    )

    assert ok is True
    assert ("smtp", "smtp.example.test", 587, 30) in calls
    assert ("starttls", True) in calls
    assert ("login", "user", "secret") in calls
    assert ("send_message", "admin@example.test") in calls


def test_event_mail_uses_smtp_ssl_for_port_465(monkeypatch):
    calls = []

    class FakeSMTPSSL:
        def __init__(self, host, port, timeout=0, context=None):
            calls.append(("smtp_ssl", host, port, timeout, bool(context)))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ehlo(self):
            calls.append(("ehlo",))

        def login(self, user, password):
            calls.append(("login", user, password))

        def send_message(self, msg):
            calls.append(("send_message", msg["To"]))

    def fail_smtp(*args, **kwargs):
        raise AssertionError("SMTP must not be used for implicit SSL port 465")

    monkeypatch.setattr("lib.notifications.smtplib.SMTP", fail_smtp)
    monkeypatch.setattr("lib.notifications.smtplib.SMTP_SSL", FakeSMTPSSL)
    monkeypatch.setattr("lib.notifications.ssl.create_default_context", lambda: object())

    ok = send_mail(
        MailConfig(
            recipient="admin@example.test",
            sender="borg@example.test",
            smtp_host="smtp.example.test",
            smtp_port=465,
            smtp_user="user",
            smtp_password="secret",
            smtp_use_tls=True,
        ),
        "Subject",
        "Body",
    )

    assert ok is True
    assert ("smtp_ssl", "smtp.example.test", 465, 30, True) in calls
    assert ("login", "user", "secret") in calls
    assert ("send_message", "admin@example.test") in calls
