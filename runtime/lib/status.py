"""
lib/status.py - Borg Backup Status I/O und Snapshot-Management
Version: 1.0.0

Ersetzt die status-bezogenen Teile von lib/borg-common.sh sowie.
save_weekly_snapshot(), load_last_week_snapshot(), cleanup_status_archive(),
trim_weekly_snapshots() aus borg_backup_summary_mail.sh.

Nur Python Standard-Library: json, pathlib, datetime, dataclasses
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

BACKUP_TYPES = ["flash", "appdata", "photos", "VMs", "sonstiges"]
LOCATIONS = ["local", "usb", "storagebox"]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BackupStatus:
    """Repräsentiert den Inhalt einer einzelnen .status Datei."""

    backup_type: str = "unknown"
    location: str = "unknown"
    timestamp: str = ""
    duration_seconds: int = 0
    exit_code: int = 99
    status: str = "unknown"          # success | warning | error | skipped
    skip_reason_code: str = ""
    skip_reason_text: str = ""
    error_message: str = ""
    log_file: str = ""
    archive_name: str = ""
    original_size: int = 0
    compressed_size: int = 0
    deduplicated_size: int = 0
    files_count: int = 0
    repository_size: int = 0
    transfer_speed_bytes_per_sec: int = 0
    repository_check_date: str = ""
    repository_check_status: str = "unknown"  # ok | overdue | unknown
    repository_next_check: str = ""

    # Pfad der Quelldatei (nicht serialisiert)
    source_path: Optional[Path] = field(default=None, repr=False, compare=False)

    @classmethod
    def from_file(cls, path: Path) -> "BackupStatus":
        """Liest und validiert eine .status JSON-Datei."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Fehler beim Lesen von %s: %s", path, exc)
            return cls(source_path=path)

        obj = cls(source_path=path)
        obj.backup_type = str(data.get("backup_type", "unknown"))
        obj.location = str(data.get("location", "unknown"))
        obj.timestamp = str(data.get("timestamp", ""))
        obj.duration_seconds = int(data.get("duration_seconds", 0) or 0)
        # Unterstütze beide Feldnamen: exit_code (neu) und borg_exit_code (alt)
        # Wichtig: `0 or X` wäre falsch (0 ist falsy) - daher explizite None-Prüfung
        _exit = data.get("exit_code")
        if _exit is None:
            _exit = data.get("borg_exit_code")
        obj.exit_code = int(_exit if _exit is not None else 99)
        obj.status = str(data.get("status", "unknown"))
        obj.error_message = str(data.get("error_message", "") or "")
        obj.log_file = str(data.get("log_file", "") or "")
        obj.archive_name = str(data.get("archive_name", "") or "")
        obj.original_size = int(data.get("original_size", 0) or 0)
        obj.compressed_size = int(data.get("compressed_size", 0) or 0)
        obj.deduplicated_size = int(data.get("deduplicated_size", 0) or 0)
        obj.files_count = int(data.get("files_count", 0) or 0)
        obj.repository_size = int(data.get("repository_size", 0) or 0)
        obj.transfer_speed_bytes_per_sec = int(
            data.get("transfer_speed_bytes_per_sec", 0) or 0
        )
        obj.repository_check_date = str(data.get("repository_check_date", "") or "")
        obj.repository_check_status = str(
            data.get("repository_check_status", "unknown") or "unknown"
        )
        obj.repository_next_check = str(data.get("repository_next_check", "") or "")
        obj.skip_reason_code = str(data.get("skip_reason_code", "") or "")
        obj.skip_reason_text = str(data.get("skip_reason_text", "") or "")

        # Fallback: Nutze deduplicated_size wenn repository_size nicht gesetzt
        if obj.repository_size == 0 and obj.deduplicated_size > 0:
            obj.repository_size = obj.deduplicated_size

        return obj

    @property
    def key(self) -> str:
        """Eindeutiger Schlüssel: backup_type_location."""
        return f"{self.backup_type}_{self.location}"

    @property
    def timestamp_dt(self) -> Optional[datetime]:
        """Parst timestamp als datetime (naive, lokale Zeit)."""
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(self.timestamp, fmt)
            except (ValueError, TypeError):
                pass
        return None

    def age_days(self, reference: Optional[datetime] = None) -> int:
        """Alter des Backups in Tagen."""
        ts = self.timestamp_dt
        if ts is None:
            return 0
        ref = reference or datetime.now()
        return max(0, (ref - ts).days)

    def save(self, status_dir: Path) -> Path:
        """Schreibt Status als JSON-Datei in status_dir. Gibt den Dateipfad zurück."""
        status_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = status_dir / f"{timestamp}_{self.backup_type}_{self.location}.status"
        data = {k: v for k, v in asdict(self).items() if k != "source_path"}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Backup-Status gespeichert: %s", path)
        return path


@dataclass
class RestoreTest:
    """Repräsentiert den Inhalt einer .test Datei."""

    test_date: str = ""
    test_result: str = "unknown"     # success | failed | unavailable
    test_level: int = 0
    tested_files: int = 0
    tested_files_count: int = 0
    tested_folders_count: int = 0
    tested_total_count: int = 0
    test_coverage: str = ""
    test_coverage_percentage: float = 0.0
    tested_archive: str = ""
    test_duration_seconds: int = 0
    test_exit_code: int = 0
    repository: str = ""
    reason: str = ""                 # Bei unavailable

    # archive_stats (nested)
    archive_original_size: int = 0
    archive_compressed_size: int = 0
    archive_deduplicated_size: int = 0
    archive_files_count: int = 0

    # error_analysis (nested)
    error_has_error: bool = False
    error_category: str = "none"
    error_details: str = ""
    error_affected_items: str = ""
    error_output: str = ""

    # level3_details (nested)
    level3_enabled: bool = False
    level3_sample_size: int = 0
    level3_success: int = 0
    level3_failed: int = 0
    level3_checksums: List[str] = field(default_factory=list)
    level3_failed_files: List[str] = field(default_factory=list)

    # tested_entries list
    tested_entries: List[str] = field(default_factory=list)

    # Backup-Typ und Location (aus Dateiname abgeleitet)
    backup_type: str = "unknown"
    location: str = "unknown"

    source_path: Optional[Path] = field(default=None, repr=False, compare=False)

    @classmethod
    def from_file(cls, path: Path) -> "RestoreTest":
        """Liest eine .test JSON-Datei."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Fehler beim Lesen von %s: %s", path, exc)
            return cls(source_path=path)

        # Backup-Typ und Location aus Dateiname: flash_local.test
        stem = path.stem  # z.B. "flash_local"
        parts = stem.split("_", 1)
        backup_type = parts[0] if len(parts) > 0 else "unknown"
        location = parts[1] if len(parts) > 1 else "unknown"

        obj = cls(source_path=path, backup_type=backup_type, location=location)
        obj.test_date = str(data.get("test_date", "") or "")
        obj.test_result = str(data.get("test_result", "unknown") or "unknown")
        obj.test_level = int(data.get("test_level", 0) or 0)
        obj.tested_files = int(data.get("tested_files", 0) or 0)
        obj.tested_files_count = int(data.get("tested_files_count", 0) or 0)
        obj.tested_folders_count = int(data.get("tested_folders_count", 0) or 0)
        obj.tested_total_count = int(data.get("tested_total_count", 0) or 0)
        obj.test_coverage = str(data.get("test_coverage", "") or "")
        obj.test_coverage_percentage = float(
            data.get("test_coverage_percentage", 0) or 0
        )
        obj.tested_archive = str(data.get("tested_archive", "") or "")
        obj.test_duration_seconds = int(data.get("test_duration_seconds", 0) or 0)
        obj.test_exit_code = int(data.get("test_exit_code", 0) or 0)
        obj.repository = str(data.get("repository", "") or "")
        obj.reason = str(data.get("reason", "") or "")

        # archive_stats (nested dict)
        archive_stats = data.get("archive_stats", {}) or {}
        obj.archive_original_size = int(archive_stats.get("original_size", 0) or 0)
        obj.archive_compressed_size = int(archive_stats.get("compressed_size", 0) or 0)
        obj.archive_deduplicated_size = int(
            archive_stats.get("deduplicated_size", 0) or 0
        )
        obj.archive_files_count = int(archive_stats.get("files_count", 0) or 0)

        # error_analysis (nested dict)
        error_analysis = data.get("error_analysis", {}) or {}
        obj.error_has_error = bool(error_analysis.get("has_error", False))
        obj.error_category = str(error_analysis.get("error_category", "none") or "none")
        obj.error_details = str(error_analysis.get("error_details", "") or "")
        obj.error_affected_items = str(
            error_analysis.get("error_affected_items", "") or ""
        )
        obj.error_output = str(error_analysis.get("error_output", "") or "")

        # level3_details (nested dict)
        level3 = data.get("level3_details", {}) or {}
        obj.level3_enabled = bool(level3.get("enabled", False))
        obj.level3_sample_size = int(level3.get("sample_size", 0) or 0)
        obj.level3_success = int(level3.get("success_count", 0) or 0)
        obj.level3_failed = int(level3.get("failed_count", 0) or 0)
        # Unterstütze beide Feldnamen: validated_checksums (neu) und checksums (alt)
        obj.level3_checksums = list(
            level3.get("validated_checksums") or level3.get("checksums", []) or []
        )
        obj.level3_failed_files = list(level3.get("failed_files", []) or [])

        obj.tested_entries = list(data.get("tested_entries", []) or [])

        return obj

    @property
    def key(self) -> str:
        return f"{self.backup_type}_{self.location}"

    @property
    def test_date_dt(self) -> Optional[datetime]:
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(self.test_date, fmt)
            except (ValueError, TypeError):
                pass
        return None

    def age_days(self, reference: Optional[datetime] = None) -> int:
        ts = self.test_date_dt
        if ts is None:
            return -1
        ref = reference or datetime.now()
        return max(0, (ref - ts).days)

    @property
    def compression_ratio_pct(self) -> int:
        """Kompressionsrate in Prozent (0-100)."""
        if self.archive_original_size <= 0:
            return 0
        ratio = (
            1 - self.archive_compressed_size / self.archive_original_size
        ) * 100
        return max(0, int(ratio))


# ---------------------------------------------------------------------------
# StatusStore – liest alle .status Dateien aus einem Verzeichnis
# ---------------------------------------------------------------------------

class StatusStore:
    """
    Liest und aggregiert alle .status Dateien eines Verzeichnisses.

    Im Dashboard werden die Dateien NICHT archiviert (nur gelesen).
    In der Summary-Mail werden sie nach dem Lesen archiviert.
    """

    def __init__(self, status_dir: Path, archive_dir: Optional[Path] = None):
        self.status_dir = status_dir
        self.archive_dir = archive_dir
        self._statuses: List[BackupStatus] = []
        self._loaded = False

    def load(self, move_to_archive: bool = False) -> List[BackupStatus]:
        """
        Lädt alle .status Dateien.

        Args:
            move_to_archive: Wenn True, werden Dateien nach dem Lesen ins
                             Archiv-Verzeichnis verschoben (für Summary-Mail).
        """
        if not self.status_dir.exists():
            logger.warning("Status-Verzeichnis nicht gefunden: %s", self.status_dir)
            return []

        statuses: List[BackupStatus] = []
        files = sorted(self.status_dir.glob("*.status"))

        for f in files:
            st = BackupStatus.from_file(f)
            statuses.append(st)

            if move_to_archive and self.archive_dir is not None:
                self.archive_dir.mkdir(parents=True, exist_ok=True)
                try:
                    dest = self.archive_dir / f.name
                    f.rename(dest)
                    logger.debug("Archiviert: %s -> %s", f.name, dest)
                except OSError as exc:
                    logger.warning("Fehler beim Archivieren von %s: %s", f, exc)

        self._statuses = statuses
        self._loaded = True
        return statuses

    def get_latest_per_key(
        self, statuses: Optional[List[BackupStatus]] = None
    ) -> Dict[str, BackupStatus]:
        """Gibt pro (backup_type_location) den neuesten Status zurück."""
        data = statuses if statuses is not None else self._statuses
        latest: Dict[str, BackupStatus] = {}
        for st in data:
            key = st.key
            existing = latest.get(key)
            if existing is None:
                latest[key] = st
            else:
                # Neuerer Timestamp gewinnt
                if (st.timestamp or "") > (existing.timestamp or ""):
                    latest[key] = st
        return latest

    def aggregate_by_key(
        self, statuses: Optional[List[BackupStatus]] = None
    ) -> Dict[str, "_BackupAggregate"]:
        """Aggregiert Statistiken pro (backup_type_location)."""
        data = statuses if statuses is not None else self._statuses
        result: Dict[str, _BackupAggregate] = {}
        for st in data:
            key = st.key
            if key not in result:
                result[key] = _BackupAggregate(key=key)
            result[key].add(st)
        return result


@dataclass
class _BackupAggregate:
    """Aggregierte Statistiken für einen Backup-Typ+Location."""

    key: str = ""
    total: int = 0
    success: int = 0
    warning: int = 0
    error: int = 0
    duration_sum: int = 0
    original_size_sum: int = 0
    deduplicated_size_sum: int = 0
    # Neuester Status (für Repository-Info)
    latest: Optional[BackupStatus] = None

    def add(self, st: BackupStatus) -> None:
        self.total += 1
        if st.status == "success":
            self.success += 1
        elif st.status in {"warning", "skipped"}:
            self.warning += 1
        elif st.status == "error":
            self.error += 1
        self.duration_sum += st.duration_seconds
        self.original_size_sum += st.original_size
        self.deduplicated_size_sum += st.deduplicated_size

        if self.latest is None or (st.timestamp or "") > (self.latest.timestamp or ""):
            self.latest = st

    @property
    def avg_duration(self) -> int:
        return self.duration_sum // self.total if self.total > 0 else 0

    @property
    def avg_original_size(self) -> int:
        return self.original_size_sum // self.total if self.total > 0 else 0

    @property
    def success_rate(self) -> float:
        return (self.success / self.total * 100) if self.total > 0 else 0.0

    @property
    def backup_type(self) -> str:
        return self.key.rsplit("_", 1)[0] if "_" in self.key else self.key

    @property
    def location(self) -> str:
        return self.key.rsplit("_", 1)[1] if "_" in self.key else ""


# ---------------------------------------------------------------------------
# SnapshotManager – wöchentliche Repository-Größen-Snapshots
# ---------------------------------------------------------------------------

class SnapshotManager:
    """
    Verwaltet weekly-snapshots.json für Trend-Analysen.

    Format:
    {
        "flash_local": [
            {"week": "2026-03-14", "size": 123456789},
            {"week": "2026-03-21", "size": 134567890}
        ],
        ...
    }
    """

    def __init__(self, snapshot_file: Path, max_entries: int = 52):
        self.snapshot_file = snapshot_file
        self.max_entries = max_entries
        self._data: Dict[str, List[Dict]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self.snapshot_file.exists():
            try:
                self._data = json.loads(
                    self.snapshot_file.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Fehler beim Lesen von %s: %s", self.snapshot_file, exc)
                self._data = {}
        else:
            self._data = {}
        self._loaded = True

    def get_last_week_sizes(self) -> Dict[str, int]:
        """
        Gibt Repository-Größen von VOR der letzten Woche zurück.
        Index [-2] = vorletzter Eintrag (Vorwoche).
        """
        self._load()
        result: Dict[str, int] = {}
        for key, entries in self._data.items():
            if isinstance(entries, list) and len(entries) >= 2:
                entry = entries[-2]
                result[key] = int(entry.get("size", 0) or 0)
        return result

    def save_snapshot(
        self,
        repo_sizes: Dict[str, int],
        week_tag: Optional[str] = None,
    ) -> None:
        """
        Speichert aktuelle Repository-Größen als neuen Snapshot-Eintrag.

        Wenn für diese Woche bereits ein Eintrag existiert, wird er aktualisiert.
        """
        self._load()
        if week_tag is None:
            week_tag = datetime.now().strftime("%Y-%m-%d")

        for key, size in repo_sizes.items():
            if size == 0:
                continue
            entries: List[Dict] = self._data.get(key, [])
            if entries and entries[-1].get("week") == week_tag:
                # Aktualisiere existierenden Eintrag dieser Woche
                entries[-1]["size"] = size
            else:
                entries.append({"week": week_tag, "size": size})
            self._data[key] = entries

        self._save()

    def trim(self) -> None:
        """Kürzt alle Eintraglisten auf max_entries (älteste werden gelöscht)."""
        self._load()
        changed = False
        for key in list(self._data.keys()):
            entries = self._data[key]
            if isinstance(entries, list) and len(entries) > self.max_entries:
                self._data[key] = entries[-self.max_entries :]
                changed = True
        if changed:
            self._save()
            logger.info(
                "Snapshot-Trim: Max. %d Einträge pro Backup-Typ", self.max_entries
            )

    def _save(self) -> None:
        self.snapshot_file.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_file.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------

def cleanup_status_archive(archive_dir: Path, retention_days: int = 90) -> int:
    """
    Löscht .status Dateien im Archiv-Verzeichnis die älter als retention_days sind.

    Returns:
        Anzahl gelöschter Dateien.
    """
    if not archive_dir.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=retention_days)
    deleted = 0

    for f in archive_dir.glob("*.status"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                deleted += 1
        except OSError as exc:
            logger.warning("Fehler beim Löschen von %s: %s", f, exc)

    return deleted


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def format_bytes(b: int) -> str:
    """Konvertiert Bytes in menschenlesbare Größe (1 Dezimalstelle)."""
    if b == 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.0f} {unit}" if unit == "B" else f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def format_duration(seconds: int) -> str:
    """Formatiert Sekunden als '2h 15m' oder '45m 30s'."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m}m"


def time_ago(timestamp_str: str, reference: Optional[datetime] = None) -> str:
    """Gibt eine menschenlesbare relative Zeit zurück ('2h ago', '3d ago')."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            ts = datetime.strptime(timestamp_str, fmt)
            break
        except (ValueError, TypeError):
            pass
    else:
        return "?"

    ref = reference or datetime.now()
    diff = int((ref - ts).total_seconds())

    if diff < 60:
        return f"{diff}s ago"
    if diff < 3600:
        return f"{diff // 60}m ago"
    if diff < 86400:
        return f"{diff // 3600}h ago"
    return f"{diff // 86400}d ago"


def load_config(config_file: Path) -> Dict[str, str]:
    """
    Liest backup.conf (Shell-Format: KEY=VALUE) und gibt Dict zurück.
    Ignoriert Kommentare, leere Zeilen und readonly-Präfixe.
    """
    config: Dict[str, str] = {}
    if not config_file.exists():
        return config

    for line in config_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Entferne "readonly " Präfix
        line = line.removeprefix("readonly ")
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # Entferne Anführungszeichen und Inline-Kommentare
        value = value.strip().strip('"').strip("'")
        # Inline-Kommentar entfernen (nur außerhalb von Quotes)
        comment_pos = value.find("  #")
        if comment_pos != -1:
            value = value[:comment_pos].strip()
        # Bash-Arrays überspringen (mehrzeilige Syntax: VALUE=(...))
        if value.startswith("("):
            continue
        if key:
            # Expandiere ${VAR} Referenzen mit bereits gelesenen Werten (wie Bash)
            # Legacy-Kompatibilität Storagebox:
            # - ${STORAGEBOX_BASE}  -> STORAGEBOX_BASE_PATH
            # - ${STORAGEBOX_BASE_PATH} -> STORAGEBOX_BASE
            def _resolve_ref(var_name: str) -> str:
                if var_name in config:
                    return config[var_name]
                if var_name == "STORAGEBOX_BASE":
                    return config.get("STORAGEBOX_BASE_PATH", f"${{{var_name}}}")
                if var_name == "STORAGEBOX_BASE_PATH":
                    return config.get("STORAGEBOX_BASE", f"${{{var_name}}}")
                return f"${{{var_name}}}"

            value = re.sub(
                r'\$\{([^}]+)\}',
                lambda m: _resolve_ref(m.group(1)),
                value,
            )
            config[key] = value

            # Alias beidseitig mitführen, damit ältere Placeholder weiter auflösbar bleiben.
            if key == "STORAGEBOX_BASE_PATH" and value and "STORAGEBOX_BASE" not in config:
                config["STORAGEBOX_BASE"] = value
            elif key == "STORAGEBOX_BASE" and value and "STORAGEBOX_BASE_PATH" not in config:
                config["STORAGEBOX_BASE_PATH"] = value

    return config
