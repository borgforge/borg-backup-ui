"""Bounded navigation through complete authorized logs, without persistence (#746)."""
import hashlib
import os
import re

import mobile_auth as auth

FILE_WINDOW = 65536
TEXT_WINDOW = 16000


def options(body):
    """Validate navigation fields; identities/paths are resolved by the caller."""
    result = {key: body[key] for key in ('start', 'before', 'file_id', 'known_size') if key in body}
    if 'start' in result and 'before' in result:
        raise auth.MobileError('mobile_bad_request', 400)
    for key in ('start', 'before', 'known_size'):
        if key in result and (type(result[key]) is not int or not 0 <= result[key] <= 2**53 - 1):
            raise auth.MobileError('mobile_bad_request', 400)
    if 'file_id' in result and (not isinstance(result['file_id'], str) or not re.fullmatch('[a-f0-9]{32}', result['file_id'])):
        raise auth.MobileError('mobile_bad_request', 400)
    if ('known_size' in result) != ('file_id' in result):
        raise auth.MobileError('mobile_bad_request', 400)
    return result


def bounds(size, identity, request, maximum):
    """Pin source and observed size, rejecting replacement/shrink with HTTP 409."""
    file_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
    if request.get('file_id', file_id) != file_id or request.get('known_size', 0) > size:
        raise auth.MobileError('mobile_job_changed', 409)
    if 'start' in request:
        start = request['start']
        end = min(size, start + maximum)
    else:
        end = request.get('before', size)
        start = max(0, end - maximum)
    if start > size or end > size:
        raise auth.MobileError('mobile_job_changed', 409)
    return start, end, file_id


def file_window(handle, request, *, running=False, identity=None):
    """Read at most 64 KiB with contiguous UTF-8 cursors from an open regular file.

    Caller owns authorization, confinement, capture identity verification and
    descriptor lifetime. Growing incomplete UTF-8 bytes remain for a later read.
    """
    from activity_log import read_window
    info = os.fstat(handle.fileno())
    start, end, file_id = bounds(info.st_size, identity or f'file:{info.st_dev}:{info.st_ino}', request, FILE_WINDOW)
    result = read_window(handle, start, end, running=running or end < info.st_size)
    return {**result, 'file_id': file_id, 'size': info.st_size, 'unit': 'bytes',
            'running': running, 'redacted': False}


def memory_window(lines, request, identity, running):
    """Copy at most 16000 code points from a locked append-only line list.

    Cursor units are Unicode code points; do not join or encode the entire log.
    Newlines match the existing browser SSE representation of memory log lines.
    """
    size = sum(len(line) + 1 for line in lines)
    start, end, file_id = bounds(size, identity, request, TEXT_WINDOW)
    pieces, position = [], 0
    for line in lines:
        following = position + len(line) + 1
        if following > start and position < end:
            left, right = max(0, start - position), min(len(line), end - position)
            pieces.append(line[left:right])
            if start <= following - 1 < end:
                pieces.append('\n')
        position = following
        if position >= end:
            break
    return {'start': start, 'end': end, 'file_id': file_id, 'size': size,
            'unit': 'characters', 'text': ''.join(pieces), 'running': running, 'redacted': False}
