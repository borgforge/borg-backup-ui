"""api/restore_api.py – Browse & Restore: Borg Archive Browser"""

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

_SECRETS_DIR = Path("/boot/config/borg-backup/secrets")

# In-memory cache: (repo, archive) → {expires, index}
# index: parent_path → {child_name: entry_dict}
_CACHE: dict = {}
_CACHE_TTL = 300  # 5 minutes

_RESTORE_RUNS: dict = {}
_RESTORE_LOCK = threading.Lock()
_RESTORE_KEEP = 20
_RESTORE_RUNS_LOADED = False

_JOB_KEY_RX = re.compile(r"^[a-zA-Z0-9_.-]+$")
_ARCHIVE_RX = re.compile(r"^[a-zA-Z0-9_.:-]+$")


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
        "target_dir": run.get("target_dir") or "",
        "destination_path": run.get("destination_path") or "",
        "conflict_mode": run.get("conflict_mode") or "",
        "preserve_owner": bool(run.get("preserve_owner", False)),
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


def _central_restore_history_migration_state(config: dict) -> dict:
    try:
        from migrations.registry import read_central_migration_state
        state = read_central_migration_state(config)
        migrations = state.get("migrations") if isinstance(state.get("migrations"), dict) else {}
        entry = migrations.get("restore_history_v1") if isinstance(migrations.get("restore_history_v1"), dict) else {}
        return entry
    except Exception:
        return {}


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


def _read_conf_file(path: Path) -> dict:
    """Simple KEY=VALUE parser for backup.conf."""
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _expand_shell_vars(s: str, env: dict) -> str:
    """Expand ${VAR} and $VAR references using env dict."""
    def _repl(m: re.Match) -> str:
        name = m.group(1) or m.group(2)
        return env.get(name, m.group(0))
    return re.sub(r'\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)', _repl, s)


def _get_job_repo_info(config: dict, job_key: str) -> dict:
    """Resolve BORG_REPO and passphrase config for legacy and wizard jobs."""
    job_key = _validate_job_key(job_key)
    from jobs_api import discover_jobs, get_jobs_meta_dirs, resolve_data_root, resolve_scripts_dir
    scripts_dir = resolve_scripts_dir(config)
    data_root = resolve_data_root(config)
    jobs = {j.key: j for j in discover_jobs(scripts_dir, data_root)}
    if job_key not in jobs:
        raise ValueError(f"Unknown job: {job_key}")

    job = jobs[job_key]

    # Wizard/scriptless path: read metadata directly.
    if job.standard == "wizard":
        meta_path = None
        for meta_dir in get_jobs_meta_dirs(scripts_dir, data_root):
            p = meta_dir / f"{job_key}.json"
            if p.exists():
                meta_path = p
                break
        if meta_path is None:
            raise ValueError(f"Wizard metadata is missing: {job_key}")
        raw = json.loads(meta_path.read_text(encoding="utf-8"))

        repo_cfg = raw.get("repo") if isinstance(raw.get("repo"), dict) else {}
        repo_key = str(repo_cfg.get("conf_key") or "")
        repo_default = str(repo_cfg.get("default") or "").strip()
        if not repo_default:
            raise ValueError(f"Repository default is missing in {meta_path.name}")

        pass_cfg = raw.get("passphrase") if isinstance(raw.get("passphrase"), dict) else {}
        pass_key = str(pass_cfg.get("conf_key") or "")
        pass_default = str(pass_cfg.get("default") or "").strip() or None

        conf: dict = {}
        for cp in (data_root / "config" / "backup.conf",
                   scripts_dir / "config" / "backup.conf"):
            if cp.exists():
                conf = _read_conf_file(cp)
                break

        raw_repo = conf.get(repo_key, repo_default) if repo_key else repo_default
        expand_env = {**dict(os.environ), **conf}
        repo_path = _expand_shell_vars(raw_repo, expand_env)
        passphrase_file = conf.get(pass_key, pass_default) if pass_key else pass_default
        return {"repo": repo_path, "passphrase_file": passphrase_file}

    script_path = job.script_path
    if script_path is None:
        raise ValueError(f"Script path is missing for job: {job_key}")
    content = script_path.read_text(encoding="utf-8")

    # Repo path — try multiple patterns to handle wizard and hand-written scripts
    repo_key: str | None = None
    repo_default: str | None = None

    def _resolve_var(varname: str) -> str | None:
        """Find the string value of a module-level variable like _DEFAULT_REPO = '...'"""
        vm = re.search(rf'^{re.escape(varname)}\s*=\s*["\']([^"\']+)["\']',
                       content, re.MULTILINE)
        return vm.group(1) if vm else None

    # Pattern 1 (wizard): env.setdefault("BORG_REPO", env.get("KEY", "literal"))
    m = re.search(
        r'env\.setdefault\("BORG_REPO",\s*env\.get\("([^"]+)",\s*"([^"\']+)"\)\)',
        content,
    )
    if m:
        repo_key, repo_default = m.group(1), m.group(2)

    # Pattern 2 (variable default): env.setdefault("BORG_REPO", env.get("KEY", VAR))
    if not repo_default:
        m = re.search(
            r'env\.setdefault\("BORG_REPO",\s*env\.get\("([^"]+)",\s*([_A-Z][_A-Z0-9]*)\)\)',
            content, re.IGNORECASE,
        )
        if m:
            repo_key = m.group(1)
            repo_default = _resolve_var(m.group(2))

    # Pattern 3: BORG_REPO = "value"  or  BORG_REPO = 'value'
    if not repo_default:
        m = re.search(r'^BORG_REPO\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
        if m:
            repo_default = m.group(1)

    # Pattern 4: env.get("BORG_REPO", "value")
    if not repo_default:
        m = re.search(r'env\.get\("BORG_REPO",\s*"([^"\']+)"\)', content)
        if m:
            repo_default = m.group(1)

    # Pattern 5: env.setdefault("BORG_REPO", "value")
    if not repo_default:
        m = re.search(r'env\.setdefault\("BORG_REPO",\s*"([^"\']+)"\)', content)
        if m:
            repo_default = m.group(1)

    # Pattern 6: _DEFAULT_REPO / _REPO / similar top-level variable used as BORG_REPO default
    if not repo_default:
        m = re.search(r'env\.setdefault\("BORG_REPO",\s*([_A-Z][_A-Z0-9]*)\)', content, re.IGNORECASE)
        if m:
            repo_default = _resolve_var(m.group(1))

    if not repo_default:
        raise ValueError(f"BORG_REPO was not found in {script_path.name}; check the script")

    # Load backup.conf (try both possible locations)
    conf: dict = {}
    from jobs_api import resolve_data_root
    data_root = resolve_data_root(config)
    for cp in (data_root / "config" / "backup.conf",
               scripts_dir / "config" / "backup.conf"):
        if cp.exists():
            conf = _read_conf_file(cp)
            break

    raw_repo = conf.get(repo_key, repo_default) if repo_key else repo_default
    # Expand ${VAR} / $VAR references using backup.conf values + env
    expand_env = {**dict(os.environ), **conf}
    repo_path = _expand_shell_vars(raw_repo, expand_env)

    # Passphrase file: extract from script pattern
    # wizard scripts: passphrase_file = env.get("BORG_PASSPHRASE_FILE_X", "/boot/config/borg-backup/secrets/.borg-passphrase-*")
    pm = re.search(
        r'env\.get\("(BORG_PASSPHRASE_FILE_[^"]+)",\s*"([^"]+)"\)',
        content,
    )
    passphrase_file: str | None = None
    if pm:
        pf_key, pf_default = pm.group(1), pm.group(2)
        passphrase_file = conf.get(pf_key, pf_default)
    else:
        # Fallback: derive from type_id
        type_id = job.backup_type
        passphrase_file = f"/boot/config/borg-backup/secrets/.borg-passphrase-{type_id}"

    return {"repo": repo_path, "passphrase_file": passphrase_file}


def _borg_env(passphrase_file: str | None) -> dict:
    env = dict(os.environ)
    candidates = []
    if passphrase_file:
        pass_path = Path(passphrase_file)
        candidates.append(pass_path)
        name = pass_path.name
        flash = _SECRETS_DIR / (name if name.startswith(".") else f".{name}")
        if flash != pass_path:
            candidates.append(flash)

    for p in candidates:
        if p.exists():
            env["BORG_PASSCOMMAND"] = f"cat {shlex.quote(str(p))}"
            break
    return env


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


def list_archives(config: dict, job_key: str) -> List[dict]:
    job_key = _validate_job_key(job_key)
    from smb_mount import ensure_smb_mount_for_job
    guard = ensure_smb_mount_for_job(config, job_key)
    try:
        info = _get_job_repo_info(config, job_key)
        env = _borg_env(info["passphrase_file"])

        r = subprocess.run(
            ["borg", "list", "--json", info["repo"]],
            capture_output=True, text=True, env=env, timeout=30,
        )
        if r.returncode != 0:
            raise RuntimeError(f"borg list failed: {r.stderr.strip()}")

        data = json.loads(r.stdout)
        return list(reversed([
            {"name": a["name"], "start": a["start"], "end": a.get("end", a["start"])}
            for a in data.get("archives", [])
        ]))
    finally:
        guard.cleanup()


def _build_index(repo: str, archive: str, env: dict) -> dict:
    """
    Load full archive listing once and build parent→children index.
    Cached for _CACHE_TTL seconds to make all subsequent navigations instant.
    """
    key = (repo, archive)
    cached = _CACHE.get(key)
    if cached and time.time() < cached["expires"]:
        return cached["index"]

    repo_archive = f"{repo}::{archive}"
    r = subprocess.run(
        ["borg", "list", "--json-lines", repo_archive],
        capture_output=True, text=True, env=env, timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"borg list failed: {r.stderr.strip()}")

    # index: parent_path (str) → {child_name: entry_dict}
    index: dict = {}

    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        ipath = item.get("path", "")
        if not ipath:
            continue

        p = Path(ipath)
        parent = str(p.parent) if str(p.parent) != "." else ""
        name = p.name
        if not name:
            continue

        entry = {
            "name": name,
            "path": ipath,
            "type": item.get("type", "-"),
            "size": item.get("size", 0),
            "mtime": item.get("mtime", ""),
            "mode": item.get("mode", ""),
        }
        index.setdefault(parent, {})[name] = entry

    # Ensure every ancestor of every known path is in the index.
    # Collect all paths first, then walk upward to root for each.
    all_paths: set = set()
    for parent_key, children in index.items():
        if parent_key:
            all_paths.add(parent_key)
        for child in children.values():
            all_paths.add(child["path"])

    for ipath in all_paths:
        p = Path(ipath)
        while True:
            parent_p = p.parent
            parent_str = str(parent_p) if str(parent_p) != "." else ""
            name = p.name
            if not name:
                break
            if name not in index.setdefault(parent_str, {}):
                index[parent_str][name] = {
                    "name": name, "path": str(p),
                    "type": "d", "size": 0, "mtime": "", "mode": "",
                }
            if not parent_str:
                break
            p = parent_p

    _CACHE[key] = {"expires": time.time() + _CACHE_TTL, "index": index}
    return index


def list_files(config: dict, job_key: str, archive: str, path: str) -> List[dict]:
    job_key = _validate_job_key(job_key)
    archive = _validate_archive_name(archive)
    from smb_mount import ensure_smb_mount_for_job
    guard = ensure_smb_mount_for_job(config, job_key)
    try:
        info = _get_job_repo_info(config, job_key)
        env = _borg_env(info["passphrase_file"])

        index = _build_index(info["repo"], archive, env)

        current = path.rstrip("/") if path else ""
        children = list(index.get(current, {}).values())

        children.sort(key=lambda x: (0 if x["type"] == "d" else 1, x["name"].lower()))
        return children
    finally:
        guard.cleanup()


def get_repo_info(config: dict, job_key: str) -> dict:
    job_key = _validate_job_key(job_key)
    return _get_job_repo_info(config, job_key)


def get_repo_stats(config: dict, job_key: str) -> dict:
    job_key = _validate_job_key(job_key)
    from smb_mount import ensure_smb_mount_for_job
    ensure_smb_mount_for_job(config, job_key)
    info = _get_job_repo_info(config, job_key)
    env = _borg_env(info["passphrase_file"])

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
    source_clean = str(source_path or "").strip().strip("/")
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
        ["borg", "list", "--json-lines", repo_archive, source_clean],
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
                if not source_type:
                    source_type = str(item.get("type", "") or "")
        except Exception:
            source_type = ""
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
        "basename": parts[-1],
        "source_clean": source_clean,
        "source_type": source_type,
    }


def restore_precheck(
    config: dict,
    job_key: str,
    archive: str,
    source_path: str,
    target_dir: str,
    conflict_mode: str,
    dry_run: bool = True,
) -> dict:
    job_key = _validate_job_key(job_key)
    archive = _validate_archive_name(archive)
    from smb_mount import ensure_smb_mount_for_job
    ensure_smb_mount_for_job(config, job_key)
    info = _get_job_repo_info(config, job_key)
    env = _borg_env(info["passphrase_file"])
    target = _validate_target_dir(target_dir, config)
    if conflict_mode not in {"skip", "overwrite", "rename"}:
        raise ValueError("Invalid conflict mode")

    mountpoint = str(target.anchor or "/")
    free = shutil.disk_usage(target).free
    meta = _precheck_metadata(info["repo"], archive, source_path, env)
    source_type = str(meta.get("source_type", "")).strip()
    source_basename = str(meta.get("basename", "")).strip()
    same_name_target = bool(source_type == "d" and source_basename and target.name == source_basename)
    dest = target if same_name_target else (target / source_basename)
    exists = dest.exists()

    return {
        "ok": bool(meta["ok"]),
        "job_key": job_key,
        "archive": archive,
        "repo": info["repo"],
        "source_path": source_path,
        "target_dir": str(target),
        "conflict_mode": conflict_mode,
        "dry_run": False,
        "dry_run_exit_code": meta["exit_code"],
        "dry_run_stdout": (
            "Precheck is metadata-only (no extraction).\n"
            + (meta["stdout"] or "")
        )[-8000:],
        "dry_run_stderr": (meta["stderr"] or "")[-8000:],
        "destination_path": str(dest),
        "destination_exists": exists,
        "target_writable": True,
        "target_mountpoint": mountpoint,
        "target_free_bytes": int(free),
    }


def start_restore(
    config: dict,
    job_key: str,
    archive: str,
    source_path: str,
    target_dir: str,
    conflict_mode: str,
    preserve_owner: bool = False,
    progress_cb=None,
) -> dict:
    job_key = _validate_job_key(job_key)
    archive = _validate_archive_name(archive)
    from smb_mount import ensure_smb_mount_for_job
    ensure_smb_mount_for_job(config, job_key)
    info = _get_job_repo_info(config, job_key)
    env = _borg_env(info["passphrase_file"])
    target = _validate_target_dir(target_dir, config)
    if conflict_mode not in {"skip", "overwrite", "rename"}:
        raise ValueError("Invalid conflict mode")

    source_clean = str(source_path or "").strip().strip("/")
    parts = [x for x in source_clean.split("/") if x]
    if not parts:
        raise ValueError("source_path is missing")
    basename = parts[-1]
    source_meta = _precheck_metadata(info["repo"], archive, source_clean, env)
    source_type = str(source_meta.get("source_type", "")).strip()
    same_name_target = bool(source_type == "d" and basename and target.name == basename)
    restore_dir_contents_directly = same_name_target
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
        if src.is_dir():
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

    # Restore directly on target filesystem (no /tmp usage), so large files do not consume RAM/tmpfs.
    dest = target if restore_dir_contents_directly else (target / basename)
    final_dest = dest
    extract_cwd = target
    cleanup_extract_dir = None
    _ensure_restore_path_inside(dest, target)
    _ensure_restore_path_inside(final_dest, target)
    if dest.exists() and not (restore_dir_contents_directly and conflict_mode != "rename"):
        if conflict_mode == "skip":
            return {"started": False, "skipped": True, "reason": "Target file exists", "skip_reason_code": "target_exists", "destination_path": str(dest)}
        if conflict_mode == "overwrite":
            extract_cwd = _make_restore_stage_dir(target)
            cleanup_extract_dir = extract_cwd
        elif conflict_mode == "rename":
            final_dest = target / f"{basename}.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            _ensure_restore_path_inside(final_dest, target)
            extract_cwd = _make_restore_stage_dir(target)
            cleanup_extract_dir = extract_cwd
    elif conflict_mode == "rename":
        # Keep consistent behavior for rename mode even when destination does not yet exist.
        final_dest = target / f"{basename}.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        _ensure_restore_path_inside(final_dest, target)
        extract_cwd = _make_restore_stage_dir(target)
        cleanup_extract_dir = extract_cwd

    if restore_dir_contents_directly:
        if conflict_mode == "skip":
            try:
                if any(target.iterdir()):
                    return {"started": False, "skipped": True, "reason": "Target directory already contains data", "skip_reason_code": "target_not_empty", "destination_path": str(target)}
            except OSError:
                return {"started": False, "skipped": True, "reason": "Target directory is not readable", "skip_reason_code": "target_unreadable", "destination_path": str(target)}
        if conflict_mode == "overwrite":
            extract_cwd = _make_restore_stage_dir(target)
            cleanup_extract_dir = extract_cwd
        elif conflict_mode == "rename":
            final_dest = target / f"{basename}.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            _ensure_restore_path_inside(final_dest, target)
            final_dest.mkdir(parents=False, exist_ok=False)
            extract_cwd = final_dest

    strip_components = max(len(parts), 0) if restore_dir_contents_directly else max(len(parts) - 1, 0)
    repo_archive = f"{info['repo']}::{archive}"
    cmd = ["borg", "extract", repo_archive, source_clean, "--strip-components", str(strip_components), "--list"]
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

    src_temp = extract_cwd if restore_dir_contents_directly else (extract_cwd / basename)
    if not src_temp.exists():
        if cleanup_extract_dir and cleanup_extract_dir.exists():
            _ensure_restore_path_inside(cleanup_extract_dir, target, allow_missing=False)
            shutil.rmtree(cleanup_extract_dir, ignore_errors=True)
        raise RuntimeError("Extract succeeded, but the source file was not found in the target")

    _ensure_restore_path_inside(src_temp, target, allow_missing=False)
    _ensure_restore_path_inside(final_dest, target)
    if restore_dir_contents_directly and conflict_mode == "overwrite":
        for child in src_temp.iterdir():
            _merge_replace(child, final_dest / child.name)
    elif conflict_mode == "overwrite" and final_dest.exists() and src_temp != final_dest:
        _merge_replace(src_temp, final_dest)
    elif src_temp != final_dest:
        _ensure_restore_path_inside(src_temp, target, allow_missing=False)
        _ensure_restore_path_inside(final_dest.parent, target, allow_missing=False)
        shutil.move(str(src_temp), str(final_dest))
        _ensure_restore_path_inside(final_dest, target, allow_missing=False)
    if cleanup_extract_dir and cleanup_extract_dir.exists() and cleanup_extract_dir != final_dest:
        _ensure_restore_path_inside(cleanup_extract_dir, target, allow_missing=False)
        shutil.rmtree(cleanup_extract_dir, ignore_errors=True)
    if not preserve_owner:
        _apply_target_owner(final_dest)
    return {
        "started": True,
        "destination_path": str(final_dest),
        "conflict_mode": conflict_mode,
        "owner_mode": "preserve_backup" if preserve_owner else "target_directory",
        "stdout": "\n".join(out_lines)[-4000:],
        "stderr": "",
    }


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
) -> dict:
    job_key = _validate_job_key(job_key)
    archive = _validate_archive_name(archive)
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
        "source_path": source_path,
        "target_dir": target_dir,
        "destination_path": "",
        "conflict_mode": conflict_mode,
        "preserve_owner": bool(preserve_owner),
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
            )
            if result.get("skipped"):
                _append(f"Skipped: {result.get('reason', 'unknown')}")
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
        "migration": _central_restore_history_migration_state(config),
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


def get_restore_history_migration(config: dict) -> dict:
    _ensure_restore_runs_loaded(config)
    return {"state": _central_restore_history_migration_state(config), "log": []}


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
            "destination_path": s.get("destination_path"),
            "error": s.get("error"),
            "skipped": bool(s.get("skipped", False)),
            "skip_reason_code": s.get("skip_reason_code", ""),
            "lines": list(s.get("lines", []))[-80:],
        }
