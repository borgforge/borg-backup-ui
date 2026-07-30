'use strict';

(function initSetupWizard() {
  window.BBUI = window.BBUI || {};
  const namespace = window.BBUI.setupWizard || {};
  let currentStatus = null;
  let returnContext = null;

  function setupT(key, params = {}) {
    return window.BBUI?.components?.i18n?.t?.(`setupWizard.${key}`, params) || `setupWizard.${key}`;
  }

  function core() {
    return window.BBUI?.core;
  }

  async function fetchStatus(force = false) {
    if (core()?.fetchSetupStatus) {
      currentStatus = await core().fetchSetupStatus(force);
      namespace.currentStatus = currentStatus;
      return currentStatus;
    }
    const res = await fetch('/api/setup-status', { credentials: 'include' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    currentStatus = await res.json();
    namespace.currentStatus = currentStatus;
    return currentStatus;
  }

  function milestone(status, key) {
    return (status?.setup?.milestones || []).find((row) => row.key === key) || {};
  }

  function setupStatusIcon(status) {
    const icons = {
      neutral: '<circle cx="12" cy="12" r="8.5"/><path d="M8 12h8"/>',
      success: '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.5 2.2 2.2 4.8-5.4"/>',
      warning: '<path d="M10.3 4.4a2 2 0 0 1 3.4 0l7.4 12.8a2 2 0 0 1-1.7 3H4.6a2 2 0 0 1-1.7-3z"/><path d="M12 8.8v4.8"/><path d="M12 17h.01"/>',
    };
    return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${icons[status] || icons.neutral}</svg>`;
  }

  function stepRow(status, key, actionHtml = '') {
    const item = milestone(status, key);
    const complete = !!item.complete;
    return `<div class="setup-wizard-step-row ${complete ? 'complete' : 'pending'}">
      <span class="setup-wizard-step-state" aria-hidden="true">${setupStatusIcon(complete ? 'success' : 'warning')}</span>
      <div class="setup-wizard-step-copy">
        <strong>${escHtml(setupT(`steps.${key}.title`))}</strong>
        <small>${escHtml(setupT(`steps.${key}.${complete ? 'complete' : 'pending'}`, { count: Number(item.count || 0) }))}</small>
      </div>
      <div class="setup-wizard-step-actions">${actionHtml}</div>
    </div>`;
  }

  function renderRequired(status) {
    const suggestion = String(status?.global_data_dir || status?.global_data_dir_suggestion || '/mnt/user/borg-backup-ui');
    return `<div class="setup-wizard-intro">
        <div class="setup-wizard-kicker">${escHtml(setupT('stepCounter', { step: 1, total: 5 }))}</div>
        <h4>${escHtml(setupT('dataDirTitle'))}</h4>
        <p>${escHtml(setupT('dataDirText'))}</p>
      </div>
      <div id="setup-wizard-message" class="status-message hidden"></div>
      <div class="form-group">
        <label class="form-label form-label-required" for="setup-wizard-data-dir-input">
          <span class="form-required-marker" aria-hidden="true">*</span>${escHtml(setupT('dataDirLabel'))}
        </label>
        <input id="setup-wizard-data-dir-input" class="form-input mono" type="text" value="${escAttr(suggestion)}" placeholder="/mnt/user/borg-backup-ui">
      </div>
      <div class="setup-wizard-required-note">${escHtml(setupT('dataDirRequiredNote'))}</div>`;
  }

  function renderOptional(status) {
    const storageActions = `<button class="btn btn-secondary btn-sm" data-setup-wizard-action="open-settings-tab" data-settings-tab-target="local">${escHtml(setupT('actions.localStorage'))}</button>
      <button class="btn btn-secondary btn-sm" data-setup-wizard-action="open-settings-tab" data-settings-tab-target="usb">${escHtml(setupT('actions.usbStorage'))}</button>
      <button class="btn btn-secondary btn-sm" data-setup-wizard-action="open-settings-tab" data-settings-tab-target="smb">${escHtml(setupT('actions.smbStorage'))}</button>
      <button class="btn btn-secondary btn-sm" data-setup-wizard-action="open-settings-tab" data-settings-tab-target="storagebox">${escHtml(setupT('actions.sshStorage'))}</button>`;
    return `<div class="setup-wizard-intro">
        <div class="setup-wizard-kicker">${escHtml(setupT('guidedSetup'))}</div>
        <h4>${escHtml(setupT('optionalTitle'))}</h4>
        <p>${escHtml(setupT('optionalText'))}</p>
      </div>
      <div class="setup-wizard-checklist">
        ${stepRow(status, 'data_dir')}
        ${stepRow(status, 'storage', storageActions)}
        ${stepRow(status, 'repository', `<button class="btn btn-primary btn-sm" data-setup-wizard-action="open-repository-manager">${escHtml(setupT('actions.repository'))}</button>`)}
        ${stepRow(status, 'job', `<button class="btn btn-primary btn-sm" data-setup-wizard-action="open-job-wizard">${escHtml(setupT('actions.job'))}</button>`)}
        <div class="setup-wizard-step-row neutral">
          <span class="setup-wizard-step-state" aria-hidden="true">${setupStatusIcon('neutral')}</span>
          <div class="setup-wizard-step-copy">
            <strong>${escHtml(setupT('steps.optional.title'))}</strong>
            <small>${escHtml(setupT('steps.optional.pending'))}</small>
          </div>
          <div class="setup-wizard-step-actions">
            <button class="btn btn-secondary btn-sm" data-setup-wizard-action="open-settings-tab" data-settings-tab-target="restore">${escHtml(setupT('actions.restore'))}</button>
            <button class="btn btn-secondary btn-sm" data-setup-wizard-action="open-settings-tab" data-settings-tab-target="notifications">${escHtml(setupT('actions.notifications'))}</button>
          </div>
        </div>
      </div>`;
  }

  function renderModal(status) {
    const body = document.getElementById('setup-wizard-body');
    if (!body) return;
    const required = !status?.global_data_dir_set;
    body.innerHTML = required ? renderRequired(status) : renderOptional(status);
    document.getElementById('setup-wizard-save-dir-btn')?.classList.toggle('hidden', !required);
    document.getElementById('setup-wizard-skip-btn')?.classList.toggle('hidden', required);
    document.getElementById('setup-wizard-finish-btn')?.classList.toggle('hidden', required);
    document.getElementById('setup-wizard-close-btn')?.classList.toggle('hidden', required);
  }

  function open(status = null) {
    const modal = document.getElementById('setup-wizard-modal');
    if (!modal) return;
    currentStatus = status || currentStatus || {};
    namespace.currentStatus = currentStatus;
    renderModal(currentStatus);
    modal.classList.remove('hidden');
  }

  function close() {
    document.getElementById('setup-wizard-modal')?.classList.add('hidden');
  }

  async function maybeOpen(forceRequired = false) {
    try {
      const status = await fetchStatus(true);
      if (!status?.global_data_dir_set) {
        if (forceRequired) open(status);
        return status;
      }
      if (status?.setup?.show_optional_wizard) open(status);
      return status;
    } catch (_) {
      return null;
    }
  }

  async function saveDataDir() {
    const input = document.getElementById('setup-wizard-data-dir-input');
    const btn = document.getElementById('setup-wizard-save-dir-btn');
    const value = String(input?.value || '').trim();
    if (!value) {
      showMsg('setup-wizard-message', 'error', setupT('dataDirRequired'));
      return;
    }
    btn?.classList.add('loading');
    hideEl('setup-wizard-message');
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates: { GLOBAL_DATA_DIR: value }, profile_updates: {} }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(apiErrorMessage(data, res.status));
      core()?.invalidateSetupStatusCache?.();
      currentStatus = await fetchStatus(true);
      core()?.updateDataDirWarning?.();
      renderModal(currentStatus);
      renderDashboardPanel(currentStatus);
    } catch (err) {
      showMsg('setup-wizard-message', 'error', setupT('saveFailed', { message: err.message }));
    } finally {
      btn?.classList.remove('loading');
    }
  }

  async function dismissOptional() {
    try {
      await fetch('/api/setup-wizard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'dismiss_optional' }),
      });
      core()?.invalidateSetupStatusCache?.();
    } catch (_) {
      // The dashboard action panel remains visible even if persisting fails.
    }
    close();
    renderDashboardPanel(await fetchStatus(true));
  }

  function armReturn(step) {
    returnContext = {
      step: String(step || ''),
      armedAt: Date.now(),
    };
    namespace.returnContext = returnContext;
  }

  function clearReturn() {
    returnContext = null;
    namespace.returnContext = null;
  }

  function shouldReturn(step) {
    if (!returnContext) return false;
    if (step && returnContext.step !== step) return false;
    const ageMs = Date.now() - Number(returnContext.armedAt || 0);
    return ageMs >= 0 && ageMs < 30 * 60 * 1000;
  }

  async function resumeAfterExternalSave(step = '') {
    if (!shouldReturn(String(step || ''))) return false;
    clearReturn();
    try {
      core()?.invalidateSetupStatusCache?.();
      const status = await fetchStatus(true);
      renderDashboardPanel(status);
      open(status);
      return true;
    } catch (_) {
      return false;
    }
  }

  function navigateSettingsTab(tab) {
    if (['local', 'usb', 'smb', 'storagebox'].includes(String(tab || ''))) armReturn('storage');
    close();
    core()?.navigate?.('settings');
    window.setTimeout(() => {
      if (typeof activateSettingsTab === 'function') activateSettingsTab(tab);
    }, 80);
  }

  function openRepositoryFlow() {
    armReturn('repository');
    close();
    core()?.navigate?.('storage');
    window.setTimeout(() => {
      if (typeof openRepositoryManager === 'function') openRepositoryManager({ forceRefresh: true });
    }, 120);
  }

  function openJobFlow() {
    armReturn('job');
    close();
    core()?.navigate?.('jobs');
    window.setTimeout(() => {
      if (typeof openWizard === 'function') openWizard();
    }, 120);
  }

  function requireAdmin(action) {
    if (!['save-data-dir', 'open-settings-tab', 'open-repository-manager', 'open-job-wizard'].includes(action)) return true;
    if (String(core()?.getCurrentRole?.() || 'viewer').toLowerCase() === 'admin') return true;
    const message = window.BBUI?.components?.i18n?.t?.('permissions.viewerActionDenied') || 'Viewer: read only.';
    showMsg(document.getElementById('setup-wizard-message') ? 'setup-wizard-message' : 'status-message', 'warning', message);
    return false;
  }

  function renderDashboardPanel(status = currentStatus) {
    const el = document.getElementById('dashboard-setup-actions');
    if (!el) return;
    const data = status || {};
    const setup = data.setup || {};
    const missing = Array.isArray(setup.missing_optional) ? setup.missing_optional : [];
    if (!data.global_data_dir_set) {
      el.className = 'setup-action-panel warning';
      el.innerHTML = `<div><strong>${escHtml(setupT(['dashboard', 'requiredTitle'].join('.')))}</strong><p>${escHtml(setupT(['dashboard', 'requiredText'].join('.')))}</p></div>
        <button class="btn btn-primary btn-sm" data-setup-wizard-action="open">${escHtml(setupT('actions.start'))}</button>`;
      return;
    }
    if (!setup.optional_incomplete || !missing.length) {
      el.className = 'setup-action-panel hidden';
      el.innerHTML = '';
      return;
    }
    const rows = missing.map((key) => {
      const action = key === 'storage'
        ? `<button class="btn btn-secondary btn-sm" data-setup-wizard-action="open">${escHtml(setupT('actions.chooseStorage'))}</button>`
        : (key === 'repository'
          ? `<button class="btn btn-secondary btn-sm" data-setup-wizard-action="open-repository-manager">${escHtml(setupT('actions.repositoryShort'))}</button>`
          : `<button class="btn btn-secondary btn-sm" data-setup-wizard-action="open-job-wizard">${escHtml(setupT('actions.jobShort'))}</button>`);
      return `<li><span>${escHtml(setupT(['dashboard', key].join('.')))}</span>${action}</li>`;
    }).join('');
    el.className = 'setup-action-panel';
    el.innerHTML = `<div class="setup-action-panel-head">
        <div><strong>${escHtml(setupT(['dashboard', 'incompleteTitle'].join('.')))}</strong><p>${escHtml(setupT(['dashboard', 'incompleteText'].join('.')))}</p></div>
        <button class="btn btn-secondary btn-sm" data-setup-wizard-action="open">${escHtml(setupT('actions.openWizard'))}</button>
      </div>
      <ul>${rows}</ul>`;
  }

  async function handleAction(event) {
    const el = event.target.closest('[data-setup-wizard-action]');
    if (!el) return;
    event.preventDefault();
    const action = el.dataset.setupWizardAction || '';
    if (!requireAdmin(action)) return;
    if (action === 'open') {
      const status = await fetchStatus(true);
      open(status);
    } else if (action === 'close') {
      close();
    } else if (action === 'save-data-dir') {
      saveDataDir();
    } else if (action === 'dismiss-optional') {
      dismissOptional();
    } else if (action === 'open-settings-tab') {
      navigateSettingsTab(el.dataset.settingsTabTarget || 'general');
    } else if (action === 'open-repository-manager') {
      openRepositoryFlow();
    } else if (action === 'open-job-wizard') {
      openJobFlow();
    }
  }

  namespace.open = open;
  namespace.close = close;
  namespace.maybeOpen = maybeOpen;
  namespace.resumeAfterExternalSave = resumeAfterExternalSave;
  namespace.renderDashboardPanel = renderDashboardPanel;
  namespace.handleAction = handleAction;
  window.BBUI.setupWizard = namespace;
})();
