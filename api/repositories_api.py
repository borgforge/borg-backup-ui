"""Repository object inventory for Borg Backup UI.

Repository objects are the canonical metadata inventory for Borg repositories.
They can also be created or imported through the repository manager; backup jobs
only reference these objects.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit


SCHEMA_VERSION = 1
ALLOWED_ENCRYPTION_MODES = {
    "repokey-blake2",
    "repokey",
    "keyfile-blake2",
    "keyfile",
    "authenticated-blake2",
    "authenticated",
    "none",
}


class RepositoryBusyError(RuntimeError):
    """The repository is healthy but currently used by another operation."""


class RepositoryLifecycleConflict(RuntimeError):
    """A repository cannot be removed while references or operations exist."""

    def __init__(self, message: str, code: str = "repository_lifecycle_conflict") -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _data_root(config: dict) -> Path:
    raw = str(config.get("BACKUP_SCRIPTS_DIR", "/boot/config/borg-backup")).strip() or "/boot/config/borg-backup"
    base = Path(raw)
    return base.parent if base.name == "scripts" else base


def repositories_file(config: dict) -> Path:
    return _data_root(config) / "config" / "repositories.json"


def _slug(value: str, fallback: str = "repository") -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text or fallback


def _hash_suffix(value: str) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:8]


def _repo_identity(path_or_uri: str) -> str:
    text = str(path_or_uri or "").strip()
    if not text:
        return ""
    if "://" in text:
        return text.rstrip("/")
    return text.rstrip("/")


def repository_key_for(seed: str, identity: str) -> str:
    base = _slug(seed, "repository")
    if not base.startswith("repo_"):
        base = f"repo_{base}"
    suffix = _hash_suffix(_repo_identity(identity))
    if base.endswith(f"_{suffix}"):
        return base
    return f"{base}_{suffix}"


def repository_name_from_path(path_or_uri: str) -> str:
    text = str(path_or_uri or "").strip()
    if not text:
        return ""
    parsed_path = urlsplit(text).path if "://" in text else text
    name = unquote(parsed_path.rstrip("/").rsplit("/", 1)[-1]).strip()
    return name or text.rstrip("/").rsplit("/", 1)[-1].strip()


def _normalize_repo_segment(value: str) -> str:
    text = str(value or "").strip().strip("/")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._")
    if not text:
        raise ValueError("Repository name must not be empty")
    if text in {".", ".."} or "/" in text:
        raise ValueError("Repository name must be a single path segment")
    return text


def _safe_relative_path(value: str) -> str:
    text = str(value or "").strip().strip("/")
    if not text:
        raise ValueError("Repository path must not be empty")
    parts = []
    for raw in text.split("/"):
        part = raw.strip()
        if not part or part in {".", ".."}:
            raise ValueError("Repository path contains unsafe path segments")
        parts.append(_normalize_repo_segment(part))
    return "/".join(parts)


def _join_path(base: str, relative: str) -> str:
    b = str(base or "").strip().rstrip("/")
    r = _safe_relative_path(relative)
    if not b:
        raise ValueError("Storage base path is missing")
    if "://" in b:
        parsed = urlsplit(b)
        path = "/".join(part for part in (parsed.path.rstrip("/"), quote(r, safe="/._-")) if part)
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))
    return f"{b}/{r}" if b != "/" else f"/{r}"


def effective_repository_path(storage: dict[str, Any], relative_path: str) -> str:
    """Build the effective Borg repository path/URI for a storage object."""
    if not isinstance(storage, dict):
        raise ValueError("Storage target is missing")
    location = str(storage.get("location") or storage.get("storage_type") or "").strip().lower()
    relative = _safe_relative_path(relative_path)
    if location == "storagebox" or str(storage.get("storage_type") or "").strip().lower() == "ssh":
        user = str(storage.get("user") or "").strip()
        host = str(storage.get("host") or "").strip()
        port = str(storage.get("port") or "23").strip() or "23"
        base_path = str(storage.get("base_path") or "").strip() or "/./backup"
        if not user or not host:
            raise ValueError("SSH storage target is incomplete")
        if base_path.startswith("./"):
            base_path = f"/{base_path}"
        elif not base_path.startswith("/"):
            base_path = f"/{base_path}"
        base_path = base_path.rstrip("/") or "/"
        return f"ssh://{quote(user, safe='')}@{host}:{port}{base_path}/{quote(relative, safe='/._-')}"
    base_path = str(storage.get("base_path") or storage.get("mount_path") or "").strip()
    return _join_path(base_path, relative)


def _storage_name_from_location(location: str) -> str:
    return {
        "local": "Local",
        "usb": "USB",
        "smb": "SMB",
        "storagebox": "Storagebox",
    }.get(str(location or "").strip().lower(), str(location or "").strip())


def enrich_repository_display_fields(repo: dict[str, Any]) -> dict[str, Any]:
    row = dict(repo or {})
    path_raw = str(row.get("path_raw") or row.get("repo_uri") or row.get("repo_path") or "").strip()
    display_name = str(row.get("display_name") or "").strip()
    job_name = str(row.get("job_name") or "").strip()
    if not job_name:
        job_name = str(row.get("display_name") or row.get("backup_type") or row.get("repository_key") or "").strip()

    repository_name = str(row.get("repository_name") or "").strip()
    if not repository_name:
        repository_name = repository_name_from_path(path_raw)
    if not repository_name:
        repository_name = str(row.get("repository_key") or "").strip()

    storage_name = str(row.get("storage_name") or "").strip()
    if not storage_name:
        storage_name = _storage_name_from_location(str(row.get("location") or row.get("storage_type") or ""))

    row["repository_name"] = repository_name
    row["job_name"] = job_name
    row["storage_name"] = storage_name
    row["display_name"] = display_name or repository_name or job_name or str(row.get("repository_key") or "").strip()
    return row


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def read_repository_store(config: dict) -> dict[str, Any]:
    payload = _read_json_file(repositories_file(config))
    rows = payload.get("repositories") if isinstance(payload.get("repositories"), list) else []
    normalized = normalize_repositories(rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": str(payload.get("updated_at") or ""),
        "repositories": normalized,
    }


def write_repository_store(config: dict, store: dict[str, Any]) -> None:
    path = repositories_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now(),
        "repositories": normalize_repositories(store.get("repositories") if isinstance(store, dict) else []),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_repositories(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        key = _slug(str(row.get("repository_key") or row.get("key") or ""), "")
        path_raw = str(row.get("path_raw") or row.get("repo_uri") or row.get("repo_path") or "").strip()
        if not key or not path_raw or key in seen:
            continue
        seen.add(key)
        location = str(row.get("location") or row.get("storage_type") or "").strip().lower()
        source_job_keys = row.get("source_job_keys") if isinstance(row.get("source_job_keys"), list) else []
        source_job_keys = [str(item).strip() for item in source_job_keys if str(item).strip()]
        used_by = row.get("used_by") if isinstance(row.get("used_by"), list) else source_job_keys
        used_by = [str(item).strip() for item in used_by if str(item).strip()]
        repo_uri = str(row.get("repo_uri") or "").strip()
        repo_path = str(row.get("repo_path") or "").strip()
        if "://" in path_raw and not repo_uri:
            repo_uri = path_raw
        if "://" not in path_raw and not repo_path:
            repo_path = path_raw
        normalized = enrich_repository_display_fields({
            "repository_key": key,
            "display_name": str(row.get("display_name") or key).strip() or key,
            "backup_type": str(row.get("backup_type") or "").strip().lower(),
            "location": location,
            "storage_type": str(row.get("storage_type") or location).strip().lower(),
            "storage_key": str(row.get("storage_key") or location).strip(),
            "storage_name": str(row.get("storage_name") or "").strip(),
            "relative_path": str(row.get("relative_path") or repository_name_from_path(path_raw)).strip(),
            "repository_name": str(row.get("repository_name") or "").strip(),
            "job_name": str(row.get("job_name") or "").strip(),
            "repo_path": repo_path,
            "repo_uri": repo_uri,
            "path_raw": path_raw,
            "path_display": str(row.get("path_display") or path_raw).strip(),
            "passphrase_ref": str(row.get("passphrase_ref") or "").strip(),
            "keyfile_ref": str(row.get("keyfile_ref") or "").strip(),
            "encryption": str(row.get("encryption") or "").strip(),
            "append_only": bool(row.get("append_only", False)),
            "storage_quota": str(row.get("storage_quota") or "").strip(),
            "initialized": bool(row.get("initialized", False)),
            "created_by": str(row.get("created_by") or "manual").strip(),
            "created_at": str(row.get("created_at") or "").strip(),
            "updated_at": str(row.get("updated_at") or "").strip(),
            "last_test_status": str(row.get("last_test_status") or "").strip(),
            "last_check_status": str(row.get("last_check_status") or "").strip(),
            "last_seen_at": str(row.get("last_seen_at") or "").strip(),
            "last_info_refresh_at": str(row.get("last_info_refresh_at") or "").strip(),
            "last_info_refresh_status": str(row.get("last_info_refresh_status") or "").strip(),
            "last_info_refresh_error": str(row.get("last_info_refresh_error") or "").strip(),
            "borg_repository_id": str(row.get("borg_repository_id") or "").strip(),
            "borg_last_modified": str(row.get("borg_last_modified") or "").strip(),
            "repository_stats": row.get("repository_stats") if isinstance(row.get("repository_stats"), dict) else {},
            "maintenance_results": row.get("maintenance_results") if isinstance(row.get("maintenance_results"), dict) else {},
            "offsite_candidate": bool(row.get("offsite_candidate", location == "storagebox")),
            "separate_medium_candidate": bool(row.get("separate_medium_candidate", location in {"usb", "storagebox", "smb"})),
            "source_job_keys": source_job_keys,
            "used_by": used_by,
        })
        for legacy_field in (
            "storage_profile_key",
            "usb_profile_key",
            "smb_profile_key",
            "repo_conf_key",
        ):
            if legacy_field in row or (legacy_field == "repo_conf_key" and "conf_key" in row):
                source_field = "conf_key" if legacy_field == "repo_conf_key" and legacy_field not in row else legacy_field
                normalized[legacy_field] = str(row.get(source_field) or "").strip()
        out.append(normalized)
    out.sort(key=lambda item: (str(item.get("location") or ""), str(item.get("display_name") or "")))
    return out


def build_repository_groups(config: dict) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {"local": [], "usb": [], "smb": [], "storagebox": []}
    for repo in read_repository_store(config)["repositories"]:
        location = str(repo.get("location") or "").strip().lower()
        if location not in groups:
            groups[location] = []
        groups[location].append({
            **repo,
            "conf_key": str(repo.get("repository_key") or ""),
        })
    for rows in groups.values():
        rows.sort(key=lambda row: (str(row.get("backup_type") or ""), str(row.get("display_name") or "")))
    return groups


def _secret_path_for_repository(config: dict, repository_key: str) -> Path:
    return _data_root(config) / "secrets" / f".borg-passphrase-{repository_key}"


def _storage_by_key(config: dict) -> dict[str, dict[str, Any]]:
    from storage_objects_api import read_storage_store
    return {
        str(row.get("storage_key") or ""): row
        for row in read_storage_store(config).get("storages", [])
        if str(row.get("storage_key") or "").strip()
    }


def _repo_env(
    storage: dict[str, Any],
    passphrase_file: Path | None,
    config: dict | None = None,
    *,
    persistent_keys: bool = True,
) -> dict[str, str]:
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    if passphrase_file is not None:
        env["BORG_PASSCOMMAND"] = f"cat {shlex.quote(str(passphrase_file))}"
    ssh_key = str(storage.get("ssh_key_path") or "").strip()
    if ssh_key:
        env["BORG_RSH"] = f"ssh -i {shlex.quote(ssh_key)} -o WarnWeakCrypto=no"
    elif str(storage.get("storage_type") or "").strip().lower() == "ssh":
        env["BORG_RSH"] = "ssh -o WarnWeakCrypto=no"
    if persistent_keys:
        from borg_key_store import apply_borg_key_environment

        env = apply_borg_key_environment(env, config or {})
    return env


def _mask_repo_output(text: str, passphrase: str = "") -> str:
    from security_utils import mask_secrets

    out = mask_secrets(str(text or ""))
    if passphrase:
        out = out.replace(passphrase, "***")
    return out


def _raise_borg_command_error(output: str, fallback: str) -> None:
    safe_output = _mask_repo_output(output)
    lowered = safe_output.lower()
    if "failed to create/acquire the lock" in lowered or "lock.exclusive" in lowered:
        raise RepositoryBusyError("Repository is currently in use by another Borg operation.")
    if "no key file for repository" in lowered or "key file" in lowered and "not found" in lowered:
        raise RuntimeError(
            "The Borg keyfile is missing. Import a matching Borg key export for this repository."
        )
    first = next((line.strip() for line in safe_output.splitlines() if line.strip()), fallback)
    raise RuntimeError(first[:500])


@contextmanager
def _repository_access(config: dict, repository: dict[str, Any]):
    storage = _storage_by_key(config).get(str(repository.get("storage_key") or ""), {})
    if not storage:
        raise ValueError("Repository storage target was not found")
    repo_path = effective_repository_path(storage, str(repository.get("relative_path") or ""))
    cleanup = None
    if str(storage.get("location") or "").lower() == "smb":
        from smb_profiles_api import run_smb_profile_action

        mounted = run_smb_profile_action(config, str(storage.get("profile_key") or ""), "mount")
        if not mounted.get("ok"):
            raise RuntimeError(str(mounted.get("message") or "SMB mount failed"))
        if mounted.get("message_code") == "smb_mount_success":
            profile_key = str(storage.get("profile_key") or "")
            cleanup = lambda: run_smb_profile_action(config, profile_key, "unmount")
    passphrase_ref = str(repository.get("passphrase_ref") or "").strip()
    passphrase_file = Path(passphrase_ref) if passphrase_ref else None
    if passphrase_file is not None and not passphrase_file.is_file():
        raise ValueError("Repository passphrase file is missing")
    try:
        yield storage, repo_path, passphrase_file
    finally:
        if cleanup:
            cleanup()


def _borg_info(config: dict, storage: dict[str, Any], repo_path: str, passphrase_file: Path | None) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["borg", "info", "--json", repo_path],
            capture_output=True,
            text=True,
            timeout=60,
            env=_repo_env(storage, passphrase_file, config),
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("borg binary not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("borg info timed out") from exc
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        _raise_borg_command_error(output, "borg info failed")
    try:
        payload = json.loads(proc.stdout or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("borg info returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("borg info returned an invalid response")
    return payload


def _borg_info_with_default_keys(
    storage: dict[str, Any], repo_path: str, passphrase_file: Path | None
) -> dict[str, Any]:
    """Probe Borg's legacy default key directory during an explicit import."""
    proc = subprocess.run(
        ["borg", "info", "--json", repo_path],
        capture_output=True,
        text=True,
        timeout=60,
        env=_repo_env(storage, passphrase_file, persistent_keys=False),
        check=False,
    )
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        _raise_borg_command_error(output, "borg info failed")
    try:
        payload = json.loads(proc.stdout or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("borg info returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("borg info returned an invalid response")
    return payload


def _import_exported_repository_key(
    config: dict,
    storage: dict[str, Any],
    repo_path: str,
    passphrase_file: Path | None,
    key_data: str,
) -> None:
    from borg_key_store import ensure_borg_keys_dir, find_key_file

    encoded = str(key_data or "").strip().encode("utf-8")
    if not encoded or len(encoded) > 1024 * 1024:
        raise ValueError("Borg key export is empty or too large")
    first = encoded.splitlines()[0].decode("utf-8", "replace").strip()
    if not first.startswith("BORG_KEY "):
        raise ValueError("Borg key export has an invalid format")
    repository_id = first[len("BORG_KEY "):].strip().lower()
    if not repository_id or any(ch not in "0123456789abcdef" for ch in repository_id):
        raise ValueError("Borg key export has an invalid repository ID")
    key_dir = ensure_borg_keys_dir(config)
    existing = find_key_file(key_dir, repository_id)
    if existing is not None:
        if existing.read_bytes().strip() != encoded.strip():
            raise ValueError("A different key for this Borg repository already exists")
        return
    temp_path: Path | None = None
    try:
        import_dir = _data_root(config) / "config"
        import_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=import_dir, prefix=".key-import-", delete=False
        ) as handle:
            handle.write(encoded + b"\n")
            temp_path = Path(handle.name)
        os.chmod(temp_path, 0o600)
        proc = subprocess.run(
            ["borg", "key", "import", repo_path, str(temp_path)],
            capture_output=True,
            text=True,
            timeout=120,
            env=_repo_env(storage, passphrase_file, config),
            check=False,
        )
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            created = find_key_file(key_dir, repository_id)
            if created is not None:
                created.unlink(missing_ok=True)
            _raise_borg_command_error(output, "Borg key import failed")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _borg_list(config: dict, storage: dict[str, Any], repo_path: str, passphrase_file: Path | None) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["borg", "list", "--json", repo_path],
            capture_output=True,
            text=True,
            timeout=60,
            env=_repo_env(storage, passphrase_file, config),
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("borg binary not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("borg list timed out") from exc
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        _raise_borg_command_error(output, "borg list failed")
    try:
        payload = json.loads(proc.stdout or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("borg list returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("borg list returned an invalid response")
    return payload


def _borg_info_fields(payload: dict[str, Any], archive_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    repository = payload.get("repository") if isinstance(payload.get("repository"), dict) else {}
    encryption = payload.get("encryption") if isinstance(payload.get("encryption"), dict) else {}
    cache = payload.get("cache") if isinstance(payload.get("cache"), dict) else {}
    stats = cache.get("stats") if isinstance(cache.get("stats"), dict) else {}
    stats = dict(stats)
    if isinstance(archive_payload, dict):
        archives = archive_payload.get("archives") if isinstance(archive_payload.get("archives"), list) else []
        stats["archives_count"] = len(archives)
    return {
        "encryption": str(encryption.get("mode") or "").strip(),
        "borg_repository_id": str(repository.get("id") or "").strip(),
        "borg_last_modified": str(repository.get("last_modified") or "").strip(),
        "repository_stats": stats,
    }


def refresh_repository_info(config: dict, repository_key: str) -> dict[str, Any]:
    key = str(repository_key or "").strip()
    store = read_repository_store(config)
    rows = store["repositories"]
    repository = next((row for row in rows if str(row.get("repository_key") or "") == key), None)
    if not repository:
        raise ValueError("Repository not found")
    storage = _storage_by_key(config).get(str(repository.get("storage_key") or ""), {})
    repo_path = effective_repository_path(storage, str(repository.get("relative_path") or ""))
    from jobs_api import is_resource_active
    if is_resource_active(config, f"repo:{repo_path}"):
        _record_repository_info_busy(config, key, _now())
        raise RepositoryBusyError("Repository is currently in use by a backup job.")
    cleanup = None
    if str(storage.get("location") or "").lower() == "smb":
        from smb_profiles_api import run_smb_profile_action
        mounted = run_smb_profile_action(config, str(storage.get("profile_key") or ""), "mount")
        if not mounted.get("ok"):
            raise RuntimeError(str(mounted.get("message") or "SMB mount failed"))
        if mounted.get("message_code") == "smb_mount_success":
            profile_key = str(storage.get("profile_key") or "")
            cleanup = lambda: run_smb_profile_action(config, profile_key, "unmount")
    passphrase_ref = str(repository.get("passphrase_ref") or "").strip()
    passphrase_file = Path(passphrase_ref) if passphrase_ref else None
    if passphrase_file is not None and not passphrase_file.is_file():
        raise ValueError("Repository passphrase file is missing")
    try:
        info_payload = _borg_info(config, storage, repo_path, passphrase_file)
        archive_payload = _borg_list(config, storage, repo_path, passphrase_file)
    except RepositoryBusyError:
        _record_repository_info_busy(config, key, _now())
        raise
    finally:
        if cleanup:
            cleanup()
    fields = _borg_info_fields(info_payload, archive_payload)
    refreshed_at = _now()
    latest_store = read_repository_store(config)
    latest_rows = latest_store["repositories"]
    latest_repository = next(
        (row for row in latest_rows if str(row.get("repository_key") or "") == key),
        None,
    )
    if not latest_repository:
        raise ValueError("Repository was removed while its information was refreshed")
    updated = {
        **latest_repository,
        **{field: value for field, value in fields.items() if value not in ("", None, {})},
        "last_test_status": "ok",
        "last_seen_at": refreshed_at,
        "last_info_refresh_at": refreshed_at,
        "last_info_refresh_status": "success",
        "last_info_refresh_error": "",
        "updated_at": refreshed_at,
    }
    write_repository_store(config, {
        "repositories": [updated if str(row.get("repository_key") or "") == key else row for row in latest_rows],
    })
    return {"ok": True, "repository": enrich_repository_display_fields(updated)}


def _parse_repository_timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _repository_info_is_due(
    repository: dict[str, Any],
    now: datetime,
    *,
    max_age_hours: int,
    retry_after_hours: int,
) -> bool:
    status = str(repository.get("last_info_refresh_status") or "").strip().lower()
    stats = repository.get("repository_stats") if isinstance(repository.get("repository_stats"), dict) else {}
    if status != "error" and not stats:
        return True
    timestamp = _parse_repository_timestamp(
        repository.get("last_info_refresh_at") or repository.get("last_seen_at")
    )
    if timestamp is None:
        return True
    hours = retry_after_hours if status in {"error", "busy"} else max_age_hours
    return timestamp <= now - timedelta(hours=max(1, int(hours)))


def _record_repository_info_error(config: dict, repository_key: str, message: str, checked_at: str) -> None:
    store = read_repository_store(config)
    rows = store["repositories"]
    found = False
    next_rows = []
    for row in rows:
        if str(row.get("repository_key") or "") != repository_key:
            next_rows.append(row)
            continue
        found = True
        next_rows.append({
            **row,
            "last_info_refresh_at": checked_at,
            "last_info_refresh_status": "error",
            "last_info_refresh_error": _mask_repo_output(str(message or "Repository information refresh failed"))[:500],
            "updated_at": checked_at,
        })
    if found:
        write_repository_store(config, {"repositories": next_rows})


def _record_repository_info_busy(config: dict, repository_key: str, checked_at: str) -> None:
    store = read_repository_store(config)
    rows = store["repositories"]
    found = False
    next_rows = []
    for row in rows:
        if str(row.get("repository_key") or "") != repository_key:
            next_rows.append(row)
            continue
        found = True
        next_rows.append({
            **row,
            "last_info_refresh_at": checked_at,
            "last_info_refresh_status": "busy",
            "last_info_refresh_error": "Repository information refresh was deferred because the repository is in use.",
            "updated_at": checked_at,
        })
    if found:
        write_repository_store(config, {"repositories": next_rows})


def refresh_due_repository_info(
    config: dict,
    *,
    max_age_hours: int = 24,
    retry_after_hours: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh cached Borg information that is missing, stale, or due for retry."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    repositories = read_repository_store(config)["repositories"]
    from jobs_api import active_resource_locks
    active_resources = {
        str(row.get("resource") or "").strip()
        for row in active_resource_locks(config)
        if str(row.get("resource") or "").strip()
    }
    due_keys = [
        str(row.get("repository_key") or "").strip()
        for row in repositories
        if str(row.get("repository_key") or "").strip()
        and (
            (
                str(row.get("last_info_refresh_status") or "").strip().lower() == "error"
                and f"repo:{str(row.get('path_raw') or row.get('repo_uri') or row.get('repo_path') or '').strip()}" in active_resources
            )
            or _repository_info_is_due(
                row,
                current,
                max_age_hours=max_age_hours,
                retry_after_hours=retry_after_hours,
            )
        )
    ]
    refreshed = 0
    failed = 0
    deferred = 0
    errors = []
    for repository_key in due_keys:
        try:
            refresh_repository_info(config, repository_key)
            refreshed += 1
        except RepositoryBusyError:
            deferred += 1
            _record_repository_info_busy(config, repository_key, _now())
        except Exception as exc:
            failed += 1
            safe_message = _mask_repo_output(str(exc or "Repository information refresh failed"))[:500]
            _record_repository_info_error(config, repository_key, safe_message, _now())
            errors.append({"repository_key": repository_key, "error": safe_message})
    return {
        "checked": len(repositories),
        "due": len(due_keys),
        "refreshed": refreshed,
        "failed": failed,
        "deferred": deferred,
        "errors": errors,
    }


def get_repository_archives(config: dict, repository_key: str, limit: int = 100) -> dict[str, Any]:
    key = str(repository_key or "").strip()
    maximum = max(1, min(int(limit or 100), 500))
    store = read_repository_store(config)
    repository = next(
        (row for row in store.get("repositories", []) if str(row.get("repository_key") or "") == key),
        None,
    )
    if not repository:
        raise ValueError("Repository not found")
    storage = _storage_by_key(config).get(str(repository.get("storage_key") or ""), {})
    cleanup = None
    if str(storage.get("location") or "").lower() == "smb":
        from smb_profiles_api import run_smb_profile_action
        mounted = run_smb_profile_action(config, str(storage.get("profile_key") or ""), "mount")
        if not mounted.get("ok"):
            raise RuntimeError(str(mounted.get("message") or "SMB mount failed"))
        if mounted.get("message_code") == "smb_mount_success":
            profile_key = str(storage.get("profile_key") or "")
            cleanup = lambda: run_smb_profile_action(config, profile_key, "unmount")
    repo_path = effective_repository_path(storage, str(repository.get("relative_path") or ""))
    passphrase_ref = str(repository.get("passphrase_ref") or "").strip()
    passphrase_file = Path(passphrase_ref) if passphrase_ref else None
    if passphrase_file is not None and not passphrase_file.is_file():
        raise ValueError("Repository passphrase file is missing")
    try:
        payload = _borg_list(config, storage, repo_path, passphrase_file)
    finally:
        if cleanup:
            cleanup()
    rows = payload.get("archives") if isinstance(payload.get("archives"), list) else []
    rows = [row for row in rows if isinstance(row, dict)]
    rows.sort(
        key=lambda row: (
            _parse_repository_timestamp(row.get("start") or row.get("end"))
            or datetime.min.replace(tzinfo=timezone.utc),
            str(row.get("name") or ""),
        ),
        reverse=True,
    )
    archives = []
    for row in rows[:maximum]:
        archives.append({
            "name": str(row.get("name") or ""),
            "id": str(row.get("id") or ""),
            "start": str(row.get("start") or ""),
            "end": str(row.get("end") or ""),
            "duration": row.get("duration"),
        })
    return {"repository_key": key, "archive_count": len(rows), "archives": archives}


def _repository_lifecycle_audit_file(config: dict) -> Path:
    return _data_root(config) / "config" / "repository-lifecycle.log.jsonl"


def _write_repository_lifecycle_audit(
    config: dict,
    repository: dict[str, Any],
    *,
    action: str,
    status: str,
    details: dict[str, Any] | None = None,
    audit_context: dict[str, Any] | None = None,
) -> None:
    path = _repository_lifecycle_audit_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    context = audit_context if isinstance(audit_context, dict) else {}
    payload = {
        "timestamp": _now(),
        "action": str(action or ""),
        "status": str(status or ""),
        "actor": str(context.get("actor") or "system"),
        "actor_role": str(context.get("actor_role") or "system"),
        "auth_method": str(context.get("auth_method") or "internal"),
        "request_id": str(context.get("request_id") or ""),
        "repository_key": str(repository.get("repository_key") or ""),
        "repository_id": str(repository.get("borg_repository_id") or ""),
        "display_name": str(repository.get("display_name") or ""),
        "storage_key": str(repository.get("storage_key") or ""),
        "details": details if isinstance(details, dict) else {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _repository_lifecycle_context(config: dict, repository_key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    from check_api import CheckManager
    from jobs_api import JobManager, is_resource_active
    from repository_context import jobs_using_repository
    from restore_api import list_restore_runs

    key = str(repository_key or "").strip()
    store = read_repository_store(config)
    repository = next(
        (row for row in store.get("repositories", []) if str(row.get("repository_key") or "") == key),
        None,
    )
    if not repository:
        raise ValueError("Repository not found")
    storage = _storage_by_key(config).get(str(repository.get("storage_key") or ""), {})
    if not storage:
        raise ValueError("Repository storage target was not found")
    repo_path = effective_repository_path(storage, str(repository.get("relative_path") or ""))
    jobs = jobs_using_repository(config, key)
    blockers: list[str] = []
    if jobs:
        blockers.append("jobs_linked")
    if is_resource_active(config, f"repo:{repo_path}"):
        blockers.append("repository_active")
    maintenance = CheckManager.get().get_state()
    if maintenance.get("running") and str(maintenance.get("target_key") or "") == key:
        blockers.append("maintenance_running")
    if JobManager.get().get_state("restore_test").get("running"):
        blockers.append("restore_test_running")
    if list_restore_runs(config, 50).get("active"):
        blockers.append("restore_running")
    blockers = list(dict.fromkeys(blockers))
    stats = repository.get("repository_stats") if isinstance(repository.get("repository_stats"), dict) else {}
    return repository, {
        "repository_key": key,
        "display_name": str(repository.get("display_name") or repository.get("repository_name") or key),
        "repository_name": str(repository.get("repository_name") or ""),
        "repository_path": repo_path,
        "storage_name": str(storage.get("display_name") or repository.get("storage_name") or ""),
        "repository_id": str(repository.get("borg_repository_id") or ""),
        "archive_count": _nonnegative_int(stats.get("archives_count")),
        "deduplicated_size": _nonnegative_int(stats.get("unique_csize")),
        "job_keys": jobs,
        "blockers": blockers,
        "allowed": not blockers,
    }


def prepare_repository_lifecycle(config: dict, repository_key: str, mode: str) -> dict[str, Any]:
    requested_mode = str(mode or "remove").strip().lower()
    if requested_mode not in {"remove", "delete"}:
        raise ValueError("Repository lifecycle mode is invalid")
    repository, context = _repository_lifecycle_context(config, repository_key)
    if not context["allowed"] or requested_mode == "remove":
        return {"ok": True, "mode": requested_mode, **context}

    with _repository_access(config, repository) as (storage, repo_path, passphrase_file):
        info_payload = _borg_info(config, storage, repo_path, passphrase_file)
        archive_payload = _borg_list(config, storage, repo_path, passphrase_file)
    fields = _borg_info_fields(info_payload, archive_payload)
    live_stats = fields.get("repository_stats") if isinstance(fields.get("repository_stats"), dict) else {}
    context.update({
        "repository_id": str(fields.get("borg_repository_id") or ""),
        "archive_count": _nonnegative_int(live_stats.get("archives_count")),
        "deduplicated_size": _nonnegative_int(live_stats.get("unique_csize")),
    })
    if not context["repository_id"]:
        raise RuntimeError("Borg did not return a repository ID")
    return {"ok": True, "mode": requested_mode, **context}


def _remove_repository_metadata(config: dict, repository_key: str) -> dict[str, Any]:
    key = str(repository_key or "").strip()
    store = read_repository_store(config)
    repository = next(
        (row for row in store.get("repositories", []) if str(row.get("repository_key") or "") == key),
        None,
    )
    if not repository:
        raise ValueError("Repository not found")
    remaining = [row for row in store.get("repositories", []) if str(row.get("repository_key") or "") != key]
    write_repository_store(config, {"repositories": remaining})
    return repository


def _remove_repository_secret(config: dict, repository: dict[str, Any]) -> bool:
    raw = str(repository.get("passphrase_ref") or "").strip()
    if not raw:
        return False
    candidate = Path(raw)
    secrets_root = (_data_root(config) / "secrets").resolve()
    try:
        if candidate.parent.resolve() != secrets_root or not candidate.name.startswith(".borg-passphrase-"):
            return False
    except OSError:
        return False
    for row in read_repository_store(config).get("repositories", []):
        if str(row.get("passphrase_ref") or "").strip() == raw:
            return False
    try:
        if candidate.is_symlink() or candidate.exists():
            candidate.unlink()
            return True
    except OSError:
        return False
    return False


def apply_repository_lifecycle(
    config: dict,
    payload: dict[str, Any],
    *,
    audit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid repository lifecycle payload")
    key = str(payload.get("repository_key") or "").strip()
    mode = str(payload.get("mode") or "remove").strip().lower()
    if mode not in {"remove", "delete"}:
        raise ValueError("Repository lifecycle mode is invalid")
    repository, context = _repository_lifecycle_context(config, key)
    display_name = str(repository.get("display_name") or repository.get("repository_name") or key)
    if str(payload.get("confirmation_name") or "") != display_name:
        raise ValueError("Repository display name confirmation does not match")
    if not context["allowed"]:
        raise RepositoryLifecycleConflict(
            "Repository cannot be removed while jobs or operations are active",
            code="repository_lifecycle_blocked",
        )

    if mode == "remove":
        removed = _remove_repository_metadata(config, key)
        _write_repository_lifecycle_audit(
            config,
            removed,
            action="remove_from_inventory",
            status="success",
            details={"repository_data_deleted": False, "secret_deleted": False},
            audit_context=audit_context,
        )
        return {"ok": True, "mode": mode, "repository_key": key, "repository_deleted": False, "secret_deleted": False}

    if str(payload.get("confirmation_phrase") or "") != "DELETE":
        raise ValueError("Permanent repository deletion requires DELETE confirmation")
    expected_id = str(payload.get("expected_repository_id") or "").strip()
    expected_path = str(payload.get("expected_repository_path") or "").strip()
    try:
        expected_archives = int(payload.get("expected_archive_count"))
    except (TypeError, ValueError):
        raise ValueError("Expected archive count is required") from None
    if not expected_id or expected_path != context["repository_path"]:
        raise ValueError("Repository identity confirmation is incomplete")

    try:
        with _repository_access(config, repository) as (storage, repo_path, passphrase_file):
            info_payload = _borg_info(config, storage, repo_path, passphrase_file)
            archive_payload = _borg_list(config, storage, repo_path, passphrase_file)
            live_fields = _borg_info_fields(info_payload, archive_payload)
            live_id = str(live_fields.get("borg_repository_id") or "").strip()
            live_stats = live_fields.get("repository_stats") if isinstance(live_fields.get("repository_stats"), dict) else {}
            live_archives = _nonnegative_int(live_stats.get("archives_count"))
            if live_id != expected_id or live_archives != expected_archives:
                raise RepositoryLifecycleConflict(
                    "Repository identity or archive count changed; repeat the deletion review",
                    code="repository_identity_changed",
                )
            env = _repo_env(storage, passphrase_file, config)
            env["BORG_DELETE_I_KNOW_WHAT_I_AM_DOING"] = "YES"
            timeout_raw = str(config.get("REPOSITORY_DELETE_TIMEOUT_SECONDS") or "3600").strip()
            try:
                timeout = max(60, min(int(timeout_raw), 86400))
            except ValueError:
                timeout = 3600
            proc = subprocess.run(
                ["borg", "delete", "--lock-wait", "30", repo_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )
            output = _mask_repo_output(((proc.stdout or "") + "\n" + (proc.stderr or "")).strip())
            if proc.returncode != 0:
                _raise_borg_command_error(output, f"borg delete failed with exit {proc.returncode}")
    except Exception as exc:
        _write_repository_lifecycle_audit(
            config,
            repository,
            action="delete_repository",
            status="failed",
            details={"error": _mask_repo_output(str(exc))[:500]},
            audit_context=audit_context,
        )
        raise

    removed = _remove_repository_metadata(config, key)
    secret_deleted = _remove_repository_secret(config, removed)
    from borg_key_store import remove_repository_key

    keyfile_deleted = remove_repository_key(
        config,
        str(removed.get("borg_repository_id") or ""),
        [
            str(row.get("borg_repository_id") or "")
            for row in read_repository_store(config).get("repositories", [])
        ],
    )
    _write_repository_lifecycle_audit(
        config,
        removed,
        action="delete_repository",
        status="success",
        details={
            "archive_count": expected_archives,
            "secret_deleted": secret_deleted,
            "keyfile_deleted": keyfile_deleted,
        },
        audit_context=audit_context,
    )
    return {
        "ok": True,
        "mode": mode,
        "repository_key": key,
        "repository_deleted": True,
        "secret_deleted": secret_deleted,
        "keyfile_deleted": keyfile_deleted,
    }


def create_or_import_repository(config: dict, payload: dict[str, Any]) -> dict[str, Any]:
    """Create/import a repository object, optionally running borg init.

    The command is intentionally scoped to repository management. Backup jobs
    should only select existing repository objects.
    """
    if not isinstance(payload, dict):
        raise ValueError("Invalid repository payload")
    action = str(payload.get("action") or "import").strip().lower()
    if action not in {"import", "create"}:
        raise ValueError("Invalid repository action")
    storage_key = str(payload.get("storage_key") or "").strip()
    storages = _storage_by_key(config)
    storage = storages.get(storage_key)
    if not storage:
        raise ValueError("Storage target not found")

    display_name = str(payload.get("display_name") or "").strip()
    repo_name = _normalize_repo_segment(str(payload.get("repository_name") or display_name or "repository"))
    relative_path = _safe_relative_path(str(payload.get("relative_path") or repo_name))
    repo_path = effective_repository_path(storage, relative_path)
    location = str(storage.get("location") or storage.get("storage_type") or "").strip().lower()
    encryption = str(payload.get("encryption") or ("repokey-blake2" if action == "create" else "auto")).strip()
    if action == "create" and encryption not in ALLOWED_ENCRYPTION_MODES:
        raise ValueError("Invalid Borg encryption mode")
    if action == "import" and encryption not in {*ALLOWED_ENCRYPTION_MODES, "auto"}:
        raise ValueError("Invalid Borg encryption mode")
    append_only = bool(payload.get("append_only", False))
    make_parent_dirs = bool(payload.get("make_parent_dirs", True))
    storage_quota = str(payload.get("storage_quota") or "").strip()
    if action != "create":
        append_only = False
        make_parent_dirs = False
        storage_quota = ""
    if storage_quota and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?[KMGTP]?", storage_quota, re.IGNORECASE):
        raise ValueError("Invalid storage quota")

    seed = f"repo_{repo_name}_{location}"
    repo_key = repository_key_for(seed, repo_path)
    store = read_repository_store(config)
    rows = store["repositories"]
    existing = next((row for row in rows if _repo_identity(row.get("path_raw") or "") == _repo_identity(repo_path)), None)

    passphrase_ref = str((existing or {}).get("passphrase_ref") or "").strip()
    passphrase_file: Path | None = None
    passphrase = str(payload.get("passphrase") or "").strip()
    key_data = str(payload.get("key_data") or "").strip()
    secret_previous: bytes | None = None
    secret_existed = False

    def restore_secret() -> None:
        if passphrase_file is None or not passphrase:
            return
        if secret_existed:
            passphrase_file.write_bytes(secret_previous or b"")
            passphrase_file.chmod(0o600)
        else:
            passphrase_file.unlink(missing_ok=True)

    if encryption != "none":
        passphrase_file = Path(passphrase_ref) if passphrase_ref else _secret_path_for_repository(config, repo_key)
        passphrase_ref = str(passphrase_file)
        if action == "create" and not passphrase:
            raise ValueError("Passphrase is required for encrypted repository creation")
        if action == "import" and not passphrase and not passphrase_file.is_file():
            passphrase_file = None
            passphrase_ref = ""
        if passphrase:
            assert passphrase_file is not None
            secret_existed = passphrase_file.exists()
            secret_previous = passphrase_file.read_bytes() if secret_existed else None
            passphrase_file.parent.mkdir(parents=True, exist_ok=True)
            passphrase_file.write_text(passphrase, encoding="utf-8")
            passphrase_file.chmod(0o600)

    output = ""
    exit_code = 0
    initialized = False
    info_fields: dict[str, Any] = {}
    if action == "create":
        cmd = ["borg", "init", f"--encryption={encryption}"]
        if append_only:
            cmd.append("--append-only")
        if storage_quota:
            cmd.extend(["--storage-quota", storage_quota])
        if make_parent_dirs:
            cmd.append("--make-parent-dirs")
        cmd.append(repo_path)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=_repo_env(storage, passphrase_file, config),
                check=False,
            )
            exit_code = proc.returncode
            output = _mask_repo_output(((proc.stdout or "") + "\n" + (proc.stderr or "")).strip(), passphrase)
        except FileNotFoundError:
            restore_secret()
            raise ValueError("borg binary not found")
        except subprocess.TimeoutExpired:
            restore_secret()
            raise TimeoutError("borg init timed out")
        if exit_code != 0:
            restore_secret()
            raise RuntimeError(output.splitlines()[0] if output.splitlines() else f"borg init failed with exit {exit_code}")
        initialized = True
        try:
            info_fields = _borg_info_fields(_borg_info(config, storage, repo_path, passphrase_file))
        except Exception:
            info_fields = {}
    else:
        try:
            if key_data:
                _import_exported_repository_key(
                    config, storage, repo_path, passphrase_file, key_data
                )
            try:
                info_payload = _borg_info(config, storage, repo_path, passphrase_file)
            except Exception as persistent_error:
                if key_data:
                    raise
                try:
                    legacy_payload = _borg_info_with_default_keys(storage, repo_path, passphrase_file)
                    legacy_fields = _borg_info_fields(legacy_payload)
                    from borg_key_store import import_default_key_if_present

                    copied = import_default_key_if_present(
                        config, str(legacy_fields.get("borg_repository_id") or "")
                    )
                    if copied is None:
                        raise persistent_error
                    info_payload = _borg_info(config, storage, repo_path, passphrase_file)
                except Exception:
                    raise persistent_error
            info_fields = _borg_info_fields(info_payload)
        except Exception:
            restore_secret()
            raise
        initialized = True
        detected_encryption = str(info_fields.get("encryption") or "").strip()
        if detected_encryption:
            encryption = detected_encryption
        elif encryption == "auto":
            encryption = "unknown"

    if existing:
        repo_key = str(existing.get("repository_key") or repo_key)
        passphrase_ref = str(existing.get("passphrase_ref") or passphrase_ref)

    now = _now()
    existing = existing if isinstance(existing, dict) else {}
    keyfile_ref = str(existing.get("keyfile_ref") or "").strip()
    if str(info_fields.get("borg_repository_id") or ""):
        from borg_key_store import borg_keys_dir, find_key_file, is_keyfile_encryption

        if is_keyfile_encryption(encryption):
            key_file = find_key_file(
                borg_keys_dir(config), str(info_fields.get("borg_repository_id") or "")
            )
            keyfile_ref = str(key_file) if key_file is not None else ""
        else:
            keyfile_ref = ""
    row = {
        **existing,
        "repository_key": repo_key,
        "display_name": display_name or repo_name,
        "repository_name": repo_name,
        "job_name": str((existing or {}).get("job_name") or "").strip(),
        "backup_type": str((existing or {}).get("backup_type") or "").strip(),
        "location": location,
        "storage_type": str(storage.get("storage_type") or location).strip().lower(),
        "storage_key": storage_key,
        "storage_name": str(storage.get("display_name") or "").strip(),
        "relative_path": relative_path,
        "repo_path": "" if repo_path.startswith("ssh://") else repo_path,
        "repo_uri": repo_path if repo_path.startswith("ssh://") else "",
        "path_raw": repo_path,
        "path_display": repo_path,
        "passphrase_ref": passphrase_ref,
        "keyfile_ref": keyfile_ref,
        "encryption": encryption,
        "append_only": append_only,
        "storage_quota": storage_quota,
        "initialized": initialized,
        "created_by": str(existing.get("created_by") or action),
        "created_at": str(existing.get("created_at") or now),
        "updated_at": now,
        **{key: value for key, value in info_fields.items() if value not in ("", None, {})},
        "last_test_status": "ok",
        "last_seen_at": now,
        "last_info_refresh_at": now,
        "last_info_refresh_status": "success",
        "last_info_refresh_error": "",
        "source_job_keys": existing.get("source_job_keys", []),
        "used_by": existing.get("used_by", []),
    }
    for legacy_field in ("storage_profile_key", "usb_profile_key", "smb_profile_key", "repo_conf_key", "conf_key"):
        row.pop(legacy_field, None)
    next_rows = [item for item in rows if str(item.get("repository_key") or "") != repo_key]
    next_rows.append(row)
    write_repository_store(config, {"repositories": next_rows})
    return {
        "ok": True,
        "action": action,
        "repository": enrich_repository_display_fields(row),
        "exit_code": exit_code,
        "output": output,
    }


def link_repository_to_job(
    config: dict,
    repository_key: str,
    job_key: str,
    *,
    previous_repository_key: str = "",
    previous_job_key: str = "",
) -> None:
    selected = str(repository_key or "").strip()
    current_job = str(job_key or "").strip()
    if not selected or not current_job:
        raise ValueError("Repository and job keys are required")
    store = read_repository_store(config)
    rows = store["repositories"]
    if not any(str(row.get("repository_key") or "") == selected for row in rows):
        raise ValueError("Repository not found")
    old_repo = str(previous_repository_key or "").strip()
    old_job = str(previous_job_key or current_job).strip()
    next_rows = []
    for row in rows:
        key = str(row.get("repository_key") or "")
        used_by = [str(item).strip() for item in row.get("used_by", []) if str(item).strip()]
        source_jobs = [str(item).strip() for item in row.get("source_job_keys", []) if str(item).strip()]
        if key == old_repo or old_job != current_job:
            used_by = [item for item in used_by if item not in {old_job, current_job}]
            source_jobs = [item for item in source_jobs if item not in {old_job, current_job}]
        if key == selected:
            if current_job not in used_by:
                used_by.append(current_job)
            if current_job not in source_jobs:
                source_jobs.append(current_job)
        next_rows.append({**row, "used_by": used_by, "source_job_keys": source_jobs, "updated_at": _now()})
    write_repository_store(config, {"repositories": next_rows})


def unlink_job_from_repositories(config: dict, job_key: str) -> None:
    current_job = str(job_key or "").strip()
    if not current_job:
        return
    store = read_repository_store(config)
    changed = False
    next_rows = []
    for row in store.get("repositories", []):
        used_by = [str(item).strip() for item in row.get("used_by", []) if str(item).strip()]
        source_jobs = [str(item).strip() for item in row.get("source_job_keys", []) if str(item).strip()]
        next_used_by = [item for item in used_by if item != current_job]
        next_source_jobs = [item for item in source_jobs if item != current_job]
        if next_used_by != used_by or next_source_jobs != source_jobs:
            changed = True
            row = {
                **row,
                "used_by": next_used_by,
                "source_job_keys": next_source_jobs,
                "updated_at": _now(),
            }
        next_rows.append(row)
    if changed:
        write_repository_store(config, {"repositories": next_rows})
