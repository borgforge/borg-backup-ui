'use strict';

// Phase A bootstrap: keep legacy app.js behavior unchanged, but route startup
// through a dedicated entrypoint so we can migrate page-by-page modules later.
(function bootstrapLegacyApp() {
  window.BBUI = window.BBUI || {};
  window.BBUI.version = 'phase-a';

  function clientLog(payload) {
    try {
      const body = JSON.stringify({
        ts: new Date().toISOString(),
        page: window.location && window.location.pathname ? window.location.pathname : '',
        ua: navigator.userAgent || '',
        ui_version: window.BBUI && window.BBUI.version ? window.BBUI.version : '',
        ...payload,
      });
      if (navigator.sendBeacon) {
        navigator.sendBeacon('/api/client-log', new Blob([body], { type: 'application/json' }));
        return;
      }
      fetch('/api/client-log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        keepalive: true,
      }).catch(() => {});
    } catch (_) {}
  }

  window.addEventListener('error', function onWindowError(e) {
    clientLog({
      type: 'js_error',
      message: String(e && e.message ? e.message : 'window.error'),
      stack: String(e && e.error && e.error.stack ? e.error.stack : ''),
    });
  });
  window.addEventListener('unhandledrejection', function onUnhandledRejection(e) {
    const reason = e && e.reason;
    clientLog({
      type: 'unhandled_rejection',
      message: String(reason && reason.message ? reason.message : reason || 'unhandled rejection'),
      stack: String(reason && reason.stack ? reason.stack : ''),
    });
  });
  const sources = [
    '/ui/js/api/client.js',
    '/ui/js/utils/dom.js',
    '/ui/js/utils/format.js',
    '/ui/js/core/app-core.js',
    '/ui/js/components/theme.js',
    '/ui/js/components/log-viewer.js',
    '/ui/js/components/modal.js',
    '/ui/js/components/schedule-modal.js',
    '/ui/js/components/toast.js',
    '/ui/js/components/app-bindings.js',
    '/ui/js/pages/storage.js',
    '/ui/js/pages/settings.js',
    '/ui/js/pages/help.js',
    '/ui/js/pages/history.js',
    '/ui/js/pages/dashboard.js',
    '/ui/js/pages/jobs.js',
    '/ui/js/pages/wizard.js',
    '/ui/js/pages/restore.js',
    '/ui/js/pages/restore-tests.js',
    '/ui/js/pages/reports.js',
    '/ui/app.js',
  ];

  function loadNext(idx) {
    if (idx >= sources.length) return;
    const script = document.createElement('script');
    script.src = sources[idx];
    script.defer = false;
    script.onload = function () { loadNext(idx + 1); };
    document.head.appendChild(script);
  }
  loadNext(0);
})();
