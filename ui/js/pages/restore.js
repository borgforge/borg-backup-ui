'use strict';

// ══════════════════════════════════════════════════════════════════════════════
// BROWSE & RESTORE PAGE
// ══════════════════════════════════════════════════════════════════════════════

window.BBUI = window.BBUI || {};
window.BBUI.restoreState = window.BBUI.restoreState || {
  step: 1,
  job: '',
  archive: '',
  path: '',
  selectedPath: '',
  selectedName: '',
  selectedType: '',
  precheck: null,
  targetSuggestTimer: null,
  targetSuggestReq: 0,
  targetSuggestCache: new Map(),
  confirmResolver: null,
  downloadConfirmResolver: null,
  activeRestoreId: '',
  restorePollTimer: null,
  autoPrecheckKey: '',
  completed: false,
  files: [],
  jobs: [],
  archives: [],
  runs: [],
  history: [],
  historyTotal: 0,
  historyDetailId: '',
  liveMode: false,
};
const restoreState = window.BBUI.restoreState;

function restoreT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(`restore.${key}`, params) || `restore.${key}`;
}

function restoreSetStep(step) {
  const next = Math.max(1, Math.min(5, Number(step) || 1));
  restoreState.step = next;
  for (let i = 1; i <= 5; i++) {
    const panel = document.getElementById(`restore-step-panel-${i}`);
    if (panel) panel.style.display = i === next ? '' : 'none';
    const badge = document.getElementById(`restore-step-badge-${i}`);
    if (badge) {
      badge.classList.toggle('is-active', i === next);
      badge.classList.toggle('is-done', i < next);
      badge.setAttribute('aria-current', i === next ? 'step' : 'false');
      const number = badge.querySelector('span');
      if (number) number.textContent = i < next ? '✓' : String(i);
    }
  }
  _restoreMsg('');
  const backBtn = document.getElementById('restore-step-back-btn');
  const nextBtn = document.getElementById('restore-step-next-btn');
  if (backBtn) {
    backBtn.disabled = next <= 1 && !restoreState.completed;
    backBtn.textContent = (next === 5 && restoreState.completed) ? restoreT('close') : restoreT('back');
  }
  if (nextBtn) {
    nextBtn.style.display = next >= 5 ? 'none' : '';
    nextBtn.textContent = next === 4 ? restoreT('toCheck') : restoreT('next');
  }
  if (next !== 5 && restoreState.liveMode) {
    restoreSetLiveMode(false);
  }
  if (next === 5 && !restoreState.liveMode) {
    restoreEnsureAutoPrecheck();
  }
  const status = document.getElementById('restore-step-status');
  if (status) status.textContent = restoreT('stepStatus', { step: next, total: 5 });
}

function restoreSetLiveMode(enabled) {
  restoreState.liveMode = !!enabled;
  const panel = document.getElementById('restore-step-panel-5');
  if (panel) panel.classList.toggle('restore-live-mode', restoreState.liveMode);
  const out = document.getElementById('restore-precheck-output');
  const details = out?.closest('details');
  if (details) {
    details.open = restoreState.liveMode || details.open;
    const summary = details.querySelector('summary');
    if (summary) summary.textContent = restoreT(restoreState.liveMode ? 'liveLog' : 'showTechnicalPrecheck');
  }
  if (restoreState.liveMode) {
    renderRestorePrecheck(null);
    setRestoreHeaderStatus('running');
  }
}

function restoreJobIcon(job) {
  const icon = resolveJobIcon(job);
  const color = resolveJobIconColor(job);
  const colorClass = color ? ` type-icon-color-${color}` : '';
  return `<span class="type-icon type-icon-${escHtml(String(job?.backup_type || 'sonstiges').toLowerCase())} restore-sidebar-job-icon${colorClass}">${typeIcon(icon)}</span>`;
}

function renderRestoreJobSidebar() {
  const list = document.getElementById('restore-sidebar-job-list');
  if (!list) return;
  const query = String(document.getElementById('restore-sidebar-search')?.value || '').trim().toLowerCase();
  const jobs = (restoreState.jobs || []).filter((job) =>
    `${job.display_name || ''} ${job.name || ''} ${job.key || ''} ${job.location || ''}`.toLowerCase().includes(query)
  );
  if (!jobs.length) {
    list.innerHTML = `<div class="restore-sidebar-empty">${escHtml(restoreT('noMatchingJobs'))}</div>`;
    return;
  }
  const order = ['local', 'usb', 'smb', 'storagebox'];
  list.innerHTML = order.map((location) => {
    const locationJobs = jobs.filter((job) => String(job.location || '').toLowerCase() === location);
    if (!locationJobs.length) return '';
    return `<section class="restore-sidebar-group"><header>${escHtml(restoreLocationLabel(location))}<span>${locationJobs.length}</span></header>${locationJobs.map((job) => {
      const active = String(job.key) === String(restoreState.job);
      return `<button type="button" class="restore-sidebar-job ${active ? 'is-active' : ''}" data-restore-sidebar-job="${escHtml(job.key)}" ${active ? 'aria-current="page"' : ''}>${restoreJobIcon(job)}<span><strong>${escHtml(job.display_name || job.name || job.key)}</strong><small>${escHtml(job.key)}</small></span></button>`;
    }).join('')}</section>`;
  }).join('');
}

function restoreLocationLabel(location) {
  const key = String(location || '').toLowerCase();
  return ({
    storagebox: restoreT('locationStoragebox'),
    usb: restoreT('locationUsb'),
    smb: restoreT('locationSmb'),
    local: restoreT('locationLocal'),
  })[key] || location || '—';
}

function renderRestoreSelectedJob() {
  const card = document.getElementById('restore-selected-job-card');
  const badge = document.getElementById('restore-job-ready-badge');
  if (!card) return;
  const job = (restoreState.jobs || []).find((item) => String(item.key) === String(restoreState.job));
  if (!job) {
    card.innerHTML = `<span class="muted">${escHtml(restoreT('chooseJob'))}</span>`;
    if (badge) badge.textContent = '';
    return;
  }
  card.innerHTML = `${restoreJobIcon(job)}<div><small>${escHtml(restoreT('selectedJob'))}</small><h3>${escHtml(job.display_name || job.name || job.key)}</h3><small>${escHtml(job.key)} · ${escHtml(restoreLocationLabel(job.location))}</small></div><span class="ready">${escHtml(restoreT('ready'))}</span>`;
  if (badge) badge.textContent = restoreT('jobSelected');
}

function renderRestoreArchiveList() {
  const list = document.getElementById('restore-archive-list');
  const count = document.getElementById('restore-archive-count');
  const context = document.getElementById('restore-archive-context');
  if (!list) return;
  const job = (restoreState.jobs || []).find((item) => String(item.key) === String(restoreState.job));
  if (context) context.textContent = job?.display_name || job?.name || restoreState.job || '';
  if (count) count.textContent = restoreT('archiveCount', { count: restoreState.archives.length });
  list.innerHTML = restoreState.archives.map((archive) => {
    const active = String(archive.name) === String(restoreState.archive);
    const date = archive.start ? String(archive.start).substring(0, 19).replace('T', ' ') : '';
    return `<button type="button" class="restore-archive-row ${active ? 'is-selected' : ''}" data-restore-archive="${escHtml(archive.name)}"><span class="restore-archive-radio">${active ? '●' : '○'}</span><span><strong>${escHtml(archive.name)}</strong><small>${escHtml(date)}</small></span><span class="ui-badge">${escHtml(restoreT('available'))}</span></button>`;
  }).join('') || `<div class="restore-sidebar-empty">${escHtml(restoreT('noArchives'))}</div>`;
}

function onRestoreRedesignClick(event) {
  const jobButton = event.target.closest('[data-restore-sidebar-job]');
  if (jobButton) {
    const select = document.getElementById('restore-job-sel');
    if (!select) return;
    select.value = jobButton.dataset.restoreSidebarJob || '';
    restoreLoadArchives();
    restoreSetStep(1);
    return;
  }
  const archiveButton = event.target.closest('[data-restore-archive]');
  if (archiveButton) {
    const select = document.getElementById('restore-archive-sel');
    if (!select) return;
    select.value = archiveButton.dataset.restoreArchive || '';
    restoreBrowse('');
    restoreSetStep(2);
    return;
  }
  const stepButton = event.target.closest('[data-restore-step]');
  if (stepButton) {
    const step = Number(stepButton.dataset.restoreStep || 1);
    if (step <= restoreState.step || restoreCanAdvance(step - 1)) restoreSetStep(step);
  }
}

function restoreCanAdvance(step) {
  if (step === 1) return !!restoreState.job;
  if (step === 2) return !!restoreState.archive;
  if (step === 3) return !!restoreState.selectedPath;
  if (step === 4) return !!document.getElementById('restore-target-path')?.value?.trim();
  return true;
}

function restoreStepNext() {
  if (!restoreCanAdvance(restoreState.step)) {
    if (restoreState.step === 1) return _restoreMsg(restoreT('selectJobFirst'), true);
    if (restoreState.step === 2) return _restoreMsg(restoreT('selectArchiveFirst'), true);
    if (restoreState.step === 3) return _restoreMsg(restoreT('selectElementFirst'), true);
    if (restoreState.step === 4) return _restoreMsg(restoreT('enterTargetFirst'), true);
  }
  restoreSetStep(restoreState.step + 1);
}

function restoreStepBack() {
  if (restoreState.step === 5 && restoreState.completed) {
    restoreReloadWizard();
    return;
  }
  restoreSetStep(restoreState.step - 1);
}

function restoreReloadWizard() {
  restoreState.completed = false;
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  restoreState.selectedPath = '';
  restoreState.selectedName = '';
  restoreState.selectedType = '';
  restoreState.archive = '';
  restoreState.job = '';
  restoreState.path = '';
  restoreState.files = [];
  _stopRestorePolling();
  const out = document.getElementById('restore-precheck-output');
  if (out) out.textContent = '';
  hideEl('restore-assist-msg');
  restoreInit();
}

function _restoreSelectionReady() {
  const target = document.getElementById('restore-target-path')?.value?.trim() || '';
  return !!(restoreState.job && restoreState.archive && restoreState.selectedPath && target);
}

function _restoreRenderSelectionSummary() {
  const jobSel = document.getElementById('restore-job-sel');
  const jobText = jobSel?.selectedOptions?.[0]?.textContent?.trim() || '—';
  const archive = restoreState.archive || '—';
  const selectedCount = restoreState.selectedPath ? 1 : 0;
  const target = document.getElementById('restore-target-path')?.value?.trim() || '—';
  const jobEl = document.getElementById('restore-summary-job');
  const archEl = document.getElementById('restore-summary-archive');
  const countEl = document.getElementById('restore-summary-count');
  const targetEl = document.getElementById('restore-summary-target');
  if (jobEl) jobEl.textContent = jobText;
  if (archEl) archEl.textContent = archive;
  if (countEl) countEl.textContent = String(selectedCount);
  if (targetEl) targetEl.textContent = target;
  const modeEl = document.getElementById('restore-summary-mode');
  const dryRunEl = document.getElementById('restore-summary-dry-run');
  const mode = document.getElementById('restore-conflict-mode')?.selectedOptions?.[0]?.textContent || '—';
  const dryRun = document.getElementById('restore-dry-run')?.checked;
  if (modeEl) modeEl.textContent = mode;
  if (dryRunEl) dryRunEl.textContent = dryRun ? restoreT('yes') : restoreT('no');
  const browserContext = document.getElementById('restore-browser-context');
  if (browserContext) browserContext.textContent = restoreState.archive || '';
}

function _restoreRenderSelectedBox() {
  const typeEl = document.getElementById('restore-selected-type');
  const pathEl = document.getElementById('restore-selected-path');
  const hintEl = document.getElementById('restore-selected-hint');
  const type = restoreState.selectedType === 'd' ? restoreT('directory') : (restoreState.selectedType === 'f' ? restoreT('file') : '—');
  const hint = restoreState.selectedType === 'd'
    ? restoreT('directoryHint')
    : (restoreState.selectedType === 'f' ? restoreT('fileHint') : restoreT('nothingSelected'));
  if (typeEl) typeEl.textContent = type;
  if (pathEl) pathEl.textContent = restoreState.selectedPath || '—';
  if (hintEl) hintEl.textContent = hint;
  const nameEl = document.getElementById('restore-selection-name');
  if (nameEl) nameEl.textContent = restoreState.selectedName || '—';
}

function _stopRestorePolling() {
  if (restoreState.restorePollTimer) {
    clearTimeout(restoreState.restorePollTimer);
    restoreState.restorePollTimer = null;
  }
}

function restoreRunStateLabel(state) {
  const key = String(state || '').toLowerCase();
  return ({
    running: restoreT('runStateRunning'),
    done: restoreT('runStateDone'),
    error: restoreT('runStateError'),
    aborted: restoreT('runStateAborted'),
  })[key] || key || '—';
}

function restoreRunStateClass(state) {
  const key = String(state || '').toLowerCase();
  if (key === 'running') return 'warning';
  if (key === 'done') return 'success';
  if (key === 'error' || key === 'aborted') return 'error';
  return 'neutral';
}

function restoreFmtDuration(seconds) {
  const total = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) return restoreT('durationHoursMinutesSeconds', { hours, minutes, seconds: secs });
  if (minutes) return restoreT('durationMinutesSeconds', { minutes, seconds: secs });
  return restoreT('durationSeconds', { seconds: secs });
}

function renderRestoreRuns(runs) {
  const panel = document.getElementById('restore-runs-panel');
  const content = document.getElementById('restore-runs-content');
  if (!panel || !content) return;
  const rows = Array.isArray(runs) ? runs : [];
  const activeRuns = rows.filter((run) => String(run.state || '').toLowerCase() === 'running');
  if (!activeRuns.length) {
    panel.classList.add('hidden');
    content.innerHTML = '';
    return;
  }
  panel.classList.remove('hidden');
  const runCard = (run) => {
    const id = String(run.restore_id || '');
    const state = String(run.state || '');
    return `<article class="restore-run-card is-active">
      <div class="restore-run-main">
        <span class="ui-badge ${restoreRunStateClass(state)}">${escHtml(restoreRunStateLabel(state))}</span>
        <strong>${escHtml(run.job_key || '—')}</strong>
        <small>${escHtml(run.archive || '—')}</small>
      </div>
      <div class="restore-run-meta">
        <span>${escHtml(restoreT('targetDirectory'))}: <b>${escHtml(run.destination_path || run.target_dir || '—')}</b></span>
        <span>${escHtml(restoreT('runStarted'))}: <b>${escHtml(run.started_at || '—')}</b></span>
        ${run.phase ? `<span>${escHtml(restoreT('runPhase'))}: <b>${escHtml(run.phase)}</b></span>` : ''}
      </div>
      <button type="button" class="btn btn-primary btn-sm" data-restore-run-action="open" data-restore-id="${escHtml(id)}">${escHtml(restoreT('resumeLiveLog'))}</button>
    </article>`;
  };
  content.innerHTML = `<div class="restore-active-runs">
    <strong>${escHtml(restoreT('activeRestoreTitle'))}</strong>
    ${activeRuns.map((run) => runCard(run)).join('')}
  </div>`;
}

async function restoreLoadRuns() {
  try {
    const res = await fetch('/api/restore/runs?limit=10', { credentials: 'include' });
    const data = await res.json();
    if (!res.ok || data.error) return;
    restoreState.runs = Array.isArray(data.runs) ? data.runs : [];
    renderRestoreRuns(restoreState.runs);
  } catch (_) {
    // Restore runs are optional context; keep the wizard usable if loading fails.
  }
}

function renderRestoreHistory(payload) {
  const panel = document.getElementById('restore-history-panel');
  const content = document.getElementById('restore-history-content');
  const count = document.getElementById('restore-history-count');
  const migration = document.getElementById('restore-history-migration');
  if (!panel || !content) return;
  const rows = Array.isArray(payload?.runs) ? payload.runs : [];
  const total = Number(payload?.total || rows.length || 0);
  restoreState.history = rows;
  restoreState.historyTotal = total;
  if (count) count.textContent = total ? restoreT('historyCount', { count: total }) : '';

  const migrationState = payload?.migration || {};
  const migrationDetails = migrationState.details || {};
  if (migration && migrationState.status === 'failed') {
    migration.classList.remove('hidden');
    migration.textContent = restoreT('historyMigrationFailed', {
      count: migrationDetails.imported || 0,
      errors: (migrationDetails.errors || []).length,
    });
  } else if (migration) {
    migration.classList.add('hidden');
    migration.textContent = '';
  }

  if (!rows.length) {
    content.innerHTML = `<div class="restore-history-empty">${escHtml(restoreT('historyEmpty'))}</div>`;
    return;
  }

  content.innerHTML = rows.map((run) => {
    const id = String(run.restore_id || '');
    const selected = id && id === restoreState.historyDetailId;
    const state = String(run.state || '');
    return `<article class="restore-history-card ${selected ? 'is-selected' : ''}" data-restore-history-id="${escHtml(id)}">
      <div class="restore-run-main">
        <span class="ui-badge ${restoreRunStateClass(state)}">${escHtml(restoreRunStateLabel(state))}</span>
        <strong>${escHtml(run.job_key || '—')}</strong>
        <small>${escHtml(run.archive || '—')}</small>
      </div>
      <div class="restore-run-meta">
        <span>${escHtml(restoreT('targetDirectory'))}: <b>${escHtml(run.destination_path || run.target_dir || '—')}</b></span>
        <span>${escHtml(restoreT('runStarted'))}: <b>${escHtml(run.started_at || '—')}</b></span>
        <span>${escHtml(restoreT('historyFinished'))}: <b>${escHtml(run.finished_at || '—')}</b></span>
        <span>${escHtml(restoreT('historyDuration'))}: <b>${escHtml(restoreFmtDuration(run.duration_seconds))}</b></span>
      </div>
      <button type="button" class="btn btn-secondary btn-sm" data-restore-history-action="detail" data-restore-id="${escHtml(id)}">${escHtml(restoreT('showRunDetails'))}</button>
      <div class="restore-history-detail" id="restore-history-detail-${escHtml(id)}"></div>
    </article>`;
  }).join('');
}

async function restoreLoadHistory() {
  try {
    const res = await fetch('/api/restore/history?limit=10', { credentials: 'include' });
    const data = await res.json();
    if (!res.ok || data.error) return;
    renderRestoreHistory(data);
    if (restoreState.historyDetailId) {
      await restoreLoadHistoryDetail(restoreState.historyDetailId);
    }
  } catch (_) {
    // Restore history is supporting context; do not block the wizard on failures.
  }
}

function renderRestoreHistoryDetail(detail) {
  const id = String(detail?.restore_id || '');
  if (!id) return;
  const target = document.getElementById(`restore-history-detail-${id}`);
  if (!target) return;
  const lines = Array.isArray(detail.lines) ? detail.lines : [];
  target.innerHTML = `<div class="restore-history-detail-grid">
    <div><small>${escHtml(restoreT('runStatus'))}</small><strong>${escHtml(restoreRunStateLabel(detail.state))}</strong></div>
    <div><small>${escHtml(restoreT('sourcePath'))}</small><strong>${escHtml(detail.source_path || '—')}</strong></div>
    <div><small>${escHtml(restoreT('targetDirectory'))}</small><strong>${escHtml(detail.target_dir || '—')}</strong></div>
    <div><small>${escHtml(restoreT('destinationLabel'))}</small><strong>${escHtml(detail.destination_path || '—')}</strong></div>
    <div><small>${escHtml(restoreT('conflictStrategy'))}</small><strong>${escHtml(detail.conflict_mode || '—')}</strong></div>
    <div><small>${escHtml(restoreT('preserveOwnerShort'))}</small><strong>${escHtml(detail.preserve_owner ? restoreT('yes') : restoreT('no'))}</strong></div>
  </div>
  ${detail.error ? `<div class="restore-history-error">${escHtml(detail.error)}</div>` : ''}
  <details class="restore-history-log"><summary>${escHtml(restoreT('historyLog'))}</summary><pre>${escHtml(lines.join('\n') || restoreT('empty'))}</pre></details>`;
}

async function restoreLoadHistoryDetail(restoreId) {
  const id = String(restoreId || '').trim();
  if (!id) return;
  restoreState.historyDetailId = id;
  try {
    const res = await fetch(`/api/restore/history/detail?restore_id=${encodeURIComponent(id)}`, { credentials: 'include' });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(apiErrorMessage(data, res.status));
    renderRestoreHistory({ runs: restoreState.history, total: restoreState.historyTotal || restoreState.history.length });
    restoreState.historyDetailId = id;
    renderRestoreHistoryDetail(data);
  } catch (err) {
    const target = document.getElementById(`restore-history-detail-${id}`);
    if (target) target.innerHTML = `<div class="restore-history-error">${escHtml(err.message)}</div>`;
  }
}

function onRestoreRunsClick(event) {
  const btn = event.target.closest('[data-restore-run-action="open"]');
  if (!btn) return;
  const restoreId = String(btn.dataset.restoreId || '').trim();
  if (restoreId) restoreOpenRun(restoreId);
}

function onRestoreHistoryClick(event) {
  const btn = event.target.closest('[data-restore-history-action="detail"]');
  if (!btn) return;
  const restoreId = String(btn.dataset.restoreId || '').trim();
  if (restoreId) restoreLoadHistoryDetail(restoreId);
}

async function restoreOpenRun(restoreId) {
  _stopRestorePolling();
  restoreState.activeRestoreId = restoreId;
  restoreState.completed = false;
  restoreSetLiveMode(true);
  hideEl('restore-assist-msg');
  restoreSetStep(5);
  _setRestoreAssistBusy(true);
  await _pollRestoreState(restoreId);
}

async function _pollRestoreState(restoreId) {
  const out = document.getElementById('restore-precheck-output');
  if (!restoreId) return;
  try {
    const res = await fetch(`/api/restore/state?restore_id=${encodeURIComponent(restoreId)}`, { credentials: 'include' });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(apiErrorMessage(data, res.status));
    if (restoreState.activeRestoreId !== restoreId) return;

    const lines = Array.isArray(data.lines) ? data.lines : [];
    const phase = data.phase || 'running';
    if (out) {
      out.textContent = [
        restoreT('restoreId', { value: restoreId }),
        restoreT('status', { value: data.state || restoreT('running') }),
        restoreT('phase', { value: phase }),
        '',
        ...lines,
      ].join('\n');
      out.scrollTop = out.scrollHeight;
    }

    if (data.state === 'done') {
      _stopRestorePolling();
      _setRestoreAssistBusy(false);
      restoreState.completed = true;
      restoreUpdateConfirmState();
      restoreSetStep(5);
      restoreLoadRuns();
      restoreLoadHistory();
      if (data.skipped) {
        setRestoreHeaderStatus('skipped');
        const reasonKey = {
          target_exists: 'targetExists',
          target_not_empty: 'targetNotEmpty',
          target_unreadable: 'targetUnreadable',
        }[data.skip_reason_code] || 'targetExists';
        showMsg('restore-assist-msg', 'warning', restoreT('skipped', { reason: restoreT(reasonKey) }));
      } else {
        setRestoreHeaderStatus('success');
        showMsg('restore-assist-msg', 'success', restoreT('success', { path: data.destination_path || '' }));
      }
      return;
    }
    if (data.state === 'error' || data.state === 'aborted') {
      _stopRestorePolling();
      _setRestoreAssistBusy(false);
      restoreUpdateConfirmState();
      setRestoreHeaderStatus('failed');
      restoreLoadRuns();
      restoreLoadHistory();
      showMsg('restore-assist-msg', 'error', restoreT('failed', { message: data.error || restoreT('unknownError') }));
      return;
    }

    restoreState.restorePollTimer = setTimeout(() => _pollRestoreState(restoreId), 1500);
  } catch (err) {
    restoreState.restorePollTimer = setTimeout(() => _pollRestoreState(restoreId), 2000);
  }
}

function _restoreBindTargetAutocomplete() {
  const input = document.getElementById('restore-target-path');
  const datalist = document.getElementById('restore-target-suggestions');
  if (!input || !datalist || input.dataset.autocompleteBound === '1') return;
  input.dataset.autocompleteBound = '1';

  const applyOptions = (dirs) => {
    datalist.innerHTML = (dirs || []).map(p => `<option value="${escHtml(p)}"></option>`).join('');
  };

  const loadSuggestions = async (rawValue) => {
    const value = String(rawValue ?? input.value ?? '').trim();
    const prefix = value || '/mnt/user/';
    if (!prefix.startsWith('/mnt/user')) {
      applyOptions([]);
      return;
    }
    if (restoreState.targetSuggestCache.has(prefix)) {
      applyOptions(restoreState.targetSuggestCache.get(prefix));
      return;
    }
    const reqId = ++restoreState.targetSuggestReq;
    try {
      const res = await fetch(`/api/restore/target-dirs?prefix=${encodeURIComponent(prefix)}&limit=30`, { credentials: 'include' });
      const data = await res.json();
      if (!res.ok || data.error) return;
      if (reqId !== restoreState.targetSuggestReq) return;
      const dirs = (data.dirs || []).map(d => d.path).filter(Boolean);
      restoreState.targetSuggestCache.set(prefix, dirs);
      applyOptions(dirs);
    } catch (_) {
      // Silent fail: autocomplete is optional UX.
    }
  };

  input.addEventListener('focus', () => {
    if (!input.value.trim()) input.value = '/mnt/user/';
    loadSuggestions(input.value);
  });
  input.addEventListener('input', () => {
    if (restoreState.targetSuggestTimer) clearTimeout(restoreState.targetSuggestTimer);
    const current = input.value;
    restoreState.targetSuggestTimer = setTimeout(() => loadSuggestions(current), 120);
  });
  input.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter') return;
    const v = String(input.value || '').trim();
    if (!v.startsWith('/mnt/user')) return;
    const options = Array.from(datalist.options || []);
    const exact = options.find(o => o.value.replace(/\/+$/, '') === v.replace(/\/+$/, ''));
    if (exact && !v.endsWith('/')) {
      ev.preventDefault();
      input.value = `${v}/`;
      loadSuggestions(input.value);
    }
  });
}

async function restoreInit() {
  restoreState.completed = false;
  restoreSetLiveMode(false);
  const sel = document.getElementById('restore-job-sel');
  sel.innerHTML = `<option value="">${restoreT('chooseJob')}</option>`;
  const wizard = document.getElementById('restore-wizard');
  if (wizard) wizard.style.display = '';
  const empty = document.getElementById('restore-empty');
  if (empty) empty.style.display = 'none';
  restoreSetStep(1);
  _restoreMsg('');
  _restoreBindTargetAutocomplete();
  const targetInput = document.getElementById('restore-target-path');
  if (targetInput && !targetInput.value.trim()) targetInput.value = '/mnt/user/';
  _restoreRenderSelectionSummary();
  _restoreRenderSelectedBox();
  restoreLoadRuns();
  restoreLoadHistory();

  try {
    const jobsRes = await fetch('/api/jobs', { credentials: 'include' });
    const jobsData = await jobsRes.json();
    const jobs = (jobsData.jobs || []).filter(j => !j.is_utility);
    restoreState.jobs = jobs;

    for (const job of jobs) {
      if (job.is_utility) continue;
      const opt = document.createElement('option');
      opt.value = job.key;
      opt.textContent = job.display_name || job.name || job.key;
      sel.appendChild(opt);
    }

    if (!jobs.length) {
      const checkRes = await fetch('/api/storage/check/jobs', { credentials: 'include' });
      if (checkRes.ok) {
        const checkData = await checkRes.json();
        for (const job of (checkData.jobs || [])) {
          const opt = document.createElement('option');
          opt.value = job.key;
          opt.textContent = job.name || job.key;
          sel.appendChild(opt);
        }
        restoreState.jobs = (checkData.jobs || []).map((job) => ({ ...job, location: job.location || 'local' }));
      }
    }
    renderRestoreJobSidebar();
    renderRestoreSelectedJob();
  } catch (e) {
    _restoreMsg(restoreT('loadJobsError', { message: e.message }), true);
  }
}

async function restoreLoadArchives() {
  const jobKey = document.getElementById('restore-job-sel').value;
  restoreState.job = jobKey;
  restoreState.archive = '';
  restoreState.path = '';
  restoreState.selectedPath = '';
  restoreState.selectedName = '';
  restoreState.selectedType = '';
  restoreState.autoPrecheckKey = '';
  restoreState.archives = [];
  const sel = document.getElementById('restore-archive-sel');
  if (sel) sel.innerHTML = `<option value="">${restoreT('chooseArchive')}</option>`;
  _restoreMsg('');

  if (!jobKey) {
    _restoreRenderSelectionSummary();
    _restoreRenderSelectedBox();
    return;
  }
  renderRestoreJobSidebar();
  renderRestoreSelectedJob();
  _restoreMsg(restoreT('loadingArchives'));

  try {
    const res = await fetch(`/api/restore/archives?job=${encodeURIComponent(jobKey)}`, { credentials: 'include' });
    const data = await res.json();
    if (!res.ok || data.error) { _restoreMsg(restoreT('error', { message: apiErrorMessage(data, res.status) }), true); return; }

    const sel = document.getElementById('restore-archive-sel');
    sel.innerHTML = `<option value="">${restoreT('chooseArchive')}</option>`;
    restoreState.archives = data.archives || [];
    for (const a of restoreState.archives) {
      const opt = document.createElement('option');
      opt.value = a.name;
      const date = a.start ? a.start.substring(0, 19).replace('T', ' ') : '';
      opt.textContent = a.name + (date ? '  (' + date + ')' : '');
      sel.appendChild(opt);
    }
    renderRestoreArchiveList();
    _restoreRenderSelectionSummary();
    _restoreMsg('');
  } catch (e) {
    _restoreMsg(restoreT('error', { message: e.message }), true);
  }
}

async function restoreBrowse(path) {
  const jobKey = restoreState.job;
  const archive = document.getElementById('restore-archive-sel').value;
  if (!archive) return;

  restoreState.archive = archive;
  restoreState.path = path;
  _restoreRenderSelectionSummary();
  renderRestoreArchiveList();
  _restoreMsg('');
  const browser = document.getElementById('restore-browser');
  const filelist = document.getElementById('restore-filelist');
  if (browser) browser.style.display = '';
  if (filelist) {
    filelist.innerHTML = `
      <div class="loading-spinner" style="padding:22px 16px">
        <div class="spinner"></div>
        <span>${restoreT('loadingFiles')}</span>
      </div>`;
  }

  try {
    const url = `/api/restore/files?job=${encodeURIComponent(jobKey)}&archive=${encodeURIComponent(archive)}&path=${encodeURIComponent(path)}`;
    const res = await fetch(url, { credentials: 'include' });
    const data = await res.json();
    if (!res.ok || data.error) { _restoreMsg(restoreT('error', { message: apiErrorMessage(data, res.status) }), true); return; }

    _restoreMsg('');
    _restoreRenderBreadcrumb(path);
    restoreState.files = data.files || [];
    _restoreRenderFiles(restoreState.files);
  } catch (e) {
    _restoreMsg(restoreT('error', { message: e.message }), true);
  }
}

function _restoreRenderBreadcrumb(path) {
  const parts = path ? path.split('/') : [];
  let html = `<span class="bc-link" data-restore-action="browse" data-path="/">/</span>`;
  let cum = '';
  for (let i = 0; i < parts.length; i++) {
    cum = parts.slice(0, i + 1).join('/');
    const p = cum;
    html += ` / <span class="${i === parts.length - 1 ? 'bc-current' : 'bc-link'}" data-restore-action="browse" data-path="${escHtml(p)}">${escHtml(parts[i])}</span>`;
  }
  document.getElementById('restore-breadcrumb').innerHTML = html;
}

function _restoreRenderFiles(files) {
  const el = document.getElementById('restore-filelist');
  if (!files.length) {
    el.innerHTML = `<div class="restore-empty">${restoreT('noFiles')}</div>`;
    return;
  }

  let rows = '';
  for (const f of files) {
    const isSelected = String(f.path || '') === String(restoreState.selectedPath || '');
    const icon = f.type === 'd' ? '📁' : (f.type === 'l' ? '🔗' : '📄');
    const size = f.type === 'd' ? '—' : _restoreFmtSize(f.size);
    const mtime = f.mtime ? f.mtime.substring(0, 19).replace('T', ' ') : '';
    const nameCell = f.type === 'd'
      ? `<span class="restore-dir-link" data-restore-action="browse" data-path="${escHtml(f.path)}">${icon} ${escHtml(f.name)}</span>`
      : `<span>${icon} ${escHtml(f.name)}</span>`;

    rows += `<tr class="${isSelected ? 'restore-row-selected' : ''}">
      <td class="restore-col-name">${nameCell}</td>
      <td class="restore-col-size">${size}</td>
      <td class="restore-col-date">${mtime}</td>
      <td class="restore-col-action">
        <button class="restore-icon-btn" data-restore-action="download" data-path="${escHtml(f.path)}" title="${restoreT('download')}" aria-label="${restoreT('download')}">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 4v10m0 0l-4-4m4 4l4-4M5 20h14"/>
          </svg>
        </button>
        <button class="restore-icon-btn ${isSelected ? 'restore-icon-btn-selected' : ''}" data-restore-action="select" data-path="${escHtml(f.path)}" data-name="${escHtml(f.name)}" data-type="${escHtml(f.type || '')}" title="${isSelected ? restoreT('selected') : restoreT('select')}" aria-label="${isSelected ? restoreT('selected') : restoreT('select')}">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20 6 9 17l-5-5"/>
          </svg>
        </button>
      </td>
    </tr>`;
  }

  el.innerHTML = `<table class="restore-table">
    <thead><tr>
      <th>${restoreT('name')}</th><th>${restoreT('size')}</th><th>${restoreT('date')}</th><th></th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function onRestoreBrowserClick(event) {
  const el = event.target.closest('[data-restore-action]');
  if (!el) return;
  const action = el.dataset.restoreAction || '';
  const path = (el.dataset.path || '').replace(/^\/$/, '');
  const name = el.dataset.name || '';
  const type = el.dataset.type || '';
  if (action === 'browse') return restoreBrowse(path);
  if (action === 'download') return restoreDownload(path);
  if (action === 'select' && path && path === restoreState.selectedPath) return restoreClearSelection();
  if (action === 'select') return restorePrepare(path, name, type);
}

async function restoreDownload(path) {
  const fileList = document.getElementById('restore-filelist');
  const originalHtml = fileList ? fileList.innerHTML : '';
  _restoreMsg(restoreT('checkingDownloadSize'));
  if (fileList) {
    fileList.innerHTML = `
      <div class="loading-spinner" style="padding:22px 16px">
        <div class="spinner"></div>
        <span>${restoreT('checkingDownloadSize')}</span>
      </div>`;
  }
  try {
    const baseParams = `job=${encodeURIComponent(restoreState.job)}&archive=${encodeURIComponent(restoreState.archive)}&path=${encodeURIComponent(path)}`;
    const checkRes = await fetch(`/api/restore/download-check?${baseParams}`, { credentials: 'include' });
    const checkData = await checkRes.json();
    if (!checkRes.ok || checkData?.error) {
      throw new Error(apiErrorMessage(checkData, checkRes.status));
    }

    if (checkData.action === 'block') {
      if (fileList) fileList.innerHTML = originalHtml;
      const message = apiMessage(checkData, restoreT('downloadBlocked'));
      _restoreMsg(message, 'warn');
      showMsg('restore-assist-msg', 'error', message);
      return;
    }

    let url = `/api/restore/download?${baseParams}`;
    if (checkData.action === 'confirm') {
      if (fileList) fileList.innerHTML = originalHtml;
      _restoreMsg('');
      const ok = await openRestoreDownloadConfirmModal(apiMessage(checkData, restoreT('largeDownload')));
      if (!ok) return;
      url += '&confirm_large=1';
    }
    if (fileList) fileList.innerHTML = originalHtml;
    _restoreMsg(restoreT('downloadStarting'));
    window.location.href = url;
  } catch (e) {
    if (fileList) fileList.innerHTML = originalHtml;
    _restoreMsg(restoreT('downloadFailed', { message: e.message }), true);
    showMsg('restore-assist-msg', 'error', restoreT('downloadFailed', { message: e.message }));
  }
}

function restorePrepare(path, name, type) {
  restoreState.selectedPath = path || '';
  restoreState.selectedName = name || '';
  restoreState.selectedType = type === 'd' ? 'd' : 'f';
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  restoreState.completed = false;
  const src = document.getElementById('restore-source-path');
  const out = document.getElementById('restore-precheck-output');
  const target = document.getElementById('restore-target-path');
  const startBtn = document.getElementById('restore-start-btn');
  const confirmCheck = document.getElementById('restore-confirm-check');
  if (src) src.value = path || '';
  if (out) out.textContent = '';
  if (startBtn) startBtn.disabled = true;
  if (confirmCheck) confirmCheck.checked = false;
  hideEl('restore-assist-msg');
  _restoreRenderSelectedBox();
  // Auswahl bleibt in Schritt 3 sichtbar; Wechsel nach Schritt 4 erfolgt über "Weiter".
  restoreSetStep(Math.max(3, restoreState.step));
  _restoreRenderSelectionSummary();
  restoreUpdateConfirmState();
  _restoreMsg(restoreT('elementSelected'), false);
}

function restoreClearSelection() {
  restoreState.selectedPath = '';
  restoreState.selectedName = '';
  restoreState.selectedType = '';
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  restoreState.completed = false;
  restoreState.activeRestoreId = '';
  const src = document.getElementById('restore-source-path');
  const out = document.getElementById('restore-precheck-output');
  const confirmCheck = document.getElementById('restore-confirm-check');
  const targetInput = document.getElementById('restore-target-path');
  const modeSel = document.getElementById('restore-conflict-mode');
  const dryRun = document.getElementById('restore-dry-run');
  const preserveOwner = document.getElementById('restore-preserve-owner');
  const startBtn = document.getElementById('restore-start-btn');
  if (src) src.value = '';
  if (out) out.textContent = '';
  if (confirmCheck) confirmCheck.checked = false;
  if (targetInput) targetInput.value = '/mnt/user/';
  if (modeSel) modeSel.value = 'skip';
  if (dryRun) dryRun.checked = true;
  if (preserveOwner) preserveOwner.checked = false;
  if (startBtn) startBtn.disabled = true;
  _stopRestorePolling();
  hideEl('restore-assist-msg');
  _restoreMsg('');
  _restoreRenderSelectedBox();
  _restoreRenderSelectionSummary();
  restoreSetStep(3);
  restoreUpdateConfirmState();
  if (restoreState.archive) {
    restoreBrowse(restoreState.path || '');
  }
}

function restoreUpdateConfirmState() {
  const startBtn = document.getElementById('restore-start-btn');
  const confirmCheck = document.getElementById('restore-confirm-check');
  const enabled = !!(_restoreSelectionReady() && restoreState.precheck && restoreState.precheck.ok && confirmCheck?.checked);
  if (startBtn) startBtn.disabled = !enabled;
}

function _isAllowedRestoreTarget(target) {
  const t = String(target || '').trim();
  return t === '/mnt/user' || t.startsWith('/mnt/user/');
}

function _setRestoreAssistBusy(busy) {
  const preBtn = document.getElementById('restore-precheck-btn');
  const startBtn = document.getElementById('restore-start-btn');
  const confirmCheck = document.getElementById('restore-confirm-check');
  const modeSel = document.getElementById('restore-conflict-mode');
  const targetInput = document.getElementById('restore-target-path');
  const dryRunCheck = document.getElementById('restore-dry-run');
  if (preBtn) preBtn.disabled = !!busy;
  if (startBtn) startBtn.disabled = !!busy || startBtn.disabled;
  if (confirmCheck) confirmCheck.disabled = !!busy;
  if (modeSel) modeSel.disabled = !!busy;
  if (targetInput) targetInput.disabled = !!busy;
  if (dryRunCheck) dryRunCheck.disabled = !!busy;
}

async function restoreRunPrecheck() {
  restoreSetLiveMode(false);
  hideEl('restore-assist-msg');
  const source = restoreState.selectedPath || document.getElementById('restore-source-path')?.value || '';
  const target = document.getElementById('restore-target-path')?.value?.trim() || '';
  const mode = document.getElementById('restore-conflict-mode')?.value || 'skip';
  const dryRun = !!document.getElementById('restore-dry-run')?.checked;
  const out = document.getElementById('restore-precheck-output');
  const confirmCheck = document.getElementById('restore-confirm-check');
  if (confirmCheck) confirmCheck.checked = false;
  if (out) out.textContent = restoreT('precheckRunning');
  _setRestoreAssistBusy(true);
  if (!restoreState.job || !restoreState.archive || !source || !target) {
    showMsg('restore-assist-msg', 'error', restoreT('precheckInputsMissing'));
    if (out) out.textContent = '';
    _setRestoreAssistBusy(false);
    return;
  }
  if (!_isAllowedRestoreTarget(target)) {
    showMsg('restore-assist-msg', 'error', restoreT('targetRestriction'));
    if (out) out.textContent = '';
    _setRestoreAssistBusy(false);
    return;
  }
  try {
    const res = await fetch('/api/restore/precheck', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_key: restoreState.job,
        archive: restoreState.archive,
        source_path: source,
        target_dir: target,
        conflict_mode: mode,
        dry_run: dryRun,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    restoreState.precheck = data;
    renderRestorePrecheck(data);
    const combinedDryRun = [data.dry_run_stdout || '', data.dry_run_stderr || '']
      .filter(Boolean)
      .join('\n')
      .trim();
    const lines = [
      restoreT('archiveValue', { value: data.archive }),
      restoreT('source', { value: data.source_path }),
      restoreT('targetPath', { value: data.target_dir }),
      restoreT('conflictMode', { value: data.conflict_mode }),
      restoreT('dryRunResult', { value: data.dry_run ? restoreT('yes') : restoreT('no'), exit: data.dry_run_exit_code }),
      restoreT('destination', { value: data.destination_path }),
      restoreT('alreadyExists', { value: data.destination_exists ? restoreT('yes') : restoreT('no') }),
      restoreT('mountpoint', { value: data.target_mountpoint }),
      restoreT('freeSpace', { value: _restoreFmtSize(data.target_free_bytes || 0) }),
      '',
      restoreT('dryRunOutput'),
      combinedDryRun || restoreT('empty'),
    ];
    if (out) out.textContent = lines.join('\n');
    showMsg('restore-assist-msg', data.ok ? 'success' : 'error', data.ok ? restoreT('precheckSuccess') : restoreT('precheckFailed'));
  } catch (err) {
    restoreState.precheck = null;
    renderRestorePrecheck(null);
    if (out) out.textContent = '';
    showMsg('restore-assist-msg', 'error', restoreT('precheckError', { message: err.message }));
  } finally {
    _setRestoreAssistBusy(false);
    restoreUpdateConfirmState();
  }
}

function renderRestorePrecheck(data) {
  const verdict = document.getElementById('restore-precheck-verdict');
  const badge = document.getElementById('restore-precheck-badge');
  const facts = document.getElementById('restore-system-check-facts');
  if (!verdict || !facts) return;
  if (!data) {
    verdict.classList.add('hidden');
    facts.innerHTML = '';
    if (badge) {
      badge.textContent = restoreT('precheckPending');
      badge.classList.remove('success', 'warning', 'error');
    }
    return;
  }
  const ok = !!data.ok;
  verdict.classList.remove('hidden');
  verdict.classList.toggle('error', !ok);
  verdict.innerHTML = `<span class="restore-precheck-verdict-mark">${ok ? '✓' : '!'}</span><span><strong>${escHtml(restoreT(ok ? 'precheckVerdictOk' : 'precheckVerdictFailed'))}</strong><small>${escHtml(restoreT(ok ? 'precheckVerdictOkDetail' : 'precheckVerdictFailedDetail'))}</small></span>`;
  facts.innerHTML = [
    [restoreT('mountpointLabel'), data.target_mountpoint || '—'],
    [restoreT('freeSpaceLabel'), _restoreFmtSize(data.target_free_bytes || 0)],
    [restoreT('destinationExistsLabel'), data.destination_exists ? restoreT('yes') : restoreT('no')],
    [restoreT('dryRunExitLabel'), data.dry_run_exit_code ?? '—'],
  ].map(([label, value]) => `<div><small>${escHtml(label)}</small><strong>${escHtml(String(value))}</strong></div>`).join('');
  if (badge) {
    badge.textContent = restoreT(ok ? 'precheckSuccessful' : 'precheckFailedShort');
    badge.classList.remove('success', 'warning', 'error');
    badge.classList.add(ok ? 'success' : 'error');
  }
}

function setRestoreHeaderStatus(state) {
  const badge = document.getElementById('restore-precheck-badge');
  if (!badge) return;
  const key = {
    success: 'restoreSuccessfulShort',
    skipped: 'restoreSkippedShort',
    failed: 'restoreFailedShort',
    running: 'restoreRunningShort',
  }[state] || 'precheckSuccessful';
  badge.textContent = restoreT(key);
  badge.classList.remove('success', 'warning', 'error');
  if (state === 'success') badge.classList.add('success');
  if (state === 'skipped') badge.classList.add('warning');
  if (state === 'failed') badge.classList.add('error');
  if (state === 'running') badge.classList.add('warning');
}

function _currentPrecheckKey() {
  const source = restoreState.selectedPath || document.getElementById('restore-source-path')?.value || '';
  const target = document.getElementById('restore-target-path')?.value?.trim() || '';
  const mode = document.getElementById('restore-conflict-mode')?.value || 'skip';
  const dryRun = !!document.getElementById('restore-dry-run')?.checked;
  return JSON.stringify([restoreState.job, restoreState.archive, source, target, mode, dryRun]);
}

function restoreEnsureAutoPrecheck() {
  const key = _currentPrecheckKey();
  if (!restoreCanAdvance(4)) {
    restoreState.precheck = null;
    restoreUpdateConfirmState();
    return;
  }
  if (restoreState.precheck?.ok && restoreState.autoPrecheckKey === key) {
    restoreUpdateConfirmState();
    return;
  }
  restoreState.autoPrecheckKey = key;
  restoreRunPrecheck();
}

async function restoreStart() {
  const source = restoreState.selectedPath || document.getElementById('restore-source-path')?.value || '';
  const target = document.getElementById('restore-target-path')?.value?.trim() || '';
  const mode = document.getElementById('restore-conflict-mode')?.value || 'skip';
  const preserveOwner = !!document.getElementById('restore-preserve-owner')?.checked;
  const confirmCheck = !!document.getElementById('restore-confirm-check')?.checked;
  if (!confirmCheck || !restoreState.precheck?.ok) {
    showMsg('restore-assist-msg', 'error', restoreT('confirmPrecheckFirst'));
    return;
  }
  if (!_isAllowedRestoreTarget(target)) {
    showMsg('restore-assist-msg', 'error', restoreT('targetRestriction'));
    return;
  }
  const summary = [
    restoreT('archiveValue', { value: restoreState.archive }),
    restoreT('source', { value: source }),
    restoreT('targetPath', { value: target }),
    restoreT('conflictMode', { value: mode }),
    restoreT('ownerGroup', { value: preserveOwner ? restoreT('ownerFromBackup') : restoreT('ownerFromTarget') }),
  ].join('\n');
  const confirmed = await openRestoreConfirmModal(summary);
  if (!confirmed) return;
  restoreSetLiveMode(true);
  const out = document.getElementById('restore-precheck-output');
  if (out) {
    out.textContent = [
      restoreT('restoreRunning'),
      restoreT('archiveValue', { value: restoreState.archive }),
      restoreT('sourceShort', { value: source }),
      restoreT('targetShort', { value: target }),
      restoreT('mode', { value: mode }),
      restoreT('ownerGroup', { value: preserveOwner ? restoreT('ownerFromBackup') : restoreT('ownerFromTarget') }),
      '',
      restoreT('wait')
    ].join('\n');
  }
  showMsg('restore-assist-msg', 'warning', restoreT('restoreRunningShort'));
  _setRestoreAssistBusy(true);
  _stopRestorePolling();
  restoreState.activeRestoreId = '';
  try {
    const res = await fetch('/api/restore/start', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        confirm: true,
        job_key: restoreState.job,
        archive: restoreState.archive,
        source_path: source,
        target_dir: target,
        conflict_mode: mode,
        preserve_owner: preserveOwner,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const restoreId = String(data.restore_id || '').trim();
    if (!restoreId) {
      throw new Error(restoreT('missingRestoreId'));
    }
    restoreState.activeRestoreId = restoreId;
    restoreState.completed = false;
    if (out) {
      out.textContent += `\n\n${restoreT('restoreId', { value: restoreId })}\n${restoreT('status', { value: restoreT('started') })}`;
    }
    _pollRestoreState(restoreId);
  } catch (err) {
    _stopRestorePolling();
    restoreState.activeRestoreId = '';
    _setRestoreAssistBusy(false);
    restoreUpdateConfirmState();
    showMsg('restore-assist-msg', 'error', restoreT('failed', { message: err.message }));
    if (out) out.textContent += `\n\n${restoreT('resultError')}\n${err.message}`;
  }
}

function openRestoreConfirmModal(summaryText) {
  return new Promise((resolve) => {
    const modal = document.getElementById('restore-confirm-modal');
    const summary = document.getElementById('restore-confirm-summary');
    if (!modal || !summary) {
      resolve(window.confirm(`${restoreT('confirmStart')}\n\n${summaryText}`));
      return;
    }
    restoreState.confirmResolver = resolve;
    summary.textContent = summaryText || '';
    modal.classList.remove('hidden');
  });
}

function closeRestoreConfirmModal(confirmed = false) {
  const modal = document.getElementById('restore-confirm-modal');
  if (modal) modal.classList.add('hidden');
  if (restoreState.confirmResolver) {
    const done = restoreState.confirmResolver;
    restoreState.confirmResolver = null;
    done(!!confirmed);
  }
}

function openRestoreDownloadConfirmModal(messageText) {
  return new Promise((resolve) => {
    const modal = document.getElementById('restore-download-confirm-modal');
    const msg = document.getElementById('restore-download-confirm-message');
    if (!modal || !msg) {
      resolve(window.confirm(messageText || restoreT('continueLargeDownload')));
      return;
    }
    restoreState.downloadConfirmResolver = resolve;
    msg.textContent = messageText || restoreT('continueLargeDownload');
    modal.classList.remove('hidden');
  });
}

function closeRestoreDownloadConfirmModal(confirmed = false) {
  const modal = document.getElementById('restore-download-confirm-modal');
  if (modal) modal.classList.add('hidden');
  if (restoreState.downloadConfirmResolver) {
    const done = restoreState.downloadConfirmResolver;
    restoreState.downloadConfirmResolver = null;
    done(!!confirmed);
  }
}

function _restoreFmtSize(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
  return bytes.toFixed(i > 0 ? 1 : 0) + '\u00a0' + units[i];
}

function _restoreMsg(msg, level = 'info') {
  const el = document.getElementById('restore-msg');
  if (!msg) {
    el.classList.add('hidden');
    el.classList.remove('restore-msg-error', 'restore-msg-warn', 'restore-msg-info');
    el.textContent = '';
    return;
  }
  el.classList.remove('hidden');
  el.classList.remove('restore-msg-error', 'restore-msg-warn', 'restore-msg-info');
  const resolved = (level === true) ? 'error' : (level === false ? 'info' : String(level || 'info'));
  if (resolved === 'error') el.classList.add('restore-msg-error');
  else if (resolved === 'warn') el.classList.add('restore-msg-warn');
  else el.classList.add('restore-msg-info');
  el.textContent = msg;
}

function restoreTargetInputChanged() {
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  restoreState.completed = false;
  _restoreRenderSelectionSummary();
  restoreUpdateConfirmState();
}

function restorePrecheckInputsChanged() {
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  restoreState.completed = false;
  _restoreRenderSelectionSummary();
  restoreUpdateConfirmState();
  if (restoreState.step === 5) {
    restoreEnsureAutoPrecheck();
  }
}

window.addEventListener?.('bbui:language-changed', () => {
  _restoreRenderSelectionSummary();
  _restoreRenderSelectedBox();
  if (Array.isArray(restoreState.files) && restoreState.files.length) {
    _restoreRenderFiles(restoreState.files);
  }
  renderRestoreJobSidebar();
  renderRestoreSelectedJob();
  renderRestoreArchiveList();
  renderRestorePrecheck(restoreState.precheck);
  renderRestoreHistory({ runs: restoreState.history, total: restoreState.historyTotal || restoreState.history.length });
  const backBtn = document.getElementById('restore-step-back-btn');
  const nextBtn = document.getElementById('restore-step-next-btn');
  if (backBtn) {
    backBtn.textContent = restoreState.step === 5 && restoreState.completed
      ? restoreT('close')
      : restoreT('back');
  }
  if (nextBtn) {
    nextBtn.textContent = restoreState.step === 4 ? restoreT('toCheck') : restoreT('next');
  }
});
