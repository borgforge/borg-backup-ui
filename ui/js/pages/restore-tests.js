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
  logState: null,
  logExitCode: null,
  selectedJob: 'all',
};
const restoreTestsState = window.BBUI.restoreTestsState;

function restoreTestsT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(`restoreTests.${key}`, params) || `restoreTests.${key}`;
}

function restoreTestsLocale() {
  return window.BBUI?.components?.i18n?.getLanguage?.() === 'en' ? 'en-US' : 'de-DE';
}

function restoreTestsLocationLabel(location) {
  const keys = { local: 'local', usb: 'usbDrive', smb: 'smb', storagebox: 'storagebox' };
  const normalized = String(location || '').toLowerCase();
  const key = keys[normalized];
  return key
    ? (window.BBUI?.components?.i18n?.t?.(`storage.${key}`) || normalized)
    : (location || '—');
}

function restoreTestsJobCount(count) {
  return restoreTestsT(count === 1 ? 'jobCountOne' : 'jobCountMany', { count });
}

function restoreTestsJobIcon(job) {
  const icon = resolveJobIcon(job);
  const color = resolveJobIconColor(job);
  const colorClass = color ? ` type-icon-color-${color}` : '';
  return `<span class="type-icon type-icon-${escHtml(String(job?.backup_type || 'sonstiges').toLowerCase())} rt-sidebar-job-icon${colorClass}">${typeIcon(icon)}</span>`;
}

function renderRestoreTestsSidebar() {
  const list = document.getElementById('rt-sidebar-job-list');
  if (!list) return;
  const query = String(document.getElementById('rt-sidebar-search')?.value || '').trim().toLowerCase();
  const jobs = (restoreTestsState.jobs || []).filter((job) => `${job.display_name || ''} ${job.name || ''} ${job.key || ''} ${job.location || ''}`.toLowerCase().includes(query));
  if (!jobs.length) {
    list.innerHTML = `<div class="ui-empty rt-sidebar-empty">${escHtml(restoreTestsT('noMatchingJobs'))}</div>`;
    return;
  }
  const planByKey = new Map((restoreTestsState.plan?.jobs || []).map((job) => [String(job.job_key), job]));
  const allActive = restoreTestsState.selectedJob === 'all';
  const allEntry = `<button class="rt-sidebar-job is-all ${allActive ? 'is-active' : ''}" data-rt-sidebar-job="all" ${allActive ? 'aria-current="page"' : ''}><span class="location-nav-glyph all">${locationIcon('all')}</span><span><strong>${escHtml(restoreTestsT('allJobs'))}</strong><small>${escHtml(restoreTestsT('overview'))}</small></span><span class="ui-badge">${jobs.length}</span></button>`;
  const order = ['storagebox', 'usb', 'smb', 'local'];
  const groups = order.map((location) => {
    const locationJobs = jobs.filter((job) => String(job.location || '').toLowerCase() === location);
    if (!locationJobs.length) return '';
    return `<section class="rt-sidebar-group"><header>${escHtml(restoreTestsLocationLabel(location))}<span>${locationJobs.length}</span></header>${locationJobs.map((job) => {
      const planJob = planByKey.get(String(job.key));
      const stateClass = planJob?.is_overdue ? 'warning' : planJob?.enabled === false ? 'disabled' : 'success';
      const active = restoreTestsState.selectedJob === String(job.key);
      return `<button class="rt-sidebar-job ${active ? 'is-active' : ''}" data-rt-sidebar-job="${escHtml(job.key)}" ${active ? 'aria-current="page"' : ''}>${restoreTestsJobIcon(job)}<span><strong>${escHtml(job.display_name || job.name || job.key)}</strong><small>${escHtml(job.key)}</small></span><span class="rt-sidebar-state ${stateClass}"></span></button>`;
    }).join('')}</section>`;
  }).join('');
  list.innerHTML = allEntry + groups;
  list.querySelectorAll('[data-rt-sidebar-job]').forEach((button) => button.addEventListener('click', () => {
    restoreTestsState.selectedJob = button.dataset.rtSidebarJob || 'all';
    renderRestoreTestsSidebar();
    renderRestorePlan(restoreTestsState.plan);
    renderRestoreTests(restoreTestsState.data || []);
    updateRestoreTestsWorkspace();
  }));
}

function updateRestoreTestsWorkspace() {
  const selected = restoreTestsState.selectedJob;
  const selectedJob = (restoreTestsState.jobs || []).find((job) => String(job.key) === selected);
  const visibleCount = selected === 'all' ? (restoreTestsState.jobs || []).length : (selectedJob ? 1 : 0);
  const title = document.getElementById('rt-workspace-title');
  const count = document.getElementById('rt-workspace-count');
  const kicker = document.getElementById('rt-workspace-kicker');
  const subtitle = document.getElementById('rt-workspace-subtitle');
  if (title) title.textContent = selectedJob?.display_name || selectedJob?.name || (selected === 'all' ? restoreTestsT('allJobs') : selected);
  if (count) count.textContent = restoreTestsJobCount(visibleCount);
  if (kicker) kicker.textContent = restoreTestsT(restoreTestsState.subtab === 'reports' ? 'reportsTab' : 'planTab');
  if (subtitle) subtitle.textContent = restoreTestsT(restoreTestsState.subtab === 'reports' ? 'reportsWorkspaceSubtitle' : 'planWorkspaceSubtitle');
}

function restoreTestFailureMessage(test) {
  const code = String(test?.failure_code || 'RT_UNKNOWN');
  const key = `restoreTests.failures.${code}`;
  const translated = window.BBUI?.components?.i18n?.t?.(key);
  return translated && translated !== key ? translated : restoreTestsT('failures.RT_UNKNOWN');
}

function restoreTestStepMessage(step) {
  const label = rtStepLabel(String(step?.step_id || ''));
  if (step?.step_id === 'cleanup' && step?.status === 'passed') return restoreTestsT('cleanupCompleted');
  if (step?.status === 'passed') return restoreTestsT('stepPassed', { step: label });
  if (step?.status === 'failed') return restoreTestsT('stepFailed', { step: label });
  if (step?.status === 'not_tested') return restoreTestsT('notTested');
  return restoreTestsT('noStepMessage');
}

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
      resolve(window.confirm(restoreTestsT('confirmFallback', { summary: summaryText })));
      return;
    }

    if (inputWrap) inputWrap.classList.add('hidden');
    if (passWrap) passWrap.classList.add('hidden');
    titleEl.textContent = restoreTestsT('confirmTitle');
    descEl.textContent = restoreTestsT('confirmDescription');
    infoEl.innerHTML = '<div class="modal-info-item info"><span class="modal-info-text" id="rt-confirm-summary-text"></span></div>';
    const summaryEl = document.getElementById('rt-confirm-summary-text');
    if (summaryEl) {
      summaryEl.textContent = String(summaryText || '');
      summaryEl.style.whiteSpace = 'pre-line';
    }
    btn.className = 'btn btn-primary';
    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><polygon points="5 3 19 12 5 21 5 3"/></svg> ${escHtml(restoreTestsT('confirmAction'))}`;
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
    restoreTestsT('runSummaryDue'),
    restoreTestsT('runSummaryPolicy'),
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
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    if (data.started === false && data.reason === 'no_due_jobs') {
      showMsg(
        'restore-tests-message',
        'info',
        restoreTestsT('noDueJobs')
      );
      await refreshRestorePlanOnly();
      return;
    }
    _openRTLogPanel();
    startRTPolling();
    await refreshRestorePlanOnly();
  } catch (err) {
    showMsg('restore-tests-message', 'error', restoreTestsT('errorValue', { message: err.message }));
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
  restoreTestsState.logState = state;
  restoreTestsState.logExitCode = exitCode;
  const badge = document.getElementById('rt-log-status-badge');
  if (!badge) return;
  const exit = String(exitCode ?? '');
  if (state === 'running') {
    badge.className = 'badge';
    badge.textContent = '';
    const dot = document.createElement('span');
    dot.className = 'running-dot';
    dot.style.marginRight = '4px';
    badge.append(dot, document.createTextNode(restoreTestsT('running')));
  } else if (state === 'success') {
    badge.className = 'badge success';
    badge.textContent = '';
    const dot = document.createElement('span');
    dot.className = 'badge-dot';
    badge.append(dot, document.createTextNode(restoreTestsT('finishedExit', { exit })));
  } else {
    badge.className = 'badge error';
    badge.textContent = '';
    const dot = document.createElement('span');
    dot.className = 'badge-dot';
    badge.append(dot, document.createTextNode(restoreTestsT('errorExit', { exit })));
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
    renderRestoreTestsSidebar();
    updateRestoreTestsWorkspace();
  } catch (err) {
    showMsg('restore-tests-message', 'error', restoreTestsT('errorValue', { message: err.message }));
  } finally {
    if (btn) btn.classList.remove('loading');
  }
}

function switchRestoreTestsSubtab(tab) {
  restoreTestsState.subtab = tab === 'reports' ? 'reports' : 'plan';
  renderRestoreTestsSubtab();
  updateRestoreTestsWorkspace();
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
    summaryEl.textContent = restoreTestsT('planUnavailable');
    contentEl.innerHTML = `<div class="status-message warning">${escHtml(restoreTestsT('planLoadFailed'))}</div>`;
    return;
  }
  const locOrder = { local: 1, usb: 2, smb: 3, storagebox: 4, custom: 5 };
  const sortedJobs = [...plan.jobs].filter((job) => restoreTestsState.selectedJob === 'all' || String(job.job_key) === restoreTestsState.selectedJob).sort((a, b) => {
    const la = String(a?.location || '').toLowerCase();
    const lb = String(b?.location || '').toLowerCase();
    const oa = locOrder[la] || 99;
    const ob = locOrder[lb] || 99;
    if (oa !== ob) return oa - ob;
    const na = String(a?.display_name || a?.job_key || '').toLowerCase();
    const nb = String(b?.display_name || b?.job_key || '').toLowerCase();
    return na.localeCompare(nb, restoreTestsLocale());
  });
  const planSummary = {
    total: sortedJobs.length,
    scheduled: sortedJobs.filter((job) => String(job.policy?.mode || 'off') === 'scheduled').length,
    manual: sortedJobs.filter((job) => String(job.policy?.mode || 'off') === 'manual_only').length,
    off: sortedJobs.filter((job) => String(job.policy?.mode || 'off') === 'off').length,
    overdue: sortedJobs.filter((job) => job.is_overdue).length,
  };
  summaryEl.innerHTML = `<section class="rt-plan-summary"><header><div><strong>${escHtml(restoreTestsT('summaryTitle'))}</strong><small>${escHtml(restoreTestsT('summarySubtitle'))}</small></div></header><div><span><small>${escHtml(restoreTestsT('summaryTotal'))}</small><b>${planSummary.total}</b></span><span class="planned"><small>${escHtml(restoreTestsT('summaryScheduled'))}</small><b>${planSummary.scheduled}</b></span><span><small>${escHtml(restoreTestsT('summaryManual'))}</small><b>${planSummary.manual}</b></span><span><small>${escHtml(restoreTestsT('summaryOff'))}</small><b>${planSummary.off}</b></span><span class="attention"><small>${escHtml(restoreTestsT('summaryOverdue'))}</small><b>${planSummary.overdue}</b></span></div></section>`;
  const rows = sortedJobs.map((j) => {
    const p = j.policy || {};
    const mode = String(p.mode || 'off');
    const interval = Number(p.interval_days || plan.defaults?.interval_days || 30);
    const level = Number(p.level || plan.defaults?.level || 2);
    const disabled = j.enabled === false ? 'disabled' : '';
    const due = j.next_due_at || (j.is_overdue ? restoreTestsT('due') : '—');
    const schedState = mode !== 'scheduled'
      ? restoreTestsT('no')
      : (j.is_overdue ? restoreTestsT('yesDue') : restoreTestsT('yesWaiting'));
    const busy = !!restoreTestsState.rowBusy[j.job_key];
    const note = restoreTestsState.rowNote[j.job_key] || '';
    return `<tr>
      <td>${escHtml(j.display_name || j.job_key || '-')}</td>
      <td><span class="history-loc-chip ${(j.location || '').toLowerCase()}">${escHtml(restoreTestsLocationLabel(j.location || ''))}</span></td>
      <td>
        <select class="form-select" data-rt-plan-input="mode" data-job-key="${escHtml(j.job_key)}" style="min-width:130px" ${disabled}>
          <option value="scheduled" ${mode === 'scheduled' ? 'selected' : ''}>${escHtml(restoreTestsT('scheduled'))}</option>
          <option value="manual_only" ${mode === 'manual_only' ? 'selected' : ''}>${escHtml(restoreTestsT('manualOnly'))}</option>
          <option value="off" ${mode === 'off' ? 'selected' : ''}>${escHtml(restoreTestsT('off'))}</option>
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
          <button type="button" class="btn btn-secondary btn-sm ${busy ? 'loading' : ''}" data-rt-plan-action="save" data-job-key="${escHtml(j.job_key)}" ${disabled} ${busy ? 'disabled' : ''}>${escHtml(restoreTestsT('save'))}</button>
          <button type="button" class="btn btn-primary btn-sm ${busy ? 'loading' : ''}" data-rt-plan-action="run" data-job-key="${escHtml(j.job_key)}" ${disabled} ${busy ? 'disabled' : ''}>${escHtml(restoreTestsT('testNow'))}</button>
          ${note ? `<span class="muted" style="font-size:11px">${escHtml(note)}</span>` : ''}
        </div>
      </td>
    </tr>`;
  }).join('');
  contentEl.innerHTML = `
    <table class="history-table">
      <thead><tr><th>${escHtml(restoreTestsT('job'))}</th><th>${escHtml(restoreTestsT('location'))}</th><th>${escHtml(restoreTestsT('policy'))}</th><th>${escHtml(restoreTestsT('intervalDays'))}</th><th>${escHtml(restoreTestsT('level'))}</th><th>${escHtml(restoreTestsT('lastTest'))}</th><th>${escHtml(restoreTestsT('nextTest'))}</th><th>${escHtml(restoreTestsT('scheduler'))}</th><th>${escHtml(restoreTestsT('actions'))}</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="9">${escHtml(restoreTestsT('noJobs'))}</td></tr>`}</tbody>
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
    showMsg('restore-tests-message', 'error', restoreTestsT('invalidInterval', { job: jobKey }));
    return;
  }
  if (![1, 2, 3].includes(level)) {
    showMsg('restore-tests-message', 'error', restoreTestsT('invalidLevel', { job: jobKey }));
    return;
  }
  restoreTestsState.rowBusy[jobKey] = true;
  restoreTestsState.rowNote[jobKey] = restoreTestsT('saving');
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
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const stamp = new Date().toLocaleTimeString(restoreTestsLocale());
    restoreTestsState.rowNote[jobKey] = restoreTestsT('savedAt', { time: stamp });
    showMsg('restore-tests-message', 'success', restoreTestsT('policySaved', { job: jobKey }));
    await refreshRestorePlanOnly();
  } catch (err) {
    restoreTestsState.rowNote[jobKey] = restoreTestsT('errorValue', { message: err.message });
    showMsg('restore-tests-message', 'error', restoreTestsT('policySaveFailed', { message: err.message }));
  } finally {
    restoreTestsState.rowBusy[jobKey] = false;
    renderRestorePlan(restoreTestsState.plan);
  }
}

async function runRestorePlanJob(jobKey) {
  restoreTestsState.rowBusy[jobKey] = true;
  restoreTestsState.rowNote[jobKey] = restoreTestsT('startingTest');
  renderRestorePlan(restoreTestsState.plan);
  try {
    const res = await fetch('/api/restore-tests/run-job', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_key: jobKey }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const stamp = new Date().toLocaleTimeString(restoreTestsLocale());
    restoreTestsState.rowNote[jobKey] = restoreTestsT('startedAt', { time: stamp });
    showMsg('restore-tests-message', 'success', restoreTestsT('testStarted', { job: jobKey }));
    _openRTLogPanel();
    startRTPolling();
    await refreshRestorePlanOnly();
  } catch (err) {
    restoreTestsState.rowNote[jobKey] = restoreTestsT('errorValue', { message: err.message });
    showMsg('restore-tests-message', 'error', restoreTestsT('startFailed', { message: err.message }));
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
    restoreTestsState.jobs = (data.jobs || []).filter(j => !j.is_utility);
    renderRestoreTestsSidebar();
    updateRestoreTestsWorkspace();
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
    list.innerHTML = `<span class="muted">${escHtml(restoreTestsT('noJobsForSelection'))}</span>`;
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
    <div class="stat-tile total"><div><div class="stat-value">${filtered.length}</div><div class="stat-label">${escHtml(restoreTestsT('reports'))}</div></div></div>
    <div class="stat-tile success"><div><div class="stat-value">${ok}</div><div class="stat-label">${escHtml(restoreTestsT('verified'))}</div></div></div>
    <div class="stat-tile warning"><div><div class="stat-value">${stale}</div><div class="stat-label">${escHtml(restoreTestsT('overdue'))}</div></div></div>
    <div class="stat-tile error"><div><div class="stat-value">${failed + unavail}</div><div class="stat-label">${escHtml(restoreTestsT('problematic'))}</div></div></div>`;
  summaryEl.classList.remove('hidden');

  if (!filtered.length) {
    contentEl.innerHTML = `<div class="status-message empty-state">${escHtml(restoreTestsT('noFilteredReports'))}</div>`;
    return;
  }
  const rows = filtered.map((t, i) => renderRTReportRow(t, i)).join('');
  contentEl.innerHTML = `
    <table class="history-table restore-tests-table">
      <thead><tr><th></th><th>${escHtml(restoreTestsT('dateTime'))}</th><th>${escHtml(restoreTestsT('type'))}</th><th>${escHtml(restoreTestsT('job'))}</th><th>${escHtml(restoreTestsT('location'))}</th><th>${escHtml(restoreTestsT('duration'))}</th><th>${escHtml(restoreTestsT('originalSize'))}</th><th>${escHtml(restoreTestsT('coverage'))}</th><th>${escHtml(restoreTestsT('status'))}</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  restoreTestsState.filteredReports = filtered;
}

function _rtStatus(t) {
  if (t.test_result === 'success' && isStaleDate(t.test_date)) return { className: 'warning', label: restoreTestsT('overdue') };
  if (t.test_result === 'success') return { className: 'success', label: restoreTestsT('verified') };
  if (t.test_result === 'failed') return { className: 'error', label: restoreTestsT('failed') };
  return { className: 'warning', label: restoreTestsT('unavailable') };
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
    if (restoreTestsState.selectedJob !== 'all' && key !== String(restoreTestsState.selectedJob).toLowerCase()) return false;
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
  if (sec >= 3600) return { label: restoreTestsT('runtimeLong'), short: restoreTestsT('runtimeLong'), cls: 'long' };
  if (sec >= 900) return { label: restoreTestsT('runtimeMedium'), short: restoreTestsT('runtimeMedium'), cls: 'medium' };
  return { label: restoreTestsT('runtimeShort'), short: restoreTestsT('runtimeShort'), cls: 'short' };
}

function formatCoveragePercent(value) {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return new Intl.NumberFormat(restoreTestsLocale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(0) + '%';
  return `${new Intl.NumberFormat(restoreTestsLocale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(n)}%`;
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
  locationEl.innerHTML = `<option value="all">${escHtml(restoreTestsT('allLocations'))}</option>`
    + locations.map((loc) => `<option value="${escHtml(loc)}">${escHtml(restoreTestsLocationLabel(loc))}</option>`).join('');
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
  const covTxt = formatCoveragePercent(cov);
  const stats = t.archive_stats_formatted || {};
  const detailError = t.test_result === 'failed' || t.test_result === 'unavailable'
    ? restoreTestFailureMessage(t)
    : '';
  const dt = String(t.test_date || '—');
  const reportId = t.report_id || t.test_id;
  const archive = t.tested_archive || t.archive_name;
  const location = restoreTestsLocationLabel(t.location || '');
  return `
    <tr id="${rowId}" class="history-row history-restore-row" data-rt-action="toggle-detail" data-row-id="${rowId}" data-detail-id="${detailId}">
      <td><svg class="history-chevron" id="rtchev-${idx}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14"><polyline points="9 18 15 12 9 6"/></svg></td>
      <td style="white-space:nowrap;color:var(--text-primary)">${escHtml(dt)}</td>
      <td><span class="history-type-badge">RESTORE TEST</span></td>
      <td style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px">${escHtml(t.job_key || t.type || '-')}</td>
      <td><span class="history-loc-chip ${(t.location || '').toLowerCase()}">${escHtml(restoreTestsLocationLabel(t.location || ''))}</span></td>
      <td>${escHtml(t.duration_formatted || '—')}</td>
      <td>${escHtml(stats.original || '—')}</td>
      <td>${escHtml(covTxt)}</td>
      <td><span class="history-status-badge ${status.className}">${escHtml(status.className === 'success' ? restoreTestsT('successful') : status.label)}</span></td>
    </tr>
    <tr id="${detailId}" class="history-detail-row" style="display:none">
      <td colspan="9">
        <div class="rt-report-card">
          <div class="rt-report-card-head">
            <div>
              <div class="rt-report-kicker">${escHtml(restoreTestsT('report'))}</div>
              <div class="rt-report-title">${escHtml(t.job_key || t.type || 'Restore Test')}</div>
              <div class="rt-report-subtitle">${escHtml(archive || restoreTestsT('noArchive'))}</div>
            </div>
            <div class="rt-report-actions">
              <span class="history-status-badge ${status.className}">${escHtml(status.className === 'success' ? restoreTestsT('successful') : status.label)}</span>
            </div>
          </div>
          ${detailError ? `<div class="rt-report-alert">${escHtml(restoreTestsT('errorValue', { message: detailError }))}</div>` : ''}
          <div class="rt-report-meta-grid">
            ${rtReportMetaItem(restoreTestsT('reportId'), reportId, true)}
            ${rtReportMetaItem(restoreTestsT('site'), location)}
            ${rtReportMetaItem(restoreTestsT('level'), t.test_level != null ? `L${t.test_level}` : null)}
            ${rtReportMetaItem(restoreTestsT('start'), t.start_ts || t.started_at)}
            ${rtReportMetaItem(restoreTestsT('end'), t.end_ts || t.finished_at || t.test_date)}
            ${rtReportMetaItem(restoreTestsT('duration'), t.duration_formatted || '—')}
            ${rtReportMetaItem(restoreTestsT('originalSize'), stats.original || '—')}
            ${rtReportMetaItem(restoreTestsT('coverage'), `${covTxt}${t.coverage_basis ? ` (${t.coverage_basis})` : ''}`)}
            ${rtReportMetaItem(restoreTestsT('overallStatus'), status.label)}
            ${rtReportMetaItem(restoreTestsT('validUntil'), t.valid_until || t.valid_until_date)}
            ${rtReportMetaItem(restoreTestsT('errorCode'), t.failure_code)}
          </div>
          ${renderRTStepsTable(t.steps || [], t)}
        </div>
      </td>
    </tr>`;
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
    const statusText = st === 'passed' ? 'OK' : (st === 'failed' ? restoreTestsT('failed') : (st === 'not_tested' ? restoreTestsT('notTested') : st));
    const statusClass = st === 'passed' ? 'success' : (st === 'failed' ? 'error' : 'warning');
    return `<div class="rt-step-row">
      <div class="rt-step-index">${i + 1}</div>
      <div class="rt-step-main">
        <div class="rt-step-head">
          <div class="rt-step-title">${escHtml(rtStepLabel(String(s.step_id || '')))}</div>
          <span class="rt-step-status ${statusClass}">${escHtml(statusText || '—')}</span>
        </div>
        <div class="rt-step-message">${escHtml(restoreTestStepMessage(s))}</div>
        <div class="rt-step-facts">
          ${s.timestamp ? `<span>${escHtml(restoreTestsT('timestampValue', { value: s.timestamp }))}</span>` : ''}
          ${s.error_code ? `<span>${escHtml(restoreTestsT('errorCodeValue', { value: s.error_code }))}</span>` : ''}
        </div>
        <div class="rt-step-command">${escHtml(s.command || '—')}</div>
        ${renderRTStepDetails(s, report)}
      </div>
      <div class="rt-step-duration">${escHtml(dur)}</div>
    </div>`;
  }).join('');
  return `<div class="rt-steps-panel">
    <div class="rt-steps-title">${escHtml(restoreTestsT('steps'))}</div>
    <div class="rt-steps-list">${list}</div>
  </div>`;
}

function rtStepLabel(stepId) {
  const map = {
    repo_reachable: restoreTestsT('stepRepoReachable'),
    archive_readable: restoreTestsT('stepArchiveReadable'),
    metadata_check: restoreTestsT('stepMetadata'),
    sample_restore: restoreTestsT('stepSampleRestore'),
    restore_probe: restoreTestsT('stepRestoreProbe'),
    integrity_compare: restoreTestsT('stepIntegrityCompare'),
    integrity_check: restoreTestsT('stepIntegrityCheck'),
    cleanup: restoreTestsT('stepCleanup'),
  };
  return map[stepId] || stepId || restoreTestsT('stepDefault');
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
      [restoreTestsT('repository'), report.repository, true],
      [restoreTestsT('site'), restoreTestsLocationLabel(report.location || '')],
      [restoreTestsT('testTime'), step.timestamp],
    ]);
  }
  if (stepId === 'archive_readable') {
    return rtStepDetailsBlock([
      [restoreTestsT('archive'), report.tested_archive || report.archive_name, true],
      [restoreTestsT('repository'), report.repository, true],
      [restoreTestsT('foundAt'), step.timestamp],
    ]);
  }
  if (stepId === 'metadata_check') {
    return rtStepDetailsBlock([
      [restoreTestsT('archiveFiles'), stats.files_count],
      [restoreTestsT('originalSize'), fmt.original],
      [restoreTestsT('compressedSize'), fmt.compressed],
      [restoreTestsT('deduplicatedSize'), fmt.deduplicated],
      [restoreTestsT('compressionRate'), compression],
      [restoreTestsT('reportSchema'), report.report_schema_version],
    ]);
  }
  if (stepId === 'restore_probe' || stepId === 'sample_restore') {
    return rtStepDetailsBlock([
      [restoreTestsT('testedFiles'), report.tested_files_count || report.tested_files],
      [restoreTestsT('testedFolders'), report.tested_folders_count],
      [restoreTestsT('testedEntries'), report.tested_total_count],
      [restoreTestsT('coverageMode'), report.test_coverage],
      [restoreTestsT('coverage'), formatCoveragePercent(report.test_coverage_percentage || report.coverage_percent || 0)],
      [restoreTestsT('basis'), report.coverage_basis],
    ]) + rtStepEntriesBlock(entries);
  }
  if (stepId === 'integrity_check' || stepId === 'integrity_compare') {
    return rtStepDetailsBlock([
      [restoreTestsT('sampleSize'), l3.sample_size],
      [restoreTestsT('successful'), l3.success_count],
      [restoreTestsT('failed'), l3.failed_count],
    ]) + rtStepChecksumsBlock(l3);
  }
  if (stepId === 'cleanup') {
    return rtStepDetailsBlock([
      [restoreTestsT('cleanupStatus'), restoreTestStepMessage(step)],
      [restoreTestsT('testTime'), step.timestamp],
      [restoreTestsT('exitCode'), report.test_exit_code],
    ]);
  }
  return rtStepDetailsBlock([
    [restoreTestsT('testTime'), step.timestamp],
    [restoreTestsT('errorCode'), step.error_code],
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
    <summary>${escHtml(restoreTestsT('sampleFiles', { count: (l3?.checksums || []).length + (l3?.failed_files || []).length }))}</summary>
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
      <span>${escHtml(isDir ? restoreTestsT('folder') : restoreTestsT('file'))}</span>
      <strong>${escHtml(path)}</strong>
    </div>`;
  }).join('');
  return `<details class="rt-step-detail-section">
    <summary>${escHtml(restoreTestsT('testedEntriesCount', { count: entries.length }))}</summary>
    <div class="rt-tested-entry-list">${items}</div>
  </details>`;
}

window.addEventListener?.('bbui:language-changed', () => {
  if (!restoreTestsState.loaded) return;
  renderRestorePlan(restoreTestsState.plan);
  renderRTReportFilterOptions(restoreTestsState.data || []);
  renderRestoreTests(restoreTestsState.data || []);
  renderRestoreTestsSubtab();
  renderRestoreTestsSidebar();
  updateRestoreTestsWorkspace();
  refreshRestoreTestJobsForSelection();
  if (restoreTestsState.logState) {
    setRTLogStatus(restoreTestsState.logState, restoreTestsState.logExitCode);
  }
});
