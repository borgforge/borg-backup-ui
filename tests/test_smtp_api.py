from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import config_api
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
    assert "Empfänger" in result["message"]


def test_send_test_email_requires_sender(monkeypatch):
    monkeypatch.setattr(config_api, "read_raw_conf", lambda _cfg: {
        "GLOBAL_SMTP_HOST": "mail.example.test",
        "GLOBAL_MAIL_RECIPIENT": "admin@example.test",
    })

    result = send_test_email({})

    assert result["success"] is False
    assert "Absender" in result["message"]
