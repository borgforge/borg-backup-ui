#!/usr/bin/env python3
"""
borg_restore_test.py – Automatischer Restore-Test für Borg-Repositories
Python-Port von borg_restore_test.sh v1.2.0

Testet alle konfigurierten Repositories auf Wiederherstellbarkeit:
  Level 2 (Standard): Extract Dry-Run + Eintrags-Validierung
  Level 3:            Sample Restore mit SHA256-Checksum-Validierung

Verwendung:
    python3 borg_restore_test.py                    # Nur Tests die fällig sind (Level 2)
    python3 borg_restore_test.py --force            # Alle Tests erzwingen
    python3 borg_restore_test.py --level 3          # Level 3 (Sample Restore)
    python3 borg_restore_test.py --location usb     # Nur USB-Repositories
    python3 borg_restore_test.py --dry-run          # Zeigt was getestet würde

Voraussetzungen:
    - borg muss im PATH sein
    - Job-Metadaten mit Repository- oder Profilbezug
    - Passphrase-Dateien aus backup.conf
"""

import argparse
import hashlib
import json
import os
import random
import re
import stat
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

VERSION = "1.0.0"

SCRIPT_DIR = Path(__file__).parent.resolve()

_API_DIR = SCRIPT_DIR.parent.parent / "api"
if _API_DIR.is_dir() and str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from smb_protocol import build_smb_mount_options, classify_smb_mount_error, sanitize_smb_error
from lifecycle_log import emit_lifecycle

# Lib-Pfad: ausschließlich plugin runtime/lib (kein Fallback)
_LIB_DIR = SCRIPT_DIR.parent / "lib"
if _LIB_DIR.is_dir():
    sys.path.insert(0, str(_LIB_DIR.parent))

# Config-Laden: entweder via lib.status oder direkt
try:
    from lib.status import (
        ensure_status_storage_directory as _ensure_status_storage_directory,
        load_config as _lib_load_config,
    )
    def _load_conf_file(path: Path) -> dict:
        return _lib_load_config(path)
except ImportError:
    def _ensure_status_storage_directory(path: Path) -> None:
        normalized = Path(os.path.abspath(os.fspath(path.expanduser())))
        parts = normalized.parts
        mount_path = None
        if len(parts) >= 3 and parts[0] == "/" and parts[1] == "mnt":
            if parts[2] in {"disks", "remotes"} and len(parts) >= 4:
                mount_path = Path("/") / "mnt" / parts[2] / parts[3]
            else:
                mount_path = Path("/") / "mnt" / parts[2]
        if mount_path is not None and not mount_path.is_mount():
            raise OSError(
                f"Status storage is not available yet ({mount_path} is not mounted): {path}"
            )
        path.mkdir(parents=True, exist_ok=True)

    def _load_conf_file(path: Path) -> dict:
        conf = {}
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip().lstrip("readonly ")
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                value = v.strip()
                if value.startswith('"'):
                    try:
                        decoded, end = json.JSONDecoder().raw_decode(value)
                        remainder = value[end:].strip()
                        if isinstance(decoded, str) and (not remainder or remainder.startswith("#")):
                            value = decoded
                    except json.JSONDecodeError:
                        value = value.strip('"')
                elif len(value) >= 2 and value[0] == value[-1] == "'":
                    value = value[1:-1]
                else:
                    comment_pos = value.find("  #")
                    if comment_pos != -1:
                        value = value[:comment_pos].rstrip()
                conf[k.strip()] = value
        return conf


# ── Konfiguration laden ────────────────────────────────────────────────────────

def load_conf() -> dict:
    search = [
        SCRIPT_DIR.parent / "config" / "backup.conf",
        Path("/boot/config/borg-backup/config/backup.conf"),
        Path("/boot/config/plugins/user.scripts/scripts/borg-backup/config/backup.conf"),
    ]
    for p in search:
        if p.is_file():
            return _load_conf_file(p)
    return {}


def _resolve_restore_test_dir(conf: dict) -> Path:
    configured_raw = str(conf.get("RESTORE_TEST_STATUS_DIR", "")).strip()
    configured = Path(configured_raw) if configured_raw else None
    status_dir = Path(conf.get("STATUS_DIR", "/mnt/user/backup-status"))
    candidates = []
    if configured:
        candidates.append(configured)
    candidates.append(status_dir.parent / "restore-status")
    candidates.append(status_dir / "restore-tests")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return configured or (status_dir.parent / "restore-status")


def _extract_test_datetime(test_data: dict, test_file: Path) -> datetime | None:
    date_str = str(test_data.get("test_date") or "").strip()
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(test_file.stat().st_mtime)
    except OSError:
        return None


def _repository_data_root() -> Path:
    configured = str(os.environ.get("BORG_UI_DATA_ROOT") or "").strip()
    if configured:
        return Path(configured)
    production = Path("/boot/config/borg-backup")
    if production.is_dir():
        return production
    return SCRIPT_DIR.parent


def _refresh_unraid_dashboard_widget_cache(conf: dict, reason: str, log_fn=None) -> None:
    try:
        from unraid_dashboard_widget import write_unraid_dashboard_widget_status_file_cache

        effective = dict(conf)
        effective.setdefault("BACKUP_SCRIPTS_DIR", str(_repository_data_root()))
        effective.setdefault("PLUGIN_DIR", str(SCRIPT_DIR.parent.parent))
        write_unraid_dashboard_widget_status_file_cache(
            effective,
            app_version=os.environ.get("BORG_UI_APP_VERSION", ""),
        )
        if log_fn:
            log_fn(f"  Unraid dashboard widget cache updated ({reason})")
    except Exception as exc:
        if log_fn:
            log_fn(f"  Unraid dashboard widget cache update skipped ({reason}): {exc}")


def discover_repos(conf: dict) -> list:
    """Build the restore-test list from canonical job/repository links."""
    data_root = _repository_data_root()
    jobs_dir = data_root / "config" / "jobs"
    repos = []
    seen = set()

    if not jobs_dir.is_dir():
        return repos
    from repository_context import RepositoryContextError, load_repository_inventory, resolve_job_repository_context

    config = {"BACKUP_SCRIPTS_DIR": str(data_root)}
    inventory = load_repository_inventory(config)
    for jf in sorted(jobs_dir.glob("*.json")):
        try:
            raw = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not bool(raw.get("enabled", True)):
            continue
        if str(raw.get("runner", "")).strip() != "scriptless-wizard-runner":
            continue
        from job_identity import metadata_job_id
        try:
            job_key = metadata_job_id(raw)
        except ValueError:
            continue
        if not job_key:
            continue
        try:
            context = resolve_job_repository_context(config, job_key, job=raw, inventory=inventory)
        except RepositoryContextError:
            continue
        location = str(context.get("location") or "").strip().lower()
        repo_path = str(context.get("repository_path") or "").strip()
        profile_key = str(context.get("profile_key") or "").strip().lower()
        key = (context["repository_key"], job_key)
        if key in seen:
            continue
        seen.add(key)
        repos.append({
            "job_key": job_key,
            "restore_test_policy": raw.get("restore_test_policy") or {},
            "type": "",
            "name": str(raw.get("name") or "Backup"),
            "location": location,
            "path": repo_path,
            "encryption": str(context.get("encryption") or "").strip().lower(),
            "passphrase_file": str(context.get("passphrase_ref") or ""),
            "profile_key": profile_key,
            "storage": context.get("storage") if isinstance(context.get("storage"), dict) else {},
            "mount_before_run": bool(raw.get("mount_before_run", True)),
            "unmount_after_run": bool(raw.get("unmount_after_run", True)),
        })

    return repos


# ── Restore Tester ─────────────────────────────────────────────────────────────

class RestoreTest:
    """Run policy-aware Borg verification and persist per-job test evidence.

    Construction opens a timestamped log and, for managed supervisors, creates
    run-specific cancellation control. ``test_repo`` coordinates locks and
    verification; callers must close the instance to finish control and logging.
    """
    STEP_IDS = [
        "repo_reachable",
        "archive_readable",
        "metadata_check",
        "restore_probe",
        "integrity_check",
        "cleanup",
    ]

    def __init__(self, conf: dict, args: argparse.Namespace):
        self.conf = conf
        self.args = args
        self.test_level      = args.level
        self.test_interval   = int(conf.get("RESTORE_TEST_INTERVAL_DAYS", 30))
        self.status_dir      = _resolve_restore_test_dir(conf)
        self.min_coverage    = int(conf.get("RESTORE_TEST_MIN_COVERAGE", 5))
        self.max_entries     = int(conf.get("RESTORE_TEST_MAX_ENTRIES", 1000))
        self.sample_size     = int(conf.get("RESTORE_TEST_SAMPLE_SIZE", 5))
        self.borg_timeout    = int(conf.get("RESTORE_TEST_BORG_TIMEOUT", 180))
        self.dryrun_timeout  = int(conf.get("RESTORE_TEST_DRY_RUN_TIMEOUT", 0))  # 0 = no timeout
        self.dryrun_chunk    = int(conf.get("RESTORE_TEST_DRY_RUN_CHUNK_SIZE", 200))
        self.dryrun_max_files = int(conf.get("RESTORE_TEST_DRY_RUN_MAX_FILES", 1000))
        self.level3_legacy_sampling = str(conf.get("RESTORE_TEST_LEVEL3_LEGACY_SAMPLING", "false")).strip().lower() == "true"
        self.full_dryrun_max_archive_gb = int(conf.get("RESTORE_TEST_FULL_DRYRUN_MAX_ARCHIVE_GB", 500))
        self.log_dir         = Path(conf.get("GLOBAL_LOG_DIR", "/mnt/user/Logs"))

        self.log_dir.mkdir(parents=True, exist_ok=True)
        date_tag = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_path = self.log_dir / f"Borg-Restore-Test--{date_tag}-{os.getpid()}.log"
        if getattr(args, "resource_worker", False):
            self.log_path = Path(os.environ["BORG_UI_RESTORE_LOG"])
        self._fh = open(self.log_path, "a", buffering=1, encoding="utf-8")
        self.mail_config = self._load_notification_config()
        self.control = None
        run_id = os.environ.get("BORG_UI_RUN_ID", "").strip()
        if run_id and not getattr(args, "resource_worker", False):
            from job_control import JobControl, CONTROL_ROOT
            keys = getattr(args, "job_keys", [])
            run_key = f"restore_test_{keys[0]}" if len(keys) == 1 else "restore_test"
            self.control = JobControl(run_key, run_id, root=CONTROL_ROOT)
            self.control.update_phase("restore_test", cancel_allowed=True)

    def log(self, msg: str = "") -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}" if msg else ""
        print(line, flush=True)
        self._fh.write(line + "\n")

    def close(self) -> None:
        """Close the log and mark runner control finished; safe to call repeatedly."""
        if self._fh.closed:
            return
        try:
            if self.control:
                self.control.update_phase("finished", cancel_allowed=False, finished=True)
        finally:
            self._fh.close()

    def cancel_requested(self) -> bool:
        """Return whether this supervisor's run has a cancellation marker."""
        control = getattr(self, "control", None)
        return bool(control and control.is_cancel_requested())

    def _record_cancelled(self, repo: dict, started: float) -> int:
        """Persist interrupted evidence (exit 130), mark the batch stopped, and return 130."""
        self._cancelled = True
        message = "Restore test cancelled by user; verification did not complete"
        self.log(message)
        self._write(repo["job_key"], repo, "failed", int(time.time() - started), 0, 0, 0,
                    "unknown", "", {}, [], exit_code=130, error_category="cancelled",
                    error_details=message, failure_code="RT_CANCELLED", failure_hint=message,
                    steps=[{"step_id": step, "status": "not_tested", "duration_ms": 0,
                            "message": message} for step in self.STEP_IDS])
        emit_lifecycle("RESTORE_TEST", "cancelled", job_key=repo["job_key"],
                       run_id=os.environ.get("BORG_UI_RUN_ID", ""), log_file=str(self.log_path))
        return 130

    # ── Hilfsmethoden ──────────────────────────────────────────────────────────

    def _load_notification_config(self):
        try:
            from lib.notifications import MailConfig
            return MailConfig.from_config(self.conf)
        except Exception as exc:
            self.log(f"  notification setup skipped: {exc}")
            return None

    def _notify_event(self, event_type: str, repo: dict, result: str, duration: int = 0,
                     coverage: str = "", error_message: str = "") -> None:
        if not bool(getattr(self.args, "scheduled", False)):
            return
        try:
            from lib.notification_events import NotificationEvent, clear_reminder_prefix, send_event
            from lib.notifications import build_restore_test_notification_message
            job_name = str(repo.get("job_key") or repo.get("type") or "restore_test")
            title = f"Borg Backup UI: Restore test {result}"
            message = build_restore_test_notification_message(
                job_name=job_name,
                status=result,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                duration_seconds=duration,
                repository=str(repo.get("path") or ""),
                level=int(self.test_level),
                coverage=coverage,
                error_message=error_message,
            )
            send_event(
                self.conf,
                NotificationEvent(
                    event_type=event_type,
                    title=title,
                    message=message,
                    severity="warning" if event_type == "restore_test_failed" else "info",
                    job_name=f"Borg Backup UI ({job_name})",
                    job_key=job_name,
                    status=result,
                    duration_seconds=duration,
                    repository=str(repo.get("path") or ""),
                    source="restore_test",
                ),
                mail_config=self.mail_config,
            )
            if event_type == "restore_test_success":
                clear_reminder_prefix(self.conf, f"restore_test_overdue:{job_name}:")
        except Exception as exc:
            self.log(f"  notification event failed: {exc}")

    def _env(self, passphrase: str | None, storage: dict | None = None, repository: str = "", *, encryption: str = "") -> dict:
        from borg_environment import apply_borg_environment
        from borg_ssh import configure_borg_ssh

        env = dict(os.environ)
        env.pop("BORG_PASSPHRASE", None)
        env.pop("BORG_PASSCOMMAND", None)
        if passphrase is not None:
            env["BORG_PASSPHRASE"] = passphrase
        config = dict(self.conf)
        config.setdefault("BACKUP_SCRIPTS_DIR", str(_repository_data_root()))
        env = apply_borg_environment(env, config, encryption=encryption)
        configure_borg_ssh(env, storage, repository)
        return env

    def _borg(self, args: list, env: dict, timeout: int | None = None, consume=None) -> subprocess.CompletedProcess:
        """Run Borg with bounded output or a streaming stdout consumer."""
        from restore_test_io import run_borg
        return run_borg(args, env, self.borg_timeout if timeout is None else timeout, consume,
                        cancel_requested=self.cancel_requested)

    def _list_sample(self, path: str, archive: str, env: dict, limit: int, *, first: bool = False):
        """Return Borg's result and a bounded file sample with an exact count."""
        from restore_test_io import ArchiveSample
        sample = ArchiveSample(limit, first=first)
        result = self._borg(["list", "--json-lines", f"{path}::{archive}"], env,
                            timeout=300, consume=sample.feed)
        if result.returncode == 0:
            try:
                sample.finish()
            except (ValueError, UnicodeError):
                result = subprocess.CompletedProcess(result.args, 2, "", "Invalid archive listing output")
        return result, sample

    @staticmethod
    def _read_passphrase(pp_file: str) -> str:
        p = Path(pp_file)
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
        raise FileNotFoundError(f"Passphrase file not found: {pp_file}")

    @staticmethod
    def _is_smb_mounted(mount_path: str) -> bool:
        if not mount_path:
            return False
        try:
            proc = subprocess.run(
                ["findmnt", "-T", mount_path, "-n", "-o", "FSTYPE"],
                capture_output=True, text=True, timeout=5, check=False
            )
            fs = (proc.stdout or "").strip().lower()
            return proc.returncode == 0 and fs in {"cifs", "smb3", "smbfs"}
        except Exception:
            return False

    def _ensure_smb_mount(self, repo: dict) -> tuple[bool, str]:
        if str(repo.get("location") or "").strip().lower() != "smb":
            return False, ""
        if not bool(self.args.smb_auto_mount):
            return False, ""
        if not bool(repo.get("mount_before_run", True)):
            return False, ""

        key = str(repo.get("profile_key") or "").strip().lower()
        if not key:
            return False, "SMB profile is missing from the job"
        profile = repo.get("storage") if isinstance(repo.get("storage"), dict) else {}

        server = str(profile.get("server", "")).strip()
        share = str(profile.get("share", "")).strip().lstrip("/")
        mount_path = str(profile.get("mount_path") or profile.get("base_path") or "").strip()
        if not server or not share or not mount_path:
            return False, f"SMB profile is incomplete: {key}"
        pf = str(profile.get("password_file", "")).strip()
        if not pf:
            pf = f"/boot/config/borg-backup/secrets/.smb-{key}.cred"
        if not Path(pf).is_file():
            return False, f"SMB credentials file is missing: {pf}"

        Path(mount_path).mkdir(parents=True, exist_ok=True)
        if self._is_smb_mounted(mount_path):
            return False, ""

        opts = build_smb_mount_options(profile, pf)
        res = subprocess.run(
            ["mount", "-t", "cifs", f"//{server}/{share}", mount_path, "-o", ",".join(opts)],
            capture_output=True, text=True, timeout=30, check=False
        )
        if res.returncode != 0:
            technical = sanitize_smb_error(res.stderr or res.stdout or "SMB mount failed")
            _code, hint = classify_smb_mount_error(technical)
            return False, f"{hint} Technical details: {technical}"
        return True, ""

    def _cleanup_smb_mount(self, repo: dict, mounted_by_me: bool) -> None:
        if not mounted_by_me:
            return
        if str(repo.get("location") or "").strip().lower() != "smb":
            return
        if not bool(self.args.smb_auto_mount):
            return
        if not bool(repo.get("unmount_after_run", True)):
            return
        storage = repo.get("storage") if isinstance(repo.get("storage"), dict) else {}
        if bool(storage.get("keep_mounted", False)):
            return
        mount_path = str(storage.get("mount_path") or storage.get("base_path") or "").strip()
        if not mount_path:
            return
        try:
            subprocess.run(["umount", mount_path], capture_output=True, text=True, timeout=20, check=False)
        except Exception:
            pass

    @staticmethod
    def _fmt_bytes(b: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} PB"

    def _collect_level3_legacy_pool(self, path: str, archive: str, env: dict, limit: int = 1000) -> list:
        """
        Legacy-kompatibel: Stichprobenpool aus regulären Dateien des gesamten Archivs
        (ähnlich zu bash: borg list --format ... | head -1000).
        """
        result, sample = self._list_sample(path, archive, env, limit, first=True)
        return sample.paths if result.returncode == 0 else []

    # ── Intervall-Prüfung ──────────────────────────────────────────────────────

    def _should_test(self, key: str) -> bool:
        """Check the original evidence interval; explicit cancellations do not reset it."""
        if self.args.force or getattr(self, "_calendar_run", False):
            return True
        tf = self.status_dir / f"{key}.test"
        if not tf.exists():
            return True
        try:
            raw = json.loads(tf.read_text(encoding="utf-8"))
            from restore_test_reports import verification_evidence
            raw, tf = verification_evidence(tf, raw)
            last_result = str(raw.get("test_result", "")).strip().lower()
            if last_result != "success":
                self.log(f"  Latest test status: {last_result or 'unknown'} - a new test is required")
                return True
        except Exception:
            # Bei beschädigter/inkompatibler Testdatei lieber erneut testen.
            self.log("  Latest test file is not readable; a new test is required")
            return True
        dt = _extract_test_datetime(raw, tf)
        if dt is None:
            self.log("  Latest test timestamp is not readable; a new test is required")
            return True
        age_days = (datetime.now() - dt).total_seconds() / 86400
        if age_days >= self.test_interval:
            self.log(f"  Last test was {age_days:.0f} days ago; test is due")
            return True
        self.log(f"  Last test was {age_days:.0f} days ago; not due yet (interval: {self.test_interval}d)")
        return False

    # ── Fehleranalyse ──────────────────────────────────────────────────────────

    @staticmethod
    def _analyze_error(output: str) -> dict:
        from borg_ssh import SSH_INTERRUPTION_MESSAGE, is_ssh_connection_interruption

        lo = output.lower()
        if is_ssh_connection_interruption(output):
            return {"category": "network", "details": SSH_INTERRUPTION_MESSAGE}
        if "timed out" in lo or "timeout" in lo:
            return {"category": "timeout",              "details": "Borg command exceeded the configured timeout"}
        if "passphrase" in lo and ("wrong" in lo or "incorrect" in lo):
            return {"category": "authentication",       "details": "Incorrect password or passphrase file"}
        if "not found" in lo or ("does not exist" in lo and "repository" in lo):
            return {"category": "repository_missing",   "details": "Repository not found or unreachable"}
        if "locked" in lo:
            return {"category": "repository_locked",    "details": "Repository is locked (another Borg process may be running)"}
        if "corrupt" in lo or "integrity" in lo or "checksum" in lo:
            return {"category": "data_corruption",      "details": "Data corruption detected; archives or chunks are damaged"}
        if "permission denied" in lo or "access denied" in lo:
            return {"category": "permission",           "details": "Missing permissions for repository or files"}
        if "no space left" in lo or "disk full" in lo:
            return {"category": "disk_full",            "details": "No disk space available"}
        if "network" in lo or "connection" in lo or "ssh" in lo or "timeout" in lo:
            return {"category": "network",              "details": "Network error or SSH connection failed"}
        if "archive" in lo and ("not found" in lo or "does not exist" in lo):
            return {"category": "archive_missing",      "details": "Archive not found in repository"}
        return {"category": "unknown",                  "details": "Unknown error; see the log for details"}

    @staticmethod
    def _failure_code_from_category(category: str) -> str:
        mapping = {
            "timeout": "RT_TIMEOUT",
            "authentication": "RT_AUTH_FAILED",
            "repository_missing": "RT_REPO_MISSING",
            "repository_locked": "RT_REPO_LOCKED",
            "data_corruption": "RT_DATA_CORRUPTION",
            "permission": "RT_PERMISSION_DENIED",
            "disk_full": "RT_DISK_FULL",
            "network": "RT_NETWORK_ERROR",
            "archive_missing": "RT_ARCHIVE_MISSING",
            "sample_restore_failed": "RT_SAMPLE_RESTORE_FAILED",
            "unknown": "RT_UNKNOWN",
            "none": "",
        }
        return mapping.get(str(category or "").strip().lower(), "RT_UNKNOWN")

    def _mark_not_tested(self, steps: list, after_step: str) -> None:
        seen_after = False
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for sid in self.STEP_IDS:
            if sid == after_step:
                seen_after = True
                continue
            if not seen_after:
                continue
            if any(s.get("step_id") == sid for s in steps):
                continue
            steps.append({
                "step_id": sid,
                "status": "not_tested",
                "duration_ms": 0,
                "message": "Not tested",
                "command": "",
                "error_code": "",
                "timestamp": now,
            })

    # ── Haupttest ──────────────────────────────────────────────────────────────

    def test_repo(self, repo: dict) -> int:
        """Verify one repository under its resource lock.

        Scheduled calls adopt the job's policy and skip disabled/not-due runs.
        Returns 0 for success, 1 for failure, 2 for skipped, or 3 for an
        unavailable repository, or 130 after cancellation and cleanup. Busy-lock
        skips and cancelled verification are persisted as test results.
        """
        from restore_test_resources import ResourceGuardError, check_cancelled
        started = time.time()
        if self.cancel_requested():
            return self._record_cancelled(repo, started)
        from jobs_api import resolve_resource_lock_dir
        from wizard_runner import ResourceLockSet
        from restore_tests_api import _normalize_restore_policy
        policy = _normalize_restore_policy(repo.get("restore_test_policy"), repo.get("location"),
                                           int(self.conf.get("RESTORE_TEST_INTERVAL_DAYS", 30)))
        self._calendar_run = bool(getattr(self.args, "scheduled", False) and policy.get("cron"))
        if getattr(self.args, "scheduled", False):
            if policy["mode"] != "scheduled":
                self.log("SKIP: restore tests are no longer scheduled for this job")
                return 2
            self.test_level = policy["level"]
            self.test_interval = policy["interval_days"]
        self.log(f"Restore-test policy: job={repo['job_key']}; level=L{self.test_level}; "
                 f"schedule={policy.get('cron') or str(policy['interval_days']) + ' days'}; "
                 f"source={'schedule' if getattr(self.args, 'scheduled', False) else 'manual'}")
        if self.args.dry_run or not self._should_test(repo["job_key"]):
            return 2
        config = dict(self.conf)
        config.setdefault("BACKUP_SCRIPTS_DIR", str(_repository_data_root()))
        locks = ResourceLockSet(resolve_resource_lock_dir(config), repo["job_key"],
                                operation="restore_test", log_file=str(getattr(self, "log_path", "")),
                                run_id=os.environ.get("BORG_UI_RUN_ID", ""))
        locks.set_activity_state("running")
        resources = [f"repo:{repo['path']}"]
        if repo.get("location") == "smb" and repo.get("profile_key"):
            resources.append(f"smb-mount:{repo['profile_key']}")
        acquired, reason = locks.acquire(resources)
        if not acquired:
            self.log(f"SKIP Restore test: {reason}")
            self._write(repo["job_key"], repo, "skipped", 0, 0, 0, 0, "unknown", "", {}, [],
                        exit_code=2, reason=reason, failure_code="RT_REPO_BUSY", failure_hint=reason)
            emit_lifecycle("RESTORE_TEST", "skipped", job_key=repo["job_key"],
                           run_id=os.environ.get("BORG_UI_RUN_ID", ""), status="skipped", reason=reason)
            return 2
        try:
            check_cancelled(self.cancel_requested)
            if str(self.conf.get("RESTORE_TEST_MEMORY_LIMIT_MIB", "2048")).strip() == "0":
                self.log("Memory protection explicitly disabled (RESTORE_TEST_MEMORY_LIMIT_MIB=0)")
                return self._test_repo_locked(repo)
            return self._test_repo_guarded(repo, resolve_resource_lock_dir(config), locks.set_activity_state)
        except ResourceGuardError as exc:
            if not exc.cancelled:
                raise
            return self._record_cancelled(repo, started)
        finally:
            locks.release()

    def _test_repo_guarded(self, repo: dict, lock_dir: Path, on_state=None) -> int:
        """Supervise one limited worker, publishing queue transitions via on_state.

        Locks, mount cleanup and failure reporting remain outside the worker.
        The optional callback accepts running/waiting and must not raise.
        """
        from restore_test_resources import ResourceGuardError, run_guarded
        started = time.time()
        mounted = False
        pending = self.status_dir / f".pending-{uuid.uuid4().hex}.json"
        try:
            limit = int(self.conf.get("RESTORE_TEST_MEMORY_LIMIT_MIB", 2048))
            reserve = int(self.conf.get("RESTORE_TEST_HOST_RESERVE_MIB", 1024))
            if repo.get("location") == "smb":
                mounted, error = self._ensure_smb_mount(repo)
                if error:
                    raise ResourceGuardError("RT_SMB_MOUNT_FAILED", error)
            command = [sys.executable, "-E", "-s", "-S", "-B", str(Path(__file__).resolve()), "--resource-worker",
                       "--job-key", repo["job_key"], "--level", str(self.test_level), "--location", "all", "--force"]
            if getattr(self.args, "scheduled", False):
                command.append("--scheduled")
            env = dict(os.environ, BORG_UI_RESTORE_LOG=str(self.log_path), BORG_UI_RESTORE_RESULT=str(pending),
                       BORG_UI_DATA_ROOT=str(_repository_data_root()))
            options = {"cancel_requested": self.cancel_requested} if getattr(self, "control", None) else {}
            if on_state is not None:
                options["on_state"] = on_state
            rc = run_guarded(command, env, lock_dir, limit, reserve, self.log, **options)
            if not pending.exists():
                raise ResourceGuardError("RT_WORKER_INTERRUPTED", "Restore-test worker ended without a new report; see the run log")
            data = json.loads(pending.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("job_id") != repo["job_key"] or data.get("test_exit_code") != rc:
                raise ResourceGuardError("RT_WORKER_INTERRUPTED", "Restore-test worker returned inconsistent evidence")
            self._publish_report(self.status_dir / f"{repo['job_key']}.test", data, repo)
            return rc
        except (ResourceGuardError, ValueError) as exc:
            if getattr(exc, "cancelled", False):
                raise
            code = getattr(exc, "code", "RT_RESOURCE_CONFIG")
            message = str(exc)
            self.log(f"ERROR {code}: {message}")
            steps = [{"step_id": "resource_guard", "status": "failed", "duration_ms": 0,
                      "message": message, "error_code": code}]
            steps.extend({"step_id": step, "status": "not_tested", "duration_ms": 0,
                          "message": "Completion not confirmed; see the run log"} for step in self.STEP_IDS)
            self._write(repo["job_key"], repo, "failed", int(time.time() - started), 0, 0, 0,
                        "unknown", "", {}, [], exit_code=1, steps=steps,
                        error_category="resource_limit", error_details=message,
                        failure_code=code, failure_hint=message)
            emit_lifecycle("RESTORE_TEST", "failed", job_key=repo["job_key"],
                           failure_code=code, reason=message, log_file=str(self.log_path))
            return 1
        finally:
            if on_state is not None:
                on_state("running")
            pending.unlink(missing_ok=True)
            self._cleanup_smb_mount(repo, mounted)

    def _test_repo_locked(self, repo: dict) -> int:
        """Verify under an existing lock; propagate cancellation after SMB cleanup.

        Returns 0=success, 1=failure, 2=skipped or 3=unavailable. Local path
        access errors are reported as unavailable before Borg or secrets are read.
        """
        location = repo["location"]
        path     = repo["path"]
        encryption = str(repo.get("encryption") or "").strip().lower()
        pp_file  = repo["passphrase_file"]
        key      = str(repo["job_key"])

        self.log(f"{'─'*60}")
        self.log(f"TEST: {repo.get('name') or key} ({location})")
        self.log(f"  Repository: {path}")

        if self.args.dry_run:
            self.log("  [dry-run] Skipped")
            return 2

        smb_mounted_by_me = False
        steps: list = []
        try:
            if location == "smb":
                smb_mounted_by_me, smb_err = self._ensure_smb_mount(repo)
                if smb_err:
                    steps.append({
                        "step_id": "repo_reachable",
                        "status": "failed",
                        "duration_ms": 0,
                        "message": "SMB mount failed",
                        "command": "",
                        "error_code": "RT_SMB_MOUNT_FAILED",
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    self._mark_not_tested(steps, "repo_reachable")
                    self.log(f"  SKIP SMB mount failed: {smb_err}")
                    self._write(key, repo, "unavailable", 0, 0, 0, 0, "unknown", "", {}, [],
                                exit_code=3, reason=f"SMB mount failed: {smb_err}",
                                steps=steps, failure_code="RT_SMB_MOUNT_FAILED", failure_hint=smb_err)
                    return 3
            repository_available = True
            unavailable_reason = "Repository is not mounted or reachable"
            access_error = ""
            if not path.startswith("ssh://"):
                try:
                    repository_available = stat.S_ISDIR(Path(path).stat().st_mode)
                except OSError as exc:
                    repository_available = False
                    # Use OS diagnostics only, not exception text that may contain paths/secrets.
                    access_error = (f"errno {exc.errno}: {os.strerror(exc.errno)}"
                                    if exc.errno is not None else type(exc).__name__)
                    unavailable_reason = (
                        f"Repository path access failed ({access_error}). "
                        "Check the drive connection, mount and access permissions before retrying."
                    )
            if not repository_available:
                steps.append({
                    "step_id": "repo_reachable",
                    "status": "failed",
                    "duration_ms": 0,
                    "message": unavailable_reason,
                    "command": "",
                    "error_code": "RT_REPO_UNAVAILABLE",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                self._mark_not_tested(steps, "repo_reachable")
                self.log(f"  SKIP Repository unavailable: {path}; {unavailable_reason}")
                self._write(key, repo, "unavailable", 0, 0, 0, 0, "unknown", "", {}, [],
                            exit_code=3, reason=unavailable_reason,
                            steps=steps, failure_code="RT_REPO_UNAVAILABLE",
                            failure_hint=unavailable_reason,
                            error_category="repository_unavailable",
                            error_details=unavailable_reason, error_output=access_error)
                return 3

            passphrase = None
            if encryption != "none":
                try:
                    passphrase = self._read_passphrase(pp_file)
                except FileNotFoundError as exc:
                    self.log(f"  ERROR: {exc}")
                    return 1

            env = self._env(passphrase, repo.get("storage"), path, encryption=encryption)
            t0 = time.time()

            self.log("Level 1: Repository integrity")
            s0 = time.time()
            r = self._borg(["list", "--short", "--last", "1", path], env)
            if r.returncode != 0:
                self.log(f"  ERROR: borg list failed (exit {r.returncode})")
                self.log(f"  {r.stderr[:300]}")
                err = self._analyze_error(r.stderr)
                code = self._failure_code_from_category(err["category"])
                steps.append({
                    "step_id": "repo_reachable",
                    "status": "failed",
                    "duration_ms": int((time.time() - s0) * 1000),
                    "message": "Repository check failed",
                    "command": f"borg list --short --last 1 {path}",
                    "error_code": code,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                self._mark_not_tested(steps, "repo_reachable")
                self._write(key, repo, "failed", int(time.time()-t0), 0, 0, 0, "unknown", "", {}, [],
                            exit_code=1, error_category=err["category"],
                            error_details=err["details"], error_output=r.stderr[:500],
                            steps=steps, failure_code=code, failure_hint=err["details"])
                return 1
            steps.append({
                "step_id": "repo_reachable",
                "status": "passed",
                "duration_ms": int((time.time() - s0) * 1000),
                "message": "Repository reachable",
                "command": f"borg list --short --last 1 {path}",
                "error_code": "",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

            last_archive = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
            if not last_archive:
                self.log("  ERROR: No archive found")
                steps.append({
                    "step_id": "archive_readable",
                    "status": "failed",
                    "duration_ms": 0,
                    "message": "No archive found",
                    "command": f"borg list --short --last 1 {path}",
                    "error_code": "RT_ARCHIVE_MISSING",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                self._mark_not_tested(steps, "archive_readable")
                self._write(key, repo, "failed", int(time.time()-t0), 0, 0, 0, "unknown", "", {}, [],
                            exit_code=1, error_category="archive_missing",
                            error_details="No archive found in repository",
                            steps=steps, failure_code="RT_ARCHIVE_MISSING",
                            failure_hint="No archive found in repository")
                return 1
            steps.append({
                "step_id": "archive_readable",
                "status": "passed",
                "duration_ms": 0,
                "message": f"Archive found: {last_archive}",
                "command": f"borg list --short --last 1 {path}",
                "error_code": "",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            self.log(f"  OK Level 1 - latest archive: {last_archive}")

            archive_stats: dict = {"original_size": 0, "compressed_size": 0, "deduplicated_size": 0, "files_count": 0}
            s_meta = time.time()
            r_info = self._borg(["info", "--json", f"{path}::{last_archive}"], env, timeout=60)
            if r_info.returncode == 0:
                try:
                    info_j = json.loads(r_info.stdout)
                    archives = info_j.get("archives", [])
                    if archives:
                        s = archives[0].get("stats", {})
                        archive_stats = {
                            "original_size": s.get("original_size", 0),
                            "compressed_size": s.get("compressed_size", 0),
                            "deduplicated_size": s.get("deduplicated_size", 0),
                            "files_count": s.get("nfiles", 0),
                        }
                        self.log(f"  Size: {self._fmt_bytes(archive_stats['original_size'])}, files: {archive_stats['files_count']}")
                except (json.JSONDecodeError, KeyError):
                    pass
            steps.append({
                "step_id": "metadata_check",
                "status": "passed" if r_info.returncode == 0 else "failed",
                "duration_ms": int((time.time() - s_meta) * 1000),
                "message": "Metadata read" if r_info.returncode == 0 else "Metadata could not be read",
                "command": f"borg info --json {path}::{last_archive}",
                "error_code": "" if r_info.returncode == 0 else "RT_METADATA_CHECK_FAILED",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

            if r_info.returncode != 0:
                err = self._analyze_error(r_info.stderr)
                code = self._failure_code_from_category(err["category"])
                self._mark_not_tested(steps, "metadata_check")
                self._write(key, repo, "failed", int(time.time() - t0), 0, 0, 0, "unknown",
                            last_archive, archive_stats, [], exit_code=1, steps=steps,
                            error_category=err["category"], error_details=err["details"],
                            failure_code=code, failure_hint=err["details"])
                return 1

            if self.test_level < 2:
                duration = int(time.time() - t0)
                steps.append({
                    "step_id": "restore_probe",
                    "status": "not_tested",
                    "duration_ms": 0,
                    "message": "Not tested (Level 1)",
                    "command": "",
                    "error_code": "",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                steps.append({
                    "step_id": "integrity_check",
                    "status": "not_tested",
                    "duration_ms": 0,
                    "message": "Not tested (Level 1)",
                    "command": "",
                    "error_code": "",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                steps.append({
                    "step_id": "cleanup",
                    "status": "passed",
                    "duration_ms": 0,
                    "message": "Cleanup completed",
                    "command": "",
                    "error_code": "",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                self._write(key, repo, "success", duration, 0, 0, 0, "not_applicable", last_archive, archive_stats, [],
                            exit_code=0, test_coverage_pct=0.0, reason="Only Level 1 is configured",
                            steps=steps)
                self.log(f"OK Restore test succeeded ({duration}s)")
                return 0

            self.log("Level 2: Extract Dry-Run")
            s_probe = time.time()
            sample_limit = min(max(1, self.max_entries), max(1, self.dryrun_max_files))
            r_list, listing = self._list_sample(path, last_archive, env, sample_limit)
            if r_list.returncode != 0:
                err = self._analyze_error(r_list.stderr)
                code = self._failure_code_from_category(err["category"])
                steps.append({"step_id": "restore_probe", "status": "failed",
                              "duration_ms": int((time.time() - s_probe) * 1000),
                              "message": "Could not list archive files for the restore probe",
                              "command": "borg list --json-lines", "error_code": code})
                self._mark_not_tested(steps, "restore_probe")
                self._write(key, repo, "failed", int(time.time()-t0), 0, 0, 0, "unknown",
                            last_archive, archive_stats, [], exit_code=1, steps=steps,
                            error_category=err["category"], error_details=err["details"],
                            failure_code=code, failure_hint=err["details"])
                return 1
            full_count = listing.count
            archive_stats["files_count"] = full_count
            # Reservoir sampling preserves uniform selection without retaining every path (#599).
            target_count = max(1, (full_count * self.min_coverage + 99) // 100)
            test_count = min(full_count, target_count, sample_limit)
            tested_paths = random.sample(listing.paths, test_count)
            tested_entries = [f"- {path}" for path in tested_paths]
            tested_files = tested_total = len(tested_paths)
            tested_folders = 0

            archive_size_gb = int(archive_stats.get("original_size", 0)) / (1024**3) if archive_stats else 0
            force_chunk = self.full_dryrun_max_archive_gb > 0 and archive_size_gb >= self.full_dryrun_max_archive_gb

            if force_chunk and tested_paths:
                self.log(f"  Chunk mode enabled (archive size {archive_size_gb:.1f} GB)")
                self.log(f"  Testing {test_count} of {full_count} files (target {self.min_coverage}%, file limits applied)")
                failed_chunk = None
                completed_paths = []
                for i in range(0, len(tested_paths), max(1, self.dryrun_chunk)):
                    chunk = tested_paths[i:i + max(1, self.dryrun_chunk)]
                    r_chunk = self._borg(["extract", "--dry-run", f"{path}::{last_archive}", *chunk], env, timeout=self.dryrun_timeout)
                    if r_chunk.returncode != 0:
                        failed_chunk = r_chunk
                        break
                    completed_paths.extend(chunk)
                if failed_chunk is not None:
                    tested_files = tested_total = len(completed_paths)
                    tested_entries = [f"- {path}" for path in completed_paths]
                    err = self._analyze_error(failed_chunk.stderr)
                    code = self._failure_code_from_category(err["category"])
                    steps.append({
                        "step_id": "restore_probe",
                        "status": "failed",
                        "duration_ms": int((time.time() - s_probe) * 1000),
                        "message": "Restore probe failed",
                        "command": "borg extract --dry-run <chunked>",
                        "error_code": code,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    self._mark_not_tested(steps, "restore_probe")
                    cov = round(tested_total / full_count * 100, 1) if full_count else 0
                    self._write(key, repo, "failed", int(time.time()-t0), tested_files, tested_folders, tested_total, "partial",
                                last_archive, archive_stats, tested_entries, exit_code=1, test_coverage_pct=cov,
                                error_category=err["category"], error_details=err["details"], error_output=failed_chunk.stderr[:500],
                                steps=steps, failure_code=code, failure_hint=err["details"])
                    return 1
            else:
                self.log(f"  Testing the complete archive ({full_count} files)")
                r_dry = self._borg(["extract", "--dry-run", f"{path}::{last_archive}"], env, timeout=self.dryrun_timeout)
                if r_dry.returncode != 0:
                    tested_files = tested_total = 0
                    tested_entries = []
                    err = self._analyze_error(r_dry.stderr)
                    code = self._failure_code_from_category(err["category"])
                    steps.append({
                        "step_id": "restore_probe",
                        "status": "failed",
                        "duration_ms": int((time.time() - s_probe) * 1000),
                        "message": "Restore probe failed",
                        "command": f"borg extract --dry-run {path}::{last_archive}",
                        "error_code": code,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    self._mark_not_tested(steps, "restore_probe")
                    cov = round(tested_total / full_count * 100, 1) if full_count else 0
                    self._write(key, repo, "failed", int(time.time()-t0), tested_files, tested_folders, tested_total, "partial",
                                last_archive, archive_stats, tested_entries, exit_code=1, test_coverage_pct=cov,
                                error_category=err["category"], error_details=err["details"], error_output=r_dry.stderr[:500],
                                steps=steps, failure_code=code, failure_hint=err["details"])
                    return 1
                if r_dry.returncode == 0:
                    tested_files = tested_total = full_count
            steps.append({
                "step_id": "restore_probe",
                "status": "passed",
                "duration_ms": int((time.time() - s_probe) * 1000),
                "message": "Restore probe succeeded",
                "command": "borg extract --dry-run",
                "error_code": "",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

            cov_pct = 100.0 if (tested_total >= full_count) else (round(tested_total / full_count * 100, 1) if full_count else 0)
            coverage = "complete" if tested_total >= full_count else "partial"
            l3: dict = {"enabled": False, "sample_size": self.sample_size, "success_count": 0, "failed_count": 0, "checksums": [], "failed_files": []}
            exit_code = 0
            error_category = "none"
            error_details = ""

            if self.test_level == 3:
                self.log("Level 3: Sample restore (SHA256 validation)")
                l3["enabled"] = True
                regular = self._collect_level3_legacy_pool(path, last_archive, env, limit=1000) if self.level3_legacy_sampling else [e[2:] for e in tested_entries if e.startswith("- ")]
                sample = random.sample(regular, min(self.sample_size, len(regular))) if regular else []
                if not sample:
                    exit_code = 1
                    error_category = "archive_missing"
                    error_details = "No regular files found for the Level 3 sample"
                checksums: list = []
                failed_files: list = []
                for fpath in sample:
                    sha = hashlib.sha256()
                    proc = self._borg(["extract", "--stdout", f"{path}::{last_archive}", fpath],
                                      env, timeout=self.dryrun_timeout, consume=sha.update)
                    if proc.returncode == 0:
                        checksums.append(f"{fpath}:{sha.hexdigest()}")
                    else:
                        failed_files.append(fpath)
                l3["success_count"] = len(checksums)
                l3["failed_count"] = len(failed_files)
                l3["checksums"] = checksums
                l3["failed_files"] = failed_files
                if failed_files:
                    exit_code = 1
                    error_category = "sample_restore_failed"
                    error_details = f"Sample restore: {len(failed_files)}/{len(sample)} files failed"

            if exit_code == 0:
                steps.append({
                    "step_id": "integrity_check",
                    "status": "passed",
                    "duration_ms": 0,
                    "message": "Integrity/sample check succeeded",
                    "command": "sha256 sample compare",
                    "error_code": "",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                steps.append({
                    "step_id": "cleanup",
                    "status": "passed",
                    "duration_ms": 0,
                    "message": "Cleanup completed",
                    "command": "remove temp test data",
                    "error_code": "",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
            else:
                code = self._failure_code_from_category(error_category)
                steps.append({
                    "step_id": "integrity_check",
                    "status": "failed",
                    "duration_ms": 0,
                    "message": "Integrity/sample check failed",
                    "command": "sha256 sample compare",
                    "error_code": code,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                self._mark_not_tested(steps, "integrity_check")

            duration = int(time.time() - t0)
            result = "success" if exit_code == 0 else "failed"
            self._write(key, repo, result, duration, tested_files, tested_folders, tested_total, coverage, last_archive, archive_stats, tested_entries,
                        exit_code=exit_code, test_coverage_pct=cov_pct, l3_details=l3, error_category=error_category, error_details=error_details,
                        steps=steps, failure_code=self._failure_code_from_category(error_category), failure_hint=error_details)
            if exit_code == 0:
                self.log(f"OK Restore test succeeded ({duration}s)")
            else:
                self.log(f"ERROR Restore test failed ({duration}s)")
            return exit_code
        finally:
            self._cleanup_smb_mount(repo, smb_mounted_by_me)

    # ── .test Datei schreiben ─────────────────────────────────────────────────

    def _write(self, key: str, repo: dict, result_str: str, duration: int,
               tested_files: int, tested_folders: int, tested_total: int,
               coverage: str, archive: str, stats: dict, entries: list,
               exit_code: int = 0, test_coverage_pct: float = 0.0,
               l3_details: dict = None, error_category: str = "none",
               error_details: str = "", error_output: str = "", reason: str = "",
               steps: list | None = None, failure_code: str = "", failure_hint: str = "") -> None:
        from job_identity import validate_job_id
        key = validate_job_id(key)
        _ensure_status_storage_directory(self.status_dir)
        # A busy repository is not a new verification result. Keep the prior evidence.
        suffix = ".skip.test" if result_str == "skipped" else ".test"
        test_file = self.status_dir / f"{key}{suffix}"
        now = datetime.now()
        start_ts = now.timestamp() - max(0, int(duration))
        overall_status = (
            "passed" if result_str == "success"
            else ("failed" if result_str in {"failed", "unavailable"} else "warning")
        )

        data = {
            "job_id":                   key,
            "report_schema_version":    1,
            "report_id":                f"RT-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex}",
            "log_file":                 str(getattr(self, "log_path", "")),
            "repository":              repo["path"],
            "job_name":                repo.get("name") or key,
            "location":                repo["location"],
            "test_level":              self.test_level,
            "test_date":               now.strftime("%Y-%m-%d %H:%M:%S"),
            "test_duration_seconds":   duration,
            "test_result":             result_str,
            "test_exit_code":          exit_code,
            "start_ts":                datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d %H:%M:%S"),
            "end_ts":                  now.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_ms":             int(max(0, duration) * 1000),
            "tested_files":            tested_files,
            "tested_files_count":      tested_files,
            "tested_folders_count":    tested_folders,
            "tested_total_count":      tested_total,
            "test_coverage":           coverage,
            "test_coverage_percentage": test_coverage_pct,
            "coverage_percent":        test_coverage_pct,
            "coverage_basis":          f"{tested_files}/{stats.get('files_count', 0) if isinstance(stats, dict) else 0}",
            "tested_archive":          archive,
            "tested_entries":          entries,
            "overall_status":          overall_status,
            "archive_stats":           stats or {
                "original_size": 0, "compressed_size": 0,
                "deduplicated_size": 0, "files_count": 0,
            },
            "error_analysis": {
                "has_error":             exit_code != 0,
                "error_category":        error_category or "none",
                "error_details":         error_details,
                "error_affected_items":  "",
                "error_output":          error_output[:500] if error_output else "",
            },
            "failure_code": failure_code,
            "failure_hint": failure_hint,
            "level3_details": l3_details or {
                "enabled": False, "sample_size": self.sample_size,
                "success_count": 0, "failed_count": 0, "checksums": [], "failed_files": [],
            },
            "steps": steps or [],
        }
        if reason:
            data["reason"] = reason

        if getattr(self.args, "resource_worker", False):
            from restore_test_reports import _atomic_write
            _atomic_write(Path(os.environ["BORG_UI_RESTORE_RESULT"]), json.dumps(data, ensure_ascii=False))
        else:
            self._publish_report(test_file, data, repo)

    def _publish_report(self, test_file: Path, data: dict, repo: dict) -> None:
        """Persist final evidence before updating dashboard and scheduled notifications."""
        from restore_test_reports import save_report
        save_report(test_file, data)
        result_str = data["test_result"]
        if result_str != "skipped":
            (self.status_dir / f"{data['job_id']}.skip.test").unlink(missing_ok=True)
        self.log(f"  → Ergebnis: {test_file}")
        _refresh_unraid_dashboard_widget_cache(self.conf, "restore test result written", self.log)
        if result_str == "success":
            self._notify_event("restore_test_success", repo, "Successful", data["test_duration_seconds"], data["test_coverage"])
        elif result_str in {"failed", "unavailable"} and data.get("failure_code") != "RT_CANCELLED":
            detail = data.get("failure_hint") or data["error_analysis"].get("error_details") or data.get("reason") or "Restore test failed"
            self._notify_event("restore_test_failed", repo, "Failed", data["test_duration_seconds"], data["test_coverage"], detail)


# ── Hauptprogramm ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=f"Borg Restore Test v{VERSION}")
    parser.add_argument("--force",    action="store_true",
                        help="Force tests even when they are not due")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Show what would be tested without making changes")
    parser.add_argument("--level",    type=int, default=2, choices=[1, 2, 3],
                        help="Test level: 1=integrity, 2=dry run (default), 3=sample restore")
    parser.add_argument("--location", default="local",
                        choices=["local", "usb", "smb", "storagebox", "all"],
                        help="Locations to test (default: local)")
    parser.add_argument("--smb-auto-mount", action="store_true",
                        help="Mount SMB repositories before testing and unmount them afterward")
    parser.add_argument("--scheduled", action="store_true",
                        help="Run was started by the scheduler; enables background notifications")
    parser.add_argument("--job-key",  dest="job_keys", action="append", default=[],
                        help="Optionally test only selected jobs (for example flash_local); may be repeated")
    parser.add_argument("--resource-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    conf  = load_conf()
    tester = RestoreTest(conf, args)
    try:
        from python_runtime_info import runtime_log_line
        tester.log(runtime_log_line())
        if args.resource_worker:
            try:
                repos = [repo for repo in discover_repos(conf) if repo["job_key"] in args.job_keys]
                if len(repos) != 1:
                    tester.log("ERROR: protected worker requires exactly one configured repository")
                    sys.exit(1)
                sys.exit(tester._test_repo_locked(repos[0]))
            finally:
                tester.close()
        run_id = os.environ.get("BORG_UI_RUN_ID", "").strip()
        request_id = os.environ.get("BORG_UI_REQUEST_ID", "").strip()
        source = os.environ.get("BORG_UI_REQUEST_SOURCE", "").strip() or ("schedule" if args.scheduled else "manual")
        actor = os.environ.get("BORG_UI_REQUEST_ACTOR", "").strip()
        started_at = time.time()

        tester.log(f"{'='*60}")
        tester.log(f"Borg Restore Test v{VERSION}")
        tester.log(f"Level: {args.level} | Location: {args.location} | Force: {args.force}")
        tester.log(f"Log: {tester.log_path}")
        tester.log(f"{'='*60}")
        if not request_id:
            emit_lifecycle(
                "RESTORE_TEST",
                "requested",
                source=source,
                actor=actor,
                run_id=run_id,
                level=args.level,
                location=args.location,
                selected_jobs=args.job_keys,
            )
        emit_lifecycle(
            "RESTORE_TEST",
            "process_started",
            request_id=request_id,
            source=source,
            actor=actor,
            run_id=run_id,
            pid=os.getpid(),
            level=args.level,
            location=args.location,
            log_file=str(tester.log_path),
            selected_jobs=args.job_keys,
        )

        repos = discover_repos(conf)
        if args.job_keys:
            wanted = {str(k).strip() for k in args.job_keys if str(k).strip()}
            repos = [r for r in repos if str(r.get("job_key", "")).strip() in wanted]
        elif args.location != "all":
            repos = [r for r in repos if r["location"] == args.location]

        if not repos:
            tester.log("No repositories configured; check job metadata, profile settings and backup.conf")
            emit_lifecycle(
                "RESTORE_TEST",
                "finished",
                request_id=request_id,
                source=source,
                actor=actor,
                run_id=run_id,
                status="skipped",
                exit_code=0,
                duration_seconds=max(0, int(time.time() - started_at)),
                log_file=str(tester.log_path),
                reason="no_repositories",
            )
            tester.close()
            sys.exit(0)

        tester.log(f"Repositories: {len(repos)}")
        tester.log("")

        ok = fail = skipped = unavail = 0
        for repo in repos:
            rc = tester.test_repo(repo)
            tester.log("")
            if   rc == 0: ok      += 1
            elif rc == 1: fail    += 1
            elif rc == 2: skipped += 1
            elif rc == 3: unavail += 1
            if getattr(tester, "_cancelled", False):
                break

        tester.log(f"{'='*60}")
        tester.log(f"Summary: {ok} OK | {fail} failed | {unavail} unavailable | {skipped} skipped")
        cancelled = getattr(tester, "_cancelled", False)
        exit_code = 130 if cancelled else (1 if fail else (2 if not ok and skipped else 0))
        status = "cancelled" if cancelled else ("failed" if fail else ("unavailable" if unavail else ("skipped" if not ok and skipped else "success")))
        emit_lifecycle(
            "RESTORE_TEST",
            "finished",
            request_id=request_id,
            source=source,
            actor=actor,
            run_id=run_id,
            status=status,
            exit_code=exit_code,
            duration_seconds=max(0, int(time.time() - started_at)),
            log_file=str(tester.log_path),
            ok_count=ok,
            failed_count=fail,
            unavailable_count=unavail,
            skipped_count=skipped,
        )
        tester.close()
        sys.exit(exit_code)
    finally:
        tester.close()


if __name__ == "__main__":
    main()
