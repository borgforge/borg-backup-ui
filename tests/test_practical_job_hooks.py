"""Import and isolated failure-path checks for practical hook templates (#557)."""
from contextlib import nullcontext
from pathlib import Path
import base64
import json
import re
import shlex
import socket
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'api'))
import job_scripts

EXAMPLES = ROOT / 'docs/examples/job-hooks/practical'
SCRIPTS = sorted(EXAMPLES.glob('*.sh'))


@pytest.fixture
def sandbox(tmp_path):
    """Provide fake external commands; all writes stay in pytest's local directory."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    bodies = {
        'mountpoint': 'exit "${MOUNT_EXIT:-0}"',
        'df': "printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\nfake 99999999 1 %s 1%% /fake\\n' \"${FREE_KIB:-20971520}\"",
        'docker': '''printf '%s\\n' "$@" > "$CAPTURE_ARGS"
printf '%s' "${DUMP_DATA-database export}"
echo 'password=secret-canary' >&2
exit "${DUMP_EXIT:-0}"''',
        'curl': '''printf '%s\\n' "$@" > "$CAPTURE_ARGS"
cat > "$CAPTURE_BODY"
printf '%s' "${HTTP_CODE:-204}"
echo 'token=secret-canary' >&2
exit "${CURL_EXIT:-0}"''',
    }
    for name, body in bodies.items():
        path = bin_dir / name
        path.write_text('#!/bin/bash\nset -eu\n' + body + '\n')
        path.chmod(0o755)
    mount = tmp_path / 'mount'
    mount.mkdir()
    output = mount / 'dumps'
    output.mkdir(mode=0o700)
    config = tmp_path / 'webhook.curl'
    config.write_text('url = "https://example.invalid/test"\n')
    config.chmod(0o600)
    env = {'PATH': f'{bin_dir}:/usr/bin:/bin', 'LC_ALL': 'C',
           'BBUI_JOB_ID': 'job-"quoted', 'BBUI_HOOK_PHASE': 'pre',
           'CAPTURE_ARGS': str(tmp_path / 'args'), 'CAPTURE_BODY': str(tmp_path / 'body')}
    return tmp_path, mount, output, config, env


def run_example(name, sandbox, *, constants=None, env=None, configured=True):
    """Execute a configured copy via Bash with a clean environment and bounded wait."""
    tmp_path, mount, output, config, base_env = sandbox
    text = (EXAMPLES / name).read_text()
    changes = {'CONFIGURED': 'yes' if configured else 'no', 'MOUNT_PATH': str(mount),
               'SOURCE_PATH': str(mount), 'EXPECTED_ID': 'volume-a',
               'OUTPUT_DIR': str(output), 'CONTAINER': 'test-db', 'DATABASE': 'app_db',
               'DB_USER': 'backup', 'CURL_CONFIG': str(config)}
    changes.update(constants or {})
    for key, value in changes.items():
        text = re.sub(rf'^{key}=.*$', lambda _: f'{key}={shlex.quote(str(value))}', text, flags=re.M)
    return subprocess.run(['/bin/bash', '--noprofile', '--norc'], input=text,
                          text=True, capture_output=True, timeout=5, cwd=tmp_path,
                          env={**base_env, **(env or {})})


@pytest.mark.parametrize('path', SCRIPTS, ids=lambda p: p.name)
def test_import_and_unconfigured_fail_closed(path, sandbox):
    draft = job_scripts.import_script({'filename': path.name,
        'content_base64': base64.b64encode(path.read_bytes()).decode()})['script']
    assert draft['content'] == path.read_text()
    result = run_example(path.name, sandbox, configured=False)
    assert result.returncode == 2
    assert 'Configure this example' in result.stderr
    assert not (sandbox[0] / 'args').exists()
    assert list(sandbox[2].iterdir()) == []


@pytest.mark.parametrize('path', SCRIPTS, ids=lambda p: p.name)
def test_wrong_phase_is_rejected(path, sandbox):
    phase = 'pre' if path.name.startswith('post-') else 'post'
    assert run_example(path.name, sandbox, env={'BBUI_HOOK_PHASE': phase}).returncode == 2
    assert not (sandbox[0] / 'args').exists()


def test_source_identity_and_mount(sandbox):
    marker = sandbox[1] / '.backup-source-id'
    name = 'pre-check-source.sh'
    assert run_example(name, sandbox).returncode != 0
    marker.write_text('volume-a\n')
    assert run_example(name, sandbox).returncode == 0
    assert run_example(name, sandbox, env={'MOUNT_EXIT': '1'}).returncode != 0
    marker.write_text('wrong-volume')
    assert run_example(name, sandbox).returncode != 0
    marker.unlink()
    target = sandbox[0] / 'elsewhere'
    target.write_text('volume-a')
    marker.symlink_to(target)
    assert run_example(name, sandbox).returncode != 0
    assert run_example(name, sandbox, constants={'SOURCE_PATH': sandbox[0]}).returncode != 0


@pytest.mark.parametrize('space,code', [('10485760', 0), ('10485759', 1), ('n/a', 1)])
def test_free_space_threshold(sandbox, space, code):
    assert run_example('pre-check-free-space.sh', sandbox,
                       env={'FREE_KIB': space}).returncode == code


def test_free_space_requires_mount(sandbox):
    assert run_example('pre-check-free-space.sh', sandbox, env={'MOUNT_EXIT': '1'}).returncode != 0


@pytest.mark.parametrize('kind,extension', [('mariadb', 'sql'), ('postgresql', 'dump')])
def test_dump_success_retains_previous_exports(sandbox, kind, extension):
    name = f'pre-dump-{kind}.sh'
    for _ in range(2):
        result = run_example(name, sandbox)
        assert result.returncode == 0, result.stderr
        assert 'secret-canary' not in result.stdout + result.stderr
    exports = list(sandbox[2].glob(f'*/database.{extension}'))
    assert len(exports) == 2
    assert all(p.read_text() == 'database export' for p in exports)
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in exports)
    assert all(p.parent.stat().st_mode & 0o777 == 0o700 for p in exports)
    assert not list(sandbox[2].rglob('*.partial'))
    args = (sandbox[0] / 'args').read_text()
    assert 'app_db' in args and 'secret' not in args.replace('/run/secrets/', '')
    if kind == 'mariadb':
        assert '--single-transaction' in args and '--defaults-extra-file=' in args
    else:
        assert '--format=custom' in args and '--no-password' in args


@pytest.mark.parametrize('kind', ['mariadb', 'postgresql'])
@pytest.mark.parametrize('failure', [{'DUMP_EXIT': '3'}, {'DUMP_DATA': ''}])
def test_dump_failure_cleans_only_own_partial(sandbox, kind, failure):
    previous = sandbox[2] / 'previous.sql'
    previous.write_text('keep me')
    result = run_example(f'pre-dump-{kind}.sh', sandbox, env=failure)
    assert result.returncode != 0
    assert list(sandbox[2].iterdir()) == [previous]
    assert previous.read_text() == 'keep me'
    assert 'secret-canary' not in result.stdout + result.stderr


@pytest.mark.parametrize('kind', ['mariadb', 'postgresql'])
def test_dump_rejects_missing_mount_unsafe_mode_and_outside_path(sandbox, kind):
    name = f'pre-dump-{kind}.sh'
    assert run_example(name, sandbox, env={'MOUNT_EXIT': '1'}).returncode != 0
    sandbox[2].chmod(0o755)
    assert run_example(name, sandbox).returncode != 0
    assert run_example(name, sandbox, constants={'OUTPUT_DIR': sandbox[0]}).returncode != 0
    assert not (sandbox[0] / 'args').exists()


def test_postgresql_rejects_connection_strings(sandbox):
    assert run_example('pre-dump-postgresql.sh', sandbox,
                       constants={'DATABASE': 'postgresql://secret@host/db'}).returncode != 0
    assert not (sandbox[0] / 'args').exists()


@pytest.mark.parametrize('result', ['success', 'warning', 'failed', 'cancelled', 'skipped'])
def test_webhook_serializes_result_and_job_id(sandbox, result):
    run = run_example('post-json-webhook.sh', sandbox,
                      env={'BBUI_HOOK_PHASE': 'post', 'BBUI_JOB_RESULT': result})
    assert run.returncode == 0, run.stderr
    body = json.loads((sandbox[0] / 'body').read_text())
    assert body == {'job_id': 'job-"quoted', 'result': result}
    args = (sandbox[0] / 'args').read_text().splitlines()
    assert args[0] == '-q' and '--max-time' in args and '--location' not in args
    assert 'https://example.invalid/test' not in args
    assert 'secret-canary' not in run.stdout + run.stderr


@pytest.mark.parametrize('override', [{'CURL_EXIT': '28'}, {'HTTP_CODE': '500'},
                                     {'HTTP_CODE': '302'}, {'BBUI_JOB_RESULT': 'unknown'}])
def test_webhook_reports_delivery_or_contract_failure(sandbox, override):
    run = run_example('post-json-webhook.sh', sandbox,
                      env={'BBUI_HOOK_PHASE': 'post', 'BBUI_JOB_RESULT': 'success', **override})
    assert run.returncode != 0
    assert 'secret-canary' not in run.stdout + run.stderr


def test_webhook_rejects_public_or_symlinked_config(sandbox):
    config = sandbox[3]
    config.chmod(0o644)
    env = {'BBUI_HOOK_PHASE': 'post', 'BBUI_JOB_RESULT': 'success'}
    assert run_example('post-json-webhook.sh', sandbox, env=env).returncode != 0
    config.chmod(0o600)
    alias = sandbox[0] / 'alias'
    alias.symlink_to(config)
    assert run_example('post-json-webhook.sh', sandbox, constants={'CURL_CONFIG': alias}, env=env).returncode != 0
    assert not (sandbox[0] / 'args').exists()


@pytest.mark.parametrize('scenario,expected', [('already_ready', 0), ('wake', 0), ('timeout', 1), ('invalid', 1)])
def test_wake_packet_readiness_and_timeout(monkeypatch, scenario, expected):
    """Run the actual embedded Python with fake sockets; never send network packets."""
    source = (EXAMPLES / 'pre-wake-server.sh').read_text().split("<<'PYTHON'\n", 1)[1].split('\nPYTHON', 1)[0]
    packets, connections = [], []

    def connect(address, timeout):
        """Model an open or closed TCP port without network access."""
        connections.append((address, timeout))
        if scenario == 'already_ready' or (scenario == 'wake' and len(connections) > 1):
            return nullcontext()
        raise OSError('closed')

    class FakeSocket:
        """Capture broadcast bytes and reject no operations on this simulated socket."""
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def setsockopt(self, *args):
            pass

        def settimeout(self, value):
            pass

        def sendto(self, packet, address):
            packets.append((packet, address))

    tick = iter(range(100))
    monkeypatch.setattr(socket, 'create_connection', connect)
    monkeypatch.setattr(socket, 'socket', lambda *args: FakeSocket())
    monkeypatch.setattr(time, 'monotonic', lambda: next(tick))
    monkeypatch.setattr(time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(sys, 'argv', ['-', 'invalid' if scenario == 'invalid' else '02:11:22:33:44:55',
                                     '192.0.2.255', '192.0.2.10', '22', '5'])
    with pytest.raises(SystemExit) as exc:
        exec(compile(source, 'pre-wake-server.sh', 'exec'), {})
    assert exc.value.code == expected
    if scenario in {'already_ready', 'invalid'}:
        assert not packets
    else:
        assert packets == [(b'\xff' * 6 + bytes.fromhex('021122334455') * 16, ('192.0.2.255', 9))]
