from __future__ import annotations

import logging
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LIB = ROOT / "runtime" / "lib"
if str(RUNTIME_LIB) not in sys.path:
    sys.path.insert(0, str(RUNTIME_LIB))

import apprise_adapter  # noqa: E402


class _FakeResult:
    def __init__(self, ok=True):
        self.ok = ok
        self.closed = False

    def __bool__(self):
        return self.ok

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True


class _FakeApprise:
    instances = []

    def __init__(self, *, asset=None):
        self.urls = []
        self.asset = asset
        _FakeApprise.instances.append(self)

    def add(self, url: str) -> bool:
        self.urls.append(url)
        return not str(url).startswith("broken://")

    def notify(self, *, title: str, body: str, **kwargs):
        self.title = title
        self.body = body
        self.notify_options = kwargs
        self.result = _FakeResult()
        return self.result

    def details(self) -> dict:
        return {
            "version": "1.2.3-test",
            "schemas": [
                {
                    "service_name": "Example",
                    "service_url": "https://example.test",
                    "setup_url": "https://setup.example.test",
                    "details": {
                        "templates": [
                            "{schema}://{token}@{host}",
                        ],
                        "tokens": {
                            "host": {
                                "name": "Hostname",
                                "type": "string",
                                "required": True,
                                "map_to": "host",
                            },
                            "token": {
                                "name": "Token",
                                "type": "string",
                                "private": True,
                                "map_to": "password",
                            },
                            "target_channel": {
                                "name": "Target Channel",
                                "type": "string",
                                "prefix": "#",
                                "map_to": "targets",
                            },
                            "schema": {"values": ["example", "examples"]},
                        },
                    },
                }
            ],
        }


def _fake_module():
    _FakeApprise.instances = []
    return SimpleNamespace(Apprise=_FakeApprise, AppriseAsset=SimpleNamespace, __version__="1.2.3-test")


def test_supported_providers_uses_apprise_details() -> None:
    providers = apprise_adapter.supported_providers(apprise_module=_fake_module())

    assert providers["version"] == "1.2.3-test"
    assert providers["provider_count"] == 1
    assert providers["providers"] == [{
        "service_name": "Example",
        "service_url": "https://example.test",
        "setup_url": "https://setup.example.test",
        "schemas": ["example", "examples"],
        "templates": ["{schema}://{token}@{host}"],
        "tokens": [
            {
                "key": "host",
                "name": "Hostname",
                "type": "string",
                "required": True,
                "private": False,
                "map_to": "host",
            },
            {
                "key": "target_channel",
                "name": "Target Channel",
                "type": "string",
                "required": False,
                "private": False,
                "map_to": "targets",
                "prefix": "#",
            },
            {
                "key": "token",
                "name": "Token",
                "type": "string",
                "required": False,
                "private": True,
                "map_to": "password",
            },
        ],
    }]


def test_supported_providers_times_out_blocking_discovery() -> None:
    class BlockingApprise:
        def details(self) -> dict:
            time.sleep(5)
            return {}

    module = SimpleNamespace(Apprise=BlockingApprise, __version__="1.2.3-test")

    with pytest.raises(apprise_adapter.AppriseAdapterError, match="exceeded"):
        apprise_adapter.supported_providers(
            apprise_module=module,
            timeout_seconds=0.01,
        )


def test_validate_and_send_test_notification_with_test_double() -> None:
    module = _fake_module()

    validation = apprise_adapter.validate_url("example://token", apprise_module=module)
    sent = apprise_adapter.send_test_notification(
        "example://token",
        title="Title",
        body="Body",
        apprise_module=module,
    )

    assert validation.ok is True
    assert sent.ok is True
    assert _FakeApprise.instances[-1].urls == ["example://token"]
    assert _FakeApprise.instances[-1].title == "Title"
    assert _FakeApprise.instances[-1].body == "Body"
    assert _FakeApprise.instances[-1].result.closed


def test_send_notification_suppresses_provider_info_logs(caplog) -> None:
    class LoggingApprise(_FakeApprise):
        def notify(self, *, title: str, body: str, **kwargs):
            logging.getLogger("apprise.plugins.ntfy").info("Sent ntfy notification to 'https://ntfy.sh'.")
            return super().notify(title=title, body=body, **kwargs)

    module = SimpleNamespace(Apprise=LoggingApprise, AppriseAsset=SimpleNamespace, __version__="1.2.3-test")

    with caplog.at_level(logging.INFO):
        result = apprise_adapter.send_notification(
            "example://token",
            title="Title",
            body="Body",
            apprise_module=module,
        )

    assert result.ok is True
    assert "Sent ntfy notification" not in caplog.text


def test_rejected_url_does_not_send() -> None:
    result = apprise_adapter.send_test_notification(
        "broken://token",
        apprise_module=_fake_module(),
    )

    assert result.ok is False
    assert "rejected" in result.message


def test_missing_vendor_directory_reports_clear_error(tmp_path: Path) -> None:
    missing = tmp_path / "runtime" / "vendor"

    with pytest.raises(apprise_adapter.AppriseAdapterError, match="Bundled Apprise runtime is missing"):
        apprise_adapter.load_bundled_apprise(vendor_dir=missing)


def test_failed_bundled_import_restores_existing_module(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    package = vendor / "apprise"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    existing = ModuleType("apprise")
    previous = sys.modules.get("apprise")
    sys.modules["apprise"] = existing
    try:
        with pytest.raises(apprise_adapter.AppriseAdapterError, match="failed to load"):
            apprise_adapter.load_bundled_apprise(vendor_dir=vendor)

        assert sys.modules["apprise"] is existing
    finally:
        if previous is not None:
            sys.modules["apprise"] = previous
        else:
            sys.modules.pop("apprise", None)


def test_provider_validation_errors_and_logs_do_not_expose_secrets(caplog):
    secret = "fake-secret-and-recipient"

    class FailingApprise(_FakeApprise):
        def add(self, url):
            logging.getLogger("apprise").warning("Rejected %s", url)
            raise ValueError(url)

    with caplog.at_level(logging.DEBUG):
        result = apprise_adapter.validate_url(
            f"json://{secret}@example.test", apprise_module=SimpleNamespace(Apprise=FailingApprise),
        )
    assert not result.ok and "ValueError" in result.message
    assert secret not in result.message + caplog.text


def test_provider_delivery_exception_does_not_expose_message_or_secret(caplog):
    class FailingApprise(_FakeApprise):
        def notify(self, **kwargs):
            logging.getLogger("apprise").error("fake-secret %s", kwargs["body"])
            raise RuntimeError("fake-secret " + kwargs["body"])

    with caplog.at_level(logging.DEBUG):
        result = apprise_adapter.send_notification(
            "json://fake-secret@example.test", title="Title", body="private body",
            apprise_module=SimpleNamespace(Apprise=FailingApprise, AppriseAsset=SimpleNamespace),
        )
    assert not result.ok and "RuntimeError" in result.message
    assert "fake-secret" not in result.message + caplog.text
    assert "private body" not in result.message + caplog.text


@pytest.mark.parametrize("timeout", [None, 0, 0.05, 120])
def test_delivery_passes_profile_budget_to_call_and_service(timeout):
    result = apprise_adapter.send_notification(
        "example://token", title="Title", body="Body", timeout_seconds=timeout,
        apprise_module=_fake_module(),
    )
    assert result.ok
    app = _FakeApprise.instances[-1]
    assert app.asset.service_timeout == app.notify_options["timeout"] == (timeout or 0)
    assert app.notify_options["log_level"] > logging.CRITICAL


def test_unsuccessful_result_is_closed_and_reported_as_failure():
    failed = _FakeResult(False)

    class FailedApprise(_FakeApprise):
        def notify(self, **kwargs):
            return failed

    result = apprise_adapter.send_notification(
        "example://token", title="Title", body="Body",
        apprise_module=SimpleNamespace(Apprise=FailedApprise, AppriseAsset=SimpleNamespace),
    )
    assert not result.ok and failed.closed


def test_provider_logs_stay_private_after_delivery_returns(caplog):
    apprise_adapter.send_notification(
        "example://token", title="Title", body="Body", apprise_module=_fake_module(),
    )
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("apprise").error("late fake-secret")
        logging.getLogger("apprise.plugins.ntfy").error("late private body")
        logging.getLogger("borg_backup_ui").warning("Application diagnostic")
    assert "fake-secret" not in caplog.text and "private body" not in caplog.text
    assert "Application diagnostic" in caplog.text
