"""Migration: make repository_key the only repository reference in job metadata."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repository_context import (
    LEGACY_JOB_REPOSITORY_FIELDS,
    RepositoryContextError,
    resolve_job_repository_context,
)


MIGRATION_ID = "repository_runtime_v1"
INTRODUCED_IN = "2026.07.10.1300"

LEGACY_JOB_FIELDS = LEGACY_JOB_REPOSITORY_FIELDS
LEGACY_REPOSITORY_FIELDS = {
    "storage_profile_key",
    "usb_profile_key",
    "smb_profile_key",
    "repo_conf_key",
    "conf_key",
    "repo_path",
    "repo_uri",
    "path_raw",
    "path_display",
}


def _data_root(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    return base.parent if base.name == "scripts" else base


def _jobs_dir(config: dict) -> Path:
    return _data_root(config) / "config" / "jobs"


def _conf_file(config: dict) -> Path:
    return _data_root(config) / "config" / "backup.conf"


def _repositories_file(config: dict) -> Path:
    return _data_root(config) / "config" / "repositories.json"


def _read_job(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Job metadata is invalid: {path.name}")
    return payload


def _assignment_key(line: str) -> str:
    stripped = str(line or "").strip()
    if not stripped or stripped.startswith("#"):
        return ""
    clean = stripped.removeprefix("readonly ")
    if "=" not in clean:
        return ""
    key = clean.split("=", 1)[0].strip()
    return key if re.fullmatch(r"[A-Z0-9_]+", key) else ""


def _legacy_conf_keys(lines: list[str]) -> list[str]:
    return sorted({
        key
        for line in lines
        if (key := _assignment_key(line))
        and (key.startswith("REPO_") or key.startswith("BORG_PASSPHRASE_FILE_"))
    })


def _expand_raw_conf(raw_conf: dict[str, Any]) -> dict[str, str]:
    resolved: dict[str, str] = {}

    def expand_key(key: str, stack: set[str]) -> str:
        if key in resolved:
            return resolved[key]
        if key in stack:
            return str(raw_conf.get(key) or "")
        value = str(raw_conf.get(key) or "")
        next_stack = {*stack, key}
        value = re.sub(
            r"\$\{([^}]+)\}",
            lambda match: expand_key(str(match.group(1)), next_stack),
            value,
        )
        resolved[key] = value
        return value

    for raw_key in raw_conf:
        expand_key(str(raw_key), set())
    return resolved


def detect(config: dict) -> dict[str, Any]:
    jobs = []
    for path in sorted(_jobs_dir(config).glob("*.json")) if _jobs_dir(config).is_dir() else []:
        try:
            job = _read_job(path)
        except Exception:
            jobs.append(path.name)
            continue
        if any(field in job for field in LEGACY_JOB_FIELDS) or int(job.get("schema_version") or 1) < 2:
            jobs.append(str(job.get("job_key") or path.stem))
    conf = _conf_file(config)
    try:
        conf_lines = conf.read_text(encoding="utf-8").splitlines() if conf.is_file() else []
    except OSError:
        conf_lines = []
    legacy_keys = _legacy_conf_keys(conf_lines)
    repository_file = _repositories_file(config)
    try:
        repository_payload = json.loads(repository_file.read_text(encoding="utf-8")) if repository_file.is_file() else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        repository_payload = {}
    repository_rows = repository_payload.get("repositories") if isinstance(repository_payload, dict) else []
    repository_rows = repository_rows if isinstance(repository_rows, list) else []
    repositories_to_clean = [
        str(row.get("repository_key") or "")
        for row in repository_rows if isinstance(row, dict)
        and any(field in row for field in LEGACY_REPOSITORY_FIELDS)
    ]
    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "required": bool(jobs or legacy_keys or repositories_to_clean),
        "jobs_to_migrate": jobs,
        "legacy_conf_keys": legacy_keys,
        "repositories_to_clean": repositories_to_clean,
    }


def _canonical_job(
    config: dict,
    path: Path,
    expanded_conf: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    job = _read_job(path)
    job_key = str(job.get("job_key") or path.stem).strip()
    if not job_key:
        raise ValueError(f"Job key is missing: {path.name}")
    context = resolve_job_repository_context(config, job_key, job=job, allow_legacy_job=True)

    legacy_repo = job.get("repo") if isinstance(job.get("repo"), dict) else {}
    legacy_conf_key = str(legacy_repo.get("conf_key") or "").strip()
    legacy_path_value = (
        expanded_conf.get(legacy_conf_key, legacy_repo.get("default"))
        if legacy_conf_key
        else legacy_repo.get("default")
    )
    legacy_path = str(legacy_path_value or "").strip().rstrip("/")
    canonical_path = str(context.get("repository_path") or "").strip().rstrip("/")
    if legacy_path and legacy_path != canonical_path:
        raise ValueError(
            f"Job '{job_key}' repository path differs from its repository object: "
            f"{legacy_path} != {canonical_path}"
        )

    legacy_passphrase = job.get("passphrase") if isinstance(job.get("passphrase"), dict) else {}
    legacy_passphrase_key = str(legacy_passphrase.get("conf_key") or "").strip()
    legacy_passphrase_value = (
        expanded_conf.get(legacy_passphrase_key, legacy_passphrase.get("default"))
        if legacy_passphrase_key
        else legacy_passphrase.get("default")
    )
    legacy_passphrase_ref = str(legacy_passphrase_value or "").strip()
    canonical_passphrase_ref = str(context.get("passphrase_ref") or "").strip()
    if legacy_passphrase_ref and legacy_passphrase_ref != canonical_passphrase_ref:
        raise ValueError(
            f"Job '{job_key}' passphrase reference differs from its repository object: "
            f"{legacy_passphrase_ref} != {canonical_passphrase_ref}"
        )

    legacy_encryption = str(job.get("encryption") or "").strip().lower()
    canonical_encryption = str(context.get("encryption") or "").strip().lower()
    if legacy_encryption and legacy_encryption != canonical_encryption:
        raise ValueError(
            f"Job '{job_key}' encryption differs from its repository object: "
            f"{legacy_encryption} != {canonical_encryption}"
        )

    cleaned = {key: value for key, value in job.items() if key not in LEGACY_JOB_FIELDS}
    cleaned["schema_version"] = 2
    cleaned["repository_key"] = context["repository_key"]
    cleaned["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return cleaned, context


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{MIGRATION_ID}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _canonical_repositories(config: dict) -> tuple[dict[str, Any], list[str]]:
    from repositories_api import read_repository_store
    from repository_context import repository_path, storage_by_key

    store = read_repository_store(config)
    cleaned_rows: list[dict[str, Any]] = []
    cleaned_keys: list[str] = []
    for repository in store.get("repositories", []):
        key = str(repository.get("repository_key") or "").strip()
        storage = storage_by_key(config, str(repository.get("storage_key") or ""))
        repository_path(repository, storage)
        encryption = str(repository.get("encryption") or "").strip().lower()
        if not encryption:
            raise ValueError(f"Repository '{key}' encryption metadata is missing")
        passphrase_ref = str(repository.get("passphrase_ref") or "").strip()
        if encryption != "none" and (not passphrase_ref or not Path(passphrase_ref).is_file()):
            raise ValueError(f"Repository '{key}' passphrase file does not exist")
        if any(field in repository for field in LEGACY_REPOSITORY_FIELDS):
            cleaned_keys.append(key)
        cleaned_rows.append({
            field: value
            for field, value in repository.items()
            if field not in LEGACY_REPOSITORY_FIELDS
        })
    return {
        "schema_version": int(store.get("schema_version") or 1),
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "repositories": cleaned_rows,
    }, cleaned_keys


def apply(config: dict) -> dict[str, Any]:
    detected = detect(config)
    if not bool(detected.get("required")):
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "not_required",
            "details": detected,
        }
    jobs_dir = _jobs_dir(config)
    job_files = sorted(jobs_dir.glob("*.json")) if jobs_dir.is_dir() else []
    prepared: dict[Path, dict[str, Any]] = {}
    repository_links: list[dict[str, str]] = []
    try:
        from config_api import read_expanded_conf, read_raw_conf

        expanded_conf = read_expanded_conf(config)
        expanded_conf.update(_expand_raw_conf(read_raw_conf(config)))
        for path in job_files:
            cleaned, context = _canonical_job(config, path, expanded_conf)
            prepared[path] = cleaned
            repository_links.append({
                "job_key": str(cleaned.get("job_key") or path.stem),
                "repository_key": str(context.get("repository_key") or ""),
                "storage_key": str(context.get("storage_key") or ""),
            })
        repository_payload, cleaned_repository_keys = _canonical_repositories(config)
    except (OSError, ValueError, RepositoryContextError, json.JSONDecodeError) as exc:
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "failed",
            "details": {"error": str(exc), "validated_jobs": len(prepared)},
        }

    conf = _conf_file(config)
    try:
        conf_lines = conf.read_text(encoding="utf-8").splitlines(keepends=True) if conf.is_file() else []
    except OSError as exc:
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "failed",
            "details": {"error": str(exc), "conf_file": str(conf)},
        }
    removed_keys = _legacy_conf_keys([line.rstrip("\n") for line in conf_lines])
    next_conf = "".join(line for line in conf_lines if _assignment_key(line) not in removed_keys)

    baseline_backup = str(config.get("_CANONICAL_BASELINE_BACKUP_DIR") or "").strip()
    owns_backup = not baseline_backup
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = (
        Path(baseline_backup)
        if baseline_backup
        else _data_root(config) / "config" / "migration-backups" / f"{MIGRATION_ID}-{timestamp}"
    )
    if owns_backup:
        backup_dir.mkdir(parents=True, exist_ok=False)
    try:
        if owns_backup:
            for path in job_files:
                shutil.copy2(path, backup_dir / path.name)
            if conf.is_file():
                shutil.copy2(conf, backup_dir / conf.name)
        repository_file = _repositories_file(config)
        if owns_backup and repository_file.is_file():
            shutil.copy2(repository_file, backup_dir / repository_file.name)

        for path, payload in prepared.items():
            _write_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        if conf_lines:
            _write_atomic(conf, next_conf)
        _write_atomic(repository_file, json.dumps(repository_payload, ensure_ascii=False, indent=2) + "\n")
    except Exception as exc:
        if owns_backup:
            for path in job_files:
                source = backup_dir / path.name
                if source.is_file():
                    shutil.copy2(source, path)
            conf_backup = backup_dir / conf.name
            if conf_backup.is_file():
                shutil.copy2(conf_backup, conf)
            repository_backup = backup_dir / _repositories_file(config).name
            if repository_backup.is_file():
                shutil.copy2(repository_backup, _repositories_file(config))
        return {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "status": "failed",
            "details": {
                "error": str(exc),
                "rollback": "restored" if owns_backup else "delegated_to_baseline",
                "backup_dir": str(backup_dir),
            },
        }

    return {
        "migration_id": MIGRATION_ID,
        "introduced_in": INTRODUCED_IN,
        "runner": "central_migration_registry",
        "status": "applied",
        "details": {
            "migration_id": MIGRATION_ID,
            "introduced_in": INTRODUCED_IN,
            "runner": "central_migration_registry",
            "backup_dir": str(backup_dir),
            "migrated_jobs": [str(payload.get("job_key") or path.stem) for path, payload in prepared.items()],
            "migrated_job_count": len(prepared),
            "repository_links": repository_links,
            "cleaned_repository_keys": cleaned_repository_keys,
            "removed_conf_keys": removed_keys,
            "actions": [
                f"converted {len(prepared)} job(s) to repository_key-only metadata",
                f"removed {len(removed_keys)} deprecated repository/passphrase config key(s)",
                f"removed legacy profile/config fields from {len(cleaned_repository_keys)} repository object(s)",
            ],
        },
    }
