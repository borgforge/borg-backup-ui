#!/usr/bin/env python3
"""Offline contract checks for the exact vendor tree to be packaged (#269/#672).

Run with python3 -S so host site-packages cannot supply missing dependencies.
All transport calls are mocked; no notification leaves the build machine.
"""

from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
import logging
from pathlib import Path
import pkgutil
import sys
import ssl
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def check_ntfy(adapter, requests, vendor: Path, response) -> None:
    """Exercise token/basic auth, payloads, TLS options and sanitized failures.

    The caller must block sockets. Only synthetic credentials are used and all
    requests are mocked; assertions fail before a candidate can be published.
    """
    token = "tk_synthetic_offline_token"
    secret_url = f"ntfys://{token}@ntfy.sh/Borg-Backup-UI"
    for scheme, protocol in (("ntfy", "http"), ("ntfys", "https")):
        url = secret_url.replace("ntfys://", scheme + "://", 1)
        assert adapter.validate_url(url, vendor_dir=vendor).ok
        with patch.object(requests.sessions.Session, "request", return_value=response) as transport:
            result = adapter.send_notification(
                url, title="Backup OK", body="Offline body: ä\nsecond line", vendor_dir=vendor,
            )
        assert result.ok and transport.call_count == 1
        sent = transport.call_args.kwargs
        assert sent["url"] == f"{protocol}://ntfy.sh"
        assert sent["headers"]["Authorization"] == f"Bearer {token}"
        assert sent["verify"] is True
        assert json.loads(sent["data"]) == {
            "topic": "Borg-Backup-UI", "title": "Backup OK", "message": "Offline body: ä\nsecond line",
        }
    with patch.object(requests.sessions.Session, "request", return_value=response) as transport:
        assert adapter.send_notification(
            "ntfys://user:fake-password@example.test/topic", title="Title", body="Body", vendor_dir=vendor,
        ).ok
        assert transport.call_args.kwargs["auth"] == ("user", "fake-password")

    for status in (401, 403, 429, 500):
        rejected = SimpleNamespace(status_code=status, content=b"{}", text="{}", headers={}, json=lambda: {})
        with patch.object(requests.sessions.Session, "request", return_value=rejected):
            result = adapter.send_notification(secret_url, title="Title", body="private body", vendor_dir=vendor)
        assert not result.ok and token not in result.message and "private body" not in result.message
    for error in (requests.exceptions.SSLError, requests.exceptions.Timeout):
        with patch.object(requests.sessions.Session, "request", side_effect=error(token + " private body")):
            result = adapter.send_notification(secret_url, title="Title", body="private body", vendor_dir=vendor)
        assert not result.ok and token not in result.message and "private body" not in result.message


def check_deadlines(adapter, requests, vendor: Path, response) -> None:
    """Check native deadlines on main/worker threads and drain late mock I/O.

    Even synchronous providers can finish after Apprise returns TIMEOUT. Keep
    transport mocks installed until these workers finish, and check that their
    late errors cannot expose secrets through application logging.
    """
    dispatch = importlib.import_module("apprise.apprise")
    capture = io.StringIO()
    handler = logging.StreamHandler(capture)
    logging.getLogger().addHandler(handler)
    try:
        for in_worker, suffix in ((False, "?async=no"), (True, "")):
            release = threading.Event()
            entered = threading.Event()

            def slow_request(*args, **kwargs):
                entered.set()
                release.wait(2)
                logging.getLogger("apprise").error("late fake-secret private body")
                return response

            with patch.object(requests.sessions.Session, "request", side_effect=slow_request):
                try:
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        def call():
                            return adapter.send_notification(
                                "ntfys://example.test/topic" + suffix, title="Title", body="Body",
                                timeout_seconds=0.1, vendor_dir=vendor,
                            )
                        start = time.monotonic()
                        result = pool.submit(call).result(timeout=3) if in_worker else call()
                        assert entered.is_set() and not result.ok
                        assert time.monotonic() - start < 1
                finally:
                    release.set()
                    until = time.monotonic() + 3
                    while dispatch.any_abandoned_calls_still_running() and time.monotonic() < until:
                        time.sleep(0.01)
                    assert not dispatch.any_abandoned_calls_still_running()
        assert "fake-secret" not in capture.getvalue() and "private body" not in capture.getvalue()
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()


def check_oauth_and_tls(requests, vendor: Path) -> None:
    """Check locked OAuth client integration and CA loading without network I/O."""
    from requests_oauthlib import OAuth1, OAuth2Session
    import certifi

    prepared = requests.Request(
        "POST", "https://example.test/notify", data={"message": "offline"},
        auth=OAuth1("fake-id", client_secret="fake-secret", resource_owner_key="fake-token",
                    resource_owner_secret="fake-owner-secret", nonce="test", timestamp="1"),
    ).prepare()
    assert b"oauth_signature=" in prepared.headers["Authorization"]
    client = OAuth2Session("fake-id", token={"access_token": "fake-token", "token_type": "Bearer"})
    with patch.object(requests.sessions.Session, "send", return_value=requests.Response()) as transport:
        client.get("https://example.test/notify")
        assert transport.call_args.args[0].headers["Authorization"] == "Bearer fake-token"
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"access_token":"fake-new-token","token_type":"Bearer","expires_in":3600}'
    with patch.object(requests.sessions.Session, "send", return_value=response):
        token = client.refresh_token("https://example.test/token", refresh_token="fake-refresh")
        assert token["access_token"] == "fake-new-token"

    ca_file = Path(certifi.where()).resolve()
    assert ca_file.is_relative_to(vendor)
    assert requests.utils.DEFAULT_CA_BUNDLE_PATH == str(ca_file)
    context = ssl.create_default_context(cafile=str(ca_file))
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert context.cert_store_stats()["x509_ca"] > 0


def check(vendor: Path) -> None:
    """Reject incomplete/incompatible vendor trees before package publication."""
    if not sys.flags.no_site:
        raise RuntimeError("Run this check with python3 -S to isolate the vendor runtime")
    sys.path.insert(0, str(ROOT / "runtime" / "lib"))
    import apprise_adapter as adapter

    module = adapter.load_bundled_apprise(vendor_dir=vendor)
    assert Path(module.__file__).resolve().is_relative_to(vendor)
    expected = json.loads((ROOT / "plugin" / "apprise-providers.json").read_text())
    actual = adapter.supported_providers(vendor_dir=vendor)
    assert actual["version"] == expected["version"] == "2.1.0"
    assert actual["provider_count"] == expected["provider_count"] == 158
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
        check_ntfy(adapter, requests, vendor, response)
        check_oauth_and_tls(requests, vendor)
        for url in urls:
            assert adapter.validate_url(url, vendor_dir=vendor).ok
            with patch.object(requests.sessions.Session, "request", return_value=response) as transport:
                result = adapter.send_notification(url, title="BBUI test", body="Offline body", vendor_dir=vendor)
                assert result.ok and transport.call_count == 1
                payload = str(transport.call_args)
                assert "BBUI test" in payload and "Offline body" in payload

        with patch("smtplib.SMTP_SSL") as smtp:
            smtp.return_value.sendmail.return_value = {}
            result = adapter.send_notification(
                "mailtos://sender:fake-password@example.test/?to=recipient@example.test&mode=ssl",
                title="BBUI test", body="Offline body", vendor_dir=vendor,
            )
            assert result.ok and smtp.return_value.sendmail.call_count == 1
            smtp.return_value.sendmail.return_value = {"recipient@example.test": (550, b"Rejected")}
            assert not adapter.send_notification(
                "mailtos://sender:fake-password@example.test/?to=recipient@example.test&mode=ssl",
                title="Title", body="Body", vendor_dir=vendor,
            ).ok

        with patch.object(requests.sessions.Session, "request", return_value=SimpleNamespace(
            status_code=500, content=b"{}", text="{}", headers={}, json=lambda: {},
        )):
            assert not adapter.send_notification(urls[1], title="Title", body="Body", vendor_dir=vendor).ok

        for url in ("json://[invalid", "json://user@[invalid]:8080/path"):
            assert not adapter.validate_url(url, vendor_dir=vendor).ok
        for scheme, code in (("napi", adapter.RETIRED_NOTIFICATIONAPI_CODE),
                             ("notificationapi", adapter.RETIRED_NOTIFICATIONAPI_CODE),
                             ("chime", adapter.RETIRED_CHIME_CODE)):
            result = adapter.send_notification(
                f"{scheme}://fake-id:fake-secret@example.test", title="Title", body="Body", vendor_dir=vendor,
            )
            assert not result.ok and result.message_code == code
            assert "fake-secret" not in result.message

        from apprise.result import AppriseResult, AppriseResultStatus
        for status in AppriseResultStatus:
            outcome = AppriseResult(status=status)
            with patch.object(module.Apprise, "notify", return_value=outcome), \
                    patch.object(outcome, "close", wraps=outcome.close) as close:
                result = adapter.send_notification(urls[0], title="Title", body="Body", vendor_dir=vendor)
            assert result.ok == (status == AppriseResultStatus.SUCCESS)
            close.assert_called_once()

        for budget in (-1, float("inf"), float("nan"), True):
            assert not adapter.send_notification(
                urls[0], title="Title", body="Body", timeout_seconds=budget, vendor_dir=vendor,
            ).ok
        check_deadlines(adapter, requests, vendor, response)

    print(f"Apprise {actual['version']}: {actual['provider_count']} providers; vendor imports, metadata, "
          "ntfy token/basic auth, HTTP/SMTP delivery/rejection, OAuth/TLS, result cleanup "
          "and main/worker deadlines passed (offline).")


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    check(Path(sys.argv[1]).resolve())
