"""
api/report_mail_api.py – Wöchentlicher Status-Report per E-Mail

Generiert einen HTML-Report aus allen Job-Status-Dateien und sendet ihn
per SMTP. Der Cron-Job ruft POST /api/settings/weekly-report/send auf.
"""

import base64
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional


_REPORT_CRON_BEGIN = "# --- BORG-BACKUP-UI WEEKLY-REPORT BEGIN ---"
_REPORT_CRON_END   = "# --- BORG-BACKUP-UI WEEKLY-REPORT END ---"

_DAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def get_weekly_report_settings(config: dict) -> dict:
    return {
        "enabled":   config.get("WEEKLY_REPORT_ENABLED", "false").lower() == "true",
        "day":       config.get("WEEKLY_REPORT_DAY", "1"),
        "time":      config.get("WEEKLY_REPORT_TIME", "09:00"),
        "recipient": config.get("WEEKLY_REPORT_RECIPIENT", config.get("GLOBAL_MAIL_RECIPIENT", "")),
    }


def apply_weekly_report_cron(config: dict) -> None:
    """Installiert oder entfernt den Cron-Eintrag für den wöchentlichen Report."""
    settings = get_weekly_report_settings(config)

    try:
        current = subprocess.check_output(["crontab", "-l"], stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError:
        current = ""

    lines = current.splitlines()
    # Remove existing block
    filtered: List[str] = []
    skip = False
    for line in lines:
        if line.strip() == _REPORT_CRON_BEGIN:
            skip = True
        if not skip:
            filtered.append(line)
        if skip and line.strip() == _REPORT_CRON_END:
            skip = False

    if settings["enabled"]:
        port = config.get("PORT", "8765")
        time_parts = settings["time"].split(":")
        hour   = time_parts[0].lstrip("0") or "0"
        minute = time_parts[1].lstrip("0") or "0" if len(time_parts) > 1 else "0"
        # cron DOW: 0=Sunday, 1=Monday … 7=Sunday (we store 0=Monday, so +1 and wrap)
        dow = (int(settings["day"]) % 7) + 1
        cron_line = (
            f"{minute} {hour} * * {dow} "
            f"curl -s -X POST http://127.0.0.1:{port}/api/settings/weekly-report/send "
            f">/dev/null 2>&1"
        )
        filtered += [
            "",
            _REPORT_CRON_BEGIN,
            cron_line,
            _REPORT_CRON_END,
        ]

    new_crontab = "\n".join(filtered).rstrip("\n") + "\n"
    proc = subprocess.run(
        ["crontab", "-"],
        input=new_crontab,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"crontab konnte nicht gesetzt werden: {proc.stderr}")


def send_weekly_report(config: dict, recipient: str = "") -> dict:
    """Generiert und sendet den HTML-Status-Report."""
    import smtplib
    import ssl
    from email.message import EmailMessage
    from config_api import read_raw_conf

    conf = read_raw_conf(config)

    to_addr = (
        recipient.strip()
        or config.get("WEEKLY_REPORT_RECIPIENT", "").strip()
        or conf.get("GLOBAL_MAIL_RECIPIENT", "").strip()
    )
    host     = (conf.get("GLOBAL_SMTP_HOST", "")).strip()
    port     = int((conf.get("GLOBAL_SMTP_PORT", "587")).strip() or 587)
    user     = (conf.get("GLOBAL_SMTP_USER", "")).strip()
    password = (conf.get("GLOBAL_SMTP_PASSWORD", "")).strip()
    use_tls  = (conf.get("GLOBAL_SMTP_USE_TLS", "true")).strip().lower() == "true"
    sender   = (conf.get("GLOBAL_MAIL_SENDER", "")).strip() or user

    if not host:
        return {"success": False, "message": "GLOBAL_SMTP_HOST ist nicht konfiguriert."}
    if not to_addr:
        return {"success": False, "message": "Kein Empfänger konfiguriert."}
    if not sender:
        return {"success": False, "message": "Kein Absender konfiguriert."}

    try:
        html = _build_html_report(config)
    except Exception as exc:
        return {"success": False, "message": f"Report-Generierung fehlgeschlagen: {exc}"}

    now = datetime.now().strftime("%d.%m.%Y")
    msg = EmailMessage()
    msg["Subject"] = f"Borg Backup – Wochenbericht {now}"
    msg["From"]    = sender
    msg["To"]      = to_addr
    msg.set_content(f"Borg Backup Wochenbericht {now}\n\nBitte im HTML-fähigen E-Mail-Programm anzeigen.")
    msg.add_alternative(html, subtype="html")

    _diag = f"[Host={host}:{port}, TLS={use_tls}]"

    def _login_if_needed(smtp_obj):
        if not user:
            return
        try:
            smtp_obj.login(user, password)
        except smtplib.SMTPNotSupportedError:
            pass

    try:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ctx) as smtp:
                smtp.ehlo()
                _login_if_needed(smtp)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                if use_tls or smtp.has_extn('starttls'):
                    smtp.starttls(context=ctx)
                    smtp.ehlo()
                _login_if_needed(smtp)
                smtp.send_message(msg)
        return {"success": True, "message": f"Wochenbericht gesendet an {to_addr}."}
    except smtplib.SMTPAuthenticationError as e:
        err = e.smtp_error.decode(errors='replace') if isinstance(e.smtp_error, bytes) else str(e)
        return {"success": False, "message": f"Authentifizierungsfehler: {err} {_diag}"}
    except smtplib.SMTPException as e:
        return {"success": False, "message": f"SMTP-Fehler: {e} {_diag}"}
    except OSError as e:
        return {"success": False, "message": f"Verbindungsfehler: {e} {_diag}"}
    except Exception as e:
        return {"success": False, "message": f"Fehler: {e} {_diag}"}


# ── HTML-Report-Generator ──────────────────────────────────────────────────────

def _build_html_report(config: dict, now: Optional[datetime] = None) -> str:
    from status import StatusStore, format_bytes, format_duration

    status_dir = Path(config["STATUS_DIR"])
    store = StatusStore(status_dir)
    all_statuses = store.load()
    latest = store.get_latest_per_key(all_statuses)
    generated_at = now or datetime.now()

    run_dates = [st.timestamp_dt for st in all_statuses if st.timestamp_dt is not None]
    period_start = min(run_dates).strftime("%d.%m.%Y %H:%M") if run_dates else "keine Daten"
    period_end = max(run_dates).strftime("%d.%m.%Y %H:%M") if run_dates else "keine Daten"
    hostname = str(config.get("HOSTNAME") or config.get("SERVER_NAME") or "").strip() or "Unraid"

    rows = []
    success_total = 0
    total_repo_size = 0
    total_duration = 0
    total_files = 0
    oldest_latest = None
    issues = []
    log_notes = []

    for key, st in sorted(latest.items(), key=lambda item: _status_sort_key(item[1], item[0])):
        status_color = {
            "success": "#22c55e",
            "skipped": "#f59e0b",
            "warning": "#f59e0b",
            "error":   "#ef4444",
        }.get(st.status, "#6b7280")
        status_label = {
            "success": "OK",
            "skipped": "Übersprungen",
            "warning": "Warnung",
            "error":   "Fehler",
        }.get(st.status, st.status)

        if st.status == "success":
            success_total += 1

        total_repo_size += st.repository_size or 0
        total_duration += st.duration_seconds or 0
        total_files += st.files_count or 0
        if st.timestamp_dt is not None and (oldest_latest is None or st.timestamp_dt < oldest_latest):
            oldest_latest = st.timestamp_dt

        ta = _time_ago_de(st.timestamp, generated_at) if st.timestamp else "—"
        repo_fmt = format_bytes(st.repository_size) if st.repository_size else "—"
        dur_fmt  = format_duration(st.duration_seconds) if st.duration_seconds else "—"
        files_fmt = f"{st.files_count:,}".replace(",", ".") if st.files_count else "—"
        archive_fmt = st.archive_name or "—"
        check_label = _repo_check_label(st.repository_check_status)
        check_color = "#16a34a" if st.repository_check_status == "ok" else ("#d97706" if st.repository_check_status == "overdue" else "#64748b")
        week_cutoff = generated_at - timedelta(days=7)
        week_runs = _count_recent_runs(all_statuses, key, week_cutoff)
        week_success_rate = _recent_success_rate(all_statuses, key, week_cutoff)
        success_rate = f"{week_success_rate:.0f}%" if week_success_rate is not None else "—"

        note = _status_note(st)
        if note:
            issues.append((key, note, status_color))
        if st.timestamp_dt and (generated_at - st.timestamp_dt) > timedelta(days=7):
            issues.append((key, f"Letzter Lauf ist {_time_ago_de(st.timestamp, generated_at)}.", "#d97706"))
        if st.repository_check_status == "overdue":
            issues.append((key, "Repository-Prüfung ist überfällig.", "#d97706"))

        if st.status == "error":
            log_summary = _summarize_log(st.log_file)
            if log_summary:
                log_notes.append((key, st, log_summary))

        rows.append(f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;white-space:nowrap">
            <div style="font-weight:700;color:#0f172a;white-space:nowrap">{_he(key)}</div>
            <div style="font-size:12px;color:#64748b;white-space:nowrap">{_he(archive_fmt)}</div>
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;color:{status_color};font-weight:700;white-space:nowrap">{status_label}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;color:#475569;font-size:13px;white-space:nowrap">
            <div>{_he(ta)}</div>
            <div style="font-size:12px;color:#94a3b8">{_he(st.timestamp or '—')}</div>
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;white-space:nowrap">{dur_fmt}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;white-space:nowrap">{repo_fmt}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;white-space:nowrap">{files_fmt}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;white-space:nowrap">{week_runs}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;white-space:nowrap">{success_rate}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;color:{check_color};white-space:nowrap">{check_label}</td>
        </tr>""")

    total = len(latest)
    error_total = sum(1 for st in latest.values() if st.status == "error")
    warn_total  = sum(1 for st in latest.values() if st.status in {"warning", "skipped"})
    summary_color = "#22c55e" if error_total == 0 and warn_total == 0 else ("#f59e0b" if error_total == 0 else "#ef4444")
    summary_text  = "Alle Backups OK" if error_total == 0 and warn_total == 0 else (
        f"{error_total} Fehler, {warn_total} Warnungen"
    )

    now = generated_at.strftime("%d.%m.%Y %H:%M")
    rows_html = "".join(rows) if rows else "<tr><td colspan='9' style='padding:16px;color:#6b7280'>Keine Backup-Daten vorhanden.</td></tr>"
    oldest_latest_fmt = oldest_latest.strftime("%d.%m.%Y %H:%M") if oldest_latest else "—"
    issue_html = _render_issue_list(issues)
    log_html = _render_log_notes(log_notes)
    logo_html = _app_icon_img_html()

    return f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><title>Borg Backup Wochenbericht</title></head>
<body style="font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;background:#eef2f7;margin:0;padding:24px;color:#0f172a">
  <div style="max-width:1120px;margin:0 auto;background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 10px 28px rgba(15,23,42,.10);border:1px solid #dbe3ee">
    <div style="background:#172033;padding:24px 28px">
      <table role="presentation" style="width:100%;border-collapse:collapse">
        <tr>
          <td style="width:58px;vertical-align:top;padding:0 14px 0 0">{logo_html}</td>
          <td style="vertical-align:middle;padding:0">
            <div style="font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#93c5fd;font-weight:700;margin-bottom:6px">Borg Backup UI</div>
            <h1 style="color:#fff;margin:0;font-size:22px;line-height:1.25">Wochenbericht</h1>
            <p style="color:#cbd5e1;margin:8px 0 0;font-size:13px;white-space:nowrap">Server: {_he(hostname)} · Zeitraum: {_he(period_start)} bis {_he(period_end)} · Erzeugt: {now}</p>
          </td>
        </tr>
      </table>
    </div>
    <div style="padding:24px 28px">
      <div style="background:{summary_color}14;border:1px solid {summary_color}55;border-radius:8px;padding:14px 16px;margin-bottom:18px">
        <span style="color:{summary_color};font-weight:800;font-size:16px">{summary_text}</span>
        <span style="color:#475569;font-size:13px;margin-left:12px">{success_total}/{total} erfolgreich</span>
      </div>

      <table role="presentation" style="width:100%;border-collapse:separate;border-spacing:10px;margin:0 -10px 18px">
        <tr>
          {_metric_card("Jobs", str(total), "letzter bekannter Status")}
          {_metric_card("Repo gesamt", format_bytes(total_repo_size) if total_repo_size else "—", "Summe der letzten Läufe")}
          {_metric_card("Dauer gesamt", format_duration(total_duration) if total_duration else "—", "Summe der letzten Läufe")}
          {_metric_card("Dateien", f"{total_files:,}".replace(",", ".") if total_files else "—", "letzte Läufe")}
          {_metric_card("Ältester Lauf", oldest_latest_fmt, "unter den letzten Jobständen")}
        </tr>
      </table>

      {issue_html}

      <h2 style="margin:22px 0 10px;font-size:15px;color:#0f172a">Job-Übersicht</h2>
      <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:13px;min-width:980px">
        <thead>
          <tr style="background:#f1f5f9">
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Job / Archiv</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Status</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Letzter Lauf</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Dauer</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Repo</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Dateien</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Läufe 7T</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Erfolg 7T</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Repo-Check</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      </div>

      {log_html}
    </div>
    <div style="background:#f8fafc;padding:14px 28px;font-size:11px;color:#94a3b8;text-align:center;border-top:1px solid #e2e8f0">
      Borg Backup UI – automatisch generierter Bericht · Statusdaten aus {_he(str(status_dir))}
    </div>
  </div>
</body>
</html>"""


def _he(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _app_icon_img_html() -> str:
    icon_path = Path(__file__).resolve().parents[1] / "ui" / "assets" / "app-icon.png"
    try:
        encoded = base64.b64encode(icon_path.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return (
        f'<img src="data:image/png;base64,{encoded}" alt="Borg Backup UI" '
        'width="48" height="48" '
        'style="display:block;width:48px;height:48px;border-radius:10px">'
    )


def _status_sort_key(st, fallback_key: str) -> tuple:
    location_order = {
        "local": 0,
        "storagebox": 1,
        "usb": 2,
        "smb": 3,
        "unknown": 9,
    }
    backup_type_order = {
        "appdata": 0,
        "flash": 1,
        "photos": 2,
        "vms": 3,
        "VMs": 3,
        "sonstiges": 4,
        "unknown": 9,
    }
    location = str(getattr(st, "location", "") or "unknown")
    backup_type = str(getattr(st, "backup_type", "") or "unknown")
    return (
        location_order.get(location.lower(), 8),
        location.lower(),
        backup_type_order.get(backup_type, backup_type_order.get(backup_type.lower(), 8)),
        backup_type.lower(),
        fallback_key.lower(),
    )


def _time_ago_de(timestamp_str: str, reference: datetime) -> str:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            ts = datetime.strptime(timestamp_str, fmt)
            break
        except (ValueError, TypeError):
            pass
    else:
        return "unbekannt"

    diff = max(0, int((reference - ts).total_seconds()))
    if diff < 60:
        return "gerade eben"
    if diff < 3600:
        minutes = diff // 60
        return f"vor {minutes} Minute" if minutes == 1 else f"vor {minutes} Minuten"
    if diff < 86400:
        hours = diff // 3600
        return f"vor {hours} Stunde" if hours == 1 else f"vor {hours} Stunden"
    days = diff // 86400
    return f"vor {days} Tag" if days == 1 else f"vor {days} Tagen"


def _metric_card(label: str, value: str, hint: str) -> str:
    return f"""
    <td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px 14px;vertical-align:top">
      <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:800;letter-spacing:.03em">{_he(label)}</div>
      <div style="font-size:18px;color:#0f172a;font-weight:800;margin-top:5px">{_he(value)}</div>
      <div style="font-size:11px;color:#94a3b8;margin-top:3px">{_he(hint)}</div>
    </td>"""


def _repo_check_label(status: str) -> str:
    return {
        "ok": "OK",
        "overdue": "überfällig",
        "unknown": "unbekannt",
    }.get(status or "unknown", status or "unbekannt")


def _status_note(st) -> str:
    if st.status == "error":
        return st.error_message or f"Backup fehlgeschlagen (Exit {st.exit_code})."
    if st.status == "warning":
        return st.error_message or "Backup mit Warnungen abgeschlossen."
    if st.status == "skipped":
        return st.skip_reason_text or st.skip_reason_code or "Backup wurde übersprungen."
    return ""


def _count_recent_runs(statuses: list, key: str, cutoff: datetime) -> int:
    count = 0
    for st in statuses:
        if st.key != key or st.timestamp_dt is None:
            continue
        if st.timestamp_dt >= cutoff:
            count += 1
    return count


def _recent_success_rate(statuses: list, key: str, cutoff: datetime) -> float | None:
    total = 0
    success = 0
    for st in statuses:
        if st.key != key or st.timestamp_dt is None:
            continue
        if st.timestamp_dt < cutoff:
            continue
        total += 1
        if st.status == "success":
            success += 1
    if total == 0:
        return None
    return success / total * 100


def _render_issue_list(issues: list) -> str:
    if not issues:
        return """
        <div style="border:1px solid #bbf7d0;background:#f0fdf4;border-radius:8px;padding:12px 14px;margin:18px 0">
          <div style="font-weight:800;color:#15803d">Keine Auffälligkeiten erkannt</div>
          <div style="font-size:12px;color:#64748b;margin-top:2px">Alle letzten Jobstände sind ohne Fehler oder Warnung.</div>
        </div>"""

    items = []
    for key, text, color in issues[:12]:
        items.append(f"""
        <tr>
          <td style="padding:7px 10px;border-bottom:1px solid #fde68a;font-weight:700;color:#92400e">{_he(key)}</td>
          <td style="padding:7px 10px;border-bottom:1px solid #fde68a;color:#475569">{_he(text)}</td>
          <td style="padding:7px 10px;border-bottom:1px solid #fde68a;color:{color};font-weight:700">prüfen</td>
        </tr>""")
    more = "" if len(issues) <= 12 else f"<div style='font-size:12px;color:#92400e;margin-top:8px'>Weitere Auffälligkeiten: {len(issues) - 12}</div>"
    return f"""
    <div style="border:1px solid #facc15;background:#fffbeb;border-radius:8px;padding:12px 14px;margin:18px 0">
      <div style="font-weight:800;color:#92400e;margin-bottom:8px">Auffälligkeiten</div>
      <table style="width:100%;border-collapse:collapse;font-size:12px">{''.join(items)}</table>
      {more}
    </div>"""


def _summarize_log(log_file: str) -> list:
    path = Path(str(log_file or ""))
    if not log_file or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    selected = []
    for line in lines[-250:]:
        if _is_attention_log_line(line):
            selected.append(line.strip())
    return selected[-5:]


def _is_attention_log_line(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False

    padded = f" {text.upper()} "
    if " INFO " in padded:
        return False

    if any(token in padded for token in (" ERROR ", " WARNING ", " WARN ")):
        return True
    if re.search(r"(^|\s)(FEHLER|WARNUNG)[:\s]", padded):
        return True
    return bool(re.search(r"(^|\s)(FAILED|FEHLGESCHLAGEN)[:\s]?", padded))


def _render_log_notes(log_notes: list) -> str:
    if not log_notes:
        return ""
    blocks = []
    ordered = sorted(log_notes, key=lambda item: _status_sort_key(item[1], item[0]))
    for key, _st, lines in ordered[:8]:
        line_html = "".join(
            f"<div style='font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:#334155;padding:3px 0'>{_he(line)}</div>"
            for line in lines
        )
        blocks.append(f"""
        <div style="border-top:1px solid #e2e8f0;padding:10px 0">
          <div style="font-size:12px;font-weight:800;color:#0f172a;margin-bottom:4px">{_he(key)}</div>
          {line_html}
        </div>""")
    return f"""
    <h2 style="margin:24px 0 8px;font-size:15px;color:#0f172a">Log-Hinweise</h2>
    <div style="border:1px solid #e2e8f0;background:#f8fafc;border-radius:8px;padding:4px 14px">{''.join(blocks)}</div>"""
