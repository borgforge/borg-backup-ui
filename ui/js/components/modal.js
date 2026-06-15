'use strict';

(function initModalComponent() {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};
  const logViewer = () => window.BBUI?.components?.logViewer;
  const modalActions = Object.create(null);

  function setAction(name, fn) {
    const key = String(name || '').trim();
    if (!key) return;
    if (typeof fn === 'function') modalActions[key] = fn;
    else delete modalActions[key];
  }

  function runAction(name) {
    const fn = modalActions[String(name || '').trim()];
    if (typeof fn !== 'function') return;
    fn();
  }

  function wireModalClosers() {
    document.getElementById('confirm-modal-close-btn')?.addEventListener('click', () => {
      runAction('closeConfirmModal');
    });
    document.getElementById('confirm-modal-cancel-btn')?.addEventListener('click', () => {
      runAction('closeConfirmModal');
    });
    document.getElementById('modal-confirm-btn')?.addEventListener('click', () => {
      runAction('confirmPrimaryAction');
    });
    document.getElementById('modal-confirm-input')?.addEventListener('input', () => {
      runAction('confirmInputChanged');
    });
    document.getElementById('modal-confirm-input')?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !document.getElementById('modal-confirm-btn')?.disabled) {
        runAction('confirmPrimaryAction');
      }
    });
  }

  function wireBackdropClose() {
    document.getElementById('confirm-modal')?.addEventListener('click', (e) => {
      if (e.target === e.currentTarget) runAction('closeConfirmModal');
    });
    document.getElementById('log-viewer-modal')?.addEventListener('click', (e) => {
      if (e.target === e.currentTarget) logViewer()?.close?.();
    });
    document.getElementById('schedule-modal')?.addEventListener('click', (e) => {
      if (e.target === e.currentTarget) runAction('closeScheduleModal');
    });
    document.getElementById('wizard-help-modal')?.addEventListener('click', (e) => {
      if (e.target === e.currentTarget) runAction('closeWizardHelpModal');
    });
    document.getElementById('settings-dialog-modal')?.addEventListener('click', (e) => {
      if (e.target === e.currentTarget) document.getElementById('settings-dialog-cancel-btn')?.click();
    });
    document.getElementById('storage-test-modal')?.addEventListener('click', (e) => {
      if (e.target === e.currentTarget) runAction('closeStorageTestModal');
    });
    document.getElementById('storage-deploy-modal')?.addEventListener('click', (e) => {
      if (e.target === e.currentTarget) runAction('closeStorageDeployModal');
    });
  }

  function init() {
    wireModalClosers();
    wireBackdropClose();
  }

  window.BBUI.components.modal = { init, setAction };
})();
