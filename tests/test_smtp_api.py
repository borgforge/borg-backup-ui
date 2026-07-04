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
from lib.notifications import MailConfig
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
