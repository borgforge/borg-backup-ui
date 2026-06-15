// ══════════════════════════════════════════════════════════════════════════════
// BERICHTE PAGE
// ══════════════════════════════════════════════════════════════════════════════

async function berichtInit() {
  const sel = document.getElementById('bericht-job-sel');
  if (!sel) return;
  sel.innerHTML = '<option value="">— Job wählen —</option>';
  document.getElementById('bericht-body').style.display = 'none';
  document.getElementById('bericht-empty').style.display = '';
  _berichtMsg('');
  try {
    const data = await (await fetch('/api/reports/jobs')).json();
    for (const job of (data.jobs || [])) {
      const opt = document.createElement('option');
      opt.value = job.key;
      opt.textContent = job.display_name;
      sel.appendChild(opt);
    }
  } catch (e) {
    _berichtMsg('Fehler beim Laden der Jobs: ' + e.message, true);
  }
}

async function berichtLoad() {
  const jobKey = document.getElementById('bericht-job-sel').value;
  document.getElementById('bericht-body').style.display = 'none';
  _berichtMsg('');
  _berichtRestoreVerification('');
  if (!jobKey) {
    document.getElementById('bericht-empty').style.display = '';
    return;
  }
  document.getElementById('bericht-empty').style.display = 'none';
  _berichtMsg('Lade Bericht...');
  try {
    const [reportRes, jobsRes] = await Promise.all([
      fetch(`/api/reports/data?job=${encodeURIComponent(jobKey)}`),
      fetch('/api/jobs'),
    ]);
    const data = await reportRes.json();
    if (data.error) { _berichtMsg('Fehler: ' + data.error, true); return; }
    const jobsData = jobsRes.ok ? await jobsRes.json() : { jobs: [] };
    const selected = (jobsData.jobs || []).find((j) => String(j.key) === String(jobKey));
    _berichtRestoreVerification(selected || null);
    _berichtMsg('');
    _berichtRender(data);
    document.getElementById('bericht-body').style.display = '';
  } catch (e) {
    _berichtMsg('Fehler: ' + e.message, true);
  }
}

function _berichtRender(d) {
  const successPct = d.run_count > 0 ? Math.round(d.success_count / d.run_count * 100) : 0;
  document.getElementById('br-runs').textContent      = d.run_count;
  document.getElementById('br-success').textContent   = `${d.success_count} (${successPct}%)`;
  document.getElementById('br-avg-dur').textContent   = d.avg_duration_fmt || '—';
  document.getElementById('br-repo-size').textContent = d.latest_repository_size_fmt || '—';
  document.getElementById('br-orig-size').textContent = d.latest_original_size_fmt || '—';
  document.getElementById('br-dedup').textContent     = d.latest_deduplicated_size_fmt || '—';
  _berichtRenderGrowthCards(d.runs || []);

  document.getElementById('bericht-borginfo-cards').style.display = 'none';
  document.getElementById('bericht-borginfo-btn').disabled = false;
  _berichtBorgInfoMsg('');

  _berichtSizeChart(d.runs || []);
  _berichtDedupChart(d.runs || []);
  _berichtDurChart(d.runs || []);
  _berichtStatusChart(d.monthly_status || []);
}

function _berichtRenderGrowthCards(runs) {
  const rows = (runs || []).filter(r => (r.repository_size || 0) > 0);
  const now = rows.length ? rows[rows.length - 1] : null;
  const prev = rows.length > 1 ? rows[rows.length - 2] : null;
  const d7 = _findRowDaysBack(rows, 7);
  const d30Raw = _findRowDaysBack(rows, 30);
  const d30 = d30Raw || (rows.length > 1 ? rows[0] : null);

  const g7 = (now && d7) ? (now.repository_size - d7.repository_size) : null;
  const g30 = (now && d30) ? (now.repository_size - d30.repository_size) : null;
  const glast = (now && prev) ? (now.repository_size - prev.repository_size) : null;

  let gAvg = null;
  let gAvgDays = 0;
  if (now && d30) {
    const days = _daysBetween(d30.date, now.date);
    if (days > 0) {
      gAvg = (now.repository_size - d30.repository_size) / days;
      gAvgDays = days;
    }
  }

  document.getElementById('br-growth-7d').textContent = _fmtDelta(g7);
  const g30El = document.getElementById('br-growth-30d');
  const gAvgEl = document.getElementById('br-growth-avg-day');
  const daysHint = gAvgDays > 0 ? `seit ${gAvgDays} Tagen` : 'seit — Tagen';
  if (g30El) {
    const main = g30 == null ? '—' : _fmtDelta(g30);
    g30El.textContent = '';
    g30El.append(document.createTextNode(main));
    g30El.append(document.createElement('br'));
    const hintEl = document.createElement('span');
    hintEl.style.fontSize = '11px';
    hintEl.style.color = 'var(--text-muted)';
    hintEl.textContent = daysHint;
    g30El.append(hintEl);
  }
  if (gAvgEl) {
    const main = gAvg == null ? '—' : `${_fmtDelta(gAvg)}/Tag`;
    gAvgEl.textContent = '';
    gAvgEl.append(document.createTextNode(main));
    gAvgEl.append(document.createElement('br'));
    const hintEl = document.createElement('span');
    hintEl.style.fontSize = '11px';
    hintEl.style.color = 'var(--text-muted)';
    hintEl.textContent = daysHint;
    gAvgEl.append(hintEl);
  }
  document.getElementById('br-growth-last').textContent = _fmtDelta(glast);
}

function _daysBetween(a, b) {
  if (!a || !b) return 0;
  const da = new Date(`${a}T00:00:00`);
  const db = new Date(`${b}T00:00:00`);
  const ms = db - da;
  if (!Number.isFinite(ms) || ms <= 0) return 0;
  return Math.round(ms / 86400000);
}

function _findRowDaysBack(rows, daysBack) {
  if (!rows.length) return null;
  const last = rows[rows.length - 1];
  if (!last?.date) return null;
  const target = new Date(`${last.date}T00:00:00`);
  target.setDate(target.getDate() - daysBack);
  let best = null;
  for (const r of rows) {
    if (!r?.date) continue;
    const d = new Date(`${r.date}T00:00:00`);
    if (d <= target) best = r;
  }
  return best;
}

function _fmtDelta(bytes) {
  if (bytes == null) return '—';
  if (bytes === 0) return '±0 B';
  const sign = bytes > 0 ? '+' : '-';
  return `${sign}${_fmtBytes(Math.abs(bytes))}`;
}

function _berichtSizeChart(runs) {
  const el = document.getElementById('bericht-size-chart');
  const pts = runs.filter(r => r.repository_size > 0);
  if (!pts.length) { el.innerHTML = _noData(); return; }

  const BAR_W = 14, BAR_GAP = 4, CHART_H = 120, LABEL_H = 36;
  const maxVal = Math.max(...pts.map(r => r.repository_size));
  const totalW = pts.length * (BAR_W + BAR_GAP) - BAR_GAP + 40;
  const svgH = CHART_H + LABEL_H;
  let bars = '', labels = '';
  let lastYear = '';

  for (let i = 0; i < pts.length; i++) {
    const r = pts[i];
    const x = 20 + i * (BAR_W + BAR_GAP);
    const barH = Math.max(2, Math.round((r.repository_size / maxVal) * (CHART_H - 16)));
    const y = CHART_H - barH;
    const prev = i > 0 ? pts[i - 1] : null;
    const prevWeek = i > 6 ? pts[i - 7] : null;
    const dDay = prev ? (r.repository_size - prev.repository_size) : null;
    const dWeek = prevWeek ? (r.repository_size - prevWeek.repository_size) : null;
    const tooltip = [
      `Datum: ${r.date || '—'}`,
      `Repo-Größe: ${_fmtBytes(r.repository_size || 0)}`,
      `Delta Vortag: ${_fmtDelta(dDay)}`,
      `Delta Vorwoche: ${_fmtDelta(dWeek)}`,
      `Status: ${r.status || 'unknown'}`
    ].join('\n');
    const clr = r.status === 'error'
      ? 'var(--error)'
      : (r.status === 'warning' || r.status === 'skipped')
        ? 'var(--warning)'
        : 'var(--accent)';
    bars += `<rect x="${x}" y="${y}" width="${BAR_W}" height="${barH}" rx="2" fill="${clr}" opacity="0.8"><title>${escHtml(tooltip)}</title></rect>`;
    const mm = r.date ? r.date.substring(5, 7) : '';
    const yyyy = r.date ? r.date.substring(0, 4) : '';
    if (mm === '01' || mm === '07' || i === 0) {
      labels += `<text x="${x + BAR_W / 2}" y="${CHART_H + 14}" text-anchor="middle" class="rs-label">${mm}</text>`;
      if (yyyy !== lastYear) {
        labels += `<text x="${x + BAR_W / 2}" y="${CHART_H + 28}" text-anchor="middle" class="rs-year">${yyyy}</text>`;
        lastYear = yyyy;
      }
    }
  }
  const topLabel = _fmtBytes(maxVal);
  bars = `<text x="4" y="14" class="rs-label" text-anchor="start">${topLabel}</text>` + bars;

  el.innerHTML = `<svg viewBox="0 0 ${totalW} ${svgH}" width="${totalW}" height="${svgH}" xmlns="http://www.w3.org/2000/svg">${bars}${labels}</svg>`;
}

function _berichtDurChart(runs) {
  const el = document.getElementById('bericht-dur-chart');
  const pts = runs.filter(r => r.duration_seconds > 0);
  if (!pts.length) { el.innerHTML = _noData(); return; }

  const BAR_W = 14, BAR_GAP = 4, CHART_H = 100, LABEL_H = 36;
  const maxVal = Math.max(...pts.map(r => r.duration_seconds));
  const totalW = pts.length * (BAR_W + BAR_GAP) - BAR_GAP + 40;
  const svgH = CHART_H + LABEL_H;
  let bars = '', labels = '';
  let lastYear = '';

  for (let i = 0; i < pts.length; i++) {
    const r = pts[i];
    const x = 20 + i * (BAR_W + BAR_GAP);
    const barH = Math.max(2, Math.round((r.duration_seconds / maxVal) * (CHART_H - 16)));
    const y = CHART_H - barH;
    const prev = i > 0 ? pts[i - 1] : null;
    const dDay = prev ? (r.duration_seconds - prev.duration_seconds) : null;
    const tooltip = [
      `Datum: ${r.date || '—'}`,
      `Dauer: ${_fmtDuration(r.duration_seconds || 0)}`,
      `Delta Vortag: ${dDay == null ? '—' : _fmtDuration(Math.abs(dDay))}`
    ].join('\n');
    bars += `<rect x="${x}" y="${y}" width="${BAR_W}" height="${barH}" rx="2" class="rs-bar" opacity="0.8"><title>${escHtml(tooltip)}</title></rect>`;
    const mm = r.date ? r.date.substring(5, 7) : '';
    const yyyy = r.date ? r.date.substring(0, 4) : '';
    if (mm === '01' || mm === '07' || i === 0) {
      labels += `<text x="${x + BAR_W / 2}" y="${CHART_H + 14}" text-anchor="middle" class="rs-label">${mm}</text>`;
      if (yyyy !== lastYear) {
        labels += `<text x="${x + BAR_W / 2}" y="${CHART_H + 28}" text-anchor="middle" class="rs-year">${yyyy}</text>`;
        lastYear = yyyy;
      }
    }
  }
  const topSecs = maxVal;
  const topLabel = topSecs >= 3600 ? Math.round(topSecs / 3600) + 'h' : topSecs >= 60 ? Math.round(topSecs / 60) + 'm' : topSecs + 's';
  bars = `<text x="4" y="14" class="rs-label" text-anchor="start">${topLabel}</text>` + bars;

  el.innerHTML = `<svg viewBox="0 0 ${totalW} ${svgH}" width="${totalW}" height="${svgH}" xmlns="http://www.w3.org/2000/svg">${bars}${labels}</svg>`;
}

function _berichtDedupChart(runs) {
  const el = document.getElementById('bericht-dedup-chart');
  const pts = runs.filter(r => r.deduplicated_size > 0);
  if (!pts.length) { el.innerHTML = _noData(); return; }

  const BAR_W = 14, BAR_GAP = 4, CHART_H = 100, LABEL_H = 36;
  const maxVal = Math.max(...pts.map(r => r.deduplicated_size));
  const totalW = pts.length * (BAR_W + BAR_GAP) - BAR_GAP + 40;
  const svgH = CHART_H + LABEL_H;
  let bars = '', labels = '';
  let lastYear = '';

  for (let i = 0; i < pts.length; i++) {
    const r = pts[i];
    const x = 20 + i * (BAR_W + BAR_GAP);
    const barH = Math.max(2, Math.round((r.deduplicated_size / maxVal) * (CHART_H - 16)));
    const y = CHART_H - barH;
    const prev = i > 0 ? pts[i - 1] : null;
    const dDay = prev ? (r.deduplicated_size - prev.deduplicated_size) : null;
    const tooltip = [
      `Datum: ${r.date || '—'}`,
      `Neue Daten: ${_fmtBytes(r.deduplicated_size || 0)}`,
      `Delta Vortag: ${_fmtDelta(dDay)}`
    ].join('\n');
    bars += `<rect x="${x}" y="${y}" width="${BAR_W}" height="${barH}" rx="2" fill="var(--success)" opacity="0.8"><title>${escHtml(tooltip)}</title></rect>`;
    const mm = r.date ? r.date.substring(5, 7) : '';
    const yyyy = r.date ? r.date.substring(0, 4) : '';
    if (mm === '01' || mm === '07' || i === 0) {
      labels += `<text x="${x + BAR_W / 2}" y="${CHART_H + 14}" text-anchor="middle" class="rs-label">${mm}</text>`;
      if (yyyy !== lastYear) {
        labels += `<text x="${x + BAR_W / 2}" y="${CHART_H + 28}" text-anchor="middle" class="rs-year">${yyyy}</text>`;
        lastYear = yyyy;
      }
    }
  }
  bars = `<text x="4" y="14" class="rs-label" text-anchor="start">${_fmtBytes(maxVal)}</text>` + bars;
  el.innerHTML = `<svg viewBox="0 0 ${totalW} ${svgH}" width="${totalW}" height="${svgH}" xmlns="http://www.w3.org/2000/svg">${bars}${labels}</svg>`;
}

function _berichtStatusChart(monthly) {
  const el = document.getElementById('bericht-status-chart');
  if (!monthly.length) { el.innerHTML = _noData(); return; }

  const BAR_W = 28, BAR_GAP = 8, CHART_H = 100, LABEL_H = 36;
  const maxVal = Math.max(...monthly.map(m => m.success + m.warning + m.error), 1);
  const totalW = monthly.length * (BAR_W + BAR_GAP) - BAR_GAP + 40;
  const svgH = CHART_H + LABEL_H;
  let bars = '', labels = '';

  for (let i = 0; i < monthly.length; i++) {
    const m = monthly[i];
    const x = 20 + i * (BAR_W + BAR_GAP);
    const total = m.success + m.warning + m.error;
    const totalH = Math.max(2, Math.round((total / maxVal) * (CHART_H - 16)));
    let yOff = CHART_H;

    const segments = [
      { val: m.error, color: 'var(--error)' },
      { val: m.warning, color: 'var(--warning)' },
      { val: m.success, color: 'var(--success)' },
    ];
    const tooltip = [
      `Monat: ${m.month || '—'}`,
      `Erfolg: ${m.success || 0}`,
      `Warnung: ${m.warning || 0}`,
      `Fehler: ${m.error || 0}`,
      `Gesamt: ${total || 0}`
    ].join('\n');
    for (const seg of segments) {
      if (!seg.val) continue;
      const h = Math.round((seg.val / total) * totalH);
      yOff -= h;
      bars += `<rect x="${x}" y="${yOff}" width="${BAR_W}" height="${h}" rx="0" fill="${seg.color}" opacity="0.85"><title>${escHtml(tooltip)}</title></rect>`;
    }
    if (total > 0) {
      bars += `<text x="${x + BAR_W / 2}" y="${CHART_H - totalH - 4}" text-anchor="middle" class="rs-bar-val">${total}</text>`;
    }
    const mm = m.month.substring(5);
    const yyyy = m.month.substring(0, 4);
    labels += `<text x="${x + BAR_W / 2}" y="${CHART_H + 16}" text-anchor="middle" class="rs-label">${mm}</text>`;
    if (mm === '01') {
      labels += `<text x="${x + BAR_W / 2}" y="${CHART_H + 30}" text-anchor="middle" class="rs-year">${yyyy}</text>`;
    }
  }

  el.innerHTML = `<svg viewBox="0 0 ${totalW} ${svgH}" width="${totalW}" height="${svgH}" xmlns="http://www.w3.org/2000/svg">${bars}${labels}</svg>`;
}

function _noData() {
  return '<div style="color:var(--text-muted);padding:20px 0;text-align:center;font-size:13px">Keine Daten</div>';
}

function _fmtBytes(b) {
  if (!b) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (b >= 1024 && i < units.length - 1) { b /= 1024; i++; }
  return b.toFixed(i > 0 ? 1 : 0) + '\u00a0' + units[i];
}

function _fmtDuration(secs) {
  if (secs == null) return '—';
  secs = Math.abs(Number(secs) || 0);
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  if (h) return `${h}h ${String(m).padStart(2, '0')}m`;
  if (m) return `${m}m ${String(s).padStart(2, '0')}s`;
  return `${s}s`;
}

function _berichtMsg(msg, isError) {
  const el = document.getElementById('bericht-msg');
  if (!el) return;
  if (!msg) { el.classList.add('hidden'); el.textContent = ''; return; }
  el.classList.remove('hidden');
  el.textContent = msg;
  el.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
}

function _berichtRestoreVerification(job) {
  const el = document.getElementById('br-restore-verification');
  if (!el) return;
  if (!job) {
    el.className = 'status-message hidden';
    el.textContent = '';
    return;
  }
  const status = String(job.restore_verification_status || '').toLowerCase();
  const map = {
    verified: { cls: 'success-state', text: 'Restore-Nachweis: verifiziert' },
    stale: { cls: 'warning-state', text: 'Restore-Nachweis: überfällig' },
    failed: { cls: 'error-state', text: 'Restore-Nachweis: fehlgeschlagen' },
    never: { cls: 'warning-state', text: 'Restore-Nachweis: noch offen' },
    not_required: { cls: 'empty-state', text: 'Restore-Nachweis: nicht geplant' },
  };
  const item = map[status] || map.never;
  const details = [
    job.restore_verification_last_test_date ? `Letzter Test: ${job.restore_verification_last_test_date}` : '',
    job.restore_verification_valid_until ? `Gültig bis: ${job.restore_verification_valid_until}` : '',
  ].filter(Boolean).join(' · ');
  el.className = `status-message ${item.cls}`;
  el.textContent = details ? `${item.text} · ${details}` : item.text;
}

async function berichtLoadBorgInfo() {
  const jobKey = document.getElementById('bericht-job-sel').value;
  if (!jobKey) return;
  const btn = document.getElementById('bericht-borginfo-btn');
  btn.disabled = true;
  btn.textContent = 'Lädt…';
  _berichtBorgInfoMsg('Frage borg info ab…');
  document.getElementById('bericht-borginfo-cards').style.display = 'none';
  try {
    const data = await (await fetch(`/api/restore/repo-stats?job=${encodeURIComponent(jobKey)}`)).json();
    if (data.error) { _berichtBorgInfoMsg('Fehler: ' + data.error, true); btn.disabled = false; btn.textContent = 'Laden'; return; }
    _berichtBorgInfoMsg('');
    const fmt = _fmtBytes;
    const savings = data.total_size > 0
      ? Math.round((1 - data.unique_csize / data.total_size) * 100) + '%'
      : '—';
    document.getElementById('bi-total-size').textContent = fmt(data.total_size);
    document.getElementById('bi-csize').textContent      = fmt(data.total_csize);
    document.getElementById('bi-unique').textContent     = fmt(data.unique_csize);
    document.getElementById('bi-savings').textContent    = savings;
    document.getElementById('bi-count').textContent      = data.archive_count;
    document.getElementById('bericht-borginfo-cards').style.display = '';
    btn.textContent = 'Aktualisieren';
    btn.disabled = false;
  } catch (e) {
    _berichtBorgInfoMsg('Fehler: ' + e.message, true);
    btn.disabled = false;
    btn.textContent = 'Laden';
  }
}

function _berichtBorgInfoMsg(msg, isError) {
  const el = document.getElementById('bericht-borginfo-msg');
  if (!el) return;
  if (!msg) { el.classList.add('hidden'); el.textContent = ''; return; }
  el.classList.remove('hidden');
  el.textContent = msg;
  el.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
}
