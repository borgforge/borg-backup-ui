'use strict';

(function initToastComponent() {
  window.BBUI = window.BBUI || {};
  window.BBUI.components = window.BBUI.components || {};
  const t = (key) => window.BBUI?.components?.i18n?.t?.(key) || key;

  /**
   * Route a message to page feedback or the browser alert fallback.
   * @param {string} targetId Feedback element ID when available.
   * @param {string} type Message severity.
   * @param {string} message Text to show; blank input is ignored.
   * @param {string} [fallbackTitle] Alert title when feedback is unavailable.
   */
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
