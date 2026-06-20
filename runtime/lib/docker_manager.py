"""
lib/docker_manager.py - Docker Container Management
Version: 1.0.0

Ersetzt docker_available(), docker_stop_all(), docker_start_all() aus lib/borg-common.sh.

Verbesserungen gegenüber Bash:
- Kein ERR-Trap-Hacking mehr nötig (Python try/except)
- Container-IDs als typisierte Liste statt Whitespace-String
- Retry-Logik als saubere Schleife ohne Bash-Arrays
- subprocess statt Shell-String-Interpolation

Nur Python Standard-Library: subprocess, logging, time, dataclasses
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Defaults (überschreibbar per DockerConfig)
_DEFAULT_STOP_TIMEOUT = 30    # Sekunden pro Container beim Stop
_DEFAULT_STOP_WAIT = 5        # Sekunden Wartezeit nach docker stop
_DEFAULT_START_WAIT = 10      # Sekunden Wartezeit nach Start jeder Prioritätsgruppe
_DEFAULT_PRIORITY_WAIT = 15   # Sekunden zwischen Prioritätsstufen
_DEFAULT_MAX_RETRIES = 2      # Anzahl Retry-Versuche nach initialem Start-Fehler
_DEFAULT_RETRY_WAIT = 30      # Sekunden Wartezeit zwischen Retries


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

@dataclass
class DockerConfig:
    """
    Konfiguration für Docker-Management.

    Werte kommen aus backup.conf (DOCKER_STOP_TIMEOUT, DOCKER_STOP_WAIT,
    DOCKER_START_WAIT). Defaults entsprechen borg-common.sh.

    Beispiel:
        from lib.status import load_config
        from lib.docker_manager import DockerConfig, DockerManager
        cfg = load_config(Path("config/backup.conf"))
        docker_cfg = DockerConfig.from_config(cfg)
        manager = DockerManager(docker_cfg)
    """

    stop_timeout: int = _DEFAULT_STOP_TIMEOUT
    stop_wait: int = _DEFAULT_STOP_WAIT
    start_wait: int = _DEFAULT_START_WAIT
    priority_wait: int = _DEFAULT_PRIORITY_WAIT
    max_retries: int = _DEFAULT_MAX_RETRIES
    retry_wait: int = _DEFAULT_RETRY_WAIT

    @classmethod
    def from_config(cls, config: Dict[str, str]) -> "DockerConfig":
        """Erstellt DockerConfig aus einem backup.conf Dict."""

        def _int(key: str, default: int) -> int:
            raw = config.get(key, str(default))
            try:
                return int(raw)
            except ValueError:
                logger.warning("Invalid value for %s ('%s'); using %d", key, raw, default)
                return default

        return cls(
            stop_timeout=_int("DOCKER_STOP_TIMEOUT", _DEFAULT_STOP_TIMEOUT),
            stop_wait=_int("DOCKER_STOP_WAIT", _DEFAULT_STOP_WAIT),
            start_wait=_int("DOCKER_START_WAIT", _DEFAULT_START_WAIT),
            priority_wait=_int("DOCKER_PRIORITY_WAIT", _DEFAULT_PRIORITY_WAIT),
            max_retries=_int("DOCKER_MAX_RETRIES", _DEFAULT_MAX_RETRIES),
            retry_wait=_int("DOCKER_RETRY_WAIT", _DEFAULT_RETRY_WAIT),
        )


# ---------------------------------------------------------------------------
# Ergebnis-Datenklasse
# ---------------------------------------------------------------------------

@dataclass
class DockerStopResult:
    """Ergebnis von DockerManager.stop_all()."""
    available: bool = False
    container_ids: List[str] = field(default_factory=list)
    count_before: int = 0
    success: bool = False


@dataclass
class DockerStartResult:
    """Ergebnis von DockerManager.start_all()."""
    count_before: int = 0
    count_after: int = 0
    failed_ids: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.failed_ids) == 0

    @property
    def all_started(self) -> bool:
        return self.count_after >= self.count_before


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def docker_available() -> bool:
    """
    Prüft ob Docker verfügbar und funktionsfähig ist.

    Entspricht docker_available() in borg-common.sh:
        command -v docker && docker info

    Returns:
        True wenn Docker verfügbar, False sonst
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


class DockerManager:
    """
    Verwaltet Docker Container rund um Backup-Operationen.

    Typischer Workflow:
        manager = DockerManager(config)
        stop_result = manager.stop_all(log_file="/mnt/.../backup.log")
        # ... Backup durchführen ...
        start_result = manager.start_all(stop_result)
    """

    def __init__(self, config: Optional[DockerConfig] = None) -> None:
        self.config = config or DockerConfig()

    def stop_all(self, log_file: str = "") -> DockerStopResult:
        """
        Stoppt alle laufenden Docker Container.

        Entspricht docker_stop_all() in borg-common.sh.
        Setzt kein globales RUNNING_CONTAINERS – gibt DockerStopResult zurück,
        das an start_all() übergeben wird.

        Args:
            log_file: Pfad zur Log-Datei (für Fehlermeldungen)

        Returns:
            DockerStopResult mit Container-IDs und Ergebnis.
            Bei Fehler (nicht alle Container gestoppt) wird SystemExit ausgelöst.
        """
        result = DockerStopResult()

        if not docker_available():
            logger.info("Docker is disabled or unavailable; skipping container stop")
            return result

        result.available = True
        container_ids = _get_running_ids()
        if not container_ids:
            logger.info("No running Docker containers")
            result.success = True
            return result

        result.container_ids = container_ids
        result.count_before = len(container_ids)
        logger.info(
            "Stopping %d Docker containers (timeout: %ds)",
            result.count_before,
            self.config.stop_timeout,
        )

        # Container-Liste loggen
        self._log_running_containers(container_ids)

        # Container stoppen
        try:
            subprocess.run(
                ["docker", "stop", "-t", str(self.config.stop_timeout)] + container_ids,
                capture_output=True,
                timeout=self.config.stop_timeout * len(container_ids) + 30,
            )
        except subprocess.TimeoutExpired:
            logger.warning("docker stop timed out")
        except OSError as exc:
            logger.warning("docker stop failed: %s", exc)

        time.sleep(self.config.stop_wait)

        # Prüfen ob alle gestoppt wurden
        still_running = len(_get_running_ids())
        if still_running != 0:
            msg = (
                f"Nicht alle Container konnten gestoppt werden "
                f"({still_running} laufen noch). Siehe Log: {log_file}"
            )
            logger.error("ERROR: %s", msg)
            raise RuntimeError(msg)

        logger.info("All Docker containers stopped successfully")
        result.success = True
        return result

    def start_all(self, stop_result: DockerStopResult) -> DockerStartResult:
        """
        Startet alle zuvor gestoppten Docker Container nach Priorität.

        Entspricht docker_start_all() in borg-common.sh.
        Container werden nach Label backup.start.priority (1/2/3) sortiert.

        Priorität 1 = Kritische Infrastruktur (Datenbanken, Redis, etc.)
        Priorität 2 = Standard-Anwendungen
        Priorität 3 = Rest (default wenn kein Label gesetzt)

        Args:
            stop_result: Ergebnis von stop_all() mit Container-IDs

        Returns:
            DockerStartResult mit Anzahl und fehlgeschlagenen IDs
        """
        result = DockerStartResult(count_before=stop_result.count_before)

        if not stop_result.available or not stop_result.container_ids:
            result.count_after = len(_get_running_ids())
            return result

        logger.info(
            "Starting %d Docker containers by priority...",
            stop_result.count_before,
        )

        # Container nach Priorität aufteilen
        groups: Dict[int, List[str]] = {1: [], 2: [], 3: []}
        for cid in stop_result.container_ids:
            priority = _get_container_priority(cid)
            groups[priority].append(cid)

        # Prioritätsgruppen starten
        all_failed: List[str] = []

        if groups[1]:
            logger.info("=== Phase 1: Critical infrastructure (databases, cache) ===")
            failed = self._start_group(groups[1], "Priority 1 - infrastructure")
            all_failed.extend(failed)
            if groups[2] or groups[3]:
                time.sleep(self.config.priority_wait)

        if groups[2]:
            logger.info("=== Phase 2: Standard applications ===")
            failed = self._start_group(groups[2], "Priority 2 - standard")
            all_failed.extend(failed)
            if groups[3]:
                time.sleep(self.config.priority_wait)

        if groups[3]:
            logger.info("=== Phase 3: Other containers ===")
            failed = self._start_group(groups[3], "Priority 3 - other")
            all_failed.extend(failed)

        # Retry-Loop für fehlgeschlagene Container
        retry_count = 1
        while all_failed and retry_count <= self.config.max_retries:
            logger.info(
                "RETRY %d/%d: attempting to restart %d containers...",
                retry_count, self.config.max_retries, len(all_failed),
            )
            new_failed = []
            for cid in all_failed:
                name = _get_container_name(cid)
                logger.info("  - Starting %s (%s)", name, cid)
                _docker_start(cid)

            time.sleep(self.config.retry_wait)

            for cid in all_failed:
                if not _is_running(cid):
                    new_failed.append(cid)
                else:
                    name = _get_container_name(cid)
                    logger.info("  OK %s started successfully", name)

            all_failed = new_failed
            retry_count += 1

        # Finale Validierung
        result.count_after = len(_get_running_ids())
        result.failed_ids = all_failed

        if result.all_started:
            logger.info(
                "OK All Docker containers started successfully (%d/%d)",
                result.count_after, result.count_before,
            )
        else:
            logger.warning(
                "WARNING: %d containers could not be started after %d retries:",
                len(all_failed), self.config.max_retries,
            )
            for cid in all_failed:
                name = _get_container_name(cid)
                logger.warning("  ✗ %s (%s)", name, cid)

        return result

    # -----------------------------------------------------------------------
    # Interne Hilfsmethoden
    # -----------------------------------------------------------------------

    def _start_group(self, container_ids: List[str], group_name: str) -> List[str]:
        """Startet eine Prioritätsgruppe und gibt fehlgeschlagene IDs zurück."""
        logger.info("Starting %d containers (%s)...", len(container_ids), group_name)

        for cid in container_ids:
            name = _get_container_name(cid)
            logger.info("  - Starting %s (%s)", name, cid)
            _docker_start(cid)

        time.sleep(self.config.start_wait)

        failed = [cid for cid in container_ids if not _is_running(cid)]
        return failed

    @staticmethod
    def _log_running_containers(container_ids: List[str]) -> None:
        """Gibt formatierte Container-Liste aus (Name + ID)."""
        logger.info("Container list:")
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}|{{.ID}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = sorted(result.stdout.strip().splitlines())
            for line in lines:
                parts = line.split("|", 1)
                name = parts[0] if parts else line
                cid = parts[1] if len(parts) > 1 else ""
                logger.info("  - %-30s (%s)", name, cid)
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Container list could not be retrieved: %s", exc)


# ---------------------------------------------------------------------------
# Modul-interne Hilfsfunktionen
# ---------------------------------------------------------------------------

def _get_running_ids() -> List[str]:
    """Gibt IDs aller laufenden Container zurück."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-q"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return [line for line in result.stdout.strip().splitlines() if line]
    except (subprocess.TimeoutExpired, OSError):
        return []


def _is_running(container_id: str) -> bool:
    """Prüft ob ein Container läuft."""
    running = _get_running_ids()
    return any(cid.startswith(container_id) or container_id.startswith(cid) for cid in running)


def _get_container_name(container_id: str) -> str:
    """Gibt den Namen eines Containers zurück (ohne führendes '/')."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format={{.Name}}", container_id],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip().lstrip("/") or "unknown"
    except (subprocess.TimeoutExpired, OSError):
        return "unknown"


def _get_container_priority(container_id: str) -> int:
    """
    Liest das Label backup.start.priority eines Containers.
    Gibt 1, 2 oder 3 zurück (default = 3 wenn Label fehlt/ungültig).
    """
    try:
        result = subprocess.run(
            ["docker", "inspect",
             '--format={{index .Config.Labels "backup.start.priority"}}',
             container_id],
            capture_output=True,
            text=True,
            timeout=10,
        )
        raw = result.stdout.strip()
        if raw in ("", "<no value>"):
            return 3
        priority = int(raw)
        return priority if priority in (1, 2, 3) else 3
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return 3


def _docker_start(container_id: str) -> None:
    """Startet einen Container (best-effort, Fehler werden geloggt)."""
    try:
        subprocess.run(
            ["docker", "start", container_id],
            capture_output=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("docker start %s failed: %s", container_id, exc)


# ---------------------------------------------------------------------------
# CLI-Einstiegspunkt  (python3 lib/docker_manager.py status|stop|start)
# ---------------------------------------------------------------------------

def _cli_status() -> None:
    """Zeigt alle laufenden Container mit Priorität an."""
    if not docker_available():
        print("Docker is unavailable.")
        return
    ids = _get_running_ids()
    if not ids:
        print("No running containers.")
        return
    print(f"{len(ids)} laufende Container:")
    for cid in ids:
        name = _get_container_name(cid)
        prio = _get_container_priority(cid)
        print(f"  [Prio {prio}] {name:<35} {cid[:12]}")


def _cli_stop(state_file: Path) -> int:
    """Stoppt alle Container und speichert IDs in state_file."""
    manager = DockerManager()
    try:
        result = manager.stop_all()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1

    if not result.available:
        print("Docker unavailable; nothing was stopped.")
        return 0
    if not result.container_ids:
        print("No running containers; nothing to do.")
        return 0

    state_file.write_text("\n".join(result.container_ids), encoding="utf-8")
    print(f"{result.count_before} containers stopped. State saved: {state_file}")
    return 0


def _cli_start(state_file: Path) -> int:
    """Startet Container aus state_file wieder."""
    if not state_file.exists():
        print(f"No saved containers found ({state_file}).")
        print("Hint: run 'stop' first.")
        return 1

    ids = [line for line in state_file.read_text(encoding="utf-8").splitlines() if line]
    if not ids:
        print("No container IDs in the state file.")
        return 1

    stop_result = DockerStopResult(
        available=True,
        container_ids=ids,
        count_before=len(ids),
        success=True,
    )
    manager = DockerManager()
    start_result = manager.start_all(stop_result)

    if start_result.all_started:
        print(f"All {start_result.count_after} containers started.")
        state_file.unlink(missing_ok=True)
        return 0
    else:
        print(
            f"Warning: {len(start_result.failed_ids)} containers could not be started: "
            + ", ".join(start_result.failed_ids)
        )
        return 1


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%F %T",
    )

    _STATE_FILE = Path("/tmp/docker_manager_state.txt")

    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        _cli_status()
        sys.exit(0)
    elif cmd == "stop":
        sys.exit(_cli_stop(_STATE_FILE))
    elif cmd == "start":
        sys.exit(_cli_start(_STATE_FILE))
    else:
        print(f"Unbekannter Befehl: {cmd!r}")
        print("Usage: python3 lib/docker_manager.py status|stop|start")
        sys.exit(1)
