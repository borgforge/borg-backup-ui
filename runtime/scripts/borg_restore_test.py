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
    - backup.conf mit REPO_*-Variablen
    - Passphrase-Dateien aus backup.conf
"""

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

VERSION = "1.0.0"

SCRIPT_DIR = Path(__file__).parent.resolve()

# Lib-Pfad: ausschließlich plugin runtime/lib (kein Fallback)
_LIB_DIR = SCRIPT_DIR.parent / "lib"
if _LIB_DIR.is_dir():
    sys.path.insert(0, str(_LIB_DIR.parent))

# Config-Laden: entweder via lib.status oder direkt
try:
    from lib.status import load_config as _lib_load_config
    def _load_conf_file(path: Path) -> dict:
        return _lib_load_config(path)
except ImportError:
    def _load_conf_file(path: Path) -> dict:
        conf = {}
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip().lstrip("readonly ")
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                conf[k.strip()] = v.strip().strip('"').strip("'")
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


def discover_repos(conf: dict) -> list:
    """Baut Repo-Liste ausschließlich aus Job-Metadaten."""
    jobs_dir_candidates = [
        Path("/boot/config/borg-backup/config/jobs"),
        SCRIPT_DIR / "config" / "jobs",
        SCRIPT_DIR.parent / "config" / "jobs",
    ]
    repos = []
    seen = set()

    for jobs_dir in jobs_dir_candidates:
        if not jobs_dir.is_dir():
            continue
        for jf in sorted(jobs_dir.glob("*.json")):
            try:
                raw = json.loads(jf.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not bool(raw.get("enabled", True)):
                continue
            if str(raw.get("runner", "")).strip() != "scriptless-wizard-runner":
                continue

            btype = str(raw.get("backup_type", "")).strip()
            location = str(raw.get("location", "")).strip().lower()
            if not btype or location not in {"local", "usb", "smb", "storagebox", "custom"}:
                continue

            repo_cfg = raw.get("repo") if isinstance(raw.get("repo"), dict) else {}
            pass_cfg = raw.get("passphrase") if isinstance(raw.get("passphrase"), dict) else {}

            repo_key = str(repo_cfg.get("conf_key") or "").strip()
            repo_default = str(repo_cfg.get("default") or "").strip()
            repo_path = conf.get(repo_key, repo_default) if repo_key else repo_default
            if not repo_path:
                continue

            pass_key = str(pass_cfg.get("conf_key") or "").strip()
            pass_default = str(pass_cfg.get("default") or "").strip()
            pass_file = conf.get(pass_key, pass_default) if pass_key else pass_default

            key = (btype.lower(), location, repo_path)
            if key in seen:
                continue
            seen.add(key)
            repos.append({
                "job_key":         str(raw.get("job_key") or f"{btype}_{location}").strip(),
                "type":            btype,
                "location":        location,
                "path":            repo_path,
                "passphrase_file": pass_file,
                "smb_profile_key": str(raw.get("smb_profile_key") or "").strip().lower(),
                "mount_before_run": bool(raw.get("mount_before_run", True)),
                "unmount_after_run": bool(raw.get("unmount_after_run", True)),
            })

    return repos


# ── Restore Tester ─────────────────────────────────────────────────────────────

class RestoreTest:
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
        self.status_dir      = Path(conf.get(
            "RESTORE_TEST_STATUS_DIR",
            str(Path(conf.get("STATUS_DIR", "/mnt/user/backup-status")) / "restore-tests")
        ))
        self.min_coverage    = int(conf.get("RESTORE_TEST_MIN_COVERAGE", 5))
        self.max_entries     = int(conf.get("RESTORE_TEST_MAX_ENTRIES", 10000))
        self.sample_size     = int(conf.get("RESTORE_TEST_SAMPLE_SIZE", 5))
        self.borg_timeout    = int(conf.get("RESTORE_TEST_BORG_TIMEOUT", 180))
        self.dryrun_timeout  = int(conf.get("RESTORE_TEST_DRY_RUN_TIMEOUT", 0))  # 0 = no timeout
        self.dryrun_chunk    = int(conf.get("RESTORE_TEST_DRY_RUN_CHUNK_SIZE", 200))
        self.dryrun_max_files = int(conf.get("RESTORE_TEST_DRY_RUN_MAX_FILES", 1500))
        self.level3_legacy_sampling = str(conf.get("RESTORE_TEST_LEVEL3_LEGACY_SAMPLING", "false")).strip().lower() == "true"
        force_types_raw = str(conf.get("RESTORE_TEST_FORCE_CHUNK_TYPES", "vms"))
        self.force_chunk_types = {x.strip().lower() for x in force_types_raw.split(",") if x.strip()}
        self.full_dryrun_max_archive_gb = int(conf.get("RESTORE_TEST_FULL_DRYRUN_MAX_ARCHIVE_GB", 200))
        self.log_dir         = Path(conf.get("GLOBAL_LOG_DIR", "/mnt/user/Logs"))

        self.log_dir.mkdir(parents=True, exist_ok=True)
        date_tag = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_path = self.log_dir / f"Borg-Restore-Test--{date_tag}.log"
        self._fh = open(self.log_path, "w", buffering=1, encoding="utf-8")

    def log(self, msg: str = "") -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}" if msg else ""
        print(line, flush=True)
        self._fh.write(line + "\n")

    def close(self) -> None:
        self._fh.close()

    # ── Hilfsmethoden ──────────────────────────────────────────────────────────

    def _env(self, passphrase: str) -> dict:
        env = dict(os.environ)
        env["BORG_PASSPHRASE"] = passphrase
        env.pop("BORG_PASSCOMMAND", None)
        return env

    def _borg(self, args: list, env: dict, timeout: int | None = None) -> subprocess.CompletedProcess:
        if timeout is None:
            timeout = self.borg_timeout
        run_timeout = None if int(timeout) <= 0 else int(timeout)
        try:
            return subprocess.run(
                ["borg"] + args,
                capture_output=True, text=True, env=env, timeout=run_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            cmd = ["borg"] + args
            stderr = f"Command timed out after {run_timeout}s: {' '.join(cmd)}"
            if exc.stderr:
                stderr = f"{stderr}\n{exc.stderr}"
            return subprocess.CompletedProcess(
                cmd, 124, exc.stdout or "", stderr
            )

    @staticmethod
    def _read_passphrase(pp_file: str) -> str:
        p = Path(pp_file)
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
        raise FileNotFoundError(f"Passphrase file not found: {pp_file}")

    def _parse_smb_profiles(self) -> dict:
        raw = str(self.conf.get("SMB_PROFILES_JSON", "[]") or "[]")
        try:
            rows = json.loads(raw)
        except Exception:
            rows = []
        out = {}
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                key = str(row.get("key", "")).strip().lower()
                if key:
                    out[key] = row
        return out

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

        key = str(repo.get("smb_profile_key") or "").strip().lower()
        if not key:
            return False, "SMB profile is missing from the job"
        profiles = self._parse_smb_profiles()
        profile = profiles.get(key)
        if not isinstance(profile, dict):
            return False, f"SMB profile not found: {key}"

        server = str(profile.get("server", "")).strip()
        share = str(profile.get("share", "")).strip().lstrip("/")
        mount_path = str(profile.get("mount_path", "")).strip()
        vers = str(profile.get("vers", "")).strip() or "3.0"
        sec = str(profile.get("sec", "")).strip()
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

        opts = [f"credentials={pf}", "iocharset=utf8", f"vers={vers}"]
        if sec:
            opts.append(f"sec={sec}")
        res = subprocess.run(
            ["mount", "-t", "cifs", f"//{server}/{share}", mount_path, "-o", ",".join(opts)],
            capture_output=True, text=True, timeout=30, check=False
        )
        if res.returncode != 0:
            return False, (res.stderr or res.stdout or "SMB mount failed").strip()
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
        mount_path = str(repo.get("path", "")).strip()
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
        r = self._borg(["list", "--json-lines", f"{path}::{archive}"], env, timeout=300)
        if r.returncode != 0:
            return []
        files = []
        for line in r.stdout.splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("type") == "-":
                p = str(e.get("path", "")).strip()
                if p:
                    files.append(p)
                    if len(files) >= limit:
                        break
        return files

    # ── Intervall-Prüfung ──────────────────────────────────────────────────────

    def _should_test(self, key: str) -> bool:
        if self.args.force:
            return True
        tf = self.status_dir / f"{key}.test"
        if not tf.exists():
            return True
        try:
            raw = json.loads(tf.read_text(encoding="utf-8"))
            last_result = str(raw.get("test_result", "")).strip().lower()
            if last_result != "success":
                self.log(f"  Latest test status: {last_result or 'unknown'} - a new test is required")
                return True
        except Exception:
            # Bei beschädigter/inkompatibler Testdatei lieber erneut testen.
            self.log("  Latest test file is not readable; a new test is required")
            return True
        age_days = (time.time() - tf.stat().st_mtime) / 86400
        if age_days >= self.test_interval:
            self.log(f"  Last test was {age_days:.0f} days ago; test is due")
            return True
        self.log(f"  Last test was {age_days:.0f} days ago; not due yet (interval: {self.test_interval}d)")
        return False

    # ── Fehleranalyse ──────────────────────────────────────────────────────────

    @staticmethod
    def _analyze_error(output: str) -> dict:
        lo = output.lower()
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
        """0=OK, 1=Fehler, 2=übersprungen, 3=unavailable"""
        btype    = repo["type"]
        location = repo["location"]
        path     = repo["path"]
        pp_file  = repo["passphrase_file"]
        key      = str(repo.get("job_key") or f"{btype}_{location}")

        self.log(f"{'─'*60}")
        self.log(f"TEST: {btype} ({location})")
        self.log(f"  Repository: {path}")

        if self.args.dry_run:
            self.log("  [dry-run] Skipped")
            return 2

        if not self._should_test(key):
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
            if not path.startswith("ssh://") and not Path(path).is_dir():
                steps.append({
                    "step_id": "repo_reachable",
                    "status": "failed",
                    "duration_ms": 0,
                    "message": "Repository unreachable",
                    "command": "",
                    "error_code": "RT_REPO_UNAVAILABLE",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                self._mark_not_tested(steps, "repo_reachable")
                self.log(f"  SKIP Repository unavailable: {path}")
                self._write(key, repo, "unavailable", 0, 0, 0, 0, "unknown", "", {}, [],
                            exit_code=3, reason="Repository is not mounted or reachable",
                            steps=steps, failure_code="RT_REPO_UNAVAILABLE",
                            failure_hint="Repository is not mounted or reachable")
                return 3

            try:
                passphrase = self._read_passphrase(pp_file)
            except FileNotFoundError as exc:
                self.log(f"  ERROR: {exc}")
                return 1

            env = self._env(passphrase)
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
            r_count = self._borg(["list", "--short", f"{path}::{last_archive}"], env, timeout=300)
            full_count = len(r_count.stdout.splitlines()) if r_count.returncode == 0 else 0
            test_count = max(100, full_count * self.min_coverage // 100) if full_count else 100
            test_count = min(test_count, self.max_entries)
            self.log(f"  Testing {test_count} of {full_count} entries")

            r_list = self._borg(["list", "--json-lines", f"{path}::{last_archive}"], env, timeout=300)
            tested_entries: list = []
            tested_files = tested_folders = 0
            if r_list.returncode == 0:
                for line in r_list.stdout.splitlines()[:test_count]:
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    etype = e.get("type", "?")
                    epath = e.get("path", "")
                    if etype == "d":
                        tested_entries.append(f"d {epath}")
                        tested_folders += 1
                    elif etype == "-":
                        tested_entries.append(f"- {epath}")
                        tested_files += 1
                    else:
                        tested_entries.append(f"{etype} {epath}")
            tested_total = len(tested_entries)

            archive_size_gb = int(archive_stats.get("original_size", 0)) / (1024**3) if archive_stats else 0
            force_chunk = btype.strip().lower() in self.force_chunk_types
            if self.full_dryrun_max_archive_gb > 0 and archive_size_gb >= self.full_dryrun_max_archive_gb:
                force_chunk = True

            if force_chunk and tested_entries:
                reason = f"type rule ({btype})" if btype.strip().lower() in self.force_chunk_types else f"archive size {archive_size_gb:.1f} GB"
                self.log(f"  Chunk mode enabled ({reason})")
                failed_chunk = None
                tested_files_only = [e[2:] for e in tested_entries if e.startswith("- ")]
                random.shuffle(tested_files_only)
                tested_paths = tested_files_only[:max(1, self.dryrun_max_files)]
                for i in range(0, len(tested_paths), max(1, self.dryrun_chunk)):
                    chunk = tested_paths[i:i + max(1, self.dryrun_chunk)]
                    r_chunk = self._borg(["extract", "--dry-run", f"{path}::{last_archive}", *chunk], env, timeout=self.dryrun_timeout)
                    if r_chunk.returncode != 0:
                        failed_chunk = r_chunk
                        break
                if failed_chunk is not None:
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
                r_dry = self._borg(["extract", "--dry-run", f"{path}::{last_archive}"], env, timeout=self.dryrun_timeout)
                if r_dry.returncode != 0 and not (r_dry.returncode == 124 and tested_entries):
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
                    proc = subprocess.Popen(["borg", "extract", "--stdout", f"{path}::{last_archive}", fpath], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
                    sha = hashlib.sha256()
                    while True:
                        chunk = proc.stdout.read(65536)
                        if not chunk:
                            break
                        sha.update(chunk)
                    proc.wait()
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
        self.status_dir.mkdir(parents=True, exist_ok=True)
        test_file = self.status_dir / f"{key}.test"
        now = datetime.now()
        start_ts = now.timestamp() - max(0, int(duration))
        overall_status = (
            "passed" if result_str == "success"
            else ("failed" if result_str in {"failed", "unavailable"} else "warning")
        )

        data = {
            "report_schema_version":    1,
            "report_id":                f"RT-{now.strftime('%Y%m%d-%H%M%S')}-{key}",
            "repository":              repo["path"],
            "type":                    repo["type"],
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
            "coverage_basis":          f"{tested_total}/{stats.get('files_count', 0) if isinstance(stats, dict) else 0}",
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

        test_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self.log(f"  → Ergebnis: {test_file}")


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
    parser.add_argument("--job-key",  dest="job_keys", action="append", default=[],
                        help="Optionally test only selected jobs (for example flash_local); may be repeated")
    args = parser.parse_args()

    conf  = load_conf()
    tester = RestoreTest(conf, args)

    tester.log(f"{'='*60}")
    tester.log(f"Borg Restore Test v{VERSION}")
    tester.log(f"Level: {args.level} | Location: {args.location} | Force: {args.force}")
    tester.log(f"Log: {tester.log_path}")
    tester.log(f"{'='*60}")

    repos = discover_repos(conf)
    if args.location != "all":
        repos = [r for r in repos if r["location"] == args.location]
    if args.job_keys:
        wanted = {str(k).strip() for k in args.job_keys if str(k).strip()}
        repos = [r for r in repos if str(r.get("job_key", "")).strip() in wanted]

    if not repos:
        tester.log("No repositories configured; check backup.conf")
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

    tester.log(f"{'='*60}")
    tester.log(f"Summary: {ok} OK | {fail} failed | {unavail} unavailable | {skipped} skipped")
    tester.close()
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
