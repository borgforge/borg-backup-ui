'use strict';

window.BBUI = window.BBUI || {};
window.BBUI.utils = window.BBUI.utils || {};
window.BBUI.utils.dom = window.BBUI.utils.dom || {};

function showMsg(elementId, type, text) {
  const el = document.getElementById(elementId);
  if (!el) return;
  el.className = `status-message ${
    type === 'error' ? 'error-state'
      : type === 'success' ? 'success-state'
        : type === 'warning' ? 'warning-state'
          : 'empty-state'
  }`;
  el.textContent = text;
}

function hideEl(elementId) {
  const el = document.getElementById(elementId);
  if (el) el.className = 'status-message hidden';
}

window.BBUI.utils.dom.showMsg = showMsg;
window.BBUI.utils.dom.hideEl = hideEl;

window.showMsg = showMsg;
window.hideEl = hideEl;
