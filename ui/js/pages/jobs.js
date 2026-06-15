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
  logAutoScroll: true,
  pollingTimer: null,
  lastRunningSnapshot: '{}',  // JSON-String der zuletzt bekannten Running-States
};
const jobsState = window.BBUI.jobsState;

window.BBUI.scheduleModalState = window.BBUI.scheduleModalState || {
  jobKey: null,
  frequency: 'daily', // 'daily' | 'weekly' | 'monthly' | 'custom'
  dow: 1,             // 0=So..6=Sa
};
const scheduleModalState = window.BBUI.scheduleModalState;

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

// ── Jobs laden ────────────────────────────────────────────────────────────────

async function refreshJobs() {
  const btn = document.getElementById('jobs-refresh-btn');
  if (btn) btn.classList.add('loading');
  hideJobsMessage();

  try {
    await window.BBUI.core.updateDataDirWarning();
    const [jobsRes, statusRes, schedRes] = await Promise.all([
      fetch('/api/jobs'),
      fetch('/api/status'),
      fetch('/api/schedules'),
    ]);
    if (!jobsRes.ok) throw new Error(`Jobs: HTTP ${jobsRes.status}`);
    if (!statusRes.ok) throw new Error(`Status: HTTP ${statusRes.status}`);

    const jobsData   = await jobsRes.json();
    const statusData = await statusRes.json();
    if (schedRes.ok) {
      const nextSchedules = await schedRes.json();
      _coreSetSchedules(nextSchedules);
    }

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
      } : {},
    }));

    jobsState.loaded = true;
    renderJobsGrid(jobsState.jobs);
  } catch (err) {
    showJobsError(`Fehler beim Laden: ${err.message}`);
  } finally {
    if (btn) btn.classList.remove('loading');
  }
}

// ── Jobs-Polling (erkennt Cron-gestartete Jobs) ─────────────────────────────

function startJobsPolling() {
  if (jobsState.pollingTimer) return;
  jobsState.pollingTimer = setInterval(_pollRunningStates, 10_000);
}

function stopJobsPolling() {
  if (jobsState.pollingTimer) {
    clearInterval(jobsState.pollingTimer);
    jobsState.pollingTimer = null;
  }
}

async function _pollRunningStates() {
  const coreState = _coreState();
  if (coreState.currentPage !== 'jobs') return;
  try {
    const res = await fetch('/api/jobs/running');
    if (!res.ok) return;
    const running = await res.json();
    const snapshot = JSON.stringify(running);
    if (snapshot === jobsState.lastRunningSnapshot) return;
    jobsState.lastRunningSnapshot = snapshot;

    jobsState.jobs = jobsState.jobs.map(j => ({
      ...j,
      running: running[j.key]?.running ?? false,
    }));
    renderJobsGrid(jobsState.jobs);

    const anyJustFinished = jobsState.jobs.some(
      j => !j.running && running[j.key] && running[j.key].exit_code !== null
    );
    if (anyJustFinished) {
      setTimeout(refreshJobs, 1500);
    }
  } catch {
    // Netzwerkfehler ignorieren
  }
}

// ── Jobs rendern ──────────────────────────────────────────────────────────────

function renderJobsGrid(jobs) {
  const el = document.getElementById('jobs-grid');
  if (!el) return;
  const jobsNewBtn = document.getElementById('jobs-new-btn');

  const logOutput = document.getElementById('log-output');
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
    el.innerHTML = '';
    showJobsEmpty('Noch keine Backup-Jobs vorhanden.<br><button class="btn btn-primary btn-sm" id="jobs-empty-create-btn" data-jobs-action="open-wizard" style="margin-top:10px">Ersten Job erstellen</button>');
    // Defensive fallback: keep direct binding in case delegated handlers are unavailable.
    document.getElementById('jobs-empty-create-btn')?.addEventListener('click', openWizard);
    return;
  }
  if (jobsNewBtn) jobsNewBtn.classList.remove('hidden');

  const typeOrder = { flash: 0, appdata: 1, photos: 2, VMs: 3, vms: 3, sonstiges: 4 };
  const locOrder  = ['local', 'usb', 'smb', 'storagebox'];

  const backupJobs = jobs.filter(j => !j.is_utility);
  const utilityJobs = jobs.filter(j => j.is_utility);

  const groups = {};
  for (const loc of locOrder) groups[loc] = [];
  for (const job of backupJobs) {
    const loc = job.location in groups ? job.location : 'local';
    groups[loc].push(job);
  }
  for (const loc of locOrder) {
    groups[loc].sort((a, b) => (typeOrder[a.backup_type] ?? 99) - (typeOrder[b.backup_type] ?? 99));
  }

  let html = locOrder
    .filter(loc => groups[loc].length > 0)
    .map(loc => `
      <div class="jobs-location-group">
        <div class="jobs-location-header">${locLabel(loc)}</div>
        <div class="jobs-group-grid">${groups[loc].map(renderJobCard).join('')}</div>
        <div class="group-log-slot" id="log-slot-${loc}"></div>
      </div>`)
    .join('');

  if (utilityJobs.length > 0) {
    html += `
      <div class="jobs-location-group">
        <div class="jobs-location-header">Weitere Skripte</div>
        <div class="jobs-group-grid">${utilityJobs.map(renderJobCard).join('')}</div>
        <div class="group-log-slot" id="log-slot-utility"></div>
      </div>`;
  }

  el.innerHTML = html;

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
    checkScrollHint(logOutput);
  }
}

function renderJobCard(job) {
  const isRunning = job.running;
  const locClass  = (job.location || '').toLowerCase();
  const titleName = job.name || job.display_name || capitalize(job.backup_type);
  const iconKey = resolveJobIcon(job);
  const iconColorKey = resolveJobIconColor(job);
  const iconColorClass = iconColorKey ? ` type-icon-color-${iconColorKey}` : '';

  const locLabel = {
    local: 'Local', usb: 'USB', smb: 'SMB', storagebox: 'Storagebox',
  }[job.location] || job.location;

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
  const policyHtml = (job.compression || retention.length === 4)
    ? `<div class="job-policy">
         ${job.compression ? `<span>Comp: <code>${escHtml(job.compression)}</code></span>` : ''}
         ${retention.length === 4 ? `<span>Ret: <code>${escHtml(retention.join('/'))}</code></span>` : ''}
       </div>`
    : '';
  const schedHtml = (job.enabled === false) ? '' : (sched
    ? `<div class="job-schedule-info ${schedActive ? '' : 'disabled'}">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12">
           <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
         </svg>
         ${schedActive
           ? (nextRun ? `Nächster Lauf: ${fmtDateShort(nextRun)}` : sched.cron)
           : 'Zeitplan deaktiviert'}
       </div>`
    : '');

  const lastRunHtml = job.last_status
    ? `<div class="job-last-run">
         Letzter Lauf: <span>${job.last_time_ago || '—'}</span>
         <span class="badge ${job.last_status}" style="margin-left:6px;vertical-align:middle">
           <span class="badge-dot"></span>${statusLabel(job.last_status)}
         </span>
       </div>`
    : `<div class="job-last-run">Noch kein Backup durchgeführt</div>`;
  const verificationHtml = renderJobRestoreVerification(job);

  const startDisabled = !_isDataDirReady();
  const effectiveStartDisabled = startDisabled || job.enabled === false;
  const actionHtml = isRunning
    ? `<div class="running-indicator">
         <span class="running-dot"></span>
         Läuft...
         <button class="btn btn-secondary btn-sm" data-jobs-action="open-log" data-job-key="${escHtml(job.key)}">Log anzeigen</button>
       </div>`
    : `<button class="btn btn-primary" data-jobs-action="start-job" data-job-key="${escHtml(job.key)}" ${effectiveStartDisabled ? `disabled title="${job.enabled === false ? 'Job ist deaktiviert.' : 'Bitte zuerst GLOBAL_DATA_DIR in Einstellungen setzen.'}"` : ''}>
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
           <polygon points="5 3 19 12 5 21 5 3"/>
         </svg>
         Starten
       </button>`;

  return `
    <div class="job-card ${isRunning ? 'running' : ''}" id="job-card-${job.key}">
      <div class="job-card-header">
        <div class="job-card-title">
          <div class="type-icon type-icon-${(job.backup_type||'sonstiges').toLowerCase()}${iconColorClass}">${typeIcon(iconKey)}</div>
          <div>
            <div class="type-name">${escHtml(titleName)}</div>
          </div>
        </div>
        <div class="job-card-badges">
          <span class="loc-badge ${locClass}">${locLabel}</span>
          <div class="job-card-menu">
            <button class="job-menu-btn" data-jobs-action="toggle-menu" data-job-key="${escHtml(job.key)}" title="Optionen">
              <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
                <circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/>
              </svg>
            </button>
            <div class="job-menu-dropdown hidden" id="job-menu-${job.key}">
              ${job.standard === 'legacy'
                ? `<button class="job-menu-item" data-jobs-action="adopt-legacy" data-job-key="${escHtml(job.key)}">
                     <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                       <polyline points="20 6 9 17 4 12"></polyline>
                     </svg>
                     In Wizard übernehmen
                   </button>`
                : `<button class="job-menu-item" data-jobs-action="edit-job" data-job-key="${escHtml(job.key)}">
                     <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                       <path d="M12 20h9"/>
                       <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>
                     </svg>
                     Job bearbeiten
                   </button>`
              }
              ${job.enabled === false ? '' : `<button class="job-menu-item ${schedActive ? 'sched-active' : ''}" data-jobs-action="show-schedule" data-job-key="${escHtml(job.key)}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                  <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                </svg>
                Zeitplan${schedActive ? ' <span class="menu-active-dot"></span>' : ''}
              </button>`}
              <button class="job-menu-item" data-jobs-action="toggle-enabled" data-job-key="${escHtml(job.key)}" data-job-enabled="${job.enabled === false ? 'false' : 'true'}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                  ${job.enabled === false
                    ? '<path d="M12 2v20"/><path d="M2 12h20"/>'
                    : '<polyline points="20 6 9 17 4 12"/>'}
                </svg>
                ${job.enabled === false ? 'Job aktivieren' : 'Job deaktivieren'}
              </button>
              <button class="job-menu-item danger" data-jobs-action="delete-job" data-job-key="${escHtml(job.key)}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6l-1 14H6L5 6"/>
                  <path d="M10 11v6"/><path d="M14 11v6"/>
                  <path d="M9 6V4h6v2"/>
                </svg>
                Job löschen
              </button>
            </div>
          </div>
        </div>
      </div>
      <div class="job-meta">${features.join('')}</div>
      ${job.enabled === false ? `<div class="status-message warning-state job-disabled-note">Job ist deaktiviert.</div>` : ''}
      ${job.description ? `<div class="job-description">${renderDescriptionMarkdown(job.description)}</div>` : ''}
      <div class="job-last-run-wrap">${policyHtml}${lastRunHtml}${verificationHtml}${schedHtml}</div>
      <div class="job-actions">${actionHtml}</div>
    </div>`;
}

function renderJobRestoreVerification(job) {
  const status = String(job.restore_verification_status || '').toLowerCase();
  if (!status) return '';
  const map = {
    verified: { cls: 'success', text: 'Restore: verifiziert' },
    stale: { cls: 'warning', text: 'Restore: überfällig' },
    failed: { cls: 'error', text: 'Restore: fehlgeschlagen' },
    never: { cls: 'unknown', text: 'Restore: offen' },
    not_required: { cls: 'neutral', text: 'Restore: nicht geplant' },
  };
  const item = map[status];
  if (!item) return '';
  const detail = [
    job.restore_verification_last_test_date ? `Letzter Test: ${job.restore_verification_last_test_date}` : '',
    job.restore_verification_valid_until ? `Gültig bis: ${job.restore_verification_valid_until}` : '',
  ].filter(Boolean).join(' · ');
  return `<div class="job-restore-proof"><span class="restore-v-badge ${item.cls}" title="${escHtml(detail || item.text)}">${item.text}</span></div>`;
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
  return String(job?.backup_type || 'sonstiges').trim().toLowerCase() || 'sonstiges';
}

function resolveJobIconColor(job) {
  const allowed = new Set([
    'blue', 'indigo', 'purple', 'pink',
    'green', 'lime', 'violet',
    'amber', 'orange',
    'red', 'rose',
    'teal', 'cyan', 'gray',
  ]);
  const color = String(job?.icon_color || '').trim().toLowerCase();
  return allowed.has(color) ? color : '';
}

function statusLabel(s) {
  return { success: 'OK', skipped: 'Übersprungen', warning: 'Warnung', error: 'Fehler' }[s] || s;
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
  showDeleteJobModal(jobKey, job.display_name || job.name || job.key, job.backup_type || '', job.location || '');
}

function onJobsGridClick(event) {
  const btn = event.target.closest('[data-jobs-action]');
  if (!btn) return;

  const action = btn.dataset.jobsAction || '';
  const jobKey = btn.dataset.jobKey || '';

  if (action === 'open-wizard') return openWizard();
  if (action === 'open-log') return openLogPanel(jobKey);
  if (action === 'start-job') return showStartModal(jobKey);
  if (action === 'toggle-menu') return toggleJobMenu(event, jobKey);
  if (action === 'adopt-legacy') {
    closeAllJobMenus();
    return adoptLegacyJob(jobKey);
  }
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
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    await refreshJobs();
    showMsg('jobs-message', 'success', `Job ${enabled ? 'aktiviert' : 'deaktiviert'}: ${jobKey}`);
  } catch (err) {
    showJobsError(`Umschalten fehlgeschlagen: ${err.message}`);
  }
}

function showStartModal(jobKey) {
  const canStart = _isDataDirReady();
  if (!canStart) {
    showMsg('jobs-message', 'error', 'Bitte zuerst GLOBAL_DATA_DIR in Einstellungen setzen.');
    return;
  }
  const job = jobsState.jobs.find(j => j.key === jobKey);
  if (!job) return;
  if (job.enabled === false) {
    showMsg('jobs-message', 'warning', `Job ist deaktiviert: ${jobKey}`);
    return;
  }

  jobsState.pendingJobKey = jobKey;
  jobsState.confirmAction = 'start';

  const titleName = job.name || job.display_name || capitalize(job.backup_type);
  document.getElementById('modal-title').textContent = `Job starten: ${titleName}`;
  document.getElementById('modal-description').textContent =
    `Das Backup "${job.display_name || job.key}" wird jetzt gestartet.`;

  const infoEl = document.getElementById('modal-info');
  const items = [];

  if (job.has_docker) {
    items.push(`<div class="modal-info-item warning">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" color="var(--warning)">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <span class="modal-info-text">Alle Docker-Container werden <strong>gestoppt</strong> und nach dem Backup wieder gestartet.</span>
    </div>`);
  }

  if (job.has_vm) {
    items.push(`<div class="modal-info-item warning">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" color="var(--warning)">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <span class="modal-info-text">Laufende <strong>VMs werden heruntergefahren</strong> und nach dem Backup neu gestartet.</span>
    </div>`);
  }

  items.push(`<div class="modal-info-item info">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" color="var(--accent)">
      <circle cx="12" cy="12" r="10"/>
      <line x1="12" y1="8" x2="12" y2="12"/>
      <line x1="12" y1="16" x2="12.01" y2="16"/>
    </svg>
    <span class="modal-info-text">Die Log-Ausgabe wird live im Browser angezeigt.</span>
  </div>`);

  infoEl.innerHTML = items.join('');
  const pwWrap = document.getElementById('modal-passphrase-delete-wrap');
  const pwCb   = document.getElementById('modal-delete-passphrase');
  const pwPath = document.getElementById('modal-delete-passphrase-path');
  const confirmBtn = document.getElementById('modal-confirm-btn');
  if (confirmBtn) {
    confirmBtn.className = 'btn btn-primary';
    confirmBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><polygon points="5 3 19 12 5 21 5 3"/></svg> Jetzt starten`;
    confirmBtn.disabled = false;
  }
  if (pwWrap) pwWrap.classList.add('hidden');
  if (pwCb) pwCb.checked = false;
  if (pwPath) pwPath.textContent = '';
  document.getElementById('confirm-modal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('confirm-modal').classList.add('hidden');
  jobsState.pendingJobKey = null;
  jobsState.pendingDeleteJobKey = null;
  jobsState.confirmAction = 'start';
  const confirmBtn = document.getElementById('modal-confirm-btn');
  if (confirmBtn) {
    confirmBtn.className = 'btn btn-primary';
    confirmBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><polygon points="5 3 19 12 5 21 5 3"/></svg> Jetzt starten`;
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

async function showDeleteJobModal(jobKey, displayName, typeId, location) {
  jobsState.pendingDeleteJobKey = jobKey;
  jobsState.confirmAction = 'delete';
  document.getElementById('modal-title').textContent = 'Job-Skript löschen';
  document.getElementById('modal-description').textContent =
    `Soll der Job „${displayName}" wirklich gelöscht werden? Diese Aktion kann nicht rückgängig gemacht werden.`;
  document.getElementById('modal-info').innerHTML = `
    <div class="modal-info-item warning">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" color="var(--warning)">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <span class="modal-info-text">Der Job wird aus der UI entfernt. Repository-Daten bleiben erhalten.</span>
    </div>`;
  document.getElementById('modal-info').innerHTML += `
    <label class="form-checkbox-row" style="margin-top:10px">
      <input type="checkbox" id="modal-delete-artifacts">
      Zusatzdateien ebenfalls löschen (Status, Logs, Restore-Test)
    </label>`;

  const pwWrap = document.getElementById('modal-passphrase-delete-wrap');
  const pwCb   = document.getElementById('modal-delete-passphrase');
  const pwPath = document.getElementById('modal-delete-passphrase-path');
  pwWrap.classList.add('hidden');
  pwCb.checked = false;
  if (typeId) {
    try {
      const res  = await fetch(`/api/wizard/passphrase-check?type_id=${encodeURIComponent(typeId)}&location=${encodeURIComponent(location || '')}`);
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
  label.textContent = `Zur Bestätigung „${jobKey}" eingeben:`;
  inp.value = '';
  inp.dataset.expected = jobKey;
  wrap.classList.remove('hidden');
  setTimeout(() => inp.focus(), 50);

  const confirmBtn = document.getElementById('modal-confirm-btn');
  confirmBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
    <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/>
    <path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/>
  </svg> Löschen`;
  confirmBtn.className = 'btn btn-danger';
  confirmBtn.disabled = true;
  document.getElementById('confirm-modal').classList.remove('hidden');
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
  return confirmJobStart();
}

async function confirmJobDelete() {
  const jobKey = jobsState.pendingDeleteJobKey;
  if (!jobKey) return;
  const deletePassphrase = document.getElementById('modal-delete-passphrase').checked;
  const deleteArtifacts = document.getElementById('modal-delete-artifacts')?.checked || false;
  closeModal();
  try {
    const res = await fetch('/api/jobs', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_key: jobKey, delete_passphrase: deletePassphrase, delete_artifacts: deleteArtifacts }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    jobsState.loaded = false;
    await refreshJobs();
    const extra = [
      data.deleted_status_files ? `${data.deleted_status_files} Status-Datei(en)` : '',
      data.deleted_log_files    ? `${data.deleted_log_files} Log-Datei(en)` : '',
      data.deleted_passphrase   ? 'Passphrase-Datei' : '',
    ].filter(Boolean).join(', ');
    showMsg('jobs-message', 'success',
      `Gelöscht: ${data.filename}${extra ? ' · ' + extra : ''}`);
  } catch (err) {
    showJobsError(`Löschen fehlgeschlagen: ${err.message}`);
  }
}

async function confirmJobStart() {
  const jobKey = jobsState.pendingJobKey;
  if (!jobKey) return;

  closeModal();

  const btn = document.getElementById('modal-confirm-btn');
  if (btn) btn.disabled = true;

  try {
    const res = await fetch('/api/jobs/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_key: jobKey }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

    await refreshJobs();
    openLogPanel(jobKey);
  } catch (err) {
    showJobsError(`Start fehlgeschlagen: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Log-Panel & SSE ───────────────────────────────────────────────────────────

function openLogPanel(jobKey) {
  const job = jobsState.jobs.find(j => j.key === jobKey);
  const title = job ? `Log: ${job.display_name || job.key}` : `Log: ${jobKey}`;

  document.getElementById('log-panel-title-text').textContent = title;
  document.getElementById('log-output').textContent = '';
  setLogStatus('running');

  const logPanel = document.getElementById('log-panel');
  if (job) {
    const slotId = job.is_utility ? 'log-slot-utility' : `log-slot-${job.location}`;
    const slot = document.getElementById(slotId);
    if (slot) slot.appendChild(logPanel);
  }
  logPanel.classList.remove('hidden');

  if (jobsState.activeEventSource) {
    jobsState.activeEventSource.close();
  }

  const es = new EventSource(`/api/jobs/log/stream?job=${encodeURIComponent(jobKey)}`);
  jobsState.activeEventSource = es;
  jobsState.logAutoScroll = true;

  es.onmessage = (e) => {
    appendLogLine(e.data);
  };

  es.addEventListener('done', (e) => {
    const code = e.data;
    setLogStatus(parseInt(code, 10) === 0 ? 'success' : 'error', code);
    es.close();
    jobsState.activeEventSource = null;
    setTimeout(refreshJobs, 1500);
  });

  es.addEventListener('error', (e) => {
    if (e.data) appendLogLine(`[Fehler] ${e.data}`);
    setLogStatus('error', '?');
    es.close();
    jobsState.activeEventSource = null;
  });

  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      // Verbindung wurde geschlossen – normal nach 'done'
    }
  };
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
  const hint = document.getElementById('log-scroll-hint');
  if (!hint) return;
  const atBottom = logEl.scrollHeight - logEl.scrollTop <= logEl.clientHeight + 40;
  hint.classList.toggle('visible', !atBottom);
  jobsState.logAutoScroll = atBottom;
}

function scrollLogToBottom() {
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

function clearLog() {
  const el = document.getElementById('log-output');
  if (el) el.textContent = '';
}

function closeLogPanel() {
  document.getElementById('log-panel').classList.add('hidden');
  if (jobsState.activeEventSource) {
    jobsState.activeEventSource.close();
    jobsState.activeEventSource = null;
  }
}

// ── Schedule Modal ────────────────────────────────────────────────────────────

function showScheduleModal(jobKey, displayName) {
  scheduleModalState.jobKey = jobKey;

  if (displayName) {
    document.getElementById('schedule-modal-title').textContent = `Zeitplan: ${displayName}`;
  } else {
    const job = jobsState.jobs.find(j => j.key === jobKey);
    if (job) {
      document.getElementById('schedule-modal-title').textContent =
        `Zeitplan: ${capitalize(job.backup_type)} (${job.location})`;
    } else {
      document.getElementById('schedule-modal-title').textContent = `Zeitplan: ${jobKey}`;
    }
  }

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
}

function closeScheduleModal() {
  document.getElementById('schedule-modal').classList.add('hidden');
  scheduleModalState.jobKey = null;
}

function setFrequency(freq) {
  scheduleModalState.frequency = freq;
  _applyFrequencyUI(freq);
  if (freq !== 'custom') updateSchedulePreview();
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
    el.textContent = `Nächster Lauf: ${fmtDateShort(next)}`;
  } else {
    el.textContent = cron ? 'Ungültiger Ausdruck' : '—';
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
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    const schedules = _coreSchedules();
    schedules[jobKey] = { cron, enabled };
    _coreSetSchedules(schedules);
    closeScheduleModal();
    _onScheduleChanged(jobKey);
  } catch (err) {
    if (window.BBUI?.components?.toast?.error) {
      window.BBUI.components.toast.error('jobs-message', `Fehler beim Speichern: ${err.message}`);
    } else {
      alert(`Fehler beim Speichern: ${err.message}`);
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
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    const schedules = _coreSchedules();
    delete schedules[jobKey];
    _coreSetSchedules(schedules);
    closeScheduleModal();
    _onScheduleChanged(jobKey);
  } catch (err) {
    if (window.BBUI?.components?.toast?.error) {
      window.BBUI.components.toast.error('jobs-message', `Fehler beim Löschen: ${err.message}`);
    } else {
      alert(`Fehler beim Löschen: ${err.message}`);
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

function parseCronToFrequency(cron) {
  const parts = (cron || '').trim().split(/\s+/);
  const result = { freq: 'custom', hour: 3, minute: 0, dom: 1, dow: 1 };
  if (parts.length !== 5) return result;

  const [minF, hrF, domF, monF, dowF] = parts;
  const hour   = hrF  === '*' ? 3 : parseInt(hrF)  || 0;
  const minute = minF === '*' ? 0 : parseInt(minF) || 0;
  const dom    = domF === '*' ? 1 : parseInt(domF) || 1;
  const dow    = dowF === '*' ? 1 : parseInt(dowF) || 1;

  result.hour   = hour;
  result.minute = minute;
  result.dom    = dom;
  result.dow    = dow;

  if (domF === '*' && monF === '*' && dowF === '*') {
    result.freq = 'daily';
  } else if (domF === '*' && monF === '*' && hrF !== '*' && minF !== '*') {
    result.freq = 'weekly';
  } else if (dowF === '*' && monF === '*' && domF !== '*') {
    result.freq = 'monthly';
  } else {
    result.freq = 'custom';
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
  const pad = n => String(n).padStart(2, '0');
  const days = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
  return `${days[d.getDay()]}, ${pad(d.getDate())}.${pad(d.getMonth()+1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ── Jobs-Meldungen ────────────────────────────────────────────────────────────

function showJobsError(msg) {
  const el = document.getElementById('jobs-message');
  if (!el) return;
  el.className = 'status-message error-state';
  el.textContent = msg;
}

function showJobsEmpty(html) {
  const el = document.getElementById('jobs-message');
  if (!el) return;
  el.className = 'status-message empty-state';
  el.innerHTML = html;
}

function hideJobsMessage() {
  const el = document.getElementById('jobs-message');
  if (el) el.className = 'status-message hidden';
}
