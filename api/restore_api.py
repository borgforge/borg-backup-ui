"""api/restore_api.py – Browse & Restore: Borg Archive Browser"""

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from restore_selection import normalize_paths, selected_entries, destination_plan

from archive_prefix import (
    archive_prefix_from_backup_type,
    archive_prefix_from_job_key,
    normalize_archive_prefixes,
)

_RESTORE_RUNS: dict = {}
_RESTORE_LOCK = threading.Lock()
_RESTORE_KEEP = 20
_RESTORE_RUNS_LOADED = False

_JOB_KEY_RX = re.compile(r"^[a-zA-Z0-9_.-]+$")
_ARCHIVE_RX = re.compile(r"^[a-zA-Z0-9_.:-]+$")


class RestoreRepositoryBusy(ValueError):
    def __init__(self, message: str, *, holder: str = "", resource: str = "") -> None:
        super().__init__(message)
        self.api_status = 409
        self.api_code = "repository_busy"
        self.api_message_params = {
            "holder": holder,
            "resource": resource,
        }


def _validate_job_key(job_key: str) -> str:
    key = str(job_key or "").strip()
    if not _JOB_KEY_RX.fullmatch(key):
        raise ValueError("Invalid job key")
    return key


def _validate_archive_name(archive: str) -> str:
    name = str(archive or "").strip()
    if not name:
        raise ValueError("archive is missing")
    if "::" in name:
        raise ValueError("Invalid archive name")
    if not _ARCHIVE_RX.fullmatch(name):
        raise ValueError("Invalid archive name")
    return name


def _get_restore_allowed_roots(config: dict) -> list[Path]:
    """
    Liest RESTORE_ALLOWED_ROOTS aus backup.conf.
    Format: komma-separierte absolute Pfade, Default /mnt/user.
    """
    try:
        from config_api import read_expanded_conf
        conf = read_expanded_conf(config)
        raw = str(conf.get("RESTORE_ALLOWED_ROOTS", "/mnt/user") or "/mnt/user").strip()
    except Exception:
        raw = "/mnt/user"

    roots: list[Path] = []
    for item in raw.split(","):
        val = str(item or "").strip()
        if not val:
            continue
        p = Path(val)
        if not p.is_absolute():
            continue
        if not _is_safe_restore_root_text(p.as_posix()):
            continue
        try:
            roots.append(p.resolve())
        except OSError:
            continue
    if not roots:
        try:
            roots = [Path("/mnt/user").resolve()]
        except OSError:
            roots = [Path("/mnt/user")]
    return roots


def _is_safe_restore_root_text(raw: str) -> bool:
    path = str(raw or "").strip().rstrip("/") or "/"
    if path in {"/", "/mnt", "/mnt/disks", "/mnt/remotes", "/boot", "/etc", "/usr", "/var"}:
        return False
    if path == "/mnt/user" or path.startswith("/mnt/user/"):
        return True
    if path == "/mnt/data" or path.startswith("/mnt/data/"):
        return True
    if re.fullmatch(r"/mnt/disk[0-9]+(?:/.*)?", path):
        return True
    if re.fullmatch(r"/mnt/disks/[^/]+(?:/.*)?", path):
        return True
    if re.fullmatch(r"/mnt/remotes/[^/]+(?:/.*)?", path):
        return True
    return False


def list_allowed_target_roots(config: dict) -> list[str]:
    roots = _get_restore_allowed_roots(config)
    out: list[str] = []
    seen: set[str] = set()
    for root in roots:
        text = root.as_posix().rstrip("/") or "/"
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out or ["/mnt/user"]


def _is_under_allowed_roots(path: Path, roots: list[Path]) -> bool:
    try:
        rp = path.resolve()
    except OSError:
        return False
    for root in roots:
        base = str(root)
        full = str(rp)
        if full == base or full.startswith(base.rstrip("/") + "/"):
            return True
    return False


def _resolved_inside(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        resolved_root = root.resolve()
    except OSError:
        return False
    full = str(resolved)
    base = str(resolved_root)
    return full == base or full.startswith(base.rstrip("/") + "/")


def _ensure_restore_path_inside(path: Path, root: Path, *, allow_missing: bool = True) -> Path:
    """Validate a restore path immediately before filesystem mutation."""
    if allow_missing and not path.exists() and not path.is_symlink():
        parent = path.parent
        if not parent.exists():
            raise ValueError("Restore destination parent does not exist")
        if not _resolved_inside(parent, root):
            raise ValueError("Restore destination parent is outside the target directory")
        return path
    if not _resolved_inside(path, root):
        raise ValueError("Restore destination is outside the target directory")
    return path


def _make_restore_stage_dir(target: Path) -> Path:
    """Create an exclusive staging directory inside the validated restore target."""
    for _ in range(10):
        stage = target / f".bbui-restore-stage-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        _ensure_restore_path_inside(stage, target)
        try:
            stage.mkdir(mode=0o700, parents=False, exist_ok=False)
            return stage
        except FileExistsError:
            continue
    raise RuntimeError("Could not create an exclusive restore staging directory")


def _restore_runs_file(config: dict) -> Path:
    base = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    return base / "config" / "restore-runs.json"


def _restore_history_dir(config: dict) -> Path:
    base = Path(str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup")
    return base / "config" / "restore-history"


def _restore_history_index_file(config: dict) -> Path:
    return _restore_history_dir(config) / "index.json"


def _restore_history_runs_dir(config: dict) -> Path:
    return _restore_history_dir(config) / "runs"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _persist_restore_runs(config: dict) -> None:
    fp = _restore_runs_file(config)
    active_runs = {
        rid: run for rid, run in _RESTORE_RUNS.items()
        if isinstance(run, dict) and not _is_restore_terminal(run.get("state"))
    }
    payload = {
        "schema_version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "runs": active_runs,
    }
    _write_json_atomic(fp, payload)


def _is_restore_terminal(state: object) -> bool:
    return str(state or "").strip().lower() in {"done", "error", "aborted"}


def _restore_run_duration_seconds(run: dict) -> int:
    try:
        started_raw = str(run.get("started_at") or "").strip()
        finished_raw = str(run.get("finished_at") or "").strip()
        if not started_raw or not finished_raw:
            return 0
        started = datetime.fromisoformat(started_raw)
        finished = datetime.fromisoformat(finished_raw)
        return max(0, int((finished - started).total_seconds()))
    except Exception:
        return 0


def _history_summary_from_run(run: dict) -> dict:
    state = str(run.get("state") or "").strip() or "unknown"
    restore_id = str(run.get("restore_id") or "").strip()
    return {
        "restore_id": restore_id,
        "state": state,
        "phase": run.get("phase") or state,
        "started_at": run.get("started_at") or "",
        "finished_at": run.get("finished_at") or "",
        "duration_seconds": _restore_run_duration_seconds(run),
        "job_key": run.get("job_key") or "",
        "archive": run.get("archive") or "",
        "source_path": run.get("source_path") or "",
        "source_paths": run.get("source_paths") or [run.get("source_path") or ""],
        "items": run.get("items") or [],
        "target_dir": run.get("target_dir") or "",
        "destination_path": run.get("destination_path") or "",
        "conflict_mode": run.get("conflict_mode") or "",
        "preserve_owner": bool(run.get("preserve_owner", False)),
        "dry_run": bool(run.get("dry_run", False)),
        "error": run.get("error") or "",
        "skipped": bool(run.get("skipped", False)),
        "skip_reason_code": run.get("skip_reason_code") or "",
    }


def _history_detail_from_run(run: dict, source: str) -> dict:
    summary = _history_summary_from_run(run)
    return {
        "schema_version": 1,
        "source": source,
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        **summary,
        "lines": [str(line) for line in (run.get("lines") or [])][-200:],
    }


def _read_history_index(config: dict) -> list[dict]:
    fp = _restore_history_index_file(config)
    if not fp.exists():
        return []
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
        rows = raw.get("runs") if isinstance(raw, dict) else []
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    except Exception:
        return []
    return []


def _write_history_index(config: dict, rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda row: str(row.get("started_at") or ""), reverse=True)
    payload = {
        "schema_version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "retention_keep": None,
        "runs": rows,
    }
    _write_json_atomic(_restore_history_index_file(config), payload)


def _record_restore_history(config: dict, run: dict, source: str) -> None:
    restore_id = str(run.get("restore_id") or "").strip()
    if not restore_id:
        return
    detail = _history_detail_from_run(run, source)
    detail_path = _restore_history_runs_dir(config) / f"{restore_id}.json"
    _write_json_atomic(detail_path, detail)
    rows = [row for row in _read_history_index(config) if str(row.get("restore_id") or "") != restore_id]
    rows.append(_history_summary_from_run(run))
    _write_history_index(config, rows)


def _ensure_restore_runs_loaded(config: dict) -> None:
    global _RESTORE_RUNS_LOADED
    with _RESTORE_LOCK:
        if _RESTORE_RUNS_LOADED:
            return
        fp = _restore_runs_file(config)
        loaded: dict = {}
        if fp.exists():
            try:
                raw = json.loads(fp.read_text(encoding="utf-8"))
                runs = raw.get("runs") if isinstance(raw, dict) else {}
                if isinstance(runs, dict):
                    for rid, val in runs.items():
                        if isinstance(rid, str) and isinstance(val, dict):
                            loaded[rid] = val
            except Exception:
                loaded = {}

        changed = False
        now_iso = datetime.now().isoformat(timespec="seconds")
        for rid, run in loaded.items():
            if str(run.get("state", "")).strip().lower() == "running":
                run["state"] = "aborted"
                run["phase"] = "aborted"
                run["error"] = str(run.get("error") or "Server restarted during restore run")
                run["finished_at"] = str(run.get("finished_at") or now_iso)
                lines = run.get("lines")
                if not isinstance(lines, list):
                    lines = []
                lines.append("Restore was marked as aborted after the server restarted.")
                run["lines"] = lines[-200:]
                try:
                    _record_restore_history(config, run, "restore-run-restart-recovery")
                except Exception:
                    pass
                changed = True

        _RESTORE_RUNS.clear()
        _RESTORE_RUNS.update(loaded)
        _RESTORE_RUNS_LOADED = True

        if changed:
            try:
                _persist_restore_runs(config)
            except Exception:
                pass


def _get_job_repo_info(config: dict, job_key: str) -> dict:
    """Resolve repository and passphrase from the canonical repository object."""
    job_key = _validate_job_key(job_key)
    from repository_context import resolve_job_repository_context

    context = resolve_job_repository_context(config, job_key)
    return {
        "repo": context["repository_path"],
        "passphrase_file": context["passphrase_ref"] or None,
        "repository_key": context["repository_key"],
        "storage_key": context["storage_key"],
        "storage": context.get("storage") if isinstance(context.get("storage"), dict) else {},
        "job": context.get("job") if isinstance(context.get("job"), dict) else {},
    }


def _borg_env(config: dict, passphrase_file: str | None) -> dict:
    from borg_key_store import apply_borg_key_environment

    env = dict(os.environ)
    if passphrase_file:
        pass_path = Path(passphrase_file)
        if pass_path.exists():
            env["BORG_PASSCOMMAND"] = f"cat {shlex.quote(str(pass_path))}"
    return apply_borg_key_environment(env, config)


def _repository_borg_env(config: dict, info: dict) -> dict:
    from borg_ssh import configure_borg_ssh

    env = _borg_env(config, info["passphrase_file"])
    configure_borg_ssh(env, info.get("storage"), str(info["repo"] or ""))
    return env


def _repository_resource(info: dict) -> str:
    repo = str(info["repo"] if "repo" in info else "").strip()
    if not repo:
        raise ValueError("Repository path is missing")
    return f"repo:{repo}"


def _resource_lock_int(config: dict, key: str, default: int) -> int:
    raw = str(config.get(key) or "").strip()
    if not raw:
        try:
            from config_api import read_expanded_conf
            raw = str(read_expanded_conf(config).get(key) or "").strip()
        except Exception:
            raw = ""
    try:
        return max(1, int(raw)) if raw else default
    except (TypeError, ValueError):
        return default


def _active_repository_lock(config: dict, info: dict) -> dict | None:
    from jobs_api import active_resource_locks

    resource = _repository_resource(info)
    for row in active_resource_locks(config):
        if str(row.get("resource") or "") == resource:
            return row
    return None


def _raise_repository_busy(resource: str, holder: str) -> None:
    holder_text = holder or "another operation"
    raise RestoreRepositoryBusy(
        f"Repository is currently used by {holder_text}. Please wait until the running operation has finished.",
        holder=holder,
        resource=resource,
    )


def ensure_restore_repository_available(config: dict, info: dict) -> None:
    resource = _repository_resource(info)
    lock = _active_repository_lock(config, info)
    if lock:
        _raise_repository_busy(resource, str(lock.get("job_key") or "").strip())


def acquire_restore_repository_lock(config: dict, info: dict, job_key: str, restore_id: str):
    from jobs_api import resolve_resource_lock_dir
    from wizard_runner import ResourceLockSet

    resource = _repository_resource(info)
    lock_set = ResourceLockSet(
        lock_dir=resolve_resource_lock_dir(config),
        job_key=_validate_job_key(job_key),
        ttl_seconds=_resource_lock_int(config, "BORG_RESOURCE_LOCK_TTL_SECONDS", 7200),
        grace_seconds=_resource_lock_int(config, "BORG_RESOURCE_LOCK_GRACE_SECONDS", 60),
        heartbeat_seconds=_resource_lock_int(config, "BORG_RESOURCE_LOCK_HEARTBEAT_SECONDS", 20),
        run_id=str(restore_id or "").strip(),
        operation="restore",
    )
    ok, reason = lock_set.acquire([resource])
    if ok:
        return lock_set
    lock = _active_repository_lock(config, info)
    holder = str(lock.get("job_key") or "").strip() if lock else ""
    lock_set.release()
    _raise_repository_busy(resource, holder or reason)


def _archive_filter_rows_for_restore_job(job_key: str, info: dict) -> list[dict]:
    from archive_prefix import archive_prefix_from_metadata, job_archive_prefixes
    job = info.get("job") if isinstance(info.get("job"), dict) else {}
    current_prefix = archive_prefix_from_metadata(job)
    prefixes = job_archive_prefixes(job)
    return [
        {
            "prefix": prefix,
            "filter": f"{prefix}-*",
            "current": bool(current_prefix and prefix == current_prefix),
        }
        for prefix in prefixes
    ]


def _archive_prefixes_for_restore_job(job_key: str, info: dict) -> list[str]:
    return [str(row["prefix"]) for row in _archive_filter_rows_for_restore_job(job_key, info)]


def _run_borg_archive_list(repo: str, env: dict, archive_filter: str = "") -> dict:
    cmd = ["borg", "list", "--json"]
    if archive_filter:
        cmd.extend(["--glob-archives", archive_filter])
    cmd.append(repo)
    r = subprocess.run(
        cmd,
        capture_output=True, text=True, env=env, timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"borg list failed: {r.stderr.strip()}")
    return json.loads(r.stdout)


def _archive_rows_from_borg_payload(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for archive in payload.get("archives", []):
        if not isinstance(archive, dict):
            continue
        rows.append({
            "name": archive["name"],
            "start": archive["start"],
            "end": archive.get("end", archive["start"]),
        })
    return rows


def _get_max_runtime_hours(config: dict) -> int:
    """
    Liefert den konfigurierten Hard-Limit-Wert in Stunden.
    0 bedeutet absichtlich 'unbegrenzt', damit große Initial-Restores
    nicht vorzeitig abgebrochen werden.
    """
    try:
        from config_api import read_expanded_conf
        conf = read_expanded_conf(config)
        raw = str(conf.get("BORG_MAX_RUNTIME_HOURS", "0") or "0").strip()
    except Exception:
        raw = "0"
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def list_archives_with_context(config: dict, job_key: str) -> dict:
    job_key = _validate_job_key(job_key)
    from smb_mount import ensure_smb_mount_for_job
    guard = ensure_smb_mount_for_job(config, job_key)
    try:
        info = _get_job_repo_info(config, job_key)
        ensure_restore_repository_available(config, info)
        env = _repository_borg_env(config, info)
        archive_filters = _archive_filter_rows_for_restore_job(job_key, info)
        prefixes = [str(row["prefix"]) for row in archive_filters]

        archives: list[dict] = []
        if prefixes:
            for prefix in prefixes:
                archives.extend(_archive_rows_from_borg_payload(
                    _run_borg_archive_list(info["repo"], env, f"{prefix}-*")
                ))
        else:
            archives.extend(_archive_rows_from_borg_payload(
                _run_borg_archive_list(info["repo"], env)
            ))

        by_name = {str(row.get("name") or ""): row for row in archives if str(row.get("name") or "")}
        return {
            "archives": sorted(by_name.values(), key=lambda row: str(row.get("start") or ""), reverse=True),
            "archive_filters": archive_filters,
        }
    finally:
        guard.cleanup()


def list_archives(config: dict, job_key: str) -> List[dict]:
    return list_archives_with_context(config, job_key)["archives"]


def list_files(config: dict, job_key: str, archive: str, path: str) -> List[dict]:
    job_key = _validate_job_key(job_key)
    archive = _validate_archive_name(archive)
    from smb_mount import ensure_smb_mount_for_job
    guard = ensure_smb_mount_for_job(config, job_key)
    try:
        info = _get_job_repo_info(config, job_key)
        ensure_restore_repository_available(config, info)
        env = _repository_borg_env(config, info)

        from archive_browser import list_archive_directory

        return list_archive_directory(info["repo"], archive, path, env, strict=True)
    finally:
        guard.cleanup()


def get_repo_info(config: dict, job_key: str) -> dict:
    job_key = _validate_job_key(job_key)
    return _get_job_repo_info(config, job_key)


def get_repo_stats(config: dict, job_key: str) -> dict:
    job_key = _validate_job_key(job_key)
    from smb_mount import ensure_smb_mount_for_job
    guard = ensure_smb_mount_for_job(config, job_key)
    try:
        info = _get_job_repo_info(config, job_key)
        ensure_restore_repository_available(config, info)
        env = _repository_borg_env(config, info)

        r_info = subprocess.run(
            ["borg", "info", "--json", info["repo"]],
            capture_output=True, text=True, env=env, timeout=60,
        )
        if r_info.returncode != 0:
            raise RuntimeError(f"borg info failed: {r_info.stderr.strip()}")

        r_list = subprocess.run(
            ["borg", "list", "--json", info["repo"]],
            capture_output=True, text=True, env=env, timeout=30,
        )
        if r_list.returncode != 0:
            raise RuntimeError(f"borg list failed: {r_list.stderr.strip()}")

        info_data = json.loads(r_info.stdout)
        list_data = json.loads(r_list.stdout)
        stats = info_data.get("cache", {}).get("stats", {})
        archives = list_data.get("archives", [])

        months: dict = {}
        for a in archives:
            start = a.get("start", "")
            if len(start) >= 7:
                month = start[:7]
                months[month] = months.get(month, 0) + 1

        sorted_months = sorted(months.items())
        return {
            "total_size": stats.get("total_size", 0),
            "total_csize": stats.get("total_csize", 0),
            "unique_csize": stats.get("unique_csize", 0),
            "archive_count": len(archives),
            "repo": info["repo"],
            "monthly": [{"month": m, "count": c} for m, c in sorted_months],
        }
    finally:
        guard.cleanup()


def list_target_dirs(prefix: str = "", limit: int = 40) -> list[dict]:
    """
    Return directory suggestions below /mnt/user for restore target input.
    Freitext remains allowed in UI; this is only an assistive autocomplete.
    """
    base = Path("/mnt/user")
    if not base.exists():
        return []

    raw = str(prefix or "").strip()
    if not raw:
        return [{"path": "/mnt/user/"}]
    if not raw.startswith("/mnt/user"):
        return []

    has_trailing = raw.endswith("/")
    candidate = Path(raw)
    search_parent: Path
    name_prefix = ""

    if has_trailing:
        search_parent = candidate
    elif candidate.is_dir():
        search_parent = candidate
    else:
        search_parent = candidate.parent
        name_prefix = candidate.name

    try:
        search_parent = search_parent.resolve()
        base_resolved = base.resolve()
    except Exception:
        return []

    if not str(search_parent).startswith(str(base_resolved)):
        return []
    if not search_parent.exists() or not search_parent.is_dir():
        return []

    out: list[dict] = []
    limit = max(1, min(int(limit or 40), 100))

    try:
        for child in sorted(search_parent.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            if name_prefix and not child.name.lower().startswith(name_prefix.lower()):
                continue
            out.append({"path": f"{child.as_posix().rstrip('/')}/"})
            if len(out) >= max(1, int(limit)):
                break
    except Exception:
        return []
    return out


def list_target_dirs_with_config(config: dict, prefix: str = "", limit: int = 40) -> list[dict]:
    roots = _get_restore_allowed_roots(config)
    primary = roots[0] if roots else Path("/mnt/user")
    if not primary.exists():
        return []

    raw = str(prefix or "").strip()
    if not raw:
        return [{"path": f"{primary.as_posix().rstrip('/')}/"}]
    if not _is_under_allowed_roots(Path(raw), roots):
        return []

    has_trailing = raw.endswith("/")
    candidate = Path(raw)
    if has_trailing:
        search_parent = candidate
    elif candidate.is_dir():
        search_parent = candidate
    else:
        search_parent = candidate.parent
    name_prefix = "" if has_trailing or candidate.is_dir() else candidate.name

    try:
        search_parent = search_parent.resolve()
    except Exception:
        return []

    if not _is_under_allowed_roots(search_parent, roots):
        return []
    if not search_parent.exists() or not search_parent.is_dir():
        return []

    out: list[dict] = []
    limit = max(1, min(int(limit or 40), 100))
    try:
        for child in sorted(search_parent.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            if name_prefix and not child.name.lower().startswith(name_prefix.lower()):
                continue
            if not _is_under_allowed_roots(child, roots):
                continue
            out.append({"path": f"{child.as_posix().rstrip('/')}/"})
            if len(out) >= limit:
                break
    except Exception:
        return []
    return out


def _validate_target_dir(target_dir: str, config: dict | None = None) -> Path:
    p = Path(str(target_dir or "").strip())
    if not p:
        raise ValueError("target_dir is missing")
    try:
        rp = p.resolve()
    except OSError:
        raise ValueError("Target path is invalid")
    roots = _get_restore_allowed_roots(config or {}) if config is not None else [Path("/mnt/user").resolve()]
    if not _is_under_allowed_roots(rp, roots):
        raise ValueError("Target path is outside the allowed restore roots")
    if not rp.exists():
        raise ValueError("Target path does not exist")
    if not rp.is_dir():
        raise ValueError("Target path is not a directory")
    if not os.access(rp, os.W_OK | os.X_OK):
        raise ValueError("Target path is not writable")
    return rp


def _precheck_metadata(repo: str, archive: str, source_path: str, env: dict) -> dict:
    source_clean = normalize_paths(source_path)[0]
    if not source_clean:
        raise ValueError("source_path is missing")
    parts = [x for x in source_clean.split("/") if x]
    repo_archive = f"{repo}::{archive}"

    # Verify archive is readable.
    info_proc = subprocess.run(
        ["borg", "info", repo_archive],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    if info_proc.returncode != 0:
        return {
            "ok": False,
            "exit_code": info_proc.returncode,
            "stdout": (info_proc.stdout or "").strip(),
            "stderr": (info_proc.stderr or "").strip(),
            "basename": parts[-1],
            "source_clean": source_clean,
        }

    # Verify source path exists in archive and detect source type.
    proc = subprocess.run(
        ["borg", "list", "--json-lines", repo_archive, "pp:" + source_clean],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    source_type = ""
    if proc.returncode == 0:
        try:
            for line in (proc.stdout or "").splitlines():
                item = json.loads(line)
                p = str(item.get("path", "")).strip("/")
                if p == source_clean:
                    source_type = str(item.get("type", "") or "")
                    break
                if not source_type and p.startswith(source_clean + "/"):
                    source_type = "d"
        except Exception:
            source_type = ""
    return {
        "ok": proc.returncode == 0 and bool(source_type),
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip() or ("Selected path is missing from the archive" if not source_type else ""),
        "basename": parts[-1],
        "source_clean": source_clean,
        "source_type": source_type,
    }


def _selection_plan(repo, archive, source_path, source_paths, target, mode, env):
    paths = normalize_paths(source_path, source_paths)
    if source_paths is None:
        meta = _precheck_metadata(repo, archive, paths[0], env)
        if not meta.get("ok"):
            raise ValueError(meta.get("stderr") or "Archive source could not be verified")
        entries = [{"path": paths[0], "type": meta.get("source_type", "-")}]
    else:
        entries = selected_entries(repo, archive, env, paths)
    return destination_plan(entries, target, mode)


def restore_precheck(
    config: dict,
    job_key: str,
    archive: str,
    source_path: str,
    target_dir: str,
    conflict_mode: str,
    dry_run: bool = True,
    source_paths=None,
) -> dict:
    job_key = _validate_job_key(job_key)
    archive = _validate_archive_name(archive)
    from smb_mount import ensure_smb_mount_for_job
    guard = ensure_smb_mount_for_job(config, job_key)
    try:
        info = _get_job_repo_info(config, job_key)
        ensure_restore_repository_available(config, info)
        env = _repository_borg_env(config, info)
        target = _validate_target_dir(target_dir, config)
        if conflict_mode not in {"skip", "overwrite", "rename"}:
            raise ValueError("Invalid conflict mode")

        mountpoint = str(target.anchor or "/")
        free = shutil.disk_usage(target).free
        plan = _selection_plan(info["repo"], archive, source_path, source_paths, target, conflict_mode, env)
        items = plan["items"]
        return {
            "ok": True, "job_key": job_key, "archive": archive, "repo": info["repo"],
            "source_path": items[0]["path"], "source_paths": [i["path"] for i in items],
            "items": items, "common_parent": plan["common_parent"],
            "target_dir": str(target), "conflict_mode": conflict_mode,
            "dry_run": False, "dry_run_exit_code": 0,
            "dry_run_stdout": "Precheck is metadata-only (no extraction).",
            "dry_run_stderr": "",
            "destination_path": items[0]["destination_path"] if len(items) == 1 else str(target),
            "destination_exists": any(i["destination_exists"] for i in items),
            "target_writable": True, "target_mountpoint": mountpoint,
            "target_free_bytes": int(free),
        }

    finally:
        guard.cleanup()


def start_restore(
    config: dict,
    job_key: str,
    archive: str,
    source_path: str,
    target_dir: str,
    conflict_mode: str,
    preserve_owner: bool = False,
    progress_cb=None,
    restore_id: str = "",
    source_paths=None,
    dry_run: bool = False,
) -> dict:
    job_key = _validate_job_key(job_key)
    archive = _validate_archive_name(archive)
    from smb_mount import ensure_smb_mount_for_job

    guard = ensure_smb_mount_for_job(config, job_key)
    lock_set = None
    cleanup_extract_dir = None
    try:
        info = _get_job_repo_info(config, job_key)
        lock_set = acquire_restore_repository_lock(
            config,
            info,
            job_key,
            str(restore_id or "").strip() or f"restore-sync-{uuid.uuid4().hex[:8]}",
        )
        env = _repository_borg_env(config, info)
        target = _validate_target_dir(target_dir, config)
        if conflict_mode not in {"skip", "overwrite", "rename"}:
            raise ValueError("Invalid conflict mode")

        plan = _selection_plan(info["repo"], archive, source_path, source_paths, target, conflict_mode, env)
        items = plan["items"]
        pending = [item for item in items if not item["skipped"]]
        for item in items:
            if progress_cb:
                progress_cb(f"{'Skip existing' if item['skipped'] else 'Restore'}: {item['path']} -> {item['destination_path']}")
        if not pending:
            return {"started": False, "skipped": True, "reason": "All selected targets already exist",
                    "skip_reason_code": "target_exists", "destination_path": str(target), "items": items}
        target_stat = target.stat()
        target_uid = int(target_stat.st_uid)
        target_gid = int(target_stat.st_gid)

        def _apply_target_owner(path: Path) -> None:
            """Set owner/group recursively to target directory ownership."""
            _ensure_restore_path_inside(path, target)
            try:
                os.lchown(path, target_uid, target_gid)
            except OSError:
                pass
            if path.is_dir() and not path.is_symlink():
                for root, dirs, files in os.walk(path):
                    root_p = Path(root)
                    _ensure_restore_path_inside(root_p, target)
                    try:
                        os.lchown(root_p, target_uid, target_gid)
                    except OSError:
                        pass
                    for name in dirs:
                        p = root_p / name
                        _ensure_restore_path_inside(p, target)
                        try:
                            os.lchown(p, target_uid, target_gid)
                        except OSError:
                            pass
                    for name in files:
                        p = root_p / name
                        _ensure_restore_path_inside(p, target)
                        try:
                            os.lchown(p, target_uid, target_gid)
                        except OSError:
                            pass

        def _merge_replace(src: Path, dst: Path) -> None:
            """
            Merge src into dst and replace only conflicting paths.
            Unrelated existing files in dst stay untouched.
            """
            _ensure_restore_path_inside(src, target, allow_missing=False)
            _ensure_restore_path_inside(dst, target)
            if dst.is_symlink():
                raise ValueError("Restore destination contains a symbolic link; choose another target directory")
            if src.is_dir() and not src.is_symlink():
                if dst.exists() and not dst.is_dir():
                    _ensure_restore_path_inside(dst, target, allow_missing=False)
                    dst.unlink()
                dst.mkdir(parents=True, exist_ok=True)
                _ensure_restore_path_inside(dst, target, allow_missing=False)
                for child in src.iterdir():
                    _merge_replace(child, dst / child.name)
                try:
                    _ensure_restore_path_inside(src, target, allow_missing=False)
                    src.rmdir()
                except OSError:
                    pass
                return

            # file/symlink/other
            if dst.exists() or dst.is_symlink():
                _ensure_restore_path_inside(dst, target, allow_missing=False)
                if dst.is_dir() and not dst.is_symlink():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            _ensure_restore_path_inside(dst.parent, target, allow_missing=False)
            shutil.move(str(src), str(dst))
            _ensure_restore_path_inside(dst, target, allow_missing=False)

        # Stage on the target filesystem. Extraction failure does not overwrite
        # existing destination files. One extract preserves multi-selection layout.
        extract_cwd = target if dry_run else _make_restore_stage_dir(target)
        cleanup_extract_dir = None if dry_run else extract_cwd
        patterns = [("pp:" if item["type"] == "d" else "pf:") + item["path"] for item in pending]
        cmd = ["borg", "extract", f"{info['repo']}::{archive}", *patterns,
               "--strip-components", str(plan["strip_components"]), "--list"]
        if dry_run:
            cmd.append("--dry-run")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=extract_cwd,
            bufsize=1,
        )
        max_runtime_hours = _get_max_runtime_hours(config)
        wd_stop = threading.Event()
        wd_thread = None
        try:
            from lib.borg_runner import _start_process_watchdog
            wd_thread = _start_process_watchdog(
                proc,
                operation="borg extract",
                max_runtime_hours=max_runtime_hours,
                stop_event=wd_stop,
            )
        except Exception:
            wd_thread = None
        out_lines: list[str] = []
        if proc.stdout is not None:
            try:
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    if line:
                        out_lines.append(line)
                        if len(out_lines) > 400:
                            del out_lines[:-400]
                        if progress_cb:
                            progress_cb(line)
            finally:
                ret = proc.wait()
                wd_stop.set()
                if wd_thread is not None:
                    wd_thread.join(timeout=1.0)
        else:
            ret = proc.wait()
            wd_stop.set()
            if wd_thread is not None:
                wd_thread.join(timeout=1.0)
        if ret != 0:
            tail = "\n".join(out_lines[-20:]).strip()
            if cleanup_extract_dir and cleanup_extract_dir.exists():
                _ensure_restore_path_inside(cleanup_extract_dir, target, allow_missing=False)
                shutil.rmtree(cleanup_extract_dir, ignore_errors=True)
            raise RuntimeError(tail or f"borg extract failed (exit {ret})")

        if dry_run:
            if progress_cb:
                progress_cb("Simulation completed: no files were restored or replaced.")
            return {"started": True, "dry_run": True, "items": items,
                    "destination_path": str(target), "stdout": "\n".join(out_lines)[-4000:]}

        # Check every extracted path before publishing any selected entry.
        for root, dirs, files in os.walk(extract_cwd):
            for name in dirs + files:
                _ensure_restore_path_inside(Path(root) / name, extract_cwd, allow_missing=False)
        for item in pending:
            src = extract_cwd / item["relative_path"]
            if not src.exists() and not src.is_symlink():
                raise RuntimeError(f"Extract succeeded, but selected path is missing: {item['path']}")
        for item in pending:
            src = extract_cwd / item["relative_path"]
            dest = Path(item["destination_path"])
            if conflict_mode == "rename":
                name = Path(item["path"]).name if item["direct_contents"] else dest.name
                parent = target if item["direct_contents"] else dest.parent
                suffix = datetime.now().strftime('%Y%m%d-%H%M%S')
                dest = parent / f"{name}.{suffix}"
                counter = 1
                while dest.exists() or dest.is_symlink():
                    dest = parent / f"{name}.{suffix}-{counter}"
                    counter += 1
            # Parent directories may be absent for selections from different folders.
            for parent in reversed([dest.parent, *dest.parent.parents]):
                if parent == target or target in parent.parents:
                    _ensure_restore_path_inside(parent, target)
                    parent.mkdir(exist_ok=True)
            _ensure_restore_path_inside(dest, target)
            if dest.is_symlink():
                raise ValueError("Restore destination contains a symbolic link; choose another target directory")
            if conflict_mode == "skip" and not item["direct_contents"] and dest.exists():
                item["skipped"] = True
                if progress_cb:
                    progress_cb(f"Skip target created during extraction: {dest}")
                continue
            if item["direct_contents"]:
                if conflict_mode == "skip" and any(p != extract_cwd for p in target.iterdir()):
                    item["skipped"] = True
                    continue
                dest.mkdir(exist_ok=True)
                for child in list(src.iterdir()):
                    _merge_replace(child, dest / child.name)
            elif conflict_mode == "overwrite" and dest.exists():
                _merge_replace(src, dest)
            else:
                shutil.move(str(src), str(dest))
            item["destination_path"] = str(dest)
            item["restored"] = True
            if not preserve_owner:
                _apply_target_owner(dest)
            if progress_cb:
                progress_cb(f"Restored: {item['path']} -> {dest}")
        skipped = all(item["skipped"] for item in items)
        return {
            "started": not skipped, "skipped": skipped,
            "skip_reason_code": "target_exists" if skipped else "",
            "items": items,
            "destination_path": items[0]["destination_path"] if len(items) == 1 else str(target),
            "conflict_mode": conflict_mode,
            "owner_mode": "preserve_backup" if preserve_owner else "target_directory",
            "stdout": "\n".join(out_lines)[-4000:], "stderr": "",
        }

    finally:
        if cleanup_extract_dir and cleanup_extract_dir.exists():
            shutil.rmtree(cleanup_extract_dir, ignore_errors=True)
        if lock_set is not None:
            lock_set.release()
        guard.cleanup()


def _trim_runs(config: dict) -> None:
    with _RESTORE_LOCK:
        if len(_RESTORE_RUNS) <= _RESTORE_KEEP:
            return
        keys = sorted(_RESTORE_RUNS.keys(), key=lambda k: _RESTORE_RUNS[k].get("started_at", ""), reverse=True)
        for k in keys[_RESTORE_KEEP:]:
            _RESTORE_RUNS.pop(k, None)
        try:
            _persist_restore_runs(config)
        except Exception:
            pass


def start_restore_async(
    config: dict,
    job_key: str,
    archive: str,
    source_path: str,
    target_dir: str,
    conflict_mode: str,
    preserve_owner: bool = False,
    source_paths=None,
    dry_run: bool = False,
) -> dict:
    job_key = _validate_job_key(job_key)
    archive = _validate_archive_name(archive)
    paths = normalize_paths(source_path, source_paths)
    _ensure_restore_runs_loaded(config)
    restore_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    state = {
        "restore_id": restore_id,
        "state": "running",
        "phase": "starting",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": "",
        "job_key": job_key,
        "archive": archive,
        "source_path": paths[0],
        "source_paths": paths,
        "target_dir": target_dir,
        "destination_path": "",
        "conflict_mode": conflict_mode,
        "preserve_owner": bool(preserve_owner),
        "dry_run": bool(dry_run),
        "error": "",
        "skipped": False,
        "skip_reason_code": "",
        "lines": [],
    }
    with _RESTORE_LOCK:
        _RESTORE_RUNS[restore_id] = state
        try:
            _persist_restore_runs(config)
        except Exception:
            pass
    _trim_runs(config)

    def _append(line: str) -> None:
        with _RESTORE_LOCK:
            s = _RESTORE_RUNS.get(restore_id)
            if not s:
                return
            lines = s.setdefault("lines", [])
            lines.append(str(line))
            if len(lines) > 200:
                del lines[:-200]
            try:
                _persist_restore_runs(config)
            except Exception:
                pass

    def _set_phase(phase: str) -> None:
        with _RESTORE_LOCK:
            s = _RESTORE_RUNS.get(restore_id)
            if s:
                s["phase"] = phase
                try:
                    _persist_restore_runs(config)
                except Exception:
                    pass

    def _finish_done(result: dict) -> None:
        with _RESTORE_LOCK:
            s = _RESTORE_RUNS.get(restore_id)
            if not s:
                return
            s["state"] = "done"
            s["phase"] = "done"
            s["finished_at"] = datetime.now().isoformat(timespec="seconds")
            s["destination_path"] = str(result.get("destination_path", "") or "")
            s["items"] = result.get("items", [])
            s["skipped"] = bool(result.get("skipped", False))
            s["skip_reason_code"] = str(result.get("skip_reason_code", "") or "")
            try:
                _record_restore_history(config, s, "restore-run-finished")
            except Exception as exc:
                lines = s.setdefault("lines", [])
                lines.append(f"Restore history write failed: {exc}")
            try:
                _persist_restore_runs(config)
            except Exception:
                pass

    def _finish_error(msg: str) -> None:
        with _RESTORE_LOCK:
            s = _RESTORE_RUNS.get(restore_id)
            if not s:
                return
            s["state"] = "error"
            s["phase"] = "error"
            s["finished_at"] = datetime.now().isoformat(timespec="seconds")
            s["error"] = msg
            try:
                _record_restore_history(config, s, "restore-run-finished")
            except Exception as exc:
                lines = s.setdefault("lines", [])
                lines.append(f"Restore history write failed: {exc}")
            try:
                _persist_restore_runs(config)
            except Exception:
                pass

    def _worker() -> None:
        try:
            _set_phase("extract")
            _append("Starting restore extract ...")
            result = start_restore(
                config,
                job_key,
                archive,
                source_path,
                target_dir,
                conflict_mode,
                preserve_owner,
                progress_cb=_append,
                restore_id=restore_id,
                **({"dry_run": True} if dry_run else {}),
                **({"source_paths": paths} if source_paths is not None else {}),
            )
            if result.get("skipped"):
                _append(f"Skipped: {result.get('reason', 'unknown')}")
            elif dry_run:
                _append("Simulation completed successfully; target files unchanged.")
            else:
                _append(f"Restore completed successfully: {result.get('destination_path', '')}")
            _finish_done(result)
        except Exception as exc:
            _append(f"ERROR: {exc}")
            _append(traceback.format_exc(limit=2).strip())
            _finish_error(str(exc))

    t = threading.Thread(target=_worker, name=f"restore-{restore_id}", daemon=True)
    t.start()
    return {"started": True, "restore_id": restore_id}


def list_restore_runs(config: dict, limit: int = 20) -> dict:
    _ensure_restore_runs_loaded(config)
    try:
        limit = max(1, min(50, int(limit)))
    except (TypeError, ValueError):
        limit = 20
    with _RESTORE_LOCK:
        rows = []
        for run in _RESTORE_RUNS.values():
            if not isinstance(run, dict):
                continue
            if _is_restore_terminal(run.get("state")):
                continue
            rows.append({
                "restore_id": run.get("restore_id"),
                "state": run.get("state"),
                "phase": run.get("phase"),
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
                "job_key": run.get("job_key"),
                "archive": run.get("archive"),
                "source_path": run.get("source_path"),
                "source_paths": run.get("source_paths") or [run.get("source_path") or ""],
                "items": run.get("items") or [],
                "dry_run": bool(run.get("dry_run", False)),
                "target_dir": run.get("target_dir"),
                "destination_path": run.get("destination_path"),
                "error": run.get("error"),
                "skipped": bool(run.get("skipped", False)),
                "skip_reason_code": run.get("skip_reason_code", ""),
                "lines": list(run.get("lines", []))[-20:],
            })
        rows.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
        active = [r for r in rows if str(r.get("state") or "").lower() == "running"]
        return {
            "runs": rows[:limit],
            "active": active,
        }


def list_restore_history(config: dict, limit: int = 20, offset: int = 0) -> dict:
    _ensure_restore_runs_loaded(config)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    if limit > 0:
        limit = min(1000, limit)
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    rows = _read_history_index(config)
    rows.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    selected = rows[offset:] if limit <= 0 else rows[offset:offset + limit]
    return {
        "runs": selected,
        "total": len(rows),
        "limit": limit,
        "offset": offset,
    }


def get_restore_history_detail(config: dict, restore_id: str) -> dict:
    _ensure_restore_runs_loaded(config)
    rid = str(restore_id or "").strip()
    if not rid:
        raise ValueError("restore_id is required")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", rid):
        raise ValueError("Invalid restore_id")
    fp = _restore_history_runs_dir(config) / f"{rid}.json"
    if not fp.exists():
        raise ValueError("Unknown restore_id")
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Could not read restore history detail: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Invalid restore history detail")
    return raw


def delete_restore_history_entry(config: dict, restore_id: str) -> dict:
    _ensure_restore_runs_loaded(config)
    rid = str(restore_id or "").strip()
    if not rid:
        raise ValueError("restore_id is required")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", rid):
        raise ValueError("Invalid restore_id")
    rows = _read_history_index(config)
    remaining = [row for row in rows if str(row.get("restore_id") or "") != rid]
    if len(remaining) == len(rows):
        raise ValueError("Unknown restore_id")
    detail_deleted = False
    detail = _restore_history_runs_dir(config) / f"{rid}.json"
    try:
        if detail.exists():
            detail.unlink()
            detail_deleted = True
    except OSError as exc:
        raise ValueError(f"Could not delete restore history detail: {exc}") from exc
    _write_history_index(config, remaining)
    return {
        "deleted": True,
        "restore_id": rid,
        "detail_deleted": detail_deleted,
        "remaining": len(remaining),
    }


def get_restore_state(config: dict, restore_id: str) -> dict:
    _ensure_restore_runs_loaded(config)
    with _RESTORE_LOCK:
        s = _RESTORE_RUNS.get(str(restore_id).strip())
        if not s:
            raise ValueError("Unknown restore_id")
        return {
            "restore_id": s.get("restore_id"),
            "state": s.get("state"),
            "phase": s.get("phase"),
            "started_at": s.get("started_at"),
            "finished_at": s.get("finished_at"),
            "job_key": s.get("job_key"),
            "archive": s.get("archive"),
            "source_path": s.get("source_path"),
            "target_dir": s.get("target_dir"),
            "source_paths": s.get("source_paths") or [s.get("source_path") or ""],
            "items": s.get("items") or [],
            "dry_run": bool(s.get("dry_run", False)),
            "destination_path": s.get("destination_path"),
            "error": s.get("error"),
            "skipped": bool(s.get("skipped", False)),
            "skip_reason_code": s.get("skip_reason_code", ""),
            "lines": list(s.get("lines", []))[-80:],
        }
