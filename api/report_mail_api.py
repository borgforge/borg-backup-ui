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
from typing import Any, List, Optional


_REPORT_CRON_BEGIN = "# --- BORG-BACKUP-UI WEEKLY-REPORT BEGIN ---"
_REPORT_CRON_END   = "# --- BORG-BACKUP-UI WEEKLY-REPORT END ---"

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


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
        raise RuntimeError(f"Could not update crontab: {proc.stderr}")


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
        return {"success": False, "message": "GLOBAL_SMTP_HOST is not configured.", "message_code": "smtp_host_missing"}
    if not to_addr:
        return {"success": False, "message": "No recipient is configured.", "message_code": "smtp_recipient_missing"}
    if not sender:
        return {"success": False, "message": "No sender is configured.", "message_code": "smtp_sender_missing"}

    try:
        html = _build_html_report(config)
    except Exception as exc:
        return {"success": False, "message": f"Report generation failed: {exc}", "message_code": "weekly_report_generation_failed"}

    now = datetime.now().strftime("%Y-%m-%d")
    msg = EmailMessage()
    msg["Subject"] = f"Borg Backup - Weekly Report {now}"
    msg["From"]    = sender
    msg["To"]      = to_addr
    msg.set_content(f"Borg Backup Weekly Report {now}\n\nPlease view this message in an HTML-capable email client.")
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
        return {"success": True, "message": f"Weekly report sent to {to_addr}.", "message_code": "weekly_report_sent", "message_params": {"recipient": to_addr}}
    except smtplib.SMTPAuthenticationError as e:
        err = e.smtp_error.decode(errors='replace') if isinstance(e.smtp_error, bytes) else str(e)
        return {"success": False, "message": f"Authentication failed: {err} {_diag}", "message_code": "smtp_auth_failed"}
    except smtplib.SMTPException as e:
        return {"success": False, "message": f"SMTP error: {e} {_diag}", "message_code": "smtp_failed"}
    except OSError as e:
        return {"success": False, "message": f"Connection failed: {e} {_diag}", "message_code": "smtp_connection_failed"}
    except Exception as e:
        return {"success": False, "message": f"Unexpected error: {e} {_diag}", "message_code": "smtp_failed"}


# ── HTML-Report-Generator ──────────────────────────────────────────────────────

def _build_html_report(config: dict, now: Optional[datetime] = None) -> str:
    from status import StatusStore, BackupStatus, format_bytes, format_duration

    status_dir = Path(config["STATUS_DIR"])
    store = StatusStore(status_dir)
    all_statuses = store.load()
    latest = store.get_latest_per_key(all_statuses)
    generated_at = now or datetime.now()
    period_start_dt, period_end_dt = _weekly_report_period(generated_at)
    period_start = period_start_dt.strftime("%Y-%m-%d %H:%M")
    period_end = period_end_dt.strftime("%Y-%m-%d %H:%M")
    hostname = str(config.get("HOSTNAME") or config.get("SERVER_NAME") or "").strip() or "Unraid"

    rows = []
    grouped_rows: dict[str, list[str]] = {}
    group_stats: dict[str, dict[str, int]] = {}
    job_meta = {job_id: row for job_id, row in _job_metadata_by_key(config).items() if row.get('enabled') is not False}
    latest = {job_id: latest.get(job_id) or BackupStatus(job_id=job_id, identity_state='assigned', status='unknown') for job_id in job_meta}
    schedules = _report_schedules(config)
    planned_job_keys = _planned_job_keys_for_period(
        set(latest.keys()) | set(job_meta.keys()),
        schedules,
        period_start_dt,
        period_end_dt,
    )
    success_total = 0
    total_repo_size = 0
    total_duration = 0
    total_files = 0
    oldest_latest = None
    issues = []
    log_notes = []

    for key, st in sorted(latest.items(), key=lambda item: _status_sort_key(item[1], item[0])):
        meta = job_meta.get(key, {})
        location_key = _report_location(key, st, meta)
        job_label = _job_label(key, st, meta)
        archive_fmt = st.archive_name or "—"
        secondary = _job_secondary_line(key, archive_fmt)
        if st.job_name_snapshot and st.job_name_snapshot != meta.get('name'):
            secondary += ' | Run name: ' + st.job_name_snapshot
        status_color = {
            "success": "#22c55e",
            "skipped": "#f59e0b",
            "warning": "#f59e0b",
            "error":   "#ef4444",
        }.get(st.status, "#6b7280")
        status_label = {
            "success": "OK",
            "skipped": "Skipped",
            "warning": "Warning",
            "error":   "Error",
        }.get(st.status, st.status)

        if st.status == "success":
            success_total += 1

        total_repo_size += st.repository_size or 0
        total_duration += st.duration_seconds or 0
        total_files += st.files_count or 0
        if st.timestamp_dt is not None and (oldest_latest is None or st.timestamp_dt < oldest_latest):
            oldest_latest = st.timestamp_dt

        ta = _time_ago(st.timestamp, generated_at) if st.timestamp else "—"
        repo_fmt = format_bytes(st.repository_size) if st.repository_size else "—"
        dur_fmt  = format_duration(st.duration_seconds) if st.duration_seconds else "—"
        files_fmt = f"{st.files_count:,}" if st.files_count else "—"
        growth_value = _repo_growth_7d(all_statuses, key, period_start_dt, period_end_dt)
        if growth_value is None:
            growth_fmt = "—"
            growth_color = "#64748b"
        else:
            prefix = "+" if growth_value > 0 else ("-" if growth_value < 0 else "")
            growth_fmt = f"{prefix}{format_bytes(abs(growth_value))}"
            growth_color = "#d97706" if growth_value > 0 else ("#16a34a" if growth_value < 0 else "#64748b")
        check_label = _repo_check_label(st.repository_check_status)
        check_color = "#16a34a" if st.repository_check_status == "ok" else ("#d97706" if st.repository_check_status == "overdue" else "#64748b")

        if key in planned_job_keys:
            note = _status_note(st)
            if note:
                issues.append((job_label, note, status_color))
            if st.timestamp_dt and st.timestamp_dt < period_start_dt:
                issues.append((job_label, f"No run in this report period; last run was {_time_ago(st.timestamp, generated_at)}.", "#d97706"))
            if st.repository_check_status == "overdue":
                issues.append((job_label, "Repository check is overdue.", "#d97706"))

        if st.status == "error":
            log_summary = _summarize_log(st.log_file)
            if log_summary:
                log_notes.append((job_label, st, log_summary))

        group = group_stats.setdefault(location_key, {"total": 0, "success": 0, "warning": 0, "error": 0})
        group["total"] += 1
        if st.status == "success":
            group["success"] += 1
        elif st.status in {"warning", "skipped"}:
            group["warning"] += 1
        elif st.status == "error":
            group["error"] += 1

        row_html = f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;white-space:nowrap">
            <div style="font-weight:800;color:#0f172a;white-space:nowrap">{_he(job_label)}</div>
            <div style="font-size:12px;color:#64748b;white-space:nowrap">{_he(secondary)}</div>
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;color:{status_color};font-weight:700;white-space:nowrap">{status_label}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;color:#475569;font-size:13px;white-space:nowrap">
            <div>{_he(ta)}</div>
            <div style="font-size:12px;color:#94a3b8">{_he(st.timestamp or '—')}</div>
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;white-space:nowrap">{dur_fmt}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;white-space:nowrap">{repo_fmt}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;white-space:nowrap">{files_fmt}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;color:{growth_color};font-weight:700;white-space:nowrap">{growth_fmt}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;color:{check_color};white-space:nowrap">{check_label}</td>
        </tr>"""
        grouped_rows.setdefault(location_key, []).append(row_html)
        rows.append(row_html)

    total = len(latest)
    error_total = sum(1 for st in latest.values() if st.status == "error")
    warn_total  = sum(1 for st in latest.values() if st.status in {"warning", "skipped", "unknown", "cancelled"})
    summary_color = "#22c55e" if error_total == 0 and warn_total == 0 else ("#f59e0b" if error_total == 0 else "#ef4444")
    summary_text  = "All backups OK" if error_total == 0 and warn_total == 0 else (
        f"{error_total} errors, {warn_total} warnings"
    )

    now = generated_at.strftime("%Y-%m-%d %H:%M")
    rows_html = _render_grouped_job_rows(grouped_rows, group_stats) if rows else "<tr><td colspan='8' style='padding:16px;color:#6b7280'>No backup data available.</td></tr>"
    oldest_latest_fmt = oldest_latest.strftime("%Y-%m-%d %H:%M") if oldest_latest else "—"
    week_activity_html = _render_week_activity(all_statuses, latest, job_meta, schedules, generated_at, period_start_dt, period_end_dt)
    issue_html = _render_issue_list(issues)
    log_html = _render_log_notes(log_notes)
    logo_html = _app_icon_img_html()

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Borg Backup Weekly Report</title></head>
<body style="font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;background:#eef2f7;margin:0;padding:24px;color:#0f172a">
  <div style="max-width:1120px;margin:0 auto;background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 10px 28px rgba(15,23,42,.10);border:1px solid #dbe3ee">
    <div style="background:#172033;padding:24px 28px">
      <table role="presentation" style="width:100%;border-collapse:collapse">
        <tr>
          <td style="width:58px;vertical-align:top;padding:0 14px 0 0">{logo_html}</td>
          <td style="vertical-align:middle;padding:0">
            <div style="font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#93c5fd;font-weight:700;margin-bottom:6px">Borg Backup UI</div>
            <h1 style="color:#fff;margin:0;font-size:22px;line-height:1.25">Weekly Report</h1>
            <p style="color:#cbd5e1;margin:8px 0 0;font-size:13px;white-space:nowrap">Server: {_he(hostname)} · Period: {_he(period_start)} to {_he(period_end)} · Generated: {now}</p>
          </td>
        </tr>
      </table>
    </div>
    <div style="padding:24px 28px">
      <div style="background:{summary_color}14;border:1px solid {summary_color}55;border-radius:8px;padding:14px 16px;margin-bottom:18px">
        <span style="color:{summary_color};font-weight:800;font-size:16px">{summary_text}</span>
        <span style="color:#475569;font-size:13px;margin-left:12px">{success_total}/{total} successful</span>
      </div>

      <table role="presentation" style="width:100%;border-collapse:separate;border-spacing:10px;margin:0 -10px 18px">
        <tr>
          {_metric_card("Jobs", str(total), "latest known status")}
          {_metric_card("Total repository size", format_bytes(total_repo_size) if total_repo_size else "—", "sum of latest runs")}
          {_metric_card("Total duration", format_duration(total_duration) if total_duration else "—", "sum of latest runs")}
          {_metric_card("Files", f"{total_files:,}" if total_files else "—", "latest runs")}
          {_metric_card("Oldest run", oldest_latest_fmt, "among latest job statuses")}
        </tr>
      </table>

      {week_activity_html}

      {issue_html}

      <h2 style="margin:22px 0 4px;font-size:15px;color:#0f172a">Job Details</h2>
      <div style="font-size:12px;color:#64748b;margin-bottom:10px">Latest known status and repository details. The weekly activity matrix above is the primary week summary.</div>
      <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:13px;min-width:820px">
        <thead>
          <tr style="background:#f1f5f9">
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Job</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Status</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Last Run</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Duration</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Repo</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Files</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Growth 7d</th>
            <th style="padding:9px 12px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:2px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Repo Check</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      </div>

      {log_html}
    </div>
    <div style="background:#f8fafc;padding:14px 28px;font-size:11px;color:#94a3b8;text-align:center;border-top:1px solid #e2e8f0">
      Borg Backup UI · Automatically generated report · Status data from {_he(str(status_dir))}
    </div>
  </div>
</body>
</html>"""


def _he(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _job_metadata_by_key(config: dict) -> dict:
    from status_read_model import configured_jobs
    return configured_jobs(config)


def _report_schedules(config: dict) -> dict:
    try:
        from schedule_api import get_schedules

        schedules = get_schedules(config)
    except Exception:
        return {}
    return schedules if isinstance(schedules, dict) else {}


def _weekly_report_period(generated_at: datetime) -> tuple[datetime, datetime]:
    start = generated_at.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    return start, generated_at


def _planned_job_keys_for_period(keys: set[str], schedules: dict, period_start: datetime, period_end: datetime) -> set[str]:
    planned: set[str] = set()
    for key in keys:
        schedule = schedules.get(key) if isinstance(schedules.get(key), dict) else {}
        cron = str(schedule.get("cron") or "").strip()
        if not cron or not bool(schedule.get("enabled", True)):
            continue
        expected_dates = _cron_expected_dates(cron, period_start, period_end)
        if expected_dates is not None:
            planned.add(key)
    return planned


def _job_label(key: str, st: Any, meta: dict[str, str]) -> str:
    for value in (
        meta.get("name"),
        meta.get("display_name"),
        _derived_job_label(st),
        key,
    ):
        text = str(value or "").strip()
        if text:
            return text
    return "Unknown job"


def _derived_job_label(st: Any) -> str:
    if getattr(st, "job_name_snapshot", ""):
        return st.job_name_snapshot
    backup_type = str(getattr(st, "backup_type", "") or "").strip()
    location = str(getattr(st, "location", "") or "").strip()
    if backup_type and backup_type != "unknown":
        return f"{backup_type.replace('_', ' ').title()} - {_location_label(location)}"
    return ""


def _job_secondary_line(_key: str, archive_name: str) -> str:
    archive_text = str(archive_name or "").strip()
    if archive_text and archive_text != "—":
        return f"Archive: {archive_text}"
    return "—"


def _location_key(st: Any) -> str:
    raw = str(getattr(st, "location", "") or "unknown").strip().lower()
    return raw or "unknown"


def _location_label(location: str) -> str:
    return {
        "local": "Local",
        "usb": "USB",
        "smb": "SMB",
        "storagebox": "Storagebox",
        "custom": "Custom",
        "unknown": "Unknown",
    }.get(str(location or "unknown").strip().lower(), str(location or "Unknown").strip().title())


def _location_order(location: str) -> tuple[int, str]:
    order = {
        "local": 0,
        "usb": 1,
        "smb": 2,
        "storagebox": 3,
        "custom": 4,
        "unknown": 9,
    }
    key = str(location or "unknown").strip().lower() or "unknown"
    return (order.get(key, 8), key)


def _render_grouped_job_rows(grouped_rows: dict[str, list[str]], group_stats: dict[str, dict[str, int]]) -> str:
    blocks = []
    for location in sorted(grouped_rows, key=_location_order):
        stats = group_stats.get(location, {})
        total = int(stats.get("total") or 0)
        success = int(stats.get("success") or 0)
        warning = int(stats.get("warning") or 0)
        error = int(stats.get("error") or 0)
        summary = f"{success}/{total} OK"
        if warning:
            summary += f" · {warning} warning"
            if warning != 1:
                summary += "s"
        if error:
            summary += f" · {error} error"
            if error != 1:
                summary += "s"
        blocks.append(f"""
        <tr>
          <td colspan="8" style="padding:10px 12px;background:#eaf1f8;border-top:1px solid #dbe3ee;border-bottom:1px solid #dbe3ee">
            <span style="font-size:12px;color:#0f172a;font-weight:900;text-transform:uppercase;letter-spacing:.04em">{_he(_location_label(location))}</span>
            <span style="font-size:12px;color:#64748b;margin-left:10px">{_he(summary)}</span>
          </td>
        </tr>""")
        blocks.extend(grouped_rows.get(location, []))
    return "".join(blocks)


def _render_week_activity(
    statuses: list,
    latest: dict[str, Any],
    job_meta: dict[str, dict[str, Any]],
    schedules: dict,
    generated_at: datetime,
    period_start: datetime,
    period_end: datetime,
) -> str:
    keys = sorted(set(latest.keys()) | set(job_meta.keys()), key=lambda key: _report_key_sort(key, latest, job_meta))
    if not keys:
        return ""

    days = [period_start.date() + timedelta(days=offset) for offset in range(7)]
    headers = "".join(
        f"<th style='padding:8px 7px;text-align:center;font-size:11px;color:#64748b;font-weight:800;border-bottom:1px solid #dbe3ee;text-transform:uppercase;white-space:nowrap'>{_he(day.strftime('%a'))}<div style='font-size:10px;color:#94a3b8;font-weight:600;text-transform:none'>{day.strftime('%m-%d')}</div></th>"
        for day in days
    )

    planned_groups: dict[str, list[str]] = {}
    manual_rows = []
    for key in keys:
        meta = job_meta.get(key, {})
        if meta.get("enabled") is False and key not in latest:
            continue
        st = latest.get(key)
        location = _report_location(key, st, meta)
        label = _report_job_label(key, st, meta)
        runs = _statuses_for_key_in_window(statuses, key, period_start, period_end)
        schedule = schedules.get(key) if isinstance(schedules.get(key), dict) else {}
        cron = str(schedule.get("cron") or "").strip()
        schedule_enabled = bool(schedule.get("enabled", True))
        expected_dates = _cron_expected_dates(cron, period_start, period_end) if cron and schedule_enabled else None

        if cron and schedule_enabled and expected_dates is not None:
            row = _render_planned_week_row(label, runs, days, expected_dates)
            planned_groups.setdefault(location, []).append(row)
        else:
            reason = "Custom schedule" if cron and schedule_enabled else "Manual"
            manual_rows.append(_render_manual_week_row(label, st, runs, reason, generated_at))

    planned_html = _render_week_planned_groups(planned_groups, headers, len(days))
    manual_html = _render_week_manual_rows(manual_rows)
    if not planned_html and not manual_html:
        return ""

    legend = """
      <div style="font-size:11px;color:#64748b;margin:6px 0 10px">
        <span style="display:inline-block;margin-right:12px"><span style="display:inline-block;width:10px;height:10px;border-radius:999px;background:#22c55e;vertical-align:-1px"></span> Success</span>
        <span style="display:inline-block;margin-right:12px"><span style="display:inline-block;width:10px;height:10px;border-radius:999px;background:#f59e0b;vertical-align:-1px"></span> Warning/skipped</span>
        <span style="display:inline-block;margin-right:12px"><span style="display:inline-block;width:10px;height:10px;border-radius:999px;background:#ef4444;vertical-align:-1px"></span> Error</span>
        <span style="display:inline-block;margin-right:12px"><span style="display:inline-block;width:10px;height:10px;border-radius:999px;border:2px solid #f97316;vertical-align:-3px"></span> Expected but not run</span>
        <span style="display:inline-block"><span style="display:inline-block;width:10px;height:10px;border-radius:999px;background:#e2e8f0;vertical-align:-1px"></span> Not scheduled</span>
      </div>"""
    return f"""
      <h2 style="margin:22px 0 4px;font-size:15px;color:#0f172a">Weekly Activity</h2>
      <div style="font-size:12px;color:#64748b;margin-bottom:4px">Scheduled jobs are compared with their cron plan. Manual jobs only show activity in the report period.</div>
      {legend}
      {planned_html}
      {manual_html}
    """


def _render_week_planned_groups(planned_groups: dict[str, list[str]], headers: str, day_count: int) -> str:
    if not planned_groups:
        return ""
    body = []
    colspan = day_count + 2
    for location in sorted(planned_groups, key=_location_order):
        body.append(f"""
        <tr>
          <td colspan="{colspan}" style="padding:9px 10px;background:#eaf1f8;border-top:1px solid #dbe3ee;border-bottom:1px solid #dbe3ee">
            <span style="font-size:12px;color:#0f172a;font-weight:900;text-transform:uppercase;letter-spacing:.04em">{_he(_location_label(location))}</span>
          </td>
        </tr>""")
        body.extend(planned_groups[location])
    return f"""
      <div style="overflow-x:auto;margin-bottom:14px">
      <table style="width:100%;border-collapse:collapse;font-size:13px;min-width:760px">
        <thead>
          <tr style="background:#f8fafc">
            <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:1px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Planned jobs</th>
            {headers}
            <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:1px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Week</th>
          </tr>
        </thead>
        <tbody>{''.join(body)}</tbody>
      </table>
      </div>"""


def _render_planned_week_row(label: str, runs: list, days: list, expected_dates: set) -> str:
    runs_by_day: dict[Any, list] = {}
    for st in runs:
        if st.timestamp_dt is None:
            continue
        runs_by_day.setdefault(st.timestamp_dt.date(), []).append(st)

    expected_count = len(expected_dates)
    ok_expected = 0
    missed = 0
    cells = []
    for day in days:
        day_runs = runs_by_day.get(day, [])
        state = _aggregate_day_state(day_runs)
        expected = day in expected_dates
        if state:
            if expected and state == "success":
                ok_expected += 1
            cells.append(_week_dot_cell(state, _day_status_title(day, state, expected)))
        elif expected:
            missed += 1
            cells.append(_week_dot_cell("missed", f"{day.isoformat()}: expected run missing"))
        else:
            cells.append(_week_dot_cell("idle", f"{day.isoformat()}: not scheduled"))

    if expected_count <= 0:
        summary = f"{len(runs)} run" + ("" if len(runs) == 1 else "s")
        summary_color = "#64748b"
    elif missed:
        summary = f"{missed}/{expected_count} missed"
        summary_color = "#f97316"
    else:
        summary = f"{ok_expected}/{expected_count} OK"
        summary_color = "#16a34a"
    return f"""
        <tr>
          <td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;font-weight:800;color:#0f172a;white-space:nowrap">{_he(label)}</td>
          {''.join(cells)}
          <td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;color:{summary_color};font-weight:800;white-space:nowrap">{_he(summary)}</td>
        </tr>"""


def _render_week_manual_rows(rows: list[str]) -> str:
    if not rows:
        return ""
    return f"""
      <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:4px">
        <thead>
          <tr style="background:#f8fafc">
            <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:1px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Manual jobs</th>
            <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:1px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Runs</th>
            <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:1px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Last run</th>
            <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748b;font-weight:800;border-bottom:1px solid #dbe3ee;text-transform:uppercase;white-space:nowrap">Result</th>
          </tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>"""


def _render_manual_week_row(label: str, st: Any, runs: list, reason: str, generated_at: datetime) -> str:
    status = str(getattr(st, "status", "") or "unknown")
    color = {
        "success": "#16a34a",
        "warning": "#d97706",
        "skipped": "#d97706",
        "error": "#dc2626",
    }.get(status, "#64748b")
    result = {
        "success": "OK",
        "warning": "Warning",
        "skipped": "Skipped",
        "error": "Error",
        "unknown": "No status",
    }.get(status, status or "No status")
    last_run = _time_ago(st.timestamp, generated_at) if st is not None and getattr(st, "timestamp", "") else "never"
    return f"""
        <tr>
          <td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;white-space:nowrap">
            <div style="font-weight:800;color:#0f172a">{_he(label)}</div>
            <div style="font-size:11px;color:#64748b">{_he(reason)}</div>
          </td>
          <td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;white-space:nowrap">{len(runs)}</td>
          <td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;color:#475569;white-space:nowrap">{_he(last_run)}</td>
          <td style="padding:9px 10px;border-bottom:1px solid #e5e7eb;color:{color};font-weight:800;white-space:nowrap">{_he(result)}</td>
        </tr>"""


def _week_dot_cell(state: str, title: str) -> str:
    if state == "missed":
        dot = '<span style="display:inline-block;width:11px;height:11px;border-radius:999px;border:2px solid #f97316;background:#fff7ed"></span>'
    else:
        color = {
            "success": "#22c55e",
            "warning": "#f59e0b",
            "error": "#ef4444",
            "idle": "#e2e8f0",
        }.get(state, "#94a3b8")
        dot = f'<span style="display:inline-block;width:13px;height:13px;border-radius:999px;background:{color}"></span>'
    return f"<td title=\"{_he(title)}\" style=\"padding:9px 7px;border-bottom:1px solid #e5e7eb;text-align:center;white-space:nowrap\">{dot}</td>"


def _day_status_title(day: Any, state: str, expected: bool) -> str:
    suffix = "scheduled" if expected else "extra run"
    return f"{day.isoformat()}: {state} ({suffix})"


def _aggregate_day_state(day_runs: list) -> str:
    statuses = {str(getattr(st, "status", "") or "").strip().lower() for st in day_runs}
    if not statuses:
        return ""
    if "error" in statuses:
        return "error"
    if statuses & {"warning", "skipped", "cancelled"}:
        return "warning"
    if "success" in statuses:
        return "success"
    return "warning"


def _statuses_for_key_in_window(statuses: list, key: str, start: datetime, end: datetime) -> list:
    result = []
    for st in statuses:
        if getattr(st, "key", "") != key or st.timestamp_dt is None:
            continue
        if start <= st.timestamp_dt <= end:
            result.append(st)
    return result


def _repo_growth_7d(statuses: list, key: str, period_start: datetime, period_end: datetime) -> int | None:
    baseline = None
    current = None
    for st in sorted(statuses, key=lambda item: item.timestamp_dt or datetime.min):
        if getattr(st, "key", "") != key or st.timestamp_dt is None:
            continue
        size = int(getattr(st, "repository_size", 0) or 0)
        if size <= 0:
            continue
        if st.timestamp_dt < period_start:
            baseline = (size, getattr(st, "repository_snapshot", ""))
            continue
        if st.timestamp_dt <= period_end:
            current = (size, getattr(st, "repository_snapshot", ""))
    if baseline is None or current is None:
        return None
    return current[0] - baseline[0] if baseline[1] and baseline[1] == current[1] else None


def _cron_expected_dates(cron: str, start: datetime, end: datetime) -> set | None:
    parts = str(cron or "").split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if month != "*":
        return None
    try:
        minute_value = int(minute)
        hour_value = int(hour)
    except ValueError:
        return None
    if minute_value < 0 or minute_value > 59 or hour_value < 0 or hour_value > 23:
        return None
    if dom != "*" and dow != "*":
        return None

    dow_values = _parse_report_cron_dow_values(dow) if dow != "*" else set(range(7))
    if not dow_values:
        return None
    dom_value = None
    if dom != "*":
        try:
            dom_value = int(dom)
        except ValueError:
            return None
        if dom_value < 1 or dom_value > 31:
            return None

    dates = set()
    current = start.date()
    last = end.date()
    while current <= last:
        candidate = datetime(current.year, current.month, current.day, hour_value, minute_value)
        if start <= candidate <= end:
            if dom_value is not None:
                if current.day == dom_value:
                    dates.add(current)
            elif _cron_dow_for_report_datetime(candidate) in dow_values:
                dates.add(current)
        current += timedelta(days=1)
    return dates


def _parse_report_cron_dow_values(raw: str) -> set[int]:
    values: set[int] = set()
    text = str(raw or "").strip()
    if not text or text == "*":
        return set(range(7))
    for part in text.split(","):
        item = part.strip()
        if not item or "/" in item:
            return set()
        if "-" in item:
            start_raw, end_raw = item.split("-", 1)
            try:
                start = int(start_raw)
                end = int(end_raw)
            except ValueError:
                return set()
            if start > end:
                return set()
            for value in range(start, end + 1):
                normalized = 0 if value == 7 else value
                if normalized < 0 or normalized > 6:
                    return set()
                values.add(normalized)
            continue
        try:
            value = int(item)
        except ValueError:
            return set()
        normalized = 0 if value == 7 else value
        if normalized < 0 or normalized > 6:
            return set()
        values.add(normalized)
    return values


def _cron_dow_for_report_datetime(value: datetime) -> int:
    return (value.weekday() + 1) % 7


def _report_key_sort(key: str, latest: dict[str, Any], job_meta: dict[str, dict[str, Any]]) -> tuple:
    meta = job_meta.get(key, {})
    st = latest.get(key)
    location = _report_location(key, st, meta)
    backup_type = str(getattr(st, "backup_type", "") or meta.get("backup_type") or "unknown")
    return (*_location_order(location), backup_type.lower(), _report_job_label(key, st, meta).lower(), key.lower())


def _report_location(key: str, st: Any, meta: dict[str, Any]) -> str:
    value = str(meta.get("location") or getattr(st, "location_snapshot", "") or "").strip().lower()
    if value:
        return value
    return "unknown"


def _report_job_label(key: str, st: Any, meta: dict[str, Any]) -> str:
    for value in (
        meta.get("name"),
        meta.get("display_name"),
        _derived_job_label(st) if st is not None else "",
        key,
    ):
        text = str(value or "").strip()
        if text:
            return text
    return "Unknown job"


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
        *_location_order(location),
        backup_type_order.get(backup_type, backup_type_order.get(backup_type.lower(), 8)),
        backup_type.lower(),
        fallback_key.lower(),
    )


def _time_ago(timestamp_str: str, reference: datetime) -> str:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            ts = datetime.strptime(timestamp_str, fmt)
            break
        except (ValueError, TypeError):
            pass
    else:
        return "unknown"

    diff = max(0, int((reference - ts).total_seconds()))
    if diff < 60:
        return "just now"
    if diff < 3600:
        minutes = diff // 60
        return f"{minutes} minute ago" if minutes == 1 else f"{minutes} minutes ago"
    if diff < 86400:
        hours = diff // 3600
        return f"{hours} hour ago" if hours == 1 else f"{hours} hours ago"
    days = diff // 86400
    return f"{days} day ago" if days == 1 else f"{days} days ago"


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
        "overdue": "overdue",
        "unknown": "unknown",
    }.get(status or "unknown", status or "unknown")


def _status_note(st) -> str:
    if st.status == "error":
        return st.error_message or f"Backup failed (exit {st.exit_code})."
    if st.status == "warning":
        return st.error_message or "Backup completed with warnings."
    if st.status == "skipped":
        return st.skip_reason_text or st.skip_reason_code or "Backup was skipped."
    return ""


def _render_issue_list(issues: list) -> str:
    if not issues:
        return """
        <div style="border:1px solid #bbf7d0;background:#f0fdf4;border-radius:8px;padding:12px 14px;margin:18px 0">
          <div style="font-weight:800;color:#15803d">No issues detected</div>
          <div style="font-size:12px;color:#64748b;margin-top:2px">All latest job statuses are free of errors and warnings.</div>
        </div>"""

    items = []
    for key, text, color in issues[:12]:
        items.append(f"""
        <tr>
          <td style="padding:7px 10px;border-bottom:1px solid #fde68a;font-weight:700;color:#92400e">{_he(key)}</td>
          <td style="padding:7px 10px;border-bottom:1px solid #fde68a;color:#475569">{_he(text)}</td>
          <td style="padding:7px 10px;border-bottom:1px solid #fde68a;color:{color};font-weight:700">check</td>
        </tr>""")
    more = "" if len(issues) <= 12 else f"<div style='font-size:12px;color:#92400e;margin-top:8px'>Additional issues: {len(issues) - 12}</div>"
    return f"""
    <div style="border:1px solid #facc15;background:#fffbeb;border-radius:8px;padding:12px 14px;margin:18px 0">
      <div style="font-weight:800;color:#92400e;margin-bottom:8px">Issues</div>
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
    <h2 style="margin:24px 0 8px;font-size:15px;color:#0f172a">Log Details</h2>
    <div style="border:1px solid #e2e8f0;background:#f8fafc;border-radius:8px;padding:4px 14px">{''.join(blocks)}</div>"""
