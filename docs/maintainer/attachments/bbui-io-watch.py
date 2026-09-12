#!/usr/bin/env python3
"""Temporary Linux file-event diagnostic; no plugin imports or file-content reads.

Outputs JSONL to stdout. Redirect/tee outside the watched trees (on Unraid: /tmp).
READ is an observed file-access event; WRITE_CLOSE only means a writable handle
was closed. Event counts are not byte counts or physical device I/O counts.
Directory discovery reads metadata once; directory-access events are omitted.
"""
import argparse
from collections import Counter
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import select
import signal
import struct
import sys
import time


EVENTS = {
    0x0001: "READ", 0x0002: "WRITE", 0x0004: "METADATA",
    0x0008: "WRITE_CLOSE", 0x0040: "MOVE_FROM", 0x0080: "MOVE_TO",
    0x0100: "CREATE", 0x0200: "DELETE", 0x0400: "WATCH_DELETED",
    0x0800: "WATCH_MOVED", 0x2000: "UNMOUNT",
}
ISDIR, IGNORED, OVERFLOW = 0x40000000, 0x8000, 0x4000
HEADER = struct.Struct("iIII")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, help="Measurement label, e.g. idle or ui")
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--data-root", help="Actual plugin GLOBAL_DATA_DIR; no automatic mount or directory creation")
    parser.add_argument("--root", action="append", help="Override default flash roots; recursively watch this path")
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be positive")
    if not sys.platform.startswith("linux"):
        parser.error("Linux is required")

    def emit(kind, **fields):
        print(json.dumps({"time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                          "phase": args.phase, "kind": kind, **fields}, ensure_ascii=True), flush=True)

    libc = ctypes.CDLL(None, use_errno=True)
    libc.inotify_init1.argtypes = [ctypes.c_int]
    libc.inotify_init1.restype = ctypes.c_int
    libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    libc.inotify_add_watch.restype = ctypes.c_int
    fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "inotify_init1 failed")
    watches, counters, read_batch = {}, Counter(), Counter()
    incomplete = False
    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    def warn(message, **details):
        nonlocal incomplete
        incomplete = True
        emit("warning", message=message, **details)

    mask = sum(EVENTS) | 0x01000000 | 0x02000000  # ONLYDIR, DONT_FOLLOW

    def watch_tree(raw, recursive):
        path = Path(os.path.abspath(raw))
        if path.is_symlink() or not path.is_dir():
            warn("Directory missing or symlink; not monitored", path=str(path))
            return
        wd = libc.inotify_add_watch(fd, os.fsencode(path), mask)
        if wd < 0:
            warn("Cannot add directory watch", path=str(path), errno=ctypes.get_errno())
            return
        previous = watches.get(wd)
        if previous:
            recursive = recursive or previous[1]
        watches[wd] = (path, recursive)
        if recursive:
            try:
                with os.scandir(path) as children:
                    subdirs = [entry.path for entry in children if entry.is_dir(follow_symlinks=False)]
                for child in subdirs:
                    watch_tree(child, True)
            except OSError as exc:
                warn("Cannot enumerate directory", path=str(path), errno=exc.errno)

    def flush_reads():
        for path, count in sorted(read_batch.items()):
            emit("reads", path=path, events=count)
        read_batch.clear()

    try:
        roots = args.root or ["/boot/config/borg-backup", "/boot/config/plugins/borg-backup-ui"]
        for root in roots:
            watch_tree(root, True)
        if args.data_root:
            base = Path(args.data_root)
            # Include root-level stores, but do not recurse into Borg caches or mounted repositories.
            watch_tree(base, False)
            for child in ("logs", "status", "restore-status"):
                watch_tree(base / child, True)
        if not watches:
            emit("error", message="No directories could be watched")
            return 1
        emit("ready", directories=len(watches), seconds=args.seconds,
             note="Only paths/events are recorded. Read events are grouped every 10 seconds; no process attribution or physical I/O measurement.")
        start = last_reads = time.monotonic()
        while not stopped and time.monotonic() - start < args.seconds:
            ready, _, _ = select.select([fd], [], [], min(1.0, max(0, args.seconds - (time.monotonic() - start))))
            if ready:
                raw = os.read(fd, 1024 * 1024)
                offset = 0
                while offset + HEADER.size <= len(raw):
                    wd, event_mask, cookie, length = HEADER.unpack_from(raw, offset)
                    offset += HEADER.size
                    name = os.fsdecode(raw[offset:offset + length].split(b"\0", 1)[0])
                    offset += length
                    if event_mask & OVERFLOW:
                        warn("Kernel event queue overflow; measurement has gaps")
                        continue
                    watched = watches.get(wd)
                    if watched is None:
                        continue
                    parent, recursive = watched
                    path = str(parent / name) if name else str(parent)
                    actions = [label for bit, label in EVENTS.items() if event_mask & bit]
                    if event_mask & ISDIR:
                        actions = [label for label in actions if label != "READ"]
                    if "READ" in actions:
                        read_batch[path] += 1
                    for action in actions:
                        counters[(path, action)] += 1
                    mutations = [action for action in actions if action != "READ"]
                    if mutations:
                        emit("event", path=path, events=mutations, cookie=cookie)
                    if event_mask & ISDIR and event_mask & (0x0100 | 0x0080) and recursive:
                        watch_tree(path, True)
                    if event_mask & (0x0800 | 0x2000):
                        warn("Watched directory moved or unmounted; restart measurement", path=path)
                        stopped = True
                    if event_mask & IGNORED:
                        watches.pop(wd, None)
            if time.monotonic() - last_reads >= 10:
                flush_reads()
                last_reads = time.monotonic()
        flush_reads()
        totals = {}
        for (path, action), count in sorted(counters.items()):
            totals.setdefault(path, {})[action] = count
        for path, counts in totals.items():
            emit("summary", path=path, events=counts)
        emit("finished", elapsed_seconds=round(time.monotonic() - start, 1),
             incomplete=incomplete, observed_events=sum(counters.values()))
        return 1 if incomplete else 0
    finally:
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
