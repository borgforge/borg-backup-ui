"""One retention policy over an explicit union of archive prefixes (#475).

Borg 1.4 shell globs cannot express arbitrary prefix unions. Select one keep
set using its calendar rules, then pass only the exact discard names to a
single Borg delete command. Never invoke repository deletion or prune once per
prefix. Caller holds the plugin repository/inventory locks for this operation.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)
PERIODS = {"daily": "%Y-%m-%d", "weekly": "%G-%V", "monthly": "%Y-%m", "yearly": "%Y"}
_PREFIX = re.compile(r"[A-Za-z0-9_.-]+")
_CHECKPOINT = re.compile(r"\.checkpoint(?:\.\d+)?$")


@dataclass(frozen=True)
class Archive:
    name: str
    id: str
    timestamp: datetime


def validate_scope(prefixes, policy):
    if not isinstance(prefixes, list) or not prefixes or any(not isinstance(p, str) for p in prefixes):
        raise ValueError("An explicit nonempty prefix scope is required")
    if len(set(prefixes)) != len(prefixes) or any(not _PREFIX.fullmatch(p) or p in {".", ".."} for p in prefixes):
        raise ValueError("Invalid archive prefix")
    if set(policy) != set(PERIODS) or any(type(v) is not int or v < 0 for v in policy.values()) or not any(policy.values()):
        raise ValueError("Retention requires non-negative counts and at least one positive count")


def parse_archives(payload):
    """Read explicit timestamps or naive timestamps from a UTC Borg inventory."""
    rows = payload.get("archives") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Borg did not return an archive inventory")
    archives, names, ids = [], set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid archive inventory")
        name, archive_id = row.get("name", row.get("archive")), row.get("id")
        if (not isinstance(name, str) or not name or any(c in name for c in ("\x00", "\n", "\r"))
                or not isinstance(archive_id, str) or not re.fullmatch(r"[0-9a-f]{64}", archive_id)
                or name in names or archive_id in ids):
            raise ValueError("Invalid or ambiguous archive identity")
        raw_time = row.get("time", row.get("start"))
        if not isinstance(raw_time, str):
            raise ValueError("Archive timestamp is missing")
        timestamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        archives.append(Archive(name, archive_id, timestamp))
        names.add(name)
        ids.add(archive_id)
    return archives


def plan_retention(archives, prefixes, policy):
    """Match Borg 1.4 calendar buckets, oldest fallback and checkpoint handling."""
    keep, discard, _ = _plan_retention(archives, prefixes, policy)
    return keep, discard


def _plan_retention(archives, prefixes, policy):
    """Select archives and retain the first rule that keeps each archive."""
    validate_scope(prefixes, policy)
    selected = sorted((a for a in archives if any(a.name.startswith(p + "-") for p in prefixes)),
                      key=lambda a: a.timestamp)
    # Borg sorts ascending and then reverses, including equal-time entries.
    selected.reverse()
    complete = [a for a in selected if not _CHECKPOINT.search(a.name)]
    kept, reasons = set(), {}
    if selected and _CHECKPOINT.search(selected[0].name):
        kept.add(selected[0].id)
        reasons[selected[0].id] = "latest checkpoint"
    for period, pattern in PERIODS.items():
        count = policy[period]
        if not count:
            continue
        previous, added = None, 0
        for archive in complete:
            bucket = archive.timestamp.astimezone().strftime(pattern)
            if bucket == previous:
                continue
            previous = bucket
            if archive.id in kept:
                continue
            kept.add(archive.id)
            added += 1
            reasons[archive.id] = f"{period} #{added}"
            if added == count:
                break
        if complete and added < count:
            if complete[-1].id not in kept:
                reasons[complete[-1].id] = f"{period}[oldest] #{added + 1}"
            kept.add(complete[-1].id)
    return ([a for a in selected if a.id in kept], [a for a in selected if a.id not in kept], reasons)


def _archive_counts(archives):
    checkpoints = sum(bool(_CHECKPOINT.search(a.name)) for a in archives)
    return len(archives) - checkpoints, checkpoints


def _log_retention_plan(archives, keep, discard, reasons):
    """Log planned decisions without claiming an archive was already deleted."""
    logger.info("Repository contains %d normal archives and %d checkpoint archives.", *_archive_counts(archives))
    logger.info("Applying rules to the matching %d archives and %d checkpoints...", *_archive_counts(keep + discard))
    logger.info("Keeping %d archives and %d checkpoints, pruning %d archives and %d checkpoints.",
                *_archive_counts(keep), *_archive_counts(discard))
    removed = 0
    for archive in sorted(keep + discard, key=lambda a: a.timestamp, reverse=True):
        timestamp = archive.timestamp.astimezone().strftime("%a, %Y-%m-%d %H:%M:%S %z")
        if archive.id in reasons:
            logger.info("Keeping archive (rule: %s): %s %s [%s]",
                        reasons[archive.id], archive.name, timestamp, archive.id)
        else:
            removed += 1
            logger.info("Selected for pruning (%d/%d): %s %s [%s]",
                        removed, len(discard), archive.name, timestamp, archive.id)


def prune_union(repo, prefixes, policy, *, process_controller=None, before_delete=None):
    """Abort on failed/changed inventories; delete exact archive names once."""
    from .borg_runner import _run_borg
    validate_scope(prefixes, policy)
    if not repo or "::" in repo:
        raise ValueError("An explicit repository location is required")
    logger.info("Borg prune: applying combined retention only to archives matching %s (keep: %dd/%dw/%dm/%dy)",
                ", ".join(p + "-*" for p in prefixes), *(policy[period] for period in PERIODS))

    def inventory():
        command = ["borg", "list", "--lock-wait", "30", "--json", "--consider-checkpoints", "--", repo]
        # Borg 1.4 JSON timestamps are naive local times. Request UTC so parsing
        # is unambiguous, then apply calendar rules in the caller's local zone.
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=None, text=True,
                                   env={**os.environ, "TZ": "UTC"})
        if process_controller:
            process_controller.attach_process(process)
        try:
            output, _ = process.communicate()
        finally:
            if process_controller:
                process_controller.detach_process()
        if process.returncode != 0:
            raise ValueError("Borg archive inventory failed; retention was not applied")
        return parse_archives(json.loads(output))

    first = inventory()
    keep, discard, reasons = _plan_retention(first, prefixes, policy)
    _log_retention_plan(first, keep, discard, reasons)
    if process_controller and process_controller.is_cancel_requested():
        logger.warning("Borg prune cancelled before deletion (exit 130)")
        return 130
    if not discard:
        logger.info("Borg prune succeeded (exit 0): no archives selected for removal")
        return 0
    command = ["borg", "delete", "--lock-wait", "30", "--list", "--show-rc", "--", repo, *[a.name for a in discard]]
    # One Borg invocation owns its repository lock for the entire deletion.
    # An oversized selection is an explicit failure, never an empty/broad call.
    if sum(len(arg.encode()) + 1 for arg in command) > 100_000:
        raise ValueError("Retention selection exceeds the safe command size")
    if inventory() != first:
        raise ValueError("Repository archives changed while planning retention; retry later")
    if process_controller and process_controller.is_cancel_requested():
        logger.warning("Borg prune cancelled before deletion (exit 130)")
        return 130
    if before_delete and not before_delete():
        raise ValueError("Job repository ownership changed; retention was not applied")
    exit_code = _run_borg(command, process_controller)
    if exit_code == 0:
        logger.info("Borg prune succeeded (exit 0)")
    elif exit_code == 1:
        logger.warning("Borg prune completed with warnings (exit 1)")
    else:
        logger.error("Borg prune failed (exit %d)", exit_code)
    return exit_code
