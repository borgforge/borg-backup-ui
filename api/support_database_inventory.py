"""Allowlisted database configuration snapshot for support consumers (#703)."""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone

from database_profiles import DatabaseError, SUPPORTED_ENGINES, store_path, validate_stored_profile


MAX_INVENTORY_BYTES = 2 * 1024 * 1024
PROFILE_FIELDS = (
    'id', 'name', 'engine', 'enabled', 'container', 'databases', 'include_globals',
    'staging_mount', 'staging_dir', 'port', 'timeout_seconds', 'min_free_mib', 'retention',
)


def support_database_inventory(config: dict) -> dict:
    """Read a bounded, credential-free snapshot without changing inventory or secrets.

    Returns export schema v1 with a fixed status and current-at-export timestamp.
    Missing, unreadable, oversized, unsupported or invalid input yields no profiles;
    only an available empty list establishes an empty inventory. Symlinks and
    non-regular files are rejected. Validation errors never expose source values.
    General support string sanitization is applied by the ZIP writer afterwards.
    """
    result = {
        'schema_version': 1,
        'scope': 'current_configuration_at_export',
        'captured_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'unreadable',
        'profiles': [],
    }
    source = store_path(config)
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return result
            raw = handle.read(MAX_INVENTORY_BYTES + 1)
    except FileNotFoundError:
        result['status'] = 'missing'
        return result
    except OSError:
        return result
    if len(raw) > MAX_INVENTORY_BYTES:
        result['status'] = 'too_large'
        return result
    try:
        inventory = json.loads(raw.decode('utf-8'))
        if not isinstance(inventory, dict) or type(inventory.get('schema_version')) is not int:
            raise ValueError('Invalid inventory envelope')
        if inventory['schema_version'] != 1:
            result['status'] = 'unsupported_schema'
            return result
        if not isinstance(inventory.get('profiles'), list):
            raise ValueError('Invalid profile collection')
        profiles = []
        seen = set()
        for raw_profile in inventory['profiles']:
            profile = validate_stored_profile(raw_profile)
            if profile['id'] in seen:
                raise ValueError('Duplicate profile ID')
            seen.add(profile['id'])
            # Select fields explicitly: never copy credentials, references,
            # execution/database users, arbitrary extensions or nested objects.
            row = {key: profile[key] for key in PROFILE_FIELDS if key in profile}
            row['engine_status'] = 'supported' if profile['engine'] in SUPPORTED_ENGINES else 'retired'
            profiles.append(row)
    except (ValueError, TypeError, KeyError, UnicodeError, DatabaseError, RecursionError):
        result['status'] = 'invalid'
        return result
    result.update(status='available', profiles=sorted(profiles, key=lambda row: row['id']))
    return result
