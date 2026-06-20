"""
lib/backup_job.py - Borg Backup Job Infrastruktur
Version: 1.0.0

Ersetzt die Job-Infrastruktur aus lib/borg-common.sh:
- EXIT-Trap (cleanup_exit L520) → BackupJob.__exit__
- ERR-Trap (error_handler L589)  → Exception-Handling in __exit__
- validate_prerequisites() L190  → check_prerequisites()
- check_usb_mount() L85          → check_usb_mount()
- check_parity_status() L141     → check_parity()
- cleanup_old_logs() L605        → cleanup_old_logs()
- save_backup_status() L716      → _save_status() + BackupStatus.save()

Verbesserungen gegenüber Bash:
- Context Manager ersetzt EXIT/ERR-Traps (kein globaler Zustand)
- SystemExit(0) für Skip-Szenarien (USB/Parity) – sauber aus __exit__ erkennbar
- JSON-Escaping via json.dumps (kein manuelles String-Escaping)
- Repository-Größe via strukturiertem JSON-Parser statt grep -oP

Nur Python Standard-Library: dataclasses, datetime, json, logging, os,
                              pathlib, re, shutil, subprocess, time
"""

from __future__ import annotations

import json
import fcntl
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from lib.docker_manager import DockerManager, DockerStopResult
    from lib.vm_manager import VmManager, VmShutdownResult
    from lib.borg_runner import BorgStats
    from lib.notifications import MailConfig

logger = logging.getLogger(__name__)

_HR = "━" * 80


def _log_section(title: str) -> None:
    logger.info(_HR)
    logger.info("  %s", title)
    logger.info(_HR)


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

@dataclass
class BackupJobConfig:
    """
    Konfiguration für einen Backup-Job.

    Alle Werte kommen aus Umgebungsvariablen (identisch zu den Bash-Skripten).

    Beispiel:
        cfg = BackupJobConfig.from_config(os.environ)
        with BackupJob(cfg) as job:
            job.check_prerequisites()
            ...
    """

    job_name: str
    backup_type: str
    backup_location: str
    lock_file: Path
    log_dir: Path
    log_file: Path
    backup_paths: List[Path]
    borg_cache_dir: Path
    date_tag: str
    log_retention_days: int = 30
    status_dir: Path = Path("/mnt/user/backup-status")
    borg_repo: str = ""
    borg_check_flag_file: Optional[Path] = None
    borg_check_interval_days: int = 30
    borg_compression: str = "lz4"
    borg_keep_daily: int = 7
    borg_keep_weekly: int = 4
    borg_keep_monthly: int = 6
    borg_keep_yearly: int = 3

    @classmethod
    def from_config(cls, env: dict) -> "BackupJobConfig":
        """Liest Konfiguration aus Umgebungsvariablen."""
        paths_str = env.get("BACKUP_PATHS", "")
        backup_paths = [Path(p) for p in paths_str.split() if p] if paths_str else []

        status_dir_str = (
            env.get("STATUS_DIR_OVERRIDE")
            or env.get("STATUS_DIR")
            or "/mnt/user/backup-status"
        )

        flag_str = env.get("BORG_CHECK_FLAG_FILE", "")
        check_flag_file = Path(flag_str) if flag_str else None

        return cls(
            job_name=env.get("JOB_NAME", "Borg Backup"),
            backup_type=env.get("BACKUP_TYPE", "unknown"),
            backup_location=env.get("BACKUP_LOCATION") or env.get("LOCATION", "unknown"),
            lock_file=Path(env.get("LOCK_FILE", "/tmp/borg-backup.lock")),
            log_dir=Path(env.get("LOG_DIR", "/tmp")),
            log_file=Path(env.get("LOG_FILE", "/tmp/borg-backup.log")),
            backup_paths=backup_paths,
            borg_cache_dir=Path(env.get("BORG_CACHE_DIR", "/tmp/borg-cache")),
            date_tag=env.get("DATE_TAG", datetime.now().strftime("%Y-%m-%d")),
            log_retention_days=int(env.get("LOG_RETENTION_DAYS", "30") or "30"),
            status_dir=Path(status_dir_str),
            borg_repo=env.get("BORG_REPO", ""),
            borg_check_flag_file=check_flag_file,
            borg_check_interval_days=int(
                env.get("BORG_CHECK_INTERVAL_DAYS", "30") or "30"
            ),
            borg_compression=env.get("BORG_COMPRESSION", "lz4") or "lz4",
            borg_keep_daily=int(env.get("BORG_KEEP_DAILY", "7") or "7"),
            borg_keep_weekly=int(env.get("BORG_KEEP_WEEKLY", "4") or "4"),
            borg_keep_monthly=int(env.get("BORG_KEEP_MONTHLY", "6") or "6"),
            borg_keep_yearly=int(env.get("BORG_KEEP_YEARLY", "3") or "3"),
        )


# ---------------------------------------------------------------------------
# Haupt-Klasse
# ---------------------------------------------------------------------------

class BackupJob:
    """
    Context Manager für Borg Backup Jobs.

    Ersetzt die Bash EXIT/ERR-Traps aus borg-common.sh. Der __exit__-Block
    übernimmt Cleanup, Notifications, Status-Speicherung und Docker-Neustart.

    Skip-Szenarien (check_usb_mount, check_parity) lösen SystemExit(0) aus.
    __exit__ erkennt dies und überspringt Notifications/Status-Speicherung,
    da die Skips bereits eigene Notifications senden.
    """

    def __init__(
        self,
        config: BackupJobConfig,
        docker_manager: Optional["DockerManager"] = None,
        vm_manager: Optional["VmManager"] = None,
        mail_config: Optional["MailConfig"] = None,
    ) -> None:
        self.config = config
        self.docker_manager = docker_manager
        self.vm_manager = vm_manager
        self.mail_config = mail_config

        self._start_time: float = 0.0
        self._borg_exit: int = 99
        self._final_msg: str = ""
        self._borg_stats: Optional["BorgStats"] = None
        self._docker_stop_result: Optional["DockerStopResult"] = None
        self._docker_restarted: bool = False
        self._vm_shutdown_result: Optional["VmShutdownResult"] = None
        self._vms_restarted: bool = False
        self._final_sent: bool = False
        self._skip_finish: bool = False
        self._skip_reason: str = ""
        self._skip_status_written: bool = False
        self._lock_fd = None

    # ------------------------------------------------------------------
    # Context Manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "BackupJob":
        self._start_time = time.time()
        self._log_startup_banner()
        self._create_lock()
        return self

    def _log_startup_banner(self) -> None:
        cfg = self.config
        _log_section("BACKUP START")
        logger.info("Job:   %s", cfg.job_name)
        logger.info("Date: %s", cfg.date_tag)
        logger.info("Log:   %s", cfg.log_file)
        logger.info("")
        logger.info("Effective configuration:")
        logger.info("  Repository:  %s", cfg.borg_repo or os.environ.get("BORG_REPO", ""))
        logger.info("  Compression: %s", cfg.borg_compression)
        logger.info(
            "  Retention:   %dd / %dw / %dm / %dy",
            cfg.borg_keep_daily, cfg.borg_keep_weekly,
            cfg.borg_keep_monthly, cfg.borg_keep_yearly,
        )
        logger.info("  Log-Dir:     %s (%d days)", cfg.log_dir, cfg.log_retention_days)
        logger.info("  Cache:       %s", cfg.borg_cache_dir)
        if self.mail_config and self.mail_config.recipient:
            logger.info("  Mail:        %s (on error)", self.mail_config.recipient)
        if self.vm_manager is not None:
            logger.info("  VM Timeout:  %ds", self.vm_manager.config.shutdown_timeout)
        logger.info("")

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Skip-Szenarien (USB/Parity): als Warning-Status speichern, dann sauber beenden
        if exc_type is SystemExit and getattr(exc_val, "code", None) == 0:
            self._skip_finish = True

        # Unbehandelte Exceptions: Exit-Code auf 2 setzen
        if exc_type is not None and not self._skip_finish:
            if self._borg_exit == 99:
                self._borg_exit = 2
            logger.error("Job aborted by exception: %s", exc_val)

        if not self._skip_finish:
            _log_section("PHASE 5: CLEANUP & COMPLETION")

        self._restart_docker()

        if self._skip_finish:
            self._persist_skip_status_once()
        else:
            self._do_finish()

        self._remove_lock()
        return False

    # ------------------------------------------------------------------
    # Öffentliche Methoden
    # ------------------------------------------------------------------

    def set_result(
        self,
        borg_exit: int,
        borg_stats: Optional["BorgStats"] = None,
        final_msg: str = "",
    ) -> None:
        """Setzt das Backup-Ergebnis. Muss vor Ende des with-Blocks aufgerufen werden."""
        self._borg_exit = borg_exit
        self._borg_stats = borg_stats
        self._final_msg = final_msg

    def stop_docker(self) -> None:
        """Stoppt Docker-Container für das Backup."""
        if self.docker_manager is not None:
            self._docker_stop_result = self.docker_manager.stop_all(
                str(self.config.log_file)
            )

    def start_docker(self) -> None:
        """Startet Docker-Container neu. Wird automatisch in __exit__ aufgerufen."""
        if (
            self.docker_manager is not None
            and self._docker_stop_result is not None
            and not self._docker_restarted
        ):
            self._docker_restarted = True
            self.docker_manager.start_all(self._docker_stop_result)

    def shutdown_vms(self) -> None:
        """Fährt VMs herunter (mit Vorwarnung). Tracking für Neustart in __exit__."""
        if self.vm_manager is not None:
            self._vm_shutdown_result = self.vm_manager.shutdown_all()

    def start_vms(self) -> None:
        """Startet VMs neu. Wird automatisch in __exit__ aufgerufen."""
        if (
            self.vm_manager is not None
            and self._vm_shutdown_result is not None
            and not self._vms_restarted
        ):
            self._vms_restarted = True
            self.vm_manager.start_all(self._vm_shutdown_result)

    def check_usb_mount(self, mount_path: Path) -> None:
        """
        Prüft ob USB-Laufwerk verfügbar und beschreibbar ist.

        Sendet Notification und löst SystemExit(0) aus wenn nicht verfügbar.
        Wird von USB-Backup-Skripten explizit aufgerufen.
        """
        from lib.notifications import notify

        if not mount_path.is_dir():
            self._write_mini_log(
                "USB_NOT_MOUNTED",
                [
                    f"Borg Backup ({self.config.backup_type}) - Skipped because the USB drive is missing",
                    f"Mount path: {mount_path}",
                    "Status: directory does not exist",
                    "Reason: USB drive is not connected or mounted",
                ],
            )
            notify(
                level="warning",
                subject="Backup übersprungen",
                description=f"USB-Laufwerk nicht gemountet ({mount_path}). Bitte anschließen.",
                job_name=f"Borg Backup ({self.config.backup_type})",
            )
            self._skip_reason = f"USB is not mounted: {mount_path}"
            self._persist_skip_status_once()
            raise SystemExit(0)

        if not os.access(mount_path, os.W_OK):
            self._write_mini_log(
                "USB_NOT_WRITABLE",
                [
                    f"Borg Backup ({self.config.backup_type}) - Skipped because the USB drive is read-only",
                    f"Mount path: {mount_path}",
                    "Status: not writable",
                    "Reason: USB drive is read-only or lacks write permissions",
                ],
            )
            notify(
                level="warning",
                subject="Backup übersprungen",
                description=f"USB-Laufwerk nicht beschreibbar ({mount_path}).",
                job_name=f"Borg Backup ({self.config.backup_type})",
            )
            self._skip_reason = f"USB is not writable: {mount_path}"
            self._persist_skip_status_once()
            raise SystemExit(0)

    def check_parity(self) -> None:
        """
        Prüft ob Unraid Parity-Sync läuft.

        Sendet Notification und löst SystemExit(0) aus wenn Parity aktiv ist.
        Kein mdcmd → kein Unraid → Backup läuft normal.
        """
        if not shutil.which("mdcmd"):
            return

        try:
            result = subprocess.run(
                ["mdcmd", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = result.stdout
        except (subprocess.TimeoutExpired, OSError):
            return

        if not output:
            return

        def _get_field(key: str) -> str:
            for line in output.splitlines():
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1]
            return ""

        resync_action = _get_field("mdResyncAction")
        resync_pos = int(_get_field("mdResyncPos") or 0)
        resync_size = int(_get_field("mdResyncSize") or 0)

        if resync_action and resync_action != "idle" and resync_pos > 0:
            from lib.notifications import notify

            progress = (resync_pos * 100 // resync_size) if resync_size > 0 else 0
            logger.info(
                "Parity operation active (%s %d%%); backup will be skipped.",
                resync_action,
                progress,
            )
            self._write_mini_log(
                "SKIPPED_PARITY",
                [
                    f"Borg Backup ({self.config.backup_type}) - Skipped because a parity operation is running",
                    f"Operation: {resync_action}",
                    f"Progress: {progress}% ({resync_pos}/{resync_size})",
                    "Reason: Preserve system performance during the parity operation",
                ],
            )
            notify(
                level="info",
                subject="Backup übersprungen",
                description=f"Parity-{resync_action} läuft ({progress}%). Backup wird später ausgeführt.",
                job_name=f"Borg Backup ({self.config.backup_type})",
            )
            self._skip_reason = f"Parity operation active: {resync_action} ({progress}%)"
            self._persist_skip_status_once()
            raise SystemExit(0)

    def check_prerequisites(self) -> None:
        """
        Prüft Backup-Voraussetzungen: Pfade, borg-Installation, Cache-Verzeichnis.

        Lock-File wird NICHT hier erstellt – das übernimmt __enter__.
        Fehlende Backup-Pfade sind Warnungen (kein Abbruch).
        """
        _log_section("PHASE 1: VALIDATION")
        logger.info("Validating prerequisites...")

        logger.info("  [1/3] Checking backup paths...")
        missing = [p for p in self.config.backup_paths if not p.is_dir()]
        existing_count = len(self.config.backup_paths) - len(missing)
        if missing:
            logger.warning("  WARNING: %d path(s) do not exist:", len(missing))
            for p in missing:
                logger.warning("    - %s", p)
        logger.info(
            "  OK - %d/%d paths found", existing_count, len(self.config.backup_paths)
        )

        logger.info("  [2/3] Checking Borg Backup installation...")
        if not shutil.which("borg"):
            logger.error("  ERROR: borg command not found")
            raise SystemExit(1)
        try:
            proc = subprocess.run(
                ["borg", "--version"], capture_output=True, text=True, timeout=10
            )
            borg_version = proc.stdout.strip().splitlines()[0] if proc.stdout else "unknown"
        except (subprocess.TimeoutExpired, OSError):
            borg_version = "unknown"
        logger.info("  OK - %s", borg_version)

        logger.info("  [3/3] Checking cache directory...")
        self.config.borg_cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("  OK - %s", self.config.borg_cache_dir)

        logger.info("Validation completed successfully")

    def cleanup_old_logs(self) -> None:
        """Löscht Backup-Logs älter als log_retention_days."""
        _log_section("PHASE 2: PREPARATION")
        if not self.config.log_dir.is_dir() or self.config.log_retention_days <= 0:
            return
        logger.info(
            "Removing logs older than %d days...", self.config.log_retention_days
        )
        cutoff = time.time() - (self.config.log_retention_days * 86400)
        pattern = f"Borg-Backup_{self.config.backup_type}--*.log"
        for log_path in self.config.log_dir.glob(pattern):
            try:
                if log_path.stat().st_mtime < cutoff:
                    log_path.unlink()
                    logger.debug("Deleted log: %s", log_path)
            except OSError as exc:
                logger.warning("Could not delete log %s: %s", log_path, exc)

    # ------------------------------------------------------------------
    # Interne Methoden
    # ------------------------------------------------------------------

    def _create_lock(self) -> None:
        """Erstellt atomaren Prozess-Lock via flock und schreibt aktuelle PID."""
        self.config.lock_file.parent.mkdir(parents=True, exist_ok=True)

        # Read stale PID info only for diagnostics/cleanup messaging.
        stale_pid = ""
        if self.config.lock_file.exists():
            try:
                stale_pid = self.config.lock_file.read_text(encoding="utf-8").strip()
                if stale_pid:
                    try:
                        os.kill(int(stale_pid), 0)
                    except (ValueError, ProcessLookupError):
                        logger.warning(
                            "Found stale lock file (PID: %s); replacing lock.",
                            stale_pid,
                        )
                    except PermissionError:
                        # Process exists but belongs to another user/context.
                        pass
            except OSError:
                stale_pid = ""

        fd = open(self.config.lock_file, "a+", encoding="utf-8")
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder_pid = ""
            try:
                fd.seek(0)
                holder_pid = fd.read().strip()
            except OSError:
                holder_pid = stale_pid
            fd.close()
            logger.error(
                "ERROR: Backup is already running (PID: %s, lock: %s)",
                holder_pid or "?",
                self.config.lock_file,
            )
            raise SystemExit(1)

        fd.seek(0)
        fd.truncate()
        fd.write(f"{os.getpid()}\n")
        fd.flush()
        self._lock_fd = fd
        logger.info("Created lock file (PID: %d)", os.getpid())

    def _remove_lock(self) -> None:
        """Entfernt Lock-File."""
        fd = self._lock_fd
        self._lock_fd = None
        try:
            if fd is not None:
                try:
                    fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
                finally:
                    fd.close()
            self.config.lock_file.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove lock file: %s", exc)

    def _restart_docker(self) -> None:
        """Startet Docker-Container und VMs neu, falls sie gestoppt wurden."""
        if not self._docker_restarted and self._docker_stop_result is not None:
            self.start_docker()
        if not self._vms_restarted and self._vm_shutdown_result is not None:
            self.start_vms()

    def _do_finish(self) -> None:
        """Sendet Notifications, speichert Status, versendet Fehler-Mail."""
        if self._final_sent:
            return
        self._final_sent = True

        from lib.notifications import notify, send_backup_log_mail

        exit_code = self._borg_exit
        duration = max(0, int(time.time() - self._start_time))

        if not self._final_msg:
            self._final_msg = f"Backup beendet (borg exit {exit_code})."

        if exit_code == 0:
            logger.info("Borg backup completed successfully (exit 0)")
            notify(
                "info",
                "Backup erfolgreich",
                f"Backup abgeschlossen. Log: {self.config.log_file}",
                job_name=f"Borg Backup ({self.config.backup_type})",
            )
        elif exit_code == 1:
            logger.info("Borg backup completed with warnings (exit 1)")
            notify(
                "warning",
                "Backup mit Warnungen",
                f"Exit 1. Prüfe Log: {self.config.log_file}",
                job_name=f"Borg Backup ({self.config.backup_type})",
            )
        else:
            logger.info("Borg backup failed (exit %d)", exit_code)
            notify(
                "alert",
                "BACKUP FEHLGESCHLAGEN",
                f"Borg Exit {exit_code}. Siehe Log: {self.config.log_file}",
                job_name=f"Borg Backup ({self.config.backup_type})",
            )

        self._save_status(duration)

        if exit_code >= 2 and self.mail_config is not None:
            logger.info("Sending failure email...")
            send_backup_log_mail(
                config=self.mail_config,
                backup_type=self.config.backup_type,
                date_tag=self.config.date_tag,
                exit_code=exit_code,
                duration_seconds=duration,
                log_file=self.config.log_file,
            )
        else:
            logger.info(
                "No email sent (success/warning is included in the weekly summary)"
            )

        logger.info("End: %s", self.config.job_name)
        _log_section("BACKUP COMPLETED")

    def _save_skip_status(self) -> None:
        """Speichert Skip-Läufe als Warning in den normalen Status-Dateien (History sichtbar)."""
        from lib.status import BackupStatus

        duration = max(0, int(time.time() - self._start_time))
        reason = self._skip_reason or "Backup was skipped"
        reason_low = reason.lower()
        if reason_low.startswith("parity operation active"):
            reason_code = "parity_active"
        elif reason_low.startswith("usb is not mounted"):
            reason_code = "usb_not_mounted"
        elif reason_low.startswith("usb is not writable"):
            reason_code = "usb_not_writable"
        else:
            reason_code = "skipped"
        logger.info("Saving skipped status: %s", reason)
        bs = BackupStatus(
            backup_type=self.config.backup_type,
            location=self.config.backup_location,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            duration_seconds=duration,
            exit_code=0,
            status="skipped",
            error_message=f"Skipped: {reason}",
            skip_reason_code=reason_code,
            skip_reason_text=reason,
            log_file=str(self.config.log_file),
            archive_name="",
            original_size=0,
            compressed_size=0,
            deduplicated_size=0,
            files_count=0,
            repository_size=0,
            transfer_speed_bytes_per_sec=0,
            repository_check_date="unknown",
            repository_check_status="unknown",
            repository_next_check="unknown",
        )
        try:
            bs.save(self.config.status_dir)
            self._skip_status_written = True
        except OSError as exc:
            logger.warning("Could not save skipped status: %s", exc)

    def _persist_skip_status_once(self) -> None:
        if self._skip_status_written:
            return
        self._save_skip_status()

    def _save_status(self, duration: int) -> None:
        """Erstellt und speichert BackupStatus-JSON-Datei."""
        from lib.status import BackupStatus

        exit_code = self._borg_exit
        if exit_code == 0:
            status_str = "success"
        elif exit_code == 1:
            status_str = "warning"
        else:
            status_str = "error"

        stats = self._borg_stats
        repo_size = self._get_repository_size()
        repo_check_date, repo_check_status, repo_next_check = self._get_repo_check_info()
        error_msg = self._extract_error_message(exit_code)

        transfer_speed = 0
        if stats and stats.deduplicated_size > 0 and duration > 0:
            transfer_speed = stats.deduplicated_size // duration

        bs = BackupStatus(
            backup_type=self.config.backup_type,
            location=self.config.backup_location,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            duration_seconds=duration,
            exit_code=exit_code,
            status=status_str,
            error_message=error_msg,
            log_file=str(self.config.log_file),
            archive_name=stats.archive_name if stats else "",
            original_size=stats.original_size if stats else 0,
            compressed_size=stats.compressed_size if stats else 0,
            deduplicated_size=stats.deduplicated_size if stats else 0,
            files_count=stats.files if stats else 0,
            repository_size=repo_size,
            transfer_speed_bytes_per_sec=transfer_speed,
            repository_check_date=repo_check_date,
            repository_check_status=repo_check_status,
            repository_next_check=repo_next_check,
        )

        try:
            bs.save(self.config.status_dir)
        except OSError as exc:
            logger.warning("Could not save status: %s", exc)

    def _get_repository_size(self) -> int:
        """
        Ermittelt Repository-Größe via 'borg info --json'.

        Gibt cache.stats.unique_size zurück (deduplizierte Gesamtgröße).
        Fallback: 0 (bei fehlendem BORG_REPO oder Fehler).
        """
        if not self.config.borg_repo:
            return 0
        try:
            result = subprocess.run(
                ["borg", "info", "--json", self.config.borg_repo],
                capture_output=True,
                text=True,
                timeout=30,
                env=os.environ.copy(),
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                return int(
                    data.get("cache", {}).get("stats", {}).get("unique_size", 0) or 0
                )
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, ValueError):
            pass
        return 0

    def _get_repo_check_info(self) -> tuple:
        """Liest Repository-Check-Informationen aus dem Flag-File."""
        flag = self.config.borg_check_flag_file
        if flag is None or not flag.is_file():
            return "unknown", "unknown", "unknown"
        try:
            last_ts = flag.stat().st_mtime
            last_date = datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M:%S")
            interval_sec = self.config.borg_check_interval_days * 86400
            next_ts = last_ts + interval_sec
            next_date = datetime.fromtimestamp(next_ts).strftime("%Y-%m-%d")
            check_status = "overdue" if time.time() > next_ts else "ok"
            return last_date, check_status, next_date
        except OSError:
            return "unknown", "unknown", "unknown"

    def _extract_error_message(self, exit_code: int) -> str:
        """Extrahiert Fehlermeldung aus Log-Datei (max. 500 Zeichen)."""
        if exit_code == 0:
            return ""

        if self.config.log_file.is_file():
            try:
                lines = self.config.log_file.read_text(encoding="utf-8").splitlines()
                pattern = re.compile(
                    r"(error|failed|warning|timeout|permission denied|lock|repository.*not found)",
                    re.IGNORECASE,
                )
                matches = [
                    re.sub(r"^\[.*?\]\s*", "", line)
                    for line in lines[-200:]
                    if pattern.search(line)
                ][:3]
                if matches:
                    return " ".join(matches)[:500]
            except OSError:
                pass

        fallback = {
            1: "Backup completed with warnings (check log for details)",
            2: "Backup failed with errors (check log for details)",
        }
        return fallback.get(exit_code, f"Backup failed with exit code {exit_code}")

    def _write_mini_log(self, suffix: str, lines: List[str]) -> None:
        """Schreibt einen kleinen Informations-Log für Skip-Szenarien."""
        try:
            self.config.log_dir.mkdir(parents=True, exist_ok=True)
            mini_log = (
                self.config.log_dir
                / f"Borg-Backup_{self.config.backup_type}--{self.config.date_tag}_{suffix}.log"
            )
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            content = "\n".join(f"[{ts}] {line}" for line in lines) + "\n"
            mini_log.write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write mini log: %s", exc)


# ---------------------------------------------------------------------------
# CLI (Smoke-Test / Diagnose)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="backup_job.py – Diagnose und Smoke-Test"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("info", help="Zeigt aktuelle Konfiguration aus Env-Vars")
    subparsers.add_parser(
        "check-parity", help="Prüft Parity-Status (exit 0 wenn aktiv)"
    )
    check_usb = subparsers.add_parser(
        "check-usb", help="Prüft USB-Mount (exit 0 wenn nicht verfügbar)"
    )
    check_usb.add_argument("mount_path", help="Pfad zum USB-Mount")

    args = parser.parse_args()

    cfg = BackupJobConfig.from_config(os.environ)

    if args.command == "info":
        print(f"job_name:            {cfg.job_name}")
        print(f"backup_type:         {cfg.backup_type}")
        print(f"backup_location:     {cfg.backup_location}")
        print(f"lock_file:           {cfg.lock_file}")
        print(f"log_dir:             {cfg.log_dir}")
        print(f"log_file:            {cfg.log_file}")
        print(f"backup_paths:        {[str(p) for p in cfg.backup_paths]}")
        print(f"borg_cache_dir:      {cfg.borg_cache_dir}")
        print(f"log_retention_days:  {cfg.log_retention_days}")
        print(f"status_dir:          {cfg.status_dir}")
        print(f"borg_repo:           {cfg.borg_repo or '(from BORG_REPO environment variable)'}")
        print(f"check_flag_file:     {cfg.borg_check_flag_file}")
        print(f"check_interval_days: {cfg.borg_check_interval_days}")
    elif args.command == "check-parity":
        job = BackupJob(cfg)
        job.check_parity()
        print("No active parity operation found.")
    elif args.command == "check-usb":
        job = BackupJob(cfg)
        job.check_usb_mount(Path(args.mount_path))
        print(f"USB-Mount OK: {args.mount_path}")
    else:
        parser.print_help()
