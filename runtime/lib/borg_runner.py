"""
lib/borg_runner.py - Borg Backup Runner (Prune, Compact, Check, Stats)
Version: 1.0.0

Ersetzt borg_prune(), borg_compact(), borg_check(), parse_borg_stats(),
convert_to_bytes() aus lib/borg-common.sh.

Verbesserungen gegenüber Bash:
- Kein PIPESTATUS-Hacking mehr (set +e / set -e Muster entfällt)
- parse_borg_stats() nutzt re statt grep -oP / sed
- convert_to_bytes() nutzt Python-Float statt bc (kein externes Tool)
- Zeitgestempelte Ausgabe ohne Shell-Pipeline (add_timestamp entfällt)
- Repository-Pfad explizit oder über BORG_REPO-Umgebungsvariable

Nur Python Standard-Library: subprocess, logging, re, os, time, dataclasses, pathlib
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_HR = "━" * 80


def _log_section(title: str) -> None:
    logger.info(_HR)
    logger.info("  %s", title)
    logger.info(_HR)


# Borg Exit-Codes (für alle Operationen identisch)
BORG_EXIT_OK = 0       # Alles in Ordnung
BORG_EXIT_WARNING = 1  # Warnungen, Backup trotzdem verwendbar
BORG_EXIT_ERROR = 2    # Fehler, Backup möglicherweise unbrauchbar

# SI-Einheiten (Borg verwendet 1000er-Basis)
# IEC-Einheiten (1024er-Basis) als Fallback
_UNIT_MULTIPLIERS: Dict[str, int] = {
    "B":   1,
    "kB":  1_000,
    "KB":  1_024,            # IEC-Fallback
    "MB":  1_000_000,
    "MiB": 1_048_576,
    "GB":  1_000_000_000,
    "GiB": 1_073_741_824,
    "TB":  1_000_000_000_000,
    "TiB": 1_099_511_627_776,
}


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

@dataclass
class BorgConfig:
    """
    Konfiguration für Borg-Operationen.

    Werte kommen aus backup.conf. Defaults entsprechen borg-common.sh.

    Beispiel:
        from lib.status import load_config
        from lib.borg_runner import BorgConfig, BorgRunner
        cfg = load_config(Path("config/backup.conf"))
        borg_cfg = BorgConfig.from_config(cfg)
        runner = BorgRunner(borg_cfg)
    """

    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 6
    keep_yearly: int = 2
    check_interval_days: int = 7
    check_flag_file: Path = Path("/tmp/borg_last_check")
    repo: str = ""  # leer = BORG_REPO Umgebungsvariable
    compression: str = "lz4"
    checkpoint_interval: int = 1800
    # 0 = kein Hard-Limit (bewusstes Default).
    # Grund: Initial-Backups (z. B. 1.5TB via 5MB/s) können mehrere Tage laufen.
    max_runtime_hours: int = 0

    @classmethod
    def from_config(cls, config: Dict[str, str]) -> "BorgConfig":
        """Erstellt BorgConfig aus einem backup.conf Dict."""

        def _int(key: str, default: int) -> int:
            raw = config.get(key, str(default))
            try:
                return int(raw)
            except ValueError:
                logger.warning("Ungültiger Wert für %s ('%s'), verwende %d", key, raw, default)
                return default

        def _non_negative_int(key: str, default: int) -> int:
            return max(0, _int(key, default))

        flag_raw = config.get("BORG_CHECK_FLAG_FILE", "/tmp/borg_last_check")
        return cls(
            keep_daily=_non_negative_int("BORG_KEEP_DAILY", 7),
            keep_weekly=_non_negative_int("BORG_KEEP_WEEKLY", 4),
            keep_monthly=_non_negative_int("BORG_KEEP_MONTHLY", 6),
            keep_yearly=_non_negative_int("BORG_KEEP_YEARLY", 2),
            check_interval_days=_int("BORG_CHECK_INTERVAL_DAYS", 7),
            check_flag_file=Path(flag_raw),
            repo=config.get("BORG_REPO", ""),
            compression=config.get("BORG_COMPRESSION", "lz4") or "lz4",
            checkpoint_interval=_int("BORG_CHECKPOINT_INTERVAL", 1800),
            max_runtime_hours=_non_negative_int("BORG_MAX_RUNTIME_HOURS", 0),
        )


# ---------------------------------------------------------------------------
# Ergebnis-Datenklasse für geparste Borg-Statistiken
# ---------------------------------------------------------------------------

@dataclass
class BorgStats:
    """
    Geparste Borg-Statistiken aus dem Backup-Log.

    Entspricht den globalen BORG_STATS_*-Variablen in borg-common.sh.
    """

    archive_name: str = "unknown"
    original_size: int = 0
    compressed_size: int = 0
    deduplicated_size: int = 0
    files: int = 0

    def as_dict(self) -> Dict[str, object]:
        return {
            "archive_name": self.archive_name,
            "original_size": self.original_size,
            "compressed_size": self.compressed_size,
            "deduplicated_size": self.deduplicated_size,
            "files": self.files,
        }


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

class BorgRunner:
    """
    Führt Borg-Operationen (prune, compact, check) aus.

    Typischer Workflow in einem Backup-Skript:
        runner = BorgRunner(BorgConfig.from_config(cfg))
        prune_exit = runner.prune()
        compact_exit = runner.compact()
        check_exit = runner.check()
    """

    def __init__(self, config: Optional[BorgConfig] = None) -> None:
        self.config = config or BorgConfig()

    def prune(self) -> int:
        """
        Löscht alte Backups nach der konfigurierten Retention Policy.

        Entspricht borg_prune() in borg-common.sh.
        Exit 0 = OK, 1 = Warnungen (Backup nutzbar), >1 = Fehler.

        Returns:
            Borg Exit-Code (0, 1 oder 2)
        """
        logger.info(
            "Borg prune: Lösche alte Backups "
            "(keep: %dd/%dw/%dm/%dy)",
            self.config.keep_daily,
            self.config.keep_weekly,
            self.config.keep_monthly,
            self.config.keep_yearly,
        )

        cmd = [
            "borg", "prune",
            "--verbose",
            "--list",
            "--show-rc",
            "--keep-daily",   str(self.config.keep_daily),
            "--keep-weekly",  str(self.config.keep_weekly),
            "--keep-monthly", str(self.config.keep_monthly),
            "--keep-yearly",  str(self.config.keep_yearly),
        ]
        if self.config.repo:
            cmd.append(self.config.repo)

        exit_code = _run_borg(cmd)

        if exit_code == BORG_EXIT_OK:
            logger.info("Borg prune erfolgreich")
        elif exit_code == BORG_EXIT_WARNING:
            logger.info("Borg prune mit Warnungen (Exit 1)")
        else:
            logger.warning("WARNUNG: Borg prune fehlgeschlagen (Exit %d)", exit_code)

        return exit_code

    def compact(self) -> int:
        """
        Gibt ungenutzten Speicherplatz im Repository frei.

        Entspricht borg_compact() in borg-common.sh.

        Returns:
            Borg Exit-Code (0 = OK, >0 = Fehler)
        """
        logger.info("Borg compact: Gebe ungenutzten Speicherplatz frei...")

        cmd = ["borg", "compact", "--verbose", "--show-rc"]
        if self.config.repo:
            cmd.append(self.config.repo)

        exit_code = _run_borg(cmd)

        if exit_code == BORG_EXIT_OK:
            logger.info("Borg compact erfolgreich")
        else:
            logger.warning("WARNUNG: Borg compact fehlgeschlagen (Exit %d)", exit_code)

        return exit_code

    def check(self) -> int:
        """
        Prüft Repository-Integrität (zeitgesteuert per Flag-Datei).

        Entspricht borg_check() in borg-common.sh.
        Check wird übersprungen, wenn letzter Check kürzer als
        check_interval_days zurückliegt.

        Returns:
            Borg Exit-Code, oder 0 wenn Check übersprungen wurde
        """
        days_since = _days_since_flag(self.config.check_flag_file)

        if days_since < self.config.check_interval_days:
            logger.info(
                "Borg check übersprungen (letzter Check vor %d Tagen, "
                "Intervall: %d Tage)",
                days_since,
                self.config.check_interval_days,
            )
            return BORG_EXIT_OK

        logger.info(
            "Borg check: Prüfe Repository-Integrität "
            "(letzter Check vor %d Tagen)...",
            days_since,
        )

        cmd = ["borg", "check", "--repository-only", "--show-rc"]
        if self.config.repo:
            cmd.append(self.config.repo)

        exit_code = _run_borg(cmd)

        if exit_code == BORG_EXIT_OK:
            logger.info("Borg check erfolgreich - Repository OK")
            _touch_flag(self.config.check_flag_file)
        else:
            logger.error("FEHLER: Borg check fehlgeschlagen (Exit %d)", exit_code)

        return exit_code

    def create(
        self,
        paths: List[Path],
        archive_prefix: str,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> int:
        """
        Erstellt ein neues Borg-Archiv.

        Entspricht dem 'borg create' Aufruf in allen Backup-Skripten.
        Exit 0 = OK, 1 = Warnungen (Backup nutzbar), ≥2 = Fehler.

        Args:
            paths:          Zu sichernde Verzeichnisse
            archive_prefix: Präfix des Archiv-Namens (z.B. "flash-backup")
            extra_env:      Zusätzliche Env-Vars für den borg-Subprocess (z.B. BORG_RSH)

        Returns:
            Borg Exit-Code (0, 1 oder ≥2)
        """
        repo = self.config.repo or os.environ.get("BORG_REPO", "")
        if not repo:
            logger.error("borg create: BORG_REPO nicht gesetzt")
            return BORG_EXIT_ERROR

        archive = f"{repo}::{archive_prefix}-{{now:%Y-%m-%d_%H-%M-%S}}"

        cmd = [
            "borg", "create",
            "--stats",
            "--show-rc",
            f"--compression={self.config.compression}",
            f"--checkpoint-interval={self.config.checkpoint_interval}",
            "--files-cache=ctime,size",
            archive,
        ] + [str(p) for p in paths]

        _log_section("PHASE 3: BORG BACKUP (CREATE)")
        logger.info("Repository: %s", repo)
        logger.info("Backup-Pfade: %s", " ".join(str(p) for p in paths))
        logger.info("Performance: Compression=%s", self.config.compression)
        logger.info("Cache: %s", os.environ.get("BORG_CACHE_DIR", ""))
        logger.info("")
        logger.info(
            "Borg create startet... (%d Pfade, compression=%s)",
            len(paths),
            self.config.compression,
        )

        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
        except FileNotFoundError:
            logger.error("borg nicht gefunden – ist Borg Backup installiert?")
            return BORG_EXIT_ERROR
        except OSError as exc:
            logger.error("Borg-Prozess konnte nicht gestartet werden: %s", exc)
            return BORG_EXIT_ERROR

        wd_stop = threading.Event()
        wd_thread = _start_process_watchdog(
            process,
            operation="borg create",
            max_runtime_hours=max(0, int(self.config.max_runtime_hours or 0)),
            stop_event=wd_stop,
        )
        assert process.stdout is not None
        try:
            for line in process.stdout:
                line = line.rstrip("\n")
                if line:
                    logger.info("%s", line)
        finally:
            process.wait()
            wd_stop.set()
            if wd_thread is not None:
                wd_thread.join(timeout=1.0)
        exit_code = process.returncode

        if exit_code == BORG_EXIT_OK:
            logger.info("Borg create erfolgreich")
        elif exit_code == BORG_EXIT_WARNING:
            logger.info("Borg create mit Warnungen (Exit 1) – Backup nutzbar")
        else:
            logger.error("FEHLER: Borg create fehlgeschlagen (Exit %d)", exit_code)

        return exit_code

    def maintenance(self) -> int:
        """
        Führt Wartungssequenz aus: prune → compact → check.

        Entspricht dem PHASE Wartung-Block in allen Backup-Skripten.
        Abbricht sofort bei exit ≥ 2 (Fehler). Sammelt Warnungen (exit 1).

        Returns:
            Schlechtester Exit-Code der drei Operationen (0, 1 oder ≥2)
        """
        _log_section("PHASE 4: BORG WARTUNG (Prune, Compact, Check)")
        worst = BORG_EXIT_OK

        steps = [
            ("prune",   self.prune),
            ("compact", self.compact),
            ("check",   self.check),
        ]

        for step_name, step_fn in steps:
            logger.info("Wartung Schritt: %s", step_name)
            exit_code = step_fn()
            if exit_code >= BORG_EXIT_ERROR:
                logger.error(
                    "Borg %s fehlgeschlagen (Exit %d) – Wartung abgebrochen",
                    step_name, exit_code,
                )
                return exit_code
            worst = max(worst, exit_code)

        return worst


# ---------------------------------------------------------------------------
# Statistik-Parsing
# ---------------------------------------------------------------------------

def parse_borg_stats(log_file: Path) -> Optional[BorgStats]:
    """
    Parst Borg-Statistiken aus dem letzten Backup-Log.

    Entspricht parse_borg_stats() in borg-common.sh.
    Liest die letzten 100 Zeilen der Log-Datei und sucht nach dem
    "This archive:"-Block oder den "Original/Compressed/Deduplicated size:"-Zeilen.

    Args:
        log_file: Pfad zur Borg-Log-Datei

    Returns:
        BorgStats-Instanz, oder None wenn Log nicht lesbar
    """
    if not log_file or not Path(log_file).exists():
        logger.warning("parse_borg_stats: Log-Datei nicht gefunden: %s", log_file)
        return None

    try:
        lines = Path(log_file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        logger.warning("parse_borg_stats: Log-Datei nicht lesbar: %s", exc)
        return None

    full_text = "\n".join(lines)
    tail = lines[-100:] if len(lines) > 100 else lines
    text = "\n".join(tail)

    stats = BorgStats()

    # Archive-Name – im gesamten Log suchen (steht oft vor dem Tail-Fenster).
    # Letztes Vorkommen nehmen, damit bei mehreren Einträgen der neueste gewinnt.
    matches = re.findall(r"Archive name:\s+(.+)", full_text)
    if matches:
        stats.archive_name = matches[-1].strip()

    # Format: "This archive:    73.43 GB    33.14 GB    492.54 MB"
    # (drei Spalten: Original, Compressed, Deduplicated)
    archive_line_match = re.search(r"This archive:\s+([\d.]+\s+\S+)\s+([\d.]+\s+\S+)\s+([\d.]+\s+\S+)", text)
    if archive_line_match:
        stats.original_size = convert_to_bytes(archive_line_match.group(1))
        stats.compressed_size = convert_to_bytes(archive_line_match.group(2))
        stats.deduplicated_size = convert_to_bytes(archive_line_match.group(3))
    else:
        # Fallback: einzelne Zeilen (ältere Borg-Versionen)
        m = re.search(r"Original size:\s+([\d.]+\s+\S+)", text)
        if m:
            stats.original_size = convert_to_bytes(m.group(1))

        m = re.search(r"Compressed size:\s+([\d.]+\s+\S+)", text)
        if m:
            stats.compressed_size = convert_to_bytes(m.group(1))

        m = re.search(r"Deduplicated size:\s+([\d.]+\s+\S+)", text)
        if m:
            stats.deduplicated_size = convert_to_bytes(m.group(1))

    # Anzahl Dateien
    m = re.search(r"Number of files:\s+(\d+)", text)
    if m:
        stats.files = int(m.group(1))

    return stats


def convert_to_bytes(size_str: str) -> int:
    """
    Konvertiert Borg-Größenangaben in Bytes.

    Entspricht convert_to_bytes() in borg-common.sh.
    Nutzt Python-Float statt externem bc-Kommando.

    Unterstützte Einheiten:
        B, kB (SI), KB (IEC), MB, MiB, GB, GiB, TB, TiB

    Args:
        size_str: Größenstring, z.B. "2.50 GB" oder "492.54 MB"

    Returns:
        Größe in Bytes als int, 0 bei ungültigem Input
    """
    if not size_str or not size_str.strip():
        return 0

    size_str = size_str.strip()

    # Zahl und Einheit trennen
    m = re.match(r"^([\d.]+)\s*([A-Za-z]+)?$", size_str)
    if not m:
        return 0

    try:
        num = float(m.group(1))
    except ValueError:
        return 0

    unit = m.group(2) or "B"
    multiplier = _UNIT_MULTIPLIERS.get(unit, 0)
    if multiplier == 0 and unit != "B":
        logger.debug("convert_to_bytes: unbekannte Einheit '%s'", unit)
        return 0

    return int(num * multiplier)


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen
# ---------------------------------------------------------------------------

def _run_borg(cmd: List[str]) -> int:
    """
    Führt ein Borg-Kommando aus und streamt die Ausgabe mit Zeitstempel.

    Entspricht dem Pattern: borg ... 2>&1 | add_timestamp in borg-common.sh.
    Kombiniert stdout und stderr, gibt jede Zeile mit Timestamp aus.

    Returns:
        Exit-Code des Borg-Prozesses
    """
    env = os.environ.copy()

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        logger.error("borg nicht gefunden – ist Borg Backup installiert?")
        return BORG_EXIT_ERROR
    except OSError as exc:
        logger.error("Borg-Prozess konnte nicht gestartet werden: %s", exc)
        return BORG_EXIT_ERROR

    max_runtime_hours = _max_runtime_hours_from_env(os.environ)
    wd_stop = threading.Event()
    wd_thread = _start_process_watchdog(
        process,
        operation=" ".join(cmd[:2]) if len(cmd) >= 2 else "borg command",
        max_runtime_hours=max_runtime_hours,
        stop_event=wd_stop,
    )
    assert process.stdout is not None
    try:
        for line in process.stdout:
            line = line.rstrip("\n")
            if line:
                logger.info("%s", line)
    finally:
        process.wait()
        wd_stop.set()
        if wd_thread is not None:
            wd_thread.join(timeout=1.0)
    return process.returncode


def _max_runtime_hours_from_env(env: Dict[str, str]) -> int:
    raw = str(env.get("BORG_MAX_RUNTIME_HOURS", "0") or "0").strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning(
            "Ungültiger Wert für BORG_MAX_RUNTIME_HOURS ('%s'), verwende 0 (unbegrenzt).",
            raw,
        )
        return 0


def _start_process_watchdog(
    process: subprocess.Popen,
    *,
    operation: str,
    max_runtime_hours: int,
    stop_event: threading.Event,
) -> Optional[threading.Thread]:
    """
    Startet einen Prozess-Watchdog.

    Design-Entscheidung (bewusst dokumentiert):
    - Default `BORG_MAX_RUNTIME_HOURS=0` bedeutet *kein* Hard-Limit.
    - Hintergrund: sehr große Initial-Backups können mehr als 72h dauern.
    - Statt blindem Kill gibt es Langlauf-Warnungen alle 24h.
    """
    try:
        max_hours = max(0, int(max_runtime_hours or 0))
    except (TypeError, ValueError):
        max_hours = 0

    started = time.time()
    kill_grace_s = 30

    def _watchdog() -> None:
        next_warn_hours = 24
        terminate_sent = False
        terminate_deadline = 0.0
        hard_deadline = (started + (max_hours * 3600)) if max_hours > 0 else None

        while not stop_event.wait(30):
            if process.poll() is not None:
                return
            now = time.time()
            elapsed_hours = (now - started) / 3600.0

            if elapsed_hours >= next_warn_hours:
                if max_hours > 0:
                    logger.warning(
                        "%s läuft seit %.1fh (Hard-Limit=%dh).",
                        operation,
                        elapsed_hours,
                        max_hours,
                    )
                else:
                    logger.warning(
                        "%s läuft seit %.1fh (kein Hard-Limit: BORG_MAX_RUNTIME_HOURS=0).",
                        operation,
                        elapsed_hours,
                    )
                next_warn_hours += 24

            if hard_deadline is not None and not terminate_sent and now >= hard_deadline:
                logger.error(
                    "%s überschreitet Hard-Limit (%dh) – sende SIGTERM.",
                    operation,
                    max_hours,
                )
                try:
                    process.terminate()
                except OSError:
                    return
                terminate_sent = True
                terminate_deadline = now + kill_grace_s
                continue

            if terminate_sent and process.poll() is None and now >= terminate_deadline:
                logger.error(
                    "%s reagiert nicht auf SIGTERM – sende SIGKILL nach %ds Grace-Phase.",
                    operation,
                    kill_grace_s,
                )
                try:
                    process.kill()
                except OSError:
                    pass
                return

    t = threading.Thread(target=_watchdog, name=f"bbui-watchdog-{operation}", daemon=True)
    t.start()
    return t


def _days_since_flag(flag_file: Path) -> int:
    """Gibt Tage seit letzter Änderung der Flag-Datei zurück (999 wenn nicht vorhanden)."""
    if not flag_file.exists():
        return 999
    try:
        mtime = flag_file.stat().st_mtime
        return int((time.time() - mtime) / 86400)
    except OSError:
        return 999


def _touch_flag(flag_file: Path) -> None:
    """Erstellt oder aktualisiert die Flag-Datei."""
    try:
        flag_file.parent.mkdir(parents=True, exist_ok=True)
        flag_file.touch()
    except OSError as exc:
        logger.warning("Flag-Datei konnte nicht geschrieben werden (%s): %s", flag_file, exc)


# ---------------------------------------------------------------------------
# CLI-Einstiegspunkt
# (python3 lib/borg_runner.py info|prune-dry|compact|check|check-force|parse-stats)
#
# Voraussetzung: BORG_REPO und BORG_PASSPHRASE (oder BORG_PASSCOMMAND)
# müssen als Umgebungsvariablen gesetzt sein – genau wie bei den Backup-Skripten.
# ---------------------------------------------------------------------------

def _cli_info(repo: str) -> int:
    """Zeigt Repository-Informationen (nicht-destruktiv)."""
    cmd = ["borg", "info", "--show-rc"]
    if repo:
        cmd.append(repo)
    return _run_borg(cmd)


def _cli_prune_dry(config: BorgConfig) -> int:
    """Simuliert prune mit --dry-run (löscht nichts)."""
    logger.info(
        "DRY-RUN prune (keep: %dd/%dw/%dm/%dy) – nichts wird gelöscht",
        config.keep_daily, config.keep_weekly,
        config.keep_monthly, config.keep_yearly,
    )
    cmd = [
        "borg", "prune",
        "--dry-run",
        "--verbose",
        "--list",
        "--show-rc",
        "--keep-daily",   str(config.keep_daily),
        "--keep-weekly",  str(config.keep_weekly),
        "--keep-monthly", str(config.keep_monthly),
        "--keep-yearly",  str(config.keep_yearly),
    ]
    if config.repo:
        cmd.append(config.repo)
    return _run_borg(cmd)


def _cli_parse_stats(log_path: Path) -> int:
    """Parst Borg-Statistiken aus einer Log-Datei und gibt sie aus."""
    stats = parse_borg_stats(log_path)
    if stats is None:
        print(f"Keine Statistiken gefunden in: {log_path}")
        return 1

    def _fmt(b: int) -> str:
        for unit, div in [("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("kB", 1e3)]:
            if b >= div:
                return f"{b / div:.2f} {unit}"
        return f"{b} B"

    print(f"Archiv:            {stats.archive_name}")
    print(f"Originalgröße:     {_fmt(stats.original_size)}")
    print(f"Komprimiert:       {_fmt(stats.compressed_size)}")
    print(f"Dedupliziert:      {_fmt(stats.deduplicated_size)}")
    print(f"Anzahl Dateien:    {stats.files:,}")
    return 0


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%F %T",
    )

    # Konfiguration vollständig aus Umgebungsvariablen lesen (wie in den Backup-Skripten)
    _config = BorgConfig.from_config(os.environ)
    _repo = _config.repo

    _USAGE = (
        "Verwendung: python3 lib/borg_runner.py <befehl> [args]\n"
        "\n"
        "Befehle:\n"
        "  info          Repository-Informationen anzeigen (sicher, read-only)\n"
        "  prune-dry     Prune simulieren ohne zu löschen (--dry-run)\n"
        "  compact       Ungenutzten Speicher freigeben\n"
        "  check         Repository-Integrität prüfen (respektiert Intervall)\n"
        "  check-force   Repository-Integrität prüfen (Intervall ignorieren)\n"
        "  parse-stats <logdatei>\n"
        "                Borg-Statistiken aus Log-Datei parsen und anzeigen\n"
        "\n"
        "Voraussetzung: BORG_REPO (und BORG_PASSPHRASE / BORG_PASSCOMMAND)\n"
        "               müssen als Umgebungsvariablen gesetzt sein.\n"
    )

    _cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if _cmd == "info":
        sys.exit(_cli_info(_repo))

    elif _cmd == "prune-dry":
        sys.exit(_cli_prune_dry(_config))

    elif _cmd == "compact":
        runner = BorgRunner(_config)
        sys.exit(runner.compact())

    elif _cmd == "check":
        runner = BorgRunner(_config)
        sys.exit(runner.check())

    elif _cmd == "check-force":
        # Intervall umgehen: Flag-Datei temporär entfernen
        _config.check_flag_file = Path("/tmp/borg_runner_check_force_flag_nonexistent")
        runner = BorgRunner(_config)
        sys.exit(runner.check())

    elif _cmd == "parse-stats":
        if len(sys.argv) < 3:
            print("Fehler: Pfad zur Log-Datei fehlt.")
            print("Beispiel: python3 lib/borg_runner.py parse-stats /mnt/user/logs/backup.log")
            sys.exit(1)
        sys.exit(_cli_parse_stats(Path(sys.argv[2])))

    else:
        print(_USAGE)
        sys.exit(0 if not _cmd else 1)
