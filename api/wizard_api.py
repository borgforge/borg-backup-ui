"""
api/wizard_api.py – Job-Wizard: Skript-Generierung und -Speicherung

Generiert Python-Backup-Skripte nach dem Muster von borg_backup_flash.py /
borg_backup_appdata.py und speichert sie im BORG_SCRIPTS_DIR.
"""

import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


def _type_upper(type_id: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", type_id.upper())


def _script_filename(type_id: str, location: str) -> str:
    if location == "local":
        return f"borg_backup_{type_id}.py"
    elif location == "usb":
        return f"borg_backup_{type_id}_usb.py"
    elif location == "storagebox":
        return f"borg_backup_storagebox_{type_id}.py"
    return f"borg_backup_{type_id}.py"


_SECRETS_DIR = Path("/boot/config/borg-backup/secrets")


def _inject_storage_profile_user_into_repo(repo_uri: str, storage_profile_key: str, scripts_dir: Path) -> str:
    repo = str(repo_uri or "").strip()
    if not repo.startswith("ssh://"):
        return repo
    parts = urlsplit(repo)
    netloc = parts.netloc or ""
    if not netloc or "@" in netloc:
        return repo
    key = str(storage_profile_key or "").strip().lower()
    if not key:
        return repo
    try:
        from config_api import read_settings_payload
        payload = read_settings_payload({"BACKUP_SCRIPTS_DIR": str(scripts_dir)})
        rows = payload.get("storage_profiles") if isinstance(payload.get("storage_profiles"), list) else []
        user = ""
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("key") or "").strip().lower() == key:
                user = str(row.get("user") or "").strip()
                break
        if not user:
            return repo
        return urlunsplit((parts.scheme, f"{user}@{netloc}", parts.path, parts.query, parts.fragment))
    except Exception:
        return repo


def _passphrase_suffix(type_id: str, location: str | None = None) -> str:
    if location:
        return f"{type_id}_{location.lower()}"
    return type_id


def check_passphrase_exists(type_id: str, location: str | None = None) -> dict:
    """Prüft ob bereits eine Passphrase-Datei für Typ/Location existiert."""
    suffix = _passphrase_suffix(type_id, location)
    path = _SECRETS_DIR / f".borg-passphrase-{suffix}"
    if path.is_file():
        return {"exists": True, "path": str(path)}
    # Backward compatibility: alte type_id-Datei ebenfalls erkennen
    fallback = _SECRETS_DIR / f".borg-passphrase-{type_id}"
    return {"exists": fallback.is_file(), "path": str(fallback if fallback.is_file() else path)}


def validate_params(
    params: dict,
    scripts_dir: Path,
    data_root: Optional[Path] = None,
    *,
    allow_existing: bool = False,
) -> None:
    """Wirft ValueError bei ungültigen Parametern."""
    type_id = params.get("type_id", "").strip()
    if not type_id:
        raise ValueError("Typ-ID darf nicht leer sein")
    if not re.fullmatch(r"[a-z0-9_]+", type_id):
        raise ValueError("Typ-ID darf nur Kleinbuchstaben, Ziffern und _ enthalten")
    if not params.get("job_name", "").strip():
        raise ValueError("Job-Name darf nicht leer sein")
    if not params.get("source_paths", "").strip():
        raise ValueError("Mindestens ein Quellpfad ist erforderlich")
    if not params.get("repo_path", "").strip():
        raise ValueError("Repository-Pfad darf nicht leer sein")

    location = params.get("location", "local")
    if location not in ("local", "usb", "smb", "storagebox"):
        raise ValueError(f"Ungültige Location: {location!r}")
    if location == "smb" and not str(params.get("smb_profile_key", "")).strip():
        raise ValueError("SMB-Profil fehlt")
    if location == "storagebox" and not str(params.get("storage_profile_key", "")).strip():
        raise ValueError("Storage-Profil fehlt")

    raw_sources = [p.strip() for p in str(params.get("source_paths", "")).split() if p.strip()]
    for src in raw_sources:
        p = Path(src)
        if not p.exists():
            raise ValueError(f"Quellpfad existiert nicht: {src}")
        if not p.is_dir():
            raise ValueError(f"Quellpfad ist kein Verzeichnis: {src}")

    filename = _script_filename(type_id, location)
    target = scripts_dir / filename
    from jobs_api import get_jobs_meta_dir
    meta_target = get_jobs_meta_dir(scripts_dir, data_root) / f"{type_id}_{location}.json"
    if (target.exists() or meta_target.exists()) and not allow_existing:
        raise FileExistsError(f"Job existiert bereits: {type_id}_{location}")


def _repo_conf_key(type_id: str, location: str) -> str:
    tu = _type_upper(type_id)
    loc = "STORAGEBOX" if location == "storagebox" else location.upper()
    return f"REPO_{tu}_{loc}"


def _passphrase_conf_key(type_id: str, location: str) -> str:
    return f"BORG_PASSPHRASE_FILE_{_type_upper(type_id)}_{location.upper()}"


def _paths_conf_key(type_id: str) -> str:
    return f"BACKUP_PATHS_{_type_upper(type_id)}"


def _wizard_repo_passphrase_path(params: dict) -> str:
    type_id = str(params.get("type_id", "")).strip().lower()
    location = str(params.get("location", "")).strip().lower()
    suffix = _passphrase_suffix(type_id, location)
    path = _SECRETS_DIR / f".borg-passphrase-{suffix}"
    if path.is_file():
        return str(path)
    fallback = _SECRETS_DIR / f".borg-passphrase-{type_id}"
    if fallback.is_file():
        return str(fallback)
    return str(path)


def _storagebox_repo_status(params: dict, ui_config: Optional[dict], scripts_dir: Optional[Path]) -> dict:
    location = str(params.get("location", "")).strip().lower()
    if location != "storagebox":
        return {"checked": False, "exists": False, "needs_init_confirm": False, "message": ""}

    repo = str(params.get("repo_path", "")).strip()
    if scripts_dir is not None:
        repo = _inject_storage_profile_user_into_repo(repo, str(params.get("storage_profile_key", "")).strip(), scripts_dir)
    if not repo.startswith("ssh://"):
        return {
            "checked": False,
            "exists": False,
            "needs_init_confirm": True,
            "message": "Storage Box repository is not an ssh:// URI.",
            "message_code": "wizard_repo_not_ssh",
        }

    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    encryption = str(params.get("encryption", "repokey-blake2") or "repokey-blake2").strip()
    passphrase = str(params.get("passphrase", "") or "").strip()
    if encryption != "none":
        if passphrase:
            env["BORG_PASSPHRASE"] = passphrase
        else:
            env["BORG_PASSCOMMAND"] = f"cat {shlex.quote(_wizard_repo_passphrase_path(params))}"

    if ui_config is not None:
        try:
            from storage_profiles_api import resolve_storage_profile
            profile = resolve_storage_profile(ui_config, str(params.get("storage_profile_key", "")).strip())
            ssh_key = str(profile.get("ssh_key_path") or "").strip()
            if ssh_key:
                env["BORG_RSH"] = f"ssh -i {shlex.quote(ssh_key)} -o WarnWeakCrypto=no"
        except Exception:
            pass

    try:
        result = subprocess.run(
            ["borg", "info", repo],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
            check=False,
        )
    except FileNotFoundError:
        return {
            "checked": False,
            "exists": False,
            "needs_init_confirm": True,
            "message": "borg binary not found; repository existence could not be checked.",
            "message_code": "wizard_borg_missing",
        }
    except subprocess.TimeoutExpired:
        return {
            "checked": True,
            "exists": False,
            "needs_init_confirm": True,
            "message": "Repository check timed out.",
            "message_code": "wizard_repo_timeout",
        }
    except Exception as exc:
        return {
            "checked": False,
            "exists": False,
            "needs_init_confirm": True,
            "message": f"Repository check failed: {exc}",
            "message_code": "wizard_repo_check_failed",
        }

    if result.returncode == 0:
        return {
            "checked": True,
            "exists": True,
            "needs_init_confirm": False,
            "message": "Remote repository exists.",
            "message_code": "wizard_repo_exists",
        }

    output = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
    first_line = output.splitlines()[0].strip() if output.splitlines() else "borg info could not open the repository."
    return {
        "checked": True,
        "exists": False,
        "needs_init_confirm": True,
        "message": first_line[:240],
        "message_code": "wizard_repo_unavailable",
        "exit_code": result.returncode,
    }


def _storagebox_repo_from_profile(params: dict, ui_config: Optional[dict]) -> str:
    if ui_config is None:
        return ""
    try:
        from storage_profiles_api import build_storage_repo_uri, resolve_storage_profile
        profile = resolve_storage_profile(ui_config, str(params.get("storage_profile_key", "")).strip())
        return build_storage_repo_uri(profile, str(params.get("type_id", "")).strip())
    except Exception:
        return ""


def _extract_script_string(script_path: Optional[Path], pattern: str) -> str:
    if script_path is None:
        return ""
    try:
        content = script_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(pattern, content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _read_script_content(script_path: Optional[Path]) -> str:
    if script_path is None:
        return ""
    try:
        return script_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _extract_script_var_string(content: str, var_name: str) -> str:
    """Extracts string value from VAR = "..." or VAR = ("..." "...") patterns."""
    if not content or not var_name:
        return ""
    m = re.search(
        rf"^{re.escape(var_name)}\s*=\s*(\((?:.|\n)*?\)|[\"'](?:.|\n)*?[\"'])",
        content,
        re.MULTILINE,
    )
    if not m:
        return ""
    raw = m.group(1).strip()
    parts = re.findall(r"[\"']([^\"']*)[\"']", raw, re.MULTILINE)
    if parts:
        return "".join(parts).strip()
    return ""


def load_job_for_wizard(job_key: str, scripts_dir: Path, ui_config: dict) -> dict:
    from jobs_api import discover_jobs, get_jobs_meta_dirs, resolve_data_root
    from config_api import read_expanded_conf

    data_root = resolve_data_root(ui_config)
    jobs = {j.key: j for j in discover_jobs(scripts_dir, data_root)}
    if job_key not in jobs:
        raise ValueError(f"Unbekannter Job: {job_key}")

    info = jobs[job_key]
    conf = read_expanded_conf(ui_config)
    type_id = str(info.backup_type or "").lower()
    location = str(info.location or "local").lower()

    repo_key = _repo_conf_key(type_id, location)
    paths_key = _paths_conf_key(type_id)
    pass_key = _passphrase_conf_key(type_id, location)

    # Prefer explicit wizard metadata values if available.
    meta_repo_default = ""
    meta_paths_default = ""
    meta_compression = ""
    meta_keep_daily = ""
    meta_keep_weekly = ""
    meta_keep_monthly = ""
    meta_keep_yearly = ""
    meta_usb_profile_key = ""
    meta_smb_profile_key = ""
    meta_storage_profile_key = ""
    meta_mount_before_run = True
    meta_unmount_after_run = True
    for meta_dir in get_jobs_meta_dirs(scripts_dir, data_root):
        meta_file = meta_dir / f"{job_key}.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if isinstance(meta.get("repo"), dict):
                meta_repo_default = str(meta["repo"].get("default") or "").strip()
            if isinstance(meta.get("paths"), dict):
                meta_paths_default = str(meta["paths"].get("default") or "").strip()
            meta_compression = str(meta.get("compression") or "").strip()
            meta_ret = meta.get("retention") if isinstance(meta.get("retention"), dict) else {}
            meta_keep_daily = str(meta_ret.get("daily") or "").strip()
            meta_keep_weekly = str(meta_ret.get("weekly") or "").strip()
            meta_keep_monthly = str(meta_ret.get("monthly") or "").strip()
            meta_keep_yearly = str(meta_ret.get("yearly") or "").strip()
            meta_usb_profile_key = str(meta.get("usb_profile_key") or "").strip()
            meta_smb_profile_key = str(meta.get("smb_profile_key") or "").strip()
            meta_storage_profile_key = str(meta.get("storage_profile_key") or "").strip()
            meta_mount_before_run = bool(meta.get("mount_before_run", True))
            meta_unmount_after_run = bool(meta.get("unmount_after_run", True))
            break
        except (json.JSONDecodeError, OSError, UnicodeDecodeError, TypeError, ValueError):
            continue

    # Fallbacks from script defaults
    script_content = _read_script_content(info.script_path)
    script_repo_default = _extract_script_string(info.script_path, r'_DEFAULT_REPO\s*=\s*["\']([^"\']+)["\']')
    script_paths_default = _extract_script_string(info.script_path, r'_DEFAULT_PATHS\s*=\s*["\']([^"\']+)["\']')
    if not script_paths_default:
        script_paths_default = _extract_script_string(
            info.script_path,
            rf'env\.setdefault\(["\']BACKUP_PATHS_{_type_upper(type_id)}["\'],\s*["\']([^"\']+)["\']\)'
        )
    # Legacy compatibility: resolve actual BACKUP_PATHS env-key used in script, if any.
    script_paths_key = ""
    if script_content:
        m_paths_key = re.search(
            r'env\.setdefault\(\s*["\']BACKUP_PATHS["\']\s*,\s*env\.get\(\s*["\']([^"\']+)["\']\s*,',
            script_content,
            re.MULTILINE,
        )
        if m_paths_key:
            script_paths_key = m_paths_key.group(1).strip()
        if not script_paths_default:
            m_paths_var = re.search(
                r'env\.setdefault\(\s*["\']BACKUP_PATHS["\']\s*,\s*env\.get\(\s*["\'][^"\']+["\']\s*,\s*([_A-Za-z][_A-Za-z0-9]*)\s*\)\s*\)',
                script_content,
                re.MULTILINE,
            )
            if m_paths_var:
                script_paths_default = _extract_script_var_string(script_content, m_paths_var.group(1).strip())

    job_name = _extract_script_string(info.script_path, r'env\.setdefault\(["\']JOB_NAME["\'],\s*["\']([^"\']+)["\']\)')

    repo_path = conf.get(repo_key) or meta_repo_default or script_repo_default
    source_paths = (
        conf.get(paths_key)
        or (conf.get(script_paths_key) if script_paths_key else "")
        or meta_paths_default
        or script_paths_default
    )
    compression = meta_compression or conf.get(f"COMPRESSION_{_type_upper(type_id)}", "lz4")

    # Prefer explicit job metadata name (JSON) over display label with location suffix.
    # This keeps edited names stable (e.g. "Flash" stays "Flash", not "Flash - Lokal").
    params = {
        "job_key": job_key,
        "type_id": type_id,
        "job_name": (info.name or "").strip() or job_name or info.display_name or job_key,
        "description": info.description or "",
        "icon": str(getattr(info, "icon", "") or "").strip().lower(),
        "icon_color": str(getattr(info, "icon_color", "") or "").strip().lower(),
        "location": location,
        "use_docker": bool(info.has_docker),
        "use_vm": bool(info.has_vm),
        "source_paths": source_paths or "",
        "repo_path": repo_path or "",
        "usb_profile_key": meta_usb_profile_key,
        "smb_profile_key": meta_smb_profile_key,
        "storage_profile_key": meta_storage_profile_key,
        "mount_before_run": meta_mount_before_run,
        "unmount_after_run": meta_unmount_after_run,
        "compression": compression,
        "encryption": "repokey-blake2",
        "passphrase": "",
        "keep_daily": meta_keep_daily or conf.get(f"RETENTION_{_type_upper(type_id)}_DAILY", "7"),
        "keep_weekly": meta_keep_weekly or conf.get(f"RETENTION_{_type_upper(type_id)}_WEEKLY", "4"),
        "keep_monthly": meta_keep_monthly or conf.get(f"RETENTION_{_type_upper(type_id)}_MONTHLY", "6"),
        "keep_yearly": meta_keep_yearly or conf.get(f"RETENTION_{_type_upper(type_id)}_YEARLY", "3"),
        "standard": info.standard,
    }
    return params


def generate_script(params: dict) -> str:
    """Generiert ein Python-Backup-Skript als String."""
    type_id       = params["type_id"].strip()
    job_name      = params["job_name"].strip()
    location      = params.get("location", "local")
    source_paths  = params["source_paths"].strip()
    repo_path     = params["repo_path"].strip()
    compression   = params.get("compression", "lz4")
    keep_daily    = str(params.get("keep_daily", "7"))
    keep_weekly   = str(params.get("keep_weekly", "4"))
    keep_monthly  = str(params.get("keep_monthly", "6"))
    keep_yearly   = str(params.get("keep_yearly", "3"))
    use_docker    = bool(params.get("use_docker", False))
    encryption    = params.get("encryption", "repokey-blake2")

    tu = _type_upper(type_id)  # e.g. "MEINEDATEN"

    if location == "local":
        loc_upper   = "LOCAL"
        loc_cache   = "local"
        loc_display = "lokal"
    elif location == "usb":
        loc_upper   = "USB"
        loc_cache   = "usb"
        loc_display = "USB"
    else:
        loc_upper   = "STORAGEBOX"
        loc_cache   = "storagebox"
        loc_display = "Storagebox"

    # Per-repo passphrase file (location-specific)
    passphrase_key = _passphrase_conf_key(type_id, location)
    passphrase_def = f"/boot/config/borg-backup/secrets/.borg-passphrase-{type_id}_{location}"

    repo_key       = f"REPO_{tu}_{loc_upper}"
    archive_prefix = f"{type_id}-backup"

    docker_import  = "from lib.docker_manager import DockerConfig, DockerManager\n" if use_docker else ""
    docker_env     = f"""    env.setdefault("DOCKER_STOP_TIMEOUT", env.get("GLOBAL_DOCKER_STOP_TIMEOUT", "60"))
    env.setdefault("DOCKER_STOP_WAIT", env.get("GLOBAL_DOCKER_STOP_WAIT", "5"))
    env.setdefault("DOCKER_START_WAIT", env.get("GLOBAL_DOCKER_START_WAIT", "5"))
""" if use_docker else ""
    docker_cfg     = "    docker_config = DockerConfig.from_config(env)\n" if use_docker else ""
    docker_mgr     = "    docker_manager = DockerManager(docker_config)\n\n" if use_docker else ""
    docker_param   = ", docker_manager=docker_manager" if use_docker else ""
    docker_stop    = "        job.stop_docker()\n\n" if use_docker else ""
    docker_start   = "\n        job.start_docker()\n" if use_docker else ""

    if encryption != "none":
        passphrase_setup = f'''
    passphrase_file = env.get("{passphrase_key}", "{passphrase_def}")
    os.environ["BORG_PASSCOMMAND"] = f"cat {{shlex.quote(str(passphrase_file))}}"'''
        init_passphrase = f'''
    passphrase_key  = "{passphrase_key}"
    passphrase_file = env.get(passphrase_key, "{passphrase_def}")
    logging.info("Passphrase file (%s): %s", passphrase_key, passphrase_file)'''
    else:
        passphrase_setup  = ""
        init_passphrase   = ""

    init_block = f'''
def _init_repo_if_needed(env: dict) -> int:
    """Initialisiert das Borg-Repository falls es noch nicht existiert."""
    import subprocess as _sp
    repo = env.get("BORG_REPO", "")
    if not repo:
        return 0
    check = _sp.run(
        ["borg", "info", repo],
        capture_output=True, text=True,
    )
    if check.returncode == 0:
        return 0
    logging.info("Repository not found; initializing: %s", repo){init_passphrase}
    result = _sp.run(
        ["borg", "init", "--encryption={encryption}", repo],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        for line in (result.stdout + result.stderr).splitlines():
            if line.strip():
                logging.error("[borg init] %s", line)
        logging.error("borg init failed (exit %d)", result.returncode)
    else:
        logging.info("Repository initialized successfully: %s", repo)
    return result.returncode

'''

    return f'''#!/usr/bin/env python3
"""{job_name} – Generiert von borg-backup-ui Job-Wizard."""

import logging
import os
import shlex
import sys
from datetime import datetime
from pathlib import Path

os.environ["LC_ALL"] = "C"
os.environ["LANG"] = "C"

VERSION = "1.0.0"
SCRIPT_DIR = Path(__file__).parent
_BORG_BASE = Path(os.environ.get("BORG_SCRIPT_DIR", str(SCRIPT_DIR.parent)))
CONFIG_FILE = _BORG_BASE / "config" / "backup.conf"
_LIB_BASE = SCRIPT_DIR if (SCRIPT_DIR / "lib").is_dir() else _BORG_BASE
sys.path.insert(0, str(_LIB_BASE))

from lib.status import load_config
from lib.backup_job import BackupJob, BackupJobConfig
from lib.borg_runner import BorgConfig, BorgRunner, parse_borg_stats
{docker_import}from lib.notifications import MailConfig

_DEFAULT_PATHS = "{source_paths}"


def _load_env() -> dict:
    env = dict(os.environ)
    if CONFIG_FILE.is_file():
        env.update(load_config(CONFIG_FILE))

    cache_base = env.get("GLOBAL_BORG_CACHE_BASE", "/mnt/cache/borg-cache")
    cache_dir = f"{{cache_base}}/{loc_cache}_{type_id}"
    date_tag = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_dir = env.get("GLOBAL_LOG_DIR", "/mnt/user/Logs")

    env.setdefault("JOB_NAME", "{job_name}")
    env.setdefault("BACKUP_TYPE", "{type_id}")
    env.setdefault("BACKUP_LOCATION", "{location}")
    env.setdefault("DATE_TAG", date_tag)
    env.setdefault("LOG_DIR", log_dir)
    env.setdefault("LOG_FILE", f"{{log_dir}}/Borg-Backup_{type_id}_{location}--{{date_tag}}.log")
    env.setdefault("LOG_RETENTION_DAYS", env.get("GLOBAL_LOG_RETENTION_DAYS", "30"))
    env.setdefault("BORG_REPO", env.get("{repo_key}", "{repo_path}"))
    env.setdefault("BORG_COMPRESSION", env.get("COMPRESSION_{tu}", "{compression}"))
    env.setdefault("BORG_CHECKPOINT_INTERVAL", env.get("GLOBAL_BORG_CHECKPOINT_INTERVAL", "1800"))
    env.setdefault("BORG_CACHE_DIR", cache_dir)
    env.setdefault("BORG_CHECK_INTERVAL_DAYS", env.get("GLOBAL_BORG_CHECK_INTERVAL_DAYS", "30"))
    env.setdefault("BORG_CHECK_FLAG_FILE", f"{{cache_dir}}/.last_check_{type_id}")
    env.setdefault("BORG_KEEP_DAILY", env.get("RETENTION_{tu}_DAILY", "{keep_daily}"))
    env.setdefault("BORG_KEEP_WEEKLY", env.get("RETENTION_{tu}_WEEKLY", "{keep_weekly}"))
    env.setdefault("BORG_KEEP_MONTHLY", env.get("RETENTION_{tu}_MONTHLY", "{keep_monthly}"))
    env.setdefault("BORG_KEEP_YEARLY", env.get("RETENTION_{tu}_YEARLY", "{keep_yearly}"))
    env.setdefault("LOCK_FILE", f"{{env.get('LOCK_FILE_DIR', '/var/run')}}/borg-backup-{type_id}.lock")
    env.setdefault("BACKUP_PATHS", env.get("BACKUP_PATHS_{tu}", _DEFAULT_PATHS))
{docker_env}{passphrase_setup}
    os.environ["BORG_REPO"] = env["BORG_REPO"]
    os.environ["BORG_CACHE_DIR"] = env["BORG_CACHE_DIR"]

    return env


def _setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )

{init_block}
def main() -> int:
    env = _load_env()
    job_config = BackupJobConfig.from_config(env)
    borg_config = BorgConfig.from_config(env)
{docker_cfg}    mail_config = MailConfig.from_config(env)

    BackupJob(job_config).check_parity()

    _setup_logging(job_config.log_file)

    init_exit = _init_repo_if_needed(env)
    if init_exit != 0:
        return init_exit


{docker_mgr}    with BackupJob(job_config{docker_param}, mail_config=mail_config) as job:
        job.check_prerequisites()
        job.cleanup_old_logs()
{docker_stop}        runner = BorgRunner(borg_config)
        exit_code = runner.create(job_config.backup_paths, "{archive_prefix}")
        if exit_code >= 2:
            job.set_result(exit_code, final_msg=f"borg create fehlgeschlagen (Exit {{exit_code}})")
            return exit_code
{docker_start}        maint_exit = runner.maintenance()
        exit_code = max(exit_code, maint_exit)
        job.set_result(exit_code, parse_borg_stats(job_config.log_file))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
'''


def generate_flow_preview(params: dict, ui_config: Optional[dict] = None, scripts_dir: Optional[Path] = None) -> dict:
    """Erzeugt eine textuelle Backup-Flow-Vorschau fuer den Wizard."""
    type_id = params["type_id"].strip()
    location = params.get("location", "local")
    source_paths = [p for p in params.get("source_paths", "").split() if p]
    repo_path = params.get("repo_path", "").strip()
    if location == "storagebox":
        repo_path = _storagebox_repo_from_profile(params, ui_config) or repo_path
    encryption = params.get("encryption", "repokey-blake2")
    use_docker = bool(params.get("use_docker", False))
    use_vm = bool(params.get("use_vm", False))

    steps = [
        "Prechecks (Prerequisites, Parity, Pfade)",
        "Resource-Locks (repo, optional docker-control/vm-control)",
    ]
    if use_docker:
        steps.append("Docker-Container stoppen")
    if use_vm:
        steps.append("VMs herunterfahren")
    steps.extend(
        [
            f"Borg Create ({len(source_paths)} Quelle(n))",
            "Borg Wartung (Prune -> Compact -> Check)",
            "Status/Benachrichtigung schreiben",
        ]
    )
    if use_vm:
        steps.append("VMs starten")
    if use_docker:
        steps.append("Docker-Container starten")
    steps.append("Resource-Locks freigeben")

    remote_repo = _storagebox_repo_status({**params, "repo_path": repo_path}, ui_config, scripts_dir)
    return {
        "runner": "scriptless-wizard-runner",
        "job_key": f"{type_id}_{location}",
        "summary": {
            "location": location,
            "repo": repo_path,
            "encryption": encryption,
            "sources_count": len(source_paths),
            "docker": use_docker,
            "vm": use_vm,
        },
        "steps": steps,
        "remote_repo": remote_repo,
    }


def save_job(params: dict, scripts_dir: Path, data_root: Optional[Path] = None, ui_config: Optional[dict] = None) -> dict:
    """Speichert Wizard-Job-Metadaten (scriptless) + optionale Passphrase."""
    from jobs_api import get_jobs_meta_dir
    type_id     = params["type_id"].strip()
    location    = params.get("location", "local")
    usb_profile_key = str(params.get("usb_profile_key", "")).strip()
    smb_profile_key = str(params.get("smb_profile_key", "")).strip()
    storage_profile_key = str(params.get("storage_profile_key", "")).strip()
    remote_init_confirmed = bool(params.get("remote_init_confirmed", False))
    description = params.get("description", "").strip()
    icon = str(params.get("icon", "")).strip().lower()
    icon_color = str(params.get("icon_color", "")).strip().lower()
    encryption  = params.get("encryption", "repokey-blake2")
    passphrase  = params.get("passphrase", "").strip()
    passphrase_suffix = _passphrase_suffix(type_id, location)
    filename    = _script_filename(type_id, location)

    scripts_dir.mkdir(parents=True, exist_ok=True)
    existing_job_key = str(params.get("existing_job_key", "")).strip()

    if encryption != "none" and passphrase:
        secrets_dir = Path("/boot/config/borg-backup/secrets")
        secrets_dir.mkdir(parents=True, exist_ok=True)
        secret_file = secrets_dir / f".borg-passphrase-{passphrase_suffix}"
        secret_file.write_text(passphrase, encoding="utf-8")
        secret_file.chmod(0o600)

    # ── Wizard-Metadaten schreiben (Phase 2) ─────────────────────────────────
    job_key = f"{type_id}_{location}"
    type_upper = _type_upper(type_id)
    if location == "local":
        repo_conf_key = f"REPO_{type_upper}_LOCAL"
    elif location == "usb":
        repo_conf_key = f"REPO_{type_upper}_USB"
    elif location == "smb":
        repo_conf_key = f"REPO_{type_upper}_SMB"
    else:
        repo_conf_key = f"REPO_{type_upper}_STORAGEBOX"
    pass_conf_key = _passphrase_conf_key(type_id, location)

    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    jobs_meta_dir = get_jobs_meta_dir(scripts_dir, data_root)
    jobs_meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path = jobs_meta_dir / f"{job_key}.json"

    existing = {}
    if meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            existing = {}

    mount_before_run = bool(params.get("mount_before_run", existing.get("mount_before_run", True)))
    unmount_after_run = bool(params.get("unmount_after_run", existing.get("unmount_after_run", True)))

    create_repo_default = True if location in {"local", "usb", "smb", "storagebox"} else False
    create_repo_if_missing = bool(existing.get("create_repo_if_missing", create_repo_default))

    repo_default = str(params.get("repo_path", "")).strip()
    if location == "storagebox":
        repo_default = _storagebox_repo_from_profile(params, ui_config) or _inject_storage_profile_user_into_repo(repo_default, storage_profile_key, scripts_dir)
        repo_status = _storagebox_repo_status({**params, "repo_path": repo_default}, ui_config, scripts_dir)
        if bool(repo_status.get("exists", False)):
            create_repo_if_missing = False
        elif create_repo_if_missing and not remote_init_confirmed:
            msg = str(repo_status.get("message") or "Remote-Repository ist nicht als vorhanden bestätigt.")
            raise ValueError(f"Remote-Repository-Anlage nicht bestätigt: {msg}")

    metadata = {
        "job_key": job_key,
        "name": params.get("job_name", "").strip() or job_key,
        "description": description,
        "icon": icon,
        "icon_color": icon_color,
        "enabled": bool(existing.get("enabled", True)),
        "standard": "wizard",
        "backup_type": type_id,
        "location": location,
        "usb_profile_key": usb_profile_key if location == "usb" else "",
        "smb_profile_key": smb_profile_key if location == "smb" else "",
        "storage_profile_key": storage_profile_key if location == "storagebox" else "",
        "mount_before_run": mount_before_run if location == "smb" else True,
        "unmount_after_run": unmount_after_run if location == "smb" else True,
        "remote_init_confirmed": remote_init_confirmed if location == "storagebox" else False,
        "script": "",
        "runner": "scriptless-wizard-runner",
        "repo": {
            "conf_key": repo_conf_key,
            "default": repo_default,
        },
        "passphrase": {
            "conf_key": pass_conf_key,
            "default": f"/boot/config/borg-backup/secrets/.borg-passphrase-{passphrase_suffix}",
            "mode": "none" if encryption == "none" else ("create_new" if passphrase else "existing_file"),
        },
        "paths": {
            "conf_key": f"BACKUP_PATHS_{type_upper}",
            "default": params.get("source_paths", "").strip(),
        },
        "features": {
            "docker": bool(params.get("use_docker", False)),
            "vm": bool(params.get("use_vm", False)),
        },
        "compression": str(params.get("compression", "lz4")).strip() or "lz4",
        "retention": {
            "daily": str(params.get("keep_daily", "7")).strip() or "7",
            "weekly": str(params.get("keep_weekly", "4")).strip() or "4",
            "monthly": str(params.get("keep_monthly", "6")).strip() or "6",
            "yearly": str(params.get("keep_yearly", "3")).strip() or "3",
        },
        "create_repo_if_missing": create_repo_if_missing,
        "encryption": encryption,
        "created_at": existing.get("created_at", now_iso),
        "updated_at": now_iso,
    }

    if repo_default and "://" not in repo_default and not repo_default.startswith("ssh:"):
        repo_path = Path(repo_default)
        if repo_path.exists() and (repo_path / "config").exists():
            metadata["create_repo_if_missing"] = False

    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if existing_job_key and existing_job_key != job_key:
        old_meta = jobs_meta_dir / f"{existing_job_key}.json"
        if old_meta.exists():
            try:
                old_meta.unlink()
            except OSError:
                pass

    return {
        "filename": filename,
        "path": "",
        "script": "",
        "metadata_path": str(meta_path),
        "regenerated_script": False,
    }
