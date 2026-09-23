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
  selections: [],
  folderFilter: '',
  folderTree: null,
  selectedName: '',
  selectedType: '',
  precheck: null,
  targetSuggestTimer: null,
  targetSuggestReq: 0,
  targetSuggestCache: new Map(),
  confirmResolver: null,
  downloadConfirmResolver: null,
  historyDeleteConfirmResolver: null,
  activeRestoreId: '',
  restorePollTimer: null,
  autoPrecheckKey: '',
  completed: false,
  files: [],
  jobs: [],
  archives: [],
  archiveFilters: [],
  archiveFilterMode: 'job',
  archiveFilterPattern: '',
  sourceRequest: 0,
  filesRequest: 0,
  runs: [],
  history: [],
  historyTotal: 0,
  historyDetailId: '',
  view: 'wizard',
  liveMode: false,
  runSnapshot: null,
  allowedTargetRoots: ['/mnt/user'],
};
const restoreState = window.BBUI.restoreState;

function restoreT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(`restore.${key}`, params) || `restore.${key}`;
}

function restorePrecheckErrorMessage(payload, status = 0) {
  const data = payload && typeof payload === 'object' ? payload : {};
  const code = String(data.code || '').trim();
  const serverMessage = String(data.message || data.details || data.error || '').trim();
  if (code === 'bad_request' && serverMessage) return serverMessage;
  return apiErrorMessage(payload, status);
}

function restoreStatusIcon(status) {
  const icons = {
    success: '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.5 2.2 2.2 4.8-5.4"/>',
    warning: '<path d="M10.3 4.4a2 2 0 0 1 3.4 0l7.4 12.8a2 2 0 0 1-1.7 3H4.6a2 2 0 0 1-1.7-3z"/><path d="M12 8.8v4.8"/><path d="M12 17h.01"/>',
    error: '<circle cx="12" cy="12" r="8.5"/><path d="m9 9 6 6"/><path d="m15 9-6 6"/>',
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${icons[status] || icons.warning}</svg>`;
}

/**
 * Show a clamped restore wizard step and update navigation/precheck state.
 * @param {number} step Requested step from one through five.
 */
function restoreSetStep(step) {
  const next = Math.max(1, Math.min(5, Number(step) || 1));
  restoreState.step = next;
  document.getElementById('restore-wizard')?.classList.toggle('restore-selection-steps', next >= 3);
  for (let i = 1; i <= 5; i++) {
    const panel = document.getElementById(`restore-step-panel-${i}`);
    if (panel) panel.style.display = i === next ? '' : 'none';
    const badge = document.getElementById(`restore-step-badge-${i}`);
    if (badge) {
      const done = i < next || (i === 5 && next === 5 && restoreState.completed
        && restoreState.runSnapshot?.state === 'done' && !restoreState.runSnapshot.skipped);
      badge.classList.toggle('is-active', i === next);
      badge.classList.toggle('is-done', done);
      badge.setAttribute('aria-current', i === next ? 'step' : 'false');
      const number = badge.querySelector('span');
      if (number) number.textContent = done ? '✓' : String(i);
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
  _restoreRenderSelectionSummary();
}

/** Switch step five between precheck and running/completed restore views. */
function restoreSetLiveMode(enabled) {
  restoreState.liveMode = !!enabled;
  const panel = document.getElementById('restore-step-panel-5');
  if (panel) panel.classList.toggle('restore-live-mode', restoreState.liveMode);
  document.getElementById('restore-run-status')?.classList.toggle('hidden', !restoreState.liveMode);
  for (const [id, key] of [
    ['restore-run-heading', restoreState.liveMode ? 'runHeading' : 'checkStartTitle'],
    ['restore-run-subtitle', restoreState.liveMode ? 'runSubtitle' : 'checkStartSubtitle'],
  ]) {
    const el = document.getElementById(id);
    if (el) { el.dataset.i18n = `restore.${key}`; el.textContent = restoreT(key); }
  }
  if (restoreState.liveMode) {
    renderRestorePrecheck(null);
    setRestoreHeaderStatus('running');
  }
}

/** Open the restore wizard or history, loading history when selected. */
function restoreSwitchView(view) {
  const next = view === 'history' ? 'history' : 'wizard';
  if (restoreState.view !== next) window.BBUI?.utils?.dom?.clearPageFeedback?.();
  restoreState.view = next;
  const wizardBtn = document.getElementById('restore-view-wizard-btn');
  const historyBtn = document.getElementById('restore-view-history-btn');
  const historyPanel = document.getElementById('restore-history-panel');
  const wizard = document.getElementById('restore-wizard');
  const empty = document.getElementById('restore-empty');
  if (wizardBtn) {
    wizardBtn.classList.toggle('is-active', next === 'wizard');
    wizardBtn.setAttribute('aria-selected', next === 'wizard' ? 'true' : 'false');
  }
  if (historyBtn) {
    historyBtn.classList.toggle('is-active', next === 'history');
    historyBtn.setAttribute('aria-selected', next === 'history' ? 'true' : 'false');
  }
  if (historyPanel) historyPanel.classList.toggle('hidden', next !== 'history');
  if (wizard) wizard.style.display = next === 'wizard' ? '' : 'none';
  if (empty) empty.style.display = 'none';
  if (next === 'history') restoreLoadHistory();
}

function restoreJobIcon(job) {
  const icon = resolveJobIcon(job);
  const color = resolveJobIconColor(job);
  const colorClass = color ? ` type-icon-color-${color}` : '';
  return `<span class="type-icon restore-sidebar-job-icon${colorClass}">${typeIcon(icon)}</span>`;
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
      return `<button type="button" class="restore-sidebar-job ${active ? 'is-active' : ''}" data-restore-sidebar-job="${escHtml(job.key)}" ${active ? 'aria-current="page"' : ''}>${restoreJobIcon(job)}<span><strong>${escHtml(job.name || job.display_name || job.key)}</strong><small>${escHtml(job.archive_prefix || '')}</small></span></button>`;
    }).join('')}</section>`;
  }).join('');
}

function restoreJobName(key) {
  const job = (restoreState.jobs || []).find((item) => String(item.key) === String(key));
  return job?.name || job?.display_name || key || '—';
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
  card.innerHTML = `${restoreJobIcon(job)}<div><small>${escHtml(restoreT('selectedJob'))}</small><h3>${escHtml(job.name || job.display_name || job.key)}</h3><small>${escHtml(job.archive_prefix || '')} · ${escHtml(restoreLocationLabel(job.location))}</small></div><span class="ready">${escHtml(restoreT('ready'))}</span>`;
  if (badge) badge.textContent = restoreT('jobSelected');
}

function renderRestoreArchiveList() {
  const list = document.getElementById('restore-archive-list');
  const count = document.getElementById('restore-archive-count');
  const context = document.getElementById('restore-archive-context');
  const filtersEl = document.getElementById('restore-archive-filter-summary');
  if (!list) return;
  const job = (restoreState.jobs || []).find((item) => String(item.key) === String(restoreState.job));
  if (context) context.textContent = job?.display_name || job?.name || restoreState.job || '';
  if (count) count.textContent = restoreT('archiveCount', { count: restoreState.archives.length });
  if (filtersEl) {
    const filters = Array.isArray(restoreState.archiveFilters) ? restoreState.archiveFilters : [];
    const current = filters.find((item) => item?.current) || filters[0] || null;
    const custom = restoreState.archiveFilterMode === 'custom';
    const currentFilter = custom ? restoreState.archiveFilterPattern : String(current?.filter || '').trim();
    filtersEl.hidden = !currentFilter;
    filtersEl.innerHTML = currentFilter
      ? `<span>${escHtml(restoreT('archiveFilterLabel'))}</span><code class="restore-archive-filter-chip is-current">${escHtml(currentFilter)}</code>${custom ? '' : restoreArchiveFilterPopover(filters)}`
      : '';
  }
  list.innerHTML = restoreState.archives.map((archive) => {
    const active = String(archive.name) === String(restoreState.archive);
    const date = archive.start ? String(archive.start).substring(0, 19).replace('T', ' ') : '';
    return `<button type="button" class="restore-archive-row ${active ? 'is-selected' : ''}" data-restore-archive="${escHtml(archive.name)}"><span class="restore-archive-radio">${active ? '●' : '○'}</span><span><strong>${escHtml(archive.name)}</strong><small>${escHtml(date)}</small></span><span class="ui-badge">${escHtml(restoreT('available'))}</span></button>`;
  }).join('') || `<div class="restore-sidebar-empty">${escHtml(restoreT('noArchives'))}</div>`;
}

function restoreArchiveFilterPopover(filters) {
  const rows = (Array.isArray(filters) ? filters : [])
    .map((item) => ({
      filter: String(item?.filter || '').trim(),
      current: !!item?.current,
    }))
    .filter((item) => item.filter);
  if (rows.length <= 1) return '';
  const groups = [true, false].map((current) => {
    const group = rows.filter((row) => row.current === current);
    if (!group.length) return '';
    return `<span><em>${escHtml(restoreT(current ? 'archiveFilterCurrent' : 'archiveFilterPrevious'))}</em>${group.map((row) => `<code>${escHtml(row.filter)}</code>`).join('')}</span>`;
  }).join('');
  return `<span class="archive-pattern-popover">
    <button type="button" class="archive-pattern-popover-button" aria-haspopup="true" aria-label="${escHtml(restoreT('archiveFilterHistoryButton'))}">i</button>
    <span class="archive-pattern-popover-panel" role="tooltip">
      <strong>${escHtml(restoreT('archiveFilterHistoryTitle'))}</strong>
      ${groups}
    </span>
  </span>`;
}

function renderRestoreSourceContext() {
  const repository = document.getElementById('restore-source-repository');
  const archive = document.getElementById('restore-source-archive');
  const job = (restoreState.jobs || []).find((item) => String(item.key) === String(restoreState.job));
  if (repository) {
    repository.textContent = job?.repository_name || job?.repository_key || '—';
  }
  if (archive) archive.textContent = restoreState.archive || '—';
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
  if (step === 4) {
    const target = document.getElementById('restore-target-path')?.value?.trim() || '';
    return !!target && _isAllowedRestoreTarget(target);
  }
  return true;
}

function restoreStepNext() {
  if (!restoreCanAdvance(restoreState.step)) {
    if (restoreState.step === 1) return _restoreMsg(restoreT('selectJobFirst'), true);
    if (restoreState.step === 2) return _restoreMsg(restoreT('selectArchiveFirst'), true);
    if (restoreState.step === 3) return _restoreMsg(restoreT('selectElementFirst'), true);
    if (restoreState.step === 4) {
      const target = document.getElementById('restore-target-path')?.value?.trim() || '';
      return _restoreMsg(target ? restoreT('targetRestriction', { roots: _restoreAllowedRootsText() }) : restoreT('enterTargetFirst'), true);
    }
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
  restoreState.selections = [];
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
  const selectedCount = _restoreSelections().length;
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
  if (dryRunEl) dryRunEl.textContent = restoreT(dryRun ? 'plannedSimulation' : 'plannedRestore');
  const modeBadge = document.getElementById('restore-mode-badge');
  if (modeBadge) modeBadge.textContent = restoreT(dryRun ? 'dryRunActive' : 'restoreActive');
  const browserContext = document.getElementById('restore-browser-context');
  if (browserContext) browserContext.textContent = restoreState.archive || '';
  const selection = document.getElementById('restore-target-selection-info');
  if (selection) selection.textContent = restoreT('selectedCount', { count: selectedCount }) + ' · ' + _restoreSelectionTypes();
  const conflictHelp = document.getElementById('restore-conflict-help');
  const conflictMode = document.getElementById('restore-conflict-mode')?.value || 'skip';
  if (conflictHelp) conflictHelp.textContent = restoreT({skip: 'skipHelp', overwrite: 'overwriteHelp', rename: 'renameHelp'}[conflictMode]);
  _restoreRenderTargetHints();
}

function _restoreSelections() {
  return restoreState.selections?.length ? restoreState.selections : (restoreState.selectedPath
    ? [{ path: restoreState.selectedPath, name: restoreState.selectedName, type: restoreState.selectedType }] : []);
}

function _restoreSelectionTypes() {
  const selections = _restoreSelections();
  const folders = selections.filter(item => item.type === 'd').length;
  return restoreT('selectionTypes', {folders, files: selections.length - folders});
}

function restoreEntryIcon(type) {
  const shape = type === 'd' ? '<path d="M2 5h6l2 2h8v10H2z"/>'
    : type === 'l' ? '<path d="m8 12 4-4m-5 6H5a3 3 0 0 1-2-5l3-3a3 3 0 0 1 4 0m0 8a3 3 0 0 0 4 0l3-3a3 3 0 0 0-2-5h-2"/>'
    : '<path d="M4 2h8l4 4v12H4zM12 2v5h4M7 11h6M7 14h6"/>';
  return `<svg class="restore-entry-icon" viewBox="0 0 20 20" aria-hidden="true">${shape}</svg>`;
}

function _restoreRenderSelectedBox() {
  const selections = _restoreSelections();
  const list = document.getElementById('restore-selected-list');
  const count = document.getElementById('restore-selection-name');
  if (count) count.textContent = restoreT('selectedCount', { count: selections.length });
  const types = document.getElementById('restore-selection-types');
  if (types) types.textContent = selections.length ? _restoreSelectionTypes() : '';
  const input = document.getElementById('restore-selection-filter');
  if (input && !selections.length) input.value = '';
  const filter = String(input?.value || '').trim().toLocaleLowerCase();
  const filtered = selections.filter(item => String(item.path).toLocaleLowerCase().includes(filter));
  const resultCount = document.getElementById('restore-selection-filter-count');
  if (resultCount) resultCount.textContent = filter ? restoreT('selectionFilterCount', {count: filtered.length, total: selections.length}) : '';
  const clear = document.getElementById('restore-clear-selection-btn');
  if (clear) clear.disabled = !selections.length;
  if (list) list.innerHTML = filtered.length ? filtered.map(item => `
    <tr><td><span class="restore-entry-name">${restoreEntryIcon(item.type)}<strong>${escHtml(item.name || item.path.split('/').pop())}</strong></span></td>
    <td class="mono">${escHtml('/' + item.path.split('/').slice(0, -1).join('/'))}</td>
    <td><button type="button" class="restore-icon-btn" data-restore-action="select" data-path="${escHtml(item.path)}"
      aria-label="${escHtml(restoreT('removeItem', { name: item.name }))}" title="${escHtml(item.path)}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button></td></tr>`).join('')
    : `<tr><td colspan="3" class="text-muted">${escHtml(restoreT(selections.length ? 'selectionNoMatches' : 'nothingSelected'))}</td></tr>`;
}

function restoreOpenPath() {
  const input = document.getElementById('restore-archive-path');
  const path = String(input?.value || '').replace(/^\/+|\/+$/g, '');
  return restoreBrowse(path);
}

function restoreFilterFolder() {
  restoreState.folderFilter = document.getElementById('restore-folder-filter')?.value || '';
  _restoreRenderFiles(restoreState.files);
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
  if (key === 'running') return 'ui-badge--running';
  if (key === 'done') return 'ui-badge--success';
  if (key === 'error' || key === 'aborted') return 'ui-badge--error';
  return 'ui-badge--disabled';
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

function restoreConflictModeLabel(mode) {
  const key = String(mode || '').trim().toLowerCase();
  return ({
    skip: restoreT('conflictSkip'),
    overwrite: restoreT('conflictOverwrite'),
    rename: restoreT('conflictRename'),
  })[key || 'skip'] || (mode || '—');
}

function restoreFailureMessage(detail) {
  const error = String(detail?.error || '').trim();
  if (error === 'Server restarted during restore run') return restoreT('serverRestartedDuringRestore');
  return error;
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
        <strong>${escHtml(run.job_name || restoreJobName(run.job_key))}</strong>
        <small>${escHtml(run.archive || '—')}${run.dry_run ? ' · ' + escHtml(restoreT('simulation')) : ''}</small>
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
  if (!panel || !content) return;
  const rows = Array.isArray(payload?.runs) ? payload.runs : [];
  const total = Number(payload?.total || rows.length || 0);
  restoreState.history = rows;
  restoreState.historyTotal = total;
  if (count) count.textContent = total ? restoreT('historyCount', { count: total }) : '';

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
        <strong>${escHtml(run.job_name || restoreJobName(run.job_key))}</strong>
        <small>${escHtml(run.archive || '—')}${run.dry_run ? ' · ' + escHtml(restoreT('simulation')) : ''}</small>
      </div>
      <div class="restore-run-meta">
        <dl>
          <dt>${escHtml(restoreT('historyRestoreId'))}</dt><dd>${escHtml(id || '—')}</dd>
          <dt>${escHtml(restoreT('targetDirectory'))}</dt><dd>${escHtml(run.destination_path || run.target_dir || '—')}</dd>
          <dt>${escHtml(restoreT('runStarted'))}</dt><dd>${escHtml(run.started_at || '—')}</dd>
          <dt>${escHtml(restoreT('historyFinished'))}</dt><dd>${escHtml(run.finished_at || '—')}</dd>
          <dt>${escHtml(restoreT('historyDuration'))}</dt><dd>${escHtml(restoreFmtDuration(run.duration_seconds))}</dd>
        </dl>
      </div>
      <div class="restore-history-card-actions">
        <span class="ui-badge ${restoreRunStateClass(state)}">${escHtml(restoreRunStateLabel(state))}</span>
        <button type="button" class="btn btn-secondary btn-sm" data-restore-history-action="detail" data-restore-id="${escHtml(id)}" aria-expanded="${selected ? 'true' : 'false'}">${escHtml(selected ? restoreT('hideRunDetails') : restoreT('showRunDetails'))}</button>
        <button type="button" class="btn btn-secondary btn-sm restore-history-delete-btn" data-restore-history-action="delete" data-restore-id="${escHtml(id)}">${escHtml(restoreT('deleteHistoryRun'))}</button>
      </div>
      <div class="restore-history-detail" id="restore-history-detail-${escHtml(id)}"></div>
    </article>`;
  }).join('');
}

async function restoreLoadHistory() {
  try {
    const res = await fetch('/api/restore/history?limit=0', { credentials: 'include' });
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

async function restoreDeleteHistoryEntry(restoreId) {
  const id = String(restoreId || '').trim();
  if (!id) return;
  const run = (restoreState.history || []).find((item) => String(item.restore_id || '') === id) || {};
  const label = run.job_name || restoreJobName(run.job_key) || id;
  const ok = await openRestoreHistoryDeleteConfirmModal(label, id);
  if (!ok) return;
  try {
    const res = await fetch('/api/restore/history', {
      method: 'DELETE',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ restore_id: id }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(apiErrorMessage(data, res.status, data.error || ''));
    if (restoreState.historyDetailId === id) restoreState.historyDetailId = '';
    await restoreLoadHistory();
  } catch (err) {
    showMsg('restore-assist-msg', 'error', restoreT('deleteHistoryRunFailed', { message: err.message }));
  }
}

function openRestoreHistoryDeleteConfirmModal(label, id) {
  return new Promise((resolve) => {
    const modal = document.getElementById('restore-history-delete-confirm-modal');
    const message = document.getElementById('restore-history-delete-confirm-message');
    const idEl = document.getElementById('restore-history-delete-confirm-id');
    if (!modal || !message || !idEl) {
      resolve(window.confirm(restoreT('deleteHistoryRunConfirm', { name: label, id })));
      return;
    }
    restoreState.historyDeleteConfirmResolver = resolve;
    message.textContent = restoreT('deleteHistoryRunModalMessage', { name: label });
    idEl.textContent = id;
    modal.classList.remove('hidden');
  });
}

function closeRestoreHistoryDeleteConfirmModal(confirmed = false) {
  const modal = document.getElementById('restore-history-delete-confirm-modal');
  if (modal) modal.classList.add('hidden');
  if (restoreState.historyDeleteConfirmResolver) {
    const done = restoreState.historyDeleteConfirmResolver;
    restoreState.historyDeleteConfirmResolver = null;
    done(!!confirmed);
  }
}

function renderRestoreHistoryDetail(detail) {
  const id = String(detail?.restore_id || '');
  if (!id) return;
  const target = document.getElementById(`restore-history-detail-${id}`);
  if (!target) return;
  const lines = Array.isArray(detail.lines) ? detail.lines : [];
  const error = restoreFailureMessage(detail);
  target.innerHTML = `<div class="restore-history-detail-grid">
    <div><small>${escHtml(restoreT('historyRestoreId'))}</small><strong>${escHtml(id)}</strong></div>
    <div><small>${escHtml(restoreT('runStatus'))}</small><strong><span class="ui-badge ${restoreRunStateClass(detail.state)}">${escHtml(restoreRunStateLabel(detail.state))}</span></strong></div>
    <div><small>${escHtml(restoreT('sourcePath'))}</small><strong>${escHtml((detail.source_paths || [detail.source_path]).filter(Boolean).join(' · ') || '—')}</strong></div>
    <div><small>${escHtml(restoreT('targetDirectory'))}</small><strong>${escHtml(detail.target_dir || '—')}</strong></div>
    <div><small>${escHtml(restoreT('destinationLabel'))}</small><strong>${escHtml(detail.destination_path || '—')}</strong></div>
    <div><small>${escHtml(restoreT('conflictStrategy'))}</small><strong>${escHtml(restoreConflictModeLabel(detail.conflict_mode))}</strong></div>
    <div><small>${escHtml(restoreT('simulation'))}</small><strong>${escHtml(detail.dry_run ? restoreT('yes') : restoreT('no'))}</strong></div>
    <div><small>${escHtml(restoreT('preserveOwnerShort'))}</small><strong>${escHtml(detail.preserve_owner ? restoreT('yes') : restoreT('no'))}</strong></div>
  </div>
  ${restoreCountSummary(detail)}
  ${detail.items?.length ? `<ul class="restore-history-items">${detail.items.map(item => `<li>${escHtml(item.path)} → ${escHtml(item.destination_path)}${item.skipped ? ' (' + escHtml(restoreT('mappingSkip')) + ')' : ''}</li>`).join('')}</ul>` : ''}
  ${error ? `<div class="restore-history-error">${escHtml(error)}</div>` : ''}
  <details class="restore-history-log"><summary>${escHtml(restoreT('historyLog'))}</summary><pre>${escHtml(lines.join('\n') || restoreT('empty'))}</pre></details>`;
}

async function restoreLoadHistoryDetail(restoreId) {
  const id = String(restoreId || '').trim();
  if (!id) return;
  if (restoreState.historyDetailId === id) {
    restoreState.historyDetailId = '';
    renderRestoreHistory({ runs: restoreState.history, total: restoreState.historyTotal || restoreState.history.length });
    return;
  }
  restoreState.historyDetailId = id;
  try {
    const res = await fetch(`/api/restore/history/detail?restore_id=${encodeURIComponent(id)}`, { credentials: 'include' });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status, data.error || ''));
    renderRestoreHistory({ runs: restoreState.history, total: restoreState.historyTotal || restoreState.history.length });
    restoreState.historyDetailId = id;
    renderRestoreHistoryDetail(data);
  } catch (err) {
    const target = document.getElementById(`restore-history-detail-${id}`);
    const message = restoreFailureMessage({ error: err.message }) || err.message;
    if (target) target.innerHTML = `<div class="restore-history-error">${escHtml(message)}</div>`;
  }
}

function onRestoreRunsClick(event) {
  const btn = event.target.closest('[data-restore-run-action="open"]');
  if (!btn) return;
  const restoreId = String(btn.dataset.restoreId || '').trim();
  if (restoreId) restoreOpenRun(restoreId);
}

function onRestoreHistoryClick(event) {
  const btn = event.target.closest('[data-restore-history-action]');
  if (!btn) return;
  const restoreId = String(btn.dataset.restoreId || '').trim();
  if (!restoreId) return;
  const action = String(btn.dataset.restoreHistoryAction || '');
  if (action === 'delete') {
    restoreDeleteHistoryEntry(restoreId);
    return;
  }
  if (action === 'detail') restoreLoadHistoryDetail(restoreId);
}

async function restoreOpenRun(restoreId) {
  _stopRestorePolling();
  restoreState.activeRestoreId = restoreId;
  restoreState.completed = false;
  restoreState.runSnapshot = null;
  restoreSetLiveMode(true);
  renderRestoreRunStatus({state: 'running', phase: 'starting'});
  hideEl('restore-assist-msg');
  restoreSetStep(5);
  _setRestoreAssistBusy(true);
  await _pollRestoreState(restoreId);
}

function restoreCountSummary(data) {
  if (data.dry_run || !data.counts_complete || !data.counts) return '';
  const fields = [['files', 'restoredFiles'], ['directories', 'restoredDirectories']];
  if (data.counts.symlinks) fields.push(['symlinks', 'restoredLinks']);
  if (data.counts.other) fields.push(['other', 'restoredOther']);
  return `<div class="restore-result-counts">${fields.map(([key, label]) =>
    `<div><strong>${escHtml(String(data.counts[key] ?? 0))}</strong><span>${escHtml(restoreT(label))}</span></div>`).join('')}</div>`;
}

function renderRestoreRunStatus(data, connected = true) {
  restoreState.runSnapshot = data;
  const panel = document.getElementById('restore-run-status');
  if (!panel) return;
  const running = !['done', 'error', 'aborted'].includes(data.state);
  const failed = ['error', 'aborted'].includes(data.state);
  setRestoreHeaderStatus(!connected ? 'unreachable' : running ? 'running' : failed ? 'failed'
    : data.skipped ? 'skipped' : data.dry_run ? 'simulation' : 'success');
  // Do not replace focused controls or announce the whole card on every poll.
  const signature = JSON.stringify({...data, duration_seconds: 0, lines: failed ? data.lines : [],
    connected, language: restoreT('runHeading')});
  if (panel.dataset.signature === signature) {
    const duration = panel.querySelector('.restore-run-duration strong');
    if (duration) duration.textContent = restoreFmtDuration(data.duration_seconds || 0);
    return;
  }
  panel.dataset.signature = signature;
  panel.setAttribute('aria-label', restoreT('runHeading'));
  const phase = {starting: 'phasePreparing', preparing: 'phasePreparing', extract: data.dry_run ? 'phaseSimulation' : 'phaseExtract',
    validate: 'phaseValidate', publish: 'phasePublish'}[data.phase] || 'phasePreparing';
  const title = !connected ? 'connectionWaiting' : running ? phase : failed ? 'runFailed'
    : data.skipped ? 'runSkipped' : data.dry_run ? 'simulationSuccess' : 'runCompleted';
  const description = !connected ? 'connectionWaitingHelp' : running
    ? ({validate: 'validateHelp', publish: 'publishHelp'}[data.phase] || (data.dry_run ? 'runSimulationHelp' : 'runningHelp'))
    : failed ? 'runFailureHelp' : data.dry_run ? 'simulationNoWrites' : data.skipped ? 'runSkippedHelp' : 'runCompletedHelp';
  const selections = data.items?.length ? data.items : (data.source_paths || [data.source_path]).filter(Boolean).map(path => ({path}));
  const skipped = selections.filter(item => item.skipped).length;
  const opened = id => panel.querySelector(`#${id}`)?.open;
  const selectionOpen = opened('restore-run-selection') ?? selections.length <= 3;
  const diagnosticsOpen = opened('restore-run-diagnostics') || false;
  const statusClass = !connected ? 'waiting' : running ? 'running' : failed ? 'error' : data.skipped ? 'waiting' : 'success';
  const facts = [
    ['archive', data.archive], ['targetDirectory', data.target_dir],
    ['conflictStrategy', restoreConflictModeLabel(data.conflict_mode)],
    ['ownerGroupLabel', restoreT(data.preserve_owner ? 'ownerFromBackup' : 'ownerFromTarget')],
    ['executionMode', restoreT(data.dry_run ? 'plannedSimulation' : 'plannedRestore')],
    ['selectionLabel', restoreT('selectedCount', {count: selections.length})],
  ];
  const error = failed ? restoreFailureMessage(data) : '';
  panel.innerHTML = `<div class="restore-run-banner ${statusClass}">
    <span class="restore-run-indicator" aria-hidden="true">${running && connected ? '' : restoreStatusIcon(failed ? 'error' : statusClass === 'success' ? 'success' : 'warning')}</span>
    <div class="restore-run-message"><h3 role="status">${escHtml(restoreT(title))}</h3><p>${escHtml(restoreT(description))}</p></div>
    <div class="restore-run-duration"><small>${escHtml(restoreT('elapsedTime'))}</small><strong>${escHtml(restoreFmtDuration(data.duration_seconds || 0))}</strong></div>
  </div>
  ${restoreCountSummary(data)}
  <div class="restore-run-facts">${facts.map(([key, value]) => `<div><small>${escHtml(restoreT(key))}</small><strong>${escHtml(value || '—')}</strong></div>`).join('')}</div>
  ${running && data.staging_path ? `<div class="restore-run-stage"><strong>${escHtml(restoreT('stagingDirectory'))}</strong><code>${escHtml(data.staging_path)}</code><p>${escHtml(restoreT('stagingHelp'))}</p></div>` : ''}
  ${skipped ? `<p class="restore-run-note">${escHtml(restoreT('skippedSelections', {count: skipped}))}</p>` : ''}
  <details id="restore-run-selection" class="restore-run-selection" ${selectionOpen ? 'open' : ''}>
    <summary>${escHtml(restoreT('runSelectionDetails'))} (${selections.length})</summary>
    <div class="restore-run-selection-list">${selections.map(item => `<div><strong>${escHtml(item.path)}</strong>
      ${item.destination_path ? `<span>→ ${escHtml(item.destination_path)}</span>` : ''}
      ${item.skipped ? `<small>${escHtml(restoreT('mappingSkip'))}</small>` : item.restored ? `<small>${escHtml(restoreT('entryRestored'))}</small>` : ''}</div>`).join('')}</div>
  </details>
  ${failed ? `<div class="restore-history-error" role="alert">${escHtml(error || restoreT('unknownError'))}</div>` : ''}
  ${failed && data.lines?.length ? `<details id="restore-run-diagnostics" class="restore-history-log" ${diagnosticsOpen ? 'open' : ''}><summary>${escHtml(restoreT('errorDetails'))}</summary><pre>${escHtml(data.lines.join('\n'))}</pre></details>` : ''}`;
}

async function _pollRestoreState(restoreId) {
  if (!restoreId) return;
  try {
    const res = await fetch(`/api/restore/state?restore_id=${encodeURIComponent(restoreId)}`, { credentials: 'include' });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    if (restoreState.activeRestoreId !== restoreId) return;
    renderRestoreRunStatus(data);

    if (['done', 'error', 'aborted'].includes(data.state)) {
      _stopRestorePolling();
      _setRestoreAssistBusy(false);
      restoreState.completed = true;
      restoreUpdateConfirmState();
      restoreSetStep(5);
      restoreLoadRuns();
      restoreLoadHistory();
      setRestoreHeaderStatus(data.state !== 'done' ? 'failed' : data.skipped ? 'skipped' : data.dry_run ? 'simulation' : 'success');
      return;
    }
    restoreState.restorePollTimer = setTimeout(() => _pollRestoreState(restoreId), 1500);
  } catch (err) {
    if (restoreState.activeRestoreId !== restoreId) return;
    renderRestoreRunStatus(restoreState.runSnapshot || {state: 'running'}, false);
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
    const fallbackRoot = _restorePrimaryAllowedRoot();
    const prefix = value || `${fallbackRoot}/`;
    if (!_isAllowedRestoreTarget(prefix)) {
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
      _restoreSetAllowedTargetRoots(data.allowed_roots || restoreState.allowedTargetRoots);
      const dirs = (data.dirs || []).map(d => d.path).filter(Boolean);
      restoreState.targetSuggestCache.set(prefix, dirs);
      applyOptions(dirs);
    } catch (_) {
      // Silent fail: autocomplete is optional UX.
    }
  };

  input.addEventListener('focus', () => {
    if (!input.value.trim()) input.value = `${_restorePrimaryAllowedRoot()}/`;
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
    if (!_isAllowedRestoreTarget(v)) return;
    const options = Array.from(datalist.options || []);
    const exact = options.find(o => o.value.replace(/\/+$/, '') === v.replace(/\/+$/, ''));
    if (exact && !v.endsWith('/')) {
      ev.preventDefault();
      input.value = `${v}/`;
      loadSuggestions(input.value);
    }
  });
}

function restoreClearFileSelection() {
  const selectionDetails = document.getElementById('restore-selection-details');
  if (selectionDetails) selectionDetails.open = false;
  const pathDetails = document.getElementById('restore-path-details');
  if (pathDetails) pathDetails.open = false;
  restoreState.folderTree = null;
  const tree = document.getElementById('restore-folder-tree');
  if (tree) tree.innerHTML = '';
  restoreState.filesRequest++;
  restoreState.files = [];
  restoreState.path = '';
  restoreState.selectedPath = '';
  restoreState.selections = [];
  restoreState.selectedName = '';
  restoreState.selectedType = '';
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  const source = document.getElementById('restore-source-path');
  if (source) source.value = '';
  const confirm = document.getElementById('restore-confirm-check');
  if (confirm) confirm.checked = false;
  const output = document.getElementById('restore-precheck-output');
  if (output) output.textContent = '';
  const files = document.getElementById('restore-filelist');
  if (files) files.innerHTML = '';
  const breadcrumb = document.getElementById('restore-breadcrumb');
  if (breadcrumb) breadcrumb.innerHTML = '';
  renderRestorePrecheck(null);
  _setRestoreAssistBusy(false);
  restoreUpdateConfirmState();
  _restoreRenderSelectedBox();
}

function restoreClearArchives() {
  restoreState.archive = '';
  restoreState.archives = [];
  restoreState.archiveFilters = [];
  restoreClearFileSelection();
  const select = document.getElementById('restore-archive-sel');
  if (select) select.innerHTML = `<option value="">${restoreT('chooseArchive')}</option>`;
  renderRestoreArchiveList();
  renderRestoreSourceContext();
  _restoreRenderSelectionSummary();
}

async function restoreInit() {
  const selectedJob = restoreState.job;
  const request = ++restoreState.sourceRequest;
  restoreState.job = '';
  restoreState.archiveFilterMode = 'job';
  restoreState.archiveFilterPattern = '';
  restoreRenderArchiveFilterControls();
  restoreClearArchives();
  restoreState.completed = false;
  restoreSetLiveMode(false);
  const sel = document.getElementById('restore-job-sel');
  sel.innerHTML = `<option value="">${restoreT('chooseJob')}</option>`;
  const wizard = document.getElementById('restore-wizard');
  if (wizard) wizard.style.display = restoreState.view === 'history' ? 'none' : '';
  const empty = document.getElementById('restore-empty');
  if (empty) empty.style.display = 'none';
  restoreSwitchView(restoreState.view || 'wizard');
  restoreSetStep(1);
  _restoreMsg('');
  _restoreBindTargetAutocomplete();
  const targetInput = document.getElementById('restore-target-path');
  await restoreLoadAllowedTargetRoots();
  if (request !== restoreState.sourceRequest) return;
  if (targetInput && !targetInput.value.trim()) targetInput.value = `${_restorePrimaryAllowedRoot()}/`;
  _restoreRenderSelectionSummary();
  _restoreRenderSelectedBox();
  restoreLoadRuns();
  restoreLoadHistory();

  try {
    const jobsRes = await fetch('/api/jobs', { credentials: 'include' });
    const jobsData = await jobsRes.json();
    if (request !== restoreState.sourceRequest) return;
    if (!jobsRes.ok) throw new Error(apiErrorMessage(jobsData, jobsRes.status));
    const jobs = (jobsData.jobs || []).filter(j => !j.is_utility);
    restoreState.jobs = jobs;

    for (const job of jobs) {
      if (job.is_utility) continue;
      const opt = document.createElement('option');
      opt.value = job.key;
      opt.textContent = job.name || job.display_name || job.key;
      sel.appendChild(opt);
    }

    if (!jobs.length) {
      const checkRes = await fetch('/api/storage/check/jobs', { credentials: 'include' });
      if (checkRes.ok) {
        const checkData = await checkRes.json();
        if (request !== restoreState.sourceRequest) return;
        for (const job of (checkData.jobs || [])) {
          const opt = document.createElement('option');
          opt.value = job.key;
          opt.textContent = job.name || job.key;
          sel.appendChild(opt);
        }
        restoreState.jobs = (checkData.jobs || []).map((job) => ({ ...job, location: job.location || 'local' }));
      }
    }
    if (restoreState.jobs.some(job => String(job.key) === String(selectedJob))) {
      sel.value = selectedJob;
      restoreState.job = selectedJob;
    }
    renderRestoreJobSidebar();
    renderRestoreSelectedJob();
    renderRestoreSourceContext();
    if (restoreState.job) await restoreLoadArchives();
  } catch (e) {
    if (request !== restoreState.sourceRequest) return;
    _restoreMsg(restoreT('loadJobsError', { message: e.message }), true);
  }
}

function restoreRenderArchiveFilterControls() {
  const mode = document.getElementById('restore-archive-filter-mode');
  const input = document.getElementById('restore-archive-filter-pattern');
  const custom = restoreState.archiveFilterMode === 'custom';
  if (mode) mode.value = restoreState.archiveFilterMode;
  if (input) {
    input.value = restoreState.archiveFilterPattern;
    input.disabled = !custom;
  }
  document.getElementById('restore-archive-filter-custom')?.classList.toggle('hidden', !custom);
}

function restoreChangeArchiveFilter() {
  restoreState.archiveFilterMode = document.getElementById('restore-archive-filter-mode').value;
  restoreRenderArchiveFilterControls();
  // Switching to custom mode requires an explicit Apply, even if a previous
  // pattern remains in the input. Never show archives from the previous mode.
  if (restoreState.archiveFilterMode === 'custom') {
    restoreEditArchiveFilter();
    document.getElementById('restore-archive-filter-pattern')?.focus();
    return;
  }
  return restoreLoadArchives();
}

function restoreEditArchiveFilter() {
  restoreState.sourceRequest++;
  restoreState.archiveFilterPattern = '';
  restoreClearArchives();
  _restoreMsg('');
  document.getElementById('restore-archive-list').innerHTML =
    `<div class="restore-sidebar-empty">${escHtml(restoreT('archiveFilterApplyHint'))}</div>`;
}

function restoreApplyArchiveFilter() {
  const pattern = document.getElementById('restore-archive-filter-pattern').value;
  if (!pattern.trim() || pattern.length > 256 || /[\x00-\x1f\x7f]/.test(pattern)) {
    return _restoreMsg(restoreT('archiveFilterInvalid'), true);
  }
  restoreState.archiveFilterPattern = pattern;
  return restoreLoadArchives();
}

async function restoreLoadArchives() {
  const request = ++restoreState.sourceRequest;
  const jobKey = document.getElementById('restore-job-sel').value;
  if (jobKey !== restoreState.job) {
    restoreState.archiveFilterMode = 'job';
    restoreState.archiveFilterPattern = '';
  }
  restoreRenderArchiveFilterControls();
  restoreState.job = jobKey;
  restoreClearArchives();
  _restoreMsg('');

  if (!jobKey) {
    _restoreRenderSelectionSummary();
    _restoreRenderSelectedBox();
    return;
  }
  if (restoreState.archiveFilterMode === 'custom' && !restoreState.archiveFilterPattern) {
    restoreEditArchiveFilter();
    return;
  }
  renderRestoreJobSidebar();
  renderRestoreSelectedJob();
  _restoreMsg(restoreT('loadingArchives'));

  try {
    let query = `job=${encodeURIComponent(jobKey)}`;
    if (restoreState.archiveFilterMode !== 'job') {
      query += `&filter_mode=${encodeURIComponent(restoreState.archiveFilterMode)}`;
      if (restoreState.archiveFilterMode === 'custom') query += `&archive_filter=${encodeURIComponent(restoreState.archiveFilterPattern)}`;
    }
    const res = await fetch(`/api/restore/archives?${query}`, { credentials: 'include' });
    const data = await res.json();
    if (request !== restoreState.sourceRequest) return;
    if (!res.ok || data.error) { _restoreMsg(restoreT('error', { message: apiErrorMessage(data, res.status) }), true); return; }

    const sel = document.getElementById('restore-archive-sel');
    sel.innerHTML = `<option value="">${restoreT('chooseArchive')}</option>`;
    restoreState.archives = data.archives || [];
    restoreState.archiveFilters = Array.isArray(data.archive_filters) ? data.archive_filters : [];
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
    if (request !== restoreState.sourceRequest) return;
    _restoreMsg(restoreT('error', { message: e.message }), true);
  }
}

function _restoreGetFolderTree() {
  if (!restoreState.folderTree) {
    restoreState.folderTree = { nodes: new Map(), expanded: new Set(['']), requests: new Map() };
  }
  return restoreState.folderTree;
}

function _restoreTreeNode(tree, path) {
  if (!tree.nodes.has(path)) {
    tree.nodes.set(path, { path, name: path.split('/').pop(), children: [], loaded: false, error: '' });
  }
  return tree.nodes.get(path);
}

function _restoreRememberTreeDirectory(tree, path, files) {
  // Direct path entry must also reveal its ancestors. Unloaded parents keep
  // these known children until expanded, when their complete listing is loaded.
  const parts = path ? path.split('/') : [];
  let parent = '';
  _restoreTreeNode(tree, parent);
  for (let index = 0; index < parts.length; index++) {
    const child = parts.slice(0, index + 1).join('/');
    const parentNode = _restoreTreeNode(tree, parent);
    if (!parentNode.children.includes(child)) parentNode.children.push(child);
    _restoreTreeNode(tree, child);
    parent = child;
  }
  const node = _restoreTreeNode(tree, path);
  node.children = files.filter(file => file.type === 'd' && typeof file.path === 'string')
    .map(file => { _restoreTreeNode(tree, file.path); return file.path; });
  node.loaded = true;
  node.error = '';
}

function _restoreOpenTreeAncestors(tree, path) {
  const parts = path ? path.split('/') : [];
  tree.expanded.add('');
  for (let i = 1; i < parts.length; i++) tree.expanded.add(parts.slice(0, i).join('/'));
}

function _restoreRenderFolderTree() {
  const element = document.getElementById('restore-folder-tree');
  if (!element) return;
  const tree = restoreState.folderTree;
  const focused = document.activeElement;
  const focusKey = focused && element.contains?.(focused) ? {path: focused.dataset.path, action: focused.dataset.restoreAction} : null;
  if (!tree) { element.innerHTML = ''; return; }
  const render = (path, depth = 0) => {
    const node = tree.nodes.get(path);
    if (!node || depth > 64) return '';
    const expanded = tree.expanded.has(path);
    const busy = tree.requests.has(path);
    const branch = !node.loaded || node.children.length > 0;
    const name = path ? node.name : restoreT('archiveRoot');
    const active = path === restoreState.path;
    return `<li><div class="restore-tree-row${active ? ' is-current' : ''}">
      ${branch ? `<button type="button" class="restore-tree-toggle" data-restore-action="tree-toggle" data-path="${escHtml(path)}" aria-expanded="${expanded}" aria-label="${escHtml(restoreT(expanded ? 'collapseFolder' : 'expandFolder', { name }))}"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3 5 5-5 5"/></svg></button>` : '<span class="restore-tree-spacer"></span>'}
      <button type="button" class="restore-tree-name" data-restore-action="browse" data-path="${escHtml(path)}" ${active ? 'aria-current="location"' : ''} title="${escHtml('/' + path)}"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M2 5h6l2 2h8v10H2z"/></svg><span>${escHtml(name)}</span></button>
    </div>${expanded && busy ? `<small class="restore-tree-note" role="status">${escHtml(restoreT('loadingFolders'))}</small>` : ''}
    ${expanded && node.error ? `<div class="restore-tree-note" role="alert">${escHtml(node.error)} <button type="button" class="btn btn-secondary btn-sm" data-restore-action="tree-retry" data-path="${escHtml(path)}">${escHtml(restoreT('retryFolders'))}</button></div>` : ''}
    ${expanded && node.children.length ? `<ul>${node.children.map(child => render(child, depth + 1)).join('')}</ul>` : ''}</li>`;
  };
  element.innerHTML = `<ul>${render('')}</ul>`;
  if (focusKey) {
    const buttons = Array.from(element.querySelectorAll('button'));
    const button = buttons.find(item => item.dataset.path === focusKey.path && item.dataset.restoreAction === focusKey.action)
      || buttons.find(item => item.dataset.path === focusKey.path && item.dataset.restoreAction === 'browse');
    button?.focus({preventScroll: true});
  }
}

async function _restoreFetchDirectory(tree, path, jobKey, archive) {
  if (tree.requests.has(path)) return tree.requests.get(path);
  const pending = (async () => {
    const url = `/api/restore/files?job=${encodeURIComponent(jobKey)}&archive=${encodeURIComponent(archive)}&path=${encodeURIComponent(path)}`;
    const res = await fetch(url, { credentials: 'include' });
    const data = await res.json();
    if (!res.ok || data?.error) {
      const error = new Error(apiErrorMessage(data, res.status));
      error.archiveUnavailable = data?.code === 'restore_archive_unavailable';
      throw error;
    }
    if (!data || !Array.isArray(data.files)) throw new Error(apiErrorMessage({code: 'internal_error'}));
    if (restoreState.folderTree === tree) _restoreRememberTreeDirectory(tree, path, data.files);
    return data.files;
  })();
  tree.requests.set(path, pending);
  _restoreTreeNode(tree, path);
  _restoreRenderFolderTree();
  try { return await pending; }
  finally {
    tree.requests.delete(path);
    if (restoreState.folderTree === tree) _restoreRenderFolderTree();
  }
}

async function restoreToggleFolder(path, retry = false) {
  const tree = _restoreGetFolderTree();
  if (!retry && tree.expanded.has(path)) {
    tree.expanded.delete(path);
    _restoreRenderFolderTree();
    return;
  }
  tree.expanded.add(path);
  const node = _restoreTreeNode(tree, path);
  node.error = '';
  _restoreRenderFolderTree();
  if (node.loaded && !retry) return;
  try {
    const jobKey = restoreState.job;
    const archive = restoreState.archive;
    let current = path;
    for (let depth = 0; depth < 64; depth++) {
      const files = await _restoreFetchDirectory(tree, current, jobKey, archive);
      if (restoreState.folderTree !== tree || !tree.expanded.has(path)) return;
      if (files.length !== 1 || files[0].type !== 'd' || typeof files[0].path !== 'string' || !files[0].path.startsWith(current ? current + '/' : '') || files[0].path === current) break;
      current = files[0].path;
      tree.expanded.add(current);
    }
  } catch (error) {
    if (restoreState.folderTree !== tree) return;
    if (error.archiveUnavailable) restoreClearArchives();
    else node.error = error.message;
  }
  _restoreRenderFolderTree();
}

async function restoreBrowse(path) {
  const jobKey = restoreState.job;
  const pathInput = document.getElementById('restore-archive-path');
  const enteredPath = pathInput?.value;
  const archive = document.getElementById('restore-archive-sel').value;
  if (!archive) return;

  const firstOpen = archive !== restoreState.archive && !path;
  if (archive !== restoreState.archive) restoreClearFileSelection();
  const request = ++restoreState.filesRequest;
  const sourceRequest = restoreState.sourceRequest;
  const isCurrent = () => request === restoreState.filesRequest && sourceRequest === restoreState.sourceRequest;
  restoreState.archive = archive;
  const tree = _restoreGetFolderTree();
  const previousPath = restoreState.path;
  renderRestoreSourceContext();
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
    let files = await _restoreFetchDirectory(tree, path, jobKey, archive);
    if (!isCurrent()) return;
    // Skip repeated clicks through structural parents. Stop at the first folder
    // containing files, several subfolders, or nothing; never select anything.
    if (firstOpen) {
      for (let depth = 0; depth < 64 && files.length === 1 && files[0].type === 'd'; depth++) {
        const child = files[0].path;
        if (typeof child !== 'string' || child === path || !child.startsWith(path ? path + '/' : '')) break;
        tree.expanded.add(path);
        path = child;
        files = await _restoreFetchDirectory(tree, path, jobKey, archive);
        if (!isCurrent()) return;
      }
      tree.expanded.add(path);
    }
    _restoreOpenTreeAncestors(tree, path);
    _restoreMsg('');
    restoreState.path = path;
    restoreState.folderFilter = '';
    const filter = document.getElementById('restore-folder-filter');
    if (filter) filter.value = '';
    if (pathInput && pathInput.value === enteredPath) pathInput.value = '/' + path;
    _restoreRenderBreadcrumb(path);
    restoreState.files = files;
    _restoreRenderFiles(restoreState.files);
    _restoreRenderFolderTree();
  } catch (e) {
    if (!isCurrent()) return;
    if (e.archiveUnavailable) restoreClearArchives();
    else {
      restoreState.path = previousPath;
      restoreState.precheck = null;
      restoreState.autoPrecheckKey = '';
      restoreUpdateConfirmState();
    }
    _restoreRenderSelectionSummary();
    if (filelist) filelist.innerHTML = `<div class="restore-empty" role="alert">${escHtml(e.message)}</div>`;
    _restoreMsg(restoreT('error', { message: e.message }), true);
  }
}

function _restoreRenderBreadcrumb(path) {
  const parts = path ? path.split('/') : [];
  let html = `<button type="button" class="bc-link" data-restore-action="browse" data-path="/">${escHtml(restoreT('archiveRoot'))}</button>`;
  let cum = '';
  for (let i = 0; i < parts.length; i++) {
    cum = parts.slice(0, i + 1).join('/');
    const p = cum;
    html += ' <span aria-hidden="true">/</span> ' + (i === parts.length - 1
      ? `<span class="bc-current" aria-current="location">${escHtml(parts[i])}</span>`
      : `<button type="button" class="bc-link" data-restore-action="browse" data-path="${escHtml(p)}">${escHtml(parts[i])}</button>`);
  }
  document.getElementById('restore-breadcrumb').innerHTML = html;
}

function _restoreRenderFiles(files) {
  const el = document.getElementById('restore-filelist');
  if (!el) return;
  const filter = String(restoreState.folderFilter || '').toLocaleLowerCase();
  files = files.filter(f => String(f.name).toLocaleLowerCase().includes(filter));
  if (!files.length) {
    el.innerHTML = `<div class="restore-empty">${restoreT('noFiles')}</div>`;
    return;
  }

  let rows = '';
  for (const f of files) {
    const isSelected = _restoreSelections().some(item => item.path === f.path);
    const included = _restoreSelections().some(item => item.type === 'd' && f.path.startsWith(item.path + '/'));
    const icon = restoreEntryIcon(f.type);
    const size = f.type === 'd' ? '—' : _restoreFmtSize(f.size);
    const mtime = f.mtime ? f.mtime.substring(0, 19).replace('T', ' ') : '';
    const nameCell = f.type === 'd'
      ? `<button type="button" class="restore-dir-link restore-entry-name" data-restore-action="browse" data-path="${escHtml(f.path)}">${icon}<span>${escHtml(f.name)}</span></button>`
      : `<span class="restore-entry-name">${icon}<span>${escHtml(f.name)}</span></span>`;

    rows += `<tr class="${isSelected ? 'restore-row-selected' : ''}">
      <td class="restore-col-select"><input type="checkbox" data-restore-action="select" data-path="${escHtml(f.path)}" data-name="${escHtml(f.name)}" data-type="${escHtml(f.type || '')}"
        ${isSelected || included ? 'checked' : ''} ${included ? 'disabled' : ''} aria-label="${escHtml(restoreT(included ? 'includedByParent' : 'selectItem', { name: f.name }))}" title="${escHtml(restoreT(included ? 'includedByParent' : 'selectItem', { name: f.name }))}"></td>
      <td class="restore-col-name">${nameCell}</td>
      <td class="restore-col-size">${size}</td>
      <td class="restore-col-date">${mtime}</td>
      <td class="restore-col-action">
        <button class="restore-icon-btn" data-restore-action="download" data-path="${escHtml(f.path)}" title="${restoreT('download')}" aria-label="${restoreT('download')}">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 4v10m0 0l-4-4m4 4l4-4M5 20h14"/>
          </svg>
        </button>

      </td>
    </tr>`;
  }

  el.innerHTML = `<table class="restore-table">
    <thead><tr>
      <th class="restore-col-select" aria-label="${escHtml(restoreT('currentSelection'))}"></th><th>${restoreT('name')}</th><th class="restore-col-size">${restoreT('size')}</th><th class="restore-col-date">${restoreT('date')}</th><th></th>
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
  if (action === 'tree-toggle') return restoreToggleFolder(path);
  if (action === 'tree-retry') return restoreToggleFolder(path, true);
  if (action === 'browse') return restoreBrowse(path);
  if (action === 'download') return restoreDownload(path);
  if (action === 'select') {
    const selectionList = el.closest('#restore-selected-list');
    const index = selectionList ? Array.from(selectionList.querySelectorAll('button')).indexOf(el) : -1;
    restorePrepare(path, name, type);
    if (selectionList) {
      const buttons = selectionList.querySelectorAll('button');
      (buttons[Math.min(index, buttons.length - 1)] || document.getElementById('restore-selection-filter'))?.focus();
    } else {
      Array.from(document.querySelectorAll('#restore-filelist input[data-path]')).find(input => input.dataset.path === path)?.focus();
    }
  }
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
  let selections = _restoreSelections();
  if (selections.some(item => item.path === path)) {
    selections = selections.filter(item => item.path !== path);
  } else {
    if (selections.some(item => item.type === 'd' && path.startsWith(item.path + '/'))) return;
    selections = selections.filter(item => !(type === 'd' && item.path.startsWith(path + '/')));
    if (selections.length >= 256) return _restoreMsg(restoreT('selectionLimit'), true);
    selections.push({ path, name, type });
  }
  restoreState.selections = selections;
  restoreState.selectedPath = selections[0]?.path || '';
  restoreState.selectedName = selections[0]?.name || '';
  restoreState.selectedType = selections[0]?.type || '';
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  restoreState.completed = false;
  const src = document.getElementById('restore-source-path');
  const out = document.getElementById('restore-precheck-output');
  const target = document.getElementById('restore-target-path');
  const startBtn = document.getElementById('restore-start-btn');
  const confirmCheck = document.getElementById('restore-confirm-check');
  if (src) src.value = selections.map(item => item.path).join('\n');
  renderRestoreSourceContext();
  if (out) out.textContent = '';
  if (startBtn) startBtn.disabled = true;
  if (confirmCheck) confirmCheck.checked = false;
  hideEl('restore-assist-msg');
  _setRestoreAssistBusy(false);
  _restoreRenderSelectedBox();
  // Auswahl bleibt in Schritt 3 sichtbar; Wechsel nach Schritt 4 erfolgt über "Weiter".
  restoreSetStep(Math.max(3, restoreState.step));
  _restoreRenderSelectionSummary();
  restoreUpdateConfirmState();
  _restoreRenderFiles(restoreState.files);
}

function restoreClearSelection() {
  restoreState.selectedPath = '';
  restoreState.selections = [];
  restoreState.selectedName = '';
  restoreState.selectedType = '';
  restoreState.precheck = null;
  restoreState.autoPrecheckKey = '';
  restoreState.completed = false;
  restoreState.activeRestoreId = '';
  const src = document.getElementById('restore-source-path');
  const out = document.getElementById('restore-precheck-output');
  const confirmCheck = document.getElementById('restore-confirm-check');
  const startBtn = document.getElementById('restore-start-btn');
  if (src) src.value = '';
  renderRestoreSourceContext();
  if (out) out.textContent = '';
  if (confirmCheck) confirmCheck.checked = false;
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
  if (startBtn) {
    startBtn.disabled = !enabled;
    startBtn.textContent = restoreT(document.getElementById('restore-dry-run')?.checked ? 'startSimulation' : 'startRestore');
  }
}

function _isAllowedRestoreTarget(target) {
  const t = String(target || '').trim();
  if (!t.startsWith('/')) return false;
  return _restoreAllowedTargetRoots().some((root) => t === root || t.startsWith(`${root}/`));
}

function _restoreNormalizePath(value) {
  const path = String(value || '').trim().replace(/\/+$/, '') || '/';
  return path;
}

function _restoreAllowedTargetRoots() {
  const roots = Array.isArray(restoreState.allowedTargetRoots) ? restoreState.allowedTargetRoots : [];
  const seen = new Set();
  const out = [];
  roots.forEach((root) => {
    const clean = _restoreNormalizePath(root);
    if (!clean || !clean.startsWith('/') || seen.has(clean)) return;
    seen.add(clean);
    out.push(clean);
  });
  return out.length ? out : ['/mnt/user'];
}

function _restorePrimaryAllowedRoot() {
  return _restoreAllowedTargetRoots()[0] || '/mnt/user';
}

function _restoreAllowedRootsText() {
  return _restoreAllowedTargetRoots().join(', ');
}

function _restoreSetAllowedTargetRoots(roots) {
  restoreState.allowedTargetRoots = (Array.isArray(roots) && roots.length ? roots : ['/mnt/user'])
    .map(_restoreNormalizePath)
    .filter((root) => root && root.startsWith('/'));
  _restoreRenderTargetHints();
}

function _restoreRenderTargetHints() {
  const hint = document.getElementById('restore-target-roots-hint');
  if (hint) hint.textContent = restoreT('targetRestrictionHint', { roots: _restoreAllowedRootsText() });
}

async function restoreLoadAllowedTargetRoots() {
  try {
    const res = await fetch('/api/restore/target-dirs?prefix=&limit=1', { credentials: 'include' });
    const data = await res.json();
    if (res.ok && !data.error) _restoreSetAllowedTargetRoots(data.allowed_roots || []);
  } catch (_) {
    _restoreSetAllowedTargetRoots(restoreState.allowedTargetRoots || ['/mnt/user']);
  }
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
  const sourceRequest = restoreState.sourceRequest;
  const filesRequest = restoreState.filesRequest;
  const requestKey = _currentPrecheckKey();
  const isCurrent = () => sourceRequest === restoreState.sourceRequest && filesRequest === restoreState.filesRequest && requestKey === _currentPrecheckKey();
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
    showMsg('restore-assist-msg', 'error', restoreT('targetRestriction', { roots: _restoreAllowedRootsText() }));
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
        source_paths: _restoreSelections().map(item => item.path),
        target_dir: target,
        conflict_mode: mode,
        dry_run: dryRun,
      }),
    });
    const data = await res.json();
    if (!isCurrent()) return;
    if (!res.ok) throw new Error(restorePrecheckErrorMessage(data, res.status));
    restoreState.precheck = data;
    restoreState.autoPrecheckKey = requestKey;
    renderRestorePrecheck(data);
    if (out) out.textContent = _restoreTechnicalPrecheckText(data, dryRun);
    if (!data.ok) showMsg('restore-assist-msg', 'error', restoreT('precheckFailed'));
  } catch (err) {
    if (!isCurrent()) return;
    restoreState.precheck = null;
    renderRestorePrecheck(null);
    if (out) out.textContent = '';
    showMsg('restore-assist-msg', 'error', restoreT('precheckError', { message: err.message }));
  } finally {
    if (isCurrent()) {
      _setRestoreAssistBusy(false);
      restoreUpdateConfirmState();
    }
  }
}

function _restoreTechnicalPrecheckText(data, dryRun) {
  const lines = [
    restoreT('metadataPrecheckDetail'),
    restoreT('archiveValue', { value: data.archive }),
    restoreT('targetPath', { value: data.target_dir }),
    restoreT('conflictMode', { value: data.conflict_mode }),
    restoreT('plannedRun', { value: restoreT(dryRun ? 'plannedSimulation' : 'plannedRestore') }),
    restoreT('mountpoint', { value: data.target_mountpoint || restoreT('mountpointUnknown') }),
    restoreT('freeSpace', { value: _restoreFmtSize(data.target_free_bytes || 0) }),
    restoreT('checkedSelectionCount', { count: data.items.length }),
    restoreT('metadataPrecheckScope'),
  ];
  data.items.forEach((item, index) => {
    const {type, action, destination} = _restorePlannedItem(data, item, dryRun);
    lines.push('', restoreT('precheckItem', { index: index + 1, count: data.items.length, type: restoreT(type) }),
      restoreT('source', { value: item.path }),
      `${restoreT('mappingWhere')}: ${destination}`,
      restoreT('alreadyExists', { value: item.destination_exists ? restoreT('yes') : restoreT('no') }),
      `${restoreT('mappingHow')}: ${restoreT(action)}`);
    if (data.conflict_mode === 'rename' && !item.skipped) lines.push(restoreT('mappingTimestamp'));
  });
  return lines.join('\n');
}

function _restorePlannedItem(data, item, simulation) {
  const directory = item.type === 'd';
  const type = directory ? 'mappingFolder' : (item.type === 'l' ? 'mappingLink' : 'mappingFile');
  let action = 'mappingRestore';
  if (item.skipped) action = 'mappingSkip';
  else if (simulation) action = 'mappingSimulate';
  else if (data.conflict_mode === 'rename') action = 'mappingRename';
  else if (data.conflict_mode === 'overwrite' && item.destination_exists) action = directory ? 'mappingMerge' : 'mappingReplace';
  // A matching single-directory target receives a timestamped child in rename mode.
  const destination = data.conflict_mode === 'rename' && item.direct_contents
    ? String(item.destination_path).replace(/\/$/, '') + '/' + String(item.path).split('/').pop()
    : item.destination_path;
  return {type, action, destination};
}

function _restoreRenderDestinationMap(data) {
  const mapping = document.getElementById('restore-destination-map');
  if (!mapping) return;
  if (!data?.items?.length) { mapping.innerHTML = ''; return; }
  const simulation = !!document.getElementById('restore-dry-run')?.checked;
  const rows = data.items.map(item => {
    const {type, action, destination} = _restorePlannedItem(data, item, simulation);
    const stateClass = item.skipped ? 'is-skipped' : (simulation ? 'is-simulation' : '');
    const source = String(item.path || '');
    const name = source.split('/').pop();
    return `<tr>
      <td class="restore-mapping-source"><strong>${escHtml(name)}</strong><small>${escHtml(restoreT(type))}</small><span class="mono">${escHtml(source)}</span></td>
      <td class="restore-mapping-action"><span class="restore-mapping-action-label ${stateClass}">${escHtml(restoreT(action))}</span></td>
      <td class="restore-mapping-target"><span class="mono">${escHtml(destination)}</span></td>
    </tr>`;
  }).join('');
  mapping.innerHTML = `<header><h3 id="restore-mapping-title">${escHtml(restoreT('destinationMapping'))}</h3><p>${escHtml(restoreT(data.conflict_mode === 'rename' ? 'mappingRenameHint' : 'mappingHint'))}${simulation ? ' ' + escHtml(restoreT('mappingNoChanges')) : ''}</p></header>
    <div class="restore-mapping-scroll"><table aria-labelledby="restore-mapping-title"><thead><tr><th scope="col">${escHtml(restoreT('mappingWhat'))}</th><th scope="col">${escHtml(restoreT('mappingHow'))}</th><th scope="col">${escHtml(restoreT('mappingWhere'))}</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderRestorePrecheck(data) {
  _restoreRenderDestinationMap(data);
  const verdict = document.getElementById('restore-precheck-verdict');
  const badge = document.getElementById('restore-precheck-badge');
  const facts = document.getElementById('restore-system-check-facts');
  if (!verdict || !facts) return;
  if (!data) {
    verdict.classList.add('hidden');
    facts.innerHTML = '';
    if (badge) {
      badge.textContent = restoreT('precheckPending');
      delete badge.dataset.state;
    }
    return;
  }
  const ok = !!data.ok;
  verdict.classList.remove('hidden');
  verdict.classList.toggle('error', !ok);
  verdict.innerHTML = `<span class="restore-precheck-verdict-mark">${restoreStatusIcon(ok ? 'success' : 'error')}</span><span><strong>${escHtml(restoreT(ok ? 'precheckVerdictOk' : 'precheckVerdictFailed'))}</strong><small>${escHtml(restoreT(ok ? 'precheckVerdictOkDetail' : 'precheckVerdictFailedDetail'))}</small></span>`;
  facts.innerHTML = [
    [restoreT('mountpointLabel'), data.target_mountpoint || restoreT('mountpointUnknown')],
    [restoreT('freeSpaceLabel'), _restoreFmtSize(data.target_free_bytes || 0)],
    [restoreT('checkedSelectionsLabel'), data.items.length],
    [restoreT('existingDestinationsLabel'), data.items.filter(item => item.destination_exists).length],
  ].map(([label, value]) => `<div><small>${escHtml(label)}</small><strong>${escHtml(String(value))}</strong></div>`).join('');
  if (badge) {
    badge.textContent = restoreT(ok ? 'precheckSuccessful' : 'precheckFailedShort');
    badge.dataset.state = ok ? 'success' : 'error';
  }
}

function setRestoreHeaderStatus(state) {
  const badge = document.getElementById('restore-precheck-badge');
  if (!badge) return;
  const key = {
    success: 'restoreSuccessfulShort',
    simulation: 'simulationSuccessShort',
    skipped: 'restoreSkippedShort',
    failed: 'restoreFailedShort',
    running: 'restoreRunningShort',
    unreachable: 'connectionWaiting',
  }[state] || 'precheckSuccessful';
  badge.textContent = restoreT(key);
  badge.dataset.state = {success: 'success', simulation: 'success', skipped: 'warning',
    failed: 'error', running: 'running', unreachable: 'warning'}[state] || 'info';
}

function _currentPrecheckKey() {
  const source = restoreState.selectedPath || document.getElementById('restore-source-path')?.value || '';
  const target = document.getElementById('restore-target-path')?.value?.trim() || '';
  const mode = document.getElementById('restore-conflict-mode')?.value || 'skip';
  const dryRun = !!document.getElementById('restore-dry-run')?.checked;
  return JSON.stringify([restoreState.job, restoreState.archive, _restoreSelections().map(item => item.path), target, mode, dryRun]);
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
  const requestKey = _currentPrecheckKey();
  if (!confirmCheck || !restoreState.precheck?.ok || restoreState.autoPrecheckKey !== requestKey) {
    showMsg('restore-assist-msg', 'error', restoreT('confirmPrecheckFirst'));
    return;
  }
  if (!_isAllowedRestoreTarget(target)) {
    showMsg('restore-assist-msg', 'error', restoreT('targetRestriction', { roots: _restoreAllowedRootsText() }));
    return;
  }
  const summary = [
    restoreT('dryRun') + ': ' + restoreT(document.getElementById('restore-dry-run')?.checked ? 'yes' : 'no'),
    restoreT('archiveValue', { value: restoreState.archive }),
    restoreT('source', { value: _restoreSelections().map(item => item.path).join('\n') }),
    restoreT('targetPath', { value: target }),
    restoreT('conflictMode', { value: mode }),
    restoreT('ownerGroup', { value: preserveOwner ? restoreT('ownerFromBackup') : restoreT('ownerFromTarget') }),
  ].join('\n');
  const confirmed = await openRestoreConfirmModal(summary);
  if (!confirmed || requestKey !== _currentPrecheckKey()) return;
  restoreSetLiveMode(true);
  renderRestoreRunStatus({state: 'running', phase: 'starting', archive: restoreState.archive,
    source_paths: _restoreSelections().map(item => item.path), items: restoreState.precheck?.items || [],
    target_dir: target, conflict_mode: mode, preserve_owner: preserveOwner,
    dry_run: !!document.getElementById('restore-dry-run')?.checked, duration_seconds: 0});
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
        source_paths: _restoreSelections().map(item => item.path),
        target_dir: target,
        conflict_mode: mode,
        preserve_owner: preserveOwner,
        dry_run: !!document.getElementById('restore-dry-run')?.checked,
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
    _pollRestoreState(restoreId);
  } catch (err) {
    _stopRestorePolling();
    restoreState.activeRestoreId = '';
    _setRestoreAssistBusy(false);
    restoreUpdateConfirmState();
    showMsg('restore-assist-msg', 'error', restoreT('failed', { message: err.message }));
    restoreState.completed = true;
    renderRestoreRunStatus({...restoreState.runSnapshot, state: 'error', error: err.message});
    restoreSetStep(5);
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
  const resolved = (level === true) ? 'error' : (level === false ? 'info' : String(level || 'info'));
  showMsg('restore-msg', resolved, msg);
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
  _restoreRenderFolderTree();
  _restoreRenderSelectionSummary();
  _restoreRenderSelectedBox();
  if (Array.isArray(restoreState.files) && restoreState.files.length) {
    _restoreRenderFiles(restoreState.files);
  }
  renderRestoreJobSidebar();
  renderRestoreSelectedJob();
  renderRestoreArchiveList();
  renderRestorePrecheck(restoreState.precheck);
  if (restoreState.liveMode && restoreState.runSnapshot) renderRestoreRunStatus(restoreState.runSnapshot);
  const stepLabel = document.getElementById('restore-step-status');
  if (stepLabel) stepLabel.textContent = restoreT('stepStatus', {step: restoreState.step, total: 5});
  _restoreRenderBreadcrumb(restoreState.path);
  if (restoreState.precheck && !restoreState.liveMode) {
    const output = document.getElementById('restore-precheck-output');
    if (output) output.textContent = _restoreTechnicalPrecheckText(restoreState.precheck, !!document.getElementById('restore-dry-run')?.checked);
  }
  restoreUpdateConfirmState();
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
