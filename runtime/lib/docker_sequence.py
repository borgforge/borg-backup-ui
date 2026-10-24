"""Plan per-container Borg archives for sequential Docker backups.

Sequential mode stops one container group at a time, archives only the paths
those containers can write inside the job's backup sources and restarts the
group before the next one is stopped. Containers whose writable paths overlap
form one group, so a path is never archived while one of its writers runs.

Group archives are named ``<prefix>@<key>-<timestamp>``. Archive prefixes and
Docker container names cannot contain ``@``, so the job's ``<prefix>-*``
retention, check and restore filters never select these archives; every group
is pruned as its own series instead.

Only Python standard library.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ARCHIVE_SEPARATOR = "@"
TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"
_DIGIT = "[0-9]"
# Borg anchors --glob-archives at both ends; this matches exactly one timestamp.
TIMESTAMP_GLOB = (
    f"{_DIGIT * 4}-{_DIGIT * 2}-{_DIGIT * 2}_{_DIGIT * 2}-{_DIGIT * 2}-{_DIGIT * 2}"
)
MAX_ARCHIVE_NAME_LENGTH = 255
_MAX_KEY_LENGTH = 100
_TIMESTAMP_RX = r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}"
_SERIES_RX = re.compile(rf"^(?P<key>[A-Za-z0-9_.+-]+)-{_TIMESTAMP_RX}(?:\.checkpoint(?:\.\d+)?)?$")
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]")
# Children of /mnt that are not views of Unraid user shares.
_NON_SHARE_ROOTS = frozenset({"user", "disks", "remotes", "addons", "rootshare"})


@dataclass
class SequenceGroup:
    """Containers stopped together and the paths archived while they are stopped."""

    key: str
    containers: List[str]
    container_ids: List[str]
    paths: List[str]


@dataclass
class SequencePlan:
    """Container groups plus the paths left for the job's main archive.

    ``main_paths`` are sources not entirely covered by a group and
    ``main_excludes`` the group paths below them. ``idle_containers`` have no
    writable path inside the sources and keep running. ``skipped_paths`` holds
    ``(container, path, reason)`` for excluded or missing container paths.
    """

    groups: List[SequenceGroup] = field(default_factory=list)
    main_paths: List[str] = field(default_factory=list)
    main_excludes: List[str] = field(default_factory=list)
    idle_containers: List[str] = field(default_factory=list)
    skipped_paths: List[Tuple[str, str, str]] = field(default_factory=list)


def canonical_share_path(path: object) -> str:
    """Return a normalized path in which Unraid share views compare equal.

    ``/mnt/cache/appdata/x``, ``/mnt/disk1/appdata/x`` and
    ``/mnt/user0/appdata/x`` expose the same user-share files as
    ``/mnt/user/appdata/x``. Other paths are only normalized.
    """
    normalized = posixpath.normpath(str(path))
    parts = normalized.split("/")
    if len(parts) >= 3 and parts[0] == "" and parts[1] == "mnt" and parts[2] and parts[2] not in _NON_SHARE_ROOTS:
        return posixpath.join("/mnt/user", *parts[3:])
    return normalized


def _within(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent.rstrip("/") + "/")


def plan_sequence(
    source_paths: Iterable[object],
    targets: Sequence[Tuple[str, str]],
    writable_mounts: Mapping[str, Sequence[str]],
    exclude_paths: Iterable[object] = (),
    path_exists: Callable[[str], bool] = os.path.lexists,
) -> SequencePlan:
    """Group target containers by the job paths they can write.

    ``targets`` are ``(name, id)`` pairs in processing order and
    ``writable_mounts`` maps container names to writable bind-mount host
    paths. A mount inside a source contributes the mount path; a mount that
    contains a source contributes the whole source. Paths keep the job's
    source spelling. Excluded or missing paths are skipped. Containers with
    equal or nested paths share one group, ordered by their first member.
    """
    sources: List[Tuple[str, str]] = []
    for raw in source_paths:
        original = posixpath.normpath(str(raw))
        sources.append((original, canonical_share_path(original)))
    excludes = [canonical_share_path(path) for path in exclude_paths]
    plan = SequencePlan()
    skipped: Dict[Tuple[str, str, str], None] = {}

    # Target index -> canonical path -> path in the job's source spelling.
    claims: Dict[int, Dict[str, str]] = {}
    for index, (name, _container_id) in enumerate(targets):
        for mount in writable_mounts.get(name) or ():
            mount_canonical = canonical_share_path(mount)
            for original, canonical in sources:
                if _within(mount_canonical, canonical):
                    relative = posixpath.relpath(mount_canonical, canonical)
                    path = original if relative == "." else posixpath.join(original, relative)
                    path_canonical = mount_canonical
                elif _within(canonical, mount_canonical):
                    path, path_canonical = original, canonical
                else:
                    continue
                if any(_within(path_canonical, excluded) for excluded in excludes):
                    skipped[(name, path, "excluded")] = None
                elif not path_exists(path):
                    skipped[(name, path, "missing")] = None
                else:
                    claims.setdefault(index, {}).setdefault(path_canonical, path)
    plan.skipped_paths = list(skipped)

    parent = {index: index for index in claims}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    indexes = sorted(claims)
    for position, left in enumerate(indexes):
        for right in indexes[position + 1:]:
            if any(_within(a, b) or _within(b, a) for a in claims[left] for b in claims[right]):
                left_root, right_root = find(left), find(right)
                # The smallest index stays the root, so groups keep target order.
                parent[max(left_root, right_root)] = min(left_root, right_root)

    members: Dict[int, List[int]] = {}
    for index in indexes:
        members.setdefault(find(index), []).append(index)
    covered: List[str] = []
    for root in sorted(members):
        paths: Dict[str, str] = {}
        for index in members[root]:
            for canonical, path in claims[index].items():
                paths.setdefault(canonical, path)
        outermost = sorted(
            canonical for canonical in paths
            if not any(other != canonical and _within(canonical, other) for other in paths)
        )
        names = [targets[index][0] for index in members[root]]
        plan.groups.append(SequenceGroup(
            key=series_key(names),
            containers=names,
            container_ids=[targets[index][1] for index in members[root]],
            paths=[paths[canonical] for canonical in outermost],
        ))
        covered.extend(outermost)
    plan.idle_containers = [name for index, (name, _cid) in enumerate(targets) if index not in claims]

    main_paths: Dict[str, None] = {}
    main_excludes: Dict[str, None] = {}
    for original, canonical in sources:
        if any(_within(canonical, group_path) for group_path in covered):
            continue
        main_paths[original] = None
        for group_path in covered:
            if group_path != canonical and _within(group_path, canonical):
                main_excludes[posixpath.join(original, posixpath.relpath(group_path, canonical))] = None
    plan.main_paths = list(main_paths)
    plan.main_excludes = list(main_excludes)
    return plan


def series_key(container_names: Iterable[str]) -> str:
    """Return the stable archive series key of a container group.

    Names are sorted and joined with ``+``, which Docker names cannot contain.
    Keys longer than 100 characters keep the first name, the number of further
    containers and a digest of the full key.
    """
    names = sorted(
        {_UNSAFE_NAME_CHARS.sub("_", str(name).strip().lstrip("/")) for name in container_names if str(name).strip()},
        key=lambda name: (name.casefold(), name),
    )
    key = "+".join(names) or "containers"
    if len(key) > _MAX_KEY_LENGTH:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
        key = f"{names[0][:60]}+{len(names) - 1}-{digest}"
    return key


def archive_name(prefix: str, key: str, timestamp: str) -> str:
    """Return one group archive name; raise ValueError above Borg's length limit."""
    name = f"{prefix}{ARCHIVE_SEPARATOR}{key}-{timestamp}"
    if len(name) > MAX_ARCHIVE_NAME_LENGTH:
        raise ValueError(
            f"Container archive name exceeds {MAX_ARCHIVE_NAME_LENGTH} characters; shorten the archive prefix"
        )
    return name


def archive_glob(prefix: str) -> str:
    """Return the Borg glob that matches every container archive of a prefix."""
    return f"{prefix}{ARCHIVE_SEPARATOR}*"


def series_keys(prefix: str, archive_names: Iterable[str]) -> List[str]:
    """Return the sorted series keys found in ``<prefix>@<key>-<timestamp>`` names.

    Checkpoint archives belong to their series. Names that do not follow the
    scheme are ignored, so they are never pruned.
    """
    start = f"{prefix}{ARCHIVE_SEPARATOR}"
    keys = set()
    for name in archive_names:
        text = str(name or "").strip()
        if not text.startswith(start):
            continue
        match = _SERIES_RX.fullmatch(text[len(start):])
        if match:
            keys.add(match.group("key"))
    return sorted(keys)


def series_glob(prefix: str, key: str, known_keys: Optional[Iterable[str]] = None) -> str:
    """Return the Borg glob that selects exactly one series including checkpoints.

    The trailing ``*`` also selects ``.checkpoint`` archives. If another known
    key starts with ``<key>-<timestamp>``, the glob stays exact so the other
    series can never be pruned with this one.
    """
    exact = f"{prefix}{ARCHIVE_SEPARATOR}{key}-{TIMESTAMP_GLOB}"
    shadowed = re.compile(rf"^{re.escape(key)}-{_TIMESTAMP_RX}")
    if any(other != key and shadowed.match(other) for other in (known_keys or ())):
        return exact
    return exact + "*"
