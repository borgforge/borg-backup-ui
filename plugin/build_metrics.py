#!/usr/bin/env python3
"""Run a build step and append timings without recording arguments or secrets."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import time


def measure(output: Path, step: str, command: list[str]) -> int:
    """Run a command, append a JSONL result even on failure, return its exit code.

    stdout/stderr pass through. CPU and peak RSS describe child processes; RSS
    units are KiB on the supported Linux build host. No environment is recorded.
    """
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic()
    code = 127
    try:
        code = subprocess.run(command, check=False).returncode
        return code
    finally:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        output.parent.mkdir(parents=True, exist_ok=True)
        row = dict(step=step, seconds=round(time.monotonic() - start, 4),
                   exit_code=code, user_seconds=after.ru_utime - before.ru_utime,
                   system_seconds=after.ru_stime - before.ru_stime,
                   maxrss_kib=after.ru_maxrss)
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--step", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("A command is required")
    raise SystemExit(measure(args.output, args.step, command))
