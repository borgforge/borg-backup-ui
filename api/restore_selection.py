"""Literal archive selections and deterministic destination planning (#521)."""

import os
from pathlib import Path, PurePosixPath

MAX_SELECTIONS = 256


def normalize_paths(source_path, source_paths=None):
    """Validate and deduplicate one to 256 literal archive paths.

    ``source_paths`` takes precedence over ``source_path`` when supplied.
    Raises ValueError for invalid count, type or path segments.
    """
    values = [source_path] if source_paths is None else source_paths
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_SELECTIONS:
        raise ValueError(f"Select between 1 and {MAX_SELECTIONS} files or folders")
    paths = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Invalid archive path")
        path = value.strip("/")
        if not path or any(c in path for c in ("\x00", "\n", "\r")) or any(p in {"", ".", ".."} for p in path.split("/")):
            raise ValueError("Invalid archive path")
        if path not in paths:
            paths.append(path)
    return paths


def selected_entries(repo, archive, env, paths):
    """Resolve selected paths against a Borg archive and remove covered descendants.

    Returns path/type records. Raises ValueError when a selected path is absent;
    archive indexing may also fail if Borg cannot read the archive.
    """
    from archive_browser import build_archive_index
    index = build_archive_index(repo, archive, env)
    entries = []
    for path in paths:
        p = PurePosixPath(path)
        parent = str(p.parent) if str(p.parent) != "." else ""
        entry = index.get(parent, {}).get(p.name)
        if entry is None:
            raise ValueError(f"Selected path is missing from the archive: {path}")
        entries.append({"path": path, "type": entry["type"]})
    # A selected directory already includes its descendants, regardless of order.
    return [e for e in entries if not any(
        parent["type"] == "d" and e["path"].startswith(parent["path"] + "/")
        for parent in entries if parent is not e
    )]


def destination_plan(entries, target, mode):
    """Map archive entries beneath ``target`` while preserving their relative layout.

    A single directory matching the target name restores its contents directly.
    Returns planned items, the shared parent and Borg strip count; ``skip`` mode
    marks existing destinations. Raises ValueError for unsafe symlink or
    non-directory destination components.
    """
    parents = [str(PurePosixPath(e["path"]).parent) for e in entries]
    common = os.path.commonpath(parents)
    common = "" if common == "." else common
    strip = len(PurePosixPath(common).parts)
    direct = len(entries) == 1 and entries[0]["type"] == "d" and PurePosixPath(entries[0]["path"]).name == target.name
    if direct:
        strip += 1
    items = []
    for entry in entries:
        relative = "/".join(entry["path"].split("/")[strip:])
        dest = target / relative
        # Reject symlinks in destination components: do not merge into another
        # selected directory or escape the target through an existing link.
        current = target
        for part in Path(relative).parts:
            current /= part
            if current.is_symlink():
                if not current.resolve().is_relative_to(target):
                    raise ValueError("Restore destination is outside the target directory")
                raise ValueError("Restore destination is a symbolic link; choose another target directory")
            if current != dest and current.exists() and not current.is_dir():
                raise ValueError("Restore destination parent is not a directory")
        exists = dest.exists()
        skip = mode == "skip" and (any(target.iterdir()) if direct else exists)
        items.append({**entry, "relative_path": relative, "destination_path": str(dest),
                      "destination_exists": exists, "skipped": skip, "direct_contents": direct})
    return {"items": items, "strip_components": strip, "common_parent": common}
