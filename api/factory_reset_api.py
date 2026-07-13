"""Guarded factory-reset planning and scheduling.

The HTTP process validates the destructive request and writes a protected
one-shot marker. A detached worker performs the reset after the response has
been returned and restarts the service.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RESET_PHRASE = "FACTORY RESET"
RESET_ACK_KEYS = (
    "ack_configuration",
    "ack_operational_data",
    "ack_secrets",
    "ack_repositories_preserved",
)


class FactoryResetBlocked(RuntimeError):
    """The reset cannot run while protected resources are active or covered."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _data_root(config: dict) -> Path:
    return Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")


def _configured_operational_root(config: dict) -> Path | None:
    try:
        from config_api import read_expanded_conf

        raw = str(read_expanded_conf(config).get("GLOBAL_DATA_DIR") or "").strip()
    except Exception:
        raw = str(config.get("GLOBAL_DATA_DIR") or "").strip()
    return Path(raw) if raw else None


def _validate_operational_root(path: Path | None) -> None:
    if path is None:
        return
    resolved = path.resolve(strict=False)
    blocked = {
        Path("/"),
        Path("/mnt"),
        Path("/mnt/user"),
        Path("/mnt/cache"),
        Path("/mnt/disks"),
        Path("/mnt/remotes"),
    }
    if (
        resolved in blocked
        or not str(resolved).startswith("/mnt/")
        or len(resolved.parts) < 4
    ):
        raise FactoryResetBlocked(
            "The configured operational data directory is too broad for a safe factory reset"
        )


def _inside(candidate: str | Path, root: Path) -> bool:
    raw = str(candidate or "").strip()
    if not raw.startswith("/"):
        return False
    try:
        item = Path(raw).resolve(strict=False)
        base = root.resolve(strict=False)
    except OSError:
        return False
    return item == base or base in item.parents


def _repository_blockers(config: dict, roots: list[Path]) -> list[dict[str, str]]:
    try:
        from repositories_api import effective_repository_path, read_repository_store
        from storage_objects_api import read_storage_store

        storages = {
            str(row.get("storage_key") or ""): row
            for row in read_storage_store(config).get("storages", [])
            if isinstance(row, dict)
        }
        rows = read_repository_store(config).get("repositories", [])
    except Exception as exc:
        raise FactoryResetBlocked(f"Repository inventory cannot be verified: {exc}") from exc

    blockers: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        storage = storages.get(str(row.get("storage_key") or ""), {})
        path = effective_repository_path(storage, str(row.get("relative_path") or ""))
        if not path or not any(_inside(path, root) for root in roots):
            continue
        blockers.append({
            "repository_key": str(row.get("repository_key") or ""),
            "display_name": str(row.get("display_name") or row.get("repository_name") or "Repository"),
            "path": path,
        })
    return blockers


def _active_operation_blockers(config: dict) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    try:
        from jobs_api import JobManager, active_resource_locks

        locked_jobs: set[str] = set()
        for row in active_resource_locks(config):
            job_key = str(row.get("job_key") or "Backup job")
            locked_jobs.add(job_key)
            blockers.append({
                "type": "backup",
                "name": job_key,
            })
        for key, state in JobManager.get().get_all_states().items():
            if key == "restore_test" or key in locked_jobs:
                continue
            if isinstance(state, dict) and state.get("running"):
                blockers.append({"type": "backup", "name": str(key)})
        restore_test = JobManager.get().get_state("restore_test")
        if restore_test.get("running"):
            blockers.append({"type": "restore_test", "name": "restore_test"})
    except Exception as exc:
        raise FactoryResetBlocked(f"Running backup operations cannot be verified: {exc}") from exc

    try:
        from check_api import CheckManager

        state = CheckManager.get().get_state()
        if state.get("running"):
            blockers.append({
                "type": "repository_maintenance",
                "name": str(state.get("target_key") or state.get("action") or "maintenance"),
            })
    except Exception as exc:
        raise FactoryResetBlocked(f"Repository maintenance state cannot be verified: {exc}") from exc

    try:
        from restore_api import list_restore_runs

        for row in list_restore_runs(config, 100).get("active", []):
            blockers.append({
                "type": "restore",
                "name": str(row.get("restore_id") or row.get("job_key") or "restore"),
            })
    except Exception as exc:
        raise FactoryResetBlocked(f"Restore state cannot be verified: {exc}") from exc

    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in blockers:
        key = (row["type"], row["name"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def factory_reset_status(config: dict) -> dict[str, Any]:
    root = _data_root(config)
    operational = _configured_operational_root(config)
    _validate_operational_root(operational)
    roots = [root]
    if operational is not None and operational.resolve(strict=False) != root.resolve(strict=False):
        roots.append(operational)
    repository_blockers = _repository_blockers(config, roots)
    operation_blockers = _active_operation_blockers(config)
    return {
        "ok": True,
        "server_name": socket.gethostname(),
        "configuration_root": str(root),
        "operational_data_root": str(operational or ""),
        "repository_blockers": repository_blockers,
        "operation_blockers": operation_blockers,
        "allowed": not repository_blockers and not operation_blockers,
        "confirmation_phrase": RESET_PHRASE,
    }


def validate_factory_reset_request(config: dict, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid factory reset request")
    status = factory_reset_status(config)
    if status["repository_blockers"]:
        names = ", ".join(row["display_name"] for row in status["repository_blockers"][:5])
        raise FactoryResetBlocked(
            "Factory reset is blocked because managed Borg repositories are located inside a deletion root: " + names
        )
    if status["operation_blockers"]:
        names = ", ".join(row["name"] for row in status["operation_blockers"][:5])
        raise FactoryResetBlocked("Factory reset is blocked while operations are running: " + names)
    missing = [key for key in RESET_ACK_KEYS if payload.get(key) is not True]
    if missing:
        raise ValueError("All factory reset risk confirmations are required")
    if str(payload.get("server_name") or "").strip() != status["server_name"]:
        raise ValueError("The server name confirmation does not match")
    if str(payload.get("confirmation_phrase") or "").strip() != RESET_PHRASE:
        raise ValueError(f'Type "{RESET_PHRASE}" to confirm the factory reset')
    return status


def schedule_factory_reset(
    config: dict,
    status: dict[str, Any],
    *,
    actor: str,
    request_id: str,
    script_dir: Path,
) -> dict[str, Any]:
    plugin_dir = Path(script_dir)
    worker = plugin_dir / "api" / "factory_reset_worker.py"
    if not worker.is_file():
        raise FileNotFoundError("Factory reset worker is missing")
    marker = plugin_dir / "factory-reset.pending.json"
    if marker.exists():
        raise FactoryResetBlocked("A factory reset is already pending")
    audit = plugin_dir / "factory-reset.log.jsonl"
    record = {
        "schema_version": 1,
        "requested_at": _now(),
        "actor": str(actor or "admin"),
        "request_id": str(request_id or ""),
        "configuration_root": str(status.get("configuration_root") or ""),
        "operational_data_root": str(status.get("operational_data_root") or ""),
        "plugin_dir": str(plugin_dir),
        "audit_file": str(audit),
        "rc_script": "/etc/rc.d/rc.borg_backup_ui",
    }
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise FactoryResetBlocked("A factory reset is already pending") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        marker.unlink(missing_ok=True)
        raise
    try:
        log_handle = open("/var/log/borg_backup_ui.log", "a", encoding="utf-8")
    except Exception:
        marker.unlink(missing_ok=True)
        raise
    try:
        try:
            subprocess.Popen(
                [sys.executable, str(worker), str(marker)],
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except Exception:
            marker.unlink(missing_ok=True)
            raise
    finally:
        log_handle.close()
    return {
        "ok": True,
        "scheduled": True,
        "message": "Factory reset scheduled. The service will restart with the administrator setup page.",
    }
