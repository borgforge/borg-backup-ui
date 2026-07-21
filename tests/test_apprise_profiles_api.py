from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
RUNTIME_LIB = ROOT / "runtime" / "lib"
for path in (ROOT, API_ROOT, RUNTIME_LIB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import apprise_profiles_api  # noqa: E402
from inventory_store import InventoryCorruptError  # noqa: E402


def _cfg(tmp_path: Path) -> dict:
    return {"BACKUP_SCRIPTS_DIR": str(tmp_path)}


def _ok_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        apprise_profiles_api,
        "validate_url",
        lambda url: type("Result", (), {"ok": bool(url), "message": "ok" if url else "empty"})(),
    )


def test_create_profile_writes_secret_and_returns_masked_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ok_validation(monkeypatch)
    config = _cfg(tmp_path)

    result = apprise_profiles_api.create_profile(config, {
        "id": "alerts-main",
        "name": "Alerts",
        "provider": "ntfy",
        "enabled": True,
        "selected_events": ["backup_failed", "restore_test_failed"],
        "timeout_seconds": 20,
        "retry_policy": {"attempts": 2, "backoff_seconds": 30},
        "priority": "high",
        "default": True,
        "url_template": "ntfy://{token}@{host}/{targets}",
        "url_fields": {"host": "example.test", "targets": "borg"},
        "apprise_url": "ntfy://token@example.test/borg",
    })

    profile = result["profile"]
    assert result["created"] is True
    assert profile["id"] == "alerts-main"
    assert profile["url_set"] is True
    assert "apprise_url" not in profile
    assert "ntfy://token" not in json.dumps(profile)
    assert profile["url_template"] == "ntfy://{token}@{host}/{targets}"
    assert profile["url_fields"] == {"host": "example.test", "targets": "borg"}

    secret = tmp_path / "secrets" / ".apprise-profile-alerts-main.url"
    assert secret.read_text(encoding="utf-8").strip() == "ntfy://token@example.test/borg"
    assert oct(secret.stat().st_mode & 0o777) == "0o600"

    store_text = (tmp_path / "config" / "apprise-profiles.json").read_text(encoding="utf-8")
    assert "ntfy://token" not in store_text
    assert json.loads(store_text)["profiles"][0]["provider"] == "ntfy"
    assert json.loads(store_text)["profiles"][0]["url_template"] == "ntfy://{token}@{host}/{targets}"
    assert json.loads(store_text)["profiles"][0]["url_fields"] == {"host": "example.test", "targets": "borg"}


def test_update_profile_preserves_write_only_secret_when_url_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ok_validation(monkeypatch)
    config = _cfg(tmp_path)
    apprise_profiles_api.create_profile(config, {
        "id": "alerts-main",
        "name": "Alerts",
        "apprise_url": "json://old-token@example.test",
    })

    updated = apprise_profiles_api.update_profile(config, "alerts-main", {
        "name": "New Alerts",
        "enabled": False,
        "url_template": "json://{token}@{host}",
        "url_fields": {"host": "example.test", "targets": "borg"},
    })

    assert updated["profile"]["name"] == "New Alerts"
    assert updated["profile"]["enabled"] is False
    assert updated["profile"]["url_set"] is True
    assert updated["profile"]["url_template"] == "json://{token}@{host}"
    assert updated["profile"]["url_fields"] == {"host": "example.test", "targets": "borg"}
    secret = tmp_path / "secrets" / ".apprise-profile-alerts-main.url"
    assert secret.read_text(encoding="utf-8").strip() == "json://old-token@example.test"


def test_profile_url_fields_are_sanitized_without_exposing_secret_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ok_validation(monkeypatch)
    config = _cfg(tmp_path)

    result = apprise_profiles_api.create_profile(config, {
        "id": "alerts-main",
        "name": "Alerts",
        "provider": "ntfy",
        "url_template": "ntfy://{token}@{host}/{targets}",
        "url_fields": {
            "host": "ntfy.example.test",
            "targets": "borg",
            "token": "",
        },
        "apprise_url": "ntfy://secret-token@ntfy.example.test/borg",
    })

    profile = result["profile"]
    assert profile["url_template"] == "ntfy://{token}@{host}/{targets}"
    assert profile["url_fields"] == {"host": "ntfy.example.test", "targets": "borg"}
    assert "secret-token" not in json.dumps(profile)
    store_text = (tmp_path / "config" / "apprise-profiles.json").read_text(encoding="utf-8")
    assert "secret-token" not in store_text


def test_delete_referenced_profile_returns_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ok_validation(monkeypatch)
    config = _cfg(tmp_path)
    apprise_profiles_api.create_profile(config, {
        "id": "alerts-main",
        "name": "Alerts",
        "apprise_url": "json://token@example.test",
    })
    monkeypatch.setattr(apprise_profiles_api, "active_profile_references", lambda _config: {"alerts-main"})

    with pytest.raises(apprise_profiles_api.AppriseProfileConflict):
        apprise_profiles_api.delete_profile(config, "alerts-main")

    assert apprise_profiles_api.get_profile(config, "alerts-main")["profile"]["url_set"] is True


def test_delete_profile_removes_secret_when_unreferenced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ok_validation(monkeypatch)
    config = _cfg(tmp_path)
    apprise_profiles_api.create_profile(config, {
        "id": "alerts-main",
        "name": "Alerts",
        "apprise_url": "json://token@example.test",
    })

    result = apprise_profiles_api.delete_profile(config, "alerts-main")

    assert result == {"deleted": True, "profile_id": "alerts-main", "secret_deleted": True}
    assert not (tmp_path / "secrets" / ".apprise-profile-alerts-main.url").exists()
    assert apprise_profiles_api.list_profiles(config)["profiles"] == []


def test_corrupt_profile_store_fails_closed(tmp_path: Path) -> None:
    config = _cfg(tmp_path)
    path = tmp_path / "config" / "apprise-profiles.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(InventoryCorruptError, match="malformed JSON"):
        apprise_profiles_api.list_profiles(config)


def test_concurrent_creates_do_not_lose_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ok_validation(monkeypatch)
    config = _cfg(tmp_path)

    def create_one(idx: int) -> None:
        apprise_profiles_api.create_profile(config, {
            "id": f"alerts-{idx}",
            "name": f"Alerts {idx}",
            "apprise_url": f"json://token-{idx}@example.test",
        })

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(create_one, range(12)))

    profiles = apprise_profiles_api.list_profiles(config)["profiles"]
    assert {row["id"] for row in profiles} == {f"alerts-{idx}" for idx in range(12)}


def test_validate_and_test_profile_do_not_return_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ok_validation(monkeypatch)
    config = _cfg(tmp_path)
    apprise_profiles_api.create_profile(config, {
        "id": "alerts-main",
        "name": "Alerts",
        "apprise_url": "json://token@example.test",
    })
    captured = {}

    def fake_send(url: str, *, title: str, body: str):
        captured["url"] = url
        captured["title"] = title
        captured["body"] = body
        return type("Result", (), {"ok": True, "message": "sent"})()

    monkeypatch.setattr(apprise_profiles_api, "send_test_notification", fake_send)

    validation = apprise_profiles_api.validate_profile_payload(config, {"apprise_url": "json://token@example.test"})
    tested = apprise_profiles_api.test_profile(config, {"profile_id": "alerts-main"})

    assert validation["success"] is True
    assert validation["url_set"] is True
    assert tested["success"] is True
    assert captured["url"] == "json://token@example.test"
    assert "json://token" not in json.dumps(validation)
    assert "json://token" not in json.dumps(tested)


def test_apprise_profile_http_routes_are_wired() -> None:
    source = (ROOT / "borg_backup_ui.py").read_text(encoding="utf-8")

    for route in (
        '"/api/notification-profiles"',
        '"/api/notification-profiles/providers"',
        '"/api/notification-profiles/validate"',
        '"/api/notification-profiles/test"',
    ):
        assert route in source
    assert "p.startswith(\"/api/notification-profiles\")" in source
