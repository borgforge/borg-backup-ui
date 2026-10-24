'use strict';

// ══════════════════════════════════════════════════════════════════════════════
// JOBS PAGE
// ══════════════════════════════════════════════════════════════════════════════

window.BBUI = window.BBUI || {};
window.BBUI.jobsState = window.BBUI.jobsState || {
  loaded: false,
  jobs: [],
  pendingJobKey: null,
  pendingDeleteJobKey: null,
  confirmAction: 'start',
  activeEventSource: null,
  logTransportCheckTimer: null,
  logAutoScroll: true,
  pollingTimer: null,
  lastRunningSnapshot: '{}',  // JSON-String der zuletzt bekannten Running-States
  selectedLocation: 'all',
  confirmCloseSnapshot: '',
};
const jobsState = window.BBUI.jobsState;
let jobsRefreshRevision = 0;
let jobsRefreshPending = 0;
let jobsPollPending = false;
const JOBS_LOCATION_ORDER = ['local', 'usb', 'smb', 'storagebox', 'utility'];

window.BBUI.scheduleModalState = window.BBUI.scheduleModalState || {
  jobKey: null,
  frequency: 'daily', // 'daily' | 'weekly' | 'monthly' | 'custom'
  dow: 1,             // 0=So..6=Sa
  closeSnapshot: '',
};
const scheduleModalState = window.BBUI.scheduleModalState;

function jobsT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(key, params) || key;
}

function scheduleModalHelpers() {
  return window.BBUI?.components?.modal || {};
}

function scheduleCloseSnapshotPayload() {
  const modal = document.getElementById('schedule-modal');
  return JSON.stringify({
    form: scheduleModalHelpers().formSnapshot?.(modal) || '',
    frequency: scheduleModalState.frequency || '',
    dow: scheduleModalState.dow ?? '',
  });
}

function scheduleCaptureCloseSnapshot() {
  scheduleModalState.closeSnapshot = scheduleCloseSnapshotPayload();
}

function scheduleHasUnsavedChanges() {
  const modal = document.getElementById('schedule-modal');
  if (!modal || modal.classList.contains('hidden')) return false;
  return !!scheduleModalState.closeSnapshot && scheduleCloseSnapshotPayload() !== scheduleModalState.closeSnapshot;
}

function captureConfirmModalCloseSnapshot() {
  jobsState.confirmCloseSnapshot = scheduleModalHelpers().formSnapshot?.(document.getElementById('confirm-modal')) || '';
}

function confirmModalHasUnsavedInput() {
  const modal = document.getElementById('confirm-modal');
  if (!modal || modal.classList.contains('hidden')) return false;
  return !!jobsState.confirmCloseSnapshot
    && scheduleModalHelpers().formSnapshot?.(modal) !== jobsState.confirmCloseSnapshot;
}

function jobsLocationLabel(location) {
  return {
    local: jobsT('jobs.locationLocal'),
    usb: jobsT('jobs.locationUsb'),
    smb: jobsT('jobs.locationSmb'),
    storagebox: jobsT('jobs.locationStoragebox'),
  }[location] || location || '–';
}

function _coreSchedules() {
  return window.BBUI.core.getSchedulesData();
}

function _coreSetSchedules(next) {
  window.BBUI.core.setSchedulesData(next);
}

function _coreState() {
  return window.BBUI.core.state;
}

function _isDataDirReady() {
  return window.BBUI.core.isGlobalDataDirReady();
}

/**
 * Normalize Docker/VM control, falling back to legacy enable flags.
 * @param {object} job Job metadata from the API.
 * @param {'docker'|'vm'} kind Runtime type.
 * @returns {{mode: string, selected: string[]}} Effective control selection.
 */
function jobRuntimeControl(job, kind) {
  const legacyEnabled = kind === 'docker' ? !!job?.has_docker : !!job?.has_vm;
  const raw = job?.[`${kind}_control`] && typeof job[`${kind}_control`] === 'object'
    ? job[`${kind}_control`]
    : {};
  const modes = kind === 'docker' ? ['all', 'selected', 'except_selected', 'none'] : ['all', 'selected', 'none'];
  const mode = modes.includes(raw.mode)
    ? raw.mode
    : (legacyEnabled ? 'all' : 'none');
  const selected = Array.isArray(raw.selected)
    ? raw.selected.map(item => String(item || '').trim()).filter(Boolean)
    : [];
  return { mode, selected };
}

function jobRuntimeWarningText(job, kind) {
  const control = jobRuntimeControl(job, kind);
  if (control.mode === 'none') return '';
  if (control.mode === 'selected') {
    const names = control.selected.length
      ? control.selected.map(name => escHtml(name)).join(', ')
      : escHtml(jobsT('jobs.runtimeSelectionStored'));
    return jobsT(kind === 'docker' ? 'jobs.dockerSelectedWarning' : 'jobs.vmSelectedWarning', { names });
  }
  if (kind === 'docker' && control.mode === 'except_selected') {
    const names = control.selected.length
      ? control.selected.map(name => escHtml(name)).join(', ')
      : escHtml(jobsT('jobs.runtimeSelectionStored'));
    return jobsT('jobs.dockerExceptSelectedWarning', { names });
  }
  return jobsT(kind === 'docker' ? 'jobs.dockerWarning' : 'jobs.vmWarning');
}

// ── Jobs laden ────────────────────────────────────────────────────────────────

/** Load jobs, run status and schedules, then refresh the jobs workspace. */
async function refreshJobs() {
  const revision = ++jobsRefreshRevision;
  jobsRefreshPending++;
  const btn = document.getElementById('jobs-refresh-btn');
  if (btn) btn.classList.add('loading');
  hideJobsMessage();

  try {
    await window.BBUI.core.updateDataDirWarning();
    const [jobsRes, schedRes, runningRes] = await Promise.all([
      fetch('/api/jobs'),
      fetch('/api/schedules'),
      fetch('/api/jobs/running'),
    ]);
    // Read the saved report after runtime state so a completed run is published atomically.
    const statusRes = await fetch('/api/status');
    if (!jobsRes.ok) throw new Error(`Jobs: HTTP ${jobsRes.status}`);
    if (!statusRes.ok) throw new Error(`Status: HTTP ${statusRes.status}`);
    if (!runningRes.ok) throw new Error(`Running jobs: HTTP ${runningRes.status}`);

    const jobsData   = await jobsRes.json();
    const statusData = await statusRes.json();
    const runningData = await runningRes.json();
    if (schedRes.ok) {
      const nextSchedules = await schedRes.json();
      if (revision === jobsRefreshRevision) _coreSetSchedules(nextSchedules);
    }

    await window.BBUI.jobGroups?.load();
    if (revision !== jobsRefreshRevision) return;
    const statusMap = {};
    for (const b of (statusData.backups || [])) {
      statusMap[b.key] = b;
    }

    jobsState.jobs = (jobsData.jobs || []).map(j => ({
      ...j,
      ...statusMap[j.key] ? {
        last_status:    statusMap[j.key].status,
        last_time_ago:  statusMap[j.key].time_ago,
        last_timestamp: statusMap[j.key].timestamp,
        last_exit_code: statusMap[j.key].exit_code,
        last_borg_steps: statusMap[j.key].borg_steps || {},
        last_job_steps: statusMap[j.key].job_steps || [],
        last_successful_backup: statusMap[j.key].last_successful_backup || {},
        last_duration_seconds: statusMap[j.key].duration_seconds,
        last_run_id: statusMap[j.key].run_id || '',
        last_log_file: statusMap[j.key].log_file || '',
      } : {},
      ...jobRuntimeState(runningData[j.key], j),
    }));
    jobsState.lastRunningSnapshot = JSON.stringify(runningData);

    jobsState.loaded = true;
    renderJobsGrid(jobsState.jobs);
    updateBorgProgressDisplays(runningData);
  } catch (err) {
    if (revision === jobsRefreshRevision) showJobsError(jobsT('jobs.loadError', { message: err.message }));
  } finally {
    jobsRefreshPending--;
    if (btn && !jobsRefreshPending) btn.classList.remove('loading');
  }
}

// ── Jobs-Polling (erkennt Cron-gestartete Jobs) ─────────────────────────────

function startJobsPolling() {
  if (jobsState.pollingTimer) return;
  jobsState.pollingTimer = setInterval(_pollRunningStates, 3_000);
}

function stopJobsPolling() {
  if (jobsState.pollingTimer) {
    clearInterval(jobsState.pollingTimer);
    jobsState.pollingTimer = null;
  }
}

/** Poll one snapshot at a time; publish finished runs together with their saved report. */
async function _pollRunningStates() {
  if (_coreState().currentPage !== 'jobs' || jobsPollPending || jobsRefreshPending) return;
  jobsPollPending = true;
  const revision = jobsRefreshRevision;
  try {
    await window.BBUI.jobGroups?.load();
    const res = await fetch('/api/jobs/running');
    if (!res.ok) return;
    const running = await res.json();
    if (revision !== jobsRefreshRevision) return;
    const runFinished = jobsState.jobs.some(j => j.running && !running[j.key]?.running);
    if (runFinished) {
      // Keep the existing timeline on screen until the completed report is loaded.
      await refreshJobs();
      return;
    }
    const snapshot = JSON.stringify(running);
    if (snapshot === jobsState.lastRunningSnapshot) {
      updateBorgProgressDisplays(running);
      return;
    }
    jobsState.lastRunningSnapshot = snapshot;
    jobsState.jobs = jobsState.jobs.map(j => ({...j, ...jobRuntimeState(running[j.key], j)}));
    renderJobsGrid(jobsState.jobs);
  } catch {
    // Keep the last displayed state on transient network errors; retry next poll.
  } finally {
    jobsPollPending = false;
  }
}

function jobRuntimeState(runtime, previous = {}) {
  return {
    running: runtime?.running ?? false,
    run_log_available: runtime?.log_available ?? previous.run_log_available ?? true,
    run_id: runtime?.run_id ?? previous.run_id ?? '',
    run_file_activity: runtime ? runtime.file_activity === true : (previous.run_file_activity ?? false),
    run_phase: runtime?.phase ?? '',
    borg_progress: runtime?.borg_progress ?? null,
    run_borg_steps: runtime?.running ? (runtime.borg_steps ?? {}) : {},
    run_job_steps: runtime?.running ? (runtime.job_steps ?? []) : [],
    run_start_time: runtime?.start_time ?? previous.run_start_time ?? '',
    group_name: runtime?.group_name ?? '',
    group_run_id: runtime?.group_run_id ?? '',
    cancel_allowed: runtime?.cancel_allowed ?? false,
    cancellation_deferred: runtime?.cancellation_deferred ?? false,
    cancel_requested: runtime?.cancel_requested ?? false,
    cancel_message_key: runtime?.message_key ?? '',
  };
}

/**
 * Render process progress after 60 seconds, separately from persisted log text.
 * @param {Object|null} runtime Active run with phase and transient borg_progress.
 * @param {number} now Current Unix time in seconds for elapsed/last-update ages.
 * @returns {string} Escaped status markup, or an empty string before 60 seconds or outside a supported Borg process.
 */
function renderBorgProgress(runtime, now = Date.now() / 1000) {
  const progress = runtime?.borg_progress;
  const phase = runtime?.phase ?? runtime?.run_phase;
  if (!runtime?.running || !['borg_create', 'borg_prune', 'borg_compact', 'borg_check'].includes(phase) || !progress) return '';
  if (typeof progress.started_at !== 'number' || !Number.isFinite(progress.started_at)
      || now - progress.started_at < 60) return '';
  if (progress.phase && progress.phase !== phase) return '';
  const creating = phase === 'borg_create';
  const maintenance = ['borg_prune', 'borg_compact'].includes(phase);
  // Maintenance shows details only if Borg has actually emitted progress.
  if (maintenance && (typeof progress.updated_at !== 'number' || !Number.isFinite(progress.updated_at))) return '';
  const percent = !creating && typeof progress.percent === 'number' && Number.isFinite(progress.percent)
    ? Math.max(0, Math.min(100, progress.percent)) : null;
  const age = timestamp => Math.max(0, Math.floor(now - timestamp));
  const elapsed = typeof progress.started_at === 'number' && Number.isFinite(progress.started_at)
    ? jobsT('jobs.borgElapsed', { time: borgProgressDuration(age(progress.started_at)) }) : '';
  const updated = typeof progress.updated_at === 'number' && Number.isFinite(progress.updated_at)
    ? jobsT('jobs.borgUpdated', { time: borgProgressDuration(age(progress.updated_at)) })
    : jobsT('jobs.borgWaiting');
  const label = jobsT(maintenance ? `jobs.${phase === 'borg_prune' ? 'prune' : 'compact'}Running` : (creating ? 'jobs.createTitle' : 'jobs.checkTitle'));
  const counters = [];
  if (creating) {
    if (Number.isSafeInteger(progress.nfiles) && progress.nfiles >= 0) {
      counters.push(jobsT('jobs.createFiles', { count: jobMetricNumber(progress.nfiles) }));
    }
    if (Number.isSafeInteger(progress.original_size) && progress.original_size >= 0) {
      counters.push(jobsT('jobs.createBytes', { size: borgProgressSize(progress.original_size) }));
    }
  }
  if (creating && Number.isSafeInteger(progress.deduplicated_size) && progress.deduplicated_size >= 0) {
    counters.push(jobsT('jobs.workflow.newData', {size: borgProgressSize(progress.deduplicated_size)}));
  }
  const details = creating ? counters : [jobsT(maintenance ? 'jobs.borgCurrentStep' : 'jobs.checkStep')];
  return `<div class="borg-progress">
    <div class="borg-progress-heading"><strong>${escHtml(label)}</strong>${percent === null ? '' : `<strong>${escHtml(percent)} %</strong>`}</div>
    <progress max="100"${percent === null ? '' : ` value="${percent}"`} aria-label="${escHtml(jobsT(creating ? 'jobs.createRunning' : 'jobs.borgCurrentStep'))}"></progress>
    ${details.map(detail => `<small class="borg-progress-metric">${escHtml(detail)}</small>`).join('')}
    <small>${escHtml([elapsed, updated].filter(Boolean).join(' · '))}</small>
  </div>`;
}

/** Format a measured value in the selected UI language.
 * @param {number} value Validated count or size to display.
 * @param {number} digits Number of fractional digits (zero for counts).
 * @returns {string} Localized number without a unit.
 */
function jobMetricNumber(value, digits = 0) {
  const language = window.BBUI?.components?.i18n?.getLanguage?.() === 'de' ? 'de' : 'en';
  return new Intl.NumberFormat(language, {minimumFractionDigits:digits, maximumFractionDigits:digits}).format(value);
}

/** Format a validated non-negative byte count using binary units. */
function borgProgressSize(bytes) {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
  const index = bytes > 0 ? Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1) : 0;
  return `${jobMetricNumber(bytes / 1024 ** index, index ? 1 : 0)} ${units[index]}`;
}

/** Format an elapsed duration without suggesting a remaining-time estimate. */
function borgProgressDuration(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor(seconds % 3600 / 60);
  const s = seconds % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`;
}

/** Return known run steps including managed database exports; older reports retain their Borg ledger. */
function jobWorkflowSteps(job) {
  const configured = job.running ? job.run_job_steps : job.last_job_steps;
  const allowed = ['pre_script', 'database_backup', 'docker_sequence', 'stop_docker', 'stop_vms', 'create', 'start_docker', 'start_vms', 'prune', 'compact', 'check', 'post_script'];
  if (Array.isArray(configured) && configured.length) {
    return configured.filter(step => step && allowed.includes(step.id));
  }
  const legacy = job.running ? job.run_borg_steps : job.last_borg_steps;
  return legacy && typeof legacy === 'object'
    ? ['create', 'prune', 'compact', 'check'].filter(id => legacy[id]).map(id => ({...legacy[id], id})) : [];
}

/** Accessible, shape-distinct SVG symbols; running alone uses a rotating ring. */
function jobStepIcon(state) {
  const circle = '<circle cx="12" cy="12" r="9"/>';
  const paths = {
    success: circle + '<path d="m8 12 3 3 5-6"/>',
    error: circle + '<path d="m9 9 6 6m0-6-6 6"/>',
    warning: '<path d="m12 3 10 18H2Z"/><path d="M12 9v5m0 3v.1"/>',
    interrupted: '<path d="m12 3 10 18H2Z"/><path d="M12 9v5m0 3v.1"/>',
    cancelled: circle + '<rect x="9" y="9" width="6" height="6"/>',
    skipped: circle + '<path d="M8 12h8"/>', pending: circle,
    running: '<circle class="job-step-ring-track" cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 9 9"/>',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[state] || circle}</svg>`;
}

/** Resolve labels and measured duration without inferring a terminal success. */
function jobStepView(step, job, now) {
  const allowed = ['success', 'warning', 'error', 'cancelled', 'skipped', 'pending', 'running', 'interrupted'];
  let state = allowed.includes(step.status) ? step.status : 'pending';
  if (state === 'running' && !job.running) state = 'interrupted';
  const reasons = ['not_due', 'keep_all', 'not_run', 'after_cancel', 'post_condition', 'unavailable', 'no_container_paths', 'no_main_archive'];
  let reason = state === 'skipped' && reasons.includes(step.reason) ? step.reason : state;
  if (state === 'pending' && !job.running) reason = 'not_run';
  const status = jobsT(`jobs.borgStep.${reason}`);
  const valid = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
  const seconds = state === 'running' && valid(step.started_at) ? Math.max(0, now - step.started_at) : step.duration_seconds;
  const duration = !['skipped', 'pending', 'interrupted'].includes(state) && valid(seconds)
    ? borgProgressDuration(Math.floor(seconds)) : status;
  const label = ['create', 'prune', 'compact', 'check'].includes(step.id) ? `borg ${step.id}` : jobsT(`jobs.workflow.names.${step.id}`);
  return {state, status, duration, label};
}

/** Format allowlisted measured results, keeping problems but omitting redundant success/exit 0. */
function jobStepDetails(step, view) {
  const details = step.details || {};
  const parts = [];
  const count = key => Number.isSafeInteger(details[key]) && details[key] >= 0;
  if (step.id === 'database_backup') {
    const results = details.results || (details.result ? [details.result] : []);
    for (const result of results) for (const file of result.files || []) {
      parts.push(`${file.database}: ${borgProgressSize(file.bytes)} / ${borgProgressDuration(Math.floor(file.duration_seconds || 0))} / ${jobsT(result.archived ? 'jobs.databaseArchived' : 'jobs.databaseDumped')}`);
    }
    if (details.error_code) parts.push(apiErrorMessage({code: details.error_code}));
  }
  if (step.id === 'docker_sequence') {
    // Container groups run one after another; list only the current and problematic groups.
    if (count('target_count')) {
      parts.push(jobsT('jobs.workflow.sequenceProgress', {done: count('completed_count') ? details.completed_count : 0, total: details.target_count}));
    }
    if (view.state === 'running' && typeof details.current === 'string' && details.current) {
      parts.push(jobsT('jobs.workflow.sequenceCurrent', {name: details.current}));
    }
    for (const group of Array.isArray(details.groups) ? details.groups : []) {
      if (!['warning', 'error', 'cancelled'].includes(group?.status) || !Array.isArray(group.containers)) continue;
      parts.push(`${group.containers.join(' + ')}: ${jobsT(`jobs.borgStep.${group.status}`)}`);
    }
    return (view.state === 'success' && parts.length ? parts : [view.status, ...parts]).join(' · ');
  }
  if (count('target_count')) {
    const action = ['stop_docker', 'stop_vms'].includes(step.id) ? 'targetsStopped'
      : ['start_docker', 'start_vms'].includes(step.id) ? 'targetsStarted' : 'targetsDone';
    parts.push(count('completed_count') ? jobsT(`jobs.workflow.${action}`, {done: details.completed_count, total: details.target_count})
      : jobsT('jobs.workflow.targets', {count: details.target_count}));
  }
  if (count('forced_count') && details.forced_count) parts.push(jobsT('jobs.workflow.forced', {count: details.forced_count}));
  if (count('nfiles')) parts.push(jobsT('jobs.createFiles', {count: jobMetricNumber(details.nfiles)}));
  if (count('original_size')) parts.push(jobsT('jobs.createBytes', {size: borgProgressSize(details.original_size)}));
  if (count('deduplicated_size')) parts.push(jobsT('jobs.workflow.newData', {size: borgProgressSize(details.deduplicated_size)}));
  if (count('freed_bytes')) parts.push(jobsT('jobs.workflow.freedSpace', {size: borgProgressSize(details.freed_bytes)}));
  if (count('kept_archives')) parts.push(jobsT('jobs.workflow.kept', {count: details.kept_archives}));
  if (count('pruned_archives')) parts.push(jobsT('jobs.workflow.pruned', {count: details.pruned_archives}));
  if (['pre_script', 'post_script'].includes(step.id) && typeof details.script_name === 'string' && details.script_name) parts.push(details.script_name);
  if (Number.isInteger(step.exit_code) && step.exit_code !== 0) parts.push(jobsT('jobs.workflow.exitCode', {code: step.exit_code}));
  if (details.hook_status === 'timeout') parts.push(jobsT('jobs.workflow.timeout'));
  return (view.state === 'success' && parts.length ? parts : [view.status, ...parts]).join(' · ');
}

/** Format stored local timestamps and a live relative age in the selected language. */
function jobBackupDate(timestamp, now) {
  const date = new Date(String(timestamp || '').replace(' ', 'T'));
  if (!Number.isFinite(date.getTime())) return '';
  const language = window.BBUI?.components?.i18n?.getLanguage?.() === 'en' ? 'en' : 'de';
  const seconds = Math.max(0, Math.floor(now - date.getTime() / 1000));
  const [unit, divisor] = seconds >= 86400 ? ['day', 86400] : seconds >= 3600 ? ['hour', 3600] : seconds >= 60 ? ['minute', 60] : ['second', 1];
  return `${date.toLocaleString(language, {year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'})} · ${new Intl.RelativeTimeFormat(language, {numeric:'always'}).format(-Math.floor(seconds / divisor), unit)}`;
}

/** Keep the last successful backup visible independently of the latest run outcome. */
function renderJobBackupFooter(job, now) {
  const success = job.last_successful_backup?.timestamp ? job.last_successful_backup
    : job.last_status === 'success' ? {timestamp:job.last_timestamp, duration_seconds:job.last_duration_seconds} : null;
  const lines = [];
  const line = (key, stamp, duration) => {
    const date = jobBackupDate(stamp, now);
    if (!date) return '';
    const measured = typeof duration === 'number' && Number.isFinite(duration) && duration >= 0;
    return jobsT(key, {date}) + (measured ? ' · ' + jobsT('jobs.borgTotalDuration', {time:borgProgressDuration(Math.floor(duration))}) : '');
  };
  if (!job.running && job.last_timestamp && job.last_timestamp !== success?.timestamp) lines.push(line('jobs.borgCompletedAt', job.last_timestamp, job.last_duration_seconds));
  if (success) lines.push(line('jobs.workflow.lastSuccess', success.timestamp, success.duration_seconds));
  else if (job.last_timestamp || jobWorkflowSteps(job).length) lines.push(jobsT('jobs.workflow.noSuccess'));
  return lines.filter(Boolean).map(text => `<small class="borg-run-summary">${escHtml(text)}</small>`).join('');
}

const jobWorkflowOpen = new Set();

/** Render the permanently named timeline and optional details below the full job row. */
function renderBorgRun(job, now = Date.now() / 1000) {
  const steps = jobWorkflowSteps(job);
  const footer = renderJobBackupFooter(job, now);
  if (!steps.length) return footer ? `<div class="job-workflow-footer"><div class="job-backup-summary">${footer}</div></div>` : '';
  const opened = jobWorkflowOpen.has(job.key);
  const items = steps.map(step => {
    const view = jobStepView(step, job, now);
    return `<li class="borg-step is-${view.state}" data-step="${escHtml(step.id)}"${view.state === 'running' ? ' aria-current="step"' : ''} title="${escHtml(view.status)}">
      <span class="borg-step-dot" role="img" aria-label="${escHtml(view.status)}">${jobStepIcon(view.state)}</span>
      <span class="borg-step-command">${escHtml(view.label)}</span>
      <span class="borg-step-duration">${escHtml(view.duration)}</span></li>`;
  }).join('');
  const details = opened ? `<div class="job-workflow-details" id="job-step-details-${escHtml(job.key)}"><table>
    <caption>${jobsT('jobs.workflow.details')}</caption>
    <colgroup><col class="job-detail-step-col"><col><col class="job-detail-duration-col"></colgroup>
    <thead class="job-details-sr"><tr><th>${jobsT('jobs.workflow.step')}</th><th>${jobsT('jobs.workflow.result')}</th><th>${jobsT('jobs.workflow.duration')}</th></tr></thead>
    <tbody>${steps.map(step => {
      const view = jobStepView(step, job, now);
      const duration = ['skipped', 'pending', 'interrupted'].includes(view.state) ? '—' : view.duration;
      const explanation = step.id === 'create' ? jobsT('jobs.workflow.createMeaning') : step.id === 'compact' ? jobsT('jobs.workflow.compactMeaning') : '';
      return `<tr class="is-${view.state}" data-step="${escHtml(step.id)}"><th scope="row"><span class="job-detail-name"><span class="job-detail-icon" role="img" aria-label="${escHtml(view.status)}">${jobStepIcon(view.state)}</span>${escHtml(view.label)}</span></th><td${explanation ? ` title="${escHtml(explanation)}"` : ''}>${escHtml(jobStepDetails(step, view))}</td><td class="job-detail-duration">${escHtml(duration)}</td></tr>`;
    }).join('')}</tbody>
    </table></div>` : `<div id="job-step-details-${escHtml(job.key)}" hidden></div>`;
  return `<ol class="borg-stepper" tabindex="0" aria-label="${escHtml(jobsT('jobs.workflow.steps'))}">${items}</ol>
    ${details}<div class="job-workflow-footer"><div class="job-backup-summary">${footer}</div>
    <button class="job-workflow-toggle" data-jobs-action="toggle-workflow" data-job-key="${escHtml(job.key)}" aria-expanded="${opened}" aria-controls="job-step-details-${escHtml(job.key)}">${jobsT(opened ? 'jobs.workflow.hideDetails' : 'jobs.workflow.showDetails')} <span aria-hidden="true">${opened ? '⌃' : '⌄'}</span></button></div>`;
}

/** Identify the current configured action immediately; Borg counters wait 60 seconds. */
function renderJobOperation(job, now = Date.now() / 1000) {
  const active = job.running && jobWorkflowSteps(job).find(step => step.status === 'running');
  const view = active && jobStepView(active, job, now);
  const progress = renderBorgProgress(job, now);
  const current = active?.id === 'docker_sequence' && typeof active.details?.current === 'string' ? active.details.current : '';
  const label = view && current ? `${view.label}: ${current}` : view?.label;
  let html = view ? `<div class="job-active-step"><strong>${escHtml(label)}</strong>${progress ? '' : `<small>${escHtml(jobsT('jobs.borgElapsed', {time:view.duration}))}</small>`}</div>` : '';
  if (!view && job.running && ['preparing', 'mounting', 'unmounting', 'pre_script', 'database_backup', 'post_script', 'stopping_docker', 'stopping_vms', 'recovering_docker', 'recovering_vms'].includes(job.run_phase)) {
    html += `<div class="job-active-step"><strong>${escHtml(jobsT(`jobGroups.phases.${job.run_phase}`))}</strong></div>`;
  }
  html += progress;
  const start = Date.parse(job.run_start_time || '');
  if (job.running && Number.isFinite(start)) html += `<small class="borg-run-summary">${escHtml(jobsT('jobs.borgTotalElapsed', {time:borgProgressDuration(Math.max(0, Math.floor(now - start/1000)))}))}</small>`;
  return html;
}

/**
 * Reconcile generated job markup in place, preserving animations and focused controls.
 * Keys are local element IDs or step IDs; unchanged attributes are never rewritten.
 * Only trusted render-function markup is accepted. Event delegation remains on the grid.
 * @param {Element} target Existing job view container.
 * @param {string} html Escaped markup produced by the job renderers.
 */
function patchJobMarkup(target, html) {
  const template = document.createElement('template');
  template.innerHTML = html;
  const key = node => node.nodeType === 1 ? node.id || node.getAttribute('data-step') || '' : '';
  const compatible = (a, b) => a && a.nodeType === b.nodeType && a.nodeName === b.nodeName && key(a) === key(b);
  const sync = (parent, desired) => {
    let cursor = parent.firstChild;
    for (const next of Array.from(desired.childNodes)) {
      let current = cursor;
      if (!compatible(current, next)) {
        current = key(next) ? Array.from(parent.childNodes).find(node => compatible(node, next)) : null;
        if (current) parent.insertBefore(current, cursor);
        else {
          parent.insertBefore(next.cloneNode(true), cursor);
          continue;
        }
      }
      if (current.nodeType === 1) {
        for (const attr of Array.from(current.attributes)) {
          if (!next.hasAttribute(attr.name)) current.removeAttribute(attr.name);
        }
        for (const attr of Array.from(next.attributes)) {
          if (current.getAttribute(attr.name) !== attr.value) current.setAttribute(attr.name, attr.value);
        }
        sync(current, next);
      } else if (current.nodeValue !== next.nodeValue) current.nodeValue = next.nodeValue;
      cursor = current.nextSibling;
    }
    while (cursor) {
      const next = cursor.nextSibling;
      parent.removeChild(cursor);
      cursor = next;
    }
  };
  sync(target, template.content);
}

/** Refresh counters and relative ages without replacing the running SVG or progress element. */
function updateBorgProgressDisplays(running) {
  for (const job of jobsState.jobs) {
    const current = {...job, ...jobRuntimeState(running[job.key], job)};
    const progress = document.getElementById(`job-borg-progress-${job.key}`);
    if (progress) patchJobMarkup(progress, renderJobOperation(current));
    const target = document.getElementById(`job-workflow-${job.key}`);
    if (target) patchJobMarkup(target, renderBorgRun(current));
  }
}

// ── Jobs rendern ──────────────────────────────────────────────────────────────

function renderJobsGrid(jobs) {
  if (window.BBUI.jobGroups?.state.view === 'groups') { window.BBUI.jobGroups.render(); return; }
  const el = document.getElementById('jobs-grid');
  if (!el) return;
  const jobsNewBtn = document.getElementById('jobs-new-btn');

  const logOutput = document.getElementById('log-output');
  jobsState.activityLog?.onScroll();
  const savedLogScrollTop = logOutput ? logOutput.scrollTop : 0;
  const savedLogDistanceFromBottom = logOutput
    ? (logOutput.scrollHeight - logOutput.scrollTop)
    : 0;

  const logPanel = document.getElementById('log-panel');
  let rescuedSlotId = null;
  if (logPanel && el.contains(logPanel)) {
    rescuedSlotId = logPanel.parentElement?.id || null;
    el.after(logPanel);
  }

  if (!jobs || jobs.length === 0) {
    if (jobsNewBtn) jobsNewBtn.classList.add('hidden');
    renderJobsLocationSidebar([]);
    updateJobsSelection([]);
    el.innerHTML = '';
    showJobsEmpty(`${jobsT('jobs.empty')}<br><button class="btn btn-primary btn-sm" id="jobs-empty-create-btn" data-jobs-action="open-wizard" style="margin-top:10px">${jobsT('jobs.createFirst')}</button>`);
    // Defensive fallback: keep direct binding in case delegated handlers are unavailable.
    document.getElementById('jobs-empty-create-btn')?.addEventListener('click', openWizard);
    return;
  }
  if (jobsNewBtn) jobsNewBtn.classList.remove('hidden');

  const visible = jobs
    .filter((job) => jobsState.selectedLocation === 'all' || jobsLocationKey(job) === jobsState.selectedLocation)
    .sort((a, b) => {
      const locationDelta = JOBS_LOCATION_ORDER.indexOf(jobsLocationKey(a))
        - JOBS_LOCATION_ORDER.indexOf(jobsLocationKey(b));
      if (locationDelta) return locationDelta;
      return String(a.name || a.display_name || '').localeCompare(String(b.name || b.display_name || ''));
    });

  renderJobsLocationSidebar(jobs);
  updateJobsSelection(visible);

  if (visible.length === 0) {
    el.innerHTML = `<div class="ui-empty">${escHtml(jobsT('jobs.noLocationJobs'))}</div>`;
  } else {
    const groups = jobsState.selectedLocation === 'all'
      ? JOBS_LOCATION_ORDER
      : [jobsState.selectedLocation];
    patchJobMarkup(el, groups.map((location) => {
      const locationJobs = visible.filter((job) => jobsLocationKey(job) === location);
      return locationJobs.length ? renderJobsLocationGroup(location, locationJobs) : '';
    }).join(''));
  }

  if (rescuedSlotId) {
    const newSlot = document.getElementById(rescuedSlotId);
    if (newSlot) newSlot.appendChild(logPanel);
  }

  if (logOutput) {
    if (jobsState.logAutoScroll) {
      logOutput.scrollTop = logOutput.scrollHeight;
    } else {
      const target = logOutput.scrollHeight - savedLogDistanceFromBottom;
      logOutput.scrollTop = Math.max(0, target);
      if (Math.abs(logOutput.scrollTop - target) > 4) {
        logOutput.scrollTop = savedLogScrollTop;
      }
    }
    if (jobsState.activityLog) jobsState.activityLog.syncScroll();
    else checkScrollHint(logOutput);
  }
}

function jobsLocationKey(job) {
  if (job?.is_utility) return 'utility';
  const location = String(job?.location || '').toLowerCase();
  return JOBS_LOCATION_ORDER.includes(location) && location !== 'utility' ? location : 'local';
}

function jobsLocationName(location) {
  return location === 'utility' ? jobsT('jobs.otherScripts') : jobsLocationLabel(location);
}

function jobsLocationGlyph(location) {
  return locationIcon(location);
}

function jobsCount(count) {
  return jobsT(count === 1 ? 'jobs.jobCountOne' : 'jobs.jobCountMany', { count });
}

function renderJobsLocationSidebar(jobs) {
  const el = document.getElementById('jobs-location-list');
  if (!el) return;
  const locations = ['all', ...JOBS_LOCATION_ORDER.filter((location) => location !== 'utility' || jobs.some((job) => job.is_utility))];
  el.innerHTML = locations.map((location) => {
    const count = location === 'all' ? jobs.length : jobs.filter((job) => jobsLocationKey(job) === location).length;
    const label = location === 'all' ? jobsT('jobs.allLocations') : jobsLocationName(location);
    const detail = location === 'all' ? jobsT('jobs.overview') : jobsCount(count);
    return `<button class="ui-context-nav__item ${jobsState.selectedLocation === location ? 'is-active' : ''}" data-jobs-location="${location}" ${jobsState.selectedLocation === location ? 'aria-current="page"' : ''}>
      <span class="location-nav-glyph ${location}">${jobsLocationGlyph(location)}</span>
      <span class="location-nav-copy"><strong>${escHtml(label)}</strong><small>${escHtml(detail)}</small></span>
      <span class="ui-badge location-nav-count">${count}</span>
    </button>`;
  }).join('');
  el.querySelectorAll('[data-jobs-location]').forEach((button) => {
    button.addEventListener('click', () => {
      jobsState.selectedLocation = button.dataset.jobsLocation || 'all';
      renderJobsGrid(jobs);
    });
  });
}

function updateJobsSelection(visible) {
  const title = document.getElementById('jobs-selection-title');
  const count = document.getElementById('jobs-selection-count');
  if (title) {
    title.textContent = jobsState.selectedLocation === 'all'
      ? jobsT('jobs.allLocations')
      : jobsLocationName(jobsState.selectedLocation);
  }
  if (count) count.textContent = jobsCount(visible.length);
}

/** Group only populated destinations; selected locations already have a page heading. */
function renderJobsLocationGroup(location, jobs) {
  if (!jobs.length) return '';
  return `<section class="jobs-location-group" id="jobs-location-${escHtml(location)}">
    ${jobsState.selectedLocation === 'all' ? `<header class="jobs-location-group__header">
      <div class="jobs-location-group__identity">
        <span class="location-nav-glyph ${location}">${jobsLocationGlyph(location)}</span>
        <span><h3>${escHtml(jobsLocationName(location))}</h3><small>${escHtml(jobsCount(jobs.length))}</small></span>
      </div>
      <span class="ui-badge">${jobs.length}</span>
    </header>` : ''}
    <div class="jobs-location-group__body">${jobs.map(renderJobCard).join('')}<div class="group-log-slot" id="log-slot-${location}"></div></div>
  </section>`;
}

function renderJobCard(job) {
  const isRunning = job.running;
  const titleName = job.name || job.display_name || 'Backup';
  const iconKey = resolveJobIcon(job);
  const iconColorKey = resolveJobIconColor(job);
  const iconColorClass = iconColorKey ? ` type-icon-color-${iconColorKey}` : '';

  const schedules = _coreSchedules();
  const sched = schedules[job.key];
  const schedActive = sched && sched.enabled;

  const features = [];
  if (job.has_docker) {
    features.push(`<span class="feature-badge">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <path d="M3 9h18"/>
      </svg>Docker
    </span>`);
  }
  if (job.has_vm) {
    features.push(`<span class="feature-badge">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="2" y="3" width="20" height="14" rx="1"/>
        <line x1="8" y1="21" x2="16" y2="21"/>
        <line x1="12" y1="17" x2="12" y2="21"/>
      </svg>VMs
    </span>`);
  }

  const nextRun = schedActive ? calcNextRun(sched.cron) : null;
  const retention = [job.retention_daily, job.retention_weekly, job.retention_monthly, job.retention_yearly]
    .map((v) => String(v || '').trim())
    .filter((v) => v !== '');
  const policy = job.retention || {};
  const retentionText = policy.mode === 'all' ? jobsT('wizard.retentionAllSummary')
    : policy.mode === 'last' ? jobsT('wizard.retentionLastSummary', {count: policy.last})
    : [Number(policy.hourly) > 0 ? `${jobsT('wizard.retentionHourly')}: ${policy.hourly}` : '', retention.join('/'),
       policy.within ? jobsT('wizard.retentionWithinSummary', {count: policy.within}) : ''].filter(Boolean).join(' · ');
  const policyHtml = (job.compression || retention.length === 4)
    ? `<div class="job-policy">
         ${job.compression ? `<span>${jobsT('jobs.compressionShort')} <code>${escHtml(job.compression)}</code></span>` : ''}
         ${retention.length === 4 ? `<span>${jobsT('jobs.retentionShort')} <code>${escHtml(retentionText)}</code></span>` : ''}
       </div>`
    : '';
  const schedHtml = (job.enabled === false) ? '' : (sched
    ? `<div class="job-schedule-info ${schedActive ? '' : 'disabled'}">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12">
           <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
         </svg>
         ${schedActive
           ? (nextRun ? jobsT('jobs.nextRun', { date: fmtDateShort(nextRun) }) : sched.cron)
           : jobsT('jobs.scheduleDisabled')}
       </div>`
    : '');

  const stateClass = isRunning ? 'info' : job.enabled === false ? 'warning' : (job.last_status === 'cancelled' ? 'warning' : (job.last_status || 'unknown'));
  const stateLabel = isRunning
    ? jobsT('jobs.running')
    : job.enabled === false
      ? jobsT('jobs.disabled')
      : job.last_status
        ? (job.last_status === 'success' && jobWorkflowSteps(job).length ? jobsT('jobs.borgSuccessful') : statusLabel(job.last_status))
        : jobsT('jobs.ready');
  const lastRunText = job.last_status
    ? `${jobsT('jobs.lastRun')} ${job.last_time_ago || '—'}`
    : jobsT('jobs.neverRun');
  const verificationHtml = renderJobRestoreVerification(job);

  const startDisabled = !_isDataDirReady();
  const effectiveStartDisabled = startDisabled || job.enabled === false;
  const cancelStatus = job.cancel_requested
    ? jobsT(job.cancel_message_key || 'jobs.cancelPending')
    : (!job.cancel_allowed && job.cancel_message_key)
      ? jobsT(job.cancel_message_key)
      : '';
  const cancelButton = job.cancel_allowed && !job.cancel_requested && job.run_id
    ? `<button class="btn btn-danger btn-sm" data-jobs-action="cancel-job" data-job-key="${escHtml(job.key)}">${jobsT('jobs.cancelJob')}</button>`
    : '';
  const actionHtml = isRunning
    ? `<div class="jobs-running-actions">
         <div class="jobs-running-state"><span class="running-dot"></span><span>${jobsT('jobs.running')}</span></div>
         <div class="jobs-running-buttons">
           ${job.run_log_available === false ? '' : `<button class="btn btn-secondary btn-sm" data-jobs-action="open-log" data-job-key="${escHtml(job.key)}">${jobsT('jobs.showLiveLog')}</button>`}
           ${cancelButton}
         </div>
         ${cancelStatus ? `<div class="jobs-running-message">${escHtml(cancelStatus)}</div>` : ''}
       </div>`
    : `<div class="jobs-completed-actions"><button class="btn btn-primary" data-jobs-action="start-job" data-job-key="${escHtml(job.key)}" ${effectiveStartDisabled ? `disabled title="${job.enabled === false ? jobsT('jobs.disabled') : jobsT('jobs.dataDirRequired')}"` : ''}>
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
           <polygon points="5 3 19 12 5 21 5 3"/>
         </svg>
         ${jobsT('jobs.startAction')}
       </button>${job.last_log_file && jobWorkflowSteps(job).length ? `<button class="btn btn-secondary btn-sm" data-jobs-action="open-saved-log" data-job-key="${escHtml(job.key)}">${jobsT('jobs.showLog')}</button>` : ''}</div>`;

  return `<article class="jobs-redesign-row ${isRunning ? 'is-running' : ''} ${job.enabled === false ? 'is-disabled' : ''}" id="job-card-${escHtml(job.key)}">
    <div class="jobs-redesign-cell jobs-redesign-main">
      <div class="job-card-title">
        <div class="type-icon${iconColorClass}">${typeIcon(iconKey)}</div>
        <div><div class="type-name">${escHtml(titleName)}</div><span class="type-sub">${escHtml(job.archive_prefix || '')}</span></div>
      </div>
      ${window.BBUI.jobGroups?.membership(job) || ''}
      ${job.description ? `<div class="job-description">${renderDescriptionMarkdown(job.description)}</div>` : ''}
      <div class="job-meta">${features.join('')}</div>
      ${job.enabled === false ? `<div class="status-message warning-state jobs-redesign-disabled-note">${jobsT('jobs.disabled')}</div>` : ''}
    </div>
    <div class="jobs-redesign-cell jobs-redesign-operation">
      <span class="jobs-redesign-label">${jobsT('jobs.operatingState')}</span>
      <span class="badge ${stateClass}"><span class="badge-dot"></span>${escHtml(stateLabel)}</span>
      ${!jobWorkflowSteps(job).length ? `<span class="jobs-redesign-detail">${escHtml(lastRunText)}</span>` : ''}
      <div id="job-borg-progress-${escHtml(job.key)}">${renderJobOperation(job)}</div>
      ${job.running && job.group_name ? `<span class="jobs-redesign-detail">${escHtml(jobsT('jobGroups.startedBy', { name: job.group_name }))}</span>` : ''}
    </div>
    <div class="jobs-redesign-cell jobs-redesign-policy">
      <span class="jobs-redesign-label">${jobsT('jobs.policy')}</span>
      ${policyHtml || `<span class="jobs-redesign-detail">—</span>`}
      ${verificationHtml}
      ${job.groups?.length ? `<span class="jobs-redesign-detail">${escHtml(jobsT('jobGroups.individualSchedule'))}</span>` : ''}
      ${schedHtml || (job.enabled === false ? `<span class="jobs-redesign-detail">${jobsT('jobs.scheduleDisabled')}</span>` : '')}
      ${window.BBUI.jobGroups?.schedules(job) || ''}
    </div>
    <div class="jobs-redesign-cell jobs-redesign-actions">
      ${actionHtml}
      <div class="job-card-menu">
            <button class="job-menu-btn" data-jobs-action="toggle-menu" data-job-key="${escHtml(job.key)}" title="${jobsT('jobs.options')}" aria-label="${jobsT('jobs.options')}">
              <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
                <circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/>
              </svg>
            </button>
            <div class="job-menu-dropdown hidden" id="job-menu-${escHtml(job.key)}">
              <button class="job-menu-item" data-jobs-action="edit-job" data-job-key="${escHtml(job.key)}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                  <path d="M12 20h9"/>
                  <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>
                </svg>
                ${jobsT('jobs.edit')}
              </button>
              ${job.enabled === false ? '' : `<button class="job-menu-item ${schedActive ? 'sched-active' : ''}" data-jobs-action="show-schedule" data-job-key="${escHtml(job.key)}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                  <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                </svg>
                ${jobsT('jobs.schedule')}${schedActive ? ' <span class="menu-active-dot"></span>' : ''}
              </button>`}
              <button class="job-menu-item" data-jobs-action="toggle-enabled" data-job-key="${escHtml(job.key)}" data-job-enabled="${job.enabled === false ? 'false' : 'true'}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                  ${job.enabled === false
                    ? '<path d="M12 2v20"/><path d="M2 12h20"/>'
                    : '<polyline points="20 6 9 17 4 12"/>'}
                </svg>
                ${job.enabled === false ? jobsT('jobs.enable') : jobsT('jobs.disable')}
              </button>
              <button class="job-menu-item danger" data-jobs-action="delete-job" data-job-key="${escHtml(job.key)}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6l-1 14H6L5 6"/>
                  <path d="M10 11v6"/><path d="M14 11v6"/>
                  <path d="M9 6V4h6v2"/>
                </svg>
                ${jobsT('jobs.deleteJob')}
              </button>
            </div>
          </div>
    </div>
    <div class="job-workflow" id="job-workflow-${escHtml(job.key)}">${renderBorgRun(job)}</div>
  </article>`;
}

function renderJobRestoreVerification(job) {
  const status = String(job.restore_verification_status || '').toLowerCase();
  if (!status) return '';
  const map = {
    verified: { cls: 'success', text: jobsT('jobs.restoreVerified') },
    stale: { cls: 'warning', text: jobsT('jobs.restoreStale') },
    failed: { cls: 'error', text: jobsT('jobs.restoreFailed') },
    never: { cls: 'unknown', text: jobsT('jobs.restoreOpen') },
    not_required: { cls: 'neutral', text: jobsT('jobs.restoreNotRequired') },
  };
  const item = map[status];
  if (!item) return '';
  const details = [
    job.restore_verification_last_test_date ? jobsT('jobs.lastTest', { date: job.restore_verification_last_test_date }) : '',
    job.restore_verification_valid_until ? jobsT('jobs.validUntil', { date: job.restore_verification_valid_until }) : '',
  ].filter(Boolean);
  const detailText = details.join(' · ');
  return `<div class="job-restore-proof"><span class="restore-v-badge ${item.cls}" title="${escHtml(detailText || item.text)}">${item.text}</span>${details.length ? `<span class="jobs-restore-dates">${details.map((detail) => `<span>${escHtml(detail)}</span>`).join('')}</span>` : ''}</div>`;
}

function resolveJobIcon(job) {
  const allowed = new Set([
    'flash', 'appdata', 'photos', 'vms', 'sonstiges',
    'docker', 'folder', 'cloud', 'archive',
    'database', 'server', 'home', 'music', 'video',
    'documents', 'code', 'camera', 'usb', 'shield',
  ]);
  const icon = String(job?.icon || '').trim().toLowerCase();
  if (icon && allowed.has(icon)) return icon;
  return 'archive';
}

function resolveJobIconColor(job) {
  const allowed = new Set([
    'blue', 'indigo', 'purple', 'pink',
    'green', 'lime', 'violet',
    'amber', 'orange',
    'red', 'rose',
    'teal', 'cyan', 'gray', 'theme-blue', 'theme-orange', 'theme-purple', 'theme-green',
  ]);
  const color = String(job?.icon_color || '').trim().toLowerCase();
  return allowed.has(color) ? color : '';
}

function statusLabel(s) {
  return {
    success: 'OK',
    skipped: jobsT('jobs.statusSkipped'),
    warning: jobsT('jobs.statusWarning'),
    cancelled: jobsT('jobs.statusCancelled'),
    error: jobsT('jobs.statusError'),
  }[s] || s;
}

function toggleJobMenu(e, key) {
  e.stopPropagation();
  const menu = document.getElementById(`job-menu-${key}`);
  if (!menu) return;
  const isHidden = menu.classList.contains('hidden');
  closeAllJobMenus();
  if (isHidden) menu.classList.remove('hidden');
}

function closeAllJobMenus() {
  document.querySelectorAll('.job-menu-dropdown').forEach(m => m.classList.add('hidden'));
}

document.addEventListener('click', closeAllJobMenus);

function _showDeleteJobModalForKey(jobKey) {
  const job = jobsState.jobs.find(j => j.key === jobKey);
  if (!job) return;
  showDeleteJobModal(jobKey, job.display_name || job.name || job.key);
}

function onJobsGridClick(event) {
  const btn = event.target.closest('[data-jobs-action]');
  if (!btn) return;

  const action = btn.dataset.jobsAction || '';
  const jobKey = btn.dataset.jobKey || '';

  if (action === 'toggle-workflow') {
    jobWorkflowOpen.has(jobKey) ? jobWorkflowOpen.delete(jobKey) : jobWorkflowOpen.add(jobKey);
    const job = jobsState.jobs.find(item => item.key === jobKey);
    const target = document.getElementById(`job-workflow-${jobKey}`);
    if (job && target) {
      patchJobMarkup(target, renderBorgRun(job));
      target.querySelector?.('[data-jobs-action="toggle-workflow"]')?.focus({preventScroll:true});
    }
    return;
  }
  if (action === 'open-wizard') return openWizard();
  if (action === 'open-log') return openLogPanel(jobKey);
  if (action === 'open-saved-log') {
    const logFile = jobsState.jobs.find(job => job.key === jobKey)?.last_log_file;
    if (logFile) window.BBUI?.components?.logViewer?.open?.(logFile);
    return;
  }
  if (action === 'start-job') return showStartModal(jobKey);
  if (action === 'cancel-job') return showCancelJobModal(jobKey);
  if (action === 'toggle-menu') return toggleJobMenu(event, jobKey);
  if (action === 'edit-job') {
    closeAllJobMenus();
    return openWizardForJob(jobKey, 'edit');
  }
  if (action === 'show-schedule') {
    closeAllJobMenus();
    return showScheduleModal(jobKey);
  }
  if (action === 'toggle-enabled') {
    closeAllJobMenus();
    return setJobEnabled(jobKey, btn.dataset.jobEnabled !== 'true');
  }
  if (action === 'delete-job') {
    closeAllJobMenus();
    return _showDeleteJobModalForKey(jobKey);
  }
}

async function setJobEnabled(jobKey, enabled) {
  try {
    const res = await fetch('/api/jobs/enabled', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_key: jobKey, enabled: !!enabled }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    await refreshJobs();
    showMsg('jobs-message', 'success', jobsT('jobs.toggleSuccess', {
      state: jobsT(enabled ? 'jobs.enabledState' : 'jobs.disabledState'),
      key: jobKey,
    }));
  } catch (err) {
    showJobsError(jobsT('jobs.toggleFailed', { message: err.message }));
  }
}

function showStartModal(jobKey) {
  const canStart = _isDataDirReady();
  if (!canStart) {
    showMsg('jobs-message', 'error', jobsT('jobs.dataDirRequired'));
    return;
  }
  const job = jobsState.jobs.find(j => j.key === jobKey);
  if (!job) return;
  if (job.enabled === false) {
    showMsg('jobs-message', 'warning', jobsT('jobs.disabledWithKey', { key: jobKey }));
    return;
  }

  jobsState.pendingJobKey = jobKey;
  jobsState.confirmAction = 'start';

  const titleName = job.name || job.display_name || 'Backup';
  document.getElementById('modal-title').textContent = jobsT('jobs.startTitle', { name: titleName });
  document.getElementById('modal-description').textContent =
    jobsT('jobs.startDescription', { name: job.display_name || job.key });

  const infoEl = document.getElementById('modal-info');
  const items = [];

  const dockerWarning = jobRuntimeWarningText(job, 'docker');
  if (dockerWarning) {
    items.push(`<div class="modal-info-item warning">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" color="var(--warning)">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <span class="modal-info-text">${dockerWarning}</span>
    </div>`);
  }

  const vmWarning = jobRuntimeWarningText(job, 'vm');
  if (vmWarning) {
    items.push(`<div class="modal-info-item warning">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" color="var(--warning)">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <span class="modal-info-text">${vmWarning}</span>
    </div>`);
  }

  items.push(`<div class="modal-info-item info">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" color="var(--accent)">
      <circle cx="12" cy="12" r="10"/>
      <line x1="12" y1="8" x2="12" y2="12"/>
      <line x1="12" y1="16" x2="12.01" y2="16"/>
    </svg>
    <span class="modal-info-text">${jobsT('jobs.liveLogInfo')}</span>
  </div>`);

  infoEl.innerHTML = items.join('');
  const pwWrap = document.getElementById('modal-passphrase-delete-wrap');
  const pwCb   = document.getElementById('modal-delete-passphrase');
  const pwPath = document.getElementById('modal-delete-passphrase-path');
  const confirmBtn = document.getElementById('modal-confirm-btn');
  if (confirmBtn) {
    confirmBtn.className = 'btn btn-primary';
    confirmBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><polygon points="5 3 19 12 5 21 5 3"/></svg> ${jobsT('jobs.startNow')}`;
    confirmBtn.disabled = false;
  }
  if (pwWrap) pwWrap.classList.add('hidden');
  if (pwCb) pwCb.checked = false;
  if (pwPath) pwPath.textContent = '';
  document.getElementById('confirm-modal').classList.remove('hidden');
  captureConfirmModalCloseSnapshot();
}

function showCancelJobModal(jobKey) {
  const job = jobsState.jobs.find(j => j.key === jobKey);
  if (!job || !job.running || !job.run_id) return;
  jobsState.pendingJobKey = jobKey;
  jobsState.confirmAction = 'cancel';
  const name = job.name || job.display_name || job.key;
  document.getElementById('modal-title').textContent = jobsT('jobs.cancelTitle', { name });
  document.getElementById('modal-description').textContent = jobsT('jobs.cancelDescription');
  document.getElementById('modal-info').innerHTML = `<div class="modal-info-item warning"><span class="modal-info-text">${jobsT('jobs.cancelWarning')}</span></div>`;
  const confirmWrap = document.getElementById('modal-confirm-input-wrap');
  const confirmInput = document.getElementById('modal-confirm-input');
  const passphraseWrap = document.getElementById('modal-passphrase-delete-wrap');
  const passphraseCheckbox = document.getElementById('modal-delete-passphrase');
  if (confirmWrap) confirmWrap.classList.add('hidden');
  if (confirmInput) confirmInput.value = '';
  if (passphraseWrap) passphraseWrap.classList.add('hidden');
  if (passphraseCheckbox) passphraseCheckbox.checked = false;
  const confirmBtn = document.getElementById('modal-confirm-btn');
  confirmBtn.className = 'btn btn-danger';
  confirmBtn.textContent = jobsT('jobs.cancelNow');
  confirmBtn.disabled = false;
  document.getElementById('confirm-modal').classList.remove('hidden');
  captureConfirmModalCloseSnapshot();
}

function closeModal(options = {}) {
  if (!options?.force && scheduleModalHelpers().confirmDiscardIfDirty?.(
    confirmModalHasUnsavedInput(),
    () => closeModal({ force: true })
  ) === false) return false;
  document.getElementById('confirm-modal').classList.add('hidden');
  jobsState.pendingJobKey = null;
  jobsState.pendingDeleteJobKey = null;
  jobsState.confirmAction = 'start';
  jobsState.confirmCloseSnapshot = '';
  const confirmBtn = document.getElementById('modal-confirm-btn');
  if (confirmBtn) {
    confirmBtn.className = 'btn btn-primary';
    confirmBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><polygon points="5 3 19 12 5 21 5 3"/></svg> ${jobsT('jobs.startNow')}`;
    confirmBtn.disabled = false;
  }
  const wrap = document.getElementById('modal-confirm-input-wrap');
  if (wrap) wrap.classList.add('hidden');
  const inp = document.getElementById('modal-confirm-input');
  if (inp) inp.value = '';
  const pwWrap = document.getElementById('modal-passphrase-delete-wrap');
  const pwCb   = document.getElementById('modal-delete-passphrase');
  const pwPath = document.getElementById('modal-delete-passphrase-path');
  if (pwWrap) pwWrap.classList.add('hidden');
  if (pwCb) pwCb.checked = false;
  if (pwPath) pwPath.textContent = '';
}

async function showDeleteJobModal(jobKey, displayName) {
  jobsState.pendingDeleteJobKey = jobKey;
  jobsState.confirmAction = 'delete';
  document.getElementById('modal-title').textContent = jobsT('jobs.deleteTitle');
  document.getElementById('modal-description').textContent =
    jobsT('jobs.deleteDescription', { name: displayName });
  document.getElementById('modal-info').innerHTML = `
    <div class="modal-info-item warning">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" color="var(--warning)">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <span class="modal-info-text">${jobsT('jobs.deleteKeepsRepository')}</span>
    </div>`;
  document.getElementById('modal-info').innerHTML += `
    <label class="form-checkbox-row" style="margin-top:10px">
      <input type="checkbox" id="modal-delete-artifacts">
      ${jobsT('jobs.deleteArtifacts')}
    </label>`;

  const pwWrap = document.getElementById('modal-passphrase-delete-wrap');
  const pwCb   = document.getElementById('modal-delete-passphrase');
  const pwPath = document.getElementById('modal-delete-passphrase-path');
  pwWrap.classList.add('hidden');
  pwCb.checked = false;
  if (jobKey) {
    try {
      const res  = await fetch(`/api/wizard/passphrase-check?job_key=${encodeURIComponent(jobKey)}`);
      const data = await res.json();
      if (data.exists) {
        pwPath.textContent = data.path;
        pwWrap.classList.remove('hidden');
      }
    } catch (_) {}
  }

  const wrap = document.getElementById('modal-confirm-input-wrap');
  const label = document.getElementById('modal-confirm-input-label');
  const inp   = document.getElementById('modal-confirm-input');
  label.textContent = jobsT('jobs.confirmDelete', { key: jobKey });
  inp.value = '';
  inp.dataset.expected = jobKey;
  wrap.classList.remove('hidden');
  setTimeout(() => inp.focus(), 50);

  const confirmBtn = document.getElementById('modal-confirm-btn');
  confirmBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
    <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/>
    <path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/>
  </svg> ${jobsT('jobs.delete')}`;
  confirmBtn.className = 'btn btn-danger';
  confirmBtn.disabled = true;
  document.getElementById('confirm-modal').classList.remove('hidden');
  captureConfirmModalCloseSnapshot();
}

function checkDeleteConfirmInput() {
  if (jobsState.confirmAction !== 'delete') return;
  const inp = document.getElementById('modal-confirm-input');
  const btn = document.getElementById('modal-confirm-btn');
  if (!inp || !btn) return;
  btn.disabled = inp.value.trim() !== inp.dataset.expected;
}

function confirmModalPrimaryAction() {
  if (jobsState.confirmAction === 'delete') return confirmJobDelete();
  if (jobsState.confirmAction === 'cancel') return confirmJobCancel();
  return confirmJobStart();
}

async function confirmJobCancel() {
  const jobKey = jobsState.pendingJobKey;
  const job = jobsState.jobs.find(j => j.key === jobKey);
  if (!job?.run_id) return;
  closeModal({ force: true });
  try {
    const res = await fetch('/api/jobs/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_key: jobKey, run_id: job.run_id }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    showMsg('jobs-message', 'warning', jobsT(data.message_key || 'jobs.cancelRequested'));
    await _pollRunningStates();
  } catch (err) {
    showJobsError(jobsT('jobs.cancelFailed', { message: err.message }));
  }
}

async function confirmJobDelete() {
  const jobKey = jobsState.pendingDeleteJobKey;
  if (!jobKey) return;
  const deletePassphrase = document.getElementById('modal-delete-passphrase').checked;
  const deleteArtifacts = document.getElementById('modal-delete-artifacts')?.checked || false;
  closeModal({ force: true });
  try {
    const res = await fetch('/api/jobs', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_key: jobKey, delete_passphrase: deletePassphrase, delete_artifacts: deleteArtifacts }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    jobsState.loaded = false;
    await refreshJobs();
    const extra = [
      data.deleted_status_files ? jobsT('jobs.statusFiles', { count: data.deleted_status_files }) : '',
      data.deleted_log_files    ? jobsT('jobs.logFiles', { count: data.deleted_log_files }) : '',
      data.deleted_passphrase   ? jobsT('jobs.passphraseFile') : '',
    ].filter(Boolean).join(', ');
    showMsg('jobs-message', 'success',
      jobsT('jobs.deleted', { filename: data.filename, extra: extra ? ` · ${extra}` : '' }));
  } catch (err) {
    showJobsError(jobsT('jobs.deleteFailed', { message: err.message }));
  }
}

async function confirmJobStart() {
  const jobKey = jobsState.pendingJobKey;
  if (!jobKey) return;

  closeModal({ force: true });

  const btn = document.getElementById('modal-confirm-btn');
  if (btn) btn.disabled = true;

  try {
    const res = await fetch('/api/jobs/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_key: jobKey }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));

    await refreshJobs();
  } catch (err) {
    showJobsError(jobsT('jobs.startFailed', { message: err.message }));
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Log-Panel & SSE ───────────────────────────────────────────────────────────

/** Open the themed log; an optional run ID prevents reconnecting to a later run. */
function openLogPanel(jobKey, runId = '') {
  jobsState.activityLog?.close();
  jobsState.activityLog = null;
  const job = jobsState.jobs.find(j => j.key === jobKey);
  jobsState.logRunId = runId || job?.run_id || '';
  const title = jobsT('jobs.logTitle', { name: job ? (job.display_name || job.key) : jobKey });

  document.getElementById('log-panel-title-text').removeAttribute('data-i18n');
  document.getElementById('log-panel-title-text').textContent = title;
  document.getElementById('log-output').textContent = '';
  setLogStatus('running');

  const logPanel = document.getElementById('log-panel');
  if (job) {
    const slotId = `log-slot-${jobsLocationKey(job)}`;
    const slot = document.getElementById(slotId);
    if (slot) slot.appendChild(logPanel);
  }
  logPanel.classList.remove('hidden');

  if (jobsState.activeEventSource) {
    jobsState.activeEventSource.close();
    jobsState.activeEventSource = null;
  }
  if (jobsState.logTransportCheckTimer) {
    clearTimeout(jobsState.logTransportCheckTimer);
    jobsState.logTransportCheckTimer = null;
  }

  if (job?.run_file_activity) {
    jobsState.activityLog = window.BBUI.components.activityLog.create({
      job: jobKey,
      run: jobsState.logRunId,
      output: document.getElementById('log-output'),
      onFollow: follow => { jobsState.logAutoScroll = follow; },
      onStatus: data => {
        if (data.running) return setLogStatus('running');
        if (data.exit_code === null) {
          const badge = document.getElementById('log-status-badge');
          badge.className = 'badge';
          badge.textContent = jobsT('jobs.activityLogEnded');
          return;
        }
        const code = Number(data.exit_code);
        const status = code === 0 ? 'success'
          : (code === 1 && data.phase === 'completed' ? 'warning'
            : (code === 130 ? 'cancelled' : (data.phase === 'skipped' ? 'skipped' : 'error')));
        setLogStatus(status, code);
      },
    });
    return;
  }

  const es = new EventSource(`/api/jobs/log/stream?job=${encodeURIComponent(jobKey)}${jobsState.logRunId ? '&run=' + encodeURIComponent(jobsState.logRunId) : ''}`);
  jobsState.activeEventSource = es;
  jobsState.logAutoScroll = true;

  es.addEventListener('open', () => {
    if (jobsState.activeEventSource !== es) return;
    setLogStatus('running');
    if (jobsState.logTransportCheckTimer) {
      clearTimeout(jobsState.logTransportCheckTimer);
      jobsState.logTransportCheckTimer = null;
    }
  });

  es.onmessage = (e) => {
    if (jobsState.activeEventSource !== es) return;
    setLogStatus('running');
    appendLogLine(e.data);
  };

  es.addEventListener('done', (e) => {
    if (jobsState.activeEventSource !== es) return;
    const code = e.data;
    const numericCode = parseInt(code, 10);
    const state = numericCode === 0
      ? 'success'
      : (numericCode === 130 ? 'cancelled' : (isResourceLockSkipExit(code) ? 'skipped' : 'error'));
    setLogStatus(state, code);
    es.close();
    jobsState.activeEventSource = null;
    if (jobsState.logTransportCheckTimer) {
      clearTimeout(jobsState.logTransportCheckTimer);
      jobsState.logTransportCheckTimer = null;
    }
    setTimeout(refreshJobs, 1500);
  });

  es.addEventListener('error', (e) => {
    if (jobsState.activeEventSource !== es) return;
    if (typeof e.data === 'string' && e.data) {
      appendLogLine(jobsT('jobs.logError', { message: e.data }));
      setLogStatus('error', '?');
      es.close();
      jobsState.activeEventSource = null;
      return;
    }
    handleLogTransportError(es, jobKey);
  });
}

function handleLogTransportError(es, jobKey) {
  if (jobsState.activeEventSource !== es) return;
  if (jobsState.logTransportCheckTimer) {
    return;
  }
  setLogStatus('running');
  jobsState.logTransportCheckTimer = setTimeout(async () => {
    jobsState.logTransportCheckTimer = null;
    if (jobsState.activeEventSource !== es) return;
    try {
      const res = await fetch('/api/jobs/running');
      if (!res.ok) return;
      const running = await res.json();
      const state = running?.[jobKey] || {};
      if (state.running) {
        setLogStatus('running');
        return;
      }
      if (state.exit_code !== undefined && state.exit_code !== null) {
        const code = String(state.exit_code);
        const numericCode = parseInt(code, 10);
        const finalState = numericCode === 0
          ? 'success'
          : (numericCode === 130 ? 'cancelled' : (isResourceLockSkipExit(code) ? 'skipped' : 'error'));
        setLogStatus(finalState, code);
        es.close();
        jobsState.activeEventSource = null;
        setTimeout(refreshJobs, 500);
        return;
      }
      setTimeout(refreshJobs, 500);
    } catch (_) {
      // Keep the running state; a later browser reconnect or manual refresh can resolve it.
    }
  }, 1500);
}

function isResourceLockSkipExit(exitCode) {
  if (parseInt(exitCode, 10) !== 2) return false;
  const el = document.getElementById('log-output');
  const text = el ? String(el.textContent || '') : '';
  return /Job is being skipped: resource locked by/i.test(text);
}

function appendLogLine(line) {
  const el = document.getElementById('log-output');
  if (!el) return;
  el.append(document.createTextNode(`${line}\n`));
  if (jobsState.logAutoScroll) {
    el.scrollTop = el.scrollHeight;
  } else {
    checkScrollHint(el);
  }
}

function checkScrollHint(logEl) {
  if (jobsState.activityLog) return jobsState.activityLog.onScroll();
  const hint = document.getElementById('log-scroll-hint');
  if (!hint) return;
  const atBottom = logEl.scrollHeight - logEl.scrollTop <= logEl.clientHeight + 40;
  hint.classList.toggle('visible', !atBottom);
  jobsState.logAutoScroll = atBottom;
}

function scrollLogToBottom() {
  if (jobsState.activityLog) return jobsState.activityLog.tail();
  const el = document.getElementById('log-output');
  if (el) {
    el.scrollTop = el.scrollHeight;
    jobsState.logAutoScroll = true;
    const hint = document.getElementById('log-scroll-hint');
    if (hint) hint.classList.remove('visible');
  }
}

function setLogStatus(state, exitCode) {
  const badge = document.getElementById('log-status-badge');
  if (!badge) return;
  const exit = String(exitCode ?? '');
  if (state === 'running') {
    badge.className = 'badge';
    badge.textContent = '';
    const dot = document.createElement('span');
    dot.className = 'running-dot';
    dot.style.marginRight = '4px';
    badge.append(dot, document.createTextNode(jobsT('jobs.running')));
  } else if (state === 'success') {
    badge.className = 'badge success';
    badge.textContent = '';
    const dot = document.createElement('span');
    dot.className = 'badge-dot';
    badge.append(dot, document.createTextNode(jobsT('jobs.logDone', { code: exit })));
  } else if (state === 'warning') {
    badge.className = 'badge warning';
    badge.textContent = jobsT('jobs.logWarning', { code: exit });
  } else if (state === 'cancelled') {
    badge.className = 'badge warning';
    badge.textContent = jobsT('jobs.logCancelled', { code: exit });
  } else if (state === 'skipped') {
    badge.className = 'badge skipped';
    badge.textContent = jobsT('jobs.logSkipped', { code: exit });
  } else {
    badge.className = 'badge error';
    badge.textContent = '';
    const dot = document.createElement('span');
    dot.className = 'badge-dot';
    badge.append(dot, document.createTextNode(jobsT('jobs.logFailed', { code: exit })));
  }
}

function clearLog() {
  if (jobsState.activityLog) return jobsState.activityLog.clear();
  const el = document.getElementById('log-output');
  if (el) el.textContent = '';
}

function closeLogPanel() {
  jobsState.logRunId = '';
  jobsState.activityLog?.close();
  jobsState.activityLog = null;
  document.getElementById('log-panel').classList.add('hidden');
  if (jobsState.activeEventSource) {
    jobsState.activeEventSource.close();
    jobsState.activeEventSource = null;
  }
  if (jobsState.logTransportCheckTimer) {
    clearTimeout(jobsState.logTransportCheckTimer);
    jobsState.logTransportCheckTimer = null;
  }
}

// ── Schedule Modal ────────────────────────────────────────────────────────────

function _updateScheduleModalTitle(jobKey, displayName) {
  const titleEl = document.getElementById('schedule-modal-title');
  if (!titleEl) return;
  if (displayName) {
    titleEl.textContent = jobsT('schedule.titleFor', { name: displayName });
  } else {
    const job = jobsState.jobs.find(j => j.key === jobKey);
    if (job) {
      titleEl.textContent = jobsT('schedule.titleFor', {
        name: job.name || job.display_name,
      });
    } else {
      titleEl.textContent = jobsT('schedule.titleFor', { name: jobKey });
    }
  }
}

function showScheduleModal(jobKey, displayName) {
  scheduleModalState.jobKey = jobKey;
  _updateScheduleModalTitle(jobKey, displayName);

  const schedules = _coreSchedules();
  const existing = schedules[jobKey];
  if (existing) {
    document.getElementById('schedule-enabled').checked = existing.enabled !== false;
    const parsed = parseCronToFrequency(existing.cron);
    scheduleModalState.frequency = parsed.freq;
    scheduleModalState.dow = parsed.dow;
    document.getElementById('schedule-hour').value   = parsed.hour;
    document.getElementById('schedule-minute').value = parsed.minute;
    document.getElementById('schedule-dom').value    = parsed.dom;
    document.getElementById('schedule-cron-custom').value = existing.cron;
    document.getElementById('schedule-delete-btn').style.display = '';
  } else {
    document.getElementById('schedule-enabled').checked = true;
    scheduleModalState.frequency = 'daily';
    scheduleModalState.dow = 1;
    document.getElementById('schedule-hour').value   = 3;
    document.getElementById('schedule-minute').value = 0;
    document.getElementById('schedule-dom').value    = 1;
    document.getElementById('schedule-cron-custom').value = '0 3 * * *';
    document.getElementById('schedule-delete-btn').style.display = 'none';
  }

  _applyFrequencyUI(scheduleModalState.frequency);
  updateSchedulePreview();
  document.getElementById('schedule-modal').classList.remove('hidden');
  scheduleCaptureCloseSnapshot();
}

function closeScheduleModal(options = {}) {
  if (!options?.force && scheduleModalHelpers().confirmDiscardIfDirty?.(
    scheduleHasUnsavedChanges(),
    () => closeScheduleModal({ force: true })
  ) === false) return false;
  document.getElementById('schedule-modal').classList.add('hidden');
  scheduleModalState.jobKey = null;
  scheduleModalState.closeSnapshot = '';
  return true;
}

/** Select a frequency mode and immediately refresh its cron preview. */
function setFrequency(freq) {
  scheduleModalState.frequency = freq;
  _applyFrequencyUI(freq);
  updateSchedulePreview();
}

function _applyFrequencyUI(freq) {
  document.querySelectorAll('.freq-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.freq === freq);
  });
  document.getElementById('schedule-time-row').classList.toggle('hidden', freq === 'custom');
  document.getElementById('schedule-dow-row').classList.toggle('hidden', freq !== 'weekly');
  document.getElementById('schedule-dom-row').classList.toggle('hidden', freq !== 'monthly');
  document.getElementById('schedule-custom-row').classList.toggle('hidden', freq !== 'custom');
}

function selectDow(dow) {
  scheduleModalState.dow = dow;
  document.querySelectorAll('.dow-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.dow) === dow);
  });
  updateSchedulePreview();
}

function buildCronExpression() {
  const freq   = scheduleModalState.frequency;
  const hour   = parseInt(document.getElementById('schedule-hour').value)   || 0;
  const minute = parseInt(document.getElementById('schedule-minute').value) || 0;
  const dom    = parseInt(document.getElementById('schedule-dom').value)    || 1;
  const dow    = scheduleModalState.dow;

  const h = Math.min(23, Math.max(0, hour));
  const m = Math.min(59, Math.max(0, minute));
  const d = Math.min(28, Math.max(1, dom));

  if (freq === 'daily')   return `${m} ${h} * * *`;
  if (freq === 'weekly')  return `${m} ${h} * * ${dow}`;
  if (freq === 'monthly') return `${m} ${h} ${d} * *`;
  return document.getElementById('schedule-cron-custom').value.trim();
}

function updateSchedulePreview() {
  const cron = buildCronExpression();
  const next = calcNextRun(cron);
  const el   = document.getElementById('schedule-next-run-text');
  if (!el) return;
  if (next) {
    el.textContent = jobsT('schedule.nextRun', { date: fmtDateShort(next) });
  } else {
    el.textContent = cron ? jobsT('schedule.invalid') : '—';
  }
}

async function saveScheduleAction() {
  const jobKey = scheduleModalState.jobKey;
  if (!jobKey) return;

  const cron    = buildCronExpression();
  const enabled = document.getElementById('schedule-enabled').checked;

  try {
    const res = await fetch('/api/schedules', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_key: jobKey, cron, enabled }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const schedules = _coreSchedules();
    schedules[jobKey] = { cron, enabled };
    _coreSetSchedules(schedules);
    closeScheduleModal({ force: true });
    _onScheduleChanged(jobKey);
  } catch (err) {
    if (window.BBUI?.components?.toast?.error) {
      window.BBUI.components.toast.error('jobs-message', jobsT('schedule.saveError', { message: err.message }));
    } else {
      alert(jobsT('schedule.saveError', { message: err.message }));
    }
  }
}

async function deleteScheduleAction() {
  const jobKey = scheduleModalState.jobKey;
  if (!jobKey) return;

  try {
    const res = await fetch('/api/schedules', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_key: jobKey }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
    const schedules = _coreSchedules();
    delete schedules[jobKey];
    _coreSetSchedules(schedules);
    closeScheduleModal({ force: true });
    _onScheduleChanged(jobKey);
  } catch (err) {
    if (window.BBUI?.components?.toast?.error) {
      window.BBUI.components.toast.error('jobs-message', jobsT('schedule.deleteError', { message: err.message }));
    } else {
      alert(jobsT('schedule.deleteError', { message: err.message }));
    }
  }
}

function _onScheduleChanged(jobKey) {
  if (jobKey === 'restore_test') {
    _updateRTScheduleBtn();
  } else {
    renderJobsGrid(jobsState.jobs);
  }
}

// ── Cron utilities ────────────────────────────────────────────────────────────

/** Parse lossless daily/weekly/monthly presets; retain all other cron text as custom.
 * Returns editor fields without narrowing lists, ranges, steps or wildcards.
 */
function parseCronToFrequency(cron) {
  const parts = (cron || '').trim().split(/\s+/);
  const result = { freq: 'custom', hour: 3, minute: 0, dom: 1, dow: 1 };
  if (parts.length !== 5) return result;
  const [minF, hrF, domF, monF, dowF] = parts;
  const integer = (field, lo, hi) => /^(0|[1-9]\d*)$/.test(field) && Number(field) >= lo && Number(field) <= hi;
  if (!integer(minF, 0, 59) || !integer(hrF, 0, 23) || monF !== '*') return result;
  result.hour = Number(hrF);
  result.minute = Number(minF);
  if (domF === '*' && dowF === '*') {
    result.freq = 'daily';
  } else if (domF === '*' && integer(dowF, 0, 6)) {
    result.freq = 'weekly';
    result.dow = Number(dowF);
  } else if (dowF === '*' && integer(domF, 1, 28)) {
    result.freq = 'monthly';
    result.dom = Number(domF);
  }
  return result;
}

function calcNextRun(cron) {
  if (!cron) return null;
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;

  function parseField(f, lo, hi) {
    if (f === '*') return Array.from({length: hi - lo + 1}, (_, i) => i + lo);
    const result = new Set();
    for (const part of f.split(',')) {
      if (part.includes('/')) {
        const [range, step] = part.split('/');
        const s = parseInt(step);
        const start = range === '*' ? lo : parseInt(range.split('-')[0]);
        for (let i = start; i <= hi; i += s) result.add(i);
      } else if (part.includes('-')) {
        const [a, b] = part.split('-').map(Number);
        for (let i = a; i <= b; i++) result.add(i);
      } else {
        const n = parseInt(part);
        if (!isNaN(n)) result.add(n);
      }
    }
    return [...result].sort((a, b) => a - b);
  }

  const [minF, hrF, domF, monF, dowF] = parts;
  const mins   = parseField(minF, 0, 59);
  const hours  = parseField(hrF,  0, 23);
  const months = parseField(monF, 1, 12);
  const doms   = parseField(domF, 1, 31);
  const dows   = new Set(parseField(dowF, 0, 6).map(d => d % 7));

  const t = new Date();
  t.setSeconds(0, 0);
  t.setMinutes(t.getMinutes() + 1);

  for (let i = 0; i < 527041; i++) {
    if (months.includes(t.getMonth() + 1) &&
        doms.includes(t.getDate()) &&
        dows.has(t.getDay()) &&
        hours.includes(t.getHours()) &&
        mins.includes(t.getMinutes())) {
      return new Date(t);
    }
    t.setMinutes(t.getMinutes() + 1);
  }
  return null;
}

function fmtDateShort(d) {
  if (!d) return '—';
  const language = window.BBUI?.components?.i18n?.getLanguage?.() || 'de';
  return new Intl.DateTimeFormat(language === 'en' ? 'en-GB' : 'de-DE', {
    weekday: 'short',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(d);
}

window.addEventListener?.('bbui:language-changed', () => {
  if (jobsState.loaded) renderJobsGrid(jobsState.jobs);
  if (scheduleModalState.jobKey) {
    _updateScheduleModalTitle(scheduleModalState.jobKey);
    updateSchedulePreview();
  }
});

// ── Jobs-Meldungen ────────────────────────────────────────────────────────────

function showJobsError(msg) {
  showMsg('jobs-message', 'error', msg);
}

function showJobsEmpty(html) {
  const el = document.getElementById('jobs-message');
  if (!el) return;
  el.className = 'status-message empty-state';
  el.innerHTML = html;
}

function hideJobsMessage() {
  hideEl('jobs-message');
}
