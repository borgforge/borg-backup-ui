#!/usr/bin/env python3
"""Offline contract checks for the exact vendor tree about to be packaged (#269).

Run with python3 -S so host site-packages cannot supply missing dependencies.
All transport calls are mocked; no notification leaves the build machine.
"""

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
import pkgutil
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def check(vendor: Path) -> None:
    if not sys.flags.no_site:
        raise RuntimeError("Run this check with python3 -S to isolate the vendor runtime")
    sys.path.insert(0, str(ROOT / "runtime" / "lib"))
    import apprise_adapter as adapter

    module = adapter.load_bundled_apprise(vendor_dir=vendor)
    assert Path(module.__file__).resolve().is_relative_to(vendor)
    expected = json.loads((ROOT / "plugin" / "apprise-providers.json").read_text())
    actual = adapter.supported_providers(vendor_dir=vendor)
    assert actual["version"] == expected["version"] == "1.13.1"
    assert actual["provider_count"] == expected["provider_count"] == 141
    inventory = {row["service_name"]: sorted(row["schemas"]) for row in actual["providers"]}
    assert inventory == {row["service_name"]: row["schemas"] for row in expected["providers"]}
    for row in actual["providers"]:
        assert row["schemas"] and row["templates"] and row["tokens"], row["service_name"]

    # Provider entry points handle their own optional-dependency checks. Do not
    # import private helpers of providers outside the agreed base package scope.
    for entry in pkgutil.iter_modules(module.plugins.__path__, "apprise.plugins."):
        importlib.import_module(entry.name)

    # The base dependency set must resolve from the vendor directory as well.
    for name in ("requests", "requests_oauthlib", "oauthlib", "yaml", "certifi",
                 "charset_normalizer", "idna", "urllib3", "click", "markdown"):
        dependency = importlib.import_module(name)
        assert Path(dependency.__file__).resolve().is_relative_to(vendor), name

    response = SimpleNamespace(status_code=200, content=b"{}", text="{}", headers={}, json=lambda: {})
    requests = importlib.import_module("requests")
    urls = ("ntfy://example.test/bbui", "json://example.test/notify")
    # Block accidental transport additions which the mocks below do not cover.
    with patch("socket.socket.connect", side_effect=AssertionError("Unexpected network access")):
        for url in urls:
            assert adapter.validate_url(url, vendor_dir=vendor).ok
            with patch.object(requests.sessions.Session, "request", return_value=response) as transport:
                result = adapter.send_notification(url, title="BBUI test", body="Offline body", vendor_dir=vendor)
                assert result.ok and transport.call_count == 1
                payload = str(transport.call_args)
                assert "BBUI test" in payload and "Offline body" in payload

        with patch("smtplib.SMTP_SSL") as smtp:
            result = adapter.send_notification(
                "mailtos://sender:fake-password@example.test/?to=recipient@example.test&mode=ssl",
                title="BBUI test", body="Offline body", vendor_dir=vendor,
            )
            assert result.ok and smtp.return_value.sendmail.call_count == 1

        with patch.object(requests.sessions.Session, "request", return_value=SimpleNamespace(
            status_code=500, content=b"{}", text="{}", headers={}, json=lambda: {},
        )):
            assert not adapter.send_notification(urls[1], title="Title", body="Body", vendor_dir=vendor).ok

        for url in ("json://[invalid", "json://user@[invalid]:8080/path"):
            assert not adapter.validate_url(url, vendor_dir=vendor).ok
        for scheme in ("napi", "notificationapi"):
            result = adapter.send_notification(
                f"{scheme}://fake-id:fake-secret@example.test", title="Title", body="Body", vendor_dir=vendor,
            )
            assert not result.ok and result.message_code == adapter.RETIRED_NOTIFICATIONAPI_CODE
            assert "fake-secret" not in result.message

        def slow_request(*args, **kwargs):
            time.sleep(2)
            return response

        # Apprise uses a worker for asynchronous delivery; explicitly use its
        # synchronous mode here to exercise the adapter's main-thread deadline.
        url = urls[1] + "?async=no"
        with patch.object(requests.sessions.Session, "request", side_effect=slow_request):
            start = time.monotonic()
            assert not adapter.send_notification(
                url, title="Title", body="Body", timeout_seconds=0.05, vendor_dir=vendor,
            ).ok
            assert time.monotonic() - start < 1

    print(f"Apprise {actual['version']}: {actual['provider_count']} providers; vendor imports, metadata, "
          "HTTP/SMTP delivery, rejection and timeout checks passed (offline).")


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    check(Path(sys.argv[1]).resolve())
