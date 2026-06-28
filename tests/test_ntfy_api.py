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
import ntfy_api  # noqa: E402


class _FakeHttpResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_prepare_ntfy_updates_writes_secrets(tmp_path: Path):
    password_file = tmp_path / ".ntfy-password"
    token_file = tmp_path / ".ntfy-token"

    updates = ntfy_api.prepare_ntfy_updates_for_save(
        {
            "NTFY_ENABLED": "true",
            "NTFY_PASSWORD": "secret-password",
            "NTFY_ACCESS_TOKEN": "secret-token",
        },
        {
            "NTFY_PASSWORD_FILE": str(password_file),
            "NTFY_ACCESS_TOKEN_FILE": str(token_file),
        },
    )

    assert updates["NTFY_ENABLED"] == "true"
    assert updates["NTFY_PASSWORD_FILE"] == str(password_file)
    assert updates["NTFY_ACCESS_TOKEN_FILE"] == str(token_file)
    assert "NTFY_PASSWORD" not in updates
    assert "NTFY_ACCESS_TOKEN" not in updates
    assert password_file.read_text(encoding="utf-8") == "secret-password"
    assert token_file.read_text(encoding="utf-8") == "secret-token"
    assert oct(password_file.stat().st_mode & 0o777) == "0o600"
    assert oct(token_file.stat().st_mode & 0o777) == "0o600"


def test_ntfy_test_uses_payload_without_persisting(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = req.data.decode("utf-8")
        captured["timeout"] = timeout
        return _FakeHttpResponse()

    monkeypatch.setattr(config_api, "read_expanded_conf", lambda _cfg: {})
    monkeypatch.setattr(notifications.urlrequest, "urlopen", fake_urlopen)

    result = ntfy_api.send_test_ntfy({}, {
        "server_url": "https://ntfy.example.test",
        "topic": "borg",
        "access_token": "test-token",
        "priority": "high",
        "tags": "white_check_mark",
    })

    assert result["success"] is True
    assert captured["url"] == "https://ntfy.example.test/borg"
    assert captured["body"] == "This is a test notification from Borg Backup UI."
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["headers"]["Priority"] == "high"
    assert captured["headers"]["Tags"] == "white_check_mark"


def test_send_ntfy_respects_event_selection(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        return _FakeHttpResponse()

    monkeypatch.setattr(notifications.urlrequest, "urlopen", fake_urlopen)
    cfg = notifications.NtfyConfig(
        enabled=True,
        server_url="https://ntfy.example.test",
        topic="borg",
        events={"backup_failed"},
    )

    assert notifications.send_ntfy(cfg, "backup_success", "Title", "Body") is False
    assert calls == []
    assert notifications.send_ntfy(cfg, "backup_failed", "Title", "Body") is True
    assert calls == ["https://ntfy.example.test/borg"]


def test_build_backup_ntfy_message_is_english():
    msg = notifications.build_backup_ntfy_message(
        job_name="appdata_daily",
        status="Error",
        timestamp="2026-06-28 10:00:00",
        duration_seconds=65,
        repository="usb_backup_01",
        error_message="Repository could not be opened",
    )

    assert "Job: appdata_daily" in msg
    assert "Status: Error" in msg
    assert "Duration: 00:01:05" in msg
    assert "Repository: usb_backup_01" in msg
    assert "Error: Repository could not be opened" in msg
