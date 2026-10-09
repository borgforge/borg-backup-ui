"""Admin-managed Bash scripts and bounded job hook execution (#550)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time
import uuid

from inventory_store import atomic_write_inventory, inventory_lock, read_inventory
from security_utils import mask_secrets


class ScriptValidationError(ValueError):
    """Expose a localized validation code and safe interpolation parameters."""

    def __init__(self, code: str, message: str, **params):
        super().__init__(message)
        self.api_code = 'job_script_' + code
        self.api_message_params = params


def store_path(config: dict) -> Path:
    """Return the persistent script inventory below the configured data root."""
    return Path(config['BACKUP_SCRIPTS_DIR']) / 'config' / 'job-scripts.json'


def list_scripts(config: dict) -> dict:
    """Read the admin-only inventory; reject corrupt existing data."""
    return read_inventory(store_path(config), collection_key='scripts', schema_version=1)


def validate_script(payload: dict) -> dict:
    """Validate fields and Bash syntax without execution; raise ValueError on failure.

    Syntax diagnostics include only the line number, never script contents.
    """
    if not isinstance(payload, dict):
        raise ScriptValidationError('selection', 'Script must be an object')
    name = str(payload.get('name') or '').strip()
    description = str(payload.get('description') or '').strip()
    content = payload.get('content')
    if not name or len(name) > 100 or '\n' in name or '\r' in name:
        raise ScriptValidationError('name', 'Script name must contain 1-100 characters on one line')
    if len(description) > 2000:
        raise ScriptValidationError('description', 'Script description exceeds 2000 characters')
    if not isinstance(content, str) or not content.strip() or '\x00' in content or len(content.encode()) > 65536:
        raise ScriptValidationError('content', 'Script content must contain 1-65536 bytes without NUL characters')
    content = content.replace('\r\n', '\n')
    try:
        timeout = int(str(payload.get('timeout_seconds', 300)))
    except (ValueError, TypeError):
        raise ScriptValidationError('timeout', 'Script timeout must be an integer') from None
    if not 1 <= timeout <= 86400:
        raise ScriptValidationError('timeout', 'Script timeout must be between 1 and 86400 seconds')
    result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-n'], input=content,
                            capture_output=True, text=True, timeout=5,
                            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    if result.returncode:
        match = re.search(r'line (\d+)', result.stderr)
        line = match.group(1) if match else '?'
        raise ScriptValidationError('syntax', f'Bash syntax error at line {line}', line=line)
    return {'name': name, 'description': description, 'content': content, 'timeout_seconds': timeout}


def save_script(config: dict, payload: dict) -> dict:
    """Create or explicitly update a validated script atomically under the inventory lock."""
    row = validate_script(payload)
    identifier = str(payload.get('id') or '')
    with inventory_lock(store_path(config).parent):
        data = list_scripts(config)
        if identifier:
            old = next((item for item in data['scripts'] if item['id'] == identifier), None)
            if old is None:
                raise ScriptValidationError('missing', 'Script no longer exists')
            data['scripts'].remove(old)
        else:
            identifier = 'script-' + uuid.uuid4().hex
        row['id'] = identifier
        data['scripts'].append(row)
        atomic_write_inventory(store_path(config), data)
    return {'script': row}


def delete_script(config: dict, identifier: str) -> dict:
    """Delete an unreferenced script; fail closed for unreadable job metadata."""
    with inventory_lock(store_path(config).parent):
        data = list_scripts(config)
        if not any(row['id'] == identifier for row in data['scripts']):
            raise ScriptValidationError('missing', 'Script no longer exists')
        for path in (store_path(config).parent / 'jobs').glob('*.json'):
            job = json.loads(path.read_text())
            hooks = job.get('hooks') or {}
            if identifier in (hooks.get('pre'), hooks.get('post')):
                raise ScriptValidationError('in_use', 'Script is assigned to a job; remove that assignment first')
        data['scripts'] = [row for row in data['scripts'] if row['id'] != identifier]
        atomic_write_inventory(store_path(config), data)
    return {'deleted': True}


def normalize_hooks(value: object, config: dict | None = None) -> dict:
    """Normalize optional job selections, optionally checking referenced scripts exist."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ScriptValidationError('selection', 'Job hooks must be an object')
    hooks = {key: str(value.get(key) or '') for key in ('pre', 'post')}
    hooks['post_when'] = value.get('post_when', 'success')
    if hooks['post_when'] not in ('success', 'always'):
        raise ScriptValidationError('selection', 'Post condition must be success or always')
    for key in ('pre', 'post'):
        if hooks[key] and not re.fullmatch(r'script-[a-f0-9]{32}', hooks[key]):
            raise ScriptValidationError('selection', 'Invalid script reference')
    if config and any(hooks[key] for key in ('pre', 'post')):
        ids = {row['id'] for row in list_scripts(config)['scripts']}
        if any(hooks[key] and hooks[key] not in ids for key in ('pre', 'post')):
            raise ScriptValidationError('missing', 'Selected script no longer exists')
    return hooks


def snapshot_hooks(config: dict, value: object) -> tuple[dict, dict]:
    """Resolve both scripts once so edits during a run cannot change its hooks."""
    hooks = normalize_hooks(value)
    if not hooks['pre'] and not hooks['post']:
        return hooks, {}
    rows = {row['id']: row for row in list_scripts(config)['scripts']}
    scripts = {}
    for phase in ('pre', 'post'):
        if hooks[phase]:
            if hooks[phase] not in rows:
                raise ScriptValidationError('missing', 'Selected script no longer exists')
            scripts[phase] = {**validate_script(rows[hooks[phase]]), 'id': hooks[phase]}
    return hooks, scripts


def run_hook(script: dict, phase: str, job_id: str, *, result: str = '', cancelled=None) -> dict:
    """Run Bash with a clean environment, bounded output and a process-group timeout.

    ``cancelled`` is polled for Pre only; Post cleanup is never cancelled. Output
    is masked and capped at 64 KiB. Children are terminated when the hook ends.
    Returns a serializable outcome; does not raise for launch or script failures.
    """
    outcome = {'script_id': script['id'], 'name': script['name'], 'status': 'failed', 'exit_code': 2}
    logging.info('━' * 80)
    logging.info('  PHASE: %s SCRIPT', phase.upper())
    logging.info('━' * 80)
    logging.info('Script: %s (timeout: %s seconds)', mask_secrets(script['name']), script['timeout_seconds'])
    started = time.monotonic()
    process = None
    script_fd = None
    try:
        # Keep source out of process arguments and disk; stdin stays non-interactive.
        script_fd = os.memfd_create('bbui-hook', os.MFD_CLOEXEC)
        os.write(script_fd, script['content'].encode())
        os.lseek(script_fd, 0, os.SEEK_SET)
        process = subprocess.Popen(['/bin/bash', '--noprofile', '--norc', f'/proc/self/fd/{script_fd}'],
            pass_fds=(script_fd,),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True, env={
                'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                'HOME': '/root', 'LANG': 'C.UTF-8',
                'BBUI_JOB_ID': job_id, 'BBUI_HOOK_PHASE': phase, 'BBUI_JOB_RESULT': result,
            })
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                if cancelled and cancelled():
                    outcome.update(status='cancelled', exit_code=130)
                    break
                if time.monotonic() - started >= script['timeout_seconds']:
                    outcome.update(status='timeout', exit_code=124)
                    break
                for key, _ in selector.select(0.1):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if chunk:
                        output.extend(chunk[:max(0, 65536 - len(output))])
                    else:
                        selector.unregister(key.fileobj)
                if process.poll() is not None and not selector.get_map():
                    code = process.returncode
                    outcome.update(status='success' if code == 0 else 'failed', exit_code=code)
                    break
        for line in mask_secrets(output.decode('utf-8', errors='replace')).splitlines():
            logging.info('[%s script] %s', phase, line)
        if len(output) >= 65536:
            logging.info('[%s script] Output truncated at 64 KiB', phase)
    except OSError:
        outcome['status'] = 'launch_failed'
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()
        if script_fd is not None:
            os.close(script_fd)
    outcome['duration_seconds'] = round(time.monotonic() - started, 3)
    logging.info('%s script finished: %s (exit %s; %.3f seconds)', phase, outcome['status'], outcome['exit_code'], outcome['duration_seconds'])
    logging.info('━' * 80)
    return outcome
