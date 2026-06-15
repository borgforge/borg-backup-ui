'use strict';

(function initToastComponent() {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};

  function notify(targetId, type, message, fallbackTitle = 'Hinweis') {
    const text = String(message || '').trim();
    if (!text) return;
    if (typeof showMsg === 'function' && targetId) {
      showMsg(targetId, type || 'info', text);
      return;
    }
    alert(`${fallbackTitle}: ${text}`);
  }

  function error(targetId, message, fallbackTitle = 'Fehler') {
    notify(targetId, 'error', message, fallbackTitle);
  }

  function success(targetId, message, fallbackTitle = 'Erfolg') {
    notify(targetId, 'success', message, fallbackTitle);
  }

  window.BBUI.components.toast = { notify, error, success };
})();
