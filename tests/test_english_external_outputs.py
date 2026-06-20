from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
RUNTIME_LIB = ROOT / "runtime" / "lib"
for path in (ROOT, API_ROOT, RUNTIME_LIB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import config_api  # noqa: E402
import notifications  # noqa: E402
from report_mail_api import send_weekly_report  # noqa: E402
from smtp_api import send_test_email  # noqa: E402


class _FakeSmtp:
    messages = []

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def ehlo(self):
        return None

    def has_extn(self, _name):
        return False

    def send_message(self, message):
        self.messages.append(message)


def _smtp_config():
    return {
        "GLOBAL_SMTP_HOST": "mail.example.test",
        "GLOBAL_SMTP_PORT": "25",
        "GLOBAL_SMTP_USE_TLS": "false",
        "GLOBAL_MAIL_SENDER": "borg@example.test",
        "GLOBAL_MAIL_RECIPIENT": "admin@example.test",
    }


def test_smtp_test_email_content_is_english(monkeypatch):
    _FakeSmtp.messages = []
    monkeypatch.setattr(config_api, "read_raw_conf", lambda _cfg: _smtp_config())
    monkeypatch.setattr("smtplib.SMTP", _FakeSmtp)

    result = send_test_email({})

    assert result["success"] is True
    message = _FakeSmtp.messages[0]
    assert message["Subject"] == "Borg Backup UI - Test Email"
    assert "This is a test email from Borg Backup UI." in message.get_content()
    assert "SMTP configuration is working correctly" in message.get_content()


def test_weekly_report_email_content_is_english(monkeypatch, tmp_path):
    _FakeSmtp.messages = []
    monkeypatch.setattr(config_api, "read_raw_conf", lambda _cfg: _smtp_config())
    monkeypatch.setattr("smtplib.SMTP", _FakeSmtp)
    status_dir = tmp_path / "status"
    status_dir.mkdir()

    result = send_weekly_report({"STATUS_DIR": str(status_dir)})

    assert result["success"] is True
    message = _FakeSmtp.messages[0]
    assert str(message["Subject"]).startswith("Borg Backup - Weekly Report ")
    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "Borg Backup Weekly Report" in plain
    assert '<html lang="en">' in html
    assert "No backup data available" in html
    assert "Wochenbericht" not in html


def test_backup_failure_email_content_is_english(monkeypatch):
    captured = {}

    def fake_send_mail(config, subject, body_text, body_html=None):
        captured.update(subject=subject, body_text=body_text, body_html=body_html)
        return True

    monkeypatch.setattr(notifications, "send_mail", fake_send_mail)

    result = notifications.send_backup_log_mail(
        notifications.MailConfig(recipient="admin@example.test"),
        backup_type="appdata",
        date_tag="2026-06-20",
        exit_code=2,
        duration_seconds=65,
    )

    assert result is True
    assert captured["subject"] == "Borg Backup Summary (appdata) - 2026-06-20"
    assert "Backup duration: 00:01:05" in captured["body_text"]
    assert "Exit code:       2" in captured["body_text"]
    assert "Zusammenfassung" not in captured["subject"]
