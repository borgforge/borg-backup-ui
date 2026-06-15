"""
api/restore_tests_api.py – Restore-Test-Ergebnisse aus .test-Dateien lesen
"""
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List
import re


def resolve_restore_test_dir(config: dict) -> Path:
    status_dir = Path(config.get("STATUS_DIR", "/mnt/user/backup-status"))
    configured = Path(str(config.get("RESTORE_TEST_STATUS_DIR", "")).strip()) if config.get("RESTORE_TEST_STATUS_DIR") else None
    candidates = []
    if configured:
        candidates.append(configured)
    candidates.append(status_dir.parent / "restore-status")
    candidates.append(status_dir / "restore-tests")
    for c in candidates:
        if c.exists():
            return c
    return configured or (status_dir.parent / "restore-status")


def list_restore_tests(config: dict) -> List[dict]:
    """Liest .test-Dateien aus konfiguriertem Restore-Test-Verzeichnis."""
    test_dir = resolve_restore_test_dir(config)
    if not test_dir.exists():
        return []

    results = []
    for test_file in sorted(test_dir.glob("*.test")):
        try:
            data = json.loads(test_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        stem = test_file.stem
        data["job_key"] = stem
        data["key"] = stem or f"{data.get('type', '?')}_{data.get('location', '?')}"
        data["time_ago"] = _time_ago(data.get("test_date", ""))
        data["duration_formatted"] = _fmt_duration(data.get("test_duration_seconds", 0))
        data["report_schema_version"] = _safe_int(data.get("report_schema_version"), 0)
        data["overall_status"] = str(data.get("overall_status") or "").strip() or (
            "passed" if str(data.get("test_result", "")).lower() == "success"
            else ("failed" if str(data.get("test_result", "")).lower() in {"failed", "unavailable"} else "warning")
        )
        data["failure_code"] = str(data.get("failure_code") or "").strip()
        data["failure_hint"] = str(data.get("failure_hint") or "").strip()
        if not isinstance(data.get("steps"), list):
            data["steps"] = []
        data["step_count"] = len(data["steps"])

        stats = data.get("archive_stats", {})
        data["archive_stats_formatted"] = {
            "original":     _fmt_bytes(stats.get("original_size", 0)),
            "compressed":   _fmt_bytes(stats.get("compressed_size", 0)),
            "deduplicated": _fmt_bytes(stats.get("deduplicated_size", 0)),
        }

        results.append(data)

    # Fehlgeschlagene zuerst, dann nach Datum absteigend
    status_order = {"failed": 0, "unavailable": 1, "success": 2}
    results.sort(key=lambda r: (
        status_order.get(r.get("test_result", ""), 3),
        r.get("test_date", ""),
    ))
    return results


def list_restore_test_plan(config: dict) -> dict:
    from jobs_api import list_jobs, resolve_data_root

    jobs = list_jobs(config, {})
    interval_default = max(1, _safe_int(config.get("RESTORE_TEST_INTERVAL_DAYS"), 30))
    level_default = _safe_int(config.get("RESTORE_TEST_LEVEL"), 2)
    if level_default not in {1, 2, 3}:
        level_default = 2

    rows: List[dict] = []
    counts = {"scheduled": 0, "manual_only": 0, "off": 0, "overdue": 0}
    now_ts = datetime.now().timestamp()
    data_root = resolve_data_root(config)
    test_dir = resolve_restore_test_dir(config)

    for job in jobs:
        key = str(job.get("key") or "").strip()
        if not key:
            continue
        raw_policy = job.get("restore_test_policy") if isinstance(job.get("restore_test_policy"), dict) else {}
        eff = _normalize_restore_policy(raw_policy, job.get("location"), interval_default)
        mode = str(eff.get("mode") or "off")
        counts[mode] = counts.get(mode, 0) + 1

        test_file = test_dir / f"{key}.test"
        test_data = _load_test_file(test_file)
        dt = _extract_test_datetime(test_data, test_file) if test_data else None
        last_test_date = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""
        last_result = str(test_data.get("test_result") or "").strip().lower() if test_data else ""

        next_due = ""
        is_overdue = False
        if mode == "scheduled":
            interval_days = max(1, _safe_int(eff.get("interval_days"), interval_default))
            if dt is None:
                is_overdue = True
            else:
                due_ts = dt.timestamp() + (interval_days * 86400)
                next_due = datetime.fromtimestamp(due_ts).strftime("%Y-%m-%d %H:%M:%S")
                if due_ts <= now_ts:
                    is_overdue = True
            if is_overdue:
                counts["overdue"] += 1

        rows.append({
            "job_key": key,
            "display_name": job.get("display_name") or job.get("name") or key,
            "location": job.get("location") or "",
            "enabled": bool(job.get("enabled", True)),
            "backup_type": job.get("backup_type") or "",
            "policy": eff,
            "policy_raw": raw_policy,
            "last_test_date": last_test_date,
            "last_test_result": last_result,
            "next_due_at": next_due,
            "is_overdue": is_overdue,
            "verification_status": job.get("restore_verification_status") or "never",
            "verification_reason": job.get("restore_verification_reason") or "",
            "job_meta_file": str((data_root / "config" / "jobs" / f"{key}.json")),
        })

    rows.sort(key=lambda r: str(r.get("display_name") or "").lower())
    return {
        "defaults": {
            "interval_days": interval_default,
            "level": level_default,
            "location": str(config.get("RESTORE_TEST_LOCATION", "local") or "local"),
        },
        "summary": {
            "total": len(rows),
            "scheduled": counts.get("scheduled", 0),
            "manual_only": counts.get("manual_only", 0),
            "off": counts.get("off", 0),
            "overdue": counts.get("overdue", 0),
        },
        "jobs": rows,
    }


def update_restore_test_policy(config: dict, job_key: str, policy_raw: dict) -> dict:
    from jobs_api import resolve_data_root
    key = str(job_key or "").strip()
    if not key:
        raise ValueError("job_key fehlt")
    if not re.fullmatch(r"[A-Za-z0-9_]+", key):
        raise ValueError("Ungültiger job_key")
    if not isinstance(policy_raw, dict):
        raise ValueError("policy muss ein Objekt sein")
    mode_raw = str(policy_raw.get("mode") or "").strip().lower()
    if mode_raw and mode_raw not in {"scheduled", "manual_only", "off", "inherit", "on", "manual"}:
        raise ValueError("Ungültiger Policy-Modus")
    if "interval_days" in policy_raw:
        try:
            interval_value = int(str(policy_raw.get("interval_days")).strip())
        except Exception:
            raise ValueError("interval_days muss eine Zahl sein")
        if interval_value < 1:
            raise ValueError("interval_days muss >= 1 sein")
    if "level" in policy_raw:
        try:
            level_value = int(str(policy_raw.get("level")).strip())
        except Exception:
            raise ValueError("level muss eine Zahl sein")
        if level_value not in {1, 2, 3}:
            raise ValueError("level muss 1, 2 oder 3 sein")

    data_root = resolve_data_root(config)
    meta_file = data_root / "config" / "jobs" / f"{key}.json"
    if not meta_file.exists():
        raise FileNotFoundError(f"Job nicht gefunden: {key}")
    try:
        raw = json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Job-Metadaten fehlerhaft: {key}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"Job-Metadaten fehlerhaft: {key}")

    interval_default = max(1, _safe_int(config.get("RESTORE_TEST_INTERVAL_DAYS"), 30))
    location = raw.get("location", "")
    normalized = _normalize_restore_policy(policy_raw, location, interval_default)
    raw["restore_test_policy"] = normalized
    raw["updated_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta_file.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"saved": True, "job_key": key, "policy": normalized}


def build_restore_verification_map(config: dict, jobs: List[dict]) -> Dict[str, dict]:
    """
    Berechnet den Restore-Nachweisstatus pro Job.

    Status:
      - verified
      - stale
      - failed
      - never
      - not_required
    """
    out: Dict[str, dict] = {}
    interval_default = _safe_int(config.get("RESTORE_TEST_INTERVAL_DAYS"), 30)
    test_dir = resolve_restore_test_dir(config)

    for job in jobs or []:
        job_key = str(job.get("key") or "").strip()
        if not job_key:
            continue

        policy = _normalize_restore_policy(job.get("restore_test_policy"), job.get("location"), interval_default)
        mode = policy["mode"]
        test_file = test_dir / f"{job_key}.test"
        test_data = _load_test_file(test_file)

        status = "never"
        reason = ""
        last_test_date = ""
        last_result = ""
        last_level = 0
        last_duration_seconds = 0
        valid_until = ""
        age_days = None
        is_overdue = False

        if mode == "off":
            status = "not_required"
            reason = "policy_off"
        elif not test_data:
            status = "never"
            reason = "no_test_report"
        else:
            last_result = str(test_data.get("test_result") or "").strip().lower()
            last_level = _safe_int(test_data.get("test_level"), 0)
            last_duration_seconds = _safe_int(test_data.get("test_duration_seconds"), 0)
            dt = _extract_test_datetime(test_data, test_file)
            if dt is not None:
                last_test_date = dt.strftime("%Y-%m-%d %H:%M:%S")
                age_days = max(0, int((datetime.now() - dt).total_seconds() // 86400))

            if last_result == "success":
                if mode == "manual_only":
                    status = "verified"
                    reason = "manual_success"
                else:
                    validity_days = max(1, _safe_int(policy.get("validity_days"), interval_default))
                    if dt is not None:
                        expiry = dt.timestamp() + (validity_days * 86400)
                        valid_until = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d %H:%M:%S")
                    if age_days is not None and age_days > validity_days:
                        status = "stale"
                        reason = "validity_expired"
                        is_overdue = True
                    else:
                        status = "verified"
                        reason = "within_validity"
            elif last_result in {"failed", "unavailable"}:
                status = "failed"
                reason = f"last_result_{last_result}"
            else:
                status = "failed"
                reason = "unknown_last_result"

        out[job_key] = {
            "status": status,
            "reason": reason,
            "policy": policy,
            "last_test_date": last_test_date,
            "last_test_result": last_result,
            "last_test_level": last_level,
            "last_test_duration_seconds": last_duration_seconds,
            "valid_until": valid_until,
            "age_days": age_days,
            "is_overdue": is_overdue,
        }
    return out


def delete_restore_test(config: dict, job_key: str) -> dict:
    key = str(job_key or "").strip()
    if not key:
        raise ValueError("job_key fehlt")
    test_dir = resolve_restore_test_dir(config)
    target = test_dir / f"{key}.test"
    if not target.exists():
        raise FileNotFoundError(f"Restore-Test nicht gefunden: {target.name}")
    target.unlink()
    return {"deleted": True, "job_key": key}


def _time_ago(date_str: str):
    if not date_str:
        return None
    try:
        delta = datetime.now() - datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        secs = int(delta.total_seconds())
        if secs < 60:
            return "gerade eben"
        if secs < 3600:
            return f"vor {secs // 60} Min."
        if secs < 86400:
            return f"vor {secs // 3600} Std."
        d = secs // 86400
        if d == 1:
            return "gestern"
        if d < 30:
            return f"vor {d} Tagen"
        if d < 365:
            return f"vor {d // 30} Mon."
        return f"vor {d // 365} Jahren"
    except ValueError:
        return None


def _fmt_bytes(b: int) -> str:
    if not b:
        return "–"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}" if unit != "B" else f"{int(b)} B"
        b /= 1024
    return f"{b:.1f} PB"


def _fmt_duration(seconds: int) -> str:
    if not seconds:
        return "–"
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


def _normalize_restore_policy(raw_policy: Any, location: Any, default_interval: int) -> dict:
    policy = raw_policy if isinstance(raw_policy, dict) else {}
    mode = str(policy.get("mode") or "").strip().lower()
    if mode == "inherit":
        mode = "scheduled"
    elif mode == "on":
        mode = "scheduled"
    elif mode == "manual":
        mode = "manual_only"
    if mode not in {"off", "scheduled", "manual_only"}:
        # konservativer Fallback:
        # lokal = manuell möglich, remote = nicht erforderlich
        mode = "manual_only" if str(location or "").strip().lower() == "local" else "off"

    interval_days = max(1, _safe_int(policy.get("interval_days"), default_interval))
    validity_days = max(1, _safe_int(policy.get("validity_days"), interval_days))
    level = _safe_int(policy.get("level"), 2)
    if level not in {1, 2, 3}:
        level = 2
    max_runtime_minutes = max(0, _safe_int(policy.get("max_runtime_minutes"), 0))

    return {
        "mode": mode,
        "interval_days": interval_days,
        "validity_days": validity_days,
        "level": level,
        "max_runtime_minutes": max_runtime_minutes,
    }


def _load_test_file(test_file: Path) -> Dict[str, Any]:
    if not test_file.exists():
        return {}
    try:
        raw = json.loads(test_file.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _extract_test_datetime(test_data: Dict[str, Any], test_file: Path) -> datetime | None:
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
