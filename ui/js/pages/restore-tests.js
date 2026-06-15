// ══════════════════════════════════════════════════════════════════════════════
// RESTORE TESTS PAGE
// ══════════════════════════════════════════════════════════════════════════════

window.BBUI = window.BBUI || {};
window.BBUI.restoreTestsState = window.BBUI.restoreTestsState || {
  loaded: false,
  data: null,
  plan: null,
  pollingTimer: null,
  activeEventSource: null,
  jobs: [],
  defaultsInitialized: false,
  rowBusy: {},
  rowNote: {},
  subtab: 'plan',
  filteredReports: [],
};
const restoreTestsState = window.BBUI.restoreTestsState;

function _updateRTScheduleBtn() {
  // Schedule icon removed in consolidated UI.
}

function showRestoreTestScheduleModal() {
  // Schedule icon removed in consolidated UI.
}

function _openRTStartConfirmModal(summaryText) {
  return new Promise((resolve) => {
    const modal = document.getElementById('confirm-modal');
    const titleEl = document.getElementById('modal-title');
    const descEl = document.getElementById('modal-description');
    const infoEl = document.getElementById('modal-info');
    const btn = document.getElementById('modal-confirm-btn');
    const closeBtn = document.getElementById('confirm-modal-close-btn');
    const cancelBtn = document.getElementById('confirm-modal-cancel-btn');
    const inputWrap = document.getElementById('modal-confirm-input-wrap');
    const passWrap = document.getElementById('modal-passphrase-delete-wrap');

    if (!modal || !titleEl || !descEl || !infoEl || !btn || !closeBtn || !cancelBtn) {
      resolve(window.confirm(`Restore-Test jetzt starten?\n\n${summaryText}`));
      return;
    }

    if (inputWrap) inputWrap.classList.add('hidden');
    if (passWrap) passWrap.classList.add('hidden');
    titleEl.textContent = 'Restore-Test starten';
    descEl.textContent = 'Die Testausführung wird jetzt gestartet.';
    infoEl.innerHTML = '<div class="modal-info-item info"><span class="modal-info-text" id="rt-confirm-summary-text"></span></div>';
    const summaryEl = document.getElementById('rt-confirm-summary-text');
    if (summaryEl) {
      summaryEl.textContent = String(summaryText || '');
      summaryEl.style.whiteSpace = 'pre-line';
    }
    btn.className = 'btn btn-primary';
    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><polygon points="5 3 19 12 5 21 5 3"/></svg> Test starten`;
    btn.disabled = false;

    const prevConfirm = btn.onclick;
    const prevClose = closeBtn.onclick;
    const prevCancel = cancelBtn.onclick;
    let done = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      btn.onclick = prevConfirm;
      closeBtn.onclick = prevClose;
      cancelBtn.onclick = prevCancel;
      closeModal();
      resolve(!!ok);
    };

    btn.onclick = () => finish(true);
    closeBtn.onclick = () => finish(false);
    cancelBtn.onclick = () => finish(false);
    modal.classList.remove('hidden');
  });
}

async function runRestoreTestNow() {
  const summary = [
    'Es werden alle fälligen Jobs mit Policy "Geplant" ausgeführt.',
    'Level/Intervall kommen pro Job aus der jeweiligen Policy.',
  ].join('\n');
  if (!await _openRTStartConfirmModal(summary)) {
    return;
  }

  const btn = document.getElementById('rt-run-btn');
  if (btn) btn.classList.add('loading');
  try {
    const res = await fetch('/api/restore-tests/run', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scheduled: true,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    if (data.started === false && data.reason === 'no_due_jobs') {
      showMsg(
        'restore-tests-message',
        'info',
        'Keine fälligen geplanten Restore-Tests. Intervall/Plan noch nicht erreicht. Du kannst einzelne Jobs in „Planung & Policy pro Job“ über „Jetzt testen“ manuell starten.'
      );
      await refreshRestorePlanOnly();
      return;
    }
    _openRTLogPanel();
    startRTPolling();
    await refreshRestorePlanOnly();
  } catch (err) {
    showMsg('restore-tests-message', 'error', `Fehler: ${err.message}`);
  } finally {
    if (btn) btn.classList.remove('loading');
  }
}

function _openRTLogPanel() {
  const panel = document.getElementById('rt-log-panel');
  const output = document.getElementById('rt-log-output');
  if (!panel || !output) return;
  output.textContent = '';
  panel.classList.remove('hidden');
  setRTLogStatus('running', null);

  if (restoreTestsState.activeEventSource) {
    restoreTestsState.activeEventSource.close();
  }
  const es = new EventSource('/api/restore-tests/log/stream');
  restoreTestsState.activeEventSource = es;

  es.onmessage = (e) => {
    output.textContent += e.data + '\n';
    output.scrollTop = output.scrollHeight;
  };
  es.addEventListener('done', (e) => {
    const code = parseInt(e.data);
    setRTLogStatus(code === 0 ? 'success' : 'error', code);
    es.close();
    restoreTestsState.activeEventSource = null;
    stopRTPolling();
    refreshRestoreTests();
  });
  es.onerror = () => {
    setRTLogStatus('error', -1);
    es.close();
    restoreTestsState.activeEventSource = null;
    stopRTPolling();
  };
}

function setRTLogStatus(state, exitCode) {
  const badge = document.getElementById('rt-log-status-badge');
  if (!badge) return;
  const exit = String(exitCode ?? '');
  if (state === 'running') {
    badge.className = 'badge';
    badge.textContent = '';
    const dot = document.createElement('span');
    dot.className = 'running-dot';
    dot.style.marginRight = '4px';
    badge.append(dot, document.createTextNode('Läuft...'));
  } else if (state === 'success') {
    badge.className = 'badge success';
    badge.textContent = '';
    const dot = document.createElement('span');
    dot.className = 'badge-dot';
    badge.append(dot, document.createTextNode(`Fertig (Exit ${exit})`));
  } else {
    badge.className = 'badge error';
    badge.textContent = '';
    const dot = document.createElement('span');
    dot.className = 'badge-dot';
    badge.append(dot, document.createTextNode(`Fehler (Exit ${exit})`));
  }
}

function closeRTLogPanel() {
  const panel = document.getElementById('rt-log-panel');
  if (panel) panel.classList.add('hidden');
  if (restoreTestsState.activeEventSource) {
    restoreTestsState.activeEventSource.close();
    restoreTestsState.activeEventSource = null;
  }
}

function startRTPolling() {
  if (restoreTestsState.pollingTimer) return;
  restoreTestsState.pollingTimer = setInterval(_pollRTRunning, 10000);
}

function stopRTPolling() {
  if (restoreTestsState.pollingTimer) {
    clearInterval(restoreTestsState.pollingTimer);
    restoreTestsState.pollingTimer = null;
  }
}

async function _pollRTRunning() {
  try {
    const res = await fetch('/api/restore-tests/running');
    if (!res.ok) return;
    const state = await res.json();
    if (!state.running && restoreTestsState.pollingTimer) {
      stopRTPolling();
    }
  } catch (_) {}
}

async function refreshRestoreTests() {
  const btn = document.getElementById('restore-tests-refresh-btn');
  if (btn) btn.classList.add('loading');
  try {
    const [testsRes, planRes, schedsRes, settingsRes] = await Promise.all([
      fetch('/api/restore-tests'),
      fetch('/api/restore-tests/plan'),
      fetch('/api/schedules'),
      fetch('/api/settings/basic'),
    ]);
    if (!testsRes.ok) throw new Error(`HTTP ${testsRes.status}`);
    const testsData = await testsRes.json();
    if (schedsRes.ok) {
      const sData = await schedsRes.json();
      const schedules = window.BBUI.core.getSchedulesData();
      Object.assign(schedules, sData);
      window.BBUI.core.setSchedulesData(schedules);
    }
    if (settingsRes.ok && !restoreTestsState.defaultsInitialized) {
      restoreTestsState.defaultsInitialized = true;
    }
    restoreTestsState.data = testsData.tests || [];
    restoreTestsState.plan = planRes.ok ? await planRes.json() : null;
    restoreTestsState.loaded = true;
    renderRestorePlan(restoreTestsState.plan);
    renderRTReportFilterOptions(restoreTestsState.data);
    renderRestoreTests(restoreTestsState.data);
    renderRestoreTestsSubtab();
    _updateRTScheduleBtn();
    await refreshRestoreTestJobOptions();
  } catch (err) {
    showMsg('restore-tests-message', 'error', `Fehler: ${err.message}`);
  } finally {
    if (btn) btn.classList.remove('loading');
  }
}

function switchRestoreTestsSubtab(tab) {
  restoreTestsState.subtab = tab === 'reports' ? 'reports' : 'plan';
  renderRestoreTestsSubtab();
}

function renderRestoreTestsSubtab() {
  const isReports = restoreTestsState.subtab === 'reports';
  const planCard = document.getElementById('restore-tests-plan');
  const reportsCard = document.getElementById('restore-tests-reports');
  const planBtn = document.getElementById('rt-subtab-plan-btn');
  const reportsBtn = document.getElementById('rt-subtab-reports-btn');
  const hint = document.querySelector('#page-restore-tests .restore-tests-hint');
  if (planCard) planCard.classList.toggle('hidden', isReports);
  if (reportsCard) reportsCard.classList.toggle('hidden', !isReports);
  if (hint) hint.classList.toggle('hidden', isReports);
  if (planBtn) planBtn.classList.toggle('active', !isReports);
  if (reportsBtn) reportsBtn.classList.toggle('active', isReports);
}

function renderRestorePlan(plan) {
  const summaryEl = document.getElementById('restore-tests-plan-summary');
  const contentEl = document.getElementById('restore-tests-plan-content');
  if (!summaryEl || !contentEl) return;
  if (!plan || !Array.isArray(plan.jobs)) {
    summaryEl.textContent = 'Plan nicht verfügbar.';
    contentEl.innerHTML = '<div class="status-message warning">Plan konnte nicht geladen werden.</div>';
    return;
  }
  const s = plan.summary || {};
  summaryEl.textContent = `Gesamt: ${s.total || 0} · Geplant: ${s.scheduled || 0} · Manuell: ${s.manual_only || 0} · Nicht geplant: ${s.off || 0} · Überfällig: ${s.overdue || 0}`;
  const locOrder = { local: 1, usb: 2, smb: 3, storagebox: 4, custom: 5 };
  const sortedJobs = [...plan.jobs].sort((a, b) => {
    const la = String(a?.location || '').toLowerCase();
    const lb = String(b?.location || '').toLowerCase();
    const oa = locOrder[la] || 99;
    const ob = locOrder[lb] || 99;
    if (oa !== ob) return oa - ob;
    const na = String(a?.display_name || a?.job_key || '').toLowerCase();
    const nb = String(b?.display_name || b?.job_key || '').toLowerCase();
    return na.localeCompare(nb, 'de');
  });
  const rows = sortedJobs.map((j) => {
    const p = j.policy || {};
    const mode = String(p.mode || 'off');
    const interval = Number(p.interval_days || plan.defaults?.interval_days || 30);
    const level = Number(p.level || plan.defaults?.level || 2);
    const disabled = j.enabled === false ? 'disabled' : '';
    const due = j.next_due_at || (j.is_overdue ? 'fällig' : '—');
    const schedState = mode !== 'scheduled'
      ? 'Nein'
      : (j.is_overdue ? 'Ja (fällig)' : 'Ja (wartet)');
    const busy = !!restoreTestsState.rowBusy[j.job_key];
    const note = restoreTestsState.rowNote[j.job_key] || '';
    return `<tr>
      <td>${escHtml(j.display_name || j.job_key || '-')}</td>
      <td><span class="history-loc-chip ${(j.location || '').toLowerCase()}">${escHtml(locLabel(j.location || ''))}</span></td>
      <td>
        <select class="form-select" data-rt-plan-input="mode" data-job-key="${escHtml(j.job_key)}" style="min-width:130px" ${disabled}>
          <option value="scheduled" ${mode === 'scheduled' ? 'selected' : ''}>Geplant</option>
          <option value="manual_only" ${mode === 'manual_only' ? 'selected' : ''}>Nur manuell</option>
          <option value="off" ${mode === 'off' ? 'selected' : ''}>Nicht geplant</option>
        </select>
      </td>
      <td><input type="number" min="1" class="form-input" data-rt-plan-input="interval_days" data-job-key="${escHtml(j.job_key)}" value="${interval}" style="width:88px" ${disabled}></td>
      <td>
        <select class="form-select" data-rt-plan-input="level" data-job-key="${escHtml(j.job_key)}" style="min-width:78px" ${disabled}>
          <option value="1" ${level === 1 ? 'selected' : ''}>L1</option>
          <option value="2" ${level === 2 ? 'selected' : ''}>L2</option>
          <option value="3" ${level === 3 ? 'selected' : ''}>L3</option>
        </select>
      </td>
      <td>${escHtml(j.last_test_date || '—')}</td>
      <td>${escHtml(due)}</td>
      <td>${escHtml(schedState)}</td>
      <td>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button type="button" class="btn btn-secondary btn-sm ${busy ? 'loading' : ''}" data-rt-plan-action="save" data-job-key="${escHtml(j.job_key)}" ${disabled} ${busy ? 'disabled' : ''}>Speichern</button>
          <button type="button" class="btn btn-primary btn-sm ${busy ? 'loading' : ''}" data-rt-plan-action="run" data-job-key="${escHtml(j.job_key)}" ${disabled} ${busy ? 'disabled' : ''}>Jetzt testen</button>
          ${note ? `<span class="muted" style="font-size:11px">${escHtml(note)}</span>` : ''}
        </div>
      </td>
    </tr>`;
  }).join('');
  contentEl.innerHTML = `
    <table class="history-table">
      <thead><tr><th>Job</th><th>Ort</th><th>Policy</th><th>Intervall (Tage)</th><th>Level</th><th>Letzter Test</th><th>Nächster Test</th><th>Scheduler</th><th>Aktionen</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="9">Keine Jobs gefunden.</td></tr>'}</tbody>
    </table>`;
}

function _getPlanInput(jobKey, field) {
  return document.querySelector(`[data-rt-plan-input="${field}"][data-job-key="${CSS.escape(jobKey)}"]`);
}

async function saveRestorePlanPolicy(jobKey) {
  const modeEl = _getPlanInput(jobKey, 'mode');
  const intervalEl = _getPlanInput(jobKey, 'interval_days');
  const levelEl = _getPlanInput(jobKey, 'level');
  if (!modeEl || !intervalEl || !levelEl) return;
  const interval = Number(intervalEl.value || 30);
  const level = Number(levelEl.value || 2);
  if (!Number.isFinite(interval) || interval < 1) {
    showMsg('restore-tests-message', 'error', `Intervall ungültig (Job ${jobKey}). Mindestwert: 1`);
    return;
  }
  if (![1, 2, 3].includes(level)) {
    showMsg('restore-tests-message', 'error', `Level ungültig (Job ${jobKey}). Erlaubt: 1,2,3`);
    return;
  }
  restoreTestsState.rowBusy[jobKey] = true;
  restoreTestsState.rowNote[jobKey] = 'Speichern...';
  renderRestorePlan(restoreTestsState.plan);
  try {
    const res = await fetch('/api/restore-tests/policy', {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_key: jobKey,
        policy: { mode: modeEl.value, interval_days: Math.trunc(interval), validity_days: Math.trunc(interval), level, max_runtime_minutes: 0 },
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    const stamp = new Date().toLocaleTimeString('de-DE');
    restoreTestsState.rowNote[jobKey] = `Gespeichert um ${stamp}`;
    showMsg('restore-tests-message', 'success', `Policy gespeichert: ${jobKey}`);
    await refreshRestorePlanOnly();
  } catch (err) {
    restoreTestsState.rowNote[jobKey] = `Fehler: ${err.message}`;
    showMsg('restore-tests-message', 'error', `Policy speichern fehlgeschlagen: ${err.message}`);
  } finally {
    restoreTestsState.rowBusy[jobKey] = false;
    renderRestorePlan(restoreTestsState.plan);
  }
}

async function runRestorePlanJob(jobKey) {
  restoreTestsState.rowBusy[jobKey] = true;
  restoreTestsState.rowNote[jobKey] = 'Starte Test...';
  renderRestorePlan(restoreTestsState.plan);
  try {
    const res = await fetch('/api/restore-tests/run-job', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_key: jobKey }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    const stamp = new Date().toLocaleTimeString('de-DE');
    restoreTestsState.rowNote[jobKey] = `Gestartet um ${stamp}`;
    showMsg('restore-tests-message', 'success', `Restore-Test gestartet: ${jobKey}`);
    _openRTLogPanel();
    startRTPolling();
    await refreshRestorePlanOnly();
  } catch (err) {
    restoreTestsState.rowNote[jobKey] = `Fehler: ${err.message}`;
    showMsg('restore-tests-message', 'error', `Start fehlgeschlagen: ${err.message}`);
  } finally {
    restoreTestsState.rowBusy[jobKey] = false;
    renderRestorePlan(restoreTestsState.plan);
  }
}

function onRestoreTestsPlanClick(event) {
  const btn = event.target.closest('[data-rt-plan-action]');
  if (!btn) return;
  event.preventDefault();
  event.stopPropagation();
  const action = btn.dataset.rtPlanAction || '';
  const jobKey = btn.dataset.jobKey || '';
  if (!jobKey) return;
  if (action === 'save') return saveRestorePlanPolicy(jobKey);
  if (action === 'run') return runRestorePlanJob(jobKey);
}

async function refreshRestorePlanOnly() {
  try {
    const [planRes, runningRes] = await Promise.all([
      fetch('/api/restore-tests/plan', { credentials: 'include' }),
      fetch('/api/restore-tests/running', { credentials: 'include' }),
    ]);
    if (planRes.ok) {
      restoreTestsState.plan = await planRes.json();
      renderRestorePlan(restoreTestsState.plan);
    }
    if (runningRes.ok) {
      const running = await runningRes.json();
      if (running?.running) startRTPolling();
    }
  } catch (_) {}
}

async function refreshRestoreTestJobOptions() {
  try {
    const res = await fetch('/api/jobs');
    if (!res.ok) return;
    const data = await res.json();
    restoreTestsState.jobs = (data.jobs || []).filter(j => j.enabled !== false);
    refreshRestoreTestJobsForSelection();
  } catch (_) {}
}

function refreshRestoreTestJobsForSelection() {
  const wrap = document.getElementById('rt-job-selector-wrap');
  const list = document.getElementById('rt-job-selector-list');
  const location = document.getElementById('rt-location-select')?.value || 'all';
  const selectAll = document.getElementById('rt-select-all-jobs')?.checked ?? true;
  if (!wrap || !list) return;
  wrap.classList.toggle('hidden', selectAll);
  if (selectAll) return;

  const rows = (restoreTestsState.jobs || [])
    .filter(j => location === 'all' || String(j.location || '').toLowerCase() === location)
    .sort((a, b) => String(a.display_name || a.name || a.key).localeCompare(String(b.display_name || b.name || b.key)));

  if (!rows.length) {
    list.innerHTML = '<span class="muted">Keine Jobs für Auswahl gefunden.</span>';
    return;
  }

  list.innerHTML = rows.map((j) => `
    <label class="form-checkbox-row" style="display:inline-flex;margin-right:12px">
      <input type="checkbox" class="rt-job-checkbox" value="${escHtml(j.key || '')}">
      ${(escHtml(j.display_name || j.name || j.key || '') || '-')}
    </label>
  `).join('');
}

function toggleRestoreTestJobSelectionMode() {
  refreshRestoreTestJobsForSelection();
}

function renderRestoreTests(tests) {
  const summaryEl = document.getElementById('restore-tests-summary');
  const contentEl = document.getElementById('restore-tests-content');
  if (!summaryEl || !contentEl) return;
  const list = Array.isArray(tests) ? tests : [];
  const filtered = _getFilteredRTReports(list);
  const stale = filtered.filter(t => t.test_result === 'success' && isStaleDate(t.test_date)).length;
  const ok = filtered.filter(t => t.test_result === 'success' && !isStaleDate(t.test_date)).length;
  const failed = filtered.filter(t => t.test_result === 'failed').length;
  const unavail = filtered.filter(t => t.test_result === 'unavailable').length;
  summaryEl.innerHTML = `
    <div class="stat-tile total"><div><div class="stat-value">${filtered.length}</div><div class="stat-label">Berichte</div></div></div>
    <div class="stat-tile success"><div><div class="stat-value">${ok}</div><div class="stat-label">Verifiziert</div></div></div>
    <div class="stat-tile warning"><div><div class="stat-value">${stale}</div><div class="stat-label">Überfällig</div></div></div>
    <div class="stat-tile error"><div><div class="stat-value">${failed + unavail}</div><div class="stat-label">Problematisch</div></div></div>`;
  summaryEl.classList.remove('hidden');

  if (!filtered.length) {
    contentEl.innerHTML = `<div class="status-message empty-state">Keine Prüfberichte für den aktuellen Filter gefunden.</div>`;
    return;
  }
  const rows = filtered.map((t, i) => renderRTReportRow(t, i)).join('');
  contentEl.innerHTML = `
    <table class="history-table restore-tests-table">
      <thead><tr><th></th><th>Datum / Zeit</th><th>Typ</th><th>Job</th><th>Ort</th><th>Dauer</th><th>Originalgröße</th><th>Abdeckung</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  restoreTestsState.filteredReports = filtered;
}

function _rtStatus(t) {
  if (t.test_result === 'success' && isStaleDate(t.test_date)) return { className: 'warning', label: 'Überfällig' };
  if (t.test_result === 'success') return { className: 'success', label: 'Verifiziert' };
  if (t.test_result === 'failed') return { className: 'error', label: 'Fehlgeschlagen' };
  return { className: 'warning', label: 'Nicht verfügbar' };
}

function _rtTs(test) {
  const raw = String(test?.test_date || '').trim();
  if (!raw) return 0;
  const iso = raw.includes('T') ? raw : raw.replace(' ', 'T');
  const ms = Date.parse(iso.endsWith('Z') ? iso : `${iso}Z`);
  return Number.isFinite(ms) ? ms : 0;
}

function _getFilteredRTReports(tests) {
  const jobNeedle = String(document.getElementById('rt-report-filter-job')?.value || '').trim().toLowerCase();
  const location = String(document.getElementById('rt-report-filter-location')?.value || 'all').toLowerCase();
  const status = String(document.getElementById('rt-report-filter-status')?.value || 'all');
  const range = String(document.getElementById('rt-report-filter-range')?.value || 'all');
  const problemOnly = !!document.getElementById('rt-report-filter-problem')?.checked;
  const now = Date.now();
  const rangeDays = Number(range || 0);
  const filtered = [...tests].filter((t) => {
    const key = String(t.job_key || t.type || '').toLowerCase();
    if (jobNeedle && !key.includes(jobNeedle)) return false;
    if (location !== 'all' && String(t.location || '').toLowerCase() !== location) return false;
    const stale = t.test_result === 'success' && isStaleDate(t.test_date);
    if (status === 'success' && !(t.test_result === 'success' && !stale)) return false;
    if (status === 'failed' && t.test_result !== 'failed') return false;
    if (status === 'unavailable' && t.test_result !== 'unavailable') return false;
    if (status === 'stale' && !stale) return false;
    if (problemOnly && !(t.test_result === 'failed' || t.test_result === 'unavailable' || stale)) return false;
    if (range !== 'all' && rangeDays > 0) {
      const ts = _rtTs(t);
      if (!ts) return false;
      if (ts < (now - rangeDays * 86400000)) return false;
    }
    return true;
  });
  filtered.sort((a, b) => _rtTs(b) - _rtTs(a));
  return filtered;
}

function _rtRuntimeBand(durationSeconds, durationFormatted) {
  let sec = Number(durationSeconds || 0);
  if (!Number.isFinite(sec) || sec <= 0) {
    const text = String(durationFormatted || '').toLowerCase();
    const m = text.match(/(\d+)\s*h/);
    if (m) sec += Number(m[1]) * 3600;
    const mm = text.match(/(\d+)\s*m/);
    if (mm) sec += Number(mm[1]) * 60;
    const ss = text.match(/(\d+)\s*s/);
    if (ss) sec += Number(ss[1]);
  }
  if (sec >= 3600) return { label: 'lang', short: 'lang', cls: 'long' };
  if (sec >= 900) return { label: 'mittel', short: 'mittel', cls: 'medium' };
  return { label: 'kurz', short: 'kurz', cls: 'short' };
}

function formatCoveragePercent(value) {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return '0,0%';
  return `${n.toFixed(1).replace('.', ',')}%`;
}

function toggleRTDetail(detailId, row) {
  const detail = document.getElementById(detailId);
  const idx    = detailId.replace('rtd-', '');
  const chev   = document.getElementById(`rtchev-${idx}`);
  if (!detail) return;
  const open = detail.style.display !== 'none';
  detail.style.display = open ? 'none' : 'table-row';
  row?.classList.toggle('history-expanded', !open);
  chev?.classList.toggle('open', !open);
}

function toggleRTEntries(headerEl) {
  const body = headerEl.nextElementSibling;
  const chev = headerEl.querySelector('.history-chevron');
  if (!body) return;
  const open = body.style.display !== 'none';
  body.style.display = open ? 'none' : 'block';
  chev?.classList.toggle('open', !open);
}

function onRestoreTestsContentClick(event) {
  const el = event.target.closest('[data-rt-action]');
  if (!el) return;
  const action = el.dataset.rtAction || '';
  if (action === 'toggle-detail') {
    const rowId = el.dataset.rowId || '';
    const detailId = el.dataset.detailId || '';
    return toggleRTDetailById(rowId, detailId);
  }
  if (action === 'toggle-entries') {
    return toggleRTEntries(el);
  }
}

function onRTReportFilterChange() {
  renderRestoreTests(restoreTestsState.data || []);
}

function renderRTReportFilterOptions(tests) {
  const locationEl = document.getElementById('rt-report-filter-location');
  if (!locationEl) return;
  const current = locationEl.value || 'all';
  const locations = Array.from(new Set((tests || []).map((t) => String(t.location || '').toLowerCase()).filter(Boolean))).sort();
  locationEl.innerHTML = '<option value="all">Alle Standorte</option>'
    + locations.map((loc) => `<option value="${escHtml(loc)}">${escHtml(locLabel(loc))}</option>`).join('');
  locationEl.value = locations.includes(current) || current === 'all' ? current : 'all';
}

function toggleRTDetailById(rowId, detailId) {
  const detail = document.getElementById(detailId);
  const row = document.getElementById(rowId);
  const idx = detailId.replace('rtd-', '');
  const chev = document.getElementById(`rtchev-${idx}`);
  if (!detail) return;
  const open = detail.style.display !== 'none';
  detail.style.display = open ? 'none' : 'table-row';
  row?.classList.toggle('history-expanded', !open);
  chev?.classList.toggle('open', !open);
}

function renderRTReportRow(t, idx) {
  const rowId = `rtr-${idx}`;
  const detailId = `rtd-${idx}`;
  const status = _rtStatus(t);
  const cov = Number(t.test_coverage_percentage || 0);
  const covTxt = Number.isFinite(cov) ? `${cov.toFixed(1).replace('.', ',')}%` : '0,0%';
  const stats = t.archive_stats_formatted || {};
  const detailError = t.failure_hint || t.error_message || t.error || '';
  const dt = String(t.test_date || '—');
  const reportId = t.report_id || t.test_id;
  const archive = t.tested_archive || t.archive_name;
  const location = locLabel(t.location || '');
  return `
    <tr id="${rowId}" class="history-row history-restore-row" data-rt-action="toggle-detail" data-row-id="${rowId}" data-detail-id="${detailId}">
      <td><svg class="history-chevron" id="rtchev-${idx}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14"><polyline points="9 18 15 12 9 6"/></svg></td>
      <td style="white-space:nowrap;color:var(--text-primary)">${escHtml(dt)}</td>
      <td><span class="history-type-badge">RESTORE TEST</span></td>
      <td style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px">${escHtml(t.job_key || t.type || '-')}</td>
      <td><span class="history-loc-chip ${(t.location || '').toLowerCase()}">${escHtml(locLabel(t.location || ''))}</span></td>
      <td>${escHtml(t.duration_formatted || '—')}</td>
      <td>${escHtml(stats.original || '—')}</td>
      <td>${escHtml(covTxt)}</td>
      <td><span class="history-status-badge ${status.className}">${escHtml(status.className === 'success' ? 'Erfolgreich' : status.label)}</span></td>
    </tr>
    <tr id="${detailId}" class="history-detail-row" style="display:none">
      <td colspan="9">
        <div class="rt-report-card">
          <div class="rt-report-card-head">
            <div>
              <div class="rt-report-kicker">Prüfbericht</div>
              <div class="rt-report-title">${escHtml(t.job_key || t.type || 'Restore Test')}</div>
              <div class="rt-report-subtitle">${escHtml(archive || 'Kein Archiv angegeben')}</div>
            </div>
            <div class="rt-report-actions">
              <span class="history-status-badge ${status.className}">${escHtml(status.className === 'success' ? 'Erfolgreich' : status.label)}</span>
            </div>
          </div>
          ${detailError ? `<div class="rt-report-alert">Fehler: ${escHtml(detailError)}</div>` : ''}
          <div class="rt-report-meta-grid">
            ${rtReportMetaItem('Report-ID', reportId, true)}
            ${rtReportMetaItem('Standort', location)}
            ${rtReportMetaItem('Level', t.test_level != null ? `L${t.test_level}` : null)}
            ${rtReportMetaItem('Start', t.start_ts || t.started_at)}
            ${rtReportMetaItem('Ende', t.end_ts || t.finished_at || t.test_date)}
            ${rtReportMetaItem('Dauer', t.duration_formatted || '—')}
            ${rtReportMetaItem('Originalgröße', stats.original || '—')}
            ${rtReportMetaItem('Abdeckung', `${covTxt}${t.coverage_basis ? ` (${t.coverage_basis})` : ''}`)}
            ${rtReportMetaItem('Gesamtstatus', t.overall_status || status.label)}
            ${rtReportMetaItem('Gültig bis', t.valid_until || t.valid_until_date)}
            ${rtReportMetaItem('Fehlercode', t.failure_code)}
          </div>
          ${renderRTStepsTable(t.steps || [], t)}
        </div>
      </td>
    </tr>`;
}

function detailGroupRT(label, value) {
  if (value == null || value === '') return '';
  return `<div class="history-detail-group"><div class="history-detail-label">${escHtml(label)}</div><div class="history-detail-value">${escHtml(String(value))}</div></div>`;
}

function rtReportMetaItem(label, value, mono = false) {
  if (value == null || value === '') return '';
  return `<div class="rt-report-meta-item">
    <div class="rt-report-meta-label">${escHtml(label)}</div>
    <div class="rt-report-meta-value ${mono ? 'rt-report-mono' : ''}">${escHtml(String(value))}</div>
  </div>`;
}

function renderRTStepsTable(steps, report = {}) {
  const rows = Array.isArray(steps) ? steps : [];
  if (!rows.length) return '';
  const list = rows.map((s, i) => {
    const ms = Number(s.duration_ms || 0);
    const dur = ms > 0 ? `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s` : '—';
    const st = String(s.status || '').toLowerCase();
    const statusText = st === 'passed' ? 'OK' : (st === 'failed' ? 'Fehler' : (st === 'not_tested' ? 'Nicht geprüft' : st));
    const statusClass = st === 'passed' ? 'success' : (st === 'failed' ? 'error' : 'warning');
    return `<div class="rt-step-row">
      <div class="rt-step-index">${i + 1}</div>
      <div class="rt-step-main">
        <div class="rt-step-head">
          <div class="rt-step-title">${escHtml(rtStepLabel(String(s.step_id || '')))}</div>
          <span class="rt-step-status ${statusClass}">${escHtml(statusText || '—')}</span>
        </div>
        <div class="rt-step-message">${escHtml(s.message || 'Kein Hinweis protokolliert')}</div>
        <div class="rt-step-facts">
          ${s.timestamp ? `<span>Zeitpunkt: ${escHtml(s.timestamp)}</span>` : ''}
          ${s.error_code ? `<span>Fehlercode: ${escHtml(s.error_code)}</span>` : ''}
        </div>
        <div class="rt-step-command">${escHtml(s.command || '—')}</div>
        ${renderRTStepDetails(s, report)}
      </div>
      <div class="rt-step-duration">${escHtml(dur)}</div>
    </div>`;
  }).join('');
  return `<div class="rt-steps-panel">
    <div class="rt-steps-title">Prüfschritte</div>
    <div class="rt-steps-list">${list}</div>
  </div>`;
}

function rtStepLabel(stepId) {
  const map = {
    repo_reachable: 'Repository erreichbar',
    archive_readable: 'Archiv lesbar',
    metadata_check: 'Metadaten-Check',
    sample_restore: 'Stichprobe Restore',
    restore_probe: 'Restore-Probe',
    integrity_compare: 'Integritätsvergleich',
    integrity_check: 'Integritätsprüfung',
    cleanup: 'Cleanup Testdaten',
  };
  return map[stepId] || stepId || 'Schritt';
}

function renderRTStepDetails(step, report) {
  const stepId = String(step?.step_id || '');
  const stats = report.archive_stats || {};
  const fmt = report.archive_stats_formatted || {};
  const l3 = report.level3_details || {};
  const entries = Array.isArray(report.tested_entries) ? report.tested_entries : [];
  const compression = stats.original_size > 0 && stats.compressed_size > 0
    ? `${Math.round((1 - stats.compressed_size / stats.original_size) * 100)}%`
    : '';

  if (stepId === 'repo_reachable') {
    return rtStepDetailsBlock([
      ['Repository', report.repository, true],
      ['Standort', locLabel(report.location || '')],
      ['Testzeitpunkt', step.timestamp],
    ]);
  }
  if (stepId === 'archive_readable') {
    return rtStepDetailsBlock([
      ['Archiv', report.tested_archive || report.archive_name, true],
      ['Repository', report.repository, true],
      ['Gefunden um', step.timestamp],
    ]);
  }
  if (stepId === 'metadata_check') {
    return rtStepDetailsBlock([
      ['Dateien im Archiv', stats.files_count],
      ['Originalgröße', fmt.original],
      ['Komprimierte Größe', fmt.compressed],
      ['Deduplizierte Größe', fmt.deduplicated],
      ['Kompressionsrate', compression],
      ['Report-Schema', report.report_schema_version],
    ]);
  }
  if (stepId === 'restore_probe' || stepId === 'sample_restore') {
    return rtStepDetailsBlock([
      ['Geprüfte Dateien', report.tested_files_count || report.tested_files],
      ['Geprüfte Ordner', report.tested_folders_count],
      ['Geprüfte Einträge', report.tested_total_count],
      ['Abdeckungsmodus', report.test_coverage],
      ['Abdeckung', formatCoveragePercent(report.test_coverage_percentage || report.coverage_percent || 0)],
      ['Basis', report.coverage_basis],
    ]) + rtStepEntriesBlock(entries);
  }
  if (stepId === 'integrity_check' || stepId === 'integrity_compare') {
    return rtStepDetailsBlock([
      ['Stichprobengröße', l3.sample_size],
      ['Erfolgreich', l3.success_count],
      ['Fehlgeschlagen', l3.failed_count],
    ]) + rtStepChecksumsBlock(l3);
  }
  if (stepId === 'cleanup') {
    return rtStepDetailsBlock([
      ['Aufräumstatus', step.message],
      ['Zeitpunkt', step.timestamp],
      ['Exit-Code', report.test_exit_code],
    ]);
  }
  return rtStepDetailsBlock([
    ['Zeitpunkt', step.timestamp],
    ['Fehlercode', step.error_code],
  ]);
}

function rtStepDetailsBlock(items) {
  const rows = (items || [])
    .filter(([, value]) => value != null && value !== '')
    .map(([label, value, mono]) => `<div class="rt-step-detail-item">
      <span>${escHtml(label)}</span>
      <strong class="${mono ? 'rt-report-mono' : ''}">${escHtml(String(value))}</strong>
    </div>`)
    .join('');
  if (!rows) return '';
  return `<div class="rt-step-details">${rows}</div>`;
}

function rtStepChecksumsBlock(l3) {
  const checksums = (l3?.checksums || []).map((item) => {
    const raw = String(item || '');
    const sep = raw.lastIndexOf(':');
    const path = sep > 0 ? raw.slice(0, sep) : raw;
    const sha = sep > 0 ? raw.slice(sep + 1) : '';
    return `<div class="rt-checksum-row">
      <div class="rt-checksum-path">${escHtml(path)}</div>
      ${sha ? `<div class="rt-checksum-hash">${escHtml(sha)}</div>` : ''}
    </div>`;
  }).join('');
  const failed = (l3?.failed_files || []).map((path) =>
    `<div class="rt-checksum-row failed"><div class="rt-checksum-path">${escHtml(path)}</div></div>`
  ).join('');
  if (!checksums && !failed) return '';
  return `<details class="rt-step-detail-section">
    <summary>Geprüfte Stichproben-Dateien (${(l3?.checksums || []).length + (l3?.failed_files || []).length})</summary>
    <div class="rt-checksum-list">${checksums}${failed}</div>
  </details>`;
}

function rtStepEntriesBlock(entries) {
  if (!entries.length) return '';
  const items = entries.map((entry) => {
    const raw = String(entry || '');
    const isDir = raw.startsWith('d ');
    const isFile = raw.startsWith('- ');
    const path = isDir || isFile ? raw.slice(2) : raw;
    return `<div class="rt-tested-entry ${isDir ? 'dir' : 'file'}">
      <span>${isDir ? 'Ordner' : 'Datei'}</span>
      <strong>${escHtml(path)}</strong>
    </div>`;
  }).join('');
  return `<details class="rt-step-detail-section">
    <summary>Getestete Einträge (${entries.length})</summary>
    <div class="rt-tested-entry-list">${items}</div>
  </details>`;
}

function renderRTReportDetails(t) {
  const stats = t.archive_stats || {};
  const fmt = t.archive_stats_formatted || {};
  const l3 = t.level3_details || {};
  const err = t.error_analysis || {};
  const entries = Array.isArray(t.tested_entries) ? t.tested_entries : [];
  const compression = stats.original_size > 0 && stats.compressed_size > 0
    ? `${Math.round((1 - stats.compressed_size / stats.original_size) * 100)}%`
    : '–';

  const archiveItems = [
    ['Repository', t.repository, true],
    ['Archiv', t.tested_archive || t.archive_name, true],
    ['Dateien im Archiv', stats.files_count],
    ['Originalgröße', fmt.original],
    ['Komprimierte Größe', fmt.compressed],
    ['Deduplizierte Größe', fmt.deduplicated],
    ['Kompressionsrate', compression],
    ['Exit-Code', t.test_exit_code],
    ['Report-Schema', t.report_schema_version],
  ];
  const scopeItems = [
    ['Geprüfte Dateien', t.tested_files_count || t.tested_files],
    ['Geprüfte Ordner', t.tested_folders_count],
    ['Geprüfte Einträge', t.tested_total_count],
    ['Abdeckungsmodus', t.test_coverage],
    ['Abdeckung', formatCoveragePercent(t.test_coverage_percentage || t.coverage_percent || 0)],
    ['Basis', t.coverage_basis],
  ];
  const l3Summary = [
    ['Aktiv', l3.enabled ? 'Ja' : 'Nein'],
    ['Stichprobengröße', l3.sample_size],
    ['Erfolgreich', l3.success_count],
    ['Fehlgeschlagen', l3.failed_count],
  ];
  const errorItems = [
    ['Fehler vorhanden', err.has_error ? 'Ja' : 'Nein'],
    ['Kategorie', err.error_category],
    ['Details', err.error_details],
    ['Betroffene Einträge', err.error_affected_items],
    ['Ausgabe', err.error_output],
  ];

  return `<div class="rt-more-panel">
    ${rtDetailsSection('Archiv & Repository', archiveItems)}
    ${rtDetailsSection('Prüfumfang', scopeItems)}
    ${rtL3DetailsSection(l3Summary, l3)}
    ${rtDetailsSection('Fehleranalyse', errorItems)}
    ${rtEntriesDetailsSection(entries)}
  </div>`;
}

function rtDetailsSection(title, items) {
  const rows = (items || [])
    .filter(([, value]) => value != null && value !== '')
    .map(([label, value, mono]) => `<div class="rt-detail-fact">
      <span>${escHtml(label)}</span>
      <strong class="${mono ? 'rt-report-mono' : ''}">${escHtml(String(value))}</strong>
    </div>`)
    .join('');
  if (!rows) return '';
  return `<details class="rt-detail-section">
    <summary>${escHtml(title)}</summary>
    <div class="rt-detail-facts">${rows}</div>
  </details>`;
}

function rtL3DetailsSection(summaryItems, l3) {
  if (!l3 || !l3.enabled) return rtDetailsSection('Level-3 Stichprobe', summaryItems);
  const checksums = (l3.checksums || []).map((item) => {
    const raw = String(item || '');
    const sep = raw.lastIndexOf(':');
    const path = sep > 0 ? raw.slice(0, sep) : raw;
    const sha = sep > 0 ? raw.slice(sep + 1) : '';
    return `<div class="rt-checksum-row">
      <div class="rt-checksum-path">${escHtml(path)}</div>
      ${sha ? `<div class="rt-checksum-hash">${escHtml(sha)}</div>` : ''}
    </div>`;
  }).join('');
  const failed = (l3.failed_files || []).map((path) =>
    `<div class="rt-checksum-row failed"><div class="rt-checksum-path">${escHtml(path)}</div></div>`
  ).join('');
  return `<details class="rt-detail-section">
    <summary>Level-3 Stichprobe</summary>
    <div class="rt-detail-facts">
      ${(summaryItems || []).filter(([, value]) => value != null && value !== '').map(([label, value]) => `<div class="rt-detail-fact"><span>${escHtml(label)}</span><strong>${escHtml(String(value))}</strong></div>`).join('')}
    </div>
    ${checksums || failed ? `<div class="rt-checksum-list">${checksums}${failed}</div>` : ''}
  </details>`;
}

function rtEntriesDetailsSection(entries) {
  if (!entries.length) return '';
  const items = entries.map((entry) => {
    const raw = String(entry || '');
    const isDir = raw.startsWith('d ');
    const isFile = raw.startsWith('- ');
    const path = isDir || isFile ? raw.slice(2) : raw;
    return `<div class="rt-tested-entry ${isDir ? 'dir' : 'file'}">
      <span>${isDir ? 'Ordner' : 'Datei'}</span>
      <strong>${escHtml(path)}</strong>
    </div>`;
  }).join('');
  return `<details class="rt-detail-section">
    <summary>Getestete Einträge (${entries.length})</summary>
    <div class="rt-tested-entry-list">${items}</div>
  </details>`;
}

function renderRTDetail(t) {
  const stats = t.archive_stats || {};
  const fmt   = t.archive_stats_formatted || {};
  const l3    = t.level3_details || {};
  const err   = t.error_analysis || {};

  const comprRatio = stats.original_size > 0
    ? `${Math.round((1 - stats.compressed_size / stats.original_size) * 100)}%`
    : '–';

  let archiveCreated = '';
  if (t.tested_archive) {
    const m = t.tested_archive.match(/(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})/);
    if (m) {
      const months = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
      archiveCreated = `${parseInt(m[3], 10)}. ${months[parseInt(m[2], 10) - 1]} ${m[1]}, ${m[4]}:${m[5]}`;
    }
  }

  const archiveCard = `
    <div class="rt-card">
      <div class="rt-card-title">Archivinformationen</div>
      <div class="rt-row"><span>Archivname</span><span class="rt-mono">${escHtml(t.tested_archive || '–')}</span></div>
      ${archiveCreated ? `<div class="rt-row"><span>Erstellt</span><span>${archiveCreated}</span></div>` : ''}
      <div class="rt-row"><span>Repository</span><span class="rt-mono">${escHtml(t.repository || '–')}</span></div>
      <div class="rt-row"><span>Dateien im Archiv</span><span>${stats.files_count || 0}</span></div>
      <div class="rt-row"><span>Originalgröße</span><span>${escHtml(fmt.original || '–')}</span></div>
      <div class="rt-row"><span>Komprimierte Größe</span><span>${escHtml(fmt.compressed || '–')}</span></div>
      <div class="rt-row"><span>Deduplizierte Größe</span><span>${escHtml(fmt.deduplicated || '–')}</span></div>
      <div class="rt-row"><span>Kompressionsrate</span><span>${comprRatio}</span></div>
    </div>`;

  const testCard = `
    <div class="rt-card">
      <div class="rt-card-title">Testausführung</div>
      <div class="rt-row"><span>Testdatum</span><span>${escHtml(t.test_date || '–')}</span></div>
      <div class="rt-row"><span>Dauer</span><span>${escHtml(t.duration_formatted || '–')}</span></div>
      <div class="rt-row"><span>Geprüfte Dateien</span><span>${t.tested_files_count || 0}</span></div>
      <div class="rt-row"><span>Geprüfte Ordner</span><span>${t.tested_folders_count || 0}</span></div>
      <div class="rt-row"><span>Geprüfte Einträge</span><span>${t.tested_total_count || 0}</span></div>
      <div class="rt-row"><span>Abdeckung</span><span style="color:${(t.test_coverage_percentage || 0) >= 100 ? 'var(--success)' : 'var(--text-primary)'}">${formatCoveragePercent(t.test_coverage_percentage || 0)}</span></div>
    </div>`;

  let l3Section = '';
  if (l3.enabled) {
    const total      = l3.sample_size || 0;
    const succCount  = l3.success_count || 0;
    const succPct    = total > 0 ? Math.round(succCount / total * 100) : 0;
    const badgeColor = succCount === total ? 'var(--success)' : 'var(--error)';

    const checksums = (l3.checksums || []).map(c => {
      const sep  = c.lastIndexOf(':');
      const path = sep > 0 ? c.substring(0, sep) : c;
      const sha  = sep > 0 ? c.substring(sep + 1) : '';
      return `<div class="rt-l3-file">
        <div class="rt-l3-filename">✓ ${escHtml(path)}</div>
        ${sha ? `<div class="rt-l3-sha">SHA256: ${sha.substring(0, 20)}...</div>` : ''}
      </div>`;
    }).join('');

    const failedFiles = (l3.failed_files || []).map(f =>
      `<div class="rt-l3-file rt-l3-failed">✗ ${escHtml(f)}</div>`
    ).join('');

    l3Section = `
      <div class="rt-l3-section">
        <div class="rt-l3-header">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0 1 12 2.944a11.955 11.955 0 0 1-8.618 3.04A12.02 12.02 0 0 0 3 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>
          Level-3 Stichproben-Restore-Ergebnis
        </div>
        <div class="rt-l3-body">
          <div class="rt-l3-row">
            <span>Sample Size</span>
            <span>${total} files</span>
          </div>
          <div class="rt-l3-row">
            <span>Success Rate</span>
            <span class="rt-success-badge" style="background:${succCount === total ? 'var(--success-dim)' : 'var(--error-dim)'};color:${badgeColor};border-color:${badgeColor}">
              ✓ ${succCount}/${total} (${succPct}%)
            </span>
          </div>
          ${checksums || failedFiles ? `
          <div class="rt-l3-row rt-l3-files-row">
            <span>Validated Files</span>
            <div class="rt-l3-files">${checksums}${failedFiles}</div>
          </div>` : ''}
        </div>
      </div>`;
  }

  let entriesSection = '';
  const entries = t.tested_entries || [];
  if (entries.length > 0) {
    const items = entries.map(e => {
      const isDir  = e.startsWith('d ');
      const isFile = e.startsWith('- ');
      const path   = isDir ? e.substring(2) : isFile ? e.substring(2) : e;
      return isDir
        ? `<div class="rt-entry rt-entry-dir"><svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M20 6h-8l-2-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2z"/></svg>${escHtml(path)}</div>`
        : `<div class="rt-entry rt-entry-file"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>${escHtml(path)}</div>`;
    }).join('');

    entriesSection = `
      <div class="rt-entries-section">
        <div class="rt-entries-header" data-rt-action="toggle-entries">
          <span class="history-chevron">▶</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          Tested Entries (${entries.length})
        </div>
        <div class="rt-entries-body" style="display:none">
          <div class="rt-entries-list">${items}</div>
        </div>
      </div>`;
  }

  const errSection = err.has_error ? `
    <div class="rt-l3-section" style="border-left-color:var(--error);border-color:rgba(248,81,73,0.3)">
      <div class="rt-l3-header" style="color:var(--error);background:var(--error-dim)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        Fehler
      </div>
      <div class="rt-l3-body">
        <div class="rt-l3-row"><span>Kategorie</span><span style="color:var(--error)">${escHtml(err.error_category || '–')}</span></div>
        <div class="rt-l3-row"><span>Details</span><span style="font-size:12px">${escHtml(err.error_details || '–')}</span></div>
      </div>
    </div>` : '';

  return `
    <div class="rt-detail-wrap">
      <div class="rt-top-grid">${archiveCard}${testCard}</div>
      ${l3Section}${entriesSection}${errSection}
    </div>`;
}
