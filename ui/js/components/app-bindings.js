'use strict';

(function initAppBindingsComponent() {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};
  const core = () => window.BBUI?.core;
  const theme = () => window.BBUI?.components?.theme;
  const logViewer = () => window.BBUI?.components?.logViewer;
  const t = (key) => window.BBUI?.components?.i18n?.t?.(key) || key;
  let roleUiObserver = null;

  function _updateCurrentUserLabel() {
    const el = document.getElementById('auth-current-user');
    if (!el) return;
    const username = String(el.dataset.username || '').trim();
    const role = String(el.dataset.role || '').trim();
    el.textContent = username
      ? `${t('settings.users.signedIn')} ${username}${role ? ` (${role})` : ''}`
      : '';
  }

  function _currentRole() {
    return String(core()?.getCurrentRole?.() || 'viewer').toLowerCase();
  }

  function _isViewer() {
    return _currentRole() === 'viewer';
  }

  function _isAdmin() {
    return _currentRole() === 'admin';
  }

  function _setHidden(selector, hidden) {
    document.querySelectorAll(selector).forEach((el) => {
      el.style.display = hidden ? 'none' : '';
    });
  }

  function _setDisabled(selector, disabled, title = '') {
    document.querySelectorAll(selector).forEach((el) => {
      el.disabled = !!disabled;
      if (disabled && title) el.title = title;
      if (!disabled && el.dataset?.roleGateTitle && el.title === el.dataset.roleGateTitle) {
        el.title = '';
      }
      if (disabled && title && el.dataset) el.dataset.roleGateTitle = title;
    });
  }

  function applyRoleUiGates() {
    const role = _currentRole();
    const isViewer = role === 'viewer';
    const canSettings = _isAdmin();
    const settingsNav = document.querySelector('.nav-item[data-page="settings"]');
    if (settingsNav) settingsNav.style.display = canSettings ? '' : 'none';
    _setHidden('#sidebar-system-health', !canSettings);

    const viewerHint = t('permissions.viewerReadOnly');
    _setHidden('#jobs-new-btn, #jobs-empty-create-btn', isViewer);
    _setHidden('[data-jobs-action="start-job"]', isViewer);
    _setHidden('[data-jobs-action="toggle-menu"]', isViewer);
    _setHidden('[data-jobs-action="open-wizard"]', isViewer);

    _setHidden('#check-run-btn', isViewer);
    _setHidden('[data-storage-action="test-repo"]', isViewer);
    _setHidden('[data-storage-action="smb-action"]', isViewer);

    _setHidden('#rt-run-btn', isViewer);
    _setHidden('#restore-start-btn', isViewer);

    _setDisabled('#restore-confirm-check', isViewer, viewerHint);
    _setDisabled('#restore-target-path, #restore-conflict-mode, #restore-dry-run, #restore-preserve-owner', isViewer, viewerHint);
    _setDisabled('#settings-save-btn', !_isAdmin(), t('permissions.adminSettingsOnly'));
  }

  function _startRoleUiObserver() {
    if (roleUiObserver) return;
    const root = document.getElementById('app-layout') || document.body;
    if (!root) return;
    roleUiObserver = new MutationObserver(() => applyRoleUiGates());
    roleUiObserver.observe(root, { childList: true, subtree: true });
  }

  function bindCoreNavigation() {
    document.addEventListener('click', (event) => {
      const coreLink = event.target.closest('[data-core-action="goto-settings"]');
      if (coreLink) {
        event.preventDefault();
        core()?.navigate?.('settings');
      }
    });

    document.querySelectorAll('.nav-item[data-page]').forEach((el) => {
      el.addEventListener('click', async () => {
        const target = el.getAttribute('data-page');
        const current = core()?.getCurrentPage?.() || '';
        if (current === 'settings' && target !== 'settings' && typeof window.canLeaveSettingsPage === 'function') {
          const ok = await window.canLeaveSettingsPage();
          if (!ok) return;
        }
        core()?.navigate?.(target);
      });
    });
  }

  function bindMainActions() {
    document.getElementById('mobile-backdrop')?.addEventListener('click', () => core()?.closeMobileNav?.());
    document.getElementById('mobile-nav-toggle-btn')?.addEventListener('click', () => core()?.toggleMobileNav?.());
    document.getElementById('refresh-btn')?.addEventListener('click', refreshStatus);
    document.getElementById('jobs-refresh-btn')?.addEventListener('click', refreshJobs);
    document.getElementById('jobs-new-btn')?.addEventListener('click', openWizard);
    document.getElementById('jobs-grid')?.addEventListener('click', onJobsGridClick);
    document.getElementById('jobs-log-clear-btn')?.addEventListener('click', clearLog);
    document.getElementById('jobs-log-close-btn')?.addEventListener('click', closeLogPanel);
    document.getElementById('jobs-log-scroll-end-btn')?.addEventListener('click', scrollLogToBottom);
    document.getElementById('history-refresh-btn')?.addEventListener('click', refreshHistory);
    document.getElementById('history-content')?.addEventListener('click', onHistoryContentClick);
    document.getElementById('check-level-select')?.addEventListener('change', checkUpdateModeHint);
    document.getElementById('storage-content')?.addEventListener('click', onStorageContentClick);
    document.getElementById('check-run-btn')?.addEventListener('click', checkRun);
    document.getElementById('check-clear-log-btn')?.addEventListener('click', checkClearLog);
    document.getElementById('check-close-log-btn')?.addEventListener('click', checkCloseLog);
    document.getElementById('history-filter-type')?.addEventListener('change', applyHistoryFilters);
    document.getElementById('history-filter-location')?.addEventListener('change', applyHistoryFilters);
    document.getElementById('history-filter-status')?.addEventListener('change', applyHistoryFilters);
    document.getElementById('bericht-job-sel')?.addEventListener('change', berichtLoad);
    document.getElementById('bericht-borginfo-btn')?.addEventListener('click', berichtLoadBorgInfo);
    document.getElementById('restore-job-sel')?.addEventListener('change', restoreLoadArchives);
    document.getElementById('restore-archive-sel')?.addEventListener('change', () => restoreBrowse(''));
    document.getElementById('restore-browser')?.addEventListener('click', onRestoreBrowserClick);
    document.getElementById('restore-start-btn')?.addEventListener('click', restoreStart);
    document.getElementById('restore-step-next-btn')?.addEventListener('click', restoreStepNext);
    document.getElementById('restore-step-back-btn')?.addEventListener('click', restoreStepBack);
    document.getElementById('restore-clear-selection-btn')?.addEventListener('click', restoreClearSelection);
    document.getElementById('restore-confirm-check')?.addEventListener('change', restoreUpdateConfirmState);
    document.getElementById('restore-target-path')?.addEventListener('input', restoreTargetInputChanged);
    document.getElementById('restore-conflict-mode')?.addEventListener('change', restorePrecheckInputsChanged);
    document.getElementById('restore-dry-run')?.addEventListener('change', restorePrecheckInputsChanged);
    document.getElementById('restore-confirm-close-btn')?.addEventListener('click', () => closeRestoreConfirmModal(false));
    document.getElementById('restore-confirm-cancel-btn')?.addEventListener('click', () => closeRestoreConfirmModal(false));
    document.getElementById('restore-confirm-start-btn')?.addEventListener('click', () => closeRestoreConfirmModal(true));
    document.getElementById('restore-download-confirm-close-btn')?.addEventListener('click', () => closeRestoreDownloadConfirmModal(false));
    document.getElementById('restore-download-confirm-cancel-btn')?.addEventListener('click', () => closeRestoreDownloadConfirmModal(false));
    document.getElementById('restore-download-confirm-start-btn')?.addEventListener('click', () => closeRestoreDownloadConfirmModal(true));
    document.getElementById('restore-download-confirm-modal')?.addEventListener('click', (event) => {
      if (event.target === event.currentTarget) closeRestoreDownloadConfirmModal(false);
    });
    document.getElementById('restore-tests-refresh-btn')?.addEventListener('click', refreshRestoreTests);
    document.getElementById('rt-run-btn')?.addEventListener('click', runRestoreTestNow);
    document.getElementById('rt-subtab-plan-btn')?.addEventListener('click', () => switchRestoreTestsSubtab('plan'));
    document.getElementById('rt-subtab-reports-btn')?.addEventListener('click', () => switchRestoreTestsSubtab('reports'));
    document.getElementById('rt-report-filter-job')?.addEventListener('input', onRTReportFilterChange);
    document.getElementById('rt-report-filter-location')?.addEventListener('change', onRTReportFilterChange);
    document.getElementById('rt-report-filter-status')?.addEventListener('change', onRTReportFilterChange);
    document.getElementById('rt-report-filter-range')?.addEventListener('change', onRTReportFilterChange);
    document.getElementById('rt-report-filter-problem')?.addEventListener('change', onRTReportFilterChange);
    document.getElementById('rt-log-close-btn')?.addEventListener('click', closeRTLogPanel);
    document.getElementById('restore-tests-content')?.addEventListener('click', onRestoreTestsContentClick);
    document.getElementById('restore-tests-plan-content')?.addEventListener('click', onRestoreTestsPlanClick);
    document.getElementById('settings-save-btn')?.addEventListener('click', saveSettings);
    document.getElementById('help-refresh-btn')?.addEventListener('click', helpInit);
    document.getElementById('settings-content')?.addEventListener('click', onSettingsContentClick);
    document.getElementById('settings-content')?.addEventListener('change', (event) => {
      const sel = event.target.closest('#ui-theme-select');
      if (sel) theme()?.applyThemePreference?.(sel.value, true);
    });
    document.getElementById('log-viewer-close-btn')?.addEventListener('click', () => logViewer()?.close?.());
    document.getElementById('storage-test-close-btn')?.addEventListener('click', closeStorageTestDetails);
    document.getElementById('storage-test-ok-btn')?.addEventListener('click', closeStorageTestDetails);
    document.getElementById('storage-test-copy-btn')?.addEventListener('click', copyStorageTestDetails);
    document.getElementById('storage-deploy-close-btn')?.addEventListener('click', closeStorageDeployModal);
    document.getElementById('storage-deploy-ok-btn')?.addEventListener('click', closeStorageDeployModal);
    document.getElementById('storage-deploy-send-btn')?.addEventListener('click', storageDeploySendInput);
    document.getElementById('storage-deploy-cancel-btn')?.addEventListener('click', storageDeployCancel);
    document.getElementById('storage-deploy-input')?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        storageDeploySendInput();
      }
    });
    document.getElementById('auth-logout-btn')?.addEventListener('click', async () => {
      try {
        await fetch('/api/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      } catch (_) {
        // ignore and still redirect to login
      }
      window.location.href = '/login';
    });

    document.addEventListener('click', (event) => {
      if (!_isViewer()) return;
      const blocked = event.target.closest([
        '[data-jobs-action="start-job"]',
        '[data-jobs-action="open-wizard"]',
        '[data-jobs-action="toggle-menu"]',
        '[data-storage-action="test-repo"]',
        '[data-storage-action="smb-action"]',
        '#check-run-btn',
        '#rt-run-btn',
        '#restore-start-btn',
        '#settings-save-btn',
      ].join(','));
      if (!blocked) return;
      event.preventDefault();
      event.stopPropagation();
      if (typeof showMsg === 'function') {
        showMsg('jobs-message', 'warning', t('permissions.viewerActionDenied'));
      }
    }, true);
  }

  function bindWizardActions() {
    document.getElementById('wizard-close-btn')?.addEventListener('click', closeWizard);
    document.getElementById('wizard-back-btn')?.addEventListener('click', wizardBack);
    document.getElementById('wizard-cancel-btn')?.addEventListener('click', closeWizard);
    document.getElementById('wizard-next-btn')?.addEventListener('click', wizardNext);
    document.getElementById('wizard-save-btn')?.addEventListener('click', saveWizardJob);
    document.getElementById('wiz-job-name')?.addEventListener('input', () => wizardClearError(1));
    document.getElementById('wiz-type-id')?.addEventListener('input', () => {
      wizardAutoFill();
      wizardClearError(1);
    });
    document.getElementById('wiz-location')?.addEventListener('change', wizardAutoFill);
    document.getElementById('wiz-usb-profile')?.addEventListener('change', wizardAutoFill);
    document.getElementById('wiz-smb-profile')?.addEventListener('change', wizardAutoFill);
    document.getElementById('wiz-storage-profile')?.addEventListener('change', wizardAutoFill);
    document.getElementById('wiz-icon')?.addEventListener('change', wizardUpdateIconPreview);
    document.getElementById('wiz-icon-color')?.addEventListener('change', wizardUpdateIconPreview);
    document.getElementById('wiz-source-paths')?.addEventListener('input', () => wizardClearError(2));
    document.getElementById('wiz-repo-path')?.addEventListener('input', () => wizardClearError(2));
    document.getElementById('wiz-keep-btn')?.addEventListener('click', wizardKeepPassphrase);
    document.getElementById('wiz-replace-btn')?.addEventListener('click', wizardReplacePassphrase);
    document.getElementById('wiz-passphrase')?.addEventListener('input', (e) => {
      wizardClearError(4);
      document.getElementById('wiz-copy-btn').disabled = !(e.target?.value || '').trim();
    });
    document.getElementById('wiz-passphrase-toggle')?.addEventListener('click', wizardTogglePassphrase);
    document.getElementById('wiz-generate-btn')?.addEventListener('click', wizardGeneratePassphrase);
    document.getElementById('wiz-copy-btn')?.addEventListener('click', wizardCopyPassphrase);
    document.getElementById('wiz-source-path-input')?.addEventListener('input', wizardSourcePathInputChanged);
    document.getElementById('wiz-source-path-input')?.addEventListener('keydown', wizardSourcePathKeydown);
    document.getElementById('wiz-source-path-list')?.addEventListener('click', wizardSourcePathsClick);
    document.getElementById('wiz-source-path-suggest')?.addEventListener('click', wizardSourcePathsClick);
    document.getElementById('wiz-description-help-btn')?.addEventListener('click', openWizardDescriptionHelp);
    document.getElementById('wizard-help-close-btn')?.addEventListener('click', closeWizardDescriptionHelp);
    document.getElementById('wizard-help-ok-btn')?.addEventListener('click', closeWizardDescriptionHelp);
    document.getElementById('wiz-sched-enabled')?.addEventListener('change', wizardSchedulePreview);
    document.getElementById('wiz-sched-hour')?.addEventListener('input', wizardSchedulePreview);
    document.getElementById('wiz-sched-minute')?.addEventListener('input', wizardSchedulePreview);
    document.getElementById('wiz-sched-dom')?.addEventListener('input', wizardSchedulePreview);
    document.getElementById('wiz-sched-cron-custom')?.addEventListener('input', wizardSchedulePreview);
    document.querySelectorAll('[data-wiz-freq]')?.forEach((el) => {
      el.addEventListener('click', () => wizardScheduleFreq(el.dataset.wizFreq));
    });
    document.querySelectorAll('[data-wiz-dow]')?.forEach((el) => {
      el.addEventListener('click', () => wizardScheduleSelectDow(parseInt(el.dataset.wizDow, 10)));
    });
  }

  function registerCoreActions() {
    const c = core();
    if (!c?.setAction) return;
    c.setAction('refreshStatus', typeof refreshStatus === 'function' ? refreshStatus : null);
    c.setAction('refreshJobs', typeof refreshJobs === 'function' ? refreshJobs : null);
    c.setAction('startJobsPolling', typeof startJobsPolling === 'function' ? startJobsPolling : null);
    c.setAction('stopJobsPolling', typeof stopJobsPolling === 'function' ? stopJobsPolling : null);
    c.setAction('restoreInit', typeof restoreInit === 'function' ? restoreInit : null);
    c.setAction('refreshRestoreTests', typeof refreshRestoreTests === 'function' ? refreshRestoreTests : null);
    c.setAction('updateRTScheduleBtn', typeof _updateRTScheduleBtn === 'function' ? _updateRTScheduleBtn : null);
    c.setAction('stopRTPolling', typeof stopRTPolling === 'function' ? stopRTPolling : null);
    c.setAction('refreshStorage', typeof refreshStorage === 'function' ? refreshStorage : null);
    c.setAction('berichtInit', typeof berichtInit === 'function' ? berichtInit : null);
    c.setAction('refreshSettings', typeof refreshSettings === 'function' ? refreshSettings : null);
    c.setAction('refreshHistory', typeof refreshHistory === 'function' ? refreshHistory : null);
    c.setAction('helpInit', typeof helpInit === 'function' ? helpInit : null);
  }

  function registerModalActions() {
    const m = window.BBUI?.components?.modal;
    if (!m?.setAction) return;
    m.setAction('closeConfirmModal', typeof closeModal === 'function' ? closeModal : null);
    m.setAction('confirmPrimaryAction', typeof confirmModalPrimaryAction === 'function' ? confirmModalPrimaryAction : null);
    m.setAction('confirmInputChanged', typeof checkDeleteConfirmInput === 'function' ? checkDeleteConfirmInput : null);
    m.setAction('closeScheduleModal', typeof closeScheduleModal === 'function' ? closeScheduleModal : null);
    m.setAction('closeWizardHelpModal', typeof closeWizardDescriptionHelp === 'function' ? closeWizardDescriptionHelp : null);
    m.setAction('closeStorageTestModal', typeof closeStorageTestDetails === 'function' ? closeStorageTestDetails : null);
    m.setAction('closeStorageDeployModal', typeof closeStorageDeployModal === 'function' ? closeStorageDeployModal : null);
  }

  function runStartup() {
    core()?.updateDataDirWarning?.().then(() => {
      if (core()?.isSetupRequired?.()) {
        core()?.navigate?.('settings');
        showMsg(
          'settings-message',
          'warning',
          window.BBUI?.components?.i18n?.t?.('settings.setup.startupRequired') || ''
        );
        return;
      }
      core()?.updateSidebarSystemHealth?.(true);
      refreshStatus();
    }).catch(() => {});
    scheduleAutoRefresh();
    updateClock();
    fetch('/api/version').then(r => r.ok ? r.json() : null).then(v => { if (v) _applyVersionInfo(v.version, v.author, v.borg_version); }).catch(() => {});
    fetch('/api/auth/status').then(r => r.ok ? r.json() : null).then((a) => {
      const el = document.getElementById('auth-current-user');
      if (!el || !a) return;
      const u = String(a.current_user || '').trim();
      const role = String(a.current_role || '').trim();
      core()?.setCurrentRole?.(role || 'viewer');
      el.dataset.username = u;
      el.dataset.role = role;
      _updateCurrentUserLabel();
      const canSettings = String(role || '').toLowerCase() === 'admin';
      applyRoleUiGates();
      core()?.updateSidebarSystemHealth?.(true);
      if (!canSettings && core()?.getCurrentPage?.() === 'settings') {
        core()?.navigate?.('dashboard');
      }
    }).catch(() => {});
    _startRoleUiObserver();
    applyRoleUiGates();
    setInterval(updateClock, 1000);
    setInterval(() => core()?.updateSidebarSystemHealth?.(), 60_000);

    const logEl = document.getElementById('log-output');
    if (logEl) logEl.addEventListener('scroll', () => checkScrollHint(logEl));

    checkUpdateModeHint();
    window.BBUI?.components?.modal?.init?.();
    window.BBUI?.components?.scheduleModal?.init?.();
  }

  function init() {
    theme()?.initThemePreference?.();
    registerCoreActions();
    registerModalActions();
    bindCoreNavigation();
    bindMainActions();
    bindWizardActions();
    window.addEventListener('bbui:language-changed', () => {
      _updateCurrentUserLabel();
      applyRoleUiGates();
    });
    runStartup();
  }

  window.BBUI.components.appBindings = { init };
})();
