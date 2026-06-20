'use strict';

// ── Core State ────────────────────────────────────────────────────────────────

const state = {
  currentPage: 'dashboard',
  data: null,
  lastRefresh: null,
  refreshTimer: null,
  REFRESH_INTERVAL_MS: 60_000,
  currentRole: 'admin',
};

let appCheckIntervalDays = 30;
let schedulesData = {}; // job_key → { cron, enabled }
let globalDataDirReady = true;
let setupRequired = false;
let setupStatusCache = { ts: 0, data: null };
let sidebarHealthCache = { ts: 0, data: null };
const coreActions = Object.create(null);

function isStaleDate(dateStr) {
  if (!dateStr) return false;
  const d = new Date(dateStr.replace(' ', 'T'));
  if (isNaN(d)) return false;
  return (Date.now() - d.getTime()) > appCheckIntervalDays * 86400000;
}

// ── Mobile Navigation ────────────────────────────────────────────────────────

function toggleMobileNav() {
  document.querySelector('.sidebar').classList.toggle('mobile-open');
  document.getElementById('mobile-backdrop').classList.toggle('visible');
}

function closeMobileNav() {
  document.querySelector('.sidebar').classList.remove('mobile-open');
  document.getElementById('mobile-backdrop').classList.remove('visible');
}

function setCoreAction(name, fn) {
  const key = String(name || '').trim();
  if (!key) return;
  if (typeof fn === 'function') {
    coreActions[key] = fn;
  } else {
    delete coreActions[key];
  }
}

function runCoreAction(name) {
  const fn = coreActions[String(name || '').trim()];
  if (typeof fn !== 'function') return;
  fn();
}

function getCurrentPage() {
  return state.currentPage;
}

// ── Navigation ───────────────────────────────────────────────────────────────

function navigate(page) {
  if (page === 'settings' && state.currentRole !== 'admin') {
    page = 'dashboard';
  }
  if (setupRequired && page !== 'settings') {
    page = 'settings';
  }

  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const pageEl = document.getElementById(`page-${page}`);
  const navEl  = document.querySelector(`.nav-item[data-page="${page}"]`);
  if (pageEl) pageEl.classList.add('active');
  if (navEl)  navEl.classList.add('active');
  state.currentPage = page;
  closeMobileNav();

  if (page === 'dashboard') runCoreAction('refreshStatus');
  if (page === 'jobs') {
    runCoreAction('refreshJobs');
    runCoreAction('startJobsPolling');
  } else {
    runCoreAction('stopJobsPolling');
  }
  if (page === 'restore') {
    runCoreAction('restoreInit');
  }
  if (page === 'restore-tests') {
    runCoreAction('refreshRestoreTests');
    runCoreAction('updateRTScheduleBtn');
  } else {
    runCoreAction('stopRTPolling');
  }
  if (page === 'storage')  runCoreAction('refreshStorage');
  if (page === 'berichte') runCoreAction('berichtInit');
  if (page === 'settings') runCoreAction('refreshSettings');
  if (page === 'history')  runCoreAction('refreshHistory');
  if (page === 'hilfe')    runCoreAction('helpInit');
  updateSidebarSystemHealth();
}

function _systemHealthAttentionCount(data) {
  const checks = data?.checks || {};
  const systemFailed = [
    checks.data_root_ok,
    checks.jobs_path_ok,
    checks.secrets_path_ok,
    checks.mount_bin_ok,
    checks.cifs_supported,
    checks.secrets_permissions_ok,
  ].filter((ok) => !ok).length;
  const migrationFailed = String(data?.migration_summary?.state || '').trim() === 'Fehlgeschlagen' ? 1 : 0;
  const registrySummary = data?.migration_registry?.summary && typeof data.migration_registry.summary === 'object'
    ? data.migration_registry.summary
    : {};
  const registryAttention = Number(registrySummary.pending || 0)
    + Number(registrySummary.failed || 0)
    + Number(registrySummary.deprecated_key_candidates || 0);
  const jobSummary = data?.job_health?.summary && typeof data.job_health.summary === 'object'
    ? data.job_health.summary
    : {};
  const jobFailed = Number(jobSummary.failed || 0);
  return systemFailed + migrationFailed + registryAttention + jobFailed;
}

function _setSidebarSystemHealth(tone, text, title = '') {
  const el = document.getElementById('sidebar-system-health');
  if (!el) return;
  const label = el.querySelector('.sidebar-health-detail');
  el.className = `sidebar-health-indicator ${tone}`;
  el.title = title || text;
  if (label) label.textContent = text;
}

function _sidebarTranslation(key, params = {}) {
  return window.BBUI?.components?.i18n?.t?.(key, params) || key;
}

async function updateSidebarSystemHealth(force = false) {
  const el = document.getElementById('sidebar-system-health');
  if (!el || state.currentRole !== 'admin') return;
  try {
    const now = Date.now();
    let data = sidebarHealthCache.data;
    if (force || !data || (now - sidebarHealthCache.ts) > 30_000) {
      const res = await fetch('/api/system-health', { credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
      sidebarHealthCache = { ts: now, data };
    }
    const count = _systemHealthAttentionCount(data);
    if (count > 0) {
      _setSidebarSystemHealth(
        'warn',
        _sidebarTranslation('sidebar.healthOpen', { count }),
        _sidebarTranslation('sidebar.healthAttention'),
      );
    } else {
      _setSidebarSystemHealth(
        'ok',
        _sidebarTranslation('sidebar.healthOk'),
        _sidebarTranslation('sidebar.healthOkTitle'),
      );
    }
  } catch {
    _setSidebarSystemHealth(
      'unknown',
      _sidebarTranslation('sidebar.unknown'),
      _sidebarTranslation('sidebar.healthUnavailable'),
    );
  }
}

async function updateDataDirWarning() {
  const dashEl = document.getElementById('dashboard-data-dir-warning');
  const dashSetupEl = document.getElementById('dashboard-system-warning');
  const jobsEl = document.getElementById('jobs-data-dir-warning');
  const settingsEl = document.getElementById('settings-setup-warning');
  if (!dashEl && !jobsEl && !dashSetupEl && !settingsEl) return;
  try {
    const now = Date.now();
    let data = setupStatusCache.data;
    if (!data || (now - setupStatusCache.ts) > 10_000) {
      const res = await fetch('/api/setup-status', { credentials: 'include' });
      if (!res.ok) return;
      data = await res.json();
      setupStatusCache = { ts: now, data };
    }
    const missing = !Boolean(data?.global_data_dir_set);
    const ready = Boolean(data?.ready);
    const firstErr = String(data?.validation?.errors?.[0]?.message || '');
    const firstErrSafe = escHtml(firstErr);
    setupRequired = !ready;
    globalDataDirReady = ready;
    const i18n = window.BBUI?.components?.i18n;
    const html = !ready
      ? (i18n
        ? `${i18n.t(missing ? 'settings.setup.dataDirMissing' : 'settings.setup.configIncomplete')} ${i18n.t('settings.setup.checkPrefix')} <a href="#" data-core-action="goto-settings">${i18n.t('nav.settings')}</a> ${i18n.t('settings.setup.checkSuffix')}${firstErrSafe ? ` ${i18n.t('settings.setup.detail', { message: firstErrSafe })}` : ''}`
        : '')
      : '';
    const dashboardHtml = !ready && i18n
      ? `${i18n.t(missing ? 'dashboard.dataDirMissing' : 'dashboard.configIncomplete')} ${i18n.t('dashboard.checkSettingsPrefix')} <a href="#" data-core-action="goto-settings">${i18n.t('nav.settings')}</a> ${i18n.t('dashboard.checkSettingsSuffix')}${firstErrSafe ? ` ${i18n.t('dashboard.detailHint', { message: firstErrSafe })}` : ''}`
      : html;
    for (const el of [dashEl, jobsEl]) {
      if (!el) continue;
      if (!ready) {
        el.innerHTML = el === dashEl ? dashboardHtml : html;
        el.className = 'status-message warning-state';
      } else {
        el.className = 'status-message hidden';
      }
    }
    applySetupNavLock();
    if (dashSetupEl) {
      if (!ready) {
        dashSetupEl.className = 'status-message warning-state';
        dashSetupEl.textContent = i18n
          ? (missing
            ? i18n.t('dashboard.firstConfigRequired')
            : i18n.t('dashboard.configCheckFailed', {
              message: firstErr || i18n.t('dashboard.checkSettingsFallback'),
            }))
          : '';
      } else {
        dashSetupEl.className = 'status-message hidden';
      }
    }
    if (settingsEl) {
      if (!ready) {
        settingsEl.className = 'status-message warning-state';
        settingsEl.textContent = i18n
          ? (missing
            ? i18n.t('settings.setup.dataDirSetFirst')
            : i18n.t('settings.setup.configError', {
              message: firstErr || i18n.t('settings.setup.checkFallback'),
            }))
          : '';
      } else {
        settingsEl.className = 'status-message hidden';
      }
    }
    applyDataDirActionGates();
  } catch {
    // ignore
  }
}

function applySetupNavLock() {
  document.querySelectorAll('.nav-item').forEach((el) => {
    const page = el.getAttribute('data-page');
    const locked = setupRequired && page !== 'settings';
    el.classList.toggle('disabled', locked);
  });
}

function applyDataDirActionGates() {
  const disabled = !globalDataDirReady;
  const hint = disabled
    ? (window.BBUI?.components?.i18n?.t?.('settings.setup.actionHint') || '')
    : '';
  for (const id of ['check-run-btn', 'rt-run-btn']) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.disabled = disabled;
    el.title = hint;
  }
}

function invalidateSetupStatusCache() {
  setupStatusCache = { ts: 0, data: null };
}

// ── D2: Namespace Registrierung (kompatibel) ───────────────────────────────

window.BBUI = window.BBUI || {};
window.BBUI.core = window.BBUI.core || {};

window.BBUI.core.state = state;
window.BBUI.core.setCurrentRole = (role) => { state.currentRole = String(role || 'viewer').toLowerCase(); };
window.BBUI.core.getCurrentRole = () => state.currentRole;
window.BBUI.core.getAppCheckIntervalDays = () => appCheckIntervalDays;
window.BBUI.core.setAppCheckIntervalDays = (days) => { appCheckIntervalDays = days; };
window.BBUI.core.getSchedulesData = () => schedulesData;
window.BBUI.core.setSchedulesData = (next) => { schedulesData = next; };
window.BBUI.core.isGlobalDataDirReady = () => globalDataDirReady;
window.BBUI.core.isSetupRequired = () => setupRequired;

window.BBUI.core.isStaleDate = isStaleDate;
window.BBUI.core.toggleMobileNav = toggleMobileNav;
window.BBUI.core.closeMobileNav = closeMobileNav;
window.BBUI.core.setAction = setCoreAction;
window.BBUI.core.runAction = runCoreAction;
window.BBUI.core.navigate = navigate;
window.BBUI.core.getCurrentPage = getCurrentPage;
window.BBUI.core.updateDataDirWarning = updateDataDirWarning;
window.BBUI.core.applySetupNavLock = applySetupNavLock;
window.BBUI.core.applyDataDirActionGates = applyDataDirActionGates;
window.BBUI.core.invalidateSetupStatusCache = invalidateSetupStatusCache;
window.BBUI.core.updateSidebarSystemHealth = updateSidebarSystemHealth;

window.addEventListener('bbui:language-changed', () => {
  updateSidebarSystemHealth(true);
  updateDataDirWarning();
});
