'use strict';

// ══════════════════════════════════════════════════════════════════════════════
// DASHBOARD PAGE
// ══════════════════════════════════════════════════════════════════════════════

function dashboardT(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(key, params) || key;
}

function dashboardLocationLabel(location) {
  return {
    all: dashboardT('dashboard.allLocations'),
    local: dashboardT('jobs.locationLocal'),
    usb: dashboardT('jobs.locationUsb'),
    smb: dashboardT('jobs.locationSmb'),
    storagebox: dashboardT('jobs.locationStoragebox'),
  }[location] || location || '—';
}

let dashboardSystemHealth = null;
let dashboardSelectedLocation = 'all';
const dashboardExpandedJobs = new Set();
let dashboardAttentionExpanded = false;
const DASHBOARD_LOCATION_ORDER = ['local', 'usb', 'smb', 'storagebox'];

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
  try {
    return await window.BBUI.core.fetchSystemHealth(false);
  } catch {
    return null;
  }
}

async function fetchDashboardSchedules() {
  try {
    const res = await fetch('/api/schedules');
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

/** Refresh dashboard status, job metadata, schedules and health together. */
async function refreshStatus() {
  window.BBUI?.resourceMonitor?.start();
  const btn = document.getElementById('refresh-btn');
  if (btn) btn.classList.add('loading');

  hideMessage();

  try {
    const [statusData, jobsData, schedulesData, systemHealth] = await Promise.all([
      fetchStatus(),
      fetchJobsList(),
      fetchDashboardSchedules(),
      fetchSystemHealth(),
    ]);
    await window.BBUI.core.updateDataDirWarning();
    window.BBUI.core.setAppCheckIntervalDays(statusData.check_interval_days || 30);
    if (schedulesData) {
      window.BBUI.core.setSchedulesData(schedulesData);
    }

    const jobMap = {};
    for (const job of (jobsData.jobs || [])) {
      const k = String(job.key || '').toLowerCase();
      if (!k) continue;
      jobMap[k] = job;
    }

    statusData.backups ||= [];
    const knownKeys = new Set(statusData.backups.map(b => String(b.key || '').toLowerCase()));
    for (const job of (jobsData.jobs || [])) {
      if (!job.is_utility && !knownKeys.has(String(job.key || '').toLowerCase())) {
        statusData.backups.push({
          key:         job.key,
          archive_prefix: job.archive_prefix,
          backup_type: job.backup_type,
          location:    job.location,
          display_name: job.display_name || job.name || '',
          name:        job.name || job.display_name || '',
          icon:        job.icon || '',
          icon_color:  job.icon_color || '',
          enabled:     job.enabled !== false,
          never_run:   true,
        });
      }
    }

    for (const b of (statusData.backups || [])) {
      const job = jobMap[String(b.key || '').toLowerCase()];
      if (!job) continue;
      b.restore_verification_status ??= job.restore_verification_status;
      b.restore_verification_last_test ??= job.restore_verification_last_test;
      b.restore_verification_valid_until ??= job.restore_verification_valid_until;
      b.enabled = job.enabled !== false;
      b.display_name = job.display_name || job.name || b.display_name || '';
      b.group_name = job.group_name || b.group_name || "";
      b.groups = job.groups || [];
      b.name = job.name || job.display_name || b.name || '';
      b.archive_prefix = job.archive_prefix || '';
      b.icon = job.icon || b.icon || '';
      b.icon_color = job.icon_color || b.icon_color || '';
    }

    const coreState = window.BBUI.core.state;
    coreState.data = statusData;
    coreState.lastRefresh = new Date();
    dashboardSystemHealth = systemHealth;
    renderDashboard(coreState.data, dashboardSystemHealth);
    refreshDashboardOverview();
    try {
      const setupStatus = await window.BBUI.core.fetchSetupStatus(false);
      window.BBUI?.setupWizard?.renderDashboardPanel?.(setupStatus);
    } catch (_) {
      window.BBUI?.setupWizard?.renderDashboardPanel?.({});
    }
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
  renderManagementDashboard(data.backups || []);
  renderDashboardSystemWarning(systemHealth);
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

/**
 * Count each latest outcome once; overdue remains an independent time status.
 * @param {object[]} backups Current status rows, including jobs without a run.
 * @returns {{counts: object, total: number, overdue: number}} Outcome and time counts.
 */
function dashboardBackupSummary(backups) {
  const counts = { success: 0, warning: 0, error: 0, skipped: 0, cancelled: 0, unknown: 0 };
  for (const backup of backups) {
    const status = backup.never_run ? 'unknown' : String(backup.status || '').toLowerCase();
    counts[Object.hasOwn(counts, status) ? status : 'unknown'] += 1;
  }
  return { counts, total: backups.length, overdue: backups.filter((backup) => backup.backup_overdue).length };
}

/**
 * Build a compact labeled ring with solid, hard-stop color segments and outcome counts.
 * @param {object[]} rows Counts, translated labels and fixed semantic color classes.
 * @param {number} value Verified/successful count shown inside the ring.
 * @param {number} total Scope denominator; zero produces an empty neutral ring.
 * @param {string} centerLabel Translated numerator label.
 * @returns {string} Escaped summary markup, including a textual legend.
 */
function dashboardSummaryContent(rows, value, total, centerLabel) {
  let offset = 0;
  const segments = rows.filter((row) => row.count > 0).map((row) => {
    const start = offset;
    offset += total ? row.count / total * 100 : 0;
    return `var(--dashboard-ring-${row.cls}) ${start}% ${offset}%`;
  });
  const fill = segments.length ? `conic-gradient(${segments.join(',')})` : 'var(--ui-color-border)';
  const description = rows.map((row) => `${row.count} ${row.label}`).join(' · ');
  return `<div class="dashboard-summary-body">
    <div class="dashboard-summary-ring" style="--dashboard-ring-fill:${fill}" role="img" aria-label="${escHtml(description)}">
      <div class="dashboard-summary-ring__center"><span><strong>${value}</strong><small>/${total}</small></span></div>
    </div>
    <div class="dashboard-summary-numbers"><div class="dashboard-summary-primary"><strong>${value}</strong><span>${escHtml(centerLabel)}</span></div>
    <dl class="dashboard-summary-legend">${rows.slice(1).map((row) => `<div class="dashboard-summary-stat ${row.cls}${row.count === 0 ? ' is-zero' : ''}"><dt>${escHtml(row.label)}</dt><dd>${row.count}</dd></div>`).join('')}</dl></div>
  </div>`;
}

/**
 * Render backup outcomes from job rows rather than the API's overdue-adjusted counters.
 * @param {object[]} backups Rows for the selected location; overdue is a separate count.
 */
function renderSummaryBar(backups) {
  const el = document.getElementById('summary-bar');
  if (!el) return;
  const summary = dashboardBackupSummary(backups);
  const rows = [
    { cls: 'success', count: summary.counts.success, label: dashboardT('dashboard.successful') },
    { cls: 'warning', count: summary.counts.warning, label: dashboardT('dashboard.withWarnings') },
    { cls: 'error', count: summary.counts.error, label: dashboardT('dashboard.errors') },
    { cls: 'neutral', count: summary.counts.skipped, label: dashboardT('dashboard.skipped') },
    ...(summary.counts.cancelled ? [{ cls: 'cancelled', count: summary.counts.cancelled, label: dashboardT('jobs.statusCancelled') }] : []),
    ...(summary.counts.unknown ? [{ cls: 'unknown', count: summary.counts.unknown, label: dashboardT('dashboard.unknownOrNever') }] : []),
  ];
  el.innerHTML = dashboardSummaryContent(rows, summary.counts.success, summary.total, dashboardT('dashboard.successful'))
    + `<p class="dashboard-summary-context">${escHtml(dashboardSelectedLocation === 'all' ? dashboardT('dashboard.allLocations') : dashboardLocationLabel(dashboardSelectedLocation))} · ${escHtml(dashboardT('dashboard.latestOutcomes', { count: summary.total }))}</p>`
    + (summary.overdue ? `<p class="dashboard-summary-overdue">${escHtml(dashboardT(summary.overdue === 1 ? 'dashboard.overdueCountOne' : 'dashboard.overdueCountMany', { count: summary.overdue }))}</p>` : '');
}

/**
 * Render verification scope explicitly and retain focus on the test-plan link during refresh.
 * Missing metadata stays unknown, never verified.
 * @param {object[]} backups Current rows; coverage includes all jobs, while the plan ratio excludes unplanned/unknown states.
 */
function renderRestoreVerificationSummary(backups) {
  const el = document.getElementById('restore-summary-bar');
  if (!el) return;
  const counts = { verified: 0, stale: 0, failed: 0, never: 0, not_required: 0, unknown: 0 };
  for (const backup of backups) {
    const status = String(backup.restore_verification_status || '').toLowerCase();
    counts[Object.hasOwn(counts, status) ? status : 'unknown'] += 1;
  }
  const total = backups.length - counts.not_required - counts.unknown;
  const rows = [
    { cls: 'success', count: counts.verified, label: dashboardT('dashboard.restoreVerified') },
    { cls: 'warning', count: counts.stale, label: dashboardT('dashboard.restoreOverdue') },
    { cls: 'error', count: counts.failed, label: dashboardT('dashboard.restoreFailed') },
    { cls: 'unknown', count: counts.never, label: dashboardT('dashboard.restoreOpen') },
  ];
  const states = {verified: 'success', stale: 'warning', failed: 'error', never: 'unknown', not_required: 'neutral', unknown: 'unknown'};
  const description = dashboardT('dashboard.restoreCoverageDescription', {count: counts.verified, total: backups.length});
  patchJobMarkup(el, `<div class="dashboard-restore-coverage">
    <div class="dashboard-summary-primary"><strong>${counts.verified}</strong><span>${escHtml(dashboardT('dashboard.restoreCoverageTotal', {total: backups.length}))}</span></div>
    <div class="dashboard-coverage-track" role="img" aria-label="${escHtml(description)}">${Object.entries(counts).map(([state, count]) => `<span class="${states[state]}"></span>`.repeat(count)).join('')}</div>
    <div class="dashboard-coverage-caption"><span>${escHtml(dashboardT('dashboard.restorePlansVerified', {count: counts.verified, total}))}</span><span>${escHtml(dashboardT('dashboard.restoreUnplannedCount', {count: counts.not_required}))}</span></div>
    <div class="dashboard-restore-exceptions">${rows.slice(1).filter(row => row.count).map(row => `<span class="${row.cls}">${row.count} ${escHtml(row.label)}</span>`).join(' · ')}${counts.unknown ? `<span>${escHtml(dashboardT('dashboard.restoreUnknownCount', {count: counts.unknown}))}</span>` : ''}</div>
    <button type="button" class="dashboard-details-toggle dashboard-tests-link" data-dashboard-page="restore-tests">${escHtml(dashboardT('management.openTests'))} <span aria-hidden="true">→</span></button>
  </div>`);
}

/**
 * Return actionable outcomes and overdue states separately, without fabricating check plans.
 * @param {object[]} backups Current rows with existing run and reminder metadata.
 * @returns {object[]} Descriptions and affected rows, ordered with failures first.
 */
function dashboardAttentionItems(backups) {
  const items = [];
  for (const backup of backups) {
    const run = dashboardRunStatus(backup);
    const message = dashboardRunMessage(backup);
    if (!backup.never_run && ['error', 'warning', 'skipped', 'cancelled'].includes(backup.status)) {
      items.push({ backup, cls: run.cls === 'error' ? 'error' : 'warning', label: run.label, message: message.text });
    }
    if (backup.backup_overdue) {
      items.push({ backup, cls: 'warning', label: dashboardT('dashboard.backupOverdue'), message: dashboardT('dashboard.backupOverdueDetails', {
        date: dashboardAbsoluteTimestamp(backup.backup_overdue_after || backup.backup_overdue_expected_run),
      }) });
    }
    if (['failed', 'stale'].includes(backup.restore_verification_status)) {
      const failed = backup.restore_verification_status === 'failed';
      items.push({ backup, cls: failed ? 'error' : 'warning', label: dashboardT(failed ? 'dashboard.restoreFailed' : 'dashboard.restoreOverdue'),
        message: dashboardT(failed ? 'dashboard.restoreFailureAttention' : 'dashboard.restoreOverdueAttention') });
    }
  }
  return items.sort((a, b) => (a.cls === 'error' ? 0 : 1) - (b.cls === 'error' ? 0 : 1));
}

/**
 * Render a compact disclosure; escaped issue descriptions expand directly below it.
 * Preserve its open state and keyboard focus across polling and language changes.
 * @param {object[]} backups Current status rows; an empty result hides the section.
 */
function renderDashboardAttention(backups) {
  const el = document.getElementById('dashboard-attention');
  if (!el) return;
  const items = dashboardAttentionItems(backups);
  el.hidden = items.length === 0;
  const focused = document.activeElement?.id === 'dashboard-attention-toggle';
  const first = items[0];
  el.innerHTML = items.length ? `<details class="dashboard-attention-disclosure ${first.cls}"${dashboardAttentionExpanded ? ' open' : ''}>
    <summary id="dashboard-attention-toggle"><span class="dashboard-attention-icon" aria-hidden="true">${iconWarn()}</span>
      <strong>${escHtml(dashboardT('dashboard.attentionCount', {count: items.length}))}</strong>
      <span class="dashboard-attention-preview">${escHtml(first.backup.name || first.backup.display_name || first.backup.key)} · <span class="dashboard-attention-label">${escHtml(first.label)}</span></span>
      <span class="dashboard-attention-action">${escHtml(dashboardT('dashboard.viewDetails'))}<span class="dashboard-details-chevron" aria-hidden="true">›</span></span></summary>
    <ul>${items.map(item => `<li class="${item.cls}"><span class="dashboard-attention-icon" aria-hidden="true">${iconWarn()}</span><div><strong>${escHtml(item.backup.name || item.backup.display_name || item.backup.key)} · ${escHtml(dashboardLocationLabel(dashboardLocationKey(item.backup)))}</strong><span class="dashboard-attention-label">${escHtml(item.label)}</span><p>${escHtml(item.message)}</p></div></li>`).join('')}</ul></details>` : '';
  el.querySelector('details')?.addEventListener('toggle', event => { dashboardAttentionExpanded = event.currentTarget.open; });
  if (focused) el.querySelector('summary')?.focus({preventScroll: true});
}

/**
 * Generate a stable HTML-safe row ID for arbitrary job keys.
 * @param {string} key Job identity, independent of display name or location filter.
 * @returns {string} Code-point-encoded DOM ID.
 */
function dashboardDetailsId(key) {
  return 'dashboard-details-' + Array.from(String(key || '')).map((char) => char.codePointAt(0).toString(16)).join('-');
}

/**
 * Toggle an existing details row without rebuilding the table or losing keyboard focus.
 * @param {HTMLButtonElement} button Inventory disclosure with the stable job key.
 */
function toggleDashboardJobDetails(button) {
  const key = button.dataset.dashboardDetails;
  const expanded = !dashboardExpandedJobs.has(key);
  if (expanded) dashboardExpandedJobs.add(key); else dashboardExpandedJobs.delete(key);
  const row = document.getElementById(dashboardDetailsId(key));
  if (row) row.hidden = !expanded;
  button.setAttribute('aria-expanded', String(expanded));
  button.setAttribute('aria-label', dashboardT(expanded ? 'dashboard.hideJobDetails' : 'dashboard.showJobDetails', { job: button.dataset.dashboardJobName }));
}

/**
 * Rebuild the grouped inventory and backup summary for the selected location, retaining disclosures and focus.
 * @param {object[]} backups Current status rows; removed jobs lose their expansion state.
 */
function renderBackupGrid(backups) {
  const el = document.getElementById('backup-grid');
  if (!el) return;

  if (!backups || backups.length === 0) {
    dashboardExpandedJobs.clear();
    dashboardSelectedLocation = 'all';
    renderDashboardLocationSidebar([]);
    updateDashboardSelection([]);
    renderSummaryBar([]);
    el.innerHTML = `<div class="ui-empty">${escHtml(dashboardT('dashboard.emptyStatus'))}<br>${escHtml(dashboardT('dashboard.emptyQuestion'))}</div>`;
    return;
  }

  const currentKeys = new Set(backups.map((backup) => String(backup.key)));
  for (const key of dashboardExpandedJobs) if (!currentKeys.has(key)) dashboardExpandedJobs.delete(key);
  if (dashboardSelectedLocation !== 'all' && !backups.some((backup) => dashboardLocationKey(backup) === dashboardSelectedLocation)) dashboardSelectedLocation = 'all';
  const focusedKey = document.activeElement?.dataset?.dashboardDetails;
  const focusedLocation = document.activeElement?.dataset?.dashboardLocation;
  const visible = backups
    .filter((backup) => dashboardSelectedLocation === 'all' || dashboardLocationKey(backup) === dashboardSelectedLocation)
    .sort((a, b) => {
      const locationDelta = DASHBOARD_LOCATION_ORDER.indexOf(dashboardLocationKey(a))
        - DASHBOARD_LOCATION_ORDER.indexOf(dashboardLocationKey(b));
      if (locationDelta) return locationDelta;
      return String(a.name || a.display_name || '').localeCompare(String(b.name || b.display_name || ''));
    });

  renderDashboardLocationSidebar(backups);
  updateDashboardSelection(visible);
  renderSummaryBar(visible);

  if (visible.length === 0) {
    el.innerHTML = `<div class="ui-empty">${escHtml(dashboardT('dashboard.noLocationBackups'))}</div>`;
    return;
  }

  el.innerHTML = `
    <table class="ui-table dashboard-inventory-table">
      <thead><tr>
        <th>${dashboardT('dashboard.backupColumn')}</th>
        <th>${dashboardT('dashboard.runStatusColumn')}</th>
        <th>${dashboardT('dashboard.nextRunTime')}</th>
        <th>${dashboardT('dashboard.restoreColumn')}</th>
        <th>${dashboardT('dashboard.repository')}</th>
      </tr></thead>
      <tbody>${renderDashboardLocationGroups(visible)}</tbody>
    </table>`;
  el.querySelectorAll('[data-dashboard-details]').forEach((button) => button.addEventListener('click', () => toggleDashboardJobDetails(button)));
  if (focusedKey) document.getElementById(dashboardDetailsId(focusedKey) + '-toggle')?.focus({ preventScroll: true });
  if (focusedLocation) document.querySelector(`[data-dashboard-location="${focusedLocation}"]`)?.focus({ preventScroll: true });
}

function renderDashboardLocationGroups(backups) {
  const locations = dashboardSelectedLocation === 'all'
    ? DASHBOARD_LOCATION_ORDER
    : [dashboardSelectedLocation];
  return locations.map((location) => {
    const locationBackups = backups.filter((backup) => dashboardLocationKey(backup) === location);
    if (!locationBackups.length) return '';
    return `${renderDashboardLocationGroupRow(location, locationBackups.length)}${locationBackups.map(renderDashboardInventoryRow).join('')}`;
  }).join('');
}

function renderDashboardLocationGroupRow(location, count) {
  return `<tr class="dashboard-location-group-row">
    <td colspan="5">
      <span class="dashboard-location-group__identity">
        <span class="location-nav-glyph ${location}">${dashboardLocationGlyph(location)}</span>
        <span><strong>${escHtml(dashboardLocationLabel(location))}</strong><small>${escHtml(dashboardBackupCount(count))}</small></span>
      </span>
    </td>
  </tr>`;
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
  const entries = ['all', ...DASHBOARD_LOCATION_ORDER.filter((location) => backups.some((backup) => dashboardLocationKey(backup) === location))];
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
      document.querySelector(`[data-dashboard-location="${dashboardSelectedLocation}"]`)?.focus({ preventScroll: true });
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
    cls: status === 'cancelled' ? 'warning' : (['success', 'skipped', 'warning', 'error'].includes(status) ? status : 'unknown'),
    label: {
      success: dashboardT('dashboard.successful'),
      skipped: dashboardT('dashboard.skipped'),
      warning: dashboardT('jobs.statusWarning'),
      cancelled: dashboardT('jobs.statusCancelled'),
      error: dashboardT('jobs.statusError'),
    }[status] || dashboardT('dashboard.unknown'),
  };
}

function dashboardRunMessage(backup) {
  if (backup.never_run) return { cls: '', text: dashboardT('dashboard.neverExecutedHint') };
  if (['error', 'warning', 'cancelled'].includes(backup.status)) {
    return { cls: backup.status === 'error' ? 'error' : 'warning', text: backup.error_message || backup.message || dashboardT(backup.status === 'error' ? 'dashboard.backupFailedDetails' : 'dashboard.backupWarningDetails') };
  }
  if (backup.status === 'skipped') {
    const key = `dashboard.skipReasons.${backup.skip_reason_code || 'skipped'}`;
    const translated = dashboardT(key);
    return { cls: 'warning', text: translated === key ? (backup.skip_reason_text || backup.error_message || dashboardT('dashboard.skipDefault')) : translated };
  }
  return { cls: '', text: '' };
}

function dashboardRelativeRunTime(timestamp) {
  const raw = String(timestamp || '').trim();
  if (!raw) return dashboardT('dashboard.unknown');
  const parsed = new Date(raw.includes('T') ? raw : raw.replace(' ', 'T'));
  if (Number.isNaN(parsed.getTime())) return dashboardT('dashboard.unknown');

  const diffSeconds = Math.round((parsed.getTime() - Date.now()) / 1000);
  const absolute = Math.abs(diffSeconds);
  let divisor = 1;
  let unit = 'second';
  if (absolute >= 86400) {
    divisor = 86400;
    unit = 'day';
  } else if (absolute >= 3600) {
    divisor = 3600;
    unit = 'hour';
  } else if (absolute >= 60) {
    divisor = 60;
    unit = 'minute';
  }
  const value = Math.round(diffSeconds / divisor);
  const language = window.BBUI?.components?.i18n?.getLanguage?.() === 'en' ? 'en' : 'de';
  return new Intl.RelativeTimeFormat(language, { numeric: 'always' }).format(value, unit);
}

function dashboardAbsoluteTimestamp(timestamp) {
  const raw = String(timestamp || '').trim();
  if (!raw) return '—';
  const parsed = new Date(raw.includes('T') ? raw : raw.replace(' ', 'T'));
  if (Number.isNaN(parsed.getTime())) return raw;
  const language = window.BBUI?.components?.i18n?.getLanguage?.() || 'de';
  return parsed.toLocaleString(language === 'en' ? 'en-GB' : 'de-DE', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function dashboardFormatNextRunDate(date) {
  const language = window.BBUI?.components?.i18n?.getLanguage?.() || 'de';
  const locale = language === 'en' ? 'en-GB' : 'de-DE';
  const datePart = new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
  const timePart = new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
  return `${datePart} ${timePart}`;
}

function dashboardRunDuration(seconds) {
  let remaining = Math.max(0, Math.round(Number(seconds || 0)));
  const hours = Math.floor(remaining / 3600);
  remaining %= 3600;
  const minutes = Math.floor(remaining / 60);
  const secs = remaining % 60;
  const parts = [];
  if (hours) parts.push(`${hours} ${dashboardT('dashboard.durationHoursShort')}`);
  if (minutes) parts.push(`${minutes} ${dashboardT('dashboard.durationMinutesShort')}`);
  if (secs || parts.length === 0) parts.push(`${secs} ${dashboardT('dashboard.durationSecondsShort')}`);
  return parts.join(' ');
}

function dashboardNextRun(jobKey, enabled) {
  if (enabled === false) return '';
  const schedules = window.BBUI.core.getSchedulesData?.() || {};
  const sched = schedules[jobKey];
  if (!sched) return dashboardT('dashboard.notScheduled');
  if (!sched.enabled) return dashboardT('dashboard.scheduleDisabled');
  const next = typeof calcNextRun === 'function' ? calcNextRun(sched.cron) : null;
  return next
    ? dashboardFormatNextRunDate(next)
    : (sched.cron || dashboardT('dashboard.unknown'));
}

/**
 * Render verification with full dates, or a compact inventory badge when requested.
 * @param {object} backup Existing verification status and date fields.
 * @param {boolean} compact Limit visible inventory facts to the validity date.
 * @returns {string} Badge/facts markup, or an empty string for unknown states.
 */
function renderDashboardRestoreVerificationBadge(backup, compact = false) {
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
  const cancelled = backup.restore_verification_last_test_result === 'cancelled';
  const details = [
    cancelled && backup.restore_verification_evidence_date
      ? [dashboardT('jobs.lastCompletedTestLabel'), backup.restore_verification_evidence_date] : null,
    backup.restore_verification_last_test_date
      ? [dashboardT(cancelled ? 'jobs.lastTestAttemptLabel' : 'dashboard.lastTestLabel'), cancelled ? `${dashboardT('jobs.statusCancelled')} · ${backup.restore_verification_last_test_date}` : backup.restore_verification_last_test_date]
      : null,
    backup.restore_verification_valid_until
      ? [dashboardT('dashboard.validUntilLabel'), backup.restore_verification_valid_until]
      : null,
  ].filter(Boolean);
  const title = details.map(([label, value]) => `${label}: ${value}`).join(' · ');
  if (compact) return `<span class="restore-v-badge ${m.cls}" title="${escHtml(title || m.text)}">${escHtml(m.text)}</span>${backup.restore_verification_valid_until ? `<span class="dashboard-cell-detail">${escHtml(dashboardT('dashboard.validUntilLabel'))}: ${escHtml(backup.restore_verification_valid_until)}</span>` : ''}`;
  return `<span class="restore-v-badge ${m.cls}" title="${escHtml(title || m.text)}">${m.text}</span>${details.length ? `<span class="dashboard-restore-facts">${details.map(([label, value]) => `<span class="dashboard-fact-row"><b>${escHtml(label)}:</b><span>${escHtml(value)}</span></span>`).join('')}</span>` : ''}`;
}

/**
 * Render an inventory row with the existing icons/archive identity and a keyed disclosure.
 * @param {object} backup Status row merged with configured job metadata.
 * @returns {string} Inventory row followed by its accessible expandable details row.
 */
function renderDashboardInventoryRow(backup) {
  const run = dashboardRunStatus(backup);
  const message = dashboardRunMessage(backup);
  const type = backup.name || backup.display_name || 'Backup';
  const iconKey = typeof resolveJobIcon === 'function' ? resolveJobIcon(backup) : (backup.icon || 'archive');
  const iconColorKey = typeof resolveJobIconColor === 'function' ? resolveJobIconColor(backup) : '';
  const iconColorClass = iconColorKey ? ` type-icon-color-${iconColorKey}` : '';
  const identityDetail = backup.archive_name || backup.archive_prefix || dashboardT('dashboard.neverExecuted');
  const runTime = dashboardRelativeRunTime(backup.timestamp);
  const runDuration = dashboardRunDuration(backup.duration_seconds);
  const nextRun = dashboardNextRun(backup.key, backup.enabled);
  const runFactRows = [
    ...(backup.group_name ? [[dashboardT('jobGroups.groupLabel'), backup.group_name, '']] : []),
    ...(!backup.never_run ? [
      [dashboardT('dashboard.lastRunTime'), runTime, ''],
      [dashboardT('dashboard.runDuration'), runDuration, ''],
    ] : []),
    ...(nextRun ? [[dashboardT('dashboard.nextRunTime'), nextRun, 'next-run']] : []),
    ...(backup.groups || []).filter(g => g.schedule?.enabled).map(g => {
      const next = typeof calcNextRun === 'function' ? calcNextRun(g.schedule.cron) : null;
      const label = backup.groups.length === 1 ? dashboardT('jobGroups.groupStartLabel') : g.name;
      const value = next ? dashboardFormatNextRunDate(next) : g.schedule.cron;
      return [label, value, 'group-next-run', dashboardT('jobGroups.groupStart', { schedule: g.name }) + ' · ' + value];
    }),
  ];
  const facts = (rows) => rows.map(([label, value, cls, detail]) => {
    const rowClass = cls ? ` ${cls}` : '';
    return `<span class="dashboard-fact-row${rowClass}"${detail ? ` title="${escHtml(detail)}"` : ''}><b>${escHtml(label.replace(/:\s*$/, ''))}:</b><span>${escHtml(value)}</span></span>`;
  }).join('');
  const scheduleRows = runFactRows.filter((row) => row[2] === 'next-run' || row[2] === 'group-next-run');
  const runRows = runFactRows.filter((row) => !scheduleRows.includes(row));
  const runFacts = runRows.length ? `<span class="dashboard-run-facts">${facts(runRows)}</span>` : '';
  const overdue = backup.backup_overdue ? `<span class="badge warning">${escHtml(dashboardT('dashboard.backupOverdue'))}</span><span class="dashboard-cell-detail">${escHtml(dashboardT('dashboard.backupOverdueDetails', { date: dashboardAbsoluteTimestamp(backup.backup_overdue_after || backup.backup_overdue_expected_run) }))}</span>` : '';
  const id = dashboardDetailsId(backup.key);
  const expanded = dashboardExpandedJobs.has(String(backup.key));
  const size = Number(backup.repository_size || 0) > 0 || Number(backup.original_size || 0) > 0 ? backup.repository_size_formatted || '—' : '—';
  return `<tr class="dashboard-inventory-row ${run.cls}">
    <td><div class="dashboard-backup-identity">
      <span class="type-icon${iconColorClass}">${typeIcon(iconKey)}</span>
      <span><strong class="dashboard-cell-primary">${escHtml(type)}</strong><span class="dashboard-cell-detail mono" title="${escHtml(identityDetail)}">${escHtml(identityDetail)}</span></span>
    </div>${backup.groups?.length ? `<div class="dashboard-group-memberships">${window.BBUI.jobGroups?.membership(backup, true) || ''}</div>` : ''}</td>
    <td><div class="dashboard-table-badges">
      ${backup.enabled === false ? `<span class="badge warning"><span class="badge-dot"></span>${dashboardT('dashboard.disabled')}</span>` : ''}
      <span class="badge ${run.cls}"><span class="badge-dot"></span>${escHtml(run.label)}</span>
    </div>${runFacts}${message.text ? `<div class="dashboard-table-message ${message.cls}">${escHtml(message.text)}</div>` : ''}</td>
    <td>${overdue}${scheduleRows.length ? `<span class="dashboard-run-facts">${facts(scheduleRows)}</span>` : '<span class="dashboard-cell-detail">—</span>'}</td>
    <td>${renderDashboardRestoreVerificationBadge(backup, true) || `<span class="dashboard-cell-detail">${dashboardT('dashboard.unknown')}</span>`}</td>
    <td><strong class="dashboard-cell-primary">${escHtml(size)}</strong><button type="button" id="${id}-toggle" class="dashboard-details-toggle" data-dashboard-details="${escHtml(backup.key)}" data-dashboard-job-name="${escHtml(type)}" aria-controls="${id}" aria-expanded="${expanded}" aria-label="${escHtml(dashboardT(expanded ? 'dashboard.hideJobDetails' : 'dashboard.showJobDetails', { job: type }))}"><span class="dashboard-details-chevron" aria-hidden="true">›</span>${escHtml(dashboardT('dashboard.details'))}</button></td>
  </tr><tr id="${id}" class="dashboard-details-row"${expanded ? '' : ' hidden'}><td colspan="5">${renderDashboardJobDetails(backup)}</td></tr>`;
}

/**
 * Describe the measured check step independently from the stored repository-check record.
 * @param {object} backup Status row with optional Borg workflow metadata.
 * @returns {string} Localized status/reason and available duration, or unknown.
 */
function dashboardBorgCheckResult(backup) {
  const step = backup.borg_steps?.check;
  const labels = {
    success: 'dashboard.successful', warning: 'dashboard.withWarnings', error: 'dashboard.errors',
    running: 'jobs.running', skipped: 'dashboard.skipped', cancelled: 'jobs.statusCancelled', pending: 'dashboard.notExecuted',
  };
  const label = dashboardT(labels[step?.status] || 'dashboard.unknown');
  const reason = ['not_due', 'keep_all', 'not_run', 'after_cancel', 'post_condition', 'unavailable'].includes(step?.reason)
    ? ` · ${dashboardT(`jobs.borgStep.${step.reason}`)}` : '';
  return `${label}${reason}${step?.duration_seconds == null ? '' : ` · ${dashboardRunDuration(step.duration_seconds)}`}`;
}

/**
 * Render all stored storage/check/restore facts without introducing a new check policy.
 * @param {object} backup Existing storage, workflow and verification status fields.
 * @returns {string} Escaped details markup; absent measurements remain unknown.
 */
function renderDashboardJobDetails(backup) {
  const growthClass = backup.growth_bytes == null ? 'neutral' : backup.growth_bytes > 0 ? 'positive' : 'negative';
  let checkStatus = backup.repository_check_status;
  if (checkStatus === 'ok' && isStaleDate(backup.repository_check_date)) checkStatus = 'overdue';
  const checkLabel = checkStatus ? repoCheckLabel({ ...backup, repository_check_status: checkStatus }) : dashboardT('dashboard.checkUnknown');
  const hasSizes = ['original_size', 'compressed_size', 'deduplicated_size', 'repository_size'].some((key) => Number(backup[key] || 0) > 0);
  const sizeFacts = hasSizes ? [
    [dashboardT('dashboard.deduplicated'), backup.deduplicated_size_formatted || '—', true],
    [dashboardT('dashboard.source'), backup.original_size_formatted || '—'],
    [dashboardT('dashboard.compressed'), backup.compressed_size_formatted || '—'],
    [dashboardT('dashboard.repository'), backup.repository_size_formatted || '—'],
  ] : [];
  const sizeValues = sizeFacts.map(([label, value, primary]) => `<div class="dashboard-fact-row${primary ? ' primary' : ''}"><b>${escHtml(label)}:</b><span>${escHtml(value)}</span></div>`).join('');
  const archive = backup.archive_name || backup.archive_prefix || '—';
  return `<div class="dashboard-job-details">
    <section><h3>${escHtml(dashboardT('dashboard.storageColumn'))}</h3><div class="dashboard-storage-facts">${sizeValues || `<span class="dashboard-cell-detail">${escHtml(dashboardT('dashboard.noSizeData'))}</span>`}<div class="dashboard-fact-row"><b>${escHtml(dashboardT('dashboard.weeklyGrowth'))}:</b><span class="dashboard-growth ${growthClass}">${escHtml(backup.growth_formatted || '—')}</span></div></div></section>
    <section><h3>${escHtml(dashboardT('dashboard.checkRestoreDetails'))}</h3><div class="dashboard-check-result"><b>${escHtml(dashboardT('dashboard.checkInLastRun'))}:</b><span>${escHtml(dashboardBorgCheckResult(backup))}</span></div>${renderDashboardRepositoryCheck(checkStatus, checkLabel, backup.repository_next_check)}${backup.repository_check_date ? `<span class="dashboard-cell-detail">${escHtml(dashboardT('dashboard.lastStoredCheck'))}: ${escHtml(dashboardAbsoluteTimestamp(backup.repository_check_date))}</span>` : ''}${renderDashboardRestoreVerificationBadge(backup) || `<span class="dashboard-cell-detail">${escHtml(dashboardT('dashboard.unknown'))}</span>`}</section>
    <div class="dashboard-details-archive"><span>${escHtml(dashboardT('dashboard.archiveLabel'))}:</span> <code>${escHtml(archive)}</code>${backup.timestamp ? `<span class="dashboard-cell-detail">${escHtml(dashboardT('dashboard.lastRunTime'))}: ${escHtml(dashboardAbsoluteTimestamp(backup.timestamp))}</span>` : ''}${backup.last_successful_backup?.timestamp ? `<span class="dashboard-cell-detail">${escHtml(dashboardT('dashboard.lastSuccessfulBackup'))}: ${escHtml(dashboardAbsoluteTimestamp(backup.last_successful_backup.timestamp))}</span>` : ''}</div>
  </div>`;
}

function renderDashboardRepositoryCheck(status, label, nextCheck) {
  if (status === 'overdue') {
    return `<span class="dashboard-cell-detail repo-check overdue">
      <span class="dashboard-check-line">${repoCheckIcon(status)} ${escHtml(dashboardT('dashboard.checkOverdueShort'))}</span>
      <span class="dashboard-check-date">${escHtml(dashboardT('dashboard.nextCheck', { date: nextCheck || '—' }))}</span>
    </span>`;
  }
  return `<span class="dashboard-cell-detail repo-check ${escHtml(status || 'unknown')}"><span class="dashboard-check-line">${repoCheckIcon(status)} ${escHtml(label)}</span></span>`;
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
  showMsg('status-message', 'error', msg);
}

function showEmpty(html) {
  const el = document.getElementById('status-message');
  if (!el) return;
  el.className = 'status-message empty-state';
  el.innerHTML = html;
}

function hideMessage() {
  hideEl('status-message');
}

window.addEventListener?.('bbui:language-changed', () => {
  const coreState = window.BBUI?.core?.state;
  if (coreState?.data) renderDashboard(coreState.data, dashboardSystemHealth);
  updateRefreshLabel();
  window.BBUI?.core?.updateDataDirWarning?.();
});

let dashboardPeriod = 30;
let dashboardOverview = null;
let dashboardOverviewRequest = 0;
let dashboardOverviewFailed = false;
let dashboardLiveRuns = null;

/**
 * Render location-scoped facts, omitting empty locations and resetting removed selections.
 * Host resource measurements retain global scope; existing chart/table nodes are reconciled.
 */
function renderManagementDashboard(backups) {
  const locations = DASHBOARD_LOCATION_ORDER.filter(location => backups.some(b => dashboardLocationKey(b) === location));
  if (dashboardSelectedLocation !== 'all' && !locations.includes(dashboardSelectedLocation)) dashboardSelectedLocation = 'all';
  const focused = document.activeElement;
  const focusData = focused?.dataset?.dashboardJobs !== undefined ? {...focused.dataset} : null;
  const rows = backups.filter(b => dashboardSelectedLocation === 'all' || dashboardLocationKey(b) === dashboardSelectedLocation);
  renderSummaryBar(rows);
  renderRestoreVerificationSummary(rows);
  renderManagementAttention(rows);
  renderManagementLocations(rows);
  renderDashboardActiveRuns(dashboardLiveRuns);
  renderDashboardTrends();
  if (focusData) Array.from(document.querySelectorAll('[data-dashboard-jobs]')).find(button => button.dataset.dashboardJobs === focusData.dashboardJobs && button.dataset.location === focusData.location)?.focus({preventScroll:true});
  const filter = document.getElementById('dashboard-location-filter');
  if (filter) {
    patchJobMarkup(filter, ['all', ...locations].map(location => `<option id="dashboard-filter-${location}" value="${location}">${escHtml(dashboardLocationLabel(location))}</option>`).join(''));
    filter.value = dashboardSelectedLocation;
    filter.onchange = () => {
      dashboardSelectedLocation = filter.value;
      renderDashboard(window.BBUI.core.state.data, dashboardSystemHealth);
      refreshDashboardOverview();
    };
  }
  const period = document.getElementById('dashboard-period');
  if (period) {
    period.value = String(dashboardPeriod);
    period.onchange = () => { dashboardPeriod = Number(period.value); refreshDashboardOverview(); };
  }
  const page = document.getElementById('page-dashboard');
  if (page) page.onclick = event => {
    const button = event.target.closest('[data-dashboard-jobs]');
    if (button) openJobsStatus(button.dataset.dashboardJobs, button.dataset.location || dashboardSelectedLocation);
    const navigation = event.target.closest('[data-dashboard-page]');
    if (navigation) window.BBUI.core.navigate(navigation.dataset.dashboardPage);
  };
}

/**
 * Render a compact attention strip; expand full saved messages and job links on demand.
 * Preserve the disclosure state and focused controls during background refreshes.
 * @param {object[]} rows Status rows scoped to the selected location.
 */
function renderManagementAttention(rows) {
  const el = document.getElementById('dashboard-attention');
  if (!el) return;
  const items = dashboardAttentionItems(rows);
  const first = items[0];
  el.hidden = false;
  const open = el.querySelector('details')?.open || false;
  patchJobMarkup(el, items.length ? `<details class="dashboard-attention-disclosure ${first.cls}"${open ? ' open' : ''}>
    <summary id="dashboard-attention-toggle"><span class="dashboard-attention-icon" aria-hidden="true">${iconWarn()}</span>
      <strong>${escHtml(dashboardT('management.attention'))} · ${items.length}</strong>
      <span class="dashboard-attention-preview">${escHtml(first.backup.name || first.backup.display_name || first.backup.key)} · <span class="dashboard-attention-label">${escHtml(first.label)}</span></span>
      <span class="dashboard-attention-action">${escHtml(dashboardT('dashboard.viewDetails'))}<span class="dashboard-details-chevron" aria-hidden="true">›</span></span></summary>
    <ul>${items.map(item => `<li class="${item.cls}"><span class="dashboard-attention-icon" aria-hidden="true">${iconWarn()}</span><div><strong>${escHtml(item.backup.name || item.backup.display_name || item.backup.key)} · ${escHtml(dashboardLocationLabel(dashboardLocationKey(item.backup)))}</strong><span class="dashboard-attention-label">${escHtml(item.label)}</span><p>${escHtml(item.message)}</p></div><button class="btn btn-secondary btn-sm" data-dashboard-jobs="${escHtml(item.backup.key)}" data-location="${escHtml(dashboardLocationKey(item.backup))}">${escHtml(dashboardT('management.openJob'))}</button></li>`).join('')}</ul></details>`
    : `<div class="dashboard-attention-clear"><span class="dashboard-attention-icon" aria-hidden="true">${iconCheck()}</span><strong>${escHtml(dashboardT('management.attention'))}</strong><span>${escHtml(dashboardT('management.noProblems'))}</span></div>`);
}

/** Reconcile current totals for populated locations, preserving rows and focused actions. */
function renderManagementLocations(rows) {
  const el = document.getElementById('dashboard-locations');
  if (!el) return;
  const locations = (dashboardSelectedLocation === 'all' ? DASHBOARD_LOCATION_ORDER : [dashboardSelectedLocation])
    .filter(location => rows.some(b => dashboardLocationKey(b) === location));
  patchJobMarkup(el, `<table class="ui-table management-locations"><thead><tr>${['dashboard.locations','management.jobs','dashboard.successful','management.problems','dashboard.restoreCoverage','management.actions'].map(k => `<th>${escHtml(dashboardT(k))}</th>`).join('')}</tr></thead><tbody>${locations.map(location => {
    const jobs = rows.filter(b => dashboardLocationKey(b) === location);
    const summary = dashboardBackupSummary(jobs);
    const problems = new Set(dashboardAttentionItems(jobs).map(item => item.backup.key)).size;
    const verified = jobs.filter(b => b.restore_verification_status === 'verified').length;
    return `<tr id="dashboard-location-${location}"><td><span class="management-location-name"><span class="location-nav-glyph ${location}">${dashboardLocationGlyph(location)}</span>${escHtml(dashboardLocationLabel(location))}</span></td><td>${jobs.length}</td><td>${summary.counts.success}/${jobs.length}</td><td>${problems}</td><td><span class="management-location-coverage"><progress max="${jobs.length}" value="${verified}" aria-label="${escHtml(dashboardT('dashboard.restoreCoverageDescription', {count: verified, total: jobs.length}))}"></progress><span>${verified}/${jobs.length}</span></span></td><td><button class="btn btn-secondary btn-sm" data-dashboard-jobs="" data-location="${location}">${escHtml(dashboardT('management.openJobs'))}</button></td></tr>`;
  }).join('')}</tbody></table>`);
}

/** Render live runs with explicit queue states and a location-filtered summary.
 * Unknown metadata and unavailable telemetry never imply waiting or zero runs. */
function renderDashboardActiveRuns(runs) {
  dashboardLiveRuns = runs;
  const el = document.getElementById('dashboard-active-runs');
  if (!el) return;
  const backups = window.BBUI.core.state.data?.backups || [];
  const visible = runs?.filter(run => dashboardSelectedLocation === 'all' || backups.some(b => b.key === run.job_key && dashboardLocationKey(b) === dashboardSelectedLocation));
  el.innerHTML = `<div class="dashboard-summary-primary"><strong>${visible?.length ?? '—'}</strong><span>${escHtml(dashboardT(runs === null ? 'resources.unavailable' : 'management.activeRuns'))}</span></div>
    ${visible?.length ? `<p class="management-activity-summary">${escHtml(runActivitySummary(visible))}</p>` : ''}
    <div class="management-active-list">${visible?.length ? visible.map(run => {
      const job = backups.find(b => b.key === run.job_key);
      const test = run.operation === 'restore_test';
      const activity = runActivityState(run);
      return `<button class="dashboard-details-toggle" ${test ? 'data-dashboard-page="restore-tests"' : run.operation === 'backup' ? `data-dashboard-jobs="${escHtml(run.job_key || '')}"` : 'data-dashboard-page="restore"'}>${escHtml(job?.name || job?.display_name || run.job_key || '—')} · ${escHtml(dashboardT(test ? 'management.restoreTest' : run.operation === 'backup' ? 'management.backup' : 'management.restore'))}${test ? ` <span class="management-run-state ${activity}">${escHtml(dashboardT(`resources.state${capitalize(activity)}`))}</span>` : ''}</button>`;
    }).join('') : `<span>${escHtml(dashboardT(runs === null ? 'management.liveUnknown' : 'management.noActive'))}</span>`}</div>`;
}

/**
 * Refresh saved-report aggregates without clearing the currently matching chart.
 * New scopes show loading; failed requests clear stale data; superseded responses are ignored.
 */
async function refreshDashboardOverview() {
  const request = ++dashboardOverviewRequest;
  dashboardOverviewFailed = false;
  renderDashboardTrends();
  try {
    const response = await fetch(`/api/reports/overview?days=${dashboardPeriod}&location=${encodeURIComponent(dashboardSelectedLocation)}`);
    if (!response.ok) throw new Error('Overview unavailable');
    const data = await response.json();
    if (request !== dashboardOverviewRequest) return;
    dashboardOverview = data;
  } catch (_) {
    if (request !== dashboardOverviewRequest) return;
    dashboardOverview = null;
    dashboardOverviewFailed = true;
  }
  renderDashboardTrends();
}

/** Format real byte measurements for the current locale; absent data remains unknown. */
function dashboardMetricBytes(bytes) {
  if (bytes == null) return '—';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
  let unit = 0;
  while (bytes >= 1024 && unit < units.length - 1) { bytes /= 1024; unit++; }
  return `${new Intl.NumberFormat(window.BBUI.components.i18n.getLanguage(), {maximumFractionDigits: 1}).format(bytes)} ${units[unit]}`;
}

/**
 * Render keyboard/touch-accessible chart guidance, retaining its disclosure on refresh.
 * @param {string} id Stable disclosure ID.
 * @param {string} titleKey Translation key for the chart title.
 * @param {string} hintKey Translation key for the calculation or measurement explanation.
 * @returns {string} Escaped disclosure markup; opening it expands normal document flow.
 */
function dashboardChartHeading(id, titleKey, hintKey) {
  const open = document.getElementById(id)?.open || false;
  return `<details id="${id}" class="management-chart-info"${open ? ' open' : ''}><summary aria-label="${escHtml(dashboardT(titleKey))} · ${escHtml(dashboardT('dashboard.viewDetails'))}"><h3>${escHtml(dashboardT(titleKey))}</h3><span aria-hidden="true">ⓘ</span></summary><p class="management-note">${escHtml(dashboardT(hintKey))}</p></details>`;
}

/** Reconcile daily outcomes and measured storage in place, retaining labels and data gaps. */
function renderDashboardTrends() {
  const el = document.getElementById('dashboard-trends');
  if (!el) return;
  const data = dashboardOverview;
  if (!data || data.location !== dashboardSelectedLocation || data.days !== dashboardPeriod) {
    patchJobMarkup(el, `<p class="management-note">${escHtml(dashboardT(dashboardOverviewFailed ? 'management.historyUnavailable' : 'dashboard.loading'))}</p>`);
    return;
  }
  const outcomes = ['success','warning','error','skipped','cancelled','unknown'];
  const labels = {success:'dashboard.successful',warning:'dashboard.warnings',error:'dashboard.errors',skipped:'dashboard.skipped',cancelled:'jobs.statusCancelled',unknown:'dashboard.unknown'};
  const maxRuns = Math.max(1, ...data.daily.map(p => outcomes.reduce((n,k) => n + p[k], 0)));
  const last = data.daily.at(-1);
  const complete = p => p.measured_repositories === data.repository_count && data.repository_count > 0 && !data.unassigned_jobs;
  const valid = data.daily.filter(complete);
  const maxBytes = Math.max(1, ...valid.map(p => p.repository_bytes));
  const minBytes = Math.min(...valid.map(p => p.repository_bytes));
  const singlePoint = valid.length === 1 ? data.daily.findIndex(complete) : -1;
  let previous = false;
  const path = data.daily.map((p,i) => {
    if (!complete(p)) { previous = false; return ''; }
    const x = 8 + i * 584 / Math.max(1, data.daily.length - 1);
    const y = 142 - p.repository_bytes / maxBytes * 126;
    const segment = `${previous ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
    previous = true;
    return segment;
  }).join(' ');
  const rate = data.success_rate == null ? '—' : `${new Intl.NumberFormat(window.BBUI.components.i18n.getLanguage(), {maximumFractionDigits:1}).format(data.success_rate)} %`;
  const range = `${data.from} – ${data.to}`;
  patchJobMarkup(el, `<div class="management-trends-grid"><section>${dashboardChartHeading('dashboard-rate-info', 'management.runHistory', 'management.rateHint')}<div class="management-metric"><strong>${rate}</strong><span>${escHtml(dashboardT('management.successRate'))}</span></div>
    <p class="management-note">${escHtml(dashboardT('management.runCount', {count:data.run_count}))} · ${escHtml(range)}</p>
    <div class="management-bars" role="img" aria-label="${escHtml(dashboardT('management.runCount', {count:data.run_count}))}">${data.daily.map(p => `<div class="management-bar" id="dashboard-day-${escHtml(p.date)}" title="${escHtml(p.date + ': ' + outcomes.map(k => `${p[k]} ${dashboardT(labels[k])}`).join(' · '))}">${outcomes.map(k => `<span class="${k}" style="height:${p[k]/maxRuns*100}%"></span>`).join('')}</div>`).join('')}</div>
    <div class="management-axis"><span>${escHtml(data.from)}</span><span>${escHtml(data.to)}</span></div>
    <div class="management-legend">${outcomes.map(k => `<span class="${k}"><i></i>${data.counts[k]} ${escHtml(dashboardT(labels[k]))}</span>`).join('')}</div></section>
    <section>${dashboardChartHeading('dashboard-storage-info', 'management.repositoryTrend', 'management.repositoryHint')}<div class="management-metric"><strong>${escHtml(complete(last) ? dashboardMetricBytes(last.repository_bytes) : '—')}</strong><span>${escHtml(dashboardT('management.measuredRepositories', {count:last.measured_repositories,total:data.repository_count}))}</span></div>
    <p class="management-note">${escHtml(dashboardT('management.lastMeasurement'))}: ${escHtml(data.repository_last_sample ? dashboardAbsoluteTimestamp(data.repository_last_sample) : '—')}</p>
    ${valid.length ? `<svg class="management-storage-chart" viewBox="0 0 600 150" preserveAspectRatio="none" role="img" aria-label="${escHtml(dashboardT('management.storageRange', {min:dashboardMetricBytes(minBytes),max:dashboardMetricBytes(maxBytes)}))}"><path d="M8 142H592" class="management-chart-axis"/><path d="${path}" class="management-chart-line"/>${singlePoint >= 0 ? `<circle cx="${8 + singlePoint * 584 / Math.max(1, data.daily.length - 1)}" cy="${142 - valid[0].repository_bytes / maxBytes * 126}" r="3" fill="currentColor"/>` : ''}</svg>` : `<div class="management-no-chart">${escHtml(dashboardT('management.noMeasurements'))}</div>`}
    <div class="management-axis"><span>${escHtml(data.from)}</span><span>${escHtml(data.to)}</span></div></section></div>`);
}
