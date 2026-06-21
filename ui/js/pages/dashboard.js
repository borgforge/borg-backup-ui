'use strict';

// ══════════════════════════════════════════════════════════════════════════════
// DASHBOARD PAGE
// ══════════════════════════════════════════════════════════════════════════════

function dashboardT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(key, params) || key;
}

function dashboardLocationLabel(location) {
  return {
    local: dashboardT('jobs.locationLocal'),
    usb: dashboardT('jobs.locationUsb'),
    smb: dashboardT('jobs.locationSmb'),
    storagebox: dashboardT('jobs.locationStoragebox'),
  }[location] || location || '—';
}

let dashboardSystemHealth = null;
let dashboardSelectedLocation = 'all';
const DASHBOARD_LOCATION_ORDER = ['storagebox', 'usb', 'smb', 'local'];

async function fetchStatus() {
  const res = await fetch('/api/status');
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  return res.json();
}

async function fetchJobsList() {
  const res = await fetch('/api/jobs');
  if (!res.ok) return { jobs: [] };
  return res.json();
}

async function fetchSystemHealth() {
  const res = await fetch('/api/system-health');
  if (!res.ok) return null;
  return res.json();
}

async function refreshStatus() {
  const btn = document.getElementById('refresh-btn');
  if (btn) btn.classList.add('loading');

  hideMessage();

  try {
    const [statusData, jobsData, systemHealth] = await Promise.all([
      fetchStatus(),
      fetchJobsList(),
      fetchSystemHealth(),
    ]);
    await window.BBUI.core.updateDataDirWarning();
    window.BBUI.core.setAppCheckIntervalDays(statusData.check_interval_days || 30);

    const jobMap = {};
    for (const job of (jobsData.jobs || [])) {
      const k = String(job.key || '').toLowerCase();
      if (!k) continue;
      jobMap[k] = job;
    }

    const knownKeys = new Set((statusData.backups || []).map(b => String(b.key || '').toLowerCase()));
    for (const job of (jobsData.jobs || [])) {
      if (!job.is_utility && !knownKeys.has(String(job.key || '').toLowerCase())) {
        statusData.backups.push({
          key:         job.key,
          backup_type: job.backup_type,
          location:    job.location,
          enabled:     job.enabled !== false,
          never_run:   true,
        });
      }
    }

    for (const b of (statusData.backups || [])) {
      const job = jobMap[String(b.key || '').toLowerCase()];
      if (!job) continue;
      b.enabled = job.enabled !== false;
    }

    const coreState = window.BBUI.core.state;
    coreState.data = statusData;
    coreState.lastRefresh = new Date();
    dashboardSystemHealth = systemHealth;
    renderDashboard(coreState.data, dashboardSystemHealth);
    updateRefreshLabel();
  } catch (err) {
    showError(dashboardT('dashboard.loadError', { message: err.message }));
  } finally {
    if (btn) btn.classList.remove('loading');
  }
}

function scheduleAutoRefresh() {
  const coreState = window.BBUI.core.state;
  if (coreState.refreshTimer) clearInterval(coreState.refreshTimer);
  coreState.refreshTimer = setInterval(refreshStatus, coreState.REFRESH_INTERVAL_MS);
}

function updateRefreshLabel() {
  const coreState = window.BBUI.core.state;
  const el = document.getElementById('last-refresh');
  if (!el || !coreState.lastRefresh) return;
  const t = coreState.lastRefresh;
  const language = window.BBUI?.components?.i18n?.getLanguage?.() || 'de';
  const time = t.toLocaleTimeString(language === 'en' ? 'en-GB' : 'de-DE', {
    hour: '2-digit',
    minute: '2-digit',
  });
  el.textContent = dashboardT('dashboard.updated', { time });
}

function renderDashboard(data, systemHealth) {
  renderSummaryBar(data.summary);
  renderRestoreVerificationSummary(data.backups || []);
  renderDashboardSystemWarning(systemHealth);
  renderBackupGrid(data.backups);
}

function renderDashboardSystemWarning(data) {
  const el = document.getElementById('dashboard-system-warning');
  if (!el) return;
  if (!data || !data.checks) {
    el.classList.add('hidden');
    el.textContent = '';
    return;
  }
  const ok = data.checks.data_root_ok
    && data.checks.jobs_path_ok
    && data.checks.secrets_path_ok
    && data.checks.last_migration_successful;
  if (ok) {
    el.classList.add('hidden');
    el.textContent = '';
    return;
  }
  el.className = 'status-message warning';
  el.textContent = dashboardT('dashboard.systemWarning');
}

function renderSummaryBar(summary) {
  const el = document.getElementById('summary-bar');
  if (!el) return;

  el.innerHTML = [
    statTile('total',   summary.total,   dashboardT('dashboard.total'), iconGrid()),
    statTile('success', summary.success, dashboardT('dashboard.successful'), iconCheck()),
    statTile('skipped', summary.skipped || 0, dashboardT('dashboard.skipped'), iconSkip()),
    statTile('warning', summary.warning, dashboardT('dashboard.warnings'), iconWarn()),
    statTile('error',   summary.error,   dashboardT('dashboard.errors'), iconX()),
  ].join('');
}

function renderRestoreVerificationSummary(backups) {
  const el = document.getElementById('restore-summary-bar');
  if (!el) return;
  if (!Array.isArray(backups) || backups.length === 0) {
    el.innerHTML = '';
    return;
  }

  const scoped = backups.filter((b) => String(b.restore_verification_status || '').toLowerCase() !== 'not_required');
  const notRequired = backups.length - scoped.length;
  const verified = scoped.filter((b) => b.restore_verification_status === 'verified').length;
  const stale = scoped.filter((b) => b.restore_verification_status === 'stale').length;
  const failed = scoped.filter((b) => b.restore_verification_status === 'failed').length;
  const never = scoped.filter((b) => b.restore_verification_status === 'never').length;

  el.innerHTML = [
    statTile('success', `${verified}/${scoped.length}`, dashboardT('dashboard.restoreVerified'), iconCheck()),
    statTile('warning', stale, dashboardT('dashboard.restoreOverdue'), iconWarn()),
    statTile('error', failed, dashboardT('dashboard.restoreFailed'), iconX()),
    statTile('unknown', never, dashboardT('dashboard.restoreOpen'), iconGrid()),
    statTile('total', notRequired, dashboardT('dashboard.restoreNotScheduled'), iconSkip()),
  ].join('');
}

function statTile(cls, value, label, icon) {
  return `
    <div class="stat-tile ${cls}">
      <div class="stat-icon">${icon}</div>
      <div>
        <div class="stat-value">${value}</div>
        <div class="stat-label">${label}</div>
      </div>
    </div>`;
}

function renderBackupGrid(backups) {
  const el = document.getElementById('backup-grid');
  if (!el) return;

  if (!backups || backups.length === 0) {
    renderDashboardLocationSidebar([]);
    updateDashboardSelection([]);
    el.innerHTML = `<div class="ui-empty">${escHtml(dashboardT('dashboard.emptyStatus'))}<br>${escHtml(dashboardT('dashboard.emptyQuestion'))}</div>`;
    return;
  }

  const typeOrder = { flash: 0, appdata: 1, photos: 2, VMs: 3, vms: 3, sonstiges: 4 };
  const visible = backups
    .filter((backup) => dashboardSelectedLocation === 'all' || dashboardLocationKey(backup) === dashboardSelectedLocation)
    .sort((a, b) => {
      const locationDelta = DASHBOARD_LOCATION_ORDER.indexOf(dashboardLocationKey(a))
        - DASHBOARD_LOCATION_ORDER.indexOf(dashboardLocationKey(b));
      if (locationDelta) return locationDelta;
      return (typeOrder[a.backup_type] ?? 99) - (typeOrder[b.backup_type] ?? 99);
    });

  renderDashboardLocationSidebar(backups);
  updateDashboardSelection(visible);

  if (visible.length === 0) {
    el.innerHTML = `<div class="ui-empty">${escHtml(dashboardT('dashboard.noLocationBackups'))}</div>`;
    return;
  }

  el.innerHTML = `
    <table class="ui-table dashboard-inventory-table">
      <thead><tr>
        <th>${dashboardT('dashboard.backupColumn')}</th>
        <th>${dashboardT('dashboard.locationColumn')}</th>
        <th>${dashboardT('dashboard.runStatusColumn')}</th>
        <th>${dashboardT('dashboard.restoreColumn')}</th>
        <th>${dashboardT('dashboard.storageColumn')}</th>
        <th>${dashboardT('dashboard.growthCheckColumn')}</th>
      </tr></thead>
      <tbody>${visible.map(renderDashboardInventoryRow).join('')}</tbody>
    </table>`;
}

function dashboardLocationKey(backup) {
  const location = String(backup?.location || '').toLowerCase();
  return DASHBOARD_LOCATION_ORDER.includes(location) ? location : 'local';
}

function dashboardLocationGlyph(location) {
  return locationIcon(location);
}

function dashboardBackupCount(count) {
  return dashboardT(count === 1 ? 'dashboard.backupCountOne' : 'dashboard.backupCountMany', { count });
}

function renderDashboardLocationSidebar(backups) {
  const el = document.getElementById('dashboard-location-list');
  if (!el) return;
  const entries = ['all', ...DASHBOARD_LOCATION_ORDER];
  el.innerHTML = entries.map((location) => {
    const count = location === 'all'
      ? backups.length
      : backups.filter((backup) => dashboardLocationKey(backup) === location).length;
    const label = location === 'all' ? dashboardT('dashboard.allLocations') : dashboardLocationLabel(location);
    const detail = location === 'all' ? dashboardT('jobs.overview') : dashboardBackupCount(count);
    return `<button class="ui-context-nav__item ${dashboardSelectedLocation === location ? 'is-active' : ''}" data-dashboard-location="${location}" ${dashboardSelectedLocation === location ? 'aria-current="page"' : ''}>
      <span class="location-nav-glyph ${location}">${dashboardLocationGlyph(location)}</span>
      <span class="location-nav-copy"><strong>${escHtml(label)}</strong><small>${escHtml(detail)}</small></span>
      <span class="ui-badge location-nav-count">${count}</span>
    </button>`;
  }).join('');
  el.querySelectorAll('[data-dashboard-location]').forEach((button) => {
    button.addEventListener('click', () => {
      dashboardSelectedLocation = button.dataset.dashboardLocation || 'all';
      renderBackupGrid(backups);
    });
  });
}

function updateDashboardSelection(visible) {
  const title = document.getElementById('dashboard-selection-title');
  const count = document.getElementById('dashboard-selection-count');
  if (title) {
    title.textContent = dashboardSelectedLocation === 'all'
      ? dashboardT('dashboard.allLocations')
      : dashboardLocationLabel(dashboardSelectedLocation);
  }
  if (count) count.textContent = dashboardBackupCount(visible.length);
}

function dashboardRunStatus(backup) {
  if (backup.never_run) return { cls: 'unknown', label: dashboardT('dashboard.neverExecuted') };
  const status = String(backup.status || 'unknown').toLowerCase();
  return {
    cls: status,
    label: {
      success: dashboardT('dashboard.successful'),
      skipped: dashboardT('dashboard.skipped'),
      warning: dashboardT('jobs.statusWarning'),
      error: dashboardT('jobs.statusError'),
    }[status] || dashboardT('dashboard.unknown'),
  };
}

function dashboardRunMessage(backup) {
  if (backup.never_run) return { cls: '', text: dashboardT('dashboard.neverExecutedHint') };
  if (backup.status === 'error') {
    return { cls: 'error', text: backup.error_message || backup.message || dashboardT('dashboard.backupFailedDetails') };
  }
  if (backup.status === 'skipped') {
    const key = `dashboard.skipReasons.${backup.skip_reason_code || 'skipped'}`;
    const translated = dashboardT(key);
    return { cls: 'warning', text: translated === key ? dashboardT('dashboard.skipDefault') : translated };
  }
  return { cls: '', text: '' };
}

function renderDashboardRestoreVerificationBadge(backup) {
  const status = String(backup.restore_verification_status || '').toLowerCase();
  if (!status) return '';
  const map = {
    verified: { cls: 'success', text: dashboardT('jobs.restoreVerified') },
    stale: { cls: 'warning', text: dashboardT('jobs.restoreStale') },
    failed: { cls: 'error', text: dashboardT('jobs.restoreFailed') },
    never: { cls: 'unknown', text: dashboardT('jobs.restoreOpen') },
    not_required: { cls: 'neutral', text: dashboardT('jobs.restoreNotRequired') },
  };
  const m = map[status];
  if (!m) return '';
  const details = [
    backup.restore_verification_last_test_date ? dashboardT('jobs.lastTest', { date: backup.restore_verification_last_test_date }) : '',
    backup.restore_verification_valid_until ? dashboardT('jobs.validUntil', { date: backup.restore_verification_valid_until }) : '',
  ].filter(Boolean).join(' · ');
  return `<span class="restore-v-badge ${m.cls}" title="${escHtml(details || m.text)}">${m.text}</span>${details ? `<span class="dashboard-cell-detail">${escHtml(details)}</span>` : ''}`;
}

function renderDashboardInventoryRow(backup) {
  const location = dashboardLocationKey(backup);
  const run = dashboardRunStatus(backup);
  const message = dashboardRunMessage(backup);
  const growthClass = backup.growth_bytes == null ? 'neutral' : backup.growth_bytes > 0 ? 'positive' : 'negative';
  let checkStatus = backup.repository_check_status;
  if (checkStatus === 'ok' && isStaleDate(backup.repository_check_date)) checkStatus = 'overdue';
  const checkLabel = checkStatus ? repoCheckLabel({ ...backup, repository_check_status: checkStatus }) : dashboardT('dashboard.checkUnknown');
  const type = capitalize(backup.backup_type || '—');
  const identityDetail = backup.archive_name || backup.key || dashboardT('dashboard.neverExecuted');
  const runDetail = [backup.time_ago || '', backup.duration_formatted || ''].filter(Boolean).join(' · ') || '—';
  const hasSizes = Number(backup.original_size || 0) > 0;
  const sizePrimary = hasSizes ? (backup.deduplicated_size_formatted || '—') : dashboardT('dashboard.noSizeData');
  const sizeDetail = hasSizes
    ? `${dashboardT('dashboard.source')}: ${backup.original_size_formatted || '—'} · ${dashboardT('dashboard.compressed')}: ${backup.compressed_size_formatted || '—'} · ${dashboardT('dashboard.repository')}: ${backup.repository_size_formatted || '—'}`
    : '';
  const growth = backup.growth_formatted || '—';

  return `<tr class="dashboard-inventory-row ${run.cls}">
    <td><div class="dashboard-backup-identity">
      <span class="type-icon type-icon-${escHtml(String(backup.backup_type || 'sonstiges').toLowerCase())}">${typeIcon(backup.backup_type)}</span>
      <span><strong class="dashboard-cell-primary">${escHtml(type)}</strong><span class="dashboard-cell-detail mono" title="${escHtml(identityDetail)}">${escHtml(identityDetail)}</span></span>
    </div></td>
    <td><span class="loc-badge ${location}">${escHtml(dashboardLocationLabel(location))}</span></td>
    <td><div class="dashboard-table-badges">
      ${backup.enabled === false ? `<span class="badge warning"><span class="badge-dot"></span>${dashboardT('dashboard.disabled')}</span>` : ''}
      <span class="badge ${run.cls}"><span class="badge-dot"></span>${escHtml(run.label)}</span>
    </div><span class="dashboard-cell-detail">${escHtml(runDetail)}</span>${message.text ? `<div class="dashboard-table-message ${message.cls}">${escHtml(message.text)}</div>` : ''}</td>
    <td>${renderDashboardRestoreVerificationBadge(backup) || `<span class="dashboard-cell-detail">${dashboardT('dashboard.unknown')}</span>`}</td>
    <td><strong class="dashboard-cell-primary">${escHtml(sizePrimary)}</strong>${sizeDetail ? `<span class="dashboard-cell-detail">${escHtml(sizeDetail)}</span>` : ''}</td>
    <td><strong class="dashboard-cell-primary dashboard-growth ${growthClass}">${escHtml(growth)}</strong><span class="dashboard-cell-detail repo-check ${escHtml(checkStatus || 'unknown')}">${repoCheckIcon(checkStatus)} ${escHtml(checkLabel)}</span></td>
  </tr>`;
}

function typeIcon(type) {
  switch ((type || '').toLowerCase()) {
    case 'flash':
      return svg('M13 2 3 14 12 14 11 22 21 10 12 10z');
    case 'appdata':
    case 'docker':
      return svg('M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z');
    case 'photos':
      return svg('M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z M12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z');
    case 'vms':
    case 'VMs':
      return svg('M2 2h20v8H2z M2 14h20v8H2z M6 6h.01 M6 18h.01');
    case 'folder':
      return svg('M3 6h5l2 2h11v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z M3 6V4a1 1 0 0 1 1-1h5l2 2');
    case 'cloud':
      return svg('M7 18a4 4 0 1 1 .6-7.96A5 5 0 0 1 17 11a3.5 3.5 0 1 1 .5 7H7z');
    case 'archive':
      return svg('M3 7h18 M5 7v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7 M10 11h4');
    case 'database':
      return svg('M12 5c-4.4 0-8 1.3-8 3s3.6 3 8 3 8-1.3 8-3-3.6-3-8-3z M4 8v4c0 1.7 3.6 3 8 3s8-1.3 8-3V8 M4 12v4c0 1.7 3.6 3 8 3s8-1.3 8-3v-4');
    case 'server':
      return svg('M3 4h18v6H3z M3 14h18v6H3z M7 7h.01 M7 17h.01');
    case 'home':
      return svg('M3 11 12 4 21 11 M5 10v10h14V10 M9 20v-6h6v6');
    case 'music':
      return svg('M9 18V5l12-2v13 M9 18a3 3 0 1 0 0 .1 M21 16a3 3 0 1 0 0 .1');
    case 'video':
      return svg('M3 7h14v10H3z M17 10l4-3v10l-4-3z');
    case 'documents':
      return svg('M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h8');
    case 'code':
      return svg('M8 9 4 12l4 3 M16 9l4 3-4 3 M14 5l-4 14');
    case 'camera':
      return svg('M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z M12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z');
    case 'usb':
      return svg('M12 2v9 M12 11l-3-3 M12 11l3-3 M12 11v7 M9 21h6 M6 7h2 M16 7h2');
    case 'shield':
      return svg('M12 2 4 5v6c0 5 3.5 9.7 8 11 4.5-1.3 8-6 8-11V5z');
    case 'sonstiges':
    default:
      return svg('M4 17l6-6-6-6 M12 19h8');
  }
}

function svg(d) {
  const paths = d.split(' M ').map((p, i) => `<path d="${i === 0 ? p : 'M ' + p}"/>`).join('');
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
}

function iconCheck() {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>`;
}

function iconWarn() {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
}

function iconSkip() {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="12" x2="20" y2="12"/><polyline points="14 6 20 12 14 18"/></svg>`;
}

function iconX() {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`;
}

function iconGrid() {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>`;
}

function repoCheckIcon(status) {
  if (status === 'ok')      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12"><polyline points="20 6 9 17 4 12"/></svg>`;
  if (status === 'overdue') return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
}

function repoCheckLabel(b) {
  if (b.repository_check_status === 'ok')
    return dashboardT('dashboard.checkOk', {
      date: b.repository_check_date ? ` (${b.repository_check_date.slice(0, 10)})` : '',
    });
  if (b.repository_check_status === 'overdue')
    return dashboardT('dashboard.checkOverdue', { date: b.repository_next_check || '—' });
  return dashboardT('dashboard.checkUnknown');
}

function showError(msg) {
  const el = document.getElementById('status-message');
  if (!el) return;
  el.className = 'status-message error-state';
  el.textContent = msg;
}

function showEmpty(html) {
  const el = document.getElementById('status-message');
  if (!el) return;
  el.className = 'status-message empty-state';
  el.innerHTML = html;
}

function hideMessage() {
  const el = document.getElementById('status-message');
  if (el) el.className = 'status-message hidden';
}

window.addEventListener?.('bbui:language-changed', () => {
  const coreState = window.BBUI?.core?.state;
  if (coreState?.data) renderDashboard(coreState.data, dashboardSystemHealth);
  updateRefreshLabel();
  window.BBUI?.core?.updateDataDirWarning?.();
});
