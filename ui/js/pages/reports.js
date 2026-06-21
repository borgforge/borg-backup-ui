// ══════════════════════════════════════════════════════════════════════════════

window.BBUI = window.BBUI || {};
window.BBUI.reportState = window.BBUI.reportState || { data: null, job: null, jobs: [], borgInfo: null, borgInfoLoaded: false };
const reportState = window.BBUI.reportState;

function reportsT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(`reports.${key}`, params) || `reports.${key}`;
}
// BERICHTE PAGE
// ══════════════════════════════════════════════════════════════════════════════

async function berichtInit() {
  const sel = document.getElementById('bericht-job-sel');
  if (!sel) return;
  sel.innerHTML = `<option value="">${escHtml(reportsT('selectJob'))}</option>`;
  document.getElementById('bericht-body').style.display = 'none';
  document.getElementById('bericht-empty').style.display = '';
  _berichtMsg('');
  try {
    const data = await (await fetch('/api/reports/jobs')).json();
    reportState.jobs = data.jobs || [];
    for (const job of (data.jobs || [])) {
      const opt = document.createElement('option');
      opt.value = job.key;
      opt.textContent = job.display_name;
      sel.appendChild(opt);
    }
    _berichtRenderJobSidebar();
    const search = document.getElementById('report-job-search');
    if (search && !search.dataset.bound) {
      search.dataset.bound = 'true';
      search.addEventListener('input', _berichtRenderJobSidebar);
    }
  } catch (e) {
    _berichtMsg(reportsT('jobsLoadError', { message: e.message }), true);
  }
}

async function berichtLoad() {
  const jobKey = document.getElementById('bericht-job-sel').value;
  document.getElementById('bericht-body').style.display = 'none';
  _berichtMsg('');
  _berichtRestoreVerification('');
  if (!jobKey) {
    reportState.data = null;
    reportState.job = null;
    reportState.borgInfo = null;
    reportState.borgInfoLoaded = false;
    document.getElementById('bericht-empty').style.display = '';
    _berichtRenderJobSidebar();
    _berichtUpdateSelection(null);
    return;
  }
  document.getElementById('bericht-empty').style.display = 'none';
  _berichtMsg(reportsT('loading'));
  try {
    const [reportRes, jobsRes] = await Promise.all([
      fetch(`/api/reports/data?job=${encodeURIComponent(jobKey)}`),
      fetch('/api/jobs'),
    ]);
    const data = await reportRes.json();
    if (!reportRes.ok || data.error) { _berichtMsg(reportsT('error', { message: apiErrorMessage(data, reportRes.status) }), true); return; }
    const jobsData = jobsRes.ok ? await jobsRes.json() : { jobs: [] };
    const selected = (jobsData.jobs || []).find((j) => String(j.key) === String(jobKey));
    const reportJob = reportState.jobs.find((job) => String(job.key) === String(jobKey));
    reportState.data = data;
    reportState.job = selected ? { ...(reportJob || {}), ...selected } : (reportJob || null);
    reportState.borgInfo = null;
    reportState.borgInfoLoaded = false;
    _berichtRestoreVerification(reportState.job);
    _berichtRenderJobSidebar();
    _berichtUpdateSelection(reportState.job);
    _berichtMsg('');
    _berichtRender(data);
    document.getElementById('bericht-body').style.display = '';
  } catch (e) {
    _berichtMsg(reportsT('error', { message: e.message }), true);
  }
}

function _berichtLocationLabel(location) {
  const key = { local: 'jobs.locationLocal', usb: 'jobs.locationUsb', smb: 'jobs.locationSmb', storagebox: 'jobs.locationStoragebox' }[String(location || '').toLowerCase()];
  return key ? window.BBUI?.components?.i18n?.t?.(key) || location : location || '—';
}

function _berichtJobGlyph(job) {
  return { flash: '▣', appdata: '⬡', photos: '◇', vms: '▤', sonstiges: '⌘' }[String(job?.backup_type || '').toLowerCase()] || '○';
}

function _berichtRenderJobSidebar() {
  const list = document.getElementById('report-job-list');
  if (!list) return;
  const query = String(document.getElementById('report-job-search')?.value || '').trim().toLowerCase();
  const selected = document.getElementById('bericht-job-sel')?.value || '';
  const jobs = (reportState.jobs || []).filter((job) => `${job.display_name || ''} ${job.key || ''} ${job.location || ''}`.toLowerCase().includes(query));
  if (!jobs.length) {
    list.innerHTML = `<div class="ui-empty report-job-empty">${escHtml(reportsT('noMatchingJobs'))}</div>`;
    return;
  }
  const order = ['storagebox', 'usb', 'smb', 'local'];
  const locations = [...new Set(jobs.map((job) => String(job.location || 'local').toLowerCase()))]
    .sort((a, b) => (order.indexOf(a) < 0 ? 99 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 99 : order.indexOf(b)));
  list.innerHTML = locations.map((location) => `<section class="report-job-group"><h3>${escHtml(_berichtLocationLabel(location))}</h3>${jobs.filter((job) => String(job.location || 'local').toLowerCase() === location).map((job) => `<button class="report-job ${String(job.key) === selected ? 'is-active' : ''}" data-report-job="${escHtml(job.key)}" ${String(job.key) === selected ? 'aria-current="page"' : ''}><span class="location-nav-glyph">${_berichtJobGlyph(job)}</span><span><strong>${escHtml(job.display_name || job.key)}</strong><small>${escHtml(job.key)}</small></span><span class="report-job-dot"></span></button>`).join('')}</section>`).join('');
  list.querySelectorAll('[data-report-job]').forEach((button) => button.addEventListener('click', () => {
    const select = document.getElementById('bericht-job-sel');
    if (select) select.value = button.dataset.reportJob || '';
    berichtLoad();
  }));
}

function _berichtUpdateSelection(job) {
  const title = document.getElementById('report-selection-title');
  const subtitle = document.getElementById('report-selection-subtitle');
  if (title) title.textContent = job?.display_name || reportsT('noJobSelected');
  if (subtitle) subtitle.textContent = job ? `${_berichtLocationLabel(job.location)} · ${job.key}` : reportsT('workspaceSubtitle');
}

function _berichtRender(d) {
  const successPct = d.run_count > 0 ? Math.round(d.success_count / d.run_count * 100) : 0;
  document.getElementById('br-runs').textContent      = d.run_count;
  document.getElementById('br-run-badge').textContent = reportsT('runCount', { count: d.run_count });
  document.getElementById('br-success').textContent   = `${d.success_count} (${successPct}%)`;
  document.getElementById('br-avg-dur').textContent   = d.avg_duration_fmt || '—';
  document.getElementById('br-repo-size').textContent = d.latest_repository_size_fmt || '—';
  document.getElementById('br-orig-size').textContent = d.latest_original_size_fmt || '—';
  document.getElementById('br-dedup').textContent     = d.latest_deduplicated_size_fmt || '—';
  _berichtRenderGrowthCards(d.runs || []);

  document.getElementById('bericht-borginfo-cards').style.display = 'none';
  const borgInfoButton = document.getElementById('bericht-borginfo-btn');
  borgInfoButton.disabled = false;
  borgInfoButton.textContent = reportsT('load');
  _berichtBorgInfoMsg('');

  _berichtTrendTable(d.runs || []);
  _berichtStatusTable(d.monthly_status || []);
}

function _berichtTrendTable(runs) {
  const body = document.getElementById('bericht-trend-body');
  if (!body) return;
  const rows = Array.isArray(runs) ? runs : [];
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="6">${escHtml(reportsT('noData'))}</td></tr>`;
    return;
  }
  const last = rows[rows.length - 1];
  const last7 = rows.slice(-7);
  const last30 = rows.slice(-30);
  const metricRows = [
    {
      label: reportsT('repoSizeMetric'), detail: reportsT('occupiedStorage'),
      values: rows.map((row) => Number(row.repository_size || 0)).filter((value) => value > 0),
      current: _fmtBytes(last.repository_size || 0),
      seven: _fmtDeltaAgainst(last.repository_size, last7[0]?.repository_size),
      thirty: _fmtDeltaAgainst(last.repository_size, last30[0]?.repository_size),
      format: _fmtBytes, color: 'var(--ui-color-accent)',
    },
    {
      label: reportsT('uniqueDataMetric'), detail: reportsT('perBackupRun'),
      values: rows.map((row) => Number(row.deduplicated_size || 0)).filter((value) => value > 0),
      current: _fmtBytes(last.deduplicated_size || 0),
      seven: reportsT('averageValue', { value: _fmtBytes(_average(last7.map((row) => row.deduplicated_size))) }),
      thirty: reportsT('averageValue', { value: _fmtBytes(_average(last30.map((row) => row.deduplicated_size))) }),
      format: _fmtBytes, color: 'var(--ui-state-success-fg)',
    },
    {
      label: reportsT('durationMetric'), detail: reportsT('executionTime'),
      values: rows.map((row) => Number(row.duration_seconds || 0)).filter((value) => value > 0),
      current: _fmtDuration(last.duration_seconds),
      seven: _fmtDurationDelta(last.duration_seconds, _average(last7.map((row) => row.duration_seconds))),
      thirty: _fmtDurationDelta(last.duration_seconds, _average(last30.map((row) => row.duration_seconds))),
      format: _fmtDuration, color: 'var(--ui-state-warning-fg)',
    },
  ];
  body.innerHTML = metricRows.map((metric) => {
    const min = metric.values.length ? Math.min(...metric.values) : 0;
    const max = metric.values.length ? Math.max(...metric.values) : 0;
    return `<tr><td><strong>${escHtml(metric.label)}</strong><small>${escHtml(metric.detail)}</small></td><td><b>${escHtml(metric.current)}</b></td><td>${escHtml(metric.seven)}</td><td>${escHtml(metric.thirty)}</td><td>${escHtml(`${metric.format(min)} / ${metric.format(max)}`)}</td><td>${_berichtSparkline(metric.values.slice(-30), metric.color, metric.label)}</td></tr>`;
  }).join('');
}

function _average(values) {
  const valid = values.map(Number).filter((value) => Number.isFinite(value) && value > 0);
  return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : 0;
}

function _fmtDeltaAgainst(current, previous) {
  if (!Number(current) || !Number(previous)) return '—';
  return _fmtDelta(Number(current) - Number(previous));
}

function _fmtDurationDelta(current, average) {
  if (!Number(current) || !Number(average)) return '—';
  const delta = Number(current) - Number(average);
  return `${delta >= 0 ? '+' : '-'}${_fmtDuration(Math.abs(delta))}`;
}

function _berichtSparkline(values, color, label) {
  const points = values.map(Number).filter((value) => Number.isFinite(value) && value > 0);
  if (points.length < 2) return `<span>${escHtml(reportsT('noData'))}</span>`;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const coordinates = points.map((value, index) => `${4 + index * (172 / (points.length - 1))},${31 - ((value - min) / range) * 25}`).join(' ');
  const lastY = 31 - ((points[points.length - 1] - min) / range) * 25;
  return `<svg class="report-sparkline" viewBox="0 0 180 36" role="img" aria-label="${escHtml(reportsT('trendFor', { metric: label }))}"><polyline points="${coordinates}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/><circle cx="176" cy="${lastY}" r="3" fill="${color}"/></svg>`;
}

function _berichtStatusTable(monthly) {
  const body = document.getElementById('bericht-status-body');
  if (!body) return;
  const rows = Array.isArray(monthly) ? [...monthly].reverse() : [];
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="7">${escHtml(reportsT('noData'))}</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((month) => {
    const success = Number(month.success || 0);
    const warning = Number(month.warning || 0);
    const error = Number(month.error || 0);
    const total = success + warning + error;
    const rate = total ? Math.round(success / total * 100) : 0;
    const label = _reportMonthLabel(month.month);
    return `<tr><td><strong>${escHtml(label)}</strong></td><td>${total}</td><td class="report-value-success">${success}</td><td class="report-value-warning">${warning}</td><td class="report-value-error">${error}</td><td><div class="report-status-distribution" aria-label="${escHtml(reportsT('distributionLabel', { success, warning, error }))}"><span class="success" style="width:${total ? success / total * 100 : 0}%"></span><span class="warning" style="width:${total ? warning / total * 100 : 0}%"></span><span class="error" style="width:${total ? error / total * 100 : 0}%"></span></div></td><td>${rate}%</td></tr>`;
  }).join('');
}

function _reportMonthLabel(value) {
  const match = /^(\d{4})-(\d{2})$/.exec(String(value || ''));
  if (!match) return value || '—';
  return new Intl.DateTimeFormat(window.BBUI?.components?.i18n?.getLanguage?.() === 'en' ? 'en-US' : 'de-DE', { month: 'long', year: 'numeric' }).format(new Date(Number(match[1]), Number(match[2]) - 1, 1));
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
  const daysHint = gAvgDays > 0 ? reportsT('sinceDays', { days: gAvgDays }) : reportsT('sinceUnknownDays');
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
    const main = gAvg == null ? '—' : reportsT('perDay', { value: _fmtDelta(gAvg) });
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
      reportsT('tooltipDate', { value: r.date || '—' }),
      reportsT('tooltipRepoSize', { value: _fmtBytes(r.repository_size || 0) }),
      reportsT('tooltipPreviousDayDelta', { value: _fmtDelta(dDay) }),
      reportsT('tooltipPreviousWeekDelta', { value: _fmtDelta(dWeek) }),
      reportsT('tooltipStatus', { value: _reportStatusLabel(r.status) })
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
      reportsT('tooltipDate', { value: r.date || '—' }),
      reportsT('tooltipDuration', { value: _fmtDuration(r.duration_seconds || 0) }),
      reportsT('tooltipPreviousDayDelta', { value: dDay == null ? '—' : _fmtDuration(Math.abs(dDay)) })
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
      reportsT('tooltipDate', { value: r.date || '—' }),
      reportsT('tooltipNewData', { value: _fmtBytes(r.deduplicated_size || 0) }),
      reportsT('tooltipPreviousDayDelta', { value: _fmtDelta(dDay) })
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
      reportsT('tooltipMonth', { value: m.month || '—' }),
      reportsT('tooltipSuccess', { value: m.success || 0 }),
      reportsT('tooltipWarning', { value: m.warning || 0 }),
      reportsT('tooltipError', { value: m.error || 0 }),
      reportsT('tooltipTotal', { value: total || 0 })
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
  return `<div style="color:var(--text-muted);padding:20px 0;text-align:center;font-size:13px">${escHtml(reportsT('noData'))}</div>`;
}

function _fmtBytes(b) {
  if (!b) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (b >= 1024 && i < units.length - 1) { b /= 1024; i++; }
  const locale = window.BBUI?.components?.i18n?.getLanguage?.() === 'en' ? 'en-US' : 'de-DE';
  return Number(b).toLocaleString(locale, {
    minimumFractionDigits: i > 0 ? 1 : 0,
    maximumFractionDigits: i > 0 ? 1 : 0,
  }) + '\u00a0' + units[i];
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
    verified: { cls: 'success-state', text: reportsT('restoreVerified') },
    stale: { cls: 'warning-state', text: reportsT('restoreOverdue') },
    failed: { cls: 'error-state', text: reportsT('restoreFailed') },
    never: { cls: 'warning-state', text: reportsT('restorePending') },
    not_required: { cls: 'empty-state', text: reportsT('restoreNotScheduled') },
  };
  const item = map[status] || map.never;
  const details = [
    job.restore_verification_last_test_date ? reportsT('lastTest', { value: job.restore_verification_last_test_date }) : '',
    job.restore_verification_valid_until ? reportsT('validUntil', { value: job.restore_verification_valid_until }) : '',
  ].filter(Boolean).join(' · ');
  el.className = `status-message ${item.cls}`;
  el.textContent = details ? `${item.text} · ${details}` : item.text;
}

async function berichtLoadBorgInfo() {
  const jobKey = document.getElementById('bericht-job-sel').value;
  if (!jobKey) return;
  const btn = document.getElementById('bericht-borginfo-btn');
  btn.disabled = true;
  btn.textContent = reportsT('loadingShort');
  _berichtBorgInfoMsg(reportsT('queryingBorgInfo'));
  document.getElementById('bericht-borginfo-cards').style.display = 'none';
  try {
    const res = await fetch(`/api/restore/repo-stats?job=${encodeURIComponent(jobKey)}`);
    const data = await res.json();
    if (!res.ok || data.error) { _berichtBorgInfoMsg(reportsT('error', { message: apiErrorMessage(data, res.status) }), true); btn.disabled = false; btn.textContent = reportsT('load'); return; }
    reportState.borgInfo = data;
    reportState.borgInfoLoaded = true;
    _berichtBorgInfoMsg('');
    _berichtRenderBorgInfo(data);
    btn.textContent = reportsT('refresh');
    btn.disabled = false;
  } catch (e) {
    _berichtBorgInfoMsg(reportsT('error', { message: e.message }), true);
    btn.disabled = false;
    btn.textContent = reportsT('load');
  }
}

function _berichtRenderBorgInfo(data) {
  if (!data) return;
  const savings = data.total_size > 0
    ? Math.round((1 - data.unique_csize / data.total_size) * 100) + '%'
    : '—';
  document.getElementById('bi-total-size').textContent = _fmtBytes(data.total_size);
  document.getElementById('bi-csize').textContent = _fmtBytes(data.total_csize);
  document.getElementById('bi-unique').textContent = _fmtBytes(data.unique_csize);
  document.getElementById('bi-savings').textContent = savings;
  document.getElementById('bi-count').textContent = data.archive_count;
  document.getElementById('bericht-borginfo-cards').style.display = '';
}

function _reportStatusLabel(status) {
  return {
    success: reportsT('statusSuccess'),
    warning: reportsT('statusWarning'),
    skipped: reportsT('statusSkipped'),
    error: reportsT('statusError'),
    unknown: reportsT('statusUnknown'),
  }[String(status || '').toLowerCase()] || status || reportsT('statusUnknown');
}

window.addEventListener?.('bbui:language-changed', () => {
  const selectPlaceholder = document.querySelector('#bericht-job-sel option[value=""]');
  if (selectPlaceholder) selectPlaceholder.textContent = reportsT('selectJob');
  if (reportState.data) {
    _berichtRender(reportState.data);
    _berichtRestoreVerification(reportState.job);
    if (reportState.borgInfoLoaded) _berichtRenderBorgInfo(reportState.borgInfo);
  }
  const button = document.getElementById('bericht-borginfo-btn');
  if (button) button.textContent = reportState.borgInfoLoaded ? reportsT('refresh') : reportsT('load');
  _berichtRenderJobSidebar();
  _berichtUpdateSelection(reportState.job);
});

function _berichtBorgInfoMsg(msg, isError) {
  const el = document.getElementById('bericht-borginfo-msg');
  if (!el) return;
  if (!msg) { el.classList.add('hidden'); el.textContent = ''; return; }
  el.classList.remove('hidden');
  el.textContent = msg;
  el.style.color = isError ? 'var(--danger)' : 'var(--text-muted)';
}
