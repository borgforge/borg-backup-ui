'use strict';

window.BBUI = window.BBUI || {};
window.BBUI.api = window.BBUI.api || {};

/**
 * Resolve a structured API message through the active locale.
 * @param {object|null} payload API response body, possibly with message/error codes.
 * @param {string} [fallback] Text used when no translation exists.
 * @param {object} [extraParams] Additional interpolation values.
 * @returns {string} Translated or fallback message.
 */
function apiMessage(payload, fallback = '', extraParams = {}) {
  const data = payload && typeof payload === 'object' ? payload : {};
  const i18n = window.BBUI?.components?.i18n;
  const messageCode = String(data.message_code || '').trim();
  const errorCode = String(data.code || '').trim();
  const key = messageCode
    ? `api.messages.${messageCode}`
    : (errorCode ? `api.errors.${errorCode}` : '');
  const params = { ...(data.message_params || {}), ...extraParams };
  if (key && i18n?.t) {
    const translated = i18n.t(key, params);
    if (translated !== key) return translated;
  }
  return fallback || i18n?.t?.('api.errors.unknown') || 'Request failed.';
}

/**
 * Resolve an API error with an HTTP-status fallback.
 * @param {object|null} payload Parsed error response.
 * @param {number} [status] HTTP response status.
 * @param {string} [fallback] Optional caller-supplied fallback.
 * @returns {string} Localized error text.
 */
function apiErrorMessage(payload, status = 0, fallback = '') {
  const i18n = window.BBUI?.components?.i18n;
  const resolvedFallback = fallback || (i18n?.t?.('api.errors.http', { status }) || `HTTP ${status}`);
  return apiMessage(payload, resolvedFallback, { status });
}

window.BBUI.api.message = apiMessage;
window.BBUI.api.errorMessage = apiErrorMessage;

// Global API behavior: if backend reports 401 (expired/invalid session),
// redirect once to /login for all API calls except the login request itself.
(function setupGlobalUnauthorizedRedirect() {
  if (window.BBUI.api._fetch401Wrapped) return;

  const nativeFetch = window.fetch.bind(window);
  let redirectIssued = false;

  function shouldHandleAsApiCall(input) {
    if (typeof input === 'string') return input.startsWith('/api/');
    if (input && typeof input.url === 'string') {
      if (input.url.startsWith('/api/')) return true;
      try {
        return new URL(input.url, window.location.origin).pathname.startsWith('/api/');
      } catch (_) {
        return false;
      }
    }
    return false;
  }

  function isLoginCall(input) {
    const url = typeof input === 'string' ? input : (input && input.url ? input.url : '');
    return String(url).includes('/api/auth/login');
  }

  /**
   * Preserve native fetch behavior while redirecting once on API session expiry.
   * @param {RequestInfo|URL} input Fetch request target.
   * @param {RequestInit} [init] Native fetch options.
   * @returns {Promise<Response>} The original response when fetch succeeds.
   */
  window.fetch = async function bbuiFetchWith401(input, init) {
    const response = await nativeFetch(input, init);
    if (
      response &&
      response.status === 401 &&
      shouldHandleAsApiCall(input) &&
      !isLoginCall(input) &&
      !redirectIssued &&
      window.location.pathname !== '/login'
    ) {
      redirectIssued = true;
      window.location.assign('/login');
    }
    return response;
  };

  window.BBUI.api._fetch401Wrapped = true;
})();
