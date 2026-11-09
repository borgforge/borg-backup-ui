"""Pinned supplier download retries, cleanup and permanent failures (#728)."""
import errno
import hashlib
import http.client
import io
from pathlib import Path
import socket
import ssl
import sys
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
import python_runtime as builder

PAYLOAD = b'verified supplier bytes'
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
URL = 'https://example.test/archive?secret=do-not-log'


class Response(io.BytesIO):
    """Closable HTTP body with a declared length for deterministic transfer tests."""
    def __init__(self, data=PAYLOAD, length=None):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data) if length is None else length)}


@pytest.fixture
def download(tmp_path, monkeypatch):
    """Supply request outcomes and record backoff without network or real waits."""
    destination = tmp_path / 'supplier.tar.zst'
    temporary = destination.with_suffix('.download')
    outcomes, calls, waits = [], [], []

    def open_url(url, timeout):
        assert not temporary.exists(), 'Partial download must be removed before retry'
        assert url == URL and timeout == 60
        calls.append(url)
        result = outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def sleep(delay):
        assert not temporary.exists(), 'Partial download must be removed before waiting'
        waits.append(delay)

    monkeypatch.setattr(builder.urllib.request, 'urlopen', open_url)
    monkeypatch.setattr(builder.time, 'sleep', sleep)
    return destination, temporary, outcomes, calls, waits


def http_error(status):
    """Return an HTTP failure with deliberately sensitive details and a closeable body."""
    return urllib.error.HTTPError(URL, status, 'do-not-log', {}, io.BytesIO(b'do-not-log'))


@pytest.mark.parametrize('status', [408, 429, 500, 502, 503, 504])
def test_transient_http_retries_then_verifies(download, status, capsys):
    destination, temporary, outcomes, calls, waits = download
    error = http_error(status)
    response = Response()
    outcomes.extend([error, response])
    builder.fetch(URL, destination, DIGEST)
    assert len(calls) == 2 and waits == [5]
    assert destination.read_bytes() == PAYLOAD and not temporary.exists()
    assert error.fp.closed and response.closed
    output = capsys.readouterr()
    assert output.out == '' and f'HTTP {status}' in output.err
    assert 'attempt 1/5' in output.err and 'retrying in 5s' in output.err
    assert 'example.test' not in output.err and 'do-not-log' not in output.err


def test_backoff_is_bounded_and_preserves_existing_cache(download):
    destination, temporary, outcomes, calls, waits = download
    destination.write_bytes(b'previous cache')
    errors = [http_error(504) for _ in range(5)]
    outcomes.extend(errors)
    with pytest.raises(urllib.error.HTTPError) as caught:
        builder.fetch(URL, destination, DIGEST)
    assert caught.value is errors[-1]
    assert len(calls) == 5 and waits == [5, 10, 20, 40]
    assert destination.read_bytes() == b'previous cache' and not temporary.exists()
    assert all(error.fp.closed for error in errors)


@pytest.mark.parametrize('error', [
    TimeoutError(), ConnectionResetError(), http.client.RemoteDisconnected(),
    urllib.error.URLError(TimeoutError()),
    urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN, 'temporary DNS failure')),
    urllib.error.URLError(OSError(errno.ENETUNREACH, 'network unavailable')),
])
def test_transient_network_errors_retry(download, error):
    destination, _, outcomes, calls, waits = download
    outcomes.extend([error, Response()])
    builder.fetch(URL, destination, DIGEST)
    assert len(calls) == 2 and waits == [5] and destination.read_bytes() == PAYLOAD


@pytest.mark.parametrize('status', [400, 401, 403, 404, 410, 501])
def test_permanent_http_errors_do_not_retry(download, status):
    destination, temporary, outcomes, calls, waits = download
    error = http_error(status)
    outcomes.append(error)
    with pytest.raises(urllib.error.HTTPError):
        builder.fetch(URL, destination, DIGEST)
    assert len(calls) == 1 and not waits
    assert not destination.exists() and not temporary.exists() and error.fp.closed


@pytest.mark.parametrize('error', [
    urllib.error.URLError(ssl.SSLCertVerificationError(1, 'invalid certificate')),
    urllib.error.URLError(socket.gaierror(socket.EAI_NONAME, 'unknown hostname')),
    urllib.error.URLError('permanent failure'),
])
def test_certificate_and_permanent_network_errors_do_not_retry(download, error):
    destination, temporary, outcomes, calls, waits = download
    outcomes.append(error)
    with pytest.raises(urllib.error.URLError):
        builder.fetch(URL, destination, DIGEST)
    assert len(calls) == 1 and not waits and not temporary.exists()


def test_partial_response_is_discarded_before_retry(download):
    destination, temporary, outcomes, calls, waits = download

    class Interrupted(Response):
        def read(self, size=-1):
            if self.tell():
                raise ConnectionResetError('connection lost')
            return super().read(3)

    partial = Interrupted()
    outcomes.extend([partial, Response()])
    builder.fetch(URL, destination, DIGEST)
    assert partial.closed and len(calls) == 2 and waits == [5]
    assert destination.read_bytes() == PAYLOAD and not temporary.exists()


def test_truncated_content_length_retries(download):
    destination, _, outcomes, calls, waits = download
    outcomes.extend([Response(b'short', len(PAYLOAD)), Response()])
    builder.fetch(URL, destination, DIGEST)
    assert len(calls) == 2 and waits == [5] and destination.read_bytes() == PAYLOAD


def test_checksum_mismatch_never_retries_or_replaces_cache(download):
    destination, temporary, outcomes, calls, waits = download
    destination.write_bytes(b'old cached input')
    outcomes.append(Response(b'wrong'))
    with pytest.raises(ValueError, match='checksum mismatch'):
        builder.fetch(URL, destination, DIGEST)
    assert len(calls) == 1 and not waits and not temporary.exists()
    assert destination.read_bytes() == b'old cached input'


def test_valid_cached_input_requires_no_network(download):
    destination, _, _, calls, waits = download
    destination.write_bytes(PAYLOAD)
    builder.fetch(URL, destination, DIGEST)
    assert not calls and not waits


def test_local_write_error_does_not_retry(download, monkeypatch):
    destination, temporary, outcomes, calls, waits = download
    response = Response()
    outcomes.append(response)
    real_open = Path.open

    def open_file(path, *args, **kwargs):
        if path == temporary:
            raise PermissionError(errno.EACCES, 'read-only cache')
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', open_file)
    with pytest.raises(PermissionError):
        builder.fetch(URL, destination, DIGEST)
    assert len(calls) == 1 and not waits and response.closed and not temporary.exists()
