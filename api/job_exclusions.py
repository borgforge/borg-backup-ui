"""Job-owned marker names and immutable imported exclusion files (#469, #470)."""
import base64
import binascii
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

MAX_FILE_BYTES = 65536
MAX_LINE_BYTES = 4096


class ExclusionError(ValueError):
    api_code = "job_exclusions_invalid"


def marker_names(raw=None):
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 32:
        raise ExclusionError("Use at most 32 marker names")
    result = []
    for name in raw:
        if (not isinstance(name, str) or not name or name in (".", "..")
                or len(name.encode('utf-8')) > 255 or '/' in name or '\\' in name
                or any(ord(char) < 32 or ord(char) == 127 for char in name)):
            raise ExclusionError("Markers must be file names without paths or control characters")
        if name not in result:
            result.append(name)
    return result


def validate_bytes(data):
    if not data or len(data) > MAX_FILE_BYTES or b'\0' in data:
        raise ExclusionError("Exclusion file must contain 1 to 65536 bytes without NUL")
    try:
        text = data.decode('utf-8')
    except UnicodeError as exc:
        raise ExclusionError("Exclusion file must use UTF-8") from exc
    if text.startswith('\ufeff'):
        raise ExclusionError("Use UTF-8 without a byte order mark")
    if any(ord(c) < 32 and c not in '\r\n\t' for c in text):
        raise ExclusionError("Exclusion file contains control characters")
    for line in text.splitlines():
        if len(line.encode('utf-8')) > MAX_LINE_BYTES:
            raise ExclusionError("Exclusion file line exceeds 4096 bytes")
        if any(ord(c) < 32 and c != '\t' for c in line):
            raise ExclusionError("Exclusion file contains control characters")
        pattern = line.strip()
        if pattern.startswith('re:'):
            try:
                re.compile(pattern[3:])
            except re.error as exc:
                raise ExclusionError("Invalid regular expression in exclusion file") from exc
    return data


def validate_file_metadata(payload):
    if not isinstance(payload, dict):
        raise ExclusionError("Invalid exclusion file metadata")
    name = payload.get('original_name')
    if (not isinstance(name, str) or not name or name in ('.', '..')
            or len(name.encode('utf-8')) > 255 or '/' in name or '\\' in name
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise ExclusionError("Invalid exclusion filename")
    if not re.fullmatch(r'[0-9a-f]{64}', str(payload.get('sha256', ''))):
        raise ExclusionError("Invalid exclusion file digest")
    if type(payload.get('size')) is not int or not 0 < payload['size'] <= MAX_FILE_BYTES:
        raise ExclusionError("Invalid exclusion file size")
    return payload


def upload_bytes(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('content_b64'), str):
        raise ExclusionError("Exclusion file content is missing")
    encoded = payload['content_b64']
    if len(encoded) > (MAX_FILE_BYTES + 2) // 3 * 4:
        raise ExclusionError("Exclusion file exceeds 65536 bytes")
    try:
        data = validate_bytes(base64.b64decode(encoded, validate=True))
    except (ValueError, binascii.Error) as exc:
        raise ExclusionError("Invalid exclusion file content") from exc
    digest = hashlib.sha256(data).hexdigest()
    # Browser uploads need only a filename and content; transfers also verify metadata.
    meta = {**payload, 'size': payload.get('size', len(data)), 'sha256': payload.get('sha256', digest)}
    validate_file_metadata(meta)
    if meta['size'] != len(data) or meta['sha256'] != digest:
        raise ExclusionError("Exclusion file does not match its recorded digest or size")
    return data, meta


def _folder(jobs_dir, job_id, create=False):
    from job_identity import validate_job_id
    job_id = validate_job_id(job_id)
    root = Path(jobs_dir)
    # Never follow a substituted parent or job directory.
    for part in [*reversed(root.parents), root, root / 'exclusions', root / 'exclusions' / job_id]:
        if part.is_symlink():
            raise ExclusionError("Symlinks are not allowed for managed exclusion files")
    folder = root / 'exclusions' / job_id
    if create:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder


def read_file(payload, jobs_dir, job_id):
    validate_file_metadata(payload)
    expected = f"{job_id}/{payload['sha256']}.txt"
    if payload.get('managed_file') != expected:
        raise ExclusionError("Exclusion file does not belong to this job")
    path = _folder(jobs_dir, job_id) / f"{payload['sha256']}.txt"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ExclusionError("Exclusion file must be a regular file")
            data = validate_bytes(source.read(MAX_FILE_BYTES + 1))
    except OSError as exc:
        raise ExclusionError("Managed exclusion file is missing or unreadable") from exc
    if len(data) != payload['size'] or hashlib.sha256(data).hexdigest() != payload['sha256']:
        raise ExclusionError("Managed exclusion file has changed or is corrupt")
    return data


def prepare_file(payload, jobs_dir, job_id):
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ExclusionError("Invalid exclusion file")
    if 'content_b64' not in payload:
        read_file(payload, jobs_dir, job_id)
        return {key: payload.get(key, '') for key in ('managed_file', 'original_name', 'size', 'sha256', 'imported_at')}
    data, meta = upload_bytes(payload)
    folder = _folder(jobs_dir, job_id, create=True)
    path = folder / f"{meta['sha256']}.txt"
    result = {key: meta[key] for key in ('original_name', 'size', 'sha256')}
    result.update(managed_file=f"{job_id}/{meta['sha256']}.txt",
                  imported_at=datetime.now(timezone.utc).isoformat())
    if path.exists() or path.is_symlink():
        read_file(result, jobs_dir, job_id)
    else:
        from inventory_store import atomic_write_bytes
        atomic_write_bytes(path, data, mode=0o600)
    return result


def cleanup_files(jobs_dir, job_id):
    """Call under the inventory lock after saving/deleting metadata."""
    meta_path = Path(jobs_dir) / f'{job_id}.json'
    current = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    keep = (current.get('exclude_from') or {}).get('sha256', '')
    folder = _folder(jobs_dir, job_id)
    if not folder.is_dir():
        return
    for path in folder.iterdir():
        if re.fullmatch(r'[0-9a-f]{64}\.txt', path.name) and path.stem != keep:
            path.unlink()
    if not any(folder.iterdir()):
        folder.rmdir()


def exported_file(payload, jobs_dir, job_id):
    return {**payload, 'content_b64': base64.b64encode(read_file(payload, jobs_dir, job_id)).decode('ascii')} if payload else None
