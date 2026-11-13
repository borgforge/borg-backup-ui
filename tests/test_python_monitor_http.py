"""Exercise transient NVD recovery, bounded waits and safe failure diagnostics (#720)."""
import io
import http.client
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
import python_monitor as monitor

URL = monitor.NVD + '?virtualMatchString=cpe:2.3:a:sqlite:sqlite:3.54.1:*:*:*:*:*:*:*&startIndex=0'
SECRET = 'do-not-log-token-or-upstream-response'


@pytest.fixture
def transport(monkeypatch):
    """Simulate socket reads and a monotonic clock without network or real sleeps."""
    state = SimpleNamespace(now=0, outcomes=[], calls=[], waits=[])

    def open_request(request, timeout):
        state.calls.append((request, timeout))
        result = state.outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return io.BytesIO(result)

    def sleep(seconds):
        state.waits.append(seconds)
        state.now += seconds

    monkeypatch.setattr(monitor.urllib.request, 'build_opener', lambda *args: SimpleNamespace(open=open_request))
    monkeypatch.setattr(monitor.time, 'monotonic', lambda: state.now)
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    return state


def http_error(code, retry_after=None):
    """Build a hostile error response; only status and valid retry hints may be used."""
    headers = {} if retry_after is None else {'Retry-After': retry_after}
    return urllib.error.HTTPError(URL, code, SECRET, headers, io.BytesIO(SECRET.encode()))


@pytest.mark.parametrize('failure', [TimeoutError(SECRET), urllib.error.URLError(TimeoutError(SECRET)),
                                   ConnectionResetError(SECRET)])
def test_transient_failure_recovers_without_leaking_details(transport, capsys, failure):
    transport.outcomes = [failure, b'{"totalResults": 0}']
    assert monitor.read_json(URL) == {'totalResults': 0}
    assert transport.waits == [15]
    log = capsys.readouterr().err
    assert 'NVD sqlite 3.54.1 startIndex=0' in log and 'attempt 2/3' in log
    assert SECRET not in log and URL not in log
    assert all('Authorization' not in request.headers for request, _ in transport.calls)


@pytest.mark.parametrize('status', [408, 429, 500, 502, 503, 504])
def test_transient_http_respects_retry_after(transport, status):
    transport.outcomes = [http_error(status, '45'), b'{}']
    assert monitor.read_json(URL) == {}
    assert transport.waits == [45]


def test_retry_after_date_and_invalid_hint(transport, monkeypatch):
    monkeypatch.setattr(monitor.time, 'time', lambda: 0)
    transport.outcomes = [http_error(503, 'Thu, 01 Jan 1970 00:01:00 GMT'),
                          http_error(429, SECRET), b'{}']
    assert monitor.read_json(URL) == {}
    assert transport.waits == [60, 30]


@pytest.mark.parametrize('status', [301, 400, 401, 403, 404])
def test_permanent_http_never_retries_or_echoes_response(transport, capsys, status):
    transport.outcomes = [http_error(status)]
    with pytest.raises(monitor.monitor.MonitorFailure, match=f'HTTP {status}.*attempt 1/3') as exc:
        monitor.read_json(URL)
    assert not transport.waits and len(transport.calls) == 1
    assert SECRET not in str(exc.value) + capsys.readouterr().err


def test_timeout_exhaustion_is_bounded_and_keeps_source_identity(transport, capsys):
    transport.outcomes = [TimeoutError(SECRET) for _ in range(3)]
    with pytest.raises(monitor.monitor.MonitorFailure, match='NVD sqlite.*timeout.*attempt 3/3') as exc:
        with monitor.phase('NVD component/schema assessment'):
            monitor.read_json(URL)
    assert transport.waits == [15, 30] and len(transport.calls) == 3
    assert SECRET not in str(exc.value) + capsys.readouterr().err


@pytest.mark.parametrize('error', [TimeoutError(SECRET), http.client.IncompleteRead(SECRET.encode(), 100)])
def test_body_read_failure_discards_partial_response_and_retries(transport, monkeypatch, error):
    class BrokenBody(io.BytesIO):
        def read(self, *_):
            raise error

    bodies = [BrokenBody(b''), io.BytesIO(b'{"totalResults": 0}')]
    monkeypatch.setattr(monitor.urllib.request, 'build_opener', lambda *args: SimpleNamespace(
        open=lambda *a, **k: bodies.pop(0)))
    assert monitor.read_json(URL) == {'totalResults': 0}
    assert transport.waits == [15]


def test_response_arriving_after_scan_budget_is_not_accepted(transport, monkeypatch):
    class LateBody(io.BytesIO):
        def read(self, *_):
            transport.now = 361
            return b'{}'

    monkeypatch.setattr(monitor.urllib.request, 'build_opener', lambda *args: SimpleNamespace(
        open=lambda *a, **k: LateBody()))
    with pytest.raises(monitor.monitor.MonitorFailure, match='budget exhausted during'):
        monitor.read_json(URL, deadline=360)


@pytest.mark.parametrize('hint,deadline', [('121', 360), ('999999999999999999999', 360), ('30', 20)])
def test_oversized_retry_delay_aborts_instead_of_retrying_early(transport, hint, deadline):
    transport.outcomes = [http_error(429, hint)]
    with pytest.raises(monitor.monitor.MonitorFailure, match='retry delay exceeds'):
        monitor.read_json(URL, deadline=deadline)
    assert not transport.waits and len(transport.calls) == 1


def test_budget_is_shared_and_limits_socket_timeout(transport):
    transport.now = 350
    transport.outcomes = [b'{}']
    assert monitor.read_json(URL, deadline=360) == {}
    assert transport.calls[0][1] == 10
    transport.now = 360
    with pytest.raises(monitor.monitor.MonitorFailure, match='budget exhausted before'):
        monitor.read_json(URL, deadline=360)
    assert len(transport.calls) == 1


@pytest.mark.parametrize('raw', [b'not-json', b'\xff', b'[]', b' ' * (16 * 1024 * 1024 + 1)])
def test_invalid_response_does_not_retry_or_report_empty_success(transport, raw):
    transport.outcomes = [raw]
    with pytest.raises(monitor.monitor.MonitorFailure, match='JSON|size bound'):
        monitor.read_json(URL)
    assert len(transport.calls) == 1 and not transport.waits


def test_unapproved_endpoint_never_reaches_network(transport):
    with pytest.raises(ValueError, match='Unapproved'):
        monitor.read_json('https://example.com/' + SECRET)
    assert transport.calls == []


@pytest.mark.parametrize('error,category', [(ValueError(SECRET), 'invalid or incomplete metadata'),
                                         (http.client.BadStatusLine(SECRET), 'connection/read failure')])
def test_phase_error_keeps_stage_but_masks_untrusted_exception(error, category):
    with pytest.raises(monitor.monitor.MonitorFailure, match=f'GitHub notification history: {category}') as exc:
        with monitor.phase('GitHub notification history'):
            raise error
    assert SECRET not in str(exc.value)


def test_incomplete_nvd_scan_cannot_write_or_notify(transport, monkeypatch):
    """Exercise apply's real read/cache path: exhausted metadata reads stop all writes."""
    lock = {'version': '3.13.18', 'build': '20261110', 'components': {'sqlite': {'version': '3.54.1'}}}
    transport.outcomes = [json.dumps({'tag': '20261110'}).encode(), b'{}',
                          TimeoutError(SECRET), TimeoutError(SECRET), TimeoutError(SECRET)]
    monkeypatch.setattr(monitor, 'baselines', lambda _: [('published stable', lock)])
    monkeypatch.setattr(monitor, 'release_findings', lambda *args: [])
    monkeypatch.setattr(monitor.monitor.evidence, 'api', lambda _: {})
    monkeypatch.setattr(monitor.monitor, 'require_main_job', lambda _: None)
    monkeypatch.setattr(monitor.monitor.hosted, 'bot', lambda: None)
    monkeypatch.setattr(monitor.monitor, 'write_issue', lambda *a, **k: pytest.fail('Incomplete scan wrote issue'))
    monkeypatch.setattr(monitor.fix_monitor, 'publish', lambda *a: pytest.fail('Incomplete scan sent notice'))
    with pytest.raises(monitor.monitor.MonitorFailure, match='NVD sqlite.*attempt 3/3'):
        monitor.run(apply=True)
