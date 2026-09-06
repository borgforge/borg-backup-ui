"""Manual maintenance uses the same frozen union policy as a backup (#475)."""

import logging
from pathlib import Path
import sys

from inventory_store import inventory_lock
from job_runs import read_run_context, descriptors, maintenance_context_unchanged
from jobs_api import resolve_resource_lock_dir
from wizard_runner import ResourceLockSet, _ensure_runtime_import_paths


def main(job_id, run_id, data_root):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    snapshot = read_run_context(job_id, run_id)
    _ensure_runtime_import_paths(Path(data_root))
    from lib.retention import prune_union
    config = {"BACKUP_SCRIPTS_DIR": data_root}
    locks = ResourceLockSet(resolve_resource_lock_dir(config), job_id, run_id=run_id,
                            operation="maintenance", snapshot=descriptors(snapshot))
    acquired, reason = locks.acquire(["repo:" + snapshot["repository_snapshot"]])
    if not acquired:
        logging.error("Retention not started: %s", reason)
        return 2
    try:
        with inventory_lock(Path(data_root) / "config"):
            if not maintenance_context_unchanged(config, snapshot):
                raise ValueError("The repository assignment changed; start maintenance again")
            policy = {period: int(snapshot["context"]["job"]["retention"][period])
                      for period in ("daily", "weekly", "monthly", "yearly")}
            return prune_union(snapshot["repository_snapshot"], snapshot["archive_prefixes_snapshot"], policy,
                               before_delete=lambda: maintenance_context_unchanged(config, snapshot))
    except (ValueError, OSError, TypeError) as exc:
        logging.error("Retention stopped: %s", exc)
        return 2
    finally:
        locks.release()


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
