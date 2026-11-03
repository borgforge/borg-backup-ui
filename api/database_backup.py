"""Bounded Docker database exports, Unraid-compatible staging and archive verification (#591).

Callers hold the existing docker-control resource for the entire operation.
Persistent operation journals prevent stale job locks from allowing an unsafe retry.
"""
from __future__ import annotations

import copy
import errno
import gzip
import hashlib
import json
import logging
import os
import re
import selectors
import stat
import subprocess
import time
import tempfile
import uuid
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager

from database_profiles import DatabaseError, data_root, read_password, profile_slug, SUPPORTED_ENGINES
from inventory_store import atomic_write_json
from security_utils import mask_secrets

SCRIPTS = Path(__file__).resolve().parents[1] / 'runtime' / 'scripts'
# The supervisor remains outside the client's process group. Its terminal marker is
# written only after wait; control also checks for non-zombie group descendants.
SUPERVISOR = r'''
set -eu
umask 077
state=/dev/shm/bbui-db-$1; shift
mkdir -m 700 "$state"
trap 'rm -f "$state/credentials"' EXIT
command -v setsid >/dev/null || { echo 24 > "$state/done"; exit 24; }
exec 3<&0
setsid sh -s -- "$state" "$@" <&3 &
child=$!
rc=0
wait "$child" || rc=$?
printf '%s\n' "$rc" > "$state/done"
exit "$rc"
'''
LEADER = r'''
state=$1; shift
printf '%s\n' "$$" > "$state/pid"
IFS= read -r line < /proc/$$/stat
rest=${line##*) }; set -- "$@" # preserve tool parameters
printf '%s\n' "$line" > "$state/identity"
'''
# Never interpolate user data into this program. PID/start time/group membership
# must agree before signalling a process group; unknown state stays blocked.
CONTROL = r'''
set -eu
state=/dev/shm/bbui-db-$1; action=$2
[ -d "$state" ] && [ ! -L "$state" ] || { echo unknown; exit; }
[ "$(stat -c %u "$state")" = "$(id -u)" ] && [ "$(stat -c %a "$state")" = 700 ] || exit 1
if [ ! -f "$state/pid" ]; then
  if [ -f "$state/done" ]; then
    if [ "$action" = ack ]; then rm -f "$state/done" "$state/credentials"; rmdir "$state"; fi
    echo done
  else echo unknown; fi
  exit
fi
read -r pid < "$state/pid"
case "$pid" in ''|*[!0-9]*) exit 1;; esac
[ "$pid" -gt 1 ] || exit 1
# Print the start time and process group from a proc stat record.
identity() { rest=${1##*) }; set -- $rest; group=$3; shift 19; printf '%s:%s' "$group" "$1"; }
live=0
for f in /proc/[0-9]*/stat; do
  IFS= read -r line < "$f" 2>/dev/null || continue
  rest=${line##*) }; set -- $rest
  if [ "$3" = "$pid" ] && [ "$1" != Z ]; then live=1; fi
done
if [ "$live" = 0 ] && [ -f "$state/done" ]; then
  if [ "$action" = ack ]; then rm -f "$state/pid" "$state/identity" "$state/done" "$state/credentials"; rmdir "$state"; fi
  echo done; exit
fi
if [ "$action" = cancel ] || [ "$action" = kill ]; then
  [ -f "$state/identity" ] && [ -r /proc/"$pid"/stat ] || { echo unknown; exit; }
  IFS= read -r old < "$state/identity"
  IFS= read -r current < /proc/"$pid"/stat
  [ "$(identity "$old")" = "$(identity "$current")" ] || { echo unknown; exit; }
  if [ "$action" = cancel ]; then kill -TERM -"$pid"; else kill -KILL -"$pid"; fi
fi
echo running
'''


def utc_now():
    """Return a timezone-qualified timestamp for durable reports."""
    return datetime.now(timezone.utc).isoformat()


def _docker(profile, container=None):
    cmd = ['docker', 'exec']
    if profile.get('execution_user'):
        cmd += ['--user', profile['execution_user']]
    return cmd + ['-i', container or profile['container'], 'env', '-i',
                  'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                  'HOME=/nonexistent', 'LC_ALL=C']


def _run(cmd, **kwargs):
    """Run a short control command, suppressing untrusted client diagnostics."""
    try:
        result = subprocess.run(cmd, stderr=subprocess.DEVNULL, timeout=15, **kwargs)
        if result.returncode:
            raise DatabaseError('container_unavailable')
        return result
    except (OSError, subprocess.TimeoutExpired):
        raise DatabaseError('container_unavailable') from None


def container_identity(profile):
    """Resolve a running container once; return only its immutable ID."""
    result = _run(['docker', 'inspect', '--format', '{{.Id}} {{.State.Running}}', profile['container']],
                  stdout=subprocess.PIPE, text=True)
    parts = result.stdout.strip().split()
    if len(parts) != 2 or parts[1] != 'true' or not re.fullmatch(r'[a-f0-9]{64}', parts[0]):
        raise DatabaseError('container_unavailable')
    return parts[0]


def _control(record, action):
    try:
        result = _run(_docker(record, record['container_id']) + ['sh', '-c', CONTROL, 'bbui', record['token'], action],
                      stdout=subprocess.PIPE, text=True)
        return result.stdout.strip()
    except DatabaseError:
        return 'unknown'


def _terminate(record):
    """Stop only the verified client group; return whether termination is confirmed."""
    for action, attempts in [('cancel', 20), ('kill', 10)]:
        if _control(record, action) == 'done':
            return True
        for _ in range(attempts):
            time.sleep(0.1)
            if _control(record, 'status') == 'done':
                return True
    return False


def reconcile_operations(config):
    """Reconcile interrupted exporters while holding docker-control, or fail closed."""
    for path in (data_root(config) / 'database-operations').glob('*.json'):
        try:
            record = json.loads(path.read_text())
            if record['status'] not in ('running', 'unresolved'):
                continue
            # A removed/stopped immutable container cannot still contain an exporter.
            present = _run(['docker', 'ps', '-aq', '--no-trunc', '--filter', 'id=' + record['container_id']], stdout=subprocess.PIPE, text=True)
            if not present.stdout.strip():
                record.update(status='interrupted', finished_at=utc_now())
                atomic_write_json(path, record)
                continue
            info = _run(['docker', 'inspect', '--format', '{{.State.Running}}', record['container_id']],
                        stdout=subprocess.PIPE, text=True)
            stopped = info.stdout.strip() == 'false'
            if not stopped and not _terminate(record):
                raise DatabaseError('unresolved_export')
            record.update(status='interrupted', finished_at=utc_now())
            atomic_write_json(path, record)
            if not stopped:
                _control(record, 'ack')
        except (OSError, KeyError, ValueError):
            raise DatabaseError('unresolved_export') from None


def _operation(config, profile, cid, action, database, output, cancelled):
    """Stream bounded chunks to a binary sink, including a gzip writer.

    Journal before launch; monitor timeout/cancellation while draining Docker stdout.
    Sink/pipe failures terminate the owned exporter group and never mark completion.
    """
    if profile.get('engine') not in SUPPORTED_ENGINES:
        raise DatabaseError('profile_unavailable')
    token = uuid.uuid4().hex
    journal = data_root(config) / 'database-operations' / (token + '.json')
    record = {'token': token, 'container_id': cid, 'execution_user': profile['execution_user'],
              'profile_id': profile['id'], 'status': 'running', 'started_at': utc_now()}
    if action == 'discover':
        record['discovery_directory'] = Path(output.name).parent.name
    credentials = ''
    credential_file = profile.get('credential_file', '')
    if profile.get('auth_mode') == 'managed':
        password = read_password(config, profile)
        if profile['engine'] in ('mariadb', 'mysql'):
            escaped = password.replace('\\', '\\\\').replace('"', '\\"').replace('\t', '\\t')
            content = '[client]\nuser=' + profile['database_user'] + '\npassword="' + escaped + '"\n'
        else:
            escaped = password.replace('\\', '\\\\').replace(':', '\\:')
            content = f"127.0.0.1:{profile['port']}:*:{profile['database_user']}:{escaped}\n"
        delimiter = 'BBUI_SECRET_' + uuid.uuid4().hex
        # Only stdin carries secret bytes. A quoted here-document disables shell expansion.
        credentials = f'cat > "$state/credentials" <<\'{delimiter}\'\n{content}{delimiter}\n'
        credential_file = '/dev/shm/bbui-db-' + token + '/credentials'
    script = LEADER + credentials + (SCRIPTS / ('database-dump-' + profile['engine'] + '.sh')).read_text()
    journal.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    atomic_write_json(journal, record)
    cmd = _docker(profile, cid) + ['sh', '-c', SUPERVISOR, 'bbui', token, action,
                                credential_file, str(profile['port']), profile['database_user'], database]
    proc = None
    reason = None
    started = time.monotonic()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        proc.stdin.write(script.encode())
        proc.stdin.close()
        limit = min(60, profile['timeout_seconds']) if action in ('probe', 'discover') else profile['timeout_seconds']
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map() or proc.poll() is None:
                if cancelled():
                    reason = 'cancelled'
                    break
                if time.monotonic() - started > limit:
                    reason = 'timeout'
                    break
                for key, _ in selector.select(timeout=.1):
                    block = os.read(key.fd, 1024 * 1024)
                    if block:
                        output.write(block)
                    else:
                        selector.unregister(key.fileobj)
        if reason:
            if not _terminate(record):
                raise DatabaseError('unresolved_export')
            raise DatabaseError(reason)
        if _control(record, 'status') != 'done':
            if not _terminate(record):
                raise DatabaseError('unresolved_export')
        if proc.returncode:
            raise DatabaseError({21: 'credentials', 22: 'nontransactional', 24: 'tools_missing'}.get(proc.returncode, 'export_failed'))
        if container_identity(profile) != cid:
            raise DatabaseError('container_changed')
        record['status'] = 'completed'
    except BaseException as exc:
        confirmed = proc is None or _terminate(record)
        record['status'] = 'failed' if confirmed else 'unresolved'
        if not confirmed:
            raise DatabaseError('unresolved_export') from None
        if isinstance(exc, (OSError, BrokenPipeError)):
            raise DatabaseError('export_failed') from None
        raise
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if proc and proc.stdout:
            proc.stdout.close()
        record['finished_at'] = utc_now()
        atomic_write_json(journal, record)
        if record['status'] != 'unresolved':
            _control(record, 'ack')


DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def open_dump_file(path):
    """Open a regular dump/manifest without following links or waiting on a FIFO.

    Ownership and permission modes are left to Unraid. Hard links are rejected
    because only files belonging to the selected dump run may be used.
    The caller supplies an anchored parent path and closes the binary handle.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise DatabaseError('storage_path')
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def open_dump_directory(root_fd, name):
    """Hold one named run directory without following links; accept Unraid modes."""
    if not is_run_directory_name(name):
        raise DatabaseError('storage_path')
    fd = os.open(name, DIRECTORY_FLAGS, dir_fd=root_fd)
    try:
        yield fd
    finally:
        os.close(fd)


def _descriptor_path(fd):
    """Return a parent-process descriptor path usable by Python and Borg children."""
    return Path('/proc') / str(os.getpid()) / 'fd' / str(fd)


def _local_filesystem(fd):
    """Reject unsupported backing filesystems using the already opened directory."""
    try:
        fs = _run(['stat', '-f', '-c', '%T', str(_descriptor_path(fd))], stdout=subprocess.PIPE, text=True).stdout.strip()
    except DatabaseError:
        raise DatabaseError('storage_filesystem') from None
    if fs not in ('btrfs', 'xfs', 'ext2/ext3', 'zfs'):
        raise DatabaseError('storage_filesystem')


@contextmanager
def open_staging(profile, *, require_space=True):
    """Yield an accessible dump root on a mounted local filesystem.

    Existing owners/modes (including nobody:users, 0777) are never changed.
    Components are opened without symlinks; callers also hold each run directory.
    Explicit exports may create missing nested directories with 0755. Read-only
    listing never creates paths or requires write access. Mount, space and
    filesystem checks remain active. Errors use localized diagnostic codes.
    """
    mount, path = Path(profile['staging_mount']), Path(profile['staging_dir'])
    fd = None
    flags = DIRECTORY_FLAGS
    try:
        if not mount.is_absolute() or not path.is_absolute() or '..' in path.parts or '..' in mount.parts or mount not in path.parents:
            raise DatabaseError('storage_path')
        fd = os.open('/', flags)
        try:
            for component in mount.parts[1:]:
                child = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = child
        except FileNotFoundError:
            raise DatabaseError('storage_mount') from None
        if not os.path.ismount(mount) or not os.path.samestat(os.fstat(fd), mount.stat()):
            raise DatabaseError('storage_mount')
        _local_filesystem(fd)
        parts = path.relative_to(mount).parts
        for component in parts:
            try:
                child = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                if not require_space:
                    raise
                # Validate the held parent before creating anything beneath it.
                _local_filesystem(fd)
                try:
                    os.mkdir(component, mode=0o755, dir_fd=fd)
                except FileExistsError:
                    pass  # A concurrent creator still has to pass O_NOFOLLOW below.
                child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        access = os.R_OK | os.X_OK | (os.W_OK if require_space else 0)
        if not os.access(_descriptor_path(fd), access, effective_ids=True):
            raise DatabaseError('storage_permissions')
        _local_filesystem(fd)
        if require_space:
            space = os.fstatvfs(fd)
            if space.f_bavail * space.f_frsize < profile['min_free_mib'] * 1024 * 1024:
                raise DatabaseError('no_space')
        yield fd
    except FileNotFoundError:
        raise DatabaseError('storage_missing') from None
    except PermissionError:
        raise DatabaseError('storage_permissions') from None
    except OSError as exc:
        raise DatabaseError('storage_permissions' if exc.errno == errno.EROFS else 'storage_path') from None
    finally:
        if fd is not None:
            os.close(fd)


def staging_root(profile, *, require_space=True):
    """Validate storage without retaining a handle; use open_staging for actual I/O."""
    with open_staging(profile, require_space=require_space):
        return Path(profile['staging_dir'])


class DumpResult(dict):
    """Serializable manifest holding both the dump root and the actual run FD.

    A private, descriptor-held alias preserves existing archive paths for Borg
    even if someone renames a run in a writable Unraid directory. Handles and
    aliases are released by close_results; no descriptors enter persisted JSON.
    """

    def __init__(self, root_fd, name, **manifest):
        super().__init__(manifest)
        self._root_fd = self._run_fd = self._alias_fd = None
        self._alias_path = None
        self._name = name
        try:
            self._root_fd = os.dup(root_fd)
            self._run_fd = os.open(name, DIRECTORY_FLAGS, dir_fd=root_fd)
            # A freshly created run must still be ours before initializing it.
            if os.fstat(self._run_fd).st_uid != os.geteuid():
                raise DatabaseError('storage_path')
            os.fchmod(self._run_fd, 0o755)
        except BaseException:
            self.close()
            raise

    @property
    def path(self):
        """Return the held run, independent of replacements of its logical path."""
        if self._run_fd is None:
            raise DatabaseError('storage_path')
        return _descriptor_path(self._run_fd)

    @property
    def borg_directory(self):
        """Create a private alias once; keep the public archive layout unchanged."""
        if self._alias_fd is None:
            # Persistent configuration may be on Unraid's FAT boot device.
            self._alias_path = Path(tempfile.mkdtemp(prefix='bbui-database-artifacts-'))
            self._alias_fd = os.open(self._alias_path, DIRECTORY_FLAGS)
            os.symlink(str(self.path), self._name, dir_fd=self._alias_fd)
        return str(_descriptor_path(self._alias_fd)) + '/./' + self._name

    def close(self):
        """Close owned handles and remove only this process's empty alias folder."""
        if self._alias_fd is not None:
            try:
                os.unlink(self._name, dir_fd=self._alias_fd)
                if os.path.samestat(os.fstat(self._alias_fd), self._alias_path.lstat()):
                    self._alias_path.rmdir()
            except OSError:
                pass
        for key in ('_alias_fd', '_run_fd', '_root_fd'):
            fd = getattr(self, key, None)
            setattr(self, key, None)
            if fd is not None:
                os.close(fd)

    def __copy__(self):
        """Copy manifest data only; reports never own live directory handles."""
        return dict(self)

    def __deepcopy__(self, memo):
        """Return detached JSON data without copying/closing live handles."""
        return copy.deepcopy(dict(self), memo)

    def __del__(self):
        if getattr(self, '_root_fd', None) is not None:
            self.close()


def close_results(results):
    """Release all live export handles after the caller's final file operation."""
    for result in results:
        if isinstance(result, DumpResult):
            result.close()


def result_directory(result):
    """Return an anchored directory for live exports, or a stored manifest path."""
    return result.path if isinstance(result, DumpResult) else Path(result['directory'])


def write_manifest(result):
    """Write a 0644 dump manifest atomically through its held run directory.

    Set mode on the new file descriptor before publishing, never chmod a name
    that could have been replaced in a shared directory. Existing secrets and
    internal journals continue using their private persistence helpers.
    """
    directory = result_directory(result)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    name = '.manifest-' + uuid.uuid4().hex + '.tmp'
    try:
        target = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o644, dir_fd=fd)
        with os.fdopen(target, 'w') as handle:
            os.fchmod(handle.fileno(), 0o644)
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, 'manifest.json', src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(name, dir_fd=fd)
        except FileNotFoundError:
            pass
        finally:
            os.close(fd)


def validate_sources(profiles, sources):
    """Reject overlapping ordinary sources so historical/partial dumps cannot enter Borg."""
    for profile in profiles:
        root = Path(profile['staging_dir']).resolve()
        for source in sources:
            src = Path(source).resolve()
            if src == root or src in root.parents or root in src.parents:
                raise DatabaseError('source_overlap')


def _hash(path, cancelled=lambda: False):
    """Hash an artifact incrementally and honor cancellation between bounded reads."""
    digest = hashlib.sha256()
    with open_dump_file(path) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            if cancelled():
                raise DatabaseError('cancelled')
            digest.update(chunk)
    return digest.hexdigest()


def _probe(config, profile, cid, database, cancelled, directory):
    """Check connectivity/versions and retain only sanitized metadata, never client diagnostics."""
    # Probe text never enters logs. Bound its disk footprint via the fixed queries.
    path = directory / '.probe'
    try:
        with path.open('xb') as handle:
            os.fchmod(handle.fileno(), 0o600)
            _operation(config, profile, cid, 'probe', database, handle, cancelled)
        if path.stat().st_size > 65536:
            raise DatabaseError('export_failed')
        lines = path.read_text().splitlines()
        if len(lines) < 2:
            raise DatabaseError('export_failed')
        server = re.search(r'\d+(?:\.\d+)+', lines[0])
        client = re.search(r'(?:Distrib |from )?(\d+(?:\.\d+)+)', lines[1].split('Distrib ')[-1])
        if not server or not client:
            raise DatabaseError('version_mismatch')
        sv, cv = server[0], client[1]
        # SQL major versions match (major.minor for MySQL/MariaDB).
        width = 2 if profile['engine'] in ('mariadb', 'mysql') else 1
        if sv.split('.')[:width] != cv.split('.')[:width]:
            raise DatabaseError('version_mismatch')
        return {'server_version': sv, 'client_version': cv,
                'extensions': [line for line in lines[2:] if re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', line)]}
    finally:
        path.unlink(missing_ok=True)


def run_directory_name(profile_name, started_at):
    """Return a safe profile slug and server-local timestamp/offset, without a UUID."""
    stamp = datetime.fromisoformat(started_at).astimezone().strftime('%Y-%m-%d_%H-%M-%S%z')
    return f'bbui-{profile_slug(profile_name)}-{stamp}'


def is_run_directory_name(name):
    """Accept readable names and retained UUID-only or profile/time/UUID runs."""
    stamp = r'[a-z0-9][a-z0-9-]{0,59}-[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}[+-][0-9]{4}'
    return bool(re.fullmatch(r'bbui-(?:' + stamp + r'(?:-[a-f0-9]{32})?|[a-f0-9]{32})', name))


class _DumpProgressWriter:
    """Forward gzip writes and report byte counters at most once per second.

    The caller owns both streams. No dump contents enter the callback and no
    telemetry is written to disk by this adapter. Sink/callback failures propagate.
    """

    def __init__(self, compressed, handle, report):
        self.compressed, self.handle, self.report = compressed, handle, report
        self.last_update = float('-inf')

    def write(self, block):
        """Write one chunk and publish current original/compressed byte counts."""
        written = self.compressed.write(block)
        now = time.monotonic()
        if now - self.last_update >= 1:
            self.last_update = now
            self.report(self.compressed.tell(), self.handle.tell())
        return written

    def tell(self):
        """Return the uncompressed stream position."""
        return self.compressed.tell()


def _export_log_label(value):
    """Mask common secret formats and escape controls in a bounded log label."""
    return json.dumps(mask_secrets(str(value))[:160], ensure_ascii=True)


@contextmanager
def _profile_export_log(profile, check_only):
    """Log profile export boundaries and safe failure context, then re-raise errors.

    The yielded context tracks the active database. Connection-only checks stay
    silent; exception messages, credentials and client output are never logged.
    """
    context = {'profile': _export_log_label(profile.get('name', '')),
               'database': '-', 'started': time.monotonic()}
    if not check_only:
        logging.info('Database profile export started: profile=%s', context['profile'])
    try:
        yield context
    except BaseException as exc:
        if not check_only:
            safe_reasons = {'cancelled', 'timeout', 'credentials', 'nontransactional',
                            'tools_missing', 'export_failed', 'unresolved_export',
                            'container_unavailable', 'container_changed', 'version_mismatch',
                            'storage_mount', 'storage_path', 'storage_missing', 'storage_permissions',
                            'storage_filesystem', 'no_space', 'profile_unavailable',
                            'dump_exists', 'empty_dump', 'invalid_dump'}
            reason = exc.reason if isinstance(exc, DatabaseError) and exc.reason in safe_reasons else 'export_failed'
            logging.warning('Database profile export %s: profile=%s; database=%s; reason=%s; elapsed=%.1fs',
                            'cancelled' if reason == 'cancelled' else 'failed', context['profile'],
                            context['database'], reason, time.monotonic() - context['started'])
        raise
    else:
        if not check_only:
            logging.info('Database profile export completed locally: profile=%s; elapsed=%.1fs; not yet verified in a Borg archive',
                         context['profile'], time.monotonic() - context['started'])


def export_profiles(config, profiles, job_id, run_id, cancelled=lambda: False, progress=None, check_only=False, results=None, live_progress=None):
    """Export into held Unraid dump directories; retain completed files on failure.

    New runs use profile/time directory names and stream raw client bytes through
    gzip level 6 without an uncompressed staging copy. Publish .gz files only after
    successful client exit, nonempty input, gzip close and fsync. Manifests record
    original byte counts and compressed sizes/hashes; failed partial files remain.
    live_progress receives throttled, content-free phase/byte updates; progress
    retains its per-completed-file manifest contract.
    Logs export start, local completion and safe failure context per profile/database;
    streaming progress is logged at most every 30 seconds per profile. Connection-only
    checks do not emit export logs. A completed export is not an archive verification.
    Returns JSON-serializable DumpResult manifests. Call close_results after the
    final archive/cleanup operation; pass results to retain partial manifests and
    explicitly close handles even when this function raises.
    """
    results = results if results is not None else []
    for profile in profiles:
        with _profile_export_log(profile, check_only) as log_context:
            if profile.get('engine') not in SUPPORTED_ENGINES:
                raise DatabaseError('profile_unavailable')
            if cancelled():
                raise DatabaseError('cancelled')
            last_log_update = time.monotonic()
            started_at = utc_now()
            name = run_directory_name(profile['name'], started_at)
            with open_staging(profile) as fd:
                try:
                    os.mkdir(name, mode=0o755, dir_fd=fd)
                except FileExistsError:
                    raise DatabaseError('dump_exists') from None
                manifest = DumpResult(fd, name)
            directory = manifest.path
            manifest.update({'format_version': 1, 'helper_version': 1, 'job_id': job_id, 'run_id': run_id,
                        'profile_id': profile['id'], 'profile_name': profile['name'], 'engine': profile['engine'], 'started_at': started_at,
                        'compression': 'gzip',
                        'status': 'running', 'archived': False, 'restore_tested': False, 'files': [],
                        'retention': profile['retention'], 'directory': str(Path(profile['staging_dir']) / name),
                        'archive_directory': name,
                        'scope': {'databases': profile['databases'], 'globals': profile['include_globals'],
                                  'credentials': False, 'application_files_consistent': False},
                        'restore': restore_hint(profile['engine'])})
            results.append(manifest)
            try:
                write_manifest(manifest)
                cid = container_identity(profile)
                manifest['container_id'] = cid
                for database_index, database in enumerate(profile['databases'], 1):
                    log_context['database'] = _export_log_label(database)
                    if not check_only:
                        logging.info('Database export started: profile=%s; database=%s (%d/%d)',
                                     log_context['profile'], log_context['database'], database_index, len(profile['databases']))
                    def report_live(phase, processed=0, stored=0):
                        """Publish live totals and throttle content-free streaming log updates."""
                        nonlocal last_log_update
                        now = time.monotonic()
                        if not check_only and phase in ('exporting', 'globals') and now - last_log_update >= 30:
                            last_log_update = now
                            logging.info('Database export running: profile=%s; database=%s; phase=%s; elapsed=%.1fs; current export=%d bytes; compressed=%d bytes',
                                         log_context['profile'], log_context['database'], phase,
                                         now - log_context['started'], processed, stored)
                        if live_progress:
                            live_progress({'phase':phase, 'database':database, 'database_index':database_index,
                                'databases_total':len(profile['databases']),
                                'processed_bytes':sum(f['uncompressed_bytes'] for f in manifest['files']) + processed,
                                'written_bytes':sum(f['bytes'] for f in manifest['files']) + stored})
                    report_live('checking')
                    started = time.monotonic()
                    versions = _probe(config, profile, cid, database, cancelled, directory)
                    if check_only:
                        manifest.setdefault('checks', []).append({'database': database, **versions})
                        continue
                    space = os.statvfs(directory)
                    if space.f_bavail * space.f_frsize < profile['min_free_mib'] * 1024 * 1024:
                        raise DatabaseError('no_space')
                    actions = ['dump']
                    if profile['include_globals'] and database == profile['databases'][0]:
                        actions.append('globals')
                    for action in actions:
                        name = ('globals.sql' if action == 'globals' else database + dump_suffix(profile['engine'])) + '.gz'
                        partial = directory / (name + '.partial')
                        report_live('globals' if action == 'globals' else 'exporting')
                        with partial.open('xb') as handle:
                            os.fchmod(handle.fileno(), 0o644)
                            with gzip.GzipFile(filename='', mode='wb', fileobj=handle, compresslevel=6, mtime=0) as compressed:
                                sink = _DumpProgressWriter(compressed, handle, lambda count, stored: report_live('globals' if action == 'globals' else 'exporting', count, stored))
                                _operation(config, profile, cid, action, database, sink, cancelled)
                                uncompressed_bytes = compressed.tell()
                            handle.flush()
                            os.fsync(handle.fileno())
                        if not uncompressed_bytes:
                            raise DatabaseError('empty_dump')
                        if profile['engine'] == 'postgresql' and action == 'dump':
                            magic = b'PGDMP'
                            with gzip.open(partial, 'rb') as handle:
                                if handle.read(len(magic)) != magic:
                                    raise DatabaseError('invalid_dump')
                        report_live('finalizing', uncompressed_bytes, partial.stat().st_size)
                        final = directory / name
                        partial.rename(final)
                        manifest['files'].append({'name': name, 'database': database, 'kind': action, **versions,
                                                  'bytes': final.stat().st_size, 'uncompressed_bytes': uncompressed_bytes, 'compression': 'gzip', 'sha256': _hash(final, cancelled),
                                                  'duration_seconds': round(time.monotonic() - started, 3), 'status': 'dump_completed'})
                        write_manifest(manifest)
                        logging.info('Database export completed locally: profile=%s; database=%s; kind=%s; duration=%.1fs; exported=%d bytes; compressed=%d bytes; not yet verified in a Borg archive',
                                     log_context['profile'], log_context['database'], action,
                                     time.monotonic() - started, uncompressed_bytes, final.stat().st_size)
                        report_live('completed')
                        if progress:
                            progress(manifest)
                manifest['status'] = 'checked' if check_only else 'dump_completed'
            except BaseException:
                manifest['status'] = 'failed'
                raise
            finally:
                manifest['finished_at'] = utc_now()
                write_manifest(manifest)
    return results


def artifact_paths(results):
    """Return the exact completed files plus manifest from this run, never a staging tree."""
    return [result_directory(r) / name for r in results for name in [*[f['name'] for f in r['files']], 'manifest.json']]


def borg_artifact_paths(results):
    """Return anchored Borg inputs; slashdot keeps process/FD paths out of archives."""
    return [r.borg_directory + '/' + name
            if isinstance(r, DumpResult) else str(Path(r['directory']) / name)
            for r in results for name in [*[f['name'] for f in r['files']], 'manifest.json']]


def discover_databases(config, profile, cancelled=lambda: False):
    """List selectable names using the configured account; never change saved backup scope.

    Caller holds docker-control. Query output is bounded and temporary, and does
    not require dump storage or an existing database selection.
    """
    parent = data_root(config) / 'database-discovery'
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="discovery-", dir=parent) as temporary:
        path = Path(temporary) / 'names'
        with path.open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            _operation(config, profile, container_identity(profile), 'discover', '', output, cancelled)
        if path.stat().st_size > 1024 * 1024:
            raise DatabaseError('export_failed')
        names = path.read_text().splitlines()
    excluded = {'mysql', 'information_schema', 'performance_schema', 'sys'} if profile['engine'] in ('mariadb', 'mysql') else {'template0', 'template1'}
    return sorted(set(name for name in names if name.lower() not in excluded and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}', name)))


def restore_hint(engine):
    """Return artifact-specific recovery requirements stored alongside every dump."""
    instructions = {
        'mariadb': 'Import SQL with a compatible mariadb client; reprovision users/grants.',
        'mysql': 'Import SQL with a compatible mysql client; reprovision users/grants.',
        'postgresql': 'Use pg_restore for custom dumps and psql for optional globals; reprovision role passwords and extensions.',
    }
    return 'Decompress .gz files first. Restore into an isolated destination. ' + instructions[engine]


def dump_suffix(engine):
    """Return the native artifact suffix; reject unrecognized manifest engines."""
    try:
        return {'mariadb': '.sql', 'mysql': '.sql', 'postgresql': '.dump'}[engine]
    except KeyError:
        raise DatabaseError('invalid_dump') from None


def managed_scripts():
    """Return fixed bundled helper sources for an administrator's read-only view."""
    return [{'name': 'database-dump-' + engine + suffix, 'engine': engine,
             'content': (SCRIPTS / ('database-dump-' + engine + suffix)).read_text()}
            for engine in ('mariadb', 'postgresql', 'mysql')
            for suffix in ['.sh']]


def verify_archive(repo, archive, results, cancelled=lambda: False):
    """Stream required artifacts back from Borg and compare hashes without a second disk copy."""
    entries = [(r, path) for r in results for path in artifact_paths([r])]
    for result, path in entries:
        expected = _hash(path, cancelled)
        archive_path = result['archive_directory'] + '/' + path.name if result.get('archive_directory') else str(path).lstrip('/')
        cmd = ['borg', 'extract', '--stdout', repo + '::' + archive, archive_path]
        digest, size = hashlib.sha256(), 0
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        started = time.monotonic()
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    if cancelled() or time.monotonic() - started > 86400:
                        raise DatabaseError('cancelled' if cancelled() else 'timeout')
                    for key, _ in selector.select(timeout=.2):
                        block = os.read(key.fd, 1024 * 1024)
                        if not block:
                            selector.unregister(key.fileobj)
                        else:
                            digest.update(block)
                            size += len(block)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    raise DatabaseError('archive_verification') from None
            if proc.returncode != 0 or size != path.stat().st_size or digest.hexdigest() != expected:
                raise DatabaseError('archive_verification')
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            proc.stdout.close()
    for result in results:
        result.update(archived=True, archive=archive, status='archived')
    return results


def cleanup_run(directory, profile, *, verified=False, interrupted=False):
    """Remove only recognized files for this profile through held run descriptors.

    Existing Unraid ownership/modes are accepted. A replaced run, links, unknown
    files or incompatible manifest block cleanup. No recursive deletion occurs.
    Enumeration opens a fresh view of the pinned directory, including files
    created after export opened it. Filesystem errors may leave a partial cleanup.
    interrupted permits a running manifest only after exporter reconciliation
    under docker-control; verified requires an archived manifest.
    """
    if isinstance(directory, DumpResult):
        _cleanup_run(directory._root_fd, directory._name, directory._run_fd, profile,
                     verified=verified, interrupted=interrupted)
        return
    logical = Path(directory)
    if logical.parent != Path(profile['staging_dir']) or not is_run_directory_name(logical.name):
        raise DatabaseError('storage_path')
    with open_staging(profile, require_space=False) as fd:
        with open_dump_directory(fd, logical.name) as run_fd:
            _cleanup_run(fd, logical.name, run_fd, profile, verified=verified, interrupted=interrupted)


def _cleanup_run(root_fd, run_name, run_fd, profile, *, verified, interrupted):
    """Validate a pinned manifest and unlink only recognized run-local entries."""
    if not os.path.samestat(os.fstat(run_fd), os.stat(run_name, dir_fd=root_fd, follow_symlinks=False)):
        raise DatabaseError('cleanup_blocked')
    path = _descriptor_path(run_fd)
    try:
        with open_dump_file(path / 'manifest.json') as handle:
            manifest = json.load(handle)
    except (OSError, DatabaseError):
        raise DatabaseError('cleanup_blocked') from None
    if manifest.get('profile_id') != profile['id'] or (manifest.get('status') == 'running' and not interrupted):
        raise DatabaseError('cleanup_blocked')
    if verified and manifest.get('status') != 'archived':
        raise DatabaseError('cleanup_blocked')
    allowed = {'manifest.json', '.probe', '.verify'}
    databases = manifest.get('scope', {}).get('databases', [])
    if not isinstance(databases, list) or any(not isinstance(db, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}', db) for db in databases):
        raise DatabaseError('cleanup_blocked')
    for database in databases:
        name = database + dump_suffix(manifest['engine'])
        if manifest.get('compression') == 'gzip':
            name += '.gz'
        allowed.update((name, name + '.partial'))
    if manifest.get('scope', {}).get('globals'):
        name = 'globals.sql.gz' if manifest.get('compression') == 'gzip' else 'globals.sql'
        allowed.update((name, name + '.partial'))
    # Btrfs can retain the entry boundary from when the empty run was opened.
    # A new open (not dup) refreshes enumeration without trusting its pathname.
    scan_fd = os.open('.', DIRECTORY_FLAGS, dir_fd=run_fd)
    try:
        children = os.listdir(scan_fd)
    finally:
        os.close(scan_fd)
    for child in children:
        info = os.stat(child, dir_fd=run_fd, follow_symlinks=False)
        if child not in allowed or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise DatabaseError('cleanup_blocked')
    for child in children:
        os.unlink(child, dir_fd=run_fd)
    os.rmdir(run_name, dir_fd=root_fd)
