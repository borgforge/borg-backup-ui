'use strict';

window.BBUI = window.BBUI || {};
window.BBUI.utils = window.BBUI.utils || {};
window.BBUI.utils.dom = window.BBUI.utils.dom || {};

function showMsg(elementId, type, text) {
  const el = document.getElementById(elementId);
  if (!el) return;
  if (!String(text || '').trim()) { hideEl(elementId); return; }
  const severity = type === 'warn' ? 'warning' : (['error', 'success', 'warning'].includes(type) ? type : 'info');
  const inline = !!el.closest('.modal-backdrop, [role="dialog"]');
  // Late results from a hidden page/panel must not clear current feedback.
  if (!inline && el.parentElement?.getClientRects().length === 0) return;
  // Keep form validation inside its dialog. Page action feedback must not move
  // the controls the user is currently interacting with (#523).
  if (!inline) clearPageFeedback();
  el.className = `status-message ${severity}-state${inline ? '' : ' page-feedback'}`;
  el.setAttribute('role', severity === 'error' ? 'alert' : 'status');
  el.setAttribute('aria-atomic', 'true');
  if (inline) { el.textContent = text; return; }

  const returnFocus = document.activeElement;
  const title = document.createElement('strong');
  title.className = 'page-feedback-title';
  title.setAttribute('data-i18n', `common.feedback.${severity}`);
  title.textContent = window.BBUI.components.i18n.t(`common.feedback.${severity}`);
  const message = document.createElement('div');
  message.className = 'page-feedback-text';
  message.textContent = text;
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'page-feedback-close';
  close.setAttribute('data-i18n-aria-label', 'common.feedback.dismiss');
  close.setAttribute('aria-label', window.BBUI.components.i18n.t('common.feedback.dismiss'));
  close.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';
  close.addEventListener('click', () => {
    hideEl(elementId);
    if (returnFocus?.isConnected && returnFocus.getClientRects().length && !returnFocus.disabled) {
      returnFocus.focus({preventScroll: true});
    }
  });
  el.replaceChildren(title, close, message);
}

function hideEl(elementId) {
  const el = document.getElementById(elementId);
  if (el) {
    el.className = 'status-message hidden';
    el.textContent = '';
  }
}

function clearPageFeedback() {
  document.querySelectorAll('.page-feedback').forEach(el => hideEl(el.id));
}

window.BBUI.utils.dom.showMsg = showMsg;
window.BBUI.utils.dom.hideEl = hideEl;
window.BBUI.utils.dom.clearPageFeedback = clearPageFeedback;

window.showMsg = showMsg;
window.hideEl = hideEl;
