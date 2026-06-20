"""
lib/vm_manager.py - Libvirt/KVM VM-Verwaltung für Borg Backup
Version: 1.0.0

Ersetzt die VM-spezifischen Hilfsfunktionen aus borg_backup_VMs.sh:
- virsh_available()          → virsh_available()
- qemu_agent_available()     → qemu_agent_available()
- get_vm_os_type()           → VmManager.get_vm_os_type()
- get_logged_in_users()      → VmManager.get_logged_in_users()
- send_vm_message()          → VmManager.send_message()
- vms_shutdown_all()         → VmManager.shutdown_all()
- vms_start_all()            → VmManager.start_all()

Verbesserungen gegenüber Bash:
- Parallele VM-Warnungen via concurrent.futures (kein Subshell-Spawning)
- Explizite VmShutdownResult statt globaler Variablen
- Saubere Timeout-Behandlung ohne sleep-Loops mit Bash-Arithmetik
- JSON via json.loads statt grep -oP

Nur Python Standard-Library: concurrent.futures, dataclasses, json,
                              logging, shutil, subprocess, time, typing
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

@dataclass
class VmConfig:
    """
    Konfiguration für VM-Verwaltung.

    Werte kommen aus backup.conf via Umgebungsvariablen.
    """

    warning_minutes: int = 5
    shutdown_timeout: int = 300
    startup_wait: int = 60

    @classmethod
    def from_config(cls, env: Dict[str, str]) -> "VmConfig":
        """Liest Konfiguration aus Umgebungsvariablen."""

        def _int(key: str, default: int) -> int:
            raw = env.get(key, "")
            try:
                return int(raw) if raw else default
            except ValueError:
                logger.warning("Invalid value for %s ('%s'); using %d", key, raw, default)
                return default

        return cls(
            warning_minutes=_int("VM_SHUTDOWN_WARNING_MINUTES", 5),
            shutdown_timeout=_int("VM_SHUTDOWN_TIMEOUT", 300),
            startup_wait=_int("VM_STARTUP_WAIT", 60),
        )


# ---------------------------------------------------------------------------
# Ergebnis-Datenklasse
# ---------------------------------------------------------------------------

@dataclass
class VmShutdownResult:
    """Ergebnis eines shutdown_all()-Aufrufs."""

    stopped_vms: List[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.stopped_vms)


# ---------------------------------------------------------------------------
# Standalone-Funktionen (analog zu docker_available in docker_manager.py)
# ---------------------------------------------------------------------------

def virsh_available() -> bool:
    """Prüft ob virsh installiert ist."""
    return shutil.which("virsh") is not None


def qemu_agent_available(vm_name: str) -> bool:
    """
    Prüft ob QEMU Guest Agent in der VM verfügbar ist.

    Nutzt guest-ping um Verfügbarkeit zu testen.
    """
    try:
        result = subprocess.run(
            ["virsh", "qemu-agent-command", vm_name,
             '{"execute":"guest-ping"}'],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Haupt-Klasse
# ---------------------------------------------------------------------------

class VmManager:
    """
    Verwaltet KVM/libvirt VMs für Borg Backup.

    Typischer Workflow im borg_backup_VMs.py Skript:
        vm_manager = VmManager(VmConfig.from_config(env))
        result = vm_manager.shutdown_all()    # Warnung + Countdown + Shutdown
        # ... borg create / maintenance ...
        vm_manager.start_all(result)          # VMs neu starten
    """

    def __init__(self, config: Optional[VmConfig] = None) -> None:
        self.config = config or VmConfig()

    # ------------------------------------------------------------------
    # Öffentliche Methoden
    # ------------------------------------------------------------------

    def shutdown_all(self) -> VmShutdownResult:
        """
        Fährt alle laufenden VMs herunter (mit Vorwarnung).

        Phase 1: Alle VMs parallel warnen (threading)
        Phase 2: Zentraler Countdown (warning_minutes)
        Phase 3: virsh shutdown, warten bis alle gestoppt (shutdown_timeout)

        Returns:
            VmShutdownResult mit Liste der gestoppten VMs.

        Raises:
            SystemExit(1): Wenn VMs nach Timeout noch laufen.
        """
        if not virsh_available():
            logger.info("virsh is unavailable; skipping VM shutdown")
            return VmShutdownResult()

        running = self._get_running_vms()
        if not running:
            logger.info("No running VMs")
            return VmShutdownResult()

        logger.info("Found %d running VM(s)", len(running))
        for vm in running:
            vm_id = self._get_vm_id(vm)
            logger.info("  - %-30s (ID: %s)", vm, vm_id)

        # Phase 1: Alle VMs parallel warnen
        warning_msg = (
            f"WARNUNG: Backup der VM wird durchgefuehrt "
            f"VM wird in {self.config.warning_minutes} Minuten heruntergefahren!"
        )
        logger.info(
            "Sending warning to all %d VM(s) (wait time: %d minutes)",
            len(running), self.config.warning_minutes,
        )
        self._warn_vms_parallel(running, warning_msg)

        # Phase 2: Zentraler Countdown
        for remaining in range(self.config.warning_minutes, 0, -1):
            if remaining == 1:
                logger.info("Final minute before shutdown; sending final warning to all VMs...")
                self._warn_vms_parallel(running, "ACHTUNG: System faehrt JETZT herunter!")
            else:
                logger.info("Waiting %d more minute(s) before VM shutdown...", remaining)
            time.sleep(60)

        # Phase 3: Graceful Shutdown
        logger.info("Shutting down %d VM(s) gracefully...", len(running))
        for vm in running:
            logger.info("  Shutdown: %s", vm)
            try:
                subprocess.run(
                    ["virsh", "shutdown", vm],
                    capture_output=True, timeout=30,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                logger.warning("virsh shutdown %s failed: %s", vm, exc)

        # Warten bis alle gestoppt
        if not self._wait_for_shutdown(timeout=self.config.shutdown_timeout):
            still_running = self._get_running_vms()
            logger.error(
                "ERROR: %d VM(s) could not be shut down: %s",
                len(still_running), still_running,
            )
            from lib.notifications import notify
            notify(
                level="alert",
                subject="VM Backup abgebrochen",
                description=f"{len(still_running)} VM(s) konnten nicht heruntergefahren werden.",
                job_name="Borg Backup (VMs)",
            )
            raise SystemExit(1)

        logger.info("All VMs shut down successfully")
        return VmShutdownResult(stopped_vms=list(running))

    def start_all(self, result: VmShutdownResult) -> None:
        """
        Startet alle zuvor gestoppten VMs neu.

        Fehlertolerant – einzelne Startfehler brechen den Prozess nicht ab.
        Validiert nach startup_wait ob alle VMs laufen.
        """
        if not virsh_available() or not result.stopped_vms:
            return

        logger.info("Restarting %d VM(s)...", result.count)
        for vm in result.stopped_vms:
            logger.info("  Starting: %s", vm)
            try:
                subprocess.run(
                    ["virsh", "start", vm],
                    capture_output=True, timeout=30,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                logger.warning("  WARNING: Could not start %s: %s", vm, exc)

        time.sleep(self.config.startup_wait)

        running_after = self._get_running_vms()
        running_count = len(running_after)
        if running_count == result.count:
            logger.info(
                "All VMs restarted successfully (%d/%d)",
                running_count, result.count,
            )
        else:
            failed = result.count - running_count
            logger.warning(
                "WARNING: %d VM(s) could not be started (%d/%d running)",
                failed, running_count, result.count,
            )
            not_started = [
                vm for vm in result.stopped_vms if vm not in running_after
            ]
            for vm in not_started:
                logger.warning("  - %s", vm)

    def get_vm_os_type(self, vm_name: str) -> str:
        """
        Ermittelt das Betriebssystem einer VM via QEMU Guest Agent.

        Returns:
            "linux", "windows" oder "unknown"
        """
        if not qemu_agent_available(vm_name):
            return "unknown"

        try:
            result = subprocess.run(
                ["virsh", "qemu-agent-command", vm_name,
                 '{"execute":"guest-get-osinfo"}'],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0 or not result.stdout:
                return "unknown"
            os_info = result.stdout.lower()
        except (subprocess.TimeoutExpired, OSError):
            return "unknown"

        if any(k in os_info for k in ("windows", "microsoft windows")):
            return "windows"
        if any(k in os_info for k in ("linux", "ubuntu", "debian", "fedora",
                                       "centos", "rhel", "arch")):
            return "linux"
        return "unknown"

    def get_logged_in_users(self, vm_name: str) -> List[str]:
        """
        Ermittelt angemeldete Benutzer in einer Linux-VM via QEMU Guest Agent.

        Nutzt 'who' Befehl im Gast und parst den base64-kodierten Output.

        Returns:
            Liste von Benutzernamen, oder leer bei Fehler/keine Benutzer.
        """
        if not qemu_agent_available(vm_name):
            return []

        try:
            exec_result = subprocess.run(
                ["virsh", "qemu-agent-command", vm_name,
                 '{"execute":"guest-exec","arguments":{"path":"who","capture-output":true}}'],
                capture_output=True, text=True, timeout=15,
            )
            if exec_result.returncode != 0 or not exec_result.stdout:
                return []

            pid = self._extract_pid(exec_result.stdout)
            if pid is None:
                return []

            time.sleep(1)

            status_result = subprocess.run(
                ["virsh", "qemu-agent-command", vm_name,
                 f'{{"execute":"guest-exec-status","arguments":{{"pid":{pid}}}}}'],
                capture_output=True, text=True, timeout=15,
            )
            if status_result.returncode != 0 or not status_result.stdout:
                return []

            return self._parse_who_output(status_result.stdout)

        except (subprocess.TimeoutExpired, OSError):
            return []

    def send_message(self, vm_name: str, message: str) -> None:
        """
        Sendet eine Nachricht an eine VM (OS-abhängig).

        Linux: notify-send für jeden angemeldeten Benutzer + wall als Fallback.
        Windows: msg.exe /TIME:300 an alle Sitzungen.
        Unbekannt: beide Methoden versucht (best-effort).
        """
        if not qemu_agent_available(vm_name):
            return

        os_type = self.get_vm_os_type(vm_name)
        logger.info("  ┌─ VM: %s (%s)", vm_name, os_type)

        try:
            if os_type == "linux":
                self._send_linux_message(vm_name, message)
            elif os_type == "windows":
                self._send_windows_message(vm_name, message)
            else:
                # Best-effort: beide Methoden versuchen
                logger.info("  |  Unknown operating system; trying all methods")
                self._send_wall_message(vm_name, message)
                self._send_windows_message(vm_name, message)
        except (subprocess.TimeoutExpired, OSError, ValueError, RuntimeError) as exc:
            logger.debug("send_message %s failed: %s", vm_name, exc)
        finally:
            logger.info("  +- Message sent")

    # ------------------------------------------------------------------
    # Interne Methoden
    # ------------------------------------------------------------------

    def _get_running_vms(self) -> List[str]:
        """Gibt Namen aller laufenden VMs zurück."""
        try:
            result = subprocess.run(
                ["virsh", "list", "--state-running", "--name"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return []
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except (subprocess.TimeoutExpired, OSError):
            return []

    def _get_vm_id(self, vm_name: str) -> str:
        """Gibt die Domain-ID einer VM zurück."""
        try:
            result = subprocess.run(
                ["virsh", "domid", vm_name],
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except (subprocess.TimeoutExpired, OSError):
            return "unknown"

    def _wait_for_shutdown(self, timeout: int) -> bool:
        """
        Wartet bis alle VMs gestoppt sind.

        Returns:
            True wenn alle VMs gestoppt, False bei Timeout.
        """
        elapsed = 0
        check_interval = 10
        while elapsed < timeout:
            still_running = len(self._get_running_vms())
            if still_running == 0:
                return True
            time.sleep(check_interval)
            elapsed += check_interval
            if elapsed % 30 == 0:
                logger.info(
                    "  Noch %d VM(s) laufen (%ds vergangen)...",
                    still_running, elapsed,
                )
        return len(self._get_running_vms()) == 0

    def _warn_vms_parallel(self, vm_names: List[str], message: str) -> None:
        """Sendet Warnungen an alle VMs parallel (ThreadPoolExecutor)."""
        with ThreadPoolExecutor(max_workers=min(len(vm_names), 8)) as executor:
            futures = {
                executor.submit(self._warn_single_vm, vm, message): vm
                for vm in vm_names
            }
            for future in as_completed(futures):
                vm = futures[future]
                try:
                    future.result()
                except (subprocess.TimeoutExpired, OSError, ValueError, RuntimeError) as exc:
                    logger.debug("Warning to VM %s failed: %s", vm, exc)

    def _warn_single_vm(self, vm_name: str, message: str) -> None:
        """Sendet Warnung an eine einzelne VM."""
        from lib.notifications import notify
        notify(
            level="warning",
            subject="VM Backup Warnung",
            description=f"VM '{vm_name}' wird in {self.config.warning_minutes} Min für Backup heruntergefahren",
            job_name="Borg Backup (VMs)",
        )
        if qemu_agent_available(vm_name):
            logger.info("  - VM: %s - QEMU Guest Agent available; sending message...", vm_name)
            self.send_message(vm_name, message)
        else:
            logger.info("  - VM: %s - QEMU Guest Agent unavailable", vm_name)

    def _send_linux_message(self, vm_name: str, message: str) -> None:
        """Sendet Desktop-Notification + wall an alle Linux-Benutzer."""
        users = self.get_logged_in_users(vm_name)
        if users:
            logger.info("  |  Found users: %s", ", ".join(users))
            for user in users:
                logger.info("  |  Processing user: %s", user)
                uid = self._get_user_uid(vm_name, user)
                if uid:
                    logger.info("  |    Resolved UID: %s", uid)
                    self._send_notify_send(vm_name, user, uid, message)
                else:
                    logger.info("  |    Could not resolve UID")
        else:
            logger.info("  |  No signed-in users found")

        # wall als Fallback (an alle Terminals)
        logger.info("  |  Also sending a wall message...")
        self._send_wall_message(vm_name, message)

    def _send_notify_send(self, vm_name: str, user: str, uid: str, message: str) -> None:
        """Sendet notify-send Desktop-Benachrichtigung in Linux-VM."""
        user_s = str(user or "").strip()
        uid_s = str(uid or "").strip()
        if not re.fullmatch(r"^[a-zA-Z0-9_.-]+$", user_s):
            logger.warning("  |    Skipping notify-send: invalid username '%s'", user_s)
            return
        if not re.fullmatch(r"^\d+$", uid_s):
            logger.warning("  |    Skipping notify-send: invalid UID '%s'", uid_s)
            return
        safe_msg = str(message or "").strip()[:512]
        payload = json.dumps({
            "execute": "guest-exec",
            "arguments": {
                "path": "/usr/sbin/runuser",
                "arg": [
                    "-u", user_s,
                    "--",
                    "/usr/bin/env",
                    "DISPLAY=:0",
                    f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid_s}/bus",
                    "/usr/bin/notify-send",
                    "--urgency=critical",
                    "-t", "120000",
                    "Backup-Wartung",
                    safe_msg,
                ],
                "capture-output": True,
            },
        })
        status = self._guest_exec_and_wait(vm_name, payload)
        if status.get("ok"):
            logger.info("  |    Notification sent")
            return
        detail = str(status.get("detail") or "unbekannte Ursache").strip()
        logger.info("  |    Note: desktop notification could not be confirmed (%s)", detail)

    def _send_wall_message(self, vm_name: str, message: str) -> None:
        """Sendet wall-Nachricht in Linux-VM."""
        safe_msg = str(message or "").strip()[:1024]
        payload = json.dumps({
            "execute": "guest-exec",
            "arguments": {
                "path": "/usr/bin/wall",
                "arg": [safe_msg],
                "capture-output": True,
            },
        })
        status = self._guest_exec_and_wait(vm_name, payload)
        if not status.get("ok"):
            detail = str(status.get("detail") or "unbekannte Ursache").strip()
            logger.info("  |    Note: wall message could not be confirmed (%s)", detail)

    def _guest_exec_and_wait(self, vm_name: str, payload: str, *, timeout: int = 15) -> Dict[str, Any]:
        """
        Startet einen QEMU guest-exec und prüft das Ergebnis.

        Benachrichtigungen sind best-effort: Fehler werden als Status
        zurückgegeben und dürfen den Backup-Flow nicht abbrechen.
        """
        try:
            exec_result = subprocess.run(
                ["virsh", "qemu-agent-command", vm_name, payload],
                capture_output=True, text=True, timeout=timeout,
            )
            if exec_result.returncode != 0:
                return {
                    "ok": False,
                    "detail": self._compact_guest_error(exec_result.stderr or exec_result.stdout),
                }
            pid = self._extract_pid(exec_result.stdout)
            if pid is None:
                return {"ok": False, "detail": "keine guest-exec PID erhalten"}

            deadline = time.time() + max(1, timeout)
            last_status: Dict[str, Any] = {}
            while time.time() < deadline:
                status_result = subprocess.run(
                    ["virsh", "qemu-agent-command", vm_name,
                     f'{{"execute":"guest-exec-status","arguments":{{"pid":{pid}}}}}'],
                    capture_output=True, text=True, timeout=timeout,
                )
                if status_result.returncode != 0:
                    return {
                        "ok": False,
                        "detail": self._compact_guest_error(status_result.stderr or status_result.stdout),
                    }
                last_status = self._parse_guest_exec_status(status_result.stdout)
                if last_status.get("exited"):
                    code = int(last_status.get("exitcode") or 0)
                    if code == 0:
                        return {"ok": True, "detail": ""}
                    detail = last_status.get("err") or last_status.get("out") or f"exit={code}"
                    return {"ok": False, "detail": self._compact_guest_error(str(detail))}
                time.sleep(0.2)

            if last_status:
                return {"ok": False, "detail": "guest-exec-status Timeout ohne Prozessende"}
            return {"ok": False, "detail": "guest-exec-status Timeout"}
        except (subprocess.TimeoutExpired, OSError):
            return {"ok": False, "detail": "guest-exec konnte nicht geprüft werden"}

    def _send_windows_message(self, vm_name: str, message: str) -> None:
        """Sendet msg.exe-Nachricht in Windows-VM."""
        logger.info("  |  Sending Windows message...")
        payload = json.dumps({
            "execute": "guest-exec",
            "arguments": {
                "path": "C:\\Windows\\System32\\msg.exe",
                "arg": ["*", "/TIME:300", message],
            },
        })
        try:
            subprocess.run(
                ["virsh", "qemu-agent-command", vm_name, payload],
                capture_output=True, timeout=15,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

    def _get_user_uid(self, vm_name: str, user: str) -> Optional[str]:
        """Ermittelt die UID eines Benutzers in einer Linux-VM."""
        try:
            exec_result = subprocess.run(
                ["virsh", "qemu-agent-command", vm_name,
                 json.dumps({
                     "execute": "guest-exec",
                     "arguments": {
                         "path": "id",
                         "arg": ["-u", user],
                         "capture-output": True,
                     },
                 })],
                capture_output=True, text=True, timeout=15,
            )
            if exec_result.returncode != 0:
                return None

            pid = self._extract_pid(exec_result.stdout)
            if pid is None:
                return None

            time.sleep(0.5)

            status_result = subprocess.run(
                ["virsh", "qemu-agent-command", vm_name,
                 f'{{"execute":"guest-exec-status","arguments":{{"pid":{pid}}}}}'],
                capture_output=True, text=True, timeout=15,
            )
            if status_result.returncode != 0:
                return None

            return self._decode_out_data(status_result.stdout)

        except (subprocess.TimeoutExpired, OSError):
            return None

    @staticmethod
    def _extract_pid(json_str: str) -> Optional[int]:
        """Extrahiert PID aus virsh qemu-agent-command guest-exec Antwort."""
        try:
            data = json.loads(json_str)
            pid = data.get("return", {}).get("pid")
            return int(pid) if pid is not None else None
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    @staticmethod
    def _decode_out_data(json_str: str) -> Optional[str]:
        """Dekodiert base64-kodierten out-data aus guest-exec-status Antwort."""
        try:
            data = json.loads(json_str)
            out_data = data.get("return", {}).get("out-data", "")
            if out_data:
                return base64.b64decode(out_data).decode("utf-8", errors="replace").strip()
        except (json.JSONDecodeError, binascii.Error, UnicodeDecodeError, ValueError, TypeError):
            pass
        return None

    @staticmethod
    def _parse_guest_exec_status(json_str: str) -> Dict[str, Any]:
        """Parst guest-exec-status mit dekodiertem stdout/stderr."""
        try:
            data = json.loads(json_str)
            ret = data.get("return", {})
            out_data = ret.get("out-data", "")
            err_data = ret.get("err-data", "")
            return {
                "exited": bool(ret.get("exited")),
                "exitcode": ret.get("exitcode", 0),
                "out": base64.b64decode(out_data).decode("utf-8", errors="replace").strip() if out_data else "",
                "err": base64.b64decode(err_data).decode("utf-8", errors="replace").strip() if err_data else "",
            }
        except (json.JSONDecodeError, binascii.Error, UnicodeDecodeError, ValueError, TypeError):
            return {"exited": False, "exitcode": 0, "out": "", "err": "guest-exec-status konnte nicht gelesen werden"}

    @staticmethod
    def _compact_guest_error(text: str) -> str:
        """Kürzt Diagnoseausgaben für normale INFO-Logs."""
        compact = " ".join(str(text or "").strip().split())
        return compact[:240] if compact else "keine Details"

    @staticmethod
    def _parse_who_output(json_str: str) -> List[str]:
        """Parst Benutzernamen aus dem base64-kodierten who-Output."""
        decoded = VmManager._decode_out_data(json_str)
        if not decoded:
            return []
        # 'who' gibt Zeilen wie "user pts/0 2026-05-01 10:00" aus
        users = list({line.split()[0] for line in decoded.splitlines() if line.strip()})
        return sorted(users)


# ---------------------------------------------------------------------------
# CLI (Diagnose)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging
    import os
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="vm_manager.py – Diagnose")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Zeigt laufende VMs")
    shutdown_p = subparsers.add_parser("shutdown", help="Fährt alle VMs herunter")
    subparsers.add_parser("start", help="Startet alle zuvor gestoppten VMs")

    args = parser.parse_args()

    cfg = VmConfig.from_config(dict(os.environ))
    manager = VmManager(cfg)

    if args.command == "status":
        running = manager._get_running_vms()
        if running:
            print(f"{len(running)} VM(s) laufen:")
            for vm in running:
                print(f"  - {vm}")
        else:
            print("No running VMs")
    elif args.command == "shutdown":
        result = manager.shutdown_all()
        print(f"Gestoppt: {result.stopped_vms}")
    elif args.command == "start":
        print("start requires a VmShutdownResult and is only available in backup context")
    else:
        parser.print_help()
