'use strict';

(function initToastComponent() {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};
  const t = (key) => window.BBUI?.components?.i18n?.t?.(key) || key;

  function notify(targetId, type, message, fallbackTitle = '') {
    const text = String(message || '').trim();
    if (!text) return;
    if (typeof showMsg === 'function' && targetId) {
      showMsg(targetId, type || 'info', text);
      return;
    }
    alert(`${fallbackTitle || t('common.notice')}: ${text}`);
  }

  function error(targetId, message, fallbackTitle = '') {
    notify(targetId, 'error', message, fallbackTitle || t('common.error'));
  }

  function success(targetId, message, fallbackTitle = '') {
    notify(targetId, 'success', message, fallbackTitle || t('common.success'));
  }

  window.BBUI.components.toast = { notify, error, success };
})();
