'use strict';

window.BBUI = window.BBUI || {};
window.BBUI.utils = window.BBUI.utils || {};
window.BBUI.utils.dom = window.BBUI.utils.dom || {};

let pageFeedbackDismissal = null;

/**
 * Auto-dismiss non-error feedback after reading time, pausing on interaction.
 * @param {HTMLElement} el Feedback container.
 * @param {string} severity Normalized message severity.
 * @param {string} text Message used to estimate reading time.
 */
function schedulePageFeedbackDismissal(el, severity, text) {
  if (severity === 'error') return;
  // Give longer messages reading time (20 characters/second), up to 30 seconds.
  let remaining = Math.max(severity === 'warning' ? 12000 : 5000,
    Math.min(30000, String(text).length * 50));
  let timer = null;
  let started = 0;
  let hovered = el.matches(':hover');
  let focused = el.contains(document.activeElement);
  const state = {element: el, cancel: null};

  function pause() {
    if (timer === null) return;
    clearTimeout(timer);
    timer = null;
    remaining = Math.max(0, remaining - (performance.now() - started));
  }
  function resume() {
    if (hovered || focused || document.hidden || timer !== null) return;
    started = performance.now();
    timer = setTimeout(() => {
      if (pageFeedbackDismissal === state) hideEl(el.id);
    }, remaining);
  }
  const enter = () => { hovered = true; pause(); };
  const leave = () => { hovered = false; resume(); };
  const focusIn = () => { focused = true; pause(); };
  const focusOut = event => {
    focused = el.contains(event.relatedTarget);
    if (!focused) resume();
  };
  const visibility = () => { if (document.hidden) pause(); else resume(); };
  const listeners = {mouseenter: enter, mouseleave: leave, focusin: focusIn, focusout: focusOut};
  Object.entries(listeners).forEach(([name, callback]) => el.addEventListener(name, callback));
  document.addEventListener('visibilitychange', visibility);
  state.cancel = () => {
    if (timer !== null) clearTimeout(timer);
    Object.entries(listeners).forEach(([name, callback]) => el.removeEventListener(name, callback));
    document.removeEventListener('visibilitychange', visibility);
  };
  pageFeedbackDismissal = state;
  resume();
}

/**
 * Show inline dialog feedback or a page notification without shifting controls.
 * @param {string} elementId Target element ID.
 * @param {string} type Requested severity (`warn` maps to `warning`).
 * @param {string} text Message to show; blank text hides the target.
 */
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
  schedulePageFeedbackDismissal(el, severity, text);
}

/** Hide feedback and cancel any dismissal timer for this element. */
function hideEl(elementId) {
  if (pageFeedbackDismissal?.element.id === elementId) {
    pageFeedbackDismissal.cancel();
    pageFeedbackDismissal = null;
  }
  const el = document.getElementById(elementId);
  if (el) {
    el.className = 'status-message hidden';
    el.textContent = '';
  }
}

/** Clear page notifications while leaving inline dialog messages intact. */
function clearPageFeedback() {
  if (pageFeedbackDismissal) {
    pageFeedbackDismissal.cancel();
    pageFeedbackDismissal = null;
  }
  document.querySelectorAll('.page-feedback').forEach(el => hideEl(el.id));
}

window.BBUI.utils.dom.showMsg = showMsg;
window.BBUI.utils.dom.hideEl = hideEl;
window.BBUI.utils.dom.clearPageFeedback = clearPageFeedback;

window.showMsg = showMsg;
window.hideEl = hideEl;
