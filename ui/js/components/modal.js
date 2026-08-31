'use strict';

(function initModalComponent() {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};
  const logViewer = () => window.BBUI?.components?.logViewer;
  const modalActions = Object.create(null);
  const escapeCloseOrder = [
    ['discard-confirm-modal', 'closeDiscardConfirm'],
    ['confirm-modal', 'closeConfirmModal'],
    ['settings-dialog-modal', 'closeSettingsDialog'],
    ['storage-deploy-modal', 'closeStorageDeployModal'],
    ['repository-lifecycle-modal', 'closeRepositoryLifecycle'],
    ['storage-maintenance-confirm-modal', 'closeStorageMaintenanceConfirm'],
    ['repository-manager-modal', 'closeRepositoryManager'],
    ['schedule-modal', 'closeScheduleModal'],
    ['wizard-help-modal', 'closeWizardHelpModal'],
    ['wizard-modal', 'closeWizard'],
    ['setup-wizard-modal', 'closeSetupWizard'],
  ];

  function t(key, fallback) {
    return window.BBUI?.components?.i18n?.t?.(key) || fallback || key;
  }

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

  let discardConfirmAction = null;

  function controlValue(el) {
    const tag = String(el?.tagName || '').toLowerCase();
    const type = String(el?.type || '').toLowerCase();
    if (type === 'checkbox' || type === 'radio') return !!el.checked;
    if (tag === 'select' && el.multiple) {
      return Array.from(el.selectedOptions || []).map((option) => option.value);
    }
    return String(el?.value || '');
  }

  function formSnapshot(root) {
    if (!root?.querySelectorAll) return '[]';
    const rows = Array.from(root.querySelectorAll('input, textarea, select'))
      .filter((el) => !el.disabled && String(el.type || '').toLowerCase() !== 'button')
      .map((el) => [el.id || el.name || '', String(el.type || el.tagName || '').toLowerCase(), controlValue(el)]);
    return JSON.stringify(rows);
  }

  function isFormDirty(root, snapshot) {
    return !!snapshot && formSnapshot(root) !== snapshot;
  }

  function ensureDiscardConfirmModal() {
    let modal = document.getElementById('discard-confirm-modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'discard-confirm-modal';
    modal.className = 'modal-backdrop hidden';
    modal.innerHTML = `
      <div class="modal">
        <div class="modal-header">
          <h3 id="discard-confirm-title"></h3>
          <button class="modal-close" id="discard-confirm-close-btn" type="button" aria-label="${t('common.close', 'Close')}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div class="modal-body">
          <p id="discard-confirm-message"></p>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" id="discard-confirm-keep-btn" type="button"></button>
          <button class="btn btn-danger" id="discard-confirm-discard-btn" type="button"></button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    document.getElementById('discard-confirm-close-btn')?.addEventListener('click', () => closeDiscardConfirm(false));
    document.getElementById('discard-confirm-keep-btn')?.addEventListener('click', () => closeDiscardConfirm(false));
    document.getElementById('discard-confirm-discard-btn')?.addEventListener('click', () => closeDiscardConfirm(true));
    modal.addEventListener('click', (event) => {
      if (event.target === event.currentTarget) closeDiscardConfirm(false);
    });
    return modal;
  }

  function openDiscardConfirm(onConfirm) {
    const modal = ensureDiscardConfirmModal();
    const title = document.getElementById('discard-confirm-title');
    const message = document.getElementById('discard-confirm-message');
    const keep = document.getElementById('discard-confirm-keep-btn');
    const discard = document.getElementById('discard-confirm-discard-btn');
    if (title) title.textContent = t('common.unsavedChangesTitle', 'Unsaved changes');
    if (message) message.textContent = t(
      'common.discardUnsavedChangesMessage',
      'Your entries in this dialog have not been saved yet.'
    );
    if (keep) keep.textContent = t('common.keepEditing', 'Keep editing');
    if (discard) discard.textContent = t('common.discardChanges', 'Discard changes');
    discardConfirmAction = typeof onConfirm === 'function' ? onConfirm : null;
    modal.classList.remove('hidden');
    keep?.focus();
  }

  function closeDiscardConfirm(confirmed = false) {
    const modal = document.getElementById('discard-confirm-modal');
    modal?.classList.add('hidden');
    const action = discardConfirmAction;
    discardConfirmAction = null;
    if (confirmed && typeof action === 'function') action();
  }

  function confirmDiscardIfDirty(dirty, onConfirm) {
    if (!dirty) return true;
    openDiscardConfirm(onConfirm);
    return false;
  }

  function isVisibleModal(id) {
    const modal = document.getElementById(id);
    return !!modal && !modal.classList.contains('hidden');
  }

  function wireEscapeClose() {
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      const target = escapeCloseOrder.find(([id]) => isVisibleModal(id));
      if (!target) return;
      event.preventDefault();
      runAction(target[1]);
    });
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
    document.getElementById('wizard-help-modal')?.addEventListener('click', (e) => {
      if (e.target === e.currentTarget) runAction('closeWizardHelpModal');
    });
  }

  function init() {
    setAction('closeDiscardConfirm', () => closeDiscardConfirm(false));
    wireModalClosers();
    wireBackdropClose();
    wireEscapeClose();
  }

  window.BBUI.components.modal = {
    confirmDiscardIfDirty,
    formSnapshot,
    init,
    isFormDirty,
    setAction,
  };
})();
